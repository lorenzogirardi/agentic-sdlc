from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from orchestrator.logging import get_logger

logger = get_logger(__name__)


class DAGError(Exception):
    pass


class CycleDetectedError(DAGError):
    pass


def topological_sort(dag: dict[str, list[str]]) -> list[list[str]]:
    in_degree: dict[str, int] = dict.fromkeys(dag, 0)
    dependents: dict[str, list[str]] = {node: [] for node in dag}

    for node, deps in dag.items():
        for dep in deps:
            if dep not in dag:
                raise DAGError(f"Dependency '{dep}' not found for node '{node}'")
            in_degree[node] += 1
            dependents[dep].append(node)

    queue: deque[str] = deque(node for node, deg in in_degree.items() if deg == 0)
    levels: list[list[str]] = []

    while queue:
        current_level = list(queue)
        queue.clear()
        for node in current_level:
            for dependent in dependents[node]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)
        levels.append(current_level)

    total_sorted = sum(len(level) for level in levels)
    if total_sorted != len(dag):
        raise CycleDetectedError("DAG contains a cycle")

    return levels


async def run_dag(
    dag: dict[str, list[str]],
    executor: Callable[[str], Awaitable[dict[str, Any]]],
    max_parallel: int = 4,
) -> dict[str, dict[str, Any]]:
    levels = topological_sort(dag)
    results: dict[str, dict[str, Any]] = {}
    semaphore = asyncio.Semaphore(max_parallel)

    async def run_node(name: str) -> None:
        async with semaphore:
            logger.info("dag_node_start", node=name)
            try:
                results[name] = await executor(name)
                logger.info("dag_node_done", node=name)
            except Exception as exc:
                logger.error("dag_node_failed", node=name, error=str(exc))
                results[name] = {"error": str(exc), "success": False}

    for level in levels:
        tasks = [asyncio.create_task(run_node(node)) for node in level]
        await asyncio.gather(*tasks)

    return results
