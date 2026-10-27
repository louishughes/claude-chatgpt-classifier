"""Knowledge Engine: turns exported AI conversations into searchable, traceable knowledge.

This is the top-level package. It imports source conversations and images
read-only, keeps exactly where every piece of information came from
(provenance), and later builds classified, evidence-backed notes on top.
Subpackages are added ticket by ticket; see docs/plans/IMPLEMENTATION_PLAN.md
for the target layout and the rules about which layer may import which.

Talking points:
    - "I used a src/ layout so tests run against the installed package, the
      same way a user would get it, not against loose files."
    - "Every subpackage arrives with the ticket that needs it, so the
      structure never runs ahead of the code."
"""

from importlib.metadata import PackageNotFoundError, version

try:
    # Read the version from the installed package metadata, so the number
    # lives in exactly one place: pyproject.toml.
    __version__ = version("knowledge-engine")
except PackageNotFoundError:  # pragma: no cover - only when run from an uninstalled checkout
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
