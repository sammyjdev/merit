"""Model layer: one place that knows about providers and structured output."""
import asyncio
import json
import os

import openai
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from merit.schemas import Demands, ResidueVerdicts

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"
DEFAULT_CLAUDE_SUBSCRIPTION_MODEL = "claude-sonnet-4-5"
DEFAULT_VERTEX_MODEL = "gemini-2.0-flash-001"


class ClaudeSubscriptionUnavailable(RuntimeError):
    """The optional Claude subscription SDK is not installed."""


def _load_claude_agent_sdk():
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise ClaudeSubscriptionUnavailable(
            "MERIT_MODEL=claude-subscription requires the claude-agent-sdk "
            "package. Install it with: pip install 'merit[subscription]'"
        ) from exc
    return claude_agent_sdk


class VertexBackendUnavailable(RuntimeError):
    """The optional langchain-google-vertexai package is not installed."""


def _load_vertex_chat_model():
    try:
        from langchain_google_vertexai import ChatVertexAI
    except ImportError as exc:
        raise VertexBackendUnavailable(
            "MERIT_MODEL=vertex requires the langchain-google-vertexai "
            "package. Install it with: pip install 'merit[vertex]'"
        ) from exc
    return ChatVertexAI


class ClaudeSubscriptionChat(BaseChatModel):
    model: str = DEFAULT_CLAUDE_SUBSCRIPTION_MODEL
    temperature: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "claude-subscription"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        text = asyncio.run(self._acomplete(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _acomplete(self, messages) -> str:
        sdk = _load_claude_agent_sdk()
        # ponytail: plain string prompts only; add role-aware conversion for real chat history.
        prompt = messages[0].content if len(messages) == 1 else "\n".join(
            str(message.content) for message in messages
        )
        options = sdk.ClaudeAgentOptions(model=self.model)
        parts = []
        async with sdk.ClaudeSDKClient(options=options) as client:
            await client.query(prompt)
            async for message in client.receive_response():
                if type(message).__name__ != "AssistantMessage":
                    continue
                parts.extend(
                    block.text
                    for block in message.content
                    if type(block).__name__ == "TextBlock"
                )
        return "".join(parts)

    def with_structured_output(
        self, schema, *, method=None, include_raw=False, **kwargs
    ) -> Runnable:
        if not isinstance(schema, type) or not issubclass(schema, BaseModel):
            raise TypeError("Claude subscription structured output requires a Pydantic BaseModel schema")

        schema_json = json.dumps(schema.model_json_schema())

        def add_instruction(prompt: str) -> str:
            return (
                f"{prompt}\n\nReturn ONLY raw JSON matching this schema, with no markdown "
                f"fences or commentary:\n{schema_json}"
            )

        def parse(message: AIMessage) -> BaseModel:
            text = message.content.strip()
            if text.startswith("```") and text.endswith("```"):
                text = text[3:-3].strip()
                text = text.removeprefix("json\n")
            return schema.model_validate(json.loads(text))

        # ponytail: include_raw is accepted for compatibility; add it if a caller needs both values.
        return RunnableLambda(add_instruction) | self | RunnableLambda(parse)


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _with_rate_limit_retry(runnable: Runnable) -> Runnable:
    """DeepInfra overload windows last minutes; retry through them."""
    return runnable.with_retry(
        retry_if_exception_type=(openai.RateLimitError,),
        wait_exponential_jitter=True,
        stop_after_attempt=8,
    )


def build_chat_model(temperature: float = 0.0) -> BaseChatModel:
    backend = _env("MERIT_MODEL")
    if backend == "claude-subscription":
        return ClaudeSubscriptionChat(temperature=temperature)
    if backend == "vertex":
        chat_vertex_ai = _load_vertex_chat_model()
        return chat_vertex_ai(
            model=DEFAULT_VERTEX_MODEL,
            project=_env("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
            temperature=temperature,
        )
    return ChatOpenAI(
        model=backend,
        base_url=os.environ.get("MERIT_API_BASE", DEEPINFRA_BASE),
        api_key=_env("MERIT_API_KEY"),
        temperature=temperature,
        max_retries=4,
    )


def build_extractor() -> Runnable:
    return _with_rate_limit_retry(
        build_chat_model(0.0).with_structured_output(Demands, method="json_schema")
    )


def build_judge() -> Runnable:
    return _with_rate_limit_retry(
        build_chat_model(0.0).with_structured_output(ResidueVerdicts, method="json_schema")
    )


def build_writer() -> Runnable:
    return _with_rate_limit_retry(build_chat_model(0.7))
