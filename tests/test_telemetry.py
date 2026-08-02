from types import SimpleNamespace
from typing import ClassVar

from merit import telemetry


class FakeSpanCM:
    def __init__(self, recorder, name):
        self.recorder = recorder
        self.name = name

    def __enter__(self):
        self.recorder.append(self.name)
        return self

    def __exit__(self, *exc):
        return False


class FakeTracer:
    def __init__(self):
        self.spans = []

    def start_as_current_span(self, name):
        return FakeSpanCM(self.spans, name)


class FakeTrace:
    def __init__(self, tracer):
        self.tracer = tracer
        self.provider_set = None

    def get_tracer(self, name):
        return self.tracer

    def set_tracer_provider(self, provider):
        self.provider_set = provider


class FakeProvider:
    def __init__(self):
        self.processors = []

    def add_span_processor(self, processor):
        self.processors.append(processor)


class FakeConsoleExporter:
    pass


class FakeBatchSpanProcessor:
    def __init__(self, exporter):
        self.exporter = exporter


class FakeFastAPIInstrumentor:
    calls: ClassVar[list] = []

    @staticmethod
    def instrument_app(app, tracer_provider=None):
        FakeFastAPIInstrumentor.calls.append((app, tracer_provider))


def test_otel_enabled_requires_exact_flag(monkeypatch):
    monkeypatch.delenv("MERIT_OTEL", raising=False)
    assert telemetry.otel_enabled() is False
    monkeypatch.setenv("MERIT_OTEL", "0")
    assert telemetry.otel_enabled() is False
    monkeypatch.setenv("MERIT_OTEL", "1")
    assert telemetry.otel_enabled() is True


def test_traced_node_is_identity_when_disabled(monkeypatch):
    monkeypatch.delenv("MERIT_OTEL", raising=False)

    def fn():
        return None

    assert telemetry.traced_node("x")(fn) is fn


def test_traced_node_does_not_load_otel_when_flag_unset(monkeypatch):
    # Proves the MERIT_OTEL gate short-circuits BEFORE _load_otel() is ever
    # called - not just that the net result happens to be identity because
    # the package is absent from this venv (it may be installed elsewhere).
    monkeypatch.delenv("MERIT_OTEL", raising=False)
    monkeypatch.setattr(
        telemetry,
        "_load_otel",
        lambda: (_ for _ in ()).throw(AssertionError("_load_otel must not be called")),
    )

    def fn():
        return None

    assert telemetry.traced_node("x")(fn) is fn


def test_traced_node_is_identity_when_package_missing(monkeypatch):
    monkeypatch.setenv("MERIT_OTEL", "1")
    monkeypatch.setattr(telemetry, "_load_otel", lambda: None)

    def fn():
        return None

    assert telemetry.traced_node("x")(fn) is fn


def test_traced_node_wraps_and_records_span(monkeypatch):
    monkeypatch.setenv("MERIT_OTEL", "1")
    tracer = FakeTracer()
    monkeypatch.setattr(
        telemetry,
        "_load_otel",
        lambda: SimpleNamespace(trace=FakeTrace(tracer)),
    )

    def fn(x):
        return x + 1

    wrapped = telemetry.traced_node("x")(fn)
    assert wrapped(1) == 2
    assert tracer.spans == ["merit.node.x"]


def test_build_exporter_defaults_to_console():
    fake_ns = SimpleNamespace(ConsoleSpanExporter=FakeConsoleExporter)
    assert isinstance(telemetry._build_exporter(None, fake_ns), FakeConsoleExporter)


def test_build_exporter_falls_back_when_otlp_missing():
    fake_ns = SimpleNamespace(ConsoleSpanExporter=FakeConsoleExporter)
    assert isinstance(
        telemetry._build_exporter("http://localhost:4318", fake_ns),
        FakeConsoleExporter,
    )


def test_setup_tracing_noop_when_flag_unset(monkeypatch):
    monkeypatch.delenv("MERIT_OTEL", raising=False)
    monkeypatch.setattr(
        telemetry,
        "_load_otel",
        lambda: (_ for _ in ()).throw(AssertionError("_load_otel must not be called")),
    )
    telemetry.setup_tracing(object())


def test_setup_tracing_noop_when_package_missing(monkeypatch):
    monkeypatch.setenv("MERIT_OTEL", "1")
    monkeypatch.setattr(telemetry, "_load_otel", lambda: None)
    telemetry.setup_tracing(object())


def test_setup_tracing_instruments_app_with_fake_otel(monkeypatch):
    monkeypatch.setenv("MERIT_OTEL", "1")
    fake_ns = SimpleNamespace(
        trace=FakeTrace(FakeTracer()),
        FastAPIInstrumentor=FakeFastAPIInstrumentor,
        TracerProvider=FakeProvider,
        BatchSpanProcessor=FakeBatchSpanProcessor,
        ConsoleSpanExporter=FakeConsoleExporter,
    )
    FakeFastAPIInstrumentor.calls = []
    monkeypatch.setattr(telemetry, "_load_otel", lambda: fake_ns)
