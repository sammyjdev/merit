from typing import ClassVar

import pytest

from merit import models


class FakeChatVertexAI:
    last_kwargs: ClassVar[dict] = {}

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def test_build_chat_model_dispatches_to_vertex(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.delenv("GOOGLE_CLOUD_LOCATION", raising=False)
    monkeypatch.setattr(models, "_load_vertex_chat_model", lambda: FakeChatVertexAI)

    result = models.build_chat_model()

    assert isinstance(result, FakeChatVertexAI)
    assert FakeChatVertexAI.last_kwargs == {
        "model": models.DEFAULT_VERTEX_MODEL,
        "project": "test-project",
        "location": "us-central1",
        "temperature": 0.0,
    }


def test_vertex_location_env_override(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "europe-west4")
    monkeypatch.setattr(models, "_load_vertex_chat_model", lambda: FakeChatVertexAI)

    models.build_chat_model()

    assert FakeChatVertexAI.last_kwargs["location"] == "europe-west4"


def test_vertex_temperature_passthrough(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setattr(models, "_load_vertex_chat_model", lambda: FakeChatVertexAI)

    models.build_chat_model(temperature=0.7)

    assert FakeChatVertexAI.last_kwargs["temperature"] == 0.7


def test_vertex_missing_project_raises(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "vertex")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setattr(models, "_load_vertex_chat_model", lambda: FakeChatVertexAI)

    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        models.build_chat_model()


def test_missing_vertex_sdk_raises_named_error(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    with pytest.raises(
        models.VertexBackendUnavailable,
        match=r"langchain-google-vertexai.*pip install",
    ):
        models.build_chat_model()
