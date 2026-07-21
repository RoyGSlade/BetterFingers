"""Real Mystery Chamber puzzle rooms, end to end (infinite_stacks.md §9.1,
§10; board task #5).

Drives the real `StacksEngineAdapter` directly (bypassing FastAPI transport,
same pattern as tests/test_stacks_e2e.py's `DeterministicReplayTests`) so
internal domain state (`room.puzzle.solution`) stays inspectable for the
validator-owned solution check, while still exercising the real wire
translation and viewer-filtered projection stacks_engine.py/stacks_
projections.py produce. `content/puzzles/ordering_sequence.py`'s generator
and `solver.py`'s independent cross-check are already covered by
tests/test_stacks_puzzles.py; this file covers the *engine* wiring around a
real instance: instantiation on breach, asymmetric per-hero clue
distribution, hints, fail-forward, and solving.
"""
from __future__ import annotations

import unittest

from backend.lan_playground.stacks_engine import StacksEngineAdapter
from backend.lan_playground.stacks_protocol import Command, CommandError


def _send(adapter, state, hero_id, ctype, payload=None, tag=""):
    cmd = Command(
        command_id=f"{ctype}-{hero_id}-{tag}",
        idempotency_key=f"{ctype}-{hero_id}-{tag}",
        run_id=state.run_id,
        hero_id=hero_id,
        encounter_id=None,
        expected_revision=state.revision,
        type=ctype,
        payload=payload or {},
    )
    return adapter.apply(state, cmd)


def _seed_with_mystery_chamber_breach(*, upper_bound: int = 3000):
    """Scan seeds through the real engine for one whose entrance's first
    breachable door lands on mystery_chamber (mirrors
    tests/test_stacks_e2e.py's seed-scan helpers -- the real engine burns a
    variable number of RNG draws generating map topology before any breach
    d8 roll, so this can't be predicted from a bare Random(seed))."""

    for seed in range(upper_bound):
        adapter = StacksEngineAdapter()
        state = adapter.create_run(seed=seed)
        _send(adapter, state, "hero_host", "join_run", {"display_name": "Host"}, tag="scan")
        room = state.rooms[state.heroes["hero_host"].room_id]
        direction = next((d for d, c in room.connectors.items() if c.state == "undiscovered"), None)
        if direction is None:
            continue
        result = _send(adapter, state, "hero_host", "breach", {"direction": direction}, tag="scan")
        family = next(e.payload["family"] for e in result.events if e.type == "die_rolled")
        if family == "mystery_chamber":
            return seed, direction
    raise AssertionError("no mystery_chamber seed found in range")


def _build_scenario():
    """Host breaches into a Mystery Chamber (claiming their own key
    fragment); Ally walks in behind them and inspects the key object,
    claiming a *different* fragment. Returns everything a test needs,
    including the live adapter+state so tests can keep acting on it."""

    seed, direction = _seed_with_mystery_chamber_breach()
    adapter = StacksEngineAdapter()
    state = adapter.create_run(seed=seed)
    _send(adapter, state, "hero_host", "join_run", {"display_name": "Host"})
    _send(adapter, state, "hero_ally", "join_run", {"display_name": "Ally"})

    breach = _send(adapter, state, "hero_host", "breach", {"direction": direction})
    room_id = next(e.payload["room_id"] for e in breach.events if e.type == "room_revealed")
    instantiated = next(e for e in breach.events if e.type == "puzzle_instantiated")
    objects = instantiated.payload["objects"]
    key_object_id = next(o["id"] for o in objects if o["role"] == "key")

    ally_move = _send(adapter, state, "hero_ally", "move", {"to_room_id": room_id})
    ally_inspect = _send(adapter, state, "hero_ally", "inspect_object", {"object_id": key_object_id})

    domain_state = adapter._domain_states[state.run_id]
    puzzle = domain_state.map.rooms[room_id].puzzle

    return {
        "adapter": adapter,
        "state": state,
        "room_id": room_id,
        "key_object_id": key_object_id,
        "objects": objects,
        "breach": breach,
        "ally_move": ally_move,
        "ally_inspect": ally_inspect,
        "puzzle": puzzle,
    }


class InstantiationAndDistributedCluesTests(unittest.TestCase):
    def test_breach_instantiates_a_real_four_object_puzzle(self):
        ctx = _build_scenario()
        objects = ctx["objects"]
        roles = {o["role"] for o in objects}
        self.assertEqual(roles, {"anchor", "key", "contradiction", "red_herring"})
        for obj in objects:
            self.assertTrue(obj["fallback"].strip())
            self.assertTrue(obj["accessible"].strip())
        # No object payload ever carries clue text or a solution field.
        for obj in objects:
            self.assertNotIn("clue_ids", obj)
            self.assertNotIn("solution", obj)

    def test_breach_delivers_exactly_one_private_clue_to_the_breacher(self):
        ctx = _build_scenario()
        breach_clue_events = [e for e in ctx["breach"].events if e.type == "private_clue_assigned"]
        self.assertEqual(len(breach_clue_events), 1)
        event = breach_clue_events[0]
        self.assertEqual(event.visibility, "private")
        self.assertEqual(event.visible_to, "hero_host")
        self.assertEqual(len(event.payload["clues"]), 1)

    def test_ally_inspecting_the_key_claims_a_different_fragment_than_host(self):
        ctx = _build_scenario()
        ally_clue_events = [e for e in ctx["ally_inspect"].events if e.type == "private_clue_assigned"]
        self.assertEqual(len(ally_clue_events), 1)
        ally_clue_ids = {c["clue_id"] for c in ally_clue_events[0].payload["clues"]}
        host_clue_ids = set(ctx["puzzle"].private_clue_assignments.get("hero_host", ()))
        self.assertTrue(ally_clue_ids, "ally should have claimed at least one fragment")
        self.assertTrue(host_clue_ids, "host should have claimed at least one fragment")
        self.assertTrue(ally_clue_ids.isdisjoint(host_clue_ids), "asymmetric clues must not overlap")

    def test_no_single_hero_view_ever_contains_the_full_key_chain(self):
        """§10.3 #8 'no player has the full solution' -- the object_inspected
        event for either hero must reveal strictly fewer clues than the full
        key chain whenever more than one hero has claimed a fragment."""

        ctx = _build_scenario()
        puzzle = ctx["puzzle"]
        full_key_chain = len(puzzle.object_clue_ids[ctx["key_object_id"]])
        ally_inspect_event = next(e for e in ctx["ally_inspect"].events if e.type == "object_inspected")
        self.assertLess(len(ally_inspect_event.payload["revealed_clues"]), full_key_chain)

    def test_anchor_and_contradiction_objects_are_visible_to_whoever_inspects(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        anchor_id = next(o["id"] for o in ctx["objects"] if o["role"] == "anchor")
        result = _send(adapter, state, "hero_ally", "inspect_object", {"object_id": anchor_id})
        inspected = next(e for e in result.events if e.type == "object_inspected")
        self.assertEqual(len(inspected.payload["revealed_clues"]), 1)


class FailForwardAndSolvingTests(unittest.TestCase):
    def test_wrong_submission_never_does_nothing(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        wrong_solution = list(reversed(ctx["puzzle"].solution))
        self.assertNotEqual(tuple(wrong_solution), ctx["puzzle"].solution)

        result = _send(adapter, state, "hero_host", "submit_solution", {"solution": wrong_solution})
        rejected = next(e for e in result.events if e.type == "puzzle_solution_rejected")
        self.assertEqual(rejected.payload["attempts_used"], 1)
        self.assertFalse(rejected.payload["forced"])

        # A fail-forward consequence is dispatched every time, never silence.
        fact_events = [e for e in result.events if e.type == "fact_emitted"]
        self.assertTrue(fact_events, "wrong submission must fire a fail-forward consequence")
        self.assertEqual(fact_events[0].payload["fact_id"], "reshelving_failed")

    def test_exhausting_attempt_limit_force_progresses(self):
        ctx = _build_scenario()
        adapter, state = ctx["adapter"], ctx["state"]
        wrong_solution = list(reversed(ctx["puzzle"].solution))
        attempt_limit = ctx["puzzle"].attempt_limit
        self.assertIsNotNone(attempt_limit)

        last_result = None
        for i in range(attempt_limit):
            last_result = _send(adapter, state, "hero_host", "submit_solution", {"solution": wrong_solution}, tag=str(i))

        forced_events = [e for e in last_result.events if e.type == "puzzle_force_progress"]
        self.assertEqual(len(forced_events), 1)
        self.assertEqual(forced_events[0].payload["reason"], "attempts_exhausted")

        with self.assertRaises(CommandError):
            _send(adapter, state, "hero_host", "submit_solution", {"solution": wrong_solution}, tag="after-forced")

    def test_correct_submission_clears_the_room(self):
        ctx = _build_scenario()
        adapter, state = ctx["adapter"], ctx["state"]
        correct_solution = list(ctx["puzzle"].solution)

        result = _send(adapter, state, "hero_host", "submit_solution", {"solution": correct_solution})
        solved = next(e for e in result.events if e.type == "puzzle_solved")
        self.assertEqual(solved.payload["attempts_used"], 1)

        fact_events = [e for e in result.events if e.type == "fact_emitted"]
        self.assertTrue(fact_events)
        self.assertEqual(fact_events[0].payload["fact_id"], "reshelving_solved")

        domain_state = adapter._domain_states[state.run_id]
        puzzle = domain_state.map.rooms[ctx["room_id"]].puzzle
        self.assertTrue(puzzle.solved)

        with self.assertRaises(CommandError):
            _send(adapter, state, "hero_host", "submit_solution", {"solution": correct_solution}, tag="again")

    def test_three_hints_then_a_fourth_force_progresses(self):
        ctx = _build_scenario()
        adapter, state = ctx["adapter"], ctx["state"]

        seen_indices = []
        for i in range(3):
            result = _send(adapter, state, "hero_host", "request_hint", tag=str(i))
            hint_event = next(e for e in result.events if e.type == "puzzle_hint_revealed")
            self.assertEqual(hint_event.visibility, "party")
            seen_indices.append(hint_event.payload["hint_index"])
        self.assertEqual(seen_indices, [0, 1, 2])

        fourth = _send(adapter, state, "hero_host", "request_hint", tag="fourth")
        forced = next(e for e in fourth.events if e.type == "puzzle_force_progress")
        self.assertEqual(forced.payload["reason"], "hints_exhausted")
        fact_events = [e for e in fourth.events if e.type == "fact_emitted"]
        self.assertTrue(fact_events, "hint exhaustion must also fail-forward, never silently lock the room")

        with self.assertRaises(CommandError):
            _send(adapter, state, "hero_host", "request_hint", tag="fifth")


class ProjectionPrivacyTests(unittest.TestCase):
    def test_solution_never_appears_in_any_projection(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        solution_str = "".join(ctx["puzzle"].solution)

        for viewer in (None, "hero_host", "hero_ally"):
            view = adapter.project(state, viewer)
            entry = view["puzzles"][room_id]
            self.assertNotIn("solution", entry)
            self.assertNotIn("accepted_solutions", entry)
            self.assertNotIn(solution_str, repr(entry))

    def test_your_private_clues_never_leaks_another_heros_fragment(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]

        host_view = adapter.project(state, "hero_host")["puzzles"][room_id]
        ally_view = adapter.project(state, "hero_ally")["puzzles"][room_id]

        host_ids = {c["clue_id"] for c in host_view["your_private_clues"]}
        ally_ids = {c["clue_id"] for c in ally_view["your_private_clues"]}
        self.assertTrue(host_ids)
        self.assertTrue(ally_ids)
        self.assertTrue(host_ids.isdisjoint(ally_ids))

        # Neither viewer's snapshot exposes an all-heroes clue map at all --
        # only their own pre-filtered "your_private_clues" list.
        self.assertNotIn("private_clues", host_view)
        self.assertNotIn("private_clues", ally_view)

    def test_spectator_view_gets_no_private_clues_or_hints(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        _send(adapter, state, "hero_host", "request_hint")

        spectator_view = adapter.project(state, None)["puzzles"][room_id]
        self.assertEqual(spectator_view["your_private_clues"], [])
        self.assertEqual(spectator_view["hints_revealed"], [])

        host_view = adapter.project(state, "hero_host")["puzzles"][room_id]
        self.assertEqual(len(host_view["hints_revealed"]), 1)

    def test_public_objects_are_visible_to_every_viewer(self):
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        for viewer in (None, "hero_host", "hero_ally"):
            entry = adapter.project(state, viewer)["puzzles"][room_id]
            self.assertEqual({o["role"] for o in entry["objects"]}, {"anchor", "key", "contradiction", "red_herring"})

    def test_orderable_items_are_public_and_do_not_leak_solution_order(self):
        """Director-directed fix (2026-07-19 17:30): submit_solution needs
        item ids on the wire, but the emitted order must not reveal the
        answer -- items are always lexicographic-by-item_id, independent of
        the shuffled solution order."""
        ctx = _build_scenario()
        adapter, state, room_id = ctx["adapter"], ctx["state"], ctx["room_id"]
        solution_order = list(ctx["puzzle"].solution)

        for viewer in (None, "hero_host", "hero_ally"):
            entry = adapter.project(state, viewer)["puzzles"][room_id]
            items = entry["items"]
            item_ids = [i["item_id"] for i in items]
            self.assertEqual(set(item_ids), set(solution_order))
            self.assertEqual(item_ids, sorted(item_ids))
            for i in items:
                self.assertNotIn("solution", i)
                self.assertTrue(i["fallback"])
                self.assertTrue(i["accessible"])

        # The whole point: a real client can build a legal (if wrong) guess
        # purely from the public item ids, with zero private/engine access.
        spectator_item_ids = adapter.project(state, None)["puzzles"][room_id]["items"]
        result = _send(
            adapter, state, "hero_host", "submit_solution",
            {"solution": [i["item_id"] for i in spectator_item_ids]},
        )
        rejected_or_accepted = {e.type for e in result.events}
        self.assertTrue({"puzzle_solution_rejected", "puzzle_solved"} & rejected_or_accepted)

        # And on a seed where the shuffle actually differs from sorted order,
        # prove the emitted order is provably not the solution order.
        self.assertNotEqual(list(item_ids), solution_order)

    def test_reconnect_missed_events_respect_private_clue_visibility(self):
        ctx = _build_scenario()
        adapter, state = ctx["adapter"], ctx["state"]

        host_missed = adapter.events_since(state, "hero_host", 0)
        ally_missed = adapter.events_since(state, "hero_ally", 0)

        host_clue_events = [e for e in host_missed if e.type == "private_clue_assigned"]
        ally_clue_events = [e for e in ally_missed if e.type == "private_clue_assigned"]
        self.assertTrue(all(e.visible_to == "hero_host" for e in host_clue_events))
        self.assertTrue(all(e.visible_to == "hero_ally" for e in ally_clue_events))
        # Neither viewer's own missed-event stream carries the other's clue.
        self.assertFalse(any(e.visible_to == "hero_ally" for e in host_missed if e.type == "private_clue_assigned"))
        self.assertFalse(any(e.visible_to == "hero_host" for e in ally_missed if e.type == "private_clue_assigned"))


if __name__ == "__main__":
    unittest.main()
