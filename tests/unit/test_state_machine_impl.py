"""B-001-004 — StateMachine implementation tests."""

import pytest

from orchestrator.state_machine import (
    InvalidTransitionError,
    StateMachine,
)
from schemas.execution import ExecutionState


class TestStateMachineImplementation:
    def test_initial_state(self) -> None:
        sm = StateMachine()
        assert sm.state == ExecutionState.BACKLOG

    def test_custom_initial_state(self) -> None:
        sm = StateMachine(initial=ExecutionState.TRIAGE)
        assert sm.state == ExecutionState.TRIAGE

    def test_valid_transition(self) -> None:
        sm = StateMachine()
        new_state = sm.transition(ExecutionState.TRIAGE)
        assert new_state == ExecutionState.TRIAGE
        assert sm.state == ExecutionState.TRIAGE

    def test_invalid_transition_raises(self) -> None:
        sm = StateMachine()
        with pytest.raises(InvalidTransitionError, match="BACKLOG -> DONE"):
            sm.transition(ExecutionState.DONE)

    def test_can_transition_true(self) -> None:
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.TRIAGE) is True

    def test_can_transition_false(self) -> None:
        sm = StateMachine()
        assert sm.can_transition(ExecutionState.DONE) is False

    def test_is_terminal(self) -> None:
        sm = StateMachine(initial=ExecutionState.DONE)
        assert sm.is_terminal is True

        sm2 = StateMachine(initial=ExecutionState.BACKLOG)
        assert sm2.is_terminal is False

    def test_force_transition(self) -> None:
        sm = StateMachine()
        sm.force_transition(ExecutionState.DONE)
        assert sm.state == ExecutionState.DONE

    def test_full_happy_path(self) -> None:
        sm = StateMachine()
        path: list[ExecutionState] = [
            ExecutionState.TRIAGE,
            ExecutionState.SPECIFIED,
            ExecutionState.PLANNED,
            ExecutionState.IMPLEMENTING,
            ExecutionState.VERIFYING,
            ExecutionState.REVIEW_REQUIRED,
            ExecutionState.DONE,
        ]
        for state in path:
            assert sm.can_transition(state) is True
            sm.transition(state)
        assert sm.is_terminal is True

    def test_blocked_from_any_state(self) -> None:
        blockable = [
            ExecutionState.TRIAGE,
            ExecutionState.SPECIFIED,
            ExecutionState.PLANNED,
            ExecutionState.IMPLEMENTING,
            ExecutionState.VERIFYING,
            ExecutionState.REVIEW_REQUIRED,
            ExecutionState.FIX_REQUIRED,
        ]
        for state in blockable:
            sm = StateMachine(initial=state)
            sm.transition(ExecutionState.BLOCKED)
            assert sm.state == ExecutionState.BLOCKED
