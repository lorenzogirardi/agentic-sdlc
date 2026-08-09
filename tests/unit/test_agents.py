"""B-001-002 — Agent model tests (Phase 2a RED)."""

from schemas.agent import AgentPlan, AgentResult, VerificationResult


class TestAgentModels:
    def test_plan_defaults(self) -> None:
        plan = AgentPlan(agent_name="test")
        assert plan.agent_name == "test"
        assert plan.summary == ""
        assert plan.steps == []
        assert plan.dependencies == []

    def test_result_success(self) -> None:
        result = AgentResult(
            agent_name="test",
            success=True,
            summary="All good",
            findings=[{"id": "F-001", "message": "ok"}],
        )
        assert result.success is True
        assert len(result.findings) == 1
        assert result.error is None

    def test_result_failure(self) -> None:
        result = AgentResult(
            agent_name="test",
            success=False,
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_verification_verified(self) -> None:
        vr = VerificationResult(agent_name="test", verified=True)
        assert vr.verified is True
        assert vr.issues == []

    def test_verification_not_verified(self) -> None:
        vr = VerificationResult(
            agent_name="test",
            verified=False,
            issues=["Missing coverage", "Failing test"],
        )
        assert vr.verified is False
        assert len(vr.issues) == 2
