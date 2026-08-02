"""Optional OpenTelemetry instrumentation for merit serve.

Two independent gates, both required for anything to happen:
1. MERIT_OTEL=1 in the environment.
2. The `otel` extra (opentelemetry-api/-sdk/-instrumentation-fastapi)
   installed.
Either missing -> every function below is a silent no-op. No
opentelemetry import is attempted unless MERIT_OTEL=1.
"""
import logging
import os
from functools import wraps
from types import SimpleNamespace

logger = logging.getLogger(__name__)


def otel_enabled() -> bool:
    return os.environ.get("MERIT_OTEL") == "1"


def _load_otel() -> SimpleNamespace | None:
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        return None
    return SimpleNamespace(
        trace=trace,
        FastAPIInstrumentor=FastAPIInstrumentor,
        TracerProvider=TracerProvider,
        BatchSpanProcessor=BatchSpanProcessor,
        ConsoleSpanExporter=ConsoleSpanExporter,
    )


def _build_exporter(endpoint: str | None, otel_ns: SimpleNamespace):
    if not endpoint:
        return otel_ns.ConsoleSpanExporter()
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT set but opentelemetry-exporter-otlp-proto-http "
            "is not installed; falling back to console exporter"
        )
        return otel_ns.ConsoleSpanExporter()
    return OTLPSpanExporter(endpoint=endpoint)


def setup_tracing(app) -> None:
    """Instrument a FastAPI app. No-op unless MERIT_OTEL=1 and otel is installed."""
    if not otel_enabled():
        return
    otel_ns = _load_otel()
    if otel_ns is None:
        logger.warning("MERIT_OTEL=1 but the otel extra is not installed; skipping tracing")
        return
    provider = otel_ns.TracerProvider()
    exporter = _build_exporter(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"), otel_ns)
    provider.add_span_processor(otel_ns.BatchSpanProcessor(exporter))
    otel_ns.trace.set_tracer_provider(provider)
    otel_ns.FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)


def traced_node(name: str):
    """Decorator: wrap a graph node callable in a span named merit.node.<name>.

    Returns the callable UNCHANGED (identity) when otel is disabled/missing -
    zero overhead, zero behavior change.
    """

    def decorator(fn):
        if not otel_enabled():
            return fn
        otel_ns = _load_otel()
        if otel_ns is None:
            return fn
        tracer = otel_ns.trace.get_tracer("merit")

        @wraps(fn)
        def wrapped(*args, **kwargs):
            with tracer.start_as_current_span(f"merit.node.{name}"):
                return fn(*args, **kwargs)

        return wrapped

    return decorator
