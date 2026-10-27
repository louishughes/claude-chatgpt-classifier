"""FND-002 acceptance: config rejects invalid limits and never reveals secrets."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from knowledge_engine.settings import (
    Capability,
    EgressDisabledError,
    EgressPolicy,
    Settings,
    load_settings,
)

FAKE_KEY = "sk-ant-SYNTHETIC-test-key-0123456789"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests must not pick up a real key or switches from the developer's shell.
    import os

    for name in list(os.environ):
        if name.startswith("KE_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)


# ---------------------------------------------------------------- defaults


def test_every_outbound_capability_is_off_by_default() -> None:
    settings = load_settings()
    for capability in Capability:
        assert not settings.egress.allows(capability)
        with pytest.raises(EgressDisabledError, match=capability.value):
            settings.egress.require(capability)


def test_default_budgets_allow_no_model_calls_or_spend() -> None:
    limits = load_settings().limits
    assert limits.max_model_calls_per_run == 0
    assert limits.max_cost_usd_per_run == 0.0


def test_enabling_text_llm_does_not_enable_vision_or_fetching() -> None:
    policy = EgressPolicy(text_llm=True)
    policy.require(Capability.TEXT_LLM)
    for capability in (Capability.VISION, Capability.NETWORK_FETCH, Capability.TRANSCRIPT_FETCH):
        assert not policy.allows(capability)


def test_settings_are_frozen() -> None:
    settings = load_settings()
    with pytest.raises(ValidationError):
        settings.media_storage_mode = "copy"


# ---------------------------------------------------------------- invalid limits


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_source_file_bytes", 0),
        ("max_source_file_bytes", -1),
        ("max_media_file_bytes", 0),
        ("max_conversations_per_batch", 0),
        ("max_conversations_per_batch", 10_001),
        ("max_model_calls_per_run", -1),
        ("max_cost_usd_per_run", -0.01),
        ("max_cost_usd_per_run", float("inf")),
        ("max_cost_usd_per_run", float("nan")),
        ("max_source_file_bytes", "lots"),
    ],
)
def test_invalid_limits_are_rejected(field: str, value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        load_settings(limits={field: value})


def test_unknown_setting_is_rejected_not_ignored() -> None:
    # A typo such as "egres" must fail loudly rather than leave egress at defaults.
    with pytest.raises(ValidationError):
        load_settings(egres={"text_llm": True})
    with pytest.raises(ValidationError):
        load_settings(egress={"text_lm": True})


def test_invalid_storage_mode_is_rejected() -> None:
    with pytest.raises(ValidationError):
        load_settings(media_storage_mode="move")


@pytest.mark.parametrize("label", ["", "Louis", "louis personal", "-x", "../up", "a" * 64])
def test_invalid_account_namespace_is_rejected(tmp_path: Path, label: str) -> None:
    with pytest.raises(ValidationError):
        load_settings(raw_roots=[{"path": tmp_path / "raw", "account_namespace": label}])


# ---------------------------------------------------------------- raw/ protection


def test_workspace_inside_raw_root_is_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    with pytest.raises(ValidationError, match="overlap"):
        load_settings(
            workspace_root=raw / "out",
            raw_roots=[{"path": raw, "account_namespace": "fixture"}],
        )


def test_workspace_equal_to_raw_root_via_dotdot_is_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    with pytest.raises(ValidationError, match="overlap"):
        load_settings(
            workspace_root=tmp_path / "other" / ".." / "raw",
            raw_roots=[{"path": raw, "account_namespace": "fixture"}],
        )


def test_raw_root_inside_workspace_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="overlap"):
        load_settings(
            workspace_root=tmp_path,
            raw_roots=[{"path": tmp_path / "raw", "account_namespace": "fixture"}],
        )


def test_duplicate_raw_root_is_rejected(tmp_path: Path) -> None:
    root = {"path": tmp_path / "raw", "account_namespace": "fixture"}
    with pytest.raises(ValidationError, match="more than once"):
        load_settings(workspace_root=tmp_path / "ws", raw_roots=[root, root])


def test_sibling_workspace_and_raw_root_are_accepted(tmp_path: Path) -> None:
    settings = load_settings(
        workspace_root=tmp_path / "workspace",
        raw_roots=[{"path": tmp_path / "raw", "account_namespace": "louis-personal"}],
    )
    assert settings.raw_roots[0].account_namespace == "louis-personal"
    assert settings.raw_roots[0].source_format == "auto"


# ---------------------------------------------------------------- secrets


def test_api_key_from_env_is_masked_everywhere(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    settings = load_settings()
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == FAKE_KEY
    for rendering in (
        repr(settings),
        str(settings),
        settings.model_dump_json(),
        str(settings.model_dump()),
    ):
        assert FAKE_KEY not in rendering


def test_prefixed_env_key_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KE_ANTHROPIC_API_KEY", FAKE_KEY)
    key = load_settings().anthropic_api_key
    assert key is not None and key.get_secret_value() == FAKE_KEY


def test_validation_error_does_not_echo_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_KEY)
    with pytest.raises(ValidationError) as excinfo:
        load_settings(limits={"max_source_file_bytes": -1})
    assert FAKE_KEY not in str(excinfo.value)


def test_secret_in_config_file_is_refused_without_echoing_it(tmp_path: Path) -> None:
    config = tmp_path / "ke.toml"
    config.write_text(f'anthropic_api_key = "{FAKE_KEY}"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="environment variables") as excinfo:
        load_settings(config_file=config)
    assert FAKE_KEY not in str(excinfo.value)


# ---------------------------------------------------------------- sources and priority


def test_env_switch_enables_one_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    egress = load_settings().egress
    assert egress.allows(Capability.TEXT_LLM)
    assert not egress.allows(Capability.VISION)


def test_config_file_is_read(tmp_path: Path) -> None:
    config = tmp_path / "ke.toml"
    config.write_text(
        f"""
workspace_root = "{(tmp_path / "ws").as_posix()}"
media_storage_mode = "copy"

[egress]
text_llm = true

[limits]
max_conversations_per_batch = 100

[[raw_roots]]
path = "{(tmp_path / "raw").as_posix()}"
account_namespace = "louis-personal"
source_format = "chatgpt-split-v1"
""",
        encoding="utf-8",
    )
    settings = load_settings(config_file=config)
    assert settings.media_storage_mode == "copy"
    assert settings.egress.text_llm is True
    assert settings.limits.max_conversations_per_batch == 100
    assert settings.raw_roots[0].source_format == "chatgpt-split-v1"


def test_priority_is_overrides_then_file_then_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_MEDIA_STORAGE_MODE", "copy")
    assert load_settings().media_storage_mode == "copy"

    config = tmp_path / "ke.toml"
    config.write_text('media_storage_mode = "reference"\n', encoding="utf-8")
    assert load_settings(config_file=config).media_storage_mode == "reference"
    assert load_settings(config_file=config, media_storage_mode="copy").media_storage_mode == "copy"


def test_missing_config_file_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(config_file=tmp_path / "absent.toml")


def test_settings_class_has_no_secret_defaults() -> None:
    assert Settings.model_fields["anthropic_api_key"].default is None
