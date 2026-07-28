"""Model layer: one place that knows about providers and structured output."""
import os

import openai
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from merit.schemas import Demands, ResidueVerdicts

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"


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


def build_chat_model(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model=_env("MERIT_MODEL"),
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
