import time

import httpx
import openai
import pytest
from langchain_core.runnables import Runnable

from merit import models


def _rate_limit_error() -> openai.RateLimitError:
    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(status_code=429, request=request)
    return openai.RateLimitError("engine_overloaded", response=response, body=None)


class FlakyRunnable(Runnable):
    """Fake runnable that fails `fail_times` invocations before succeeding."""

    def __init__(self, fail_times: int) -> None:
        self.calls = 0
        self.fail_times = fail_times

    def invoke(self, input, config=None, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise _rate_limit_error()
        return "ok"

    def with_structured_output(self, schema, method=None):
        return self


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # The retry wrapper uses real exponential backoff; skip the wait so
    # tests stay fast regardless of stop_after_attempt.
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def test_build_extractor_retries_then_succeeds(monkeypatch):
    flaky = FlakyRunnable(fail_times=2)
    monkeypatch.setattr(models, "build_chat_model", lambda temperature=0.0: flaky)

    extractor = models.build_extractor()

    assert extractor.invoke("posting text") == "ok"
    assert flaky.calls == 3


def test_build_judge_exhausts_attempts_and_reraises(monkeypatch):
    flaky = FlakyRunnable(fail_times=999)
    monkeypatch.setattr(models, "build_chat_model", lambda temperature=0.0: flaky)

    judge = models.build_judge()

    with pytest.raises(openai.RateLimitError):
        judge.invoke("posting text")
    assert flaky.calls == 8


def test_build_writer_retries_then_succeeds(monkeypatch):
    flaky = FlakyRunnable(fail_times=2)
    monkeypatch.setattr(models, "build_chat_model", lambda temperature=0.7: flaky)

    writer = models.build_writer()

    assert writer.invoke("posting text") == "ok"
    assert flaky.calls == 3
