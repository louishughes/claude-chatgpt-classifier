"""FND-001 acceptance: the package installs and imports in a fresh environment."""

import re
import subprocess
import sys

import knowledge_engine


def test_package_imports_and_has_a_version() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+.*", knowledge_engine.__version__)
    assert knowledge_engine.__version__ != "0.0.0+unknown", "package metadata not installed"


def test_package_is_marked_as_typed() -> None:
    # py.typed tells mypy (and users' type checkers) that our type hints are real.
    from importlib.resources import files

    assert files("knowledge_engine").joinpath("py.typed").is_file()


def test_import_has_no_side_effects_on_stdout() -> None:
    # Importing must not print or touch the filesystem: later layers rely on
    # being able to import the package safely, even next to private data.
    result = subprocess.run(
        [sys.executable, "-c", "import knowledge_engine"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout == ""
    assert result.stderr == ""
