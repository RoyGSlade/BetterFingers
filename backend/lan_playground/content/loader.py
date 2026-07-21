"""Strict YAML pack loading for The Lost Meaning: Infinite Stacks (board task #2).

Loads `content/packs/<pack_id>/*.yaml` into the dataclasses defined in
`schemas.py`. Loading is deliberately strict: unknown fields, missing required
fields, wrong types, invalid enum values, and duplicate IDs all raise
`LoaderError` (a `ContentError`) at load time rather than surfacing later as a
runtime KeyError or a silently-ignored typo. Content never executes code --
`yaml.safe_load` only.

Shop content (`shops.yaml`) loads through `backend.lan_playground.shops.
content_loader` instead of this module -- wave 4 shipped it here with a
`from ..shops import models as shop_models` import, a documented backwards
edge (content depending on a package, the reverse of every other package's
"content never imports the package" discipline). Wave 5 (board task #18)
moved the loading/validation code into the shops package instead of moving
`shops.models`'s dataclasses into `schemas.py`: the ECON-001-proven economy/
services/seeding modules have no other content-side consumer, so relocating
the *entry point* removes the edge with zero change to that already-tested
surface. This module now has no import of `shops` at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from . import schemas as S

CORE_PACK_DIR = Path(__file__).resolve().parent / "packs" / "core"


class LoaderError(S.ContentError):
    """Raised when a pack YAML file is malformed or violates the content schema."""


def require_keys(raw: Any, allowed: set[str], *, where: str) -> Mapping[str, Any]:
    if not isinstance(raw, Mapping):
        raise LoaderError(f"{where}: expected a mapping, got {type(raw).__name__}")
    unknown = set(raw) - allowed
    if unknown:
        raise LoaderError(f"{where}: unknown field(s) {sorted(unknown)}")
    return raw


def _prose(raw: Any, *, where: str) -> S.Prose:
    raw = require_keys(raw, {"fallback", "accessible"}, where=f"{where}.prose")
    fallback = raw.get("fallback", "")
    accessible = raw.get("accessible", fallback)
    return S.Prose(fallback=fallback, accessible=accessible)


def _effects(raw: Any, *, where: str) -> tuple[S.Effect, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LoaderError(f"{where}: expected a list of effect ops")
    out = []
    for i, item in enumerate(raw):
        item = require_keys(item, {"op", "args"}, where=f"{where}[{i}]")
        try:
            out.append(S.Effect(op=item["op"], args=item.get("args", {}) or {}))
        except S.ContentError as exc:
            raise LoaderError(f"{where}[{i}]: {exc}") from exc
    return tuple(out)


def _load_skill(raw: Any, *, where: str) -> S.Skill:
    raw = require_keys(raw, {"id", "name", "prose", "typical_uses"}, where=where)
    return S.Skill(
        id=raw["id"],
        name=raw["name"],
        prose=_prose(raw["prose"], where=where),
        typical_uses=tuple(raw.get("typical_uses", [])),
    )


def _load_background(raw: Any, *, where: str) -> S.Background:
    raw = require_keys(
        raw,
        {
            "id",
            "name",
            "prose",
            "attribute_bonus",
            "skill_ranks",
            "starting_item_ids",
            "signature_ability",
        },
        where=where,
    )
    sig_where = f"{where}.signature_ability"
    sig_raw = require_keys(
        raw["signature_ability"], {"id", "name", "prose", "frequency", "effects"}, where=sig_where
    )
    signature = S.SignatureAbility(
        id=sig_raw["id"],
        name=sig_raw["name"],
        prose=_prose(sig_raw["prose"], where=sig_where),
        frequency=sig_raw["frequency"],
        effects=_effects(sig_raw.get("effects"), where=f"{sig_where}.effects"),
    )
    try:
        return S.Background(
            id=raw["id"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            attribute_bonus=raw["attribute_bonus"],
            skill_ranks=dict(raw["skill_ranks"]),
            starting_item_ids=tuple(raw.get("starting_item_ids", [])),
            signature_ability=signature,
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_ability(raw: Any, *, where: str) -> S.Ability:
    raw = require_keys(
        raw, {"id", "name", "prose", "trigger", "frequency", "effects", "source"}, where=where
    )
    try:
        return S.Ability(
            id=raw["id"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            trigger=raw["trigger"],
            frequency=raw["frequency"],
            effects=_effects(raw.get("effects"), where=f"{where}.effects"),
            source=raw.get("source", "general"),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_check(raw: Any, *, where: str) -> S.CardCheck:
    raw = require_keys(raw, {"attribute", "skill", "dc", "outcomes"}, where=where)
    o_where = f"{where}.outcomes"
    o_raw = require_keys(
        raw.get("outcomes", {}),
        {"strong_success", "success", "cost", "setback"},
        where=o_where,
    )
    outcomes = S.CheckOutcomes(
        strong_success=_effects(o_raw.get("strong_success"), where=f"{o_where}.strong_success"),
        success=_effects(o_raw.get("success"), where=f"{o_where}.success"),
        cost=_effects(o_raw.get("cost"), where=f"{o_where}.cost"),
        setback=_effects(o_raw.get("setback"), where=f"{o_where}.setback"),
    )
    try:
        return S.CardCheck(attribute=raw["attribute"], skill=raw["skill"], dc=raw["dc"], outcomes=outcomes)
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_card(raw: Any, *, where: str) -> S.Card:
    allowed = {
        "id",
        "name",
        "prose",
        "accessible_text",
        "timing",
        "range",
        "legal_targets",
        "keywords",
        "art_ref",
        "required_state",
        "base_effects",
        "check",
        "combination_tags",
        "end_state",
        "source",
    }
    raw = require_keys(raw, allowed, where=where)
    try:
        timing = S.CardTiming(raw["timing"])
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid timing {raw['timing']!r}") from exc
    try:
        end_state = S.CardEndState(raw.get("end_state", "discard"))
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid end_state {raw.get('end_state')!r}") from exc
    check = _load_check(raw["check"], where=f"{where}.check") if raw.get("check") else None
    try:
        return S.Card(
            id=raw["id"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            accessible_text=raw["accessible_text"],
            timing=timing,
            range=raw["range"],
            legal_targets=tuple(raw["legal_targets"]),
            keywords=tuple(raw.get("keywords", [])),
            art_ref=raw.get("art_ref", ""),
            required_state=tuple(raw.get("required_state", [])),
            base_effects=_effects(raw.get("base_effects"), where=f"{where}.base_effects"),
            check=check,
            combination_tags=tuple(raw.get("combination_tags", [])),
            end_state=end_state,
            source=raw.get("source", "general"),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_item(raw: Any, *, where: str) -> S.Item:
    allowed = {
        "id",
        "name",
        "prose",
        "slot_cost",
        "consumable",
        "granted_card_ids",
        "passive_effects",
        "use_effects",
        "tags",
        # Wave-4 herowire addition (board task #13): real weapon/equipment
        # modifiers, straight pass-through to S.Item -- see schemas.py's Item
        # for the zero-value defaults these fall back to when omitted.
        "weapon_die_faces",
        "weapon_damage_bonus",
        "weapon_accuracy_bonus",
        "passive_defense_bonus",
        "knowledge",
    }
    raw = require_keys(raw, allowed, where=where)
    try:
        return S.Item(
            id=raw["id"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            slot_cost=raw.get("slot_cost", 1),
            consumable=raw.get("consumable", False),
            granted_card_ids=tuple(raw.get("granted_card_ids", [])),
            passive_effects=_effects(raw.get("passive_effects"), where=f"{where}.passive_effects"),
            use_effects=_effects(raw.get("use_effects"), where=f"{where}.use_effects"),
            tags=tuple(raw.get("tags", [])),
            weapon_die_faces=raw.get("weapon_die_faces"),
            weapon_damage_bonus=raw.get("weapon_damage_bonus", 0),
            weapon_accuracy_bonus=raw.get("weapon_accuracy_bonus", 0),
            passive_defense_bonus=raw.get("passive_defense_bonus", 0),
            knowledge=raw.get("knowledge", False),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_condition(raw: Any, *, where: str) -> S.Condition:
    raw = require_keys(raw, {"id", "name", "prose", "primary_effect", "duration", "treatments"}, where=where)
    pe_where = f"{where}.primary_effect"
    pe_raw = require_keys(raw["primary_effect"], {"op", "args"}, where=pe_where)
    try:
        primary = S.Effect(op=pe_raw["op"], args=pe_raw.get("args", {}) or {})
    except S.ContentError as exc:
        raise LoaderError(f"{pe_where}: {exc}") from exc

    treatments = []
    for i, t_raw in enumerate(raw.get("treatments", [])):
        t_where = f"{where}.treatments[{i}]"
        t_raw = require_keys(t_raw, {"id", "prose", "effects"}, where=t_where)
        treatments.append(
            S.Treatment(
                id=t_raw["id"],
                prose=_prose(t_raw["prose"], where=t_where),
                effects=_effects(t_raw.get("effects"), where=f"{t_where}.effects"),
            )
        )
    try:
        return S.Condition(
            id=raw["id"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            primary_effect=primary,
            duration=raw["duration"],
            treatments=tuple(treatments),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_enemy(raw: Any, *, where: str) -> S.Enemy:
    allowed = {
        "id",
        "name",
        "family",
        "prose",
        "threat_tier",
        "threat_cost",
        "hp",
        "defense",
        "intents",
        "resists",
        "weaknesses",
        "non_elimination_routes",
    }
    raw = require_keys(raw, allowed, where=where)
    try:
        tier = S.ThreatTier(raw["threat_tier"])
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid threat_tier {raw['threat_tier']!r}") from exc

    intents = []
    for i, intent_raw in enumerate(raw.get("intents", [])):
        i_where = f"{where}.intents[{i}]"
        intent_raw = require_keys(intent_raw, {"id", "prose", "trigger", "effects", "counterplay"}, where=i_where)
        try:
            intents.append(
                S.EnemyIntent(
                    id=intent_raw["id"],
                    prose=_prose(intent_raw["prose"], where=i_where),
                    trigger=intent_raw["trigger"],
                    effects=_effects(intent_raw.get("effects"), where=f"{i_where}.effects"),
                    counterplay=intent_raw["counterplay"],
                )
            )
        except S.ContentError as exc:
            raise LoaderError(f"{i_where}: {exc}") from exc

    try:
        return S.Enemy(
            id=raw["id"],
            name=raw["name"],
            family=raw["family"],
            prose=_prose(raw["prose"], where=where),
            threat_tier=tier,
            threat_cost=raw["threat_cost"],
            hp=raw["hp"],
            defense=raw["defense"],
            intents=tuple(intents),
            resists=tuple(raw.get("resists", [])),
            weaknesses=tuple(raw.get("weaknesses", [])),
            non_elimination_routes=tuple(raw.get("non_elimination_routes", [])),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_puzzle_template_meta(raw: Any, *, where: str) -> S.PuzzleTemplateMeta:
    raw = require_keys(raw, {"id", "family", "name", "prose", "difficulty_range"}, where=where)
    dr = raw.get("difficulty_range", [1, 5])
    try:
        return S.PuzzleTemplateMeta(
            id=raw["id"],
            family=raw["family"],
            name=raw["name"],
            prose=_prose(raw["prose"], where=where),
            difficulty_range=tuple(dr),
        )
    except S.ContentError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


_ITEM_FILES: dict[str, tuple[str, str, Callable[..., Any]]] = {
    "skills": ("skills.yaml", "skills", _load_skill),
    "backgrounds": ("backgrounds.yaml", "backgrounds", _load_background),
    "abilities": ("abilities.yaml", "abilities", _load_ability),
    "cards": ("cards.yaml", "cards", _load_card),
    "items": ("items.yaml", "items", _load_item),
    "conditions": ("conditions.yaml", "conditions", _load_condition),
    "enemies": ("enemies.yaml", "enemies", _load_enemy),
}


def load_yaml_file(path: Path) -> Any:
    if not path.exists():
        raise LoaderError(f"{path}: file not found")
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise LoaderError(f"{path}: invalid YAML: {exc}") from exc


def _load_collection(
    pack_dir: Path, filename: str, top_key: str, item_loader: Callable[..., Any]
) -> dict[str, Any]:
    path = pack_dir / filename
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, Mapping) or top_key not in raw:
        raise LoaderError(f"{path}: expected top-level key {top_key!r}")
    items_raw = raw[top_key]
    if not isinstance(items_raw, list):
        raise LoaderError(f"{path}: {top_key!r} must be a list")

    items: dict[str, Any] = {}
    for i, item_raw in enumerate(items_raw):
        where = f"{path.name}:{top_key}[{i}]"
        obj = item_loader(item_raw, where=where)
        if obj.id in items:
            raise LoaderError(f"{where}: duplicate id {obj.id!r}")
        items[obj.id] = obj
    return items


def load_puzzle_templates(puzzles_dir: Path) -> dict[str, S.PuzzleTemplateMeta]:
    templates: dict[str, S.PuzzleTemplateMeta] = {}
    if not puzzles_dir.exists():
        return templates
    for path in sorted(puzzles_dir.glob("*.yaml")):
        raw = load_yaml_file(path) or {}
        if not isinstance(raw, Mapping) or "puzzle_template" not in raw:
            raise LoaderError(f"{path}: expected top-level key 'puzzle_template'")
        meta = _load_puzzle_template_meta(raw["puzzle_template"], where=f"{path.name}:puzzle_template")
        if meta.id in templates:
            raise LoaderError(f"{path}: duplicate puzzle template id {meta.id!r}")
        templates[meta.id] = meta
    return templates


def load_pack(pack_dir: Path, *, pack_id: str) -> S.ContentPack:
    """Load and structurally validate every YAML file in `pack_dir`.

    Raises `LoaderError` on the first malformed file. Cross-file reference
    checks (e.g. a card referencing an unknown item) live in `validators.py`,
    which runs against the returned `ContentPack`.
    """

    collections = {
        attr: _load_collection(pack_dir, filename, top_key, item_loader)
        for attr, (filename, top_key, item_loader) in _ITEM_FILES.items()
    }
    puzzle_templates = load_puzzle_templates(pack_dir / "puzzles")

    return S.ContentPack(
        schema_version=S.CONTENT_SCHEMA_VERSION,
        pack_id=pack_id,
        backgrounds=collections["backgrounds"],
        skills=collections["skills"],
        abilities=collections["abilities"],
        cards=collections["cards"],
        items=collections["items"],
        conditions=collections["conditions"],
        enemies=collections["enemies"],
        puzzle_templates=puzzle_templates,
    )


def load_core_pack() -> S.ContentPack:
    return load_pack(CORE_PACK_DIR, pack_id="core")
