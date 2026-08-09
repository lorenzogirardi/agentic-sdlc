"""B-001-004 — State Machine tests (Phase 2a RED)."""

import pytest

from schemas.execution import ExecutionState


class TestStateMachineTransitions:
    VALID_TRANSITIONS = {
        ExecutionState.BACKLOG: {ExecutionState.TRIAGE},
        ExecutionState.TRIAGE: {ExecutionState.SPECIFIED, ExecutionState.BLOCKED},
        ExecutionState.SPECIFIED: {ExecutionState.PLANNED, ExecutionState.BLOCKED},
        ExecutionState.PLANNED: {ExecutionState.IMPLEMENTING, ExecutionState.BLOCKED},
        ExecutionState.IMPLEMENTING: {
            ExecutionState.VERIFYING,
            ExecutionState.FIX_REQUIRED,
            ExecutionState.BLOCKED,
        },
        ExecutionState.VERIFYING: {
            ExecutionState.REVIEW_REQUIRED,
            ExecutionState.FIX_REQUIRED,
            ExecutionState.BLOCKED,
        },
        ExecutionState.REVIEW_REQUIRED: {
            ExecutionState.DONE,
            ExecutionState.FIX_REQUIRED,
            ExecutionState.BLOCKED,
        },
        ExecutionState.FIX_REQUIRED: {ExecutionState.IMPLEMENTING, ExecutionState.BLOCKED},
        ExecutionState.DONE: set(),
        ExecutionState.BLOCKED: set(),
    }

    @pytest.mark.parametrize(
        "from_state,to_state",
        [
            (ExecutionState.BACKLOG, ExecutionState.TRIAGE),
            (ExecutionState.TRIAGE, ExecutionState.SPECIFIED),
            (ExecutionState.SPECIFIED, ExecutionState.PLANNED),
            (ExecutionState.PLANNED, ExecutionState.IMPLEMENTING),
            (ExecutionState.IMPLEMENTING, ExecutionState.VERIFYING),
            (ExecutionState.VERIFYING, ExecutionState.REVIEW_REQUIRED),
            (ExecutionState.REVIEW_REQUIRED, ExecutionState.DONE),
            (ExecutionState.IMPLEMENTING, ExecutionState.FIX_REQUIRED),
            (ExecutionState.VERIFYING, ExecutionState.FIX_REQUIRED),
            (ExecutionState.FIX_REQUIRED, ExecutionState.IMPLEMENTING),
            (ExecutionState.TRIAGE, ExecutionState.BLOCKED),
        ],
    )
    def test_valid_transitions(self, from_state: ExecutionState, to_state: ExecutionState) -> None:
        assert to_state in self.VALID_TRANSITIONS[from_state]

    def test_no_self_transition(self) -> None:
        for state in ExecutionState:
            assert state not in self.VALID_TRANSITIONS[state]

    def test_terminal_states_have_no_exits(self) -> None:
        for state in (ExecutionState.DONE, ExecutionState.BLOCKED):
            assert self.VALID_TRANSITIONS[state] == set()

    def test_all_states_defined(self) -> None:
        for state in ExecutionState:
            assert state in self.VALID_TRANSITIONS
