"""Strict YAML loading for NPC template content (wave 6B).

Split out of `study_loader.py` to stay under the repo's ~500-line module
convention. Same discipline as `loader.py`: `yaml.safe_load` only, unknown
fields and missing required fields raise `LoaderError` at load time, and
every constructed dataclass runs through `npcs.py`'s own `__post_init__`
invariants (including the disclosure-leak check).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import npcs as N
from . import schemas as S
from .loader import LoaderError, load_yaml_file
from .study_common import prose, require_keys, viewer_scope


def _load_provenance(raw: Any, *, where: str) -> N.Provenance:
    raw = require_keys(raw, {"knower_id", "method"}, where=where)
    try:
        return N.Provenance(knower_id=raw["knower_id"], method=raw["method"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_knowledge_atom(raw: Any, *, where: str) -> N.KnowledgeAtom:
    raw = require_keys(raw, {"id", "statement", "is_true", "provenance", "disclosure"}, where=where)
    provenance = tuple(
        _load_provenance(p, where=f"{where}.provenance[{i}]") for i, p in enumerate(raw.get("provenance", []))
    )
    try:
        disclosure = N.DisclosureLayer(raw["disclosure"])
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid disclosure {raw['disclosure']!r}") from exc
    try:
        return N.KnowledgeAtom(
            id=raw["id"], statement=raw["statement"], is_true=raw["is_true"], provenance=provenance, disclosure=disclosure
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_tell(raw: Any, *, where: str) -> N.Tell:
    raw = require_keys(raw, {"id", "prose", "hints_at_atom_id"}, where=where)
    try:
        return N.Tell(id=raw["id"], prose=prose(raw["prose"], where=where), hints_at_atom_id=raw["hints_at_atom_id"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_objective(raw: Any, *, where: str) -> N.Objective:
    raw = require_keys(raw, {"id", "kind", "prose", "viewer_scope"}, where=where)
    try:
        kind = N.ObjectiveKind(raw["kind"])
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid objective kind {raw['kind']!r}") from exc
    try:
        return N.Objective(
            id=raw["id"], kind=kind, prose=prose(raw["prose"], where=where), viewer_scope=viewer_scope(raw["viewer_scope"], where=where)
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_inventory_entry(raw: Any, *, where: str) -> N.InventoryEntry:
    raw = require_keys(raw, {"item_id", "quantity", "viewer_scope"}, where=where)
    try:
        return N.InventoryEntry(
            item_id=raw["item_id"],
            quantity=raw.get("quantity", 1),
            viewer_scope=viewer_scope(raw.get("viewer_scope", "public"), where=where),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_relationship(raw: Any, *, where: str) -> N.Relationship:
    raw = require_keys(raw, {"other_npc_id", "kind", "prose"}, where=where)
    try:
        return N.Relationship(other_npc_id=raw["other_npc_id"], kind=raw["kind"], prose=prose(raw["prose"], where=where))
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_npc_trigger(raw: Any, *, where: str) -> N.Trigger:
    raw = require_keys(raw, {"id", "condition", "effect_description"}, where=where)
    try:
        return N.Trigger(id=raw["id"], condition=raw["condition"], effect_description=raw["effect_description"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_npc_state(raw: Any, *, where: str) -> N.EmotionalPhysicalState:
    raw = require_keys(raw, {"disposition", "physical_state"}, where=where)
    try:
        return N.EmotionalPhysicalState(disposition=raw["disposition"], physical_state=raw["physical_state"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_npc_template(raw: Any, *, where: str) -> N.NPCTemplate:
    allowed = {
        "id",
        "archetype_pool",
        "age",
        "sex_gender_presentation",
        "visual_traits",
        "persona_voice",
        "stats",
        "boundaries",
        "preferences",
        "fears",
        "knowledge",
        "lies",
        "tells",
        "inventory",
        "relationships",
        "objectives",
        "triggers",
        "state",
    }
    raw = require_keys(raw, allowed, where=where)
    knowledge = tuple(
        _load_knowledge_atom(k, where=f"{where}.knowledge[{i}]") for i, k in enumerate(raw.get("knowledge", []))
    )
    tells = tuple(_load_tell(t, where=f"{where}.tells[{i}]") for i, t in enumerate(raw.get("tells", [])))
    inventory = tuple(
        _load_inventory_entry(x, where=f"{where}.inventory[{i}]") for i, x in enumerate(raw.get("inventory", []))
    )
    relationships = tuple(
        _load_relationship(r, where=f"{where}.relationships[{i}]") for i, r in enumerate(raw.get("relationships", []))
    )
    objectives = tuple(
        _load_objective(o, where=f"{where}.objectives[{i}]") for i, o in enumerate(raw.get("objectives", []))
    )
    triggers = tuple(_load_npc_trigger(t, where=f"{where}.triggers[{i}]") for i, t in enumerate(raw.get("triggers", [])))
    state = _load_npc_state(raw["state"], where=f"{where}.state")
    try:
        return N.NPCTemplate(
            id=raw["id"],
            archetype_pool=tuple(raw.get("archetype_pool", [])),
            age=raw["age"],
            sex_gender_presentation=raw["sex_gender_presentation"],
            visual_traits=tuple(raw.get("visual_traits", [])),
            persona_voice=prose(raw["persona_voice"], where=where),
            stats=dict(raw.get("stats", {})),
            boundaries=tuple(raw.get("boundaries", [])),
            preferences=tuple(raw.get("preferences", [])),
            fears=tuple(raw.get("fears", [])),
            knowledge=knowledge,
            lies=tuple(raw.get("lies", [])),
            tells=tells,
            inventory=inventory,
            relationships=relationships,
            objectives=objectives,
            triggers=triggers,
            state=state,
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def load_npc_templates(path: Path) -> dict[str, N.NPCTemplate]:
    if not path.exists():
        return {}
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, Mapping) or "npcs" not in raw:
        raise LoaderError(f"{path}: expected top-level key 'npcs'")
    templates: dict[str, N.NPCTemplate] = {}
    for i, item in enumerate(raw["npcs"]):
        where = f"{path.name}:npcs[{i}]"
        template = _load_npc_template(item, where=where)
        if template.id in templates:
            raise LoaderError(f"{where}: duplicate npc id {template.id!r}")
        templates[template.id] = template
    return templates
