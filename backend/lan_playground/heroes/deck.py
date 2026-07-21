"""Deck lifecycle (infinite_stacks.md §13.2): starting deck composition,
draw, play (discard/Exhaust), safe-rest reshuffle, and Exhausted recovery.

Card definitions are passed in as data (a `card_lookup: Mapping[str, CardLike]`
built from a loaded content pack, e.g. `pack.cards`) -- this module never
imports `content.schemas` or `content.loader`. `cards.py` is the only place
that inspects a card's *effects*; this module only reads `timing`/`end_state`
(duck-typed strings/enum members, compared by `.value` or `str()` so it does
not need `content.schemas.CardTiming`/`CardEndState` imported either).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from . import cards as C
from .rng import HeroesRNG

if TYPE_CHECKING:  # pragma: no cover
    from ..content.schemas import Card

BACKGROUND_CARD_COUNT = 4
GENERAL_CARD_COUNT = 2
PERSONA_CARD_COUNT = 1
MAX_EQUIPMENT_CARDS = 2


class DeckError(ValueError):
    pass


class DeckCardLike(Protocol):
    id: str
    timing: Any  # CardTiming-like; compared via str(...)
    end_state: Any  # CardEndState-like; compared via str(...)


def _is_reaction(card: "DeckCardLike | Card") -> bool:
    value = getattr(card.timing, "value", card.timing)
    return value == "reaction"


def _end_state(card: "DeckCardLike | Card") -> str:
    value = getattr(card.end_state, "value", card.end_state)
    return str(value)


@dataclass(frozen=True)
class DeckState:
    hero_id: str
    deck: tuple[str, ...] = ()
    hand: tuple[str, ...] = ()
    discard: tuple[str, ...] = ()
    exhausted: tuple[str, ...] = ()


def build_starting_deck(
    hero_id: str,
    *,
    background_card_ids: Sequence[str],
    general_card_ids: Sequence[str],
    persona_card_id: str,
    equipment_card_ids: Sequence[str] = (),
    card_lookup: Mapping[str, "DeckCardLike | Card"],
    rng: HeroesRNG,
) -> DeckState:
    """§13.2: four background cards, two selected general cards, one persona
    signature card, up to two equipment-granted cards. Every card must
    compile to LIVE effect ops (`cards.compile_deck_card_pool`) -- a card that
    doesn't FAILS LOUDLY here, before the deck exists, not when it is later
    drawn or played."""

    if len(background_card_ids) != BACKGROUND_CARD_COUNT:
        raise DeckError(
            f"starting deck needs exactly {BACKGROUND_CARD_COUNT} background cards, "
            f"got {len(background_card_ids)}"
        )
    if len(general_card_ids) != GENERAL_CARD_COUNT:
        raise DeckError(
            f"starting deck needs exactly {GENERAL_CARD_COUNT} selected general cards, "
            f"got {len(general_card_ids)}"
        )
    if len(equipment_card_ids) > MAX_EQUIPMENT_CARDS:
        raise DeckError(
            f"starting deck allows at most {MAX_EQUIPMENT_CARDS} equipment-granted cards, "
            f"got {len(equipment_card_ids)}"
        )

    all_ids = (
        tuple(background_card_ids)
        + tuple(general_card_ids)
        + (persona_card_id,)
        + tuple(equipment_card_ids)
    )
    C.compile_deck_card_pool(all_ids, card_lookup)  # build-time gate: raises loudly

    return DeckState(hero_id=hero_id, deck=tuple(rng.shuffled(list(all_ids))))


def draw(state: DeckState, count: int) -> DeckState:
    """Draw up to `count` cards from the deck into hand. Does not
    auto-reshuffle -- an empty deck simply yields fewer cards; reshuffling
    only happens on a safe rest (§13.2)."""

    if count < 0:
        raise DeckError("draw count must be >= 0")
    drawn = state.deck[:count]
    remaining = state.deck[count:]
    return DeckState(
        hero_id=state.hero_id,
        deck=remaining,
        hand=state.hand + drawn,
        discard=state.discard,
        exhausted=state.exhausted,
    )


def play_card(state: DeckState, card_id: str, card_lookup: Mapping[str, "DeckCardLike | Card"]) -> DeckState:
    """Move a played card from hand to discard or Exhaust, per its own
    `end_state` (§13.2)."""

    if card_id not in state.hand:
        raise DeckError(f"card {card_id!r} is not in hand")
    if card_id not in card_lookup:
        raise KeyError(f"unknown card id {card_id!r}")

    hand = list(state.hand)
    hand.remove(card_id)
    end_state = _end_state(card_lookup[card_id])
    discard, exhausted = list(state.discard), list(state.exhausted)
    if end_state == "exhaust":
        exhausted.append(card_id)
    else:
        discard.append(card_id)
    return DeckState(
        hero_id=state.hero_id,
        deck=state.deck,
        hand=tuple(hand),
        discard=tuple(discard),
        exhausted=tuple(exhausted),
    )


def safe_rest_reshuffle(state: DeckState, rng: HeroesRNG) -> DeckState:
    """A safe rest reshuffles discard back into the deck (§13.2). Exhausted
    cards are untouched -- they need the stronger recovery rule below."""

    reshuffled = rng.shuffled(list(state.deck) + list(state.discard))
    return DeckState(
        hero_id=state.hero_id,
        deck=tuple(reshuffled),
        hand=state.hand,
        discard=(),
        exhausted=state.exhausted,
    )


def recover_exhausted_card(state: DeckState, card_id: str) -> DeckState:
    """The "stronger recovery rule" (§13.2) Exhausted cards need: an explicit,
    opt-in recovery of exactly one card back into the discard pile (never
    automatic on an ordinary safe rest). Callers gate *when* this may be
    invoked (a specific item, a full-floor rest, a rare room effect) -- that
    policy belongs to wave-4 domain wiring, not this pure package."""

    if card_id not in state.exhausted:
        raise DeckError(f"card {card_id!r} is not Exhausted")
    exhausted = list(state.exhausted)
    exhausted.remove(card_id)
    return DeckState(
        hero_id=state.hero_id,
        deck=state.deck,
        hand=state.hand,
        discard=state.discard + (card_id,),
        exhausted=tuple(exhausted),
    )


def reaction_cards_in_hand(
    state: DeckState, card_lookup: Mapping[str, "DeckCardLike | Card"]
) -> tuple[str, ...]:
    """Cards in hand flagged for other-turn (reaction) play (§13.2)."""

    return tuple(card_id for card_id in state.hand if _is_reaction(card_lookup[card_id]))
