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
    COMBAT_ATTACK = "combat_attack"
    COMBAT_MANEUVER = "combat_maneuver"
    COMBAT_REACTION = "combat_reaction"
    COMBAT_MOVE = "combat_move"
    COMBAT_QUICK_INTERACTION = "combat_quick_interaction"
    COMBAT_STABILIZE = "combat_stabilize"
    COMBAT_BARRICADE = "combat_barricade"
    COMBAT_END_TURN = "combat_end_turn"

    # Wave-5 enemy-to-hit / reaction-interrupt window (board task #16,
    # stacks-enemyroll; domain registration requested via chat 2026-07-19,
    # landed by stacks-shopwire as domain schema owner)
    RESOLVE_REACTION = "resolve_reaction"

    # Heroes wiring (infinite_stacks.md §11, §13; wave 4, board task #13)
    ROLL_ATTRIBUTE_DICE = "roll_attribute_dice"
    CREATE_HERO = "create_hero"
    PLAY_CARD = "play_card"
    DRAW_CARDS = "draw_cards"
    SAFE_REST = "safe_rest"
    PICKUP_ITEM = "pickup_item"
    DROP_ITEM = "drop_item"
    TRADE_ITEM = "trade_item"
    RECOVER_BODY_LOOT = "recover_body_loot"

    # Shops wiring (infinite_stacks.md §9.6, §16.4-16.6; wave 5, board task #18)
    SHOP_BUY = "shop_buy"
    SHOP_SELL = "shop_sell"
    SHOP_REPAIR = "shop_repair"
    SHOP_IDENTIFY = "shop_identify"
    SHOP_TREAT = "shop_treat"

    # Server-side clue sharing (wave 5, board task #18)
    SHARE_CLUE = "share_clue"

    # Abilities (wave 6, board task #21; docs/PLAYTEST_FINDINGS_2026-07-19.md
    # E1/A5) -- player-invoked trigger=="manual" abilities. Domain schema
    # posted to the collab room 2026-07-20.
    USE_ABILITY = "use_ability"

    # Study-room domain wiring (wave6b/slice-wiring, docs/
    # INFINITE_STACKS_STUDY_SLICE.md, wavebasedgame.md §3.2-3.6): object/NPC
    # interaction commands realizing the revised core loop. `interact`
    # payload: {object_id: str, interaction_id: str}. `converse` payload:
    # {npc_id: str, appeal_objective_id: str | None} -- NEITHER modifier
    # input is ever taken from the payload as a tier (standing rule #5: no
    # client-supplied modifiers, ever). Evidence is derived server-side from
    # whether `systems.study_social_wire.EVIDENCE_FACT_ID` has already been
    # promoted for the acting hero's own viewer id (StudyRoomState.
    # promoted_fact_ids). Motive is derived server-side from the optional
    # `appeal_objective_id` (a roleplay choice naming which NPC objective the
    # hero appeals to) matched against the NPC's own authored objective data
    # -- see systems/study_social_wire.py::_derive_motive_alignment. An
    # unknown/garbage appeal id degrades to NEUTRAL, never an error. Any
    # legacy `motive_alignment` payload field is ignored entirely.
    INTERACT = "interact"
    CONVERSE = "converse"


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
