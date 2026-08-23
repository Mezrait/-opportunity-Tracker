# tests/unit/test_config.py
import pytest

from opportunity_tracker import config


def test_default_constants():
    assert config.STALENESS_DAYS == 30
    assert config.TRUST_THRESHOLD_DEFAULT == 0.85
    assert config.INSTITUTION_CAP_DEFAULT == 50


def test_get_groq_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test-123")
    assert config.get_groq_api_key() == "gsk-test-123"


def test_get_groq_api_key_raises_when_unset(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        config.get_groq_api_key()


def test_get_tavily_api_key_reads_env(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test-123")
    assert config.get_tavily_api_key() == "tvly-test-123"


def test_get_tavily_api_key_raises_when_unset(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        config.get_tavily_api_key()
