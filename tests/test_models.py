import pytest

from merit.models import DEEPINFRA_BASE, build_chat_model


def test_env_mapping(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("MERIT_API_KEY", "k")
    monkeypatch.delenv("MERIT_API_BASE", raising=False)
    m = build_chat_model()
    assert m.model_name == "openai/gpt-oss-120b"
    assert str(m.openai_api_base or m.base_url) == DEEPINFRA_BASE
    assert m.temperature == 0.0


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("MERIT_MODEL", raising=False)
    monkeypatch.setenv("MERIT_API_KEY", "k")
    with pytest.raises(RuntimeError, match="MERIT_MODEL"):
        build_chat_model()
