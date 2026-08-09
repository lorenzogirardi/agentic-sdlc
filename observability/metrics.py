"""B-001-023 — Prometheus metrics for the SDLC platform."""

from __future__ import annotations

from prometheus_client import Counter, Histogram, start_http_server

TASK_TOTAL = Counter(
    "sdlc_task_total",
    "Total number of SDLC tasks executed",
    ["verdict"],
)
TASK_DURATION = Histogram(
    "sdlc_task_duration_seconds",
    "Task execution duration in seconds",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1800),
)
AGENT_RUNS = Counter(
    "sdlc_agent_runs_total",
    "Total agent executions",
    ["agent", "status"],
)
AGENT_DURATION = Histogram(
    "sdlc_agent_duration_seconds",
    "Agent execution duration in seconds",
    ["agent"],
    buckets=(0.1, 0.5, 1, 5, 15, 30, 60, 120),
)
TOOL_CALLS = Counter(
    "sdlc_agent_tool_calls_total",
    "Total tool invocations",
    ["tool", "exit_status"],
)
LLM_TOKENS = Counter(
    "sdlc_llm_tokens_total",
    "Total LLM tokens consumed",
    ["model", "kind"],
)
LLM_COST = Counter(
    "sdlc_llm_cost_eur_total",
    "Estimated LLM cost in EUR",
    ["model"],
)
GATE_FAILURES = Counter(
    "sdlc_gate_failures_total",
    "Policy gate failures",
    ["gate"],
)
HUMAN_APPROVALS = Counter(
    "sdlc_human_approvals_total",
    "Human approval requests",
    ["action", "decision"],
)


def start_metrics_server(port: int = 9464) -> None:
    start_http_server(port)


class MetricsRecorder:
    """Thin wrapper so the orchestrator does not touch prometheus_client directly."""

    def record_task(self, verdict: str, duration_seconds: float) -> None:
        TASK_TOTAL.labels(verdict=verdict).inc()
        TASK_DURATION.observe(duration_seconds)

    def record_agent(self, agent: str, status: str, duration_seconds: float) -> None:
        AGENT_RUNS.labels(agent=agent, status=status).inc()
        AGENT_DURATION.labels(agent=agent).observe(duration_seconds)

    def record_tool(self, tool: str, exit_code: int) -> None:
        TOOL_CALLS.labels(tool=tool, exit_status="ok" if exit_code == 0 else "error").inc()

    def record_llm(self, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        LLM_TOKENS.labels(model=model, kind="prompt").inc(prompt_tokens)
        LLM_TOKENS.labels(model=model, kind="completion").inc(completion_tokens)

    def record_llm_cost(self, model: str, cost_eur: float) -> None:
        LLM_COST.labels(model=model).inc(cost_eur)

    def record_gate_failure(self, gate: str) -> None:
        GATE_FAILURES.labels(gate=gate).inc()

    def record_human_approval(self, action: str, decision: str) -> None:
        HUMAN_APPROVALS.labels(action=action, decision=decision).inc()
