"""Clean-machine release check: install, import, upgrade, restore (OPS-007).

``python -m knowledge_engine.devtools.release_check`` (from the repository
root) does what a person does with a new release on a fresh computer:

1. builds the wheel, the file a release ships;
2. makes a brand-new virtual environment and installs only that wheel
   (its dependencies come from the package index, nothing from this repo);
3. checks ``ke --version`` matches ``pyproject.toml`` and ``CHANGELOG.md``;
4. imports a generated synthetic export into a new workspace;
5. steps the schema back one migration, which is the database the previous
   release left on disk, and runs ``ke db upgrade``: it must back up first
   and end at the newest schema;
6. verifies that backup and restores it into an empty folder: the restored
   copy must be the pre-upgrade database (the rollback path).

Everything happens in a temporary folder that is deleted afterwards. It
needs the network for the package index, so it runs in the nightly CI job,
not with every test run. No model is called.

Talking points:
    - "Every night CI installs the release the way a stranger would, on a
      clean machine, and proves upgrade and rollback both work."
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from knowledge_engine.devtools.ci import clean_environment


class ReleaseCheckError(RuntimeError):
    """A step of the release check failed (the message says which)."""


def _run(*command: str | Path, env: dict[str, str]) -> str:
    done = subprocess.run(
        [str(c) for c in command], env=env, capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise ReleaseCheckError(f"{Path(str(command[0])).name} failed:\n{done.stderr[-2000:]}")
    return done.stdout


def _ke(ke: Path, *args: str | Path, env: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(_run(ke, "--json", *args, env=env))
    return result


def project_version(repo: Path) -> str:
    """The version in ``pyproject.toml``."""
    data = tomllib.loads((repo / "pyproject.toml").read_text(encoding="utf-8"))
    version: str = data["project"]["version"]
    return version


def changelog_versions(repo: Path) -> list[str]:
    """Versions with a ``## [x.y.z]`` heading in ``CHANGELOG.md``, newest first."""
    text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    return re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\]", text)


def check(repo: Path, work: Path) -> list[str]:
    """Run every step in ``work``; return one line per passed step.

    Raises:
        ReleaseCheckError: The first step that failed.
    """
    done: list[str] = []
    version = project_version(repo)
    if not changelog_versions(repo) or changelog_versions(repo)[0] != version:
        raise ReleaseCheckError(f"CHANGELOG.md's newest entry is not {version}")
    done.append(f"changelog: newest entry is {version}")

    env = clean_environment(os.environ)
    dist = work / "dist"
    _run(sys.executable, "-m", "pip", "wheel", repo, "--no-deps", "-q", "-w", dist, env=env)
    [wheel] = sorted(dist.glob("knowledge_engine-*.whl"))
    done.append(f"build: {wheel.name}")

    venv = work / "venv"
    _run(sys.executable, "-m", "venv", venv, env=env)
    bin_dir = venv / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    _run(python, "-m", "pip", "install", "-q", wheel, env=env)
    ke = bin_dir / ("ke.exe" if os.name == "nt" else "ke")
    shown = _run(ke, "--version", env=env).split()[-1]
    if shown != version:
        raise ReleaseCheckError(f"ke --version says {shown}, pyproject says {version}")
    done.append(f"install: fresh venv, ke {shown}")

    # The installed package writes the synthetic export: nothing from the repo.
    source = work / "source"
    script = (
        "import sys; from pathlib import Path; "
        "from knowledge_engine.evaluation.synthetic import write_generated; "
        "print(write_generated(Path(sys.argv[1]), 5, 1) / 'export')"
    )
    export = _run(python, "-c", script, source, env=env).strip()
    env = {**env, "KE_WORKSPACE_ROOT": str(work / "ws")}
    imported = _ke(ke, "import", export, env=env)
    done.append(f"import: {imported['data']['conversations']['new']} conversations")

    step_back = (
        "import sys; from pathlib import Path; from alembic.script import ScriptDirectory; "
        "from knowledge_engine.infrastructure.db import create_sqlite_engine; "
        "from knowledge_engine.infrastructure.migrations import "
        "alembic_config, downgrade_to, head_revision; "
        "down = ScriptDirectory.from_config(alembic_config())"
        ".get_revision(head_revision()).down_revision; "
        "engine = create_sqlite_engine(Path(sys.argv[1])); downgrade_to(engine, down); print(down)"
    )
    previous = _run(python, "-c", step_back, work / "ws" / "knowledge.db", env=env).strip()
    upgraded = _ke(ke, "db", "upgrade", env=env)["data"]
    if not (upgraded["changed"] and upgraded["before"] == previous and upgraded["backup"]):
        raise ReleaseCheckError(f"db upgrade did not back up and migrate: {upgraded}")
    done.append(f"upgrade: {previous} -> {upgraded['after']}, backup taken first")

    folder = work / "ws-backups" / upgraded["backup"]
    if not _ke(ke, "backup", "verify", folder, env=env)["data"]["ok"]:
        raise ReleaseCheckError("the pre-upgrade backup does not verify")
    restored = _ke(ke, "backup", "restore", folder, "--to", work / "rolled-back", env=env)
    if not restored["data"]["ok"]:
        raise ReleaseCheckError("restoring the pre-upgrade backup did not check out")
    env = {**env, "KE_WORKSPACE_ROOT": str(work / "rolled-back")}
    revision = _ke(ke, "status", env=env)["data"]["database"]["revision"]
    if revision != previous:
        raise ReleaseCheckError(f"the restored database is at {revision}, not {previous}")
    done.append(f"rollback: backup verified and restored at {previous}")
    return done


def main() -> int:
    """Run the check in a temporary folder; exit 1 on the first failure."""
    repo = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="ke-release-") as temporary:
        try:
            for line in check(repo, Path(temporary)):
                print(f"ok   {line}", flush=True)
        except ReleaseCheckError as error:
            print(f"FAIL {error}", flush=True)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
