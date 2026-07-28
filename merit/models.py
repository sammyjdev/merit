"""Model layer: one place that knows about providers and structured output."""
import os

from langchain_openai import ChatOpenAI

from merit.schemas import Demands, ResidueVerdicts

DEEPINFRA_BASE = "https://api.deepinfra.com/v1/openai"


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def build_chat_model(temperature: float = 0.0) -> ChatOpenAI:
    return ChatOpenAI(
        model=_env("MERIT_MODEL"),
        base_url=os.environ.get("MERIT_API_BASE", DEEPINFRA_BASE),
        api_key=_env("MERIT_API_KEY"),
        temperature=temperature,
    )


def build_extractor():
    return build_chat_model(0.0).with_structured_output(Demands, method="json_schema")


def build_judge():
    return build_chat_model(0.0).with_structured_output(ResidueVerdicts, method="json_schema")


def build_writer() -> ChatOpenAI:
    return build_chat_model(0.7)
