"""Seed-driven generator for the ordering/sequence Mystery Chamber template.

Family: infinite_stacks.md §10.3 #1 ("ordering and sequence constraints"),
registered as `core_ordering_sequence` in
`content/packs/core/puzzles/ordering_sequence.yaml`.

Four-object structure (§10.2), mapped onto ordering facts about a shelf of
damaged index cards:

- **Anchor**: one absolute `position(item, p)` fact -- dependable, unconditional.
- **Key**: the full directed chain of `immediately_before(a, b)` facts linking
  every consecutive pair in the true order. This alone determines the unique
  solution; anchor and contradiction corroborate rather than gate it.
- **Contradiction**: a `not_position(item, p)` fact that reads as correcting a
  plausible but wrong assumption (an old, superseded label).
- **Red herring**: a true but non-essential `before(a, b)` fact, already
  implied by the key chain.

Every clue's `reveals` dict is the structured fact `solver.py` consumes.
`solver.py` is intentionally a separate module with no shared code -- see its
docstring for why that separation matters.
"""

from __future__ import annotations

import random

from .. import schemas as S

TEMPLATE_ID = "core_ordering_sequence"

_ITEM_NAMES = [
    "Fireproofing Codes",
    "Root Cellar Almanac",
    "Border Ink Treaty",
    "Weathered Tide Log",
    "Broken Loom Manual",
    "Salt Circuit Primer",
]


def _n_items_for_difficulty(difficulty: int) -> int:
    return 4 + min(difficulty - 1, 2)  # difficulty 1-5 -> 4..6 items


def item_name(item_id: str) -> str:
    """Public helper so callers (including tests) can render an item id
    without depending on `_ITEM_NAMES` directly."""

    index = int(item_id.rsplit("_", 1)[-1])
    return _ITEM_NAMES[index]


def generate_instance(seed: int, difficulty: int = 1) -> S.PuzzleInstance:
    if not (1 <= difficulty <= 5):
        raise ValueError(f"difficulty must be 1-5, got {difficulty}")

    rng = random.Random(seed)
    n = _n_items_for_difficulty(difficulty)
    item_ids = [f"card_{i}" for i in range(n)]

    solution = item_ids[:]
    rng.shuffle(solution)  # the true shelf order, position 0..n-1
    pos = {item: i for i, item in enumerate(solution)}

    clues: list[S.PuzzleClue] = []

    def add_clue(clue_id: str, fallback: str, accessible: str, reveals: dict) -> str:
        clues.append(
            S.PuzzleClue(
                id=clue_id,
                prose=S.Prose(fallback=fallback, accessible=accessible),
                viewer_scope=S.ViewerScope.PUBLIC,
                reveals=reveals,
            )
        )
        return clue_id

    # --- Anchor: one absolute, dependable position fact ---
    anchor_item = solution[0]
    anchor_clue_id = add_clue(
        "clue_anchor_position",
        f"A brass plate on {item_name(anchor_item)} reads 'Shelf position 1.'",
        f"Anchor clue: {item_name(anchor_item)} is at shelf position 1.",
        {"type": "position", "item": anchor_item, "position": 0},
    )

    # --- Key: the full directed chain, sufficient on its own for a unique order ---
    key_clue_ids = []
    for i in range(n - 1):
        a, b = solution[i], solution[i + 1]
        cid = add_clue(
            f"clue_key_{i}",
            f"A binding thread runs from {item_name(a)} straight into {item_name(b)}.",
            f"Key clue: {item_name(a)} sits immediately before {item_name(b)}.",
            {"type": "immediately_before", "a": a, "b": b},
        )
        key_clue_ids.append(cid)

    # --- Contradiction: rules out a wrong position an old label suggests ---
    contra_item = solution[-1]
    wrong_pos = 0 if pos[contra_item] != 0 else n - 1
    contradiction_clue_id = add_clue(
        "clue_contradiction",
        f"A torn label suggests {item_name(contra_item)} belongs at position 1 -- "
        "but the tear is old, from before the shelf was rebuilt, and no longer applies.",
        f"Contradiction clue: despite the torn label, {item_name(contra_item)} is "
        "NOT at shelf position 1.",
        {"type": "not_position", "item": contra_item, "position": wrong_pos},
    )

    # --- Red herring: true, informative, not required ---
    herring_clue_id = add_clue(
        "clue_red_herring",
        f"{item_name(solution[0])} was reshelved long before {item_name(solution[-1])}.",
        f"Red herring: {item_name(solution[0])} comes somewhere before "
        f"{item_name(solution[-1])} (true, but already implied by the key clues).",
        {"type": "before", "a": solution[0], "b": solution[-1]},
    )

    objects = (
        S.PuzzleObject(
            id="obj_anchor",
            role=S.PuzzleObjectRole.ANCHOR,
            prose=S.Prose(
                fallback="A brass-plated index card, clearly labeled.",
                accessible="Object: anchor. A brass-plated index card with a position stamped on it.",
            ),
            clue_ids=(anchor_clue_id,),
        ),
        S.PuzzleObject(
            id="obj_key",
            role=S.PuzzleObjectRole.KEY,
            prose=S.Prose(
                fallback="A bundle of index cards tied together with binding thread.",
                accessible="Object: key. A bundle of index cards connected by binding "
                "thread, each thread showing which card leads into which.",
            ),
            clue_ids=tuple(key_clue_ids),
        ),
        S.PuzzleObject(
            id="obj_contradiction",
            role=S.PuzzleObjectRole.CONTRADICTION,
            prose=S.Prose(
                fallback="A card with a torn, half-legible label.",
                accessible="Object: contradiction. A card with an old, torn label that no longer applies.",
            ),
            clue_ids=(contradiction_clue_id,),
        ),
        S.PuzzleObject(
            id="obj_red_herring",
            role=S.PuzzleObjectRole.RED_HERRING,
            prose=S.Prose(
                fallback="A dusty ledger noting when each card was last reshelved.",
                accessible="Object: red herring. A dusty ledger recording reshelving "
                "dates -- true, but not required to solve the puzzle.",
            ),
            clue_ids=(herring_clue_id,),
        ),
    )

    hint1 = S.Prose(
        fallback=f"Focus on the anchor: {item_name(anchor_item)} sits at shelf position 1.",
        accessible=f"Hint 1: the anchor card {item_name(anchor_item)} is at position 1.",
    )
    hint2 = S.Prose(
        fallback="The key clues form a chain -- each names one card immediately before "
        "another. Follow the chain forward from the anchor.",
        accessible="Hint 2: chain the key clues together starting from the anchor's "
        "position to build the full order.",
    )
    hint3 = S.Prose(
        fallback=(
            f"Next valid placement: put {item_name(solution[0])} at position 1, "
            f"immediately followed by {item_name(solution[1])} at position 2."
        ),
        accessible=(
            f"Hint 3: place {item_name(solution[0])} at position 1 and "
            f"{item_name(solution[1])} at position 2."
        ),
    )

    solution_tuple = tuple(solution)
    instance_id = f"puzzle_core_ordering_sequence_{seed}_{difficulty}"

    return S.PuzzleInstance(
        id=instance_id,
        template_id=TEMPLATE_ID,
        seed=seed,
        difficulty=difficulty,
        objects=objects,
        clues=tuple(clues),
        private_clue_assignments={},
        solution=solution_tuple,
        accepted_solutions=(solution_tuple,),
        hint_steps=(hint1, hint2, hint3),
        attempt_limit=3,
        failure_events=(S.Effect(op="emit_fact", args={"fact_id": "reshelving_failed"}),),
        success_events=(S.Effect(op="emit_fact", args={"fact_id": "reshelving_solved"}),),
        reward_table="core_puzzle_rewards",
        validator_version="1.0.0",
    )
