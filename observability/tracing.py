"""B-001-023 — OpenTelemetry tracing setup."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import Tracer

SERVICE_NAME = "agentic-sdlc"


def setup_tracing(
    service_name: str = SERVICE_NAME,
    otlp_endpoint: str | None = None,
) -> Tracer:
    """Configure OTel tracing. No-op exporter when endpoint is unset."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)

    endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            exporter = OTLPSpanExporter(endpoint=f"{endpoint.rstrip('/')}/v1/traces")
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            pass

    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)
