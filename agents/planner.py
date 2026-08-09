from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from agents.base import Agent, AgentContext
from orchestrator.dag_scheduler import topological_sort
from orchestrator.logging import get_logger

logger = get_logger(__name__)


class PlannerOutput(BaseModel):
    summary: str
    assumptions: list[str] = Field(default_factory=list)
    required_agents: list[str] = Field(default_factory=list)
    dag: dict[str, list[str]] = Field(default_factory=dict)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    requires_human_approval: bool = False
    acceptance_criteria_understood: list[str] = Field(default_factory=list)


AGENT_ALIASES = {
    "repo_inspector": "repo_inspector",
    "repository_inspector": "repo_inspector",
    "lint": "lint",
    "test_pyramid": "test_pyramid",
    "test": "test_pyramid",
    "security": "security",
    "code_quality": "code_quality",
    "codequality": "code_quality",
    "coding": "coding",
    "terraform": "terraform",
    "docker": "docker",
    "observability": "observability",
    "cost_eval": "cost_eval",
    "cost": "cost_eval",
    "reviewer": "reviewer",
}


class PlannerAgent(Agent):
    name = "planner"

    def __init__(self, opencode_adapter: Any = None) -> None:
        self._opencode = opencode_adapter

    async def analyze(self, ctx: AgentContext) -> dict:
        task = ctx.execution.task
        requested = task.requested_agents or []
        title = task.title
        description = task.description
        acceptance = task.acceptance_criteria

        resolved_agents = [AGENT_ALIASES.get(a, a) for a in requested]
        valid_agents = [a for a in resolved_agents if a in AGENT_ALIASES.values()]
        unresolved = [a for a in resolved_agents if a not in AGENT_ALIASES.values()]
        if unresolved:
            logger.warning("planner_unresolved_agents", agents=unresolved)
            try:
                result = await self._opencode.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": """You are a software architect planning agent.
Analyze the task and produce a structured execution plan.
Always return valid JSON matching the schema.

Rules:
- Identify which agents are needed.
- Generate a DAG (Directed Acyclic Graph) with agent names and their dependencies.
- repo_inspector must run before other agents.
- reviewer always runs last after all other agents.
- Independent agents can have no dependencies (empty list).
- Identify risks and assumptions.
- Determine if human approval is needed.""",
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                {
                                    "title": title,
                                    "description": description,
                                    "acceptance_criteria": acceptance,
                                    "requested_agents": valid_agents,
                                }
                            ),
                        },
                    ],
                    response_schema=PlannerOutput,
                )
                plan = PlannerOutput.model_validate(result)
            except Exception as exc:
                logger.warning("planner_llm_failed", error=str(exc))
                plan = self._fallback_plan(title, description, acceptance, valid_agents)
        else:
            plan = self._fallback_plan(title, description, acceptance, valid_agents)

        try:
            topological_sort(plan.dag)
        except Exception as exc:
            logger.warning("planner_dag_invalid", error=str(exc), dag=plan.dag)
            plan.dag = self._linear_dag(plan.required_agents)

        return plan.model_dump()

    async def execute(self, ctx: AgentContext) -> dict:
        plan_dict = await self.analyze(ctx)
        plan = PlannerOutput.model_validate(plan_dict)

        ctx.execution.dag = list(plan.dag.keys())

        return {
            "agent_name": self.name,
            "success": True,
            "summary": plan.summary,
            "plan": plan.model_dump(),
        }

    async def verify(self, ctx: AgentContext, result: dict) -> dict:
        dag = result.get("plan", {}).get("dag", {})
        try:
            topological_sort(dag)
            dag_valid = True
        except Exception:
            dag_valid = False

        return {
            "verified": dag_valid and len(result.get("plan", {}).get("required_agents", [])) > 0,
            "issues": [] if dag_valid else ["DAG validation failed"],
        }

    def _fallback_plan(
        self,
        title: str,
        description: str,
        acceptance: list[str],
        requested: list[str],
    ) -> PlannerOutput:
        agents = requested or ["repo_inspector", "test_pyramid", "security", "lint", "reviewer"]

        dag: dict[str, list[str]] = {}
        prev: str | None = None
        for agent in agents:
            dag[agent] = [prev] if prev else []
            prev = agent

        dag["reviewer"] = [a for a in agents if a != "reviewer"]

        return PlannerOutput(
            summary=f"Plan for: {title}",
            assumptions=["Generated by fallback planner (no LLM available)"],
            required_agents=agents,
            dag=dag,
            steps=[{"agent": a, "description": f"Execute {a}"} for a in agents],
            risks=["Fallback planner used — may miss context-specific risks"],
            requires_human_approval=False,
            acceptance_criteria_understood=acceptance or [],
        )

    def _linear_dag(self, agents: list[str]) -> dict[str, list[str]]:
        dag: dict[str, list[str]] = {}
        prev: str | None = None
        for agent in agents:
            dag[agent] = [prev] if prev else []
            prev = agent
        return dag
