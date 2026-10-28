"""OPS-007: the version, the changelog and the installed package agree.

The full clean-machine check needs the package index and runs nightly
(release.yml); this part is free, so it runs on every change.
"""

from __future__ import annotations

from pathlib import Path

from knowledge_engine import __version__
from knowledge_engine.devtools.release_check import changelog_versions, project_version

REPO = Path(__file__).resolve().parents[2]


def test_the_newest_changelog_entry_is_this_version() -> None:
    versions = changelog_versions(REPO)
    assert versions and versions[0] == project_version(REPO)
    assert len(versions) == len(set(versions))  # one entry per release


def test_the_installed_package_reports_the_same_version() -> None:
    assert __version__ == project_version(REPO)
