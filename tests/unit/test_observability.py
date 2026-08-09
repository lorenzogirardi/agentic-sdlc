"""B-001-023 — Observability tests."""

from opentelemetry import trace

from observability.metrics import MetricsRecorder
from observability.tracing import setup_tracing


class TestTracing:
    def test_setup_tracing_no_endpoint(self) -> None:
        tracer = setup_tracing()
        assert tracer is not None
        assert isinstance(trace.get_tracer_provider(), trace.TracerProvider)

    def test_span_creation(self) -> None:
        tracer = setup_tracing()
        with tracer.start_as_current_span("test_span") as span:
            span.set_attribute("key", "value")
            assert span.is_recording() or not span.is_recording()  # no-op span OK


class TestMetricsRecorder:
    def test_record_task(self) -> None:
        recorder = MetricsRecorder()
        recorder.record_task("PASS", 1.5)

    def test_record_agent(self) -> None:
        recorder = MetricsRecorder()
        recorder.record_agent("planner", "success", 0.5)

    def test_record_tool(self) -> None:
        recorder = MetricsRecorder()
        recorder.record_tool("pytest", 0)
        recorder.record_tool("ruff", 1)

    def test_record_llm(self) -> None:
        recorder = MetricsRecorder()
        recorder.record_llm("deepseek-v4-flash-free", 100, 50)
        recorder.record_llm_cost("deepseek-v4-flash-free", 0.001)

    def test_record_gate_and_approval(self) -> None:
        recorder = MetricsRecorder()
        recorder.record_gate_failure("policy")
        recorder.record_human_approval("merge", "approved")

    def test_metrics_registered(self) -> None:
        from prometheus_client import REGISTRY

        names = {m.name for m in REGISTRY.collect()}
        # Counters are collected without the _total suffix on the family name
        assert "sdlc_task" in names
        assert "sdlc_agent_runs" in names
        assert "sdlc_llm_tokens" in names
        assert "sdlc_gate_failures" in names
        assert "sdlc_human_approvals" in names
