from __future__ import annotations

from schemas.execution import ExecutionState

VALID_TRANSITIONS: dict[ExecutionState, set[ExecutionState]] = {
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

TERMINAL_STATES = {ExecutionState.DONE, ExecutionState.BLOCKED}


class StateMachineError(Exception):
    pass


class InvalidTransitionError(StateMachineError):
    def __init__(self, current: ExecutionState, target: ExecutionState) -> None:
        super().__init__(f"Invalid transition: {current} -> {target}")


class StateMachine:
    def __init__(self, initial: ExecutionState = ExecutionState.BACKLOG) -> None:
        self._state = initial

    @property
    def state(self) -> ExecutionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in TERMINAL_STATES

    def can_transition(self, target: ExecutionState) -> bool:
        return target in VALID_TRANSITIONS.get(self._state, set())

    def transition(self, target: ExecutionState) -> ExecutionState:
        if not self.can_transition(target):
            raise InvalidTransitionError(self._state, target)
        self._state = target
        return self._state

    def force_transition(self, target: ExecutionState) -> ExecutionState:
        self._state = target
        return self._state
