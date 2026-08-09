"""B-001-005 — DAG Scheduler implementation tests."""

import asyncio

import pytest

from orchestrator.dag_scheduler import (
    CycleDetectedError,
    DAGError,
    run_dag,
    topological_sort,
)


class TestTopologicalSort:
    def test_linear(self) -> None:
        dag = {"a": [], "b": ["a"], "c": ["b"]}
        levels = topological_sort(dag)
        flat = [node for level in levels for node in level]
        assert flat.index("a") < flat.index("b")
        assert flat.index("b") < flat.index("c")

    def test_diamond(self) -> None:
        dag = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"]}
        levels = topological_sort(dag)
        assert len(levels) == 3
        assert set(levels[0]) == {"a"}
        assert set(levels[2]) == {"d"}

    def test_independent_nodes_same_level(self) -> None:
        dag = {"a": [], "b": [], "c": []}
        levels = topological_sort(dag)
        assert len(levels) == 1
        assert set(levels[0]) == {"a", "b", "c"}

    def test_missing_dependency_raises(self) -> None:
        dag = {"a": ["nonexistent"]}
        with pytest.raises(DAGError, match="nonexistent"):
            topological_sort(dag)

    def test_cycle_detected(self) -> None:
        dag = {"a": ["b"], "b": ["c"], "c": ["a"]}
        with pytest.raises(CycleDetectedError, match="cycle"):
            topological_sort(dag)

    def test_empty_dag(self) -> None:
        levels = topological_sort({})
        assert levels == []


class TestRunDAG:
    async def test_executes_in_order(self) -> None:
        order: list[str] = []
        dag = {"a": [], "b": ["a"], "c": ["b"]}

        async def executor(name: str) -> dict:
            order.append(name)
            return {"name": name}

        await run_dag(dag, executor, max_parallel=1)
        assert order == ["a", "b", "c"]

    async def test_parallel_execution(self) -> None:
        dag = {"a": [], "b": [], "c": []}
        started: list[str] = []
        lock = asyncio.Lock()

        async def executor(name: str) -> dict:
            async with lock:
                started.append(name)
            await asyncio.sleep(0.1)
            return {"name": name}

        await run_dag(dag, executor, max_parallel=3)
        assert len(started) == 3

    async def test_error_handling(self) -> None:
        dag = {"a": [], "b": ["a"]}

        async def executor(name: str) -> dict:
            if name == "b":
                raise RuntimeError("fail")
            return {"name": name}

        results = await run_dag(dag, executor)
        assert results["a"] == {"name": "a"}
        assert results["b"]["success"] is False
        assert "fail" in results["b"]["error"]

    async def test_respects_max_parallel(self) -> None:
        dag = {f"n{i}": [] for i in range(10)}
        running: int = 0
        max_running: int = 0
        lock = asyncio.Lock()

        async def executor(name: str) -> dict:
            nonlocal running, max_running
            async with lock:
                running += 1
                max_running = max(max_running, running)
            await asyncio.sleep(0.05)
            async with lock:
                running -= 1
            return {}

        await run_dag(dag, executor, max_parallel=3)
        assert max_running <= 3
