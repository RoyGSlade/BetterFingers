"""Generator + independent-solver agreement tests for the ordering/sequence
Mystery Chamber puzzle (infinite_stacks.md §10, §10.2, §10.3 #1).

`content/puzzles/ordering_sequence.py` generates instances; `solver.py` is a
separately written verifier that only reads each clue's structured `reveals`
dict (never the instance's declared `solution`) and brute-forces the answer.
Agreement across 1000+ seeds is the acceptance bar from board task #2 and
infinite_stacks.md §10.1 / §26.1.
"""

from __future__ import annotations

import re

import pytest

from backend.lan_playground.content import schemas as S
from backend.lan_playground.content import validators as V
from backend.lan_playground.content.puzzles import ordering_sequence as OS
from backend.lan_playground.content.puzzles import generate_instance, solve, solve_instance

SEED_COUNT = 1200


def _all_instances():
    for seed in range(SEED_COUNT):
        difficulty = (seed % 5) + 1
        yield seed, difficulty, generate_instance(seed, difficulty)


def test_generate_instance_rejects_bad_difficulty():
    with pytest.raises(ValueError):
        generate_instance(seed=0, difficulty=0)
    with pytest.raises(ValueError):
        generate_instance(seed=0, difficulty=6)


def test_instance_is_deterministic_for_a_given_seed():
    a = generate_instance(seed=42, difficulty=3)
    b = generate_instance(seed=42, difficulty=3)
    assert a.solution == b.solution
    assert a.clues == b.clues
    assert a.id == b.id


def test_every_instance_has_the_four_object_structure():
    for _seed, _difficulty, instance in _all_instances():
        roles = {obj.role for obj in instance.objects}
        assert roles == {
            S.PuzzleObjectRole.ANCHOR,
            S.PuzzleObjectRole.KEY,
            S.PuzzleObjectRole.CONTRADICTION,
            S.PuzzleObjectRole.RED_HERRING,
        }


def test_generator_and_independent_solver_agree_across_seeds():
    """The core acceptance test: every instance is solvable, the solution is
    unique, and it matches what the generator claims -- verified by a solver
    that shares no code with the generator (§26.1: "puzzle generation and
    solver agreement across thousands of seeds")."""

    checked = 0
    for seed, difficulty, instance in _all_instances():
        solutions = solve_instance(instance)
        assert len(solutions) == 1, (
            f"seed={seed} difficulty={difficulty}: expected a unique solution, "
            f"solver found {len(solutions)}"
        )
        assert solutions[0] == instance.solution, (
            f"seed={seed} difficulty={difficulty}: solver answer {solutions[0]} "
            f"!= generator's claimed solution {instance.solution}"
        )
        assert instance.solution in instance.accepted_solutions
        checked += 1
    assert checked >= 1000


def test_no_unreachable_clues_across_seeds():
    """Every clue must be exposed by an object or a private assignment
    (§23.2 "unreachable puzzle solutions or endings"); this template routes
    every clue through an object, so `check_puzzle_instance` must report
    nothing for any generated instance."""

    for seed, difficulty, instance in _all_instances():
        findings = V.check_puzzle_instance(instance)
        assert findings == [], f"seed={seed} difficulty={difficulty}: {findings}"


def test_hints_are_consistent_with_the_answer():
    """Hint 1 must name the anchor's true position; hint 3 must name the
    first two items of the true order, in the correct adjacent sequence
    (§10.4: hints may reveal a valid operation but must never contradict the
    verified answer)."""

    for seed, difficulty, instance in _all_instances():
        solution = instance.solution
        hint1, hint2, hint3 = instance.hint_steps

        anchor_name = OS.item_name(solution[0])
        assert anchor_name in hint1.fallback
        assert "position 1" in hint1.fallback

        assert "key clues" in hint2.fallback.lower()

        first_name = OS.item_name(solution[0])
        second_name = OS.item_name(solution[1])
        assert first_name in hint3.fallback
        assert second_name in hint3.fallback
        assert hint3.fallback.index(first_name) < hint3.fallback.index(second_name), (
            f"seed={seed} difficulty={difficulty}: hint 3 names {second_name} before "
            f"{first_name}, contradicting the true order"
        )


def test_solver_ignores_declared_solution_field():
    """Sanity check on the independence claim: corrupting `clues` (not
    `solution`) changes the solver's answer, proving `solve()` derives its
    result from clue facts rather than reading `instance.solution` under the
    hood."""

    instance = generate_instance(seed=7, difficulty=2)
    original = solve_instance(instance)
    assert len(original) == 1

    # Swap the anchor's claimed position to something false -> now unsolvable
    bad_clue = S.PuzzleClue(
        id=instance.clues[0].id,
        prose=instance.clues[0].prose,
        viewer_scope=instance.clues[0].viewer_scope,
        reveals={**instance.clues[0].reveals, "position": 99},
    )
    bad_clues = (bad_clue,) + instance.clues[1:]
    assert solve(bad_clues) == []


def test_red_herring_is_true_but_not_required_for_uniqueness():
    """Removing the red-herring clue must not change the solver's answer --
    it is informative, not load-bearing (§10.2)."""

    for seed in range(0, 200, 7):
        instance = generate_instance(seed=seed, difficulty=(seed % 5) + 1)
        herring_ids = {
            cid
            for obj in instance.objects
            if obj.role is S.PuzzleObjectRole.RED_HERRING
            for cid in obj.clue_ids
        }
        remaining = tuple(c for c in instance.clues if c.id not in herring_ids)
        solutions = solve(remaining)
        assert len(solutions) == 1
        assert solutions[0] == instance.solution


def test_contradiction_clue_rules_out_a_wrong_answer():
    """Removing the contradiction clue must never turn a unique solution into
    zero solutions -- it should only ever prune, never be required to find
    *a* solution (only to keep the *true* one unique in edge cases)."""

    for seed in range(0, 200, 11):
        instance = generate_instance(seed=seed, difficulty=(seed % 5) + 1)
        contra_ids = {
            cid
            for obj in instance.objects
            if obj.role is S.PuzzleObjectRole.CONTRADICTION
            for cid in obj.clue_ids
        }
        remaining = tuple(c for c in instance.clues if c.id not in contra_ids)
        solutions = solve(remaining)
        assert instance.solution in solutions
