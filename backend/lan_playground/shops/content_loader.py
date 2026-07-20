"""Shop content: pack loading + cross-reference validation (infinite_stacks.md
§9.6; board tasks #15/#18).

Wave 4 shipped `shops.models`'s authored/runtime dataclasses with shop-YAML
loading and shop-specific validation living on the *content* side
(`content/loader.py`'s `load_shops`/`load_core_shops`, `content/validators.py`'s
`check_shop_item_references`/`validate_core_pack_and_shops`), because
`content/schemas.py` was off-limits to the shops lane that wave. That produced
a documented backwards dependency edge (content -> shops), the opposite of
every other package's discipline: heroes/combat content never imports the
package, the package never imports content.

Wave 5 (board task #18, layering cleanup) removes that edge by relocating the
*entry point* here rather than moving `shops.models`'s ShopArchetype family
into `content/schemas.py`: nothing else in `content/` consumes those
dataclasses, so this is a zero-risk move that leaves the ECON-001-proven
`economy.py`/`services.py`/`seeding.py` modules -- and their 1000-seed
property test -- completely untouched. `content/loader.py` and
`content/validators.py` no longer import anything from `shops/`; this module
is the only place the dependency now runs, and it runs shops -> content (the
same forward direction `systems/heroes_wire.py` already uses for its own
pack lookups), never the reverse.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..content import schemas as S
from ..content.loader import CORE_PACK_DIR, LoaderError, load_pack, load_yaml_file, require_keys
from ..content.validators import Finding, ValidationError, validate_pack
from . import models as shop_models

SHOPS_FILENAME = "shops.yaml"


def _load_persona(raw: Any, *, where: str) -> shop_models.MerchantPersona:
    raw = require_keys(raw, {"name", "tagline", "tone"}, where=where)
    try:
        return shop_models.MerchantPersona(name=raw["name"], tagline=raw["tagline"], tone=raw["tone"])
    except shop_models.ShopModelError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_rumor(raw: Any, *, where: str) -> shop_models.Rumor:
    raw = require_keys(raw, {"id", "text", "accessible_text"}, where=where)
    try:
        return shop_models.Rumor(id=raw["id"], text=raw["text"], accessible_text=raw["accessible_text"])
    except shop_models.ShopModelError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_relationship_complication(raw: Any, *, where: str) -> shop_models.RelationshipComplication:
    raw = require_keys(raw, {"id", "description", "accessible_text"}, where=where)
    try:
        return shop_models.RelationshipComplication(
            id=raw["id"], description=raw["description"], accessible_text=raw["accessible_text"]
        )
    except shop_models.ShopModelError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_inventory_listing(raw: Any, *, where: str) -> shop_models.InventoryListing:
    raw = require_keys(raw, {"item_id", "buy_price", "stock"}, where=where)
    try:
        return shop_models.InventoryListing(
            item_id=raw["item_id"], buy_price=raw["buy_price"], stock=raw.get("stock")
        )
    except shop_models.ShopModelError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def _load_shop(raw: Any, *, where: str) -> shop_models.ShopArchetype:
    allowed = {
        "id",
        "name",
        "persona",
        "services",
        "sell_price_ratio",
        "repair_cost_per_wear",
        "identify_price",
        "treatment_price",
        "guaranteed_inventory",
        "rotating_pool",
        "rotating_slots",
        "rumor",
        "relationship_complication",
    }
    raw = require_keys(raw, allowed, where=where)
    try:
        services = frozenset(shop_models.ShopService(s) for s in raw.get("services", []))
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid service in {raw.get('services')!r}") from exc

    guaranteed = tuple(
        _load_inventory_listing(item, where=f"{where}.guaranteed_inventory[{i}]")
        for i, item in enumerate(raw.get("guaranteed_inventory", []))
    )
    pool = tuple(
        _load_inventory_listing(item, where=f"{where}.rotating_pool[{i}]")
        for i, item in enumerate(raw.get("rotating_pool", []))
    )
    try:
        return shop_models.ShopArchetype(
            id=raw["id"],
            name=raw["name"],
            persona=_load_persona(raw["persona"], where=f"{where}.persona"),
            services=services,
            guaranteed_inventory=guaranteed,
            rotating_pool=pool,
            rotating_slots=raw.get("rotating_slots", 0),
            sell_price_ratio=raw["sell_price_ratio"],
            repair_cost_per_wear=raw["repair_cost_per_wear"],
            identify_price=raw["identify_price"],
            treatment_price=raw["treatment_price"],
            rumor=_load_rumor(raw["rumor"], where=f"{where}.rumor"),
            relationship_complication=_load_relationship_complication(
                raw["relationship_complication"], where=f"{where}.relationship_complication"
            ),
        )
    except shop_models.ShopModelError as exc:
        raise LoaderError(f"{where}: {exc}") from exc


def load_shops(pack_dir: Path) -> dict[str, shop_models.ShopArchetype]:
    """Tolerant of a missing `shops.yaml` (returns `{}`), the same pattern
    `content.loader.load_puzzle_templates` uses for an optional pack section."""

    path = pack_dir / SHOPS_FILENAME
    if not path.exists():
        return {}
    raw = load_yaml_file(path) or {}
    if not isinstance(raw, Mapping) or "shops" not in raw:
        raise LoaderError(f"{path}: expected top-level key 'shops'")
    shops_raw = raw["shops"]
    if not isinstance(shops_raw, list):
        raise LoaderError(f"{path}: 'shops' must be a list")

    shops: dict[str, shop_models.ShopArchetype] = {}
    for i, item_raw in enumerate(shops_raw):
        where = f"{path.name}:shops[{i}]"
        shop = _load_shop(item_raw, where=where)
        if shop.id in shops:
            raise LoaderError(f"{where}: duplicate id {shop.id!r}")
        shops[shop.id] = shop
    return shops


def load_core_shops() -> dict[str, shop_models.ShopArchetype]:
    return load_shops(CORE_PACK_DIR)


# ---------------------------------------------------------------------------
# Shop item references (infinite_stacks.md §9.6, §23.2, board task #15)
# ---------------------------------------------------------------------------


def check_shop_item_references(
    shops: Mapping[str, shop_models.ShopArchetype], pack: S.ContentPack
) -> list[Finding]:
    """Every `item_id` a shop's guaranteed/rotating inventory lists must
    exist in the loaded pack's `items` (§23.2: "unknown ... item ...
    references")."""

    findings: list[Finding] = []
    for shop in shops.values():
        for listing in shop.all_listings():
            if listing.item_id not in pack.items:
                findings.append(
                    Finding("unknown_reference", f"shop:{shop.id}", f"unknown item {listing.item_id!r}")
                )
    return findings


def validate_shops(shops: Mapping[str, shop_models.ShopArchetype], pack: S.ContentPack) -> list[Finding]:
    return check_shop_item_references(shops, pack)


def validate_shops_strict(shops: Mapping[str, shop_models.ShopArchetype], pack: S.ContentPack) -> None:
    findings = validate_shops(shops, pack)
    if findings:
        raise ValidationError(findings)


def validate_core_pack_and_shops() -> tuple[S.ContentPack, dict[str, shop_models.ShopArchetype]]:
    """One-call entry point mirroring `content.validators.validate_pack_dir`,
    extended to cover the core pack's `shops.yaml`. Raises `ValidationError`
    carrying every pack finding *and* every shop finding together if any
    fire."""

    pack = load_pack(CORE_PACK_DIR, pack_id="core")
    shops = load_shops(CORE_PACK_DIR)
    findings = validate_pack(pack) + validate_shops(shops, pack)
    if findings:
        raise ValidationError(findings)
    return pack, shops
