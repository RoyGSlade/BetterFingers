"""CI-style cross-file validators for room/NPC/lattice content (wave 6B).

Sibling to `validators.py`, kept separate for the same module-size reason as
`study_loader.py`. Mirrors that module's `Finding`/`ValidationError` pattern
exactly so a caller running both content families sees a uniform report
shape.

Checks here specifically cover what a single dataclass's `__post_init__`
cannot see across files:
  - a room's `npc_ids` must reference NPCs that actually exist in the pack;
  - an NPC's `inventory` item ids should exist in the core item pack when
    that pack is supplied (soft-checked: the study slice is additive to the
    core pack, so this validator accepts an optional `known_item_ids` set
    rather than importing `content.loader` and creating a cycle);
  - defense-in-depth disclosure-leak re-check across every NPC in the pack
    (the authoritative check lives in `npcs.NPCTemplate.__post_init__`; this
    mirrors `validators.py`'s existing "defense-in-depth" style for effects/
    prose so a future relaxation of the constructor check still gets caught
    in CI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from . import npcs as N
from . import rooms as R
from .schemas import ContentError
from .study_loader import StudyContentPack


@dataclass(frozen=True)
class Finding:
    rule: str
    location: str
    message: str

    def __str__(self) -> str:
        return f"[{self.rule}] {self.location}: {self.message}"


class ValidationError(ContentError):
    def __init__(self, findings: Sequence[Finding]):
        self.findings = list(findings)
        super().__init__("; ".join(str(f) for f in self.findings))


def check_room_npc_links(pack: StudyContentPack) -> list[Finding]:
    findings: list[Finding] = []
    for room in pack.rooms.values():
        for npc_id in room.npc_ids:
            if npc_id not in pack.npcs:
                findings.append(
                    Finding("unknown_reference", f"room:{room.id}", f"unknown npc_id {npc_id!r}")
                )
    return findings


def check_room_lattice_recipe_reachable(pack: StudyContentPack) -> list[Finding]:
    """Every declared lattice recipe should be satisfiable from at least one
    combination of the rooms in this pack -- otherwise it is a dead recipe
    that can never reveal a stair. This is intentionally permissive (it
    checks the *sum* of every room's contribution against the recipe, not
    real room-resolution order, since that is domain/systems territory) but
    catches the construction-time-obvious case: a recipe with no possible
    rooms behind it at all."""

    findings: list[Finding] = []
    all_contributions = [room.lattice_contribution for room in pack.rooms.values()]
    for recipe in pack.lattice_recipes.values():
        if not recipe.is_satisfied(all_contributions):
            findings.append(
                Finding(
                    "unreachable_lattice_recipe",
                    f"lattice_recipe:{recipe.id}",
                    "recipe cannot be satisfied even by summing every room's lattice contribution in this pack",
                )
            )
    return findings


def check_npc_disclosure_no_leak(pack: StudyContentPack) -> list[Finding]:
    """Defense-in-depth: `NPCTemplate.__post_init__` already rejects a FREE
    tell pointing at a GATED atom, or an atom marked both FREE and GATED.
    Re-derive the same check here so CI catches a future relaxation of the
    constructor rule."""

    findings: list[Finding] = []
    for npc in pack.npcs.values():
        gated_ids = {atom.id for atom in npc.knowledge if atom.disclosure is N.DisclosureLayer.GATED}
        for tell in npc.tells:
            if tell.hints_at_atom_id in gated_ids:
                findings.append(
                    Finding(
                        "disclosure_leak",
                        f"npc:{npc.id}:tell:{tell.id}",
                        f"free-layer tell reaches gated atom {tell.hints_at_atom_id!r}",
                    )
                )
    return findings


def check_npc_inventory_known_items(pack: StudyContentPack, known_item_ids: frozenset[str] | None) -> list[Finding]:
    if known_item_ids is None:
        return []
    findings: list[Finding] = []
    for npc in pack.npcs.values():
        for entry in npc.inventory:
            if entry.item_id not in known_item_ids:
                findings.append(
                    Finding("unknown_reference", f"npc:{npc.id}", f"unknown inventory item {entry.item_id!r}")
                )
    return findings


ALL_STUDY_PACK_CHECKS = (
    check_room_npc_links,
    check_room_lattice_recipe_reachable,
    check_npc_disclosure_no_leak,
)


def validate_study_pack(pack: StudyContentPack, *, known_item_ids: frozenset[str] | None = None) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL_STUDY_PACK_CHECKS:
        findings.extend(check(pack))
    findings.extend(check_npc_inventory_known_items(pack, known_item_ids))
    return findings


def validate_study_pack_strict(pack: StudyContentPack, *, known_item_ids: frozenset[str] | None = None) -> None:
    findings = validate_study_pack(pack, known_item_ids=known_item_ids)
    if findings:
        raise ValidationError(findings)
