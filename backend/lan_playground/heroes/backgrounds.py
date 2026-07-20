"""Apply §11.3 backgrounds from content-pack data.

Backgrounds are read as data (a `content.schemas.Background`-shaped object,
duck-typed -- see `BackgroundLike` below) rather than imported: this module
never imports `content.schemas` or `content.loader` at runtime, so it stays
pure and I/O-free (the same "content pack data passed IN as parsed data, not
imported" rule the deck/inventory/cards modules follow). Callers load the
real pack (`content.loader.load_core_pack()`) and pass `pack.backgrounds[id]`
in.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Mapping, Protocol

from .creation import Attributes, CreationError

if TYPE_CHECKING:  # pragma: no cover -- type hints only, never imported at runtime
    from ..content.schemas import Background


class BackgroundLike(Protocol):
    """Structural shape this module needs from a background definition --
    exactly `content.schemas.Background`'s public fields, duck-typed so no
    import of that module is required."""

    id: str
    attribute_bonus: str
    skill_ranks: Mapping[str, int]
    starting_item_ids: tuple[str, ...]
    signature_ability: "SignatureAbilityLike"


class SignatureAbilityLike(Protocol):
    id: str
    frequency: str  # "once_per_floor" | "once_per_room" | "once_per_fight"


def apply_background_bonus(attributes: Attributes, background: "BackgroundLike | Background") -> Attributes:
    """+1 to the background's listed attribute, capped at 5 (§11.3, §11.1)."""

    return attributes.with_bonus(background.attribute_bonus, amount=1)


def starting_skill_ranks(background: "BackgroundLike | Background") -> dict[str, int]:
    return dict(background.skill_ranks)


def starting_item_ids(background: "BackgroundLike | Background") -> tuple[str, ...]:
    return tuple(background.starting_item_ids)


# ---------------------------------------------------------------------------
# Signature abilities as charges (§11.3: once-per-floor/room/fight powers)
# ---------------------------------------------------------------------------


class SignatureChargeError(ValueError):
    pass


_CHARGES_BY_FREQUENCY = {
    "once_per_floor": 1,
    "once_per_room": 1,
    "once_per_fight": 1,
}


@dataclass(frozen=True)
class SignatureCharge:
    """A hook, not a full recharge system: wave-4 domain owns the actual
    floor/room/fight boundaries that refill a charge (`refreshed()` below is
    the seam it calls). This wave only tracks "does the hero have a charge
    available right now"."""

    ability_id: str
    frequency: str
    charges_remaining: int
    max_charges: int

    def spend(self) -> "SignatureCharge":
        if self.charges_remaining <= 0:
            raise SignatureChargeError(
                f"signature ability {self.ability_id!r} has no charges remaining this "
                f"{self.frequency.removeprefix('once_per_')}"
            )
        return SignatureCharge(
            ability_id=self.ability_id,
            frequency=self.frequency,
            charges_remaining=self.charges_remaining - 1,
            max_charges=self.max_charges,
        )

    def refreshed(self) -> "SignatureCharge":
        """Called by wave-4 domain at the boundary named by `frequency`
        (new floor / new room / new fight)."""

        return SignatureCharge(
            ability_id=self.ability_id,
            frequency=self.frequency,
            charges_remaining=self.max_charges,
            max_charges=self.max_charges,
        )


def initial_signature_charge(background: "BackgroundLike | Background") -> SignatureCharge:
    ability = background.signature_ability
    max_charges = _CHARGES_BY_FREQUENCY.get(ability.frequency)
    if max_charges is None:
        raise SignatureChargeError(
            f"background {background.id!r} signature ability {ability.id!r} has unknown "
            f"frequency {ability.frequency!r} (expected one of {sorted(_CHARGES_BY_FREQUENCY)})"
        )
    return SignatureCharge(
        ability_id=ability.id,
        frequency=ability.frequency,
        charges_remaining=max_charges,
        max_charges=max_charges,
    )


# ---------------------------------------------------------------------------
# §11.3 data hooks the content schema has no field for yet -- explicit,
# narrow, and documented rather than silently baked into a generic system.
# ---------------------------------------------------------------------------

# Traveling Charlatan: "a concealed item slot" (§11.3) -- one bonus carry slot
# content/schemas.py's Background has no field for this yet (editing that
# schema is out of this wave's claimed files), so it is named here explicitly
# rather than invented as a generic per-background numeric field.
CONCEALED_ITEM_SLOT_BONUS = {"traveling_charlatan": 1}


def bonus_carry_slots(background: "BackgroundLike | Background") -> int:
    return CONCEALED_ITEM_SLOT_BONUS.get(background.id, 0)
