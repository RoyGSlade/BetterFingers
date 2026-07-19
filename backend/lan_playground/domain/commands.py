"""Command envelope per docs/INFINITE_STACKS_CONTRACTS.md §2."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CommandType(str, Enum):
    JOIN_RUN = "join_run"
    MOVE = "move"
    BREACH = "breach"
    OBSERVE = "observe"
    INSPECT = "inspect"
    PASS = "pass"
    CHECK = "check"
    INSPECT_OBJECT = "inspect_object"
    SUBMIT_SOLUTION = "submit_solution"
    REQUEST_HINT = "request_hint"


class ErrorCode(str, Enum):
    STALE_REVISION = "stale_revision"
    ILLEGAL_ACTION = "illegal_action"
    NOT_YOUR_TURN = "not_your_turn"
    UNKNOWN_TARGET = "unknown_target"
    SCHEMA_ERROR = "schema_error"


@dataclass(frozen=True)
class Command:
    command_id: str
    idempotency_key: str
    run_id: str
    type: CommandType
    hero_id: str | None = None
    encounter_id: str | None = None
    expected_revision: int = 0
    payload: dict = field(default_factory=dict)


class CommandError(Exception):
    def __init__(self, code: ErrorCode, message: str, legal_actions: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.legal_actions = legal_actions or []

    def to_dict(self) -> dict:
        return {"code": self.code.value, "message": self.message, "legal_actions": self.legal_actions}
