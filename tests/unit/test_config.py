# tests/unit/test_config.py
import pytest

from opportunity_tracker import config


def test_default_constants():
    assert config.STALENESS_DAYS == 30
    assert config.TRUST_THRESHOLD_DEFAULT == 0.85
    assert config.INSTITUTION_CAP_DEFAULT == 50


def test_get_anthropic_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    assert config.get_anthropic_api_key() == "sk-test-123"


def test_get_anthropic_api_key_raises_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        config.get_anthropic_api_key()
