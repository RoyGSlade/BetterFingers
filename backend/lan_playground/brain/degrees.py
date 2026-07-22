"""Social degrees (wavebasedgame.md §3.6, infinite_stacks.md §12.1-12.3):
engine-computed DC for a social check, an authored-tier `-5..+5` contextual
modifier, and rich outcome kinds mapped onto the existing §12.3 degree
table.

This module deliberately duplicates the §12.3 margin table (`SocialOutcome`/
`outcome_for_margin` below) rather than importing
`backend.lan_playground.systems.checks` -- this package may not import
`systems`/`domain` at all (pure-package rule), the same reason `heroes/`
literally duplicates `combat.models.ATTRIBUTE_NAMES`/`SKILL_NAMES` instead
of importing them. `tests/test_stacks_brain.py` carries a drift-guard test
against `systems.checks.Outcome`/`outcome_for_margin`, mirroring
`test_stacks_heroes.py::test_attribute_and_skill_names_match_combat_models_exactly`,
so a change to one table is caught immediately rather than silently
diverging.

The critical accessibility guarantee (testable property, not just a
docstring promise): every input to the `-5..+5` modifier is an in-world
evidence/leverage/motive enum. There is no code path anywhere in this
module that accepts free text, a grammar/eloquence score, a verbosity
count, or any other delivery-based signal as a modifier input.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

MIN_MODIFIER = -5
MAX_MODIFIER = 5


class SocialOutcome(str, Enum):
    """Literal duplicate of `systems.checks.Outcome` -- see module docstring
    for why this isn't an import. Values match exactly so downstream event
    payloads read identically regardless of which check produced them."""

    STRONG_SUCCESS = "strong_success"      # margin >= 5
    CLEAN_SUCCESS = "clean_success"        # 0 <= margin <= 4
    COST_PROGRESS = "cost_progress"        # -4 <= margin <= -1
    SETBACK = "setback"                    # margin <= -5


def outcome_for_margin(margin: int) -> SocialOutcome:
    """Literal duplicate of `systems.checks.outcome_for_margin` -- see
    module docstring. Kept byte-for-byte identical on purpose; the
    drift-guard test in tests/test_stacks_brain.py enforces this."""
    if margin >= 5:
        return SocialOutcome.STRONG_SUCCESS
    if margin >= 0:
        return SocialOutcome.CLEAN_SUCCESS
    if margin >= -4:
        return SocialOutcome.COST_PROGRESS
    return SocialOutcome.SETBACK


# Suggested visible DCs (infinite_stacks.md §12.1), duplicated for the same
# import-boundary reason as SocialOutcome above.
DC_ROUTINE = 8
DC_STANDARD = 11
DC_DIFFICULT = 14
DC_SEVERE = 17
DC_EXTRAORDINARY = 20


class EvidenceTier(str, Enum):
    """In-world evidence/leverage enum -- one of the two structural inputs
    to the contextual modifier. Every member is something a game rule can
    point at (an item, a fact, a witnessed event), never a delivery signal.
    """

    NONE = "none"                                  # no leverage / plausible cover story -> 0
    CIRCUMSTANTIAL = "circumstantial"               # suggestive but deniable -> +1..+2
    VERIFIABLE = "verifiable"                       # confirmed true, checkable -> +2..+3
    FORGED_VERIFIABLE = "forged_verifiable"         # forged but passes verification -> +3..+5
    CONTRADICTED = "contradicted"                   # evidence the NPC can disprove -> -2..-4


class MotiveAlignment(str, Enum):
    """In-world motive-alignment enum -- how well the ask lines up with the
    NPC's authored objectives/fears, never a tone/politeness score."""

    STRONGLY_ALIGNED = "strongly_aligned"           # serves a stated objective -> +2..+4
    NEUTRAL = "neutral"                             # no particular pull either way -> 0
    THREATENS_STATED_FEAR = "threatens_stated_fear"  # no offsetting motive -> -3..-5
    CONTRADICTS_OBJECTIVE = "contradicts_objective"  # actively works against a goal -> -2..-4


@dataclass(frozen=True)
class ModifierTier:
    """One authored tier of the contextual `-5..+5` modifier: a label, the
    inclusive value range it may produce, and which in-world enum(s) it
    keys off. Authors add tiers as data; nothing here reads free text."""

    label: str
    min_value: int
    max_value: int

    def __post_init__(self) -> None:
        if self.min_value < MIN_MODIFIER or self.max_value > MAX_MODIFIER:
            raise ValueError(f"tier {self.label!r} range must be within [{MIN_MODIFIER}, {MAX_MODIFIER}]")
        if self.min_value > self.max_value:
            raise ValueError(f"tier {self.label!r} has min_value > max_value")

    def clamp(self, value: int) -> int:
        return max(self.min_value, min(self.max_value, value))


# Authored data tiers (wavebasedgame.md §3.6's worked examples), keyed by
# the in-world enum they read. Purely data -- adding/adjusting a tier never
# touches the resolution code below.
EVIDENCE_MODIFIER_TIERS = {
    EvidenceTier.NONE: ModifierTier("no leverage / plausible cover story", 0, 0),
    EvidenceTier.CIRCUMSTANTIAL: ModifierTier("circumstantial, deniable evidence", 1, 2),
    EvidenceTier.VERIFIABLE: ModifierTier("confirmed, checkable evidence", 2, 3),
    EvidenceTier.FORGED_VERIFIABLE: ModifierTier("forged, verifiable evidence in hand", 3, 5),
    EvidenceTier.CONTRADICTED: ModifierTier("evidence the NPC can disprove", -4, -2),
}

MOTIVE_MODIFIER_TIERS = {
    MotiveAlignment.STRONGLY_ALIGNED: ModifierTier("directly serves a stated NPC objective", 2, 4),
    MotiveAlignment.NEUTRAL: ModifierTier("no particular motive pull", 0, 0),
    MotiveAlignment.THREATENS_STATED_FEAR: ModifierTier("threatens a stated fear, no offsetting motive", -5, -3),
    MotiveAlignment.CONTRADICTS_OBJECTIVE: ModifierTier("actively works against a stated objective", -4, -2),
}


@dataclass(frozen=True)
class SocialModifierInputs:
    """The only accepted inputs to the contextual modifier -- structurally
    just two in-world enums (plus an optional within-tier nudge for content
    authors), nothing text-shaped. This is the type-level half of the
    accessibility guarantee: there is no `str` field here a caller could
    stuff free text into and have it read as a modifier signal."""

    evidence: EvidenceTier = EvidenceTier.NONE
    motive: MotiveAlignment = MotiveAlignment.NEUTRAL
    evidence_nudge: int = 0  # authored fine-tune within the evidence tier's own range
    motive_nudge: int = 0    # authored fine-tune within the motive tier's own range


def compute_contextual_modifier(inputs: SocialModifierInputs) -> int:
    """Compute the `-5..+5` contextual modifier purely from in-world
    evidence/motive enums (wavebasedgame.md §3.6). Structurally cannot
    exceed +-5: each tier's own range is already inside [-5, 5], the two
    tiers are summed and then clamped again as a final backstop, and no
    additional signal (grammar, eloquence, verbosity, disability, or
    flattering the model) is ever read here."""
    evidence_tier = EVIDENCE_MODIFIER_TIERS[inputs.evidence]
    motive_tier = MOTIVE_MODIFIER_TIERS[inputs.motive]

    evidence_value = evidence_tier.clamp(evidence_tier.min_value + inputs.evidence_nudge)
    motive_value = motive_tier.clamp(motive_tier.min_value + inputs.motive_nudge)

    total = evidence_value + motive_value
    return max(MIN_MODIFIER, min(MAX_MODIFIER, total))


class RichOutcomeKind(str, Enum):
    """Outcome kinds richer than plain pass/fail, layered on top of the
    §12.3 margin table (wavebasedgame.md §3.6)."""

    PARTIAL_CONCESSION = "partial_concession"
    COUNTEROFFER = "counteroffer"
    LIE = "lie"
    DISPOSITION_CHANGE = "disposition_change"
    OBJECTIVE_CHANGE = "objective_change"
    NEW_DANGER = "new_danger"
    BEHAVIORAL_TELL = "behavioral_tell"


# Which rich outcome kinds are even eligible at a given margin bucket --
# authored data, not a decision the model or free text ever makes. A caller
# (domain wiring) still picks the specific kind (e.g. via content data for
# this NPC); this only bounds what's structurally possible per bucket.
ELIGIBLE_RICH_OUTCOMES = {
    SocialOutcome.STRONG_SUCCESS: (
        RichOutcomeKind.DISPOSITION_CHANGE,
        RichOutcomeKind.OBJECTIVE_CHANGE,
    ),
    SocialOutcome.CLEAN_SUCCESS: (
        RichOutcomeKind.PARTIAL_CONCESSION,
        RichOutcomeKind.DISPOSITION_CHANGE,
    ),
    SocialOutcome.COST_PROGRESS: (
        RichOutcomeKind.PARTIAL_CONCESSION,
        RichOutcomeKind.COUNTEROFFER,
        RichOutcomeKind.BEHAVIORAL_TELL,
    ),
    SocialOutcome.SETBACK: (
        RichOutcomeKind.LIE,
        RichOutcomeKind.NEW_DANGER,
        RichOutcomeKind.OBJECTIVE_CHANGE,
    ),
}


@dataclass(frozen=True)
class SocialDCInputs:
    """Every declared input the engine uses to compute a social DC
    (wavebasedgame.md §3.6): concession value, NPC stats/resolve, risk,
    disposition, objectives, relationship, evidence, approach. Each is a
    small int/enum-shaped contribution; the function below sums them and
    clamps to the nearest §12.1 named DC."""

    concession_value: int = 0     # how big an ask this is, in DC points
    npc_resolve: int = 0          # NPC stat/resolve contribution
    risk: int = 0                 # situational risk contribution
    disposition: int = 0          # current NPC disposition toward the party (negative = hostile)
    objective_friction: int = 0   # how much the ask cuts against NPC objectives
    relationship: int = 0         # prior relationship/history contribution (negative = strained)
    approach_penalty: int = 0     # a strongly counterproductive approach (§3.6), always >= 0


_NAMED_DCS = (DC_ROUTINE, DC_STANDARD, DC_DIFFICULT, DC_SEVERE, DC_EXTRAORDINARY)


def compute_social_dc(inputs: SocialDCInputs) -> int:
    """Sum every declared DC contribution and clamp to at least the lowest
    named DC (routine, 8) -- a social check is never trivially free, and
    there is no upper clamp so extraordinary asks can exceed 20+ per
    §12.1's own "20+" convention."""
    raw = (
        DC_STANDARD  # baseline: a social ask starts "standard" before adjustment
        + inputs.concession_value
        + inputs.npc_resolve
        + inputs.risk
        - inputs.disposition
        + inputs.objective_friction
        - inputs.relationship
        + inputs.approach_penalty
    )
    return max(DC_ROUTINE, raw)


@dataclass(frozen=True)
class SocialCheckResult:
    """The engine-facing result of resolving a social check: everything a
    Narrator/NPC-Performer packet needs, and nothing a model computed."""

    dc: int
    modifier: int
    total: int
    margin: int
    outcome: SocialOutcome
    eligible_rich_outcomes: tuple = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "eligible_rich_outcomes", tuple(self.eligible_rich_outcomes))


def resolve_social_check(
    *,
    d20_roll: int,
    attribute_score: int,
    skill_rank: int,
    dc_inputs: SocialDCInputs,
    modifier_inputs: SocialModifierInputs,
) -> SocialCheckResult:
    """Resolve a full social check: `d20 + attribute + skill + contextual
    modifier` against an engine-computed DC (wavebasedgame.md §3.6),
    mapped onto the existing §12.3 degree table. The d20 roll itself is
    never performed by this package (randomness stays with the engine's
    injected RNG elsewhere) -- this function only combines an already-
    rolled value with the rest of the formula."""
    dc = compute_social_dc(dc_inputs)
    modifier = compute_contextual_modifier(modifier_inputs)
    total = d20_roll + attribute_score + skill_rank + modifier
    margin = total - dc
    outcome = outcome_for_margin(margin)
    return SocialCheckResult(
        dc=dc,
        modifier=modifier,
        total=total,
        margin=margin,
        outcome=outcome,
        eligible_rich_outcomes=ELIGIBLE_RICH_OUTCOMES[outcome],
    )
