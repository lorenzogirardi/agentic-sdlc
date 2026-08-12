"""B-001-013/016/018/019/020/021 — Advanced agent tests."""

import json
from pathlib import Path

import pytest

from agents.base import AgentContext
from agents.code_quality import CodeQualityAgent
from agents.coding import CodingAgent
from agents.cost_eval import CostEvalAgent
from agents.docker import DockerAgent
from agents.observability import ObservabilityAgent
from agents.terraform import TerraformAgent
from runners.tool_runner import ToolRunner
from schemas.execution import TaskSpec


def make_ctx(tmp_path: Path, dry_run: bool = True) -> AgentContext:
    task = TaskSpec(
        execution_id="adv-test",
        title="Advanced agent test",
        repository_path=str(tmp_path),
    )
    from schemas.execution import ExecutionContext

    execution = ExecutionContext(execution_id="adv-test", task=task)
    return AgentContext(execution=execution, work_dir=str(tmp_path), dry_run=dry_run)


@pytest.fixture
def runner() -> ToolRunner:
    return ToolRunner(
        allowed_commands=["python", "terraform", "hadolint", "ruff"],
    )


class TestCodingAgent:
    async def test_no_llm_plan_only(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        agent = CodingAgent(opencode_adapter=None)
        result = await agent.execute(ctx)
        assert result["success"] is True
        assert result["changes"] == []

    def test_forbidden_paths_blocked(self, tmp_path: Path) -> None:
        agent = CodingAgent()
        assert agent._is_safe_path(".env") is False
        assert agent._is_safe_path("config/secret.yaml") is False
        assert agent._is_safe_path("src/main.py") is True
        assert agent._is_safe_path("keys/id_rsa") is False

    async def test_existing_code_passed_to_llm(self, tmp_path: Path) -> None:
        """Regression: CodingAgent used to prompt the LLM blind, with no view of
        the current code — it once rewrote a FastAPI app to Flask from scratch
        because it never saw the existing framework."""
        (tmp_path / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        class RecordingOpenCode:
            def __init__(self) -> None:
                self.last_messages: list[dict] | None = None

            async def chat(self, messages, response_schema=None, **kwargs):
                self.last_messages = messages
                return {"changes": []}

        opencode = RecordingOpenCode()
        agent = CodingAgent(opencode_adapter=opencode)
        ctx = make_ctx(tmp_path)

        await agent.execute(ctx)

        assert opencode.last_messages is not None
        user_content = json.loads(opencode.last_messages[1]["content"])
        assert "from fastapi import FastAPI" in user_content["existing_files"]

    def test_path_escape_blocked(self, tmp_path: Path) -> None:
        agent = CodingAgent()
        agent._apply_changes(
            str(tmp_path),
            [{"path": "../evil.py", "content": "x = 1"}],
        )
        assert not (tmp_path.parent / "evil.py").exists()


class TestDockerAgent:
    async def test_no_dockerfile(self, tmp_path: Path, runner: ToolRunner) -> None:
        ctx = make_ctx(tmp_path)
        agent = DockerAgent(runner)
        result = await agent.execute(ctx)
        assert result["success"] is True
        assert "No Dockerfile" in result["summary"]

    async def test_root_user_detected(self, tmp_path: Path, runner: ToolRunner) -> None:
        (tmp_path / "Dockerfile").write_text("FROM python:latest\nRUN pip install flask\n")
        ctx = make_ctx(tmp_path)
        agent = DockerAgent(runner)
        result = await agent.execute(ctx)
        messages = [f.get("message", "") for f in result["findings"]]
        assert any("root" in m for m in messages)
        assert any("not pinned" in m for m in messages)

    async def test_secret_in_env_detected(self, tmp_path: Path, runner: ToolRunner) -> None:
        (tmp_path / "Dockerfile").write_text(
            "FROM python:3.12-slim\nUSER app\nENV SECRET_KEY=abc\n"
        )
        ctx = make_ctx(tmp_path)
        agent = DockerAgent(runner)
        result = await agent.execute(ctx)
        critical = [f for f in result["findings"] if f.get("severity") == "critical"]
        assert len(critical) == 1
        assert result["success"] is False


class TestTerraformAgent:
    async def test_no_terraform(self, tmp_path: Path, runner: ToolRunner) -> None:
        ctx = make_ctx(tmp_path)
        agent = TerraformAgent(runner)
        result = await agent.execute(ctx)
        assert "No Terraform" in result["summary"]

    async def test_sensitive_resource_detected(self, tmp_path: Path, runner: ToolRunner) -> None:
        (tmp_path / "main.tf").write_text(
            'resource "aws_iam_role" "admin" {\n  name = "admin"\n}\n'
        )
        ctx = make_ctx(tmp_path)
        agent = TerraformAgent(runner)
        result = await agent.execute(ctx)
        assert any(f.get("resource") == "aws_iam_role" for f in result["findings"])

    async def test_db_without_prevent_destroy(self, tmp_path: Path, runner: ToolRunner) -> None:
        (tmp_path / "db.tf").write_text(
            'resource "aws_db_instance" "main" {\n  engine = "postgres"\n}\n'
        )
        ctx = make_ctx(tmp_path)
        agent = TerraformAgent(runner)
        result = await agent.execute(ctx)
        high = [f for f in result["findings"] if f.get("severity") == "high"]
        assert len(high) == 1
        assert high[0]["destructive"] is True
        assert result["success"] is False

    def test_forbidden_subcommands(self, runner: ToolRunner) -> None:
        agent = TerraformAgent(runner)
        assert "apply" in agent.FORBIDDEN_SUBCOMMANDS
        assert "destroy" in agent.FORBIDDEN_SUBCOMMANDS


class TestCostEvalAgent:
    async def test_empty_repo(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        agent = CostEvalAgent()
        result = await agent.execute(ctx)
        assert result["cost"]["estimated_monthly_cost"] == 0.0
        assert result["cost"]["confidence"] == "high"

    async def test_eks_cluster_cost(self, tmp_path: Path) -> None:
        (tmp_path / "eks.tf").write_text(
            'resource "aws_eks_cluster" "main" {\n  name = "prod"\n}\n'
        )
        ctx = make_ctx(tmp_path)
        agent = CostEvalAgent()
        result = await agent.execute(ctx)
        assert result["cost"]["estimated_monthly_cost"] == 73.0
        assert len(result["cost"]["cost_drivers"]) == 1

    async def test_unknown_resource_lowers_confidence(self, tmp_path: Path) -> None:
        (tmp_path / "x.tf").write_text(
            'resource "aws_quicksight_account" "q" {}\nresource "aws_gamelift_fleet" "g" {}\n'
        )
        ctx = make_ctx(tmp_path)
        agent = CostEvalAgent()
        result = await agent.execute(ctx)
        assert result["cost"]["confidence"] == "low"
        assert result["cost"]["estimated_monthly_cost"] == 0.0
        assert len(result["cost"]["warnings"]) == 1


class TestObservabilityAgent:
    async def test_fully_instrumented(self, tmp_path: Path) -> None:
        (tmp_path / "app.py").write_text(
            "from fastapi import FastAPI\n"
            "import structlog\n"
            "from opentelemetry import trace\n"
            "from prometheus_client import Counter\n"
            "app = FastAPI()\n"
            '@app.get("/health")\nasync def h(): return {"ok": True}\n'
            '@app.get("/ready")\nasync def r(): return {"ok": True}\n'
        )
        ctx = make_ctx(tmp_path)
        agent = ObservabilityAgent()
        result = await agent.execute(ctx)
        checks = result["checks"]
        assert checks["health_endpoint"] is True
        assert checks["readiness_endpoint"] is True
        assert checks["otel_tracing"] is True
        assert checks["structured_logging"] is True
        assert checks["prometheus_metrics"] is True

    async def test_bare_service_suggestions(self, tmp_path: Path) -> None:
        (tmp_path / "main.py").write_text("print('hello')\n")
        ctx = make_ctx(tmp_path)
        agent = ObservabilityAgent()
        result = await agent.execute(ctx)
        assert len(result["suggestions"]) == 5
        assert result["success"] is True  # never blocking


class TestCodeQualityAgent:
    async def test_no_python(self, tmp_path: Path, runner: ToolRunner) -> None:
        (tmp_path / "main.go").write_text("package main\n")
        ctx = make_ctx(tmp_path)
        agent = CodeQualityAgent(runner)
        result = await agent.execute(ctx)
        assert "not applicable" in result["summary"]
