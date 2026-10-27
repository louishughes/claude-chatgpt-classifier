"""Settings: every switch and limit the engine reads, checked once at start-up.

All configuration lives in one typed, frozen object. That gives three
guarantees the rest of the code relies on. First, anything that leaves the
machine (cloud models, web fetches, transcripts, image analysis) is switched
off unless a setting turns that one capability on (ADR-0007). Second, the
workspace the engine writes to can never sit inside a read-only raw folder,
so a misconfiguration cannot lead to writes into ``raw/``. Third, secrets
such as API keys are masked whenever settings are printed, logged or saved.

Values come from, highest priority first: keyword arguments, an optional
TOML config file (``load_settings(config_file=...)``), environment variables
prefixed ``KE_`` (nested with ``__``, e.g. ``KE_EGRESS__TEXT_LLM=true``),
then the defaults below. API keys are only accepted from environment
variables, never from the config file, because config files tend to get
copied and committed.

Talking points:
    - "Privacy by default is enforced in code: every outbound capability has
      its own switch, and they all ship switched off."
    - "Settings are validated once and then frozen, so nothing can quietly
      flip a switch halfway through a run."
    - "The config refuses a workspace inside the raw data folder, which turns
      'never write to raw/' from a promise into a check."
"""

from __future__ import annotations

import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# A short, stable label such as "louis-personal" (OD-03). It becomes part of
# conversation identity, so it is restricted to characters that are safe in
# IDs and file names and cannot be confused with each other.
AccountNamespace = Annotated[
    str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$", strip_whitespace=True)
]

_MIB = 1024 * 1024


class Capability(StrEnum):
    """Each kind of operation that sends data off this machine.

    The names match ADR-0007. Code that is about to do one of these calls
    ``EgressPolicy.require`` first.
    """

    TEXT_LLM = "text_llm"
    EMBEDDING = "embedding"
    VISION = "vision"
    NETWORK_FETCH = "network_fetch"
    TRANSCRIPT_FETCH = "transcript_fetch"


class EgressDisabledError(PermissionError):
    """Raised when code asks for an outbound capability that is switched off."""

    def __init__(self, capability: Capability) -> None:
        """Build the error with a message that names the setting to change.

        Args:
            capability: The capability that was requested but is disabled.
        """
        self.capability = capability
        super().__init__(
            f"Outbound capability '{capability.value}' is disabled. "
            f"Enable it explicitly with KE_EGRESS__{capability.value.upper()}=true "
            "or [egress] in the config file."
        )


class EgressPolicy(BaseModel):
    """Per-capability on/off switches for anything that leaves the machine.

    Every switch defaults to off. ``vision`` and the fetch switches stay
    separate from ``text_llm`` on purpose: allowing a text model must never
    silently allow sending images or fetching web pages.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    text_llm: bool = False
    embedding: bool = False
    vision: bool = False
    network_fetch: bool = False
    transcript_fetch: bool = False

    def allows(self, capability: Capability) -> bool:
        """Return True if the given capability is switched on.

        Args:
            capability: The outbound capability to check.

        Returns:
            Whether the capability is enabled.
        """
        return bool(getattr(self, capability.value))

    def require(self, capability: Capability) -> None:
        """Stop with an error unless the capability is switched on.

        Call this immediately before any outbound operation.

        Args:
            capability: The outbound capability about to be used.

        Raises:
            EgressDisabledError: If the capability is switched off.
        """
        if not self.allows(capability):
            raise EgressDisabledError(capability)


class RawRoot(BaseModel):
    """One read-only folder of source material, such as ``raw/``.

    Attributes:
        path: The folder. The engine only ever reads from it.
        account_namespace: Which account these conversations belong to
            (OD-03). Needed because the split format carries no account ID.
        source_format: Which adapter reads it; ``auto`` lets the adapter
            probe decide (ING-002).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: Path
    account_namespace: AccountNamespace
    source_format: Literal["auto", "chatgpt-export", "chatgpt-split-v1"] = "auto"


class Limits(BaseModel):
    """Size limits and run budgets. All must be positive or zero as stated.

    Attributes:
        max_source_file_bytes: Largest single JSON/ZIP file the importer will
            open. Protects against reading a huge or corrupt file into memory.
        max_media_file_bytes: Largest single image/attachment that will be
            hashed and stored.
        max_conversations_per_batch: How many conversations one commit group
            holds before a checkpoint (IMP-004).
        max_model_calls_per_run: Hard cap on model calls in one run. Zero
            means no model calls at all.
        max_cost_usd_per_run: Hard spending cap per run. Zero means nothing
            may be spent.
        import_lock_timeout_s: How long an import waits for another import
            into the same workspace to finish (IMP-004).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_source_file_bytes: int = Field(default=2048 * _MIB, gt=0)
    max_media_file_bytes: int = Field(default=512 * _MIB, gt=0)
    max_conversations_per_batch: int = Field(default=50, gt=0, le=10_000)
    max_model_calls_per_run: int = Field(default=0, ge=0)
    max_cost_usd_per_run: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    import_lock_timeout_s: float = Field(default=600.0, ge=0.0, allow_inf_nan=False)


class Settings(BaseSettings):
    """The complete, validated, read-only configuration for one engine run.

    Build it with ``load_settings`` rather than directly, so that the
    optional config file is handled the same way everywhere.

    Attributes:
        workspace_root: Where the engine writes its database, media store
            and generated notes. Git-ignored by default.
        raw_roots: The read-only source folders.
        media_storage_mode: ``reference`` keeps images in place and checks
            their hash on each import; ``copy`` copies them into the
            workspace (OD-02).
        egress: Outbound capability switches, all off by default.
        limits: Size limits and run budgets.
        anthropic_api_key: Read from ``KE_ANTHROPIC_API_KEY`` or
            ``ANTHROPIC_API_KEY``. Masked whenever printed.
    """

    model_config = SettingsConfigDict(
        env_prefix="KE_",
        env_nested_delimiter="__",
        frozen=True,
        extra="forbid",
    )

    workspace_root: Path = Path("workspace")
    raw_roots: tuple[RawRoot, ...] = ()
    media_storage_mode: Literal["reference", "copy"] = "reference"
    egress: EgressPolicy = EgressPolicy()
    limits: Limits = Limits()
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("KE_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )

    @model_validator(mode="after")
    def _workspace_outside_raw_roots(self) -> Settings:
        """Reject a workspace inside (or equal to) any raw root, and vice versa.

        Paths are resolved first so ``raw/../raw/out`` cannot slip through.
        """
        workspace = self.workspace_root.resolve()
        for root in self.raw_roots:
            raw = root.path.resolve()
            if workspace == raw or workspace.is_relative_to(raw) or raw.is_relative_to(workspace):
                raise ValueError(
                    "workspace_root and a raw root overlap; raw folders are read-only, "
                    "so the workspace must live outside them"
                )
        return self

    @model_validator(mode="after")
    def _raw_roots_are_distinct(self) -> Settings:
        """Reject the same folder listed twice, which would import it twice."""
        resolved = [root.path.resolve() for root in self.raw_roots]
        if len(resolved) != len(set(resolved)):
            raise ValueError("the same raw root is listed more than once")
        return self


_SECRET_FIELDS = {"anthropic_api_key"}


def load_settings(config_file: Path | None = None, **overrides: Any) -> Settings:
    """Build the settings from a config file, environment variables and overrides.

    Args:
        config_file: Optional TOML file. Its tables mirror the fields, e.g.
            ``[egress]`` and ``[[raw_roots]]``.
        **overrides: Values that win over everything else (used by tests and
            command-line flags).

    Returns:
        The validated, frozen settings.

    Raises:
        FileNotFoundError: If ``config_file`` is given but does not exist.
        ValueError: If the config file contains a secret.
        pydantic.ValidationError: If any value is invalid. The message names
            the field; secrets are never echoed.
    """
    file_values: dict[str, Any] = {}
    if config_file is not None:
        with config_file.open("rb") as handle:
            file_values = tomllib.load(handle)
        leaked = _SECRET_FIELDS & file_values.keys()
        if leaked:
            # Name the key, never the value.
            raise ValueError(
                f"{config_file.name} contains {sorted(leaked)}; secrets must come from "
                "environment variables, not from a config file"
            )
    # Keyword arguments take priority over environment variables in
    # pydantic-settings, so merging file values in here puts them above env.
    return Settings(**{**file_values, **overrides})
