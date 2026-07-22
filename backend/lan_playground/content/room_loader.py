"""Strict YAML loading for room/object/lattice content (wave 6B).

Split out of `study_loader.py` to stay under the repo's ~500-line module
convention. Same discipline as `loader.py`: `yaml.safe_load` only, unknown
fields and missing required fields raise `LoaderError` at load time, and
every constructed dataclass runs through its own `__post_init__` invariants
from `rooms.py` / `lattice.py`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from . import lattice as LT
from . import rooms as R
from . import schemas as S
from .loader import LoaderError, load_yaml_file
from .study_common import effects, prose, require_keys, viewer_scope

# ---------------------------------------------------------------------------
# Lattice
# ---------------------------------------------------------------------------


def _component(raw: str, *, where: str) -> LT.LatticeComponent:
    try:
        return LT.LatticeComponent(raw)
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid lattice component {raw!r}") from exc


def _load_lattice_recipe(raw: Any, *, where: str) -> LT.LatticeRecipe:
    raw = require_keys(raw, {"id", "floor_id", "thresholds"}, where=where)
    thresholds_raw = require_keys(
        raw.get("thresholds", {}), set(c.value for c in LT.LatticeComponent), where=f"{where}.thresholds"
    )
    thresholds = {_component(k, where=f"{where}.thresholds"): v for k, v in thresholds_raw.items()}
    try:
        return LT.LatticeRecipe(id=raw["id"], floor_id=raw["floor_id"], thresholds=thresholds)
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def load_lattice_recipes(path: Path) -> dict[str, LT.LatticeRecipe]:
    if not path.exists():
        return {}
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, Mapping) or "lattice_recipes" not in raw:
        raise LoaderError(f"{path}: expected top-level key 'lattice_recipes'")
    recipes: dict[str, LT.LatticeRecipe] = {}
    for i, item in enumerate(raw["lattice_recipes"]):
        where = f"{path.name}:lattice_recipes[{i}]"
        recipe = _load_lattice_recipe(item, where=where)
        if recipe.id in recipes:
            raise LoaderError(f"{where}: duplicate lattice recipe id {recipe.id!r}")
        recipes[recipe.id] = recipe
    return recipes


def _load_lattice_contribution(raw: Any, *, where: str) -> LT.LatticeContribution:
    raw = require_keys(raw, set(c.value for c in LT.LatticeComponent), where=where)
    amounts = {_component(k, where=where): v for k, v in raw.items()}
    try:
        return LT.LatticeContribution(amounts=amounts)
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


# ---------------------------------------------------------------------------
# Rooms / objects
# ---------------------------------------------------------------------------


def _load_object_state(raw: Any, *, where: str) -> R.ObjectState:
    raw = require_keys(raw, {"id", "prose", "visibility"}, where=where)
    try:
        visibility = R.ObjectVisibility(raw["visibility"])
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid visibility {raw['visibility']!r}") from exc
    try:
        return R.ObjectState(id=raw["id"], prose=prose(raw["prose"], where=where), visibility=visibility)
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_state_transition(raw: Any, *, where: str) -> R.StateTransition:
    raw = require_keys(raw, {"id", "from_state", "to_state", "trigger", "effects"}, where=where)
    try:
        return R.StateTransition(
            id=raw["id"],
            from_state=raw["from_state"],
            to_state=raw["to_state"],
            trigger=raw["trigger"],
            effects=effects(raw.get("effects"), where=f"{where}.effects"),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_object_interaction(raw: Any, *, where: str) -> R.ObjectInteraction:
    allowed = {"id", "verb", "legal_states", "prose", "effects", "state_transition_id", "repeatable", "reveals_state"}
    raw = require_keys(raw, allowed, where=where)
    try:
        return R.ObjectInteraction(
            id=raw["id"],
            verb=raw["verb"],
            legal_states=tuple(raw.get("legal_states", [])),
            prose=prose(raw["prose"], where=where),
            effects=effects(raw.get("effects"), where=f"{where}.effects"),
            state_transition_id=raw.get("state_transition_id"),
            repeatable=raw.get("repeatable", True),
            reveals_state=raw.get("reveals_state"),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_book_fact(raw: Any, *, where: str) -> R.BookProvenance:
    raw = require_keys(raw, {"fact_id", "statement", "is_reliable", "source"}, where=where)
    try:
        return R.BookProvenance(
            fact_id=raw["fact_id"], statement=raw["statement"], is_reliable=raw["is_reliable"], source=raw["source"]
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_book(raw: Any, *, where: str) -> R.BookContent:
    raw = require_keys(raw, {"id", "title", "facts"}, where=where)
    facts = tuple(_load_book_fact(f, where=f"{where}.facts[{i}]") for i, f in enumerate(raw.get("facts", [])))
    try:
        return R.BookContent(id=raw["id"], title=raw["title"], facts=facts)
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_room_object(raw: Any, *, where: str) -> R.RoomObject:
    allowed = {"id", "version", "name", "initial_state", "states", "interactions", "transitions", "book"}
    raw = require_keys(raw, allowed, where=where)
    states = tuple(_load_object_state(s, where=f"{where}.states[{i}]") for i, s in enumerate(raw.get("states", [])))
    interactions = tuple(
        _load_object_interaction(x, where=f"{where}.interactions[{i}]")
        for i, x in enumerate(raw.get("interactions", []))
    )
    transitions = tuple(
        _load_state_transition(t, where=f"{where}.transitions[{i}]") for i, t in enumerate(raw.get("transitions", []))
    )
    book = _load_book(raw["book"], where=f"{where}.book") if raw.get("book") else None
    try:
        return R.RoomObject(
            id=raw["id"],
            version=raw["version"],
            name=raw["name"],
            initial_state=raw["initial_state"],
            states=states,
            interactions=interactions,
            transitions=transitions,
            book=book,
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_narration_fact(raw: Any, *, where: str) -> R.NarrationFact:
    raw = require_keys(raw, {"fact_id", "prose", "viewer_scope"}, where=where)
    try:
        return R.NarrationFact(
            fact_id=raw["fact_id"], prose=prose(raw["prose"], where=where), viewer_scope=viewer_scope(raw["viewer_scope"], where=where)
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_secret(raw: Any, *, where: str) -> R.Secret:
    raw = require_keys(raw, {"id", "fact_id", "prose", "viewer_scope", "revealed_by_interaction_id"}, where=where)
    try:
        return R.Secret(
            id=raw["id"],
            fact_id=raw["fact_id"],
            prose=prose(raw["prose"], where=where),
            viewer_scope=viewer_scope(raw["viewer_scope"], where=where),
            revealed_by_interaction_id=raw.get("revealed_by_interaction_id"),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_clue_link(raw: Any, *, where: str) -> R.ClueLink:
    raw = require_keys(raw, {"clue_id", "source_object_id", "source_interaction_id", "requires_clue_ids"}, where=where)
    try:
        return R.ClueLink(
            clue_id=raw["clue_id"],
            source_object_id=raw["source_object_id"],
            source_interaction_id=raw["source_interaction_id"],
            requires_clue_ids=tuple(raw.get("requires_clue_ids", [])),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_subobjective(raw: Any, *, where: str) -> R.SubObjective:
    raw = require_keys(raw, {"id", "prose", "reward_fact_id"}, where=where)
    try:
        return R.SubObjective(id=raw["id"], prose=prose(raw["prose"], where=where), reward_fact_id=raw.get("reward_fact_id"))
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_hazard(raw: Any, *, where: str) -> R.Hazard:
    raw = require_keys(raw, {"id", "prose", "trigger", "effects"}, where=where)
    try:
        return R.Hazard(
            id=raw["id"], prose=prose(raw["prose"], where=where), trigger=raw["trigger"], effects=effects(raw.get("effects"), where=f"{where}.effects")
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_encounter_hook(raw: Any, *, where: str) -> R.EncounterHook:
    raw = require_keys(raw, {"id", "kind", "trigger"}, where=where)
    try:
        return R.EncounterHook(id=raw["id"], kind=raw["kind"], trigger=raw["trigger"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_payoff_interaction(raw: Any, *, where: str) -> R.PayoffInteraction:
    raw = require_keys(raw, {"object_id", "interaction_id", "description"}, where=where)
    try:
        return R.PayoffInteraction(object_id=raw["object_id"], interaction_id=raw["interaction_id"], description=raw["description"])
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_room_template(raw: Any, *, where: str) -> R.RoomTemplate:
    allowed = {
        "id",
        "archetype",
        "purpose",
        "layout",
        "atmosphere",
        "condition",
        "cleanliness",
        "objects",
        "visible_facts",
        "subtle_inconsistencies",
        "secrets",
        "clue_graph",
        "npc_ids",
        "subobjectives",
        "hazards",
        "encounter_hooks",
        "lattice_contribution",
        "payoff_interaction",
        "narration_facts",
        "persistent",
    }
    raw = require_keys(raw, allowed, where=where)
    objects = tuple(_load_room_object(o, where=f"{where}.objects[{i}]") for i, o in enumerate(raw.get("objects", [])))
    visible_facts = tuple(
        _load_narration_fact(f, where=f"{where}.visible_facts[{i}]") for i, f in enumerate(raw.get("visible_facts", []))
    )
    subtle_inconsistencies = tuple(
        _load_narration_fact(f, where=f"{where}.subtle_inconsistencies[{i}]")
        for i, f in enumerate(raw.get("subtle_inconsistencies", []))
    )
    secrets = tuple(_load_secret(s, where=f"{where}.secrets[{i}]") for i, s in enumerate(raw.get("secrets", [])))
    clue_graph = tuple(_load_clue_link(c, where=f"{where}.clue_graph[{i}]") for i, c in enumerate(raw.get("clue_graph", [])))
    subobjectives = tuple(
        _load_subobjective(s, where=f"{where}.subobjectives[{i}]") for i, s in enumerate(raw.get("subobjectives", []))
    )
    hazards = tuple(_load_hazard(h, where=f"{where}.hazards[{i}]") for i, h in enumerate(raw.get("hazards", [])))
    encounter_hooks = tuple(
        _load_encounter_hook(h, where=f"{where}.encounter_hooks[{i}]") for i, h in enumerate(raw.get("encounter_hooks", []))
    )
    lattice_contribution = _load_lattice_contribution(raw["lattice_contribution"], where=f"{where}.lattice_contribution")
    payoff_interaction = _load_payoff_interaction(raw["payoff_interaction"], where=f"{where}.payoff_interaction")
    narration_facts = tuple(
        _load_narration_fact(f, where=f"{where}.narration_facts[{i}]") for i, f in enumerate(raw.get("narration_facts", []))
    )
    try:
        return R.RoomTemplate(
            id=raw["id"],
            archetype=raw["archetype"],
            purpose=raw["purpose"],
            layout=raw["layout"],
            atmosphere=raw["atmosphere"],
            condition=raw["condition"],
            cleanliness=raw["cleanliness"],
            objects=objects,
            visible_facts=visible_facts,
            subtle_inconsistencies=subtle_inconsistencies,
            secrets=secrets,
            clue_graph=clue_graph,
            npc_ids=tuple(raw.get("npc_ids", [])),
            subobjectives=subobjectives,
            hazards=hazards,
            encounter_hooks=encounter_hooks,
            lattice_contribution=lattice_contribution,
            payoff_interaction=payoff_interaction,
            narration_facts=narration_facts,
            persistent=raw.get("persistent", True),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def load_room_templates(path: Path) -> dict[str, R.RoomTemplate]:
    if not path.exists():
        return {}
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, Mapping) or "rooms" not in raw:
        raise LoaderError(f"{path}: expected top-level key 'rooms'")
    templates: dict[str, R.RoomTemplate] = {}
    for i, item in enumerate(raw["rooms"]):
        where = f"{path.name}:rooms[{i}]"
        template = _load_room_template(item, where=where)
        if template.id in templates:
            raise LoaderError(f"{where}: duplicate room template id {template.id!r}")
        templates[template.id] = template
    return templates
