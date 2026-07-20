"""CI-style content validators for The Lost Meaning: Infinite Stacks (§23.2).

`loader.py` validates one file at a time (structure, required fields, enum
values, non-empty prose). This module runs the checks that only make sense
across a fully loaded pack: unknown cross-file references, effects without a
declared engine handler, unreachable puzzle clues, and permanent rewards from
unbounded repeatable accomplishments.

Every `check_*` function returns a list of `Finding`s instead of raising, so
a CI run sees every violation in one pass. `validate_pack` aggregates them;
`validate_pack_dir` is the one-call entry point CI (or a test) uses: load,
then validate, raising `ValidationError` with every finding attached if any
check fails.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Import the schemas submodule directly (not `from . import schemas`) so the
# static import graph records an edge to content.schemas rather than back to
# the content package itself, which would form a package<->validators cycle.
import backend.lan_playground.content.schemas as S

from .loader import load_pack


@dataclass(frozen=True)
class Finding:
    rule: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.location}: {self.message}"


class ValidationError(S.ContentError):
    """Raised by `validate_pack_dir` / `validate_pack_strict` when any Finding fires."""

    def __init__(self, findings: Sequence[Finding]):
        self.findings = list(findings)
        super().__init__("; ".join(str(f) for f in self.findings))


# ---------------------------------------------------------------------------
# Unknown references (§23.2: "unknown card, item, enemy, ... references")
# ---------------------------------------------------------------------------


def check_unknown_references(pack: S.ContentPack) -> list[Finding]:
    findings: list[Finding] = []

    for bg in pack.backgrounds.values():
        for item_id in bg.starting_item_ids:
            if item_id not in pack.items:
                findings.append(
                    Finding("unknown_reference", f"background:{bg.id}", f"unknown starting item {item_id!r}")
                )

    for card in pack.cards.values():
        if card.source not in ("general", "persona", "equipment") and card.source not in pack.backgrounds:
            findings.append(
                Finding("unknown_reference", f"card:{card.id}", f"unknown source background {card.source!r}")
            )

    for item in pack.items.values():
        for card_id in item.granted_card_ids:
            if card_id not in pack.cards:
                findings.append(
                    Finding("unknown_reference", f"item:{item.id}", f"unknown granted card {card_id!r}")
                )

    for location, effect in _iter_all_effects(pack):
        if effect.op == "apply_condition" or effect.op == "remove_condition":
            cond_id = effect.args.get("condition_id")
            if cond_id not in pack.conditions:
                findings.append(
                    Finding("unknown_reference", location, f"unknown condition {cond_id!r}")
                )
        if effect.op in ("grant_card", "exhaust_card"):
            card_id = effect.args.get("card_id")
            if card_id not in pack.cards:
                findings.append(Finding("unknown_reference", location, f"unknown card {card_id!r}"))

    return findings


# ---------------------------------------------------------------------------
# Effects without handlers (§23.2)
# ---------------------------------------------------------------------------


def _iter_all_effects(pack: S.ContentPack) -> Iterable[tuple[str, S.Effect]]:
    for bg in pack.backgrounds.values():
        for eff in bg.signature_ability.effects:
            yield f"background:{bg.id}:signature_ability", eff

    for card in pack.cards.values():
        for eff in card.base_effects:
            yield f"card:{card.id}:base_effects", eff
        if card.check is not None:
            for group in ("strong_success", "success", "cost", "setback"):
                for eff in getattr(card.check.outcomes, group):
                    yield f"card:{card.id}:check:{group}", eff

    for item in pack.items.values():
        for eff in item.passive_effects:
            yield f"item:{item.id}:passive_effects", eff
        for eff in item.use_effects:
            yield f"item:{item.id}:use_effects", eff

    for cond in pack.conditions.values():
        yield f"condition:{cond.id}:primary_effect", cond.primary_effect
        for treatment in cond.treatments:
            for eff in treatment.effects:
                yield f"condition:{cond.id}:treatment:{treatment.id}", eff

    for enemy in pack.enemies.values():
        for intent in enemy.intents:
            for eff in intent.effects:
                yield f"enemy:{enemy.id}:intent:{intent.id}", eff


def check_effects_have_handlers(pack: S.ContentPack) -> list[Finding]:
    """Defense-in-depth: `Effect.__post_init__` already rejects unknown ops at
    construction time, so this mainly guards against a future relaxation of
    that constructor check."""

    findings = []
    for location, eff in _iter_all_effects(pack):
        if eff.op not in S.KNOWN_OPS:
            findings.append(Finding("effect_without_handler", location, f"op {eff.op!r} has no known handler"))
    return findings


# ---------------------------------------------------------------------------
# Missing fallback / accessible prose (§23.2, §13.3, §25)
# ---------------------------------------------------------------------------


def _iter_all_prose(pack: S.ContentPack) -> Iterable[tuple[str, S.Prose]]:
    for bg in pack.backgrounds.values():
        yield f"background:{bg.id}", bg.prose
        yield f"background:{bg.id}:signature_ability", bg.signature_ability.prose
    for skill in pack.skills.values():
        yield f"skill:{skill.id}", skill.prose
    for card in pack.cards.values():
        yield f"card:{card.id}", card.prose
    for item in pack.items.values():
        yield f"item:{item.id}", item.prose
    for cond in pack.conditions.values():
        yield f"condition:{cond.id}", cond.prose
        for treatment in cond.treatments:
            yield f"condition:{cond.id}:treatment:{treatment.id}", treatment.prose
    for enemy in pack.enemies.values():
        yield f"enemy:{enemy.id}", enemy.prose
        for intent in enemy.intents:
            yield f"enemy:{enemy.id}:intent:{intent.id}", intent.prose
    for template in pack.puzzle_templates.values():
        yield f"puzzle_template:{template.id}", template.prose


def check_prose_complete(pack: S.ContentPack) -> list[Finding]:
    """Defense-in-depth: `Prose.__post_init__` already rejects empty fallback
    or accessible text at construction time."""

    findings = []
    for location, prose in _iter_all_prose(pack):
        if not prose.fallback.strip():
            findings.append(Finding("missing_fallback_prose", location, "fallback text is empty"))
        if not prose.accessible.strip():
            findings.append(Finding("missing_accessible_description", location, "accessible text is empty"))
    return findings


# ---------------------------------------------------------------------------
# Enemies without readable intent / counterplay (§14.6, §23.2)
# ---------------------------------------------------------------------------


def check_enemy_intents(pack: S.ContentPack) -> list[Finding]:
    """Defense-in-depth: `Enemy.__post_init__` already rejects an empty
    `intents` tuple and `EnemyIntent.__post_init__` rejects empty counterplay."""

    findings = []
    for enemy in pack.enemies.values():
        if not enemy.intents:
            findings.append(Finding("enemy_without_intent", f"enemy:{enemy.id}", "no readable intents declared"))
        for intent in enemy.intents:
            if not intent.counterplay.strip():
                findings.append(
                    Finding("enemy_without_intent", f"enemy:{enemy.id}:intent:{intent.id}", "no counterplay text")
                )
    return findings


# ---------------------------------------------------------------------------
# Missing treatment for a condition (§16.4, §23.2)
# ---------------------------------------------------------------------------


def check_condition_treatments(pack: S.ContentPack) -> list[Finding]:
    """Defense-in-depth: `Condition.__post_init__` already rejects an empty
    `treatments` tuple."""

    findings = []
    for cond in pack.conditions.values():
        if not cond.treatments:
            findings.append(Finding("missing_treatment", f"condition:{cond.id}", "no treatment path declared"))
    return findings


# ---------------------------------------------------------------------------
# Permanent rewards from unbounded repeatables (§17.6, §23.2)
# ---------------------------------------------------------------------------


def check_no_permanent_reward_from_unbounded_repeatable(
    accomplishments: Sequence[S.Accomplishment],
) -> list[Finding]:
    findings = []
    for accomplishment in accomplishments:
        unbounded = accomplishment.repeatable and accomplishment.repeat_cap is None
        grants_permanent = accomplishment.permanent_unlock_id is not None
        if unbounded and grants_permanent:
            findings.append(
                Finding(
                    "permanent_reward_from_unbounded_repeatable",
                    f"accomplishment:{accomplishment.id}",
                    f"repeatable with no cap grants permanent unlock {accomplishment.permanent_unlock_id!r} "
                    "(§17.6 anti-farming)",
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Puzzle instance checks (§10.1-10.2, §23.2)
# ---------------------------------------------------------------------------


def check_puzzle_instance(instance: S.PuzzleInstance) -> list[Finding]:
    """Cross-field checks a single `PuzzleInstance` cannot fully enforce in its
    own `__post_init__` (which only knows about the four-object structure and
    that clue ids referenced *by objects* exist)."""

    findings: list[Finding] = []
    clue_ids = {clue.id for clue in instance.clues}
    assigned_clue_ids: set[str] = set()

    for viewer, clue_id_list in instance.private_clue_assignments.items():
        for clue_id in clue_id_list:
            assigned_clue_ids.add(clue_id)
            if clue_id not in clue_ids:
                findings.append(
                    Finding(
                        "unknown_reference",
                        f"puzzle:{instance.id}:private_clue_assignments:{viewer}",
                        f"unknown clue {clue_id!r}",
                    )
                )

    reachable = assigned_clue_ids | {cid for obj in instance.objects for cid in obj.clue_ids}
    unreachable = clue_ids - reachable
    if unreachable:
        findings.append(
            Finding(
                "unreachable_clue",
                f"puzzle:{instance.id}",
                f"clues never exposed by any object or private assignment: {sorted(unreachable)}",
            )
        )

    for clue in instance.clues:
        if clue.viewer_scope is S.ViewerScope.PUBLIC and clue.id in assigned_clue_ids:
            findings.append(
                Finding(
                    "secret_scope_conflict",
                    f"puzzle:{instance.id}:clue:{clue.id}",
                    "clue is PUBLIC scoped but also privately assigned",
                )
            )
        if clue.viewer_scope is not S.ViewerScope.PUBLIC and clue.id not in assigned_clue_ids:
            findings.append(
                Finding(
                    "secret_scope_conflict",
                    f"puzzle:{instance.id}:clue:{clue.id}",
                    f"clue has viewer_scope {clue.viewer_scope.value!r} but no private assignment routes it to a viewer",
                )
            )

    return findings


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

ALL_PACK_CHECKS = (
    check_unknown_references,
    check_effects_have_handlers,
    check_prose_complete,
    check_enemy_intents,
    check_condition_treatments,
)


def validate_pack(pack: S.ContentPack) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_PACK_CHECKS:
        findings.extend(check(pack))
    for template_meta in pack.puzzle_templates.values():
        # Instance-level checks run separately per generated PuzzleInstance
        # (see content/puzzles/*); template metadata has no instance to check yet.
        del template_meta
    return findings


def validate_pack_strict(pack: S.ContentPack) -> None:
    findings = validate_pack(pack)
    if findings:
        raise ValidationError(findings)


def validate_pack_dir(pack_dir: Path, *, pack_id: str) -> S.ContentPack:
    """Load `pack_dir` and validate it. Raises `loader.LoaderError` for
    single-file structural problems, or `ValidationError` (with every
    `Finding`) for cross-file problems. Both are `ContentError` subclasses."""

    pack = load_pack(pack_dir, pack_id=pack_id)
    validate_pack_strict(pack)
    return pack
