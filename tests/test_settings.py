import pytest

from invoice_processing.settings import ConfigurationError, LiveSettings, load_live_settings

SENTINEL = "sk-SENTINEL-123"
GOOD = {"XAI_API_KEY": SENTINEL, "XAI_MODEL": "grok-test"}


def test_loads_defaults():
    s = load_live_settings(GOOD)
    assert s.model == "grok-test" and s.api_key == SENTINEL
    assert (s.timeout_seconds, s.call_budget, s.tool_turn_cap, s.excerpt_chars) == (
        30.0,
        6,
        3,
        4000,
    )


def test_overrides():
    s = load_live_settings({**GOOD, "XAI_TIMEOUT_SECONDS": "12.5", "MODEL_CALL_BUDGET": "4"})
    assert s.timeout_seconds == 12.5 and s.call_budget == 4


def test_missing_key_names_variable():
    with pytest.raises(ConfigurationError, match="XAI_API_KEY"):
        load_live_settings({"XAI_MODEL": "grok-test"})


def test_missing_model_names_variable_not_key():
    with pytest.raises(ConfigurationError) as ei:
        load_live_settings({"XAI_API_KEY": SENTINEL})
    assert "XAI_MODEL" in str(ei.value) and SENTINEL not in str(ei.value)


def test_blank_values_are_missing():
    with pytest.raises(ConfigurationError, match="XAI_API_KEY"):
        load_live_settings({"XAI_API_KEY": "  ", "XAI_MODEL": "m"})


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MODEL_CALL_BUDGET", "0"),
        ("MODEL_CALL_BUDGET", "abc"),
        ("XAI_TIMEOUT_SECONDS", "-1"),
        ("XAI_TIMEOUT_SECONDS", "nan"),
        ("XAI_TIMEOUT_SECONDS", "x"),
    ],
)
def test_bad_numbers(name, value):
    with pytest.raises(ConfigurationError) as ei:
        load_live_settings({**GOOD, name: value})
    assert name in str(ei.value)
    assert SENTINEL not in str(ei.value) and f"={value}" not in str(ei.value)


def test_repr_and_str_mask_key():
    s = load_live_settings(GOOD)
    assert SENTINEL not in repr(s) and SENTINEL not in str(s)
    assert "***" in repr(s) and isinstance(s, LiveSettings)


def test_dotenv_not_read_when_env_passed(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("XAI_API_KEY=from-file\nXAI_MODEL=from-file\n")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigurationError):
        load_live_settings({})


def test_dotenv_read_without_override(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("XAI_API_KEY=from-file\nXAI_MODEL=from-file\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_MODEL", "from-env")
    monkeypatch.delenv("XAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("MODEL_CALL_BUDGET", raising=False)
    s = load_live_settings()
    assert s.api_key == "from-file" and s.model == "from-env"
    monkeypatch.delenv("XAI_API_KEY", raising=False)
