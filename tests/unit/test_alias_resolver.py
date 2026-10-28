"""TAX-003: aliases map to canonical IDs; collisions are flagged, never guessed."""

from __future__ import annotations

from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.registry import (
    Dimension,
    SnapshotProject,
    SnapshotTerm,
    TaxonomySnapshot,
)

UNREAL = "term_unreal"
UNITY = "term_unity"
GAMEDEV = "term_gamedev"


def _snapshot() -> TaxonomySnapshot:
    def term(term_id: str, dimension: str, label: str, *aliases: str) -> SnapshotTerm:
        return SnapshotTerm(term_id, dimension, label, None, None, (label, *aliases))

    return TaxonomySnapshot(
        version="tax-test",
        content_sha256="0" * 64,
        terms=(
            term(UNREAL, "topic", "Unreal Engine", "UE5", "UE", "Unreal", "Unreal Engine 5"),
            term(UNITY, "topic", "Unity"),
            term(GAMEDEV, "domain", "Game development", "gamedev"),
            # The same spelling in another dimension: a collision to flag.
            term("term_unreal_style", "purpose", "Unreal"),
        ),
        projects=(SnapshotProject("proj_ke", "Knowledge Engine", ("Knowledge Engine", "KE")),),
    )


def test_ue5_and_unreal_spellings_map_to_one_id() -> None:
    resolver = AliasResolver(_snapshot())
    for text in ("UE5", "ue5", "Unreal Engine 5", "unreal-engine  5", "UNREAL ENGINE"):
        result = resolver.resolve(text, scope=Dimension.TOPIC)
        assert result.status is MatchStatus.MATCHED, text
        assert result.target_id == UNREAL


def test_shared_spelling_is_ambiguous_until_scoped() -> None:
    resolver = AliasResolver(_snapshot())
    unscoped = resolver.resolve("Unreal")
    assert unscoped.status is MatchStatus.AMBIGUOUS
    assert unscoped.target_id is None
    assert {c.target_id for c in unscoped.candidates} == {UNREAL, "term_unreal_style"}
    assert resolver.resolve("Unreal", scope=Dimension.TOPIC).target_id == UNREAL
    assert resolver.resolve("Unreal", scope="purpose").target_id == "term_unreal_style"


def test_collisions_lists_every_shared_spelling() -> None:
    collisions = AliasResolver(_snapshot()).collisions()
    assert list(collisions) == ["unreal"]


def test_unknown_text_is_unmatched() -> None:
    resolver = AliasResolver(_snapshot())
    assert resolver.resolve("Godot").status is MatchStatus.UNMATCHED
    assert resolver.resolve("UE5", scope=Dimension.DOMAIN).status is MatchStatus.UNMATCHED
    assert resolver.resolve("!!!").status is MatchStatus.UNMATCHED


def test_projects_resolve_in_their_own_scope() -> None:
    resolver = AliasResolver(_snapshot())
    assert resolver.resolve("ke", scope="project").target_id == "proj_ke"


def test_find_matches_whole_words_only_with_exact_spans() -> None:
    resolver = AliasResolver(_snapshot())
    text = "Synthetic: the UE queue in Unreal Engine 5 beat Unity; QUEUE and unity3d don't count."
    mentions = resolver.find(text, scope=Dimension.TOPIC)
    found = [(text[m.span.start : m.span.end], m.resolution.target_id) for m in mentions]
    # "UE" inside "queue"/"QUEUE" and "unity" inside "unity3d" never match;
    # the longest alias wins, so "Unreal Engine 5" is one mention, not "Unreal".
    assert found == [("UE", UNREAL), ("Unreal Engine 5", UNREAL), ("Unity", UNITY)]


def test_find_reports_ambiguous_mentions_without_choosing() -> None:
    resolver = AliasResolver(_snapshot())
    (mention,) = resolver.find("Synthetic: something Unreal happened.")
    assert mention.resolution.status is MatchStatus.AMBIGUOUS
