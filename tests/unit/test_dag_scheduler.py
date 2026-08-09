"""B-001-005 — DAG Scheduler tests (Phase 2a RED)."""

import pytest


class TestDAGTopologicalSort:
    def test_linear_dag(self) -> None:
        dag = {
            "a": [],
            "b": ["a"],
            "c": ["b"],
        }
        result = _topological_sort(dag)
        assert result.index("a") < result.index("b")
        assert result.index("b") < result.index("c")

    def test_diamond_dag(self) -> None:
        dag = {
            "a": [],
            "b": ["a"],
            "c": ["a"],
            "d": ["b", "c"],
        }
        result = _topological_sort(dag)
        assert result.index("a") < result.index("b")
        assert result.index("a") < result.index("c")
        assert result.index("b") < result.index("d")
        assert result.index("c") < result.index("d")

    def test_single_node(self) -> None:
        dag = {"a": []}
        result = _topological_sort(dag)
        assert result == ["a"]

    def test_cycle_detection(self) -> None:
        dag = {
            "a": ["b"],
            "b": ["c"],
            "c": ["a"],
        }
        with pytest.raises(ValueError, match="cycle"):
            _topological_sort(dag)

    def test_independent_nodes_can_run_in_parallel(self) -> None:
        dag = {
            "a": [],
            "b": [],
            "c": [],
        }
        result = _topological_sort(dag)
        assert set(result) == {"a", "b", "c"}

    def test_disconnected_graph(self) -> None:
        dag = {
            "a": [],
            "b": [],
            "c": ["d"],
            "d": [],
            "e": [],
        }
        result = _topological_sort(dag)
        assert len(result) == 5
        assert result.index("d") < result.index("c")


def _topological_sort(dag: dict[str, list[str]]) -> list[str]:
    in_degree: dict[str, int] = dict.fromkeys(dag, 0)
    for node, deps in dag.items():
        for dep in deps:
            if dep not in dag:
                raise ValueError(f"Dependency '{dep}' not found for node '{node}'")
            in_degree[node] += 1

    queue = [node for node, deg in in_degree.items() if deg == 0]
    result = []

    while queue:
        node = queue.pop(0)
        result.append(node)
        for dependent in dag:
            if node in dag[dependent]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

    if len(result) != len(dag):
        raise ValueError("DAG contains a cycle")
    return result
