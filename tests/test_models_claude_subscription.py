import json
from typing import ClassVar

import pytest

from merit import models
from merit.schemas import Demands


class FakeTextBlock:
    def __init__(self, text):
        self.text = text


class FakeAssistantMessage:
    def __init__(self, blocks):
        self.content = blocks


class FakeClaudeSDKClient:
    last_options = None
    last_prompt = None
    response_blocks: ClassVar[list] = []

    def __init__(self, options=None):
        type(self).last_options = options

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def query(self, prompt):
        type(self).last_prompt = prompt

    async def receive_response(self):
        for message in type(self).response_blocks:
            yield message


class FakeClaudeAgentOptions:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeSDKModule:
    ClaudeSDKClient = FakeClaudeSDKClient
    ClaudeAgentOptions = FakeClaudeAgentOptions


FakeTextBlock.__name__ = "TextBlock"
FakeAssistantMessage.__name__ = "AssistantMessage"


@pytest.fixture(autouse=True)
def _reset_fake_client():
    FakeClaudeSDKClient.last_options = None
    FakeClaudeSDKClient.last_prompt = None
    FakeClaudeSDKClient.response_blocks = []


def test_build_chat_model_dispatches_to_claude_subscription(monkeypatch):
    monkeypatch.setenv("MERIT_MODEL", "claude-subscription")

    assert isinstance(models.build_chat_model(), models.ClaudeSubscriptionChat)


def test_claude_subscription_invoke_returns_text(monkeypatch):
    monkeypatch.setattr(models, "_load_claude_agent_sdk", lambda: FakeSDKModule)
    FakeClaudeSDKClient.response_blocks = [FakeAssistantMessage([FakeTextBlock("hello")])]

    assert models.ClaudeSubscriptionChat().invoke("hi").content == "hello"
    assert FakeClaudeSDKClient.last_prompt == "hi"


def test_claude_subscription_concatenates_multiple_text_blocks_and_messages(monkeypatch):
    monkeypatch.setattr(models, "_load_claude_agent_sdk", lambda: FakeSDKModule)
    FakeClaudeSDKClient.response_blocks = [
        FakeAssistantMessage([FakeTextBlock("hello")]),
        FakeAssistantMessage([FakeTextBlock(" world")]),
    ]

    assert models.ClaudeSubscriptionChat().invoke("hi").content == "hello world"


def test_claude_subscription_structured_output_parses_json(monkeypatch):
    monkeypatch.setattr(models, "_load_claude_agent_sdk", lambda: FakeSDKModule)
    FakeClaudeSDKClient.response_blocks = [
        FakeAssistantMessage(
            [
                FakeTextBlock(
                    json.dumps(
                        {"demands": [{"name": "python", "kind": "core", "quote": "q"}]}
                    )
                )
            ]
        )
    ]

    result = models.ClaudeSubscriptionChat().with_structured_output(Demands).invoke("posting")

    assert isinstance(result, Demands)
    assert result.demands[0].name == "python"


def test_claude_subscription_structured_output_strips_markdown_fence(monkeypatch):
    monkeypatch.setattr(models, "_load_claude_agent_sdk", lambda: FakeSDKModule)
    payload = json.dumps({"demands": [{"name": "python", "kind": "core", "quote": "q"}]})
    FakeClaudeSDKClient.response_blocks = [FakeAssistantMessage([FakeTextBlock(f"```json\n{payload}\n```")])]

    result = models.ClaudeSubscriptionChat().with_structured_output(Demands).invoke("posting")

    assert result.demands[0].name == "python"


def test_claude_subscription_structured_output_rejects_non_pydantic_schema():
    with pytest.raises(TypeError):
        models.ClaudeSubscriptionChat().with_structured_output(dict)


def test_missing_sdk_raises_named_error(monkeypatch):
    monkeypatch.setattr(
        models,
        "_load_claude_agent_sdk",
        lambda: (_ for _ in ()).throw(
            models.ClaudeSubscriptionUnavailable(
                "claude-agent-sdk: pip install 'merit[subscription]'"
            )
        ),
    )

    with pytest.raises(models.ClaudeSubscriptionUnavailable, match=r"claude-agent-sdk.*pip install"):
        models.ClaudeSubscriptionChat().invoke("hi")
