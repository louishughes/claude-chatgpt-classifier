"""Unit and batch tests for the spike, using synthetic data and the fake provider."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import make_conversation
from loader import clip_text, load_conversation, sample_conversations
from providers import FakeProvider, FatalError
from report import consistency, run_stats
from runner import CostMeter, label_one, load_records, run_once
from schema import ConversationLabel
import spike


def no_sleep(_):
    pass


def conv_from(tmp_path, data):
    p = tmp_path / "c.json"
    p.write_text(json.dumps(data))
    return load_conversation(p)


# --- loader -----------------------------------------------------------------

def test_follows_active_branch_and_drops_hidden_parts(tmp_path):
    conv = conv_from(tmp_path, make_conversation("x", n_exchanges=2, branch=True))
    text = conv.full_text()
    assert "ALTERNATIVE BRANCH TEXT" not in text   # unselected regeneration
    assert "secret reasoning" not in text          # thoughts
    assert "system prompt" not in text             # system role
    assert "hidden custom instructions" not in text
    assert [t.role for t in conv.turns] == ["user", "assistant", "user", "assistant"]
    assert conv.turns[0].image_refs == 1           # counted, not sent
    assert conv.branch_points == 1


def test_non_conversation_json_is_skipped(raw_dir):
    root = raw_dir(3)
    convs, skipped = sample_conversations(root, 10, seed=1)
    assert len(convs) == 3
    assert skipped["not_a_conversation"] == 1


def test_sample_is_reproducible_and_nested(raw_dir):
    root = raw_dir(20)
    small, _ = sample_conversations(root, 5, seed=7)
    again, _ = sample_conversations(root, 5, seed=7)
    big, _ = sample_conversations(root, 10, seed=7)
    ids = lambda cs: [c.conversation_id for c in cs]
    assert ids(small) == ids(again)
    assert ids(big)[:5] == ids(small)


def test_clip_keeps_start_and_end():
    text = "START" + "x" * 1000 + "END"
    clipped, was = clip_text(text, 200)
    assert was and clipped.startswith("START") and clipped.endswith("END")
    assert clip_text("short", 200) == ("short", False)


# --- schema -----------------------------------------------------------------

def valid_label(**over):
    base = dict(primary_domain="games", secondary_domains=[], purpose="build_or_fix",
                project_candidates=[], topics=["Unity"], knowledge_types=["how_to"],
                outputs=["code"], summary="s", decisions=[], confidence=0.5)
    base.update(over)
    return base


def decision(**over):
    base = dict(statement="s", proposed_by="assistant", state="accepted",
                evidence_quote="q", evidence_speaker="user")
    base.update(over)
    return base


def test_schema_accepts_valid_and_normalises_lists():
    label = ConversationLabel(**valid_label(topics=["Unity", "unity "], outputs=["code", "code"]))
    assert label.topics == ["unity"] and [o.value for o in label.outputs] == ["code"]


@pytest.mark.parametrize("bad", [
    {"primary_domain": "not_a_domain"},
    {"purpose": "procrastinate"},
    {"topics": [f"t{i}" for i in range(6)]},
    {"topics": []},
    {"summary": "x" * 301},
    {"confidence": 1.5},
    {"secondary_domains": ["games"]},                      # repeats the primary
    {"secondary_domains": ["other", "home_and_life", "money_and_admin", "ai_and_automation"]},
    {"outputs": ["none", "code"]},
    {"knowledge_types": []},
    {"project_candidates": ["a", "b", "c", "d"]},
    {"decisions": [decision(state="approved")]},
    {"decisions": [decision(proposed_by="narrator")]},
])
def test_schema_rejects_contract_breaks(bad):
    with pytest.raises(ValidationError):
        ConversationLabel(**valid_label(**bad))


# --- runner: one conversation ----------------------------------------------

@pytest.fixture
def conv(tmp_path):
    return conv_from(tmp_path, make_conversation("conv-A"))


def test_transient_errors_retry_then_succeed(conv):
    p = FakeProvider({"conv-A": ["timeout", "rate_limit"]})
    rec = label_one(conv, p, CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "ok" and rec.calls == 3
    assert rec.transient_errors == {"timeout": 1, "rate_limit": 1}


def test_gives_up_after_three_transient_failures(conv):
    p = FakeProvider({"conv-A": ["timeout"] * 5})
    rec = label_one(conv, p, CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "failed" and rec.calls == 3


def test_one_schema_repair_then_ok(conv):
    rec = label_one(conv, FakeProvider({"conv-A": ["schema"]}), CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "ok" and rec.repaired and rec.schema_failures == 1


def test_second_schema_failure_goes_to_review(conv):
    rec = label_one(conv, FakeProvider({"conv-A": ["schema", "schema"]}), CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "review_required" and rec.calls == 2


def test_refusal_is_recorded(conv):
    rec = label_one(conv, FakeProvider({"conv-A": ["refusal"]}), CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "refusal"


def test_cost_cap_stops_before_calling(conv):
    p = FakeProvider()
    rec = label_one(conv, p, CostMeter(cap_usd=1, already_spent=1), 24000, sleep=no_sleep)
    assert rec.status == "skipped_cost_cap" and p.calls == 0


def test_quote_check_counts_only_real_quotes(conv):
    rec = label_one(conv, FakeProvider(), CostMeter(10), 24000, sleep=no_sleep)
    assert rec.decisions_total == rec.decisions_quote_found == 1


def test_quote_must_come_from_the_stated_speaker(conv):
    from runner import Record, check_quotes
    user_words = conv.turns[0].text[:25]
    assistant_words = conv.turns[1].text[:8]
    rec = Record("x", "f", "ok", "fake", label=valid_label(decisions=[
        decision(evidence_quote=user_words, evidence_speaker="user"),          # real, right speaker
        decision(evidence_quote=user_words, evidence_speaker="assistant"),     # real words, wrong speaker
        decision(evidence_quote="words nobody wrote", evidence_speaker="user"),
        decision(evidence_quote=assistant_words, evidence_speaker="assistant", state="accepted"),
    ]))
    check_quotes(rec, conv)
    assert rec.decisions_total == 4
    assert rec.decisions_quote_found == 2
    assert rec.decisions_assistant_accepted_unquoted == 2


# --- runner: batches ---------------------------------------------------------

@pytest.mark.parametrize("size", [50, 100])
def test_batch_with_injected_failures_accounts_for_every_chat(raw_dir, tmp_path, size):
    """The 50/100 batch gate on synthetic data: every chat ends in a known state."""
    convs, _ = sample_conversations(raw_dir(size), size, seed=3)
    plan = {"conv-001": ["timeout", "timeout", "timeout"],   # gives up
            "conv-002": ["schema"],                          # repaired
            "conv-003": ["schema", "schema"],                # review
            "conv-004": ["refusal"],
            "conv-005": ["server", "connection"]}            # recovers
    out = tmp_path / "out"
    out.mkdir()
    runs = []
    for i in (1, 2):
        runs.append(run_once(convs, FakeProvider(plan), out / f"run-{i}.jsonl", CostMeter(10),
                             24000, workers=8, backoff_s=0, progress=lambda *_: None))
    stats = run_stats(runs[0])
    assert stats["conversations"] == size
    assert stats["status_counts"] == {"ok": size - 3, "failed": 1, "review_required": 1, "refusal": 1}
    assert stats["repaired_ok"] == 1
    # The fake provider is deterministic, so two runs must agree perfectly.
    c = consistency(runs)[0]
    assert c["primary_domain_agree_pct"] == c["purpose_agree_pct"] == 100.0
    assert c["topics_jaccard"] == c["project_names_jaccard"] == 1.0


def test_resume_skips_finished_and_retries_failed(raw_dir, tmp_path):
    convs, _ = sample_conversations(raw_dir(10), 10, seed=1)
    out = tmp_path / "run-1.jsonl"
    first = FakeProvider({"conv-001": ["timeout"] * 3})
    run_once(convs, first, out, CostMeter(10), 24000, backoff_s=0, progress=lambda *_: None)
    second = FakeProvider()
    run_once(convs, second, out, CostMeter(10), 24000, backoff_s=0, progress=lambda *_: None)
    assert second.calls == 1   # only the chat that failed last time
    assert all(r["status"] == "ok" for r in load_records(out).values())


def test_fatal_error_stops_the_run(raw_dir, tmp_path):
    convs, _ = sample_conversations(raw_dir(5), 5, seed=1)
    with pytest.raises(FatalError):
        run_once(convs, FakeProvider({"conv-": ["fatal"] * 99}), tmp_path / "r.jsonl",
                 CostMeter(10), 24000, workers=1, progress=lambda *_: None)


# --- command line ------------------------------------------------------------

def tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_cli_fake_run_writes_report_and_leaves_raw_untouched(raw_dir, tmp_path):
    root = raw_dir(12)
    before = tree_hash(root)
    out = tmp_path / "out"
    code = spike.main(["--raw-dir", str(root), "--out", str(out), "--sample", "10",
                       "--runs", "2", "--provider", "fake", "--workers", "3"])
    assert code == 0
    assert tree_hash(root) == before
    report = json.loads((out / "report.json").read_text())
    assert report["consistency"][0]["primary_domain_agree_pct"] == 100.0
    assert report["consistency"][0]["orders_differ"] is True   # runs used different orders
    assert "Run-to-run consistency" in (out / "report.md").read_text()


def test_cli_dry_run_makes_no_files(raw_dir, tmp_path):
    out = tmp_path / "out"
    assert spike.main(["--raw-dir", str(raw_dir(5)), "--out", str(out), "--dry-run"]) == 0
    assert not out.exists()


def test_cli_refuses_output_inside_a_git_repo(raw_dir, tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    code = spike.main(["--raw-dir", str(raw_dir(3)), "--out", str(repo / "out"), "--provider", "fake"])
    assert code == 2


# --- gold set ----------------------------------------------------------------

def test_gold_template_then_accuracy_in_report(raw_dir, tmp_path):
    import csv
    root = raw_dir(12)
    out = tmp_path / "out"
    base = ["--raw-dir", str(root), "--out", str(out), "--sample", "10", "--provider", "fake"]
    assert spike.main(base + ["--gold-template", "4"]) == 0
    rows = list(csv.DictReader((out / "gold_template.csv").open()))
    assert len(rows) == 4 and rows[0]["title"] == "synthetic" and not (out / "run-1.jsonl").exists()

    # Label two chats with the fake model's own answer and two with a wrong one.
    assert spike.main(base + ["--runs", "1"]) == 0
    model = load_records(out / "run-1.jsonl")
    for i, row in enumerate(rows):
        label = model[row["conversation_id"]]["label"]
        right = label["primary_domain"]
        row["primary_domain"] = right if i < 2 else ("games" if right != "games" else "other")
        row["purpose"] = label["purpose"]
    with (out / "gold.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    assert spike.main(base + ["--runs", "1", "--gold", str(out / "gold.csv")]) == 0
    report = json.loads((out / "report.json").read_text())
    assert report["gold"][0]["scored"] == 4
    assert report["gold"][0]["primary_domain_accuracy_pct"] == 50.0
    assert report["gold"][0]["purpose_accuracy_pct"] == 100.0
    assert "Accuracy vs your hand labels" in (out / "report.md").read_text()


def test_gold_rejects_unknown_category(tmp_path):
    from gold import load_gold
    p = tmp_path / "g.csv"
    p.write_text("conversation_id,primary_domain,purpose\nx,gamez,brainstorm\n")
    with pytest.raises(ValueError, match="gamez"):
        load_gold(p)
    p.write_text("conversation_id,primary_domain,purpose\nx,games,dither\n")
    with pytest.raises(ValueError, match="dither"):
        load_gold(p)


# --- processing order ----------------------------------------------------------

def test_labels_do_not_depend_on_processing_order(raw_dir, tmp_path):
    """Same chats, three different orders: identical labels.

    Guards against the old failure where a vocabulary grew during the run, so
    chat 800 was labelled against different words from chat 8. Each call here
    is independent; this test fails if anyone adds shared state between calls.
    """
    convs, _ = sample_conversations(raw_dir(30), 30, seed=1)
    labels = []
    for order in (1, 2, 3):
        recs = run_once(convs, FakeProvider(), tmp_path / f"o{order}.jsonl", CostMeter(10), 24000,
                        workers=1, progress=lambda *_: None, order_seed=order)
        labels.append({cid: r["label"] for cid, r in recs.items()})
        positions = [recs[c.conversation_id]["position"] for c in convs]
        assert sorted(positions) == list(range(30))
    assert labels[0] == labels[1] == labels[2]


def test_semantic_answers_are_never_retried(conv):
    """A well-formed answer is accepted once, even if it may be wrong: no retry loop."""
    p = FakeProvider()
    rec = label_one(conv, p, CostMeter(10), 24000, sleep=no_sleep)
    assert rec.status == "ok" and p.calls == 1


# --- gold set selection ------------------------------------------------------

def test_gold_pick_is_varied_and_reproducible(raw_dir):
    from gold import _size, pick_diverse
    convs, _ = sample_conversations(raw_dir(40), 40, seed=2)
    a = pick_diverse(convs, 10, seed=5)
    assert [c.conversation_id for c in a] == [c.conversation_id for c in pick_diverse(convs, 10, seed=5)]
    assert len({c.conversation_id for c in a}) == 10
    groups_all = {(_size(c), c.image_refs > 0, c.branch_points > 0) for c in convs}
    groups_picked = {(_size(c), c.image_refs > 0, c.branch_points > 0) for c in a}
    assert groups_picked == groups_all          # every shape of chat is represented
    assert len(pick_diverse(convs, 100, seed=5)) == 40


def test_gold_sheet_has_context_and_blank_labels(raw_dir, tmp_path):
    import csv
    out = tmp_path / "out"
    assert spike.main(["--raw-dir", str(raw_dir(12)), "--out", str(out), "--sample", "10",
                       "--provider", "fake", "--gold-template", "5"]) == 0
    rows = list(csv.DictReader((out / "gold_template.csv").open()))
    assert rows[0]["first_user_message"].startswith("conv-") and rows[0]["turns"]
    assert all(not r["primary_domain"] and not r["purpose"] for r in rows)   # never pre-filled
    text = (out / "gold_instructions.txt").read_text()
    assert "software_development" in text and "brainstorm" in text


def test_report_fingerprints_the_gold_file(raw_dir, tmp_path):
    import csv
    root, out = raw_dir(6), tmp_path / "out"
    base = ["--raw-dir", str(root), "--out", str(out), "--sample", "5", "--provider", "fake", "--runs", "1"]
    spike.main(base + ["--gold-template", "2"])
    rows = list(csv.DictReader((out / "gold_template.csv").open()))
    for r in rows:
        r["primary_domain"], r["purpose"] = "games", "brainstorm"
    gold = out / "gold.csv"
    with gold.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(rows)
    spike.main(base + ["--gold", str(gold)])
    first = json.loads((out / "report.json").read_text())["meta"]["gold_file_sha256"]
    gold.write_text(gold.read_text().replace("brainstorm", "build_or_fix"))
    spike.main(base + ["--gold", str(gold)])
    second = json.loads((out / "report.json").read_text())["meta"]["gold_file_sha256"]
    assert first != second and len(first) == 16


def test_cli_allows_a_git_ignored_folder_inside_the_repo(raw_dir, tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".gitignore").write_text("private/\n")
    common = ["--raw-dir", str(raw_dir(3)), "--provider", "fake", "--runs", "1"]
    assert spike.main(common + ["--out", str(repo / "private" / "spike-out")]) == 0
    assert (repo / "private" / "spike-out" / "report.md").exists()
    assert spike.main(common + ["--out", str(repo / "results")]) == 2   # not ignored: refused
