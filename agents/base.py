from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from schemas.execution import ExecutionContext


class AgentContext:
    def __init__(
        self,
        execution: ExecutionContext,
        work_dir: str,
        dry_run: bool = True,
    ) -> None:
        self.execution = execution
        self.work_dir = work_dir
        self.dry_run = dry_run


class Agent(ABC):
    name: str

    @abstractmethod
    async def analyze(self, ctx: AgentContext) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> dict[str, Any]: ...

    @abstractmethod
    async def verify(self, ctx: AgentContext, result: dict[str, Any]) -> dict[str, Any]: ...
