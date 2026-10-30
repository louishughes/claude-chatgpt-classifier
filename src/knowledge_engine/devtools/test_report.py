"""Run every check and write a plain-English HTML report (TEST_EVERYTHING.bat).

``python -m knowledge_engine.devtools.test_report`` runs the same steps as CI
(``devtools.ci``): the everyday checks, then the nightly ones. Each step's
output goes to its own log file, and ``report.html`` gets one line per area:
green or red, what the area proves, and what to do if it's red. The report
then opens in the browser.

It exists so the owner can test the whole project by double-clicking one file
instead of typing commands. It reuses ``ci.CHECKS``, ``ci.NIGHTLY`` and
``ci.clean_environment`` rather than listing the commands again, so "green
here" and "green in CI" can't drift apart: every model credential is removed
and no step can call a paid model.

The report lands in ``workspace/test-report/`` (git-ignored) because the
nightly steps can mention local paths.

Talking points:
    - "Testing the project is one double-click; the result is a web page with
      a green or red line per area and what to do about a red one."
    - "The button runs exactly what CI runs, with the API keys stripped out."
"""

from __future__ import annotations

import argparse
import html
import os
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine.devtools.ci import CHECKS, NIGHTLY, Step, clean_environment

# How many lines of a failed step's output the report shows. The full log is
# linked next to it; the tail is usually where the error message is.
TAIL_LINES = 60


@dataclass(frozen=True)
class Area:
    """What one CI step means, in words for someone who didn't write it."""

    title: str
    proves: str
    if_red: str


# Keyed by the step names in devtools.ci. A step without an entry still runs
# and still shows up; it just gets its bare name (tested, so a new CI step
# can't be left out silently).
AREAS: dict[str, Area] = {
    "lint": Area(
        "Code tidiness",
        "The code has no common mistakes such as unused imports or undefined names.",
        "Ask Claude to fix the lint errors; the log names each file and line.",
    ),
    "format": Area(
        "Code layout",
        "Every file is laid out the standard way (spacing, line length).",
        "Ask Claude to run the formatter. This never changes what the code does.",
    ),
    "types": Area(
        "Type checks",
        "Every function is called with the kind of values it expects.",
        "Ask Claude to fix the mypy errors in the log.",
    ),
    "guard": Area(
        "Privacy guard",
        "Nothing private (raw/, private/, workspace/, ke.toml, .env) is in Git, "
        "and every test fixture is marked synthetic.",
        "Don't commit or push until this is green. Ask Claude what the guard found.",
    ),
    "tests": Area(
        "All automated tests",
        "Thousands of small checks: importing exports, branches, images, repeat "
        "imports, links, notes, search, the web pages and more.",
        "Open the log, copy the lines under FAILED, and give them to Claude.",
    ),
    "gate": Area(
        "Release scorecard",
        "Each quality check (import fidelity, labels, decisions, links, search) "
        "against its threshold, on synthetic chats with a fake model.",
        "Only a FAIL line is a problem; REVIEW and BLOCKED are expected for now. "
        "Give the log to Claude.",
    ),
    "variance": Area(
        "Same answer every time",
        "Importing in a shuffled order and repeating a run gives identical results.",
        "Give the log to Claude: something depends on order or luck.",
    ),
    "e2e": Area(
        "Whole journey",
        "A synthetic export goes import, classify, extract, notes and search, and "
        "every Obsidian link in the notes opens.",
        "Give the log to Claude; it names the first stage that went wrong.",
    ),
}


@dataclass(frozen=True)
class StepResult:
    """What happened when one step ran."""

    name: str
    group: str  # "everyday" or "nightly"
    exit_code: int
    seconds: float
    log_file: Path
    tail: str

    @property
    def passed(self) -> bool:
        """A step passes when its command exits with 0."""
        return self.exit_code == 0


# A runner takes (command, env, log path) and returns the exit code. The real
# one starts a process; tests pass a fake so they don't run the whole suite.
Runner = Callable[[Sequence[str], Mapping[str, str], Path], int]


def run_to_log(command: Sequence[str], env: Mapping[str, str], log_file: Path) -> int:
    """Run ``command``, sending its output to ``log_file`` and the console."""
    with log_file.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(
            list(command),
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        # Copy line by line so the black window shows progress while it runs.
        for line in process.stdout:
            log.write(line)
            print(line, end="", flush=True)
        return process.wait()


def _tail(log_file: Path, lines: int = TAIL_LINES) -> str:
    text = log_file.read_text(encoding="utf-8", errors="replace")
    return "\n".join(text.splitlines()[-lines:])


def run_steps(
    groups: Sequence[tuple[str, Sequence[Step]]],
    environ: Mapping[str, str],
    out_dir: Path,
    runner: Runner | None = None,
) -> list[StepResult]:
    """Run every step of every group; a failure doesn't stop the rest."""
    # Looked up at call time (not as a default argument) so a test can swap it.
    runner = runner or run_to_log
    env = clean_environment(environ)
    # The checks write into a pipe, not the console. On Windows a pipe would
    # use the old cp1252 encoding, and printing a character like "→" would
    # crash a check that's actually fine. UTF-8 mode avoids that.
    env["PYTHONUTF8"] = "1"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for group, steps in groups:
        for step in steps:
            title = AREAS[step.name].title if step.name in AREAS else step.name
            print(f"\n== {title} ({step.name}) ==", flush=True)
            log_file = out_dir / f"{step.name}.log"
            started = time.monotonic()
            code = runner(step.command, env, log_file)
            seconds = time.monotonic() - started
            results.append(StepResult(step.name, group, code, seconds, log_file, _tail(log_file)))
    return results


def _duration(seconds: float) -> str:
    # Round once, first, so 119.7 seconds reads "2m 0s" and never "1m 60s".
    whole = round(seconds)
    if whole < 60:
        return f"{whole}s"
    return f"{whole // 60}m {whole % 60}s"


def render_html(results: Sequence[StepResult], finished_at: datetime) -> str:
    """The report page. Every piece of log text is escaped before it goes in."""
    all_green = all(r.passed for r in results)
    failed = [r for r in results if not r.passed]
    if all_green:
        headline = "Everything passed"
        summary = "Every check is green. The project is in working order."
    else:
        headline = f"{len(failed)} of {len(results)} areas need attention"
        summary = "The red lines below say what each one checks and what to do next."
    rows = []
    for r in results:
        area = AREAS.get(r.name, Area(r.name, "", "Give the log to Claude."))
        status = "PASS" if r.passed else "FAIL"
        advice = "" if r.passed else f'<p class="todo">What to do: {html.escape(area.if_red)}</p>'
        details = ""
        if not r.passed:
            details = (
                "<details><summary>Last lines of the log</summary>"
                f"<pre>{html.escape(r.tail)}</pre></details>"
            )
        rows.append(
            f'<tr class="{status.lower()}">'
            f'<td><span class="badge">{status}</span></td>'
            f"<td><strong>{html.escape(area.title)}</strong>"
            f' <span class="muted">({html.escape(r.name)}, {r.group})</span>'
            f"<p>{html.escape(area.proves)}</p>{advice}{details}</td>"
            f'<td class="num">{_duration(r.seconds)}</td>'
            f'<td><a href="{html.escape(r.log_file.name)}">full log</a></td>'
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test report</title>
<style>
:root {{ --bg: #fbfbfa; --fg: #1f2328; --muted: #656d76; --line: #d8dee4;
  --pass: #1a7f37; --pass-bg: #dafbe1; --fail: #cf222e; --fail-bg: #ffebe9; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #161b22; --fg: #e6edf3; --muted: #8d96a0; --line: #30363d;
    --pass: #3fb950; --pass-bg: #12261e; --fail: #f85149; --fail-bg: #2d1416; }}
}}
body {{ background: var(--bg); color: var(--fg); margin: 0 auto; max-width: 960px;
  padding: 24px 16px; font: 16px/1.5 system-ui, sans-serif; }}
h1 {{ margin: 0 0 4px; }}
.banner {{ border-radius: 8px; padding: 16px; margin: 16px 0;
  background: {"var(--pass-bg)" if all_green else "var(--fail-bg)"};
  border-left: 6px solid {"var(--pass)" if all_green else "var(--fail)"}; }}
table {{ border-collapse: collapse; width: 100%; }}
td {{ border-top: 1px solid var(--line); padding: 12px 8px; vertical-align: top; }}
td p {{ margin: 4px 0 0; }}
.badge {{ font-weight: 700; padding: 2px 8px; border-radius: 4px; }}
.pass .badge {{ color: var(--pass); background: var(--pass-bg); }}
.fail .badge {{ color: var(--fail); background: var(--fail-bg); }}
.todo {{ color: var(--fail); }}
.muted {{ color: var(--muted); font-size: 14px; }}
.num {{ text-align: right; white-space: nowrap; }}
pre {{ overflow-x: auto; font-size: 13px; background: var(--line); padding: 8px; }}
a {{ color: inherit; }}
</style>
</head>
<body>
<h1>Test report</h1>
<p class="muted">Finished {finished_at:%Y-%m-%d %H:%M} UTC. No paid AI was used:
every API key is removed and the AI steps use a fake model.</p>
<div class="banner"><strong>{headline}</strong><br>{summary}</div>
<table>{"".join(rows)}</table>
<p class="muted">Next: try the app by hand with OPEN_DASHBOARD.bat and the checklist
in docs/TESTING.md.</p>
</body>
</html>
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks, write the report, open it; exit 1 if anything failed."""
    parser = argparse.ArgumentParser(prog="python -m knowledge_engine.devtools.test_report")
    parser.add_argument("--quick", action="store_true", help="skip the nightly checks")
    parser.add_argument("--no-browser", action="store_true", help="don't open the report")
    parser.add_argument(
        "--out", type=Path, default=Path("workspace") / "test-report", help="report folder"
    )
    args = parser.parse_args(argv)
    groups: list[tuple[str, Sequence[Step]]] = [("everyday", CHECKS)]
    if not args.quick:
        groups.append(("nightly", NIGHTLY))
    results = run_steps(groups, os.environ, args.out)
    report = args.out / "report.html"
    report.write_text(render_html(results, datetime.now(UTC)), encoding="utf-8")
    print()
    for r in results:
        print(f"{'PASS' if r.passed else 'FAIL'}  {r.name} ({_duration(r.seconds)})")
    print(f"\nReport: {report.resolve()}")
    if not args.no_browser:
        webbrowser.open(report.resolve().as_uri())
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
