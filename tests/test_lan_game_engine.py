"""Unit tests for backend.lan_playground.game (board #39).

Pure in-memory engine tests only -- no FastAPI app, network, or model
involved. Every test drives Room/GameRegistry directly.
"""

import unittest

from backend.lan_playground.game import (
    APPROACHES,
    ENCOUNTERS,
    MAX_PLAYERS,
    AlreadySubmittedError,
    GameRegistry,
    InactivePlayerError,
    InvalidApproachError,
    InvalidPhaseError,
    InvalidTokenError,
    NotAllSubmittedError,
    NotHostError,
    Room,
    RoomFullError,
    UnknownPlayerError,
)


def _new_room(seed=1, host_name="Host"):
    registry = GameRegistry()
    room, host_id, host_token = registry.create_room(host_name, seed=seed)
    return registry, room, host_id, host_token


def _submit_all(room, players, approach_for):
    """players: list of (player_id, token). approach_for: dict or callable(player_id)->approach."""
    for pid, token in players:
        approach = approach_for(pid) if callable(approach_for) else approach_for[pid]
        room.submit_choice(pid, token, approach, f"a bounded one-line move by {pid}")


class LobbyAndJoinTests(unittest.TestCase):
    def test_creator_becomes_host_and_first_player(self):
        _, room, host_id, host_token = _new_room()
        state = room.public_state()
        self.assertEqual(state["host_id"], host_id)
        self.assertEqual(len(state["players"]), 1)
        self.assertTrue(state["players"][0]["is_host"])
        self.assertTrue(room.verify_token(host_id, host_token))

    def test_guests_can_join_up_to_max_players(self):
        _, room, _, _ = _new_room()
        for i in range(MAX_PLAYERS - 1):
            player_id, token = room.join(f"Guest{i}")
            self.assertTrue(room.verify_token(player_id, token))
        self.assertEqual(len(room.public_state()["players"]), MAX_PLAYERS)

    def test_room_full_rejects_fifth_player(self):
        _, room, _, _ = _new_room()
        for i in range(MAX_PLAYERS - 1):
            room.join(f"Guest{i}")
        with self.assertRaises(RoomFullError):
            room.join("OneTooMany")

    def test_join_rejected_once_game_started(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        with self.assertRaises(InvalidPhaseError):
            room.join("LateComer")

    def test_solo_play_is_allowed(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        self.assertEqual(room.public_state()["phase"], "choosing")

    def test_player_name_bounded_and_defaulted(self):
        _, room, _, _ = _new_room()
        pid, _ = room.join("   ")
        state = room.public_state()
        guest = next(p for p in state["players"] if p["player_id"] == pid)
        self.assertEqual(guest["name"], "Adventurer")

        pid2, _ = room.join("x" * 500)
        state2 = room.public_state()
        guest2 = next(p for p in state2["players"] if p["player_id"] == pid2)
        self.assertLessEqual(len(guest2["name"]), 40)


class DeterminismTests(unittest.TestCase):
    def test_same_seed_yields_same_encounter_order(self):
        _, room_a, _, _ = _new_room(seed=42)
        _, room_b, _, _ = _new_room(seed=42)
        self.assertEqual(room_a._encounter_order, room_b._encounter_order)

    def test_red_tape_dragon_is_always_the_final_boss(self):
        for seed in range(20):
            _, room, _, _ = _new_room(seed=seed)
            self.assertEqual(room._encounter_order[-1], len(ENCOUNTERS) - 1)
            self.assertEqual(ENCOUNTERS[room._encounter_order[-1]].id, "red_tape_dragon")

    def test_all_five_encounters_are_distinct_and_covered(self):
        self.assertEqual(len(ENCOUNTERS), 5)
        ids = {enc.id for enc in ENCOUNTERS}
        self.assertEqual(len(ids), 5)
        for enc in ENCOUNTERS:
            self.assertIn(enc.weakness, APPROACHES)
            self.assertIn(enc.resistant, APPROACHES)
            self.assertNotEqual(enc.weakness, enc.resistant)
            self.assertNotIn(enc.neutral, (enc.weakness, enc.resistant))


class ChoiceAndResolutionTests(unittest.TestCase):
    def test_full_round_trip_success_reduces_no_hearts(self):
        _, room, host_id, host_token = _new_room(seed=7)
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        encounter = room._current_encounter()

        room.submit_choice(host_id, host_token, encounter.weakness, "we out-clever it")
        room.submit_choice(p2, t2, encounter.neutral, "we play it safe")
        self.assertTrue(room.can_resolve())

        record = room.resolve(host_id, host_token)
        self.assertEqual(record["successes"], 1)
        self.assertEqual(record["backfires"], 0)
        self.assertEqual(record["damage"], 0)
        self.assertEqual(room.public_state()["hearts"], 3)
        self.assertEqual(room.public_state()["phase"], "reveal")

    def test_backfire_majority_deals_damage(self):
        _, room, host_id, host_token = _new_room(seed=7)
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        encounter = room._current_encounter()

        room.submit_choice(host_id, host_token, encounter.resistant, "bad idea")
        room.submit_choice(p2, t2, encounter.resistant, "also bad")
        record = room.resolve(host_id, host_token)

        self.assertEqual(record["backfires"], 2)
        self.assertEqual(record["successes"], 0)
        self.assertEqual(record["damage"], 2)
        self.assertEqual(room.public_state()["hearts"], 1)

    def test_successes_cancel_backfires_net_floor_zero(self):
        _, room, host_id, host_token = _new_room(seed=7)
        p2, t2 = room.join("Guest")
        p3, t3 = room.join("Guest2")
        room.start(host_id, host_token)
        encounter = room._current_encounter()

        room.submit_choice(host_id, host_token, encounter.weakness, "clever")
        room.submit_choice(p2, t2, encounter.weakness, "also clever")
        room.submit_choice(p3, t3, encounter.resistant, "oops")
        record = room.resolve(host_id, host_token)

        self.assertEqual(record["damage"], 0)
        self.assertEqual(room.public_state()["hearts"], 3)

    def test_zero_hearts_ends_game_in_defeat_without_advance(self):
        _, room, host_id, host_token = _new_room(seed=7)
        p2, t2 = room.join("Guest")
        p3, t3 = room.join("Guest2")
        room.start(host_id, host_token)

        # Drive hearts to 0 across successive rounds by always backfiring.
        for _ in range(3):
            if room.public_state()["phase"] == "finished":
                break
            encounter = room._current_encounter()
            room.submit_choice(host_id, host_token, encounter.resistant, "oops")
            room.submit_choice(p2, t2, encounter.resistant, "oops")
            room.submit_choice(p3, t3, encounter.resistant, "oops")
            room.resolve(host_id, host_token)
            if room.public_state()["phase"] == "reveal":
                room.advance(host_id, host_token)

        state = room.public_state()
        self.assertEqual(state["phase"], "finished")
        self.assertFalse(state["finished_victory"])
        self.assertEqual(state["hearts"], 0)

    def test_winning_all_five_encounters_yields_victory(self):
        _, room, host_id, host_token = _new_room(seed=7)
        room.start(host_id, host_token)
        for round_num in range(len(ENCOUNTERS)):
            encounter = room._current_encounter()
            room.submit_choice(host_id, host_token, encounter.weakness, "clever")
            room.resolve(host_id, host_token)
            state = room.public_state()
            if state["phase"] == "finished":
                break
            room.advance(host_id, host_token)

        state = room.public_state()
        self.assertEqual(state["phase"], "finished")
        self.assertTrue(state["finished_victory"])
        self.assertGreater(state["hearts"], 0)

    def test_invalid_approach_rejected(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        with self.assertRaises(InvalidApproachError):
            room.submit_choice(host_id, host_token, "fireball", "nope")

    def test_double_submit_rejected(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        room.submit_choice(host_id, host_token, "charm", "hello")
        with self.assertRaises(AlreadySubmittedError):
            room.submit_choice(host_id, host_token, "bonk", "again")

    def test_resolve_before_all_submitted_rejected(self):
        _, room, host_id, host_token = _new_room()
        room.join("Guest")
        room.start(host_id, host_token)
        room.submit_choice(host_id, host_token, "charm", "hi")
        self.assertFalse(room.can_resolve())
        with self.assertRaises(NotAllSubmittedError):
            room.resolve(host_id, host_token)

    def test_move_text_is_bounded_one_line_and_cosmetic(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        weird = "line one\nline two\t\tpadded" + ("!" * 500)
        room.submit_choice(host_id, host_token, "charm", weird)
        record = room.resolve(host_id, host_token)
        move_text = record["choices"][0]["move_text"]
        self.assertNotIn("\n", move_text)
        self.assertLessEqual(len(move_text), 140)
        # Move text never influences success/backfire counts -- only approach.
        self.assertIn(record["successes"] + record["backfires"], (0, 1))


class HostAuthorityTests(unittest.TestCase):
    def test_non_host_cannot_start_resolve_advance_or_replay(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        with self.assertRaises(NotHostError):
            room.start(p2, t2)
        room.start(host_id, host_token)
        room.submit_choice(host_id, host_token, "charm", "hi")
        room.submit_choice(p2, t2, "charm", "hi")
        with self.assertRaises(NotHostError):
            room.resolve(p2, t2)
        room.resolve(host_id, host_token)
        with self.assertRaises(NotHostError):
            room.advance(p2, t2)

    def test_invalid_token_rejected(self):
        _, room, host_id, _ = _new_room()
        with self.assertRaises(InvalidTokenError):
            room.start(host_id, "wrong-token")

    def test_unknown_player_rejected(self):
        _, room, _, _ = _new_room()
        with self.assertRaises(UnknownPlayerError):
            room.submit_choice("no-such-player", "tok", "charm", "hi")


class DisconnectTests(unittest.TestCase):
    def test_disconnect_excludes_player_from_resolve_requirement(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        room.disconnect(p2, t2)
        room.submit_choice(host_id, host_token, "charm", "hi")
        self.assertTrue(room.can_resolve())
        record = room.resolve(host_id, host_token)
        self.assertEqual(len(record["choices"]), 1)

    def test_host_disconnect_promotes_next_active_player_no_deadlock(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.disconnect(host_id, host_token)
        state = room.public_state()
        self.assertEqual(state["host_id"], p2)
        # New host can now drive the game -- proves no deadlock.
        room.start(p2, t2)
        self.assertEqual(room.public_state()["phase"], "choosing")

    def test_solo_host_disconnect_reconnect_does_not_strand_room(self):
        _, room, host_id, host_token = _new_room()
        room.disconnect(host_id, host_token)
        self.assertEqual(room.public_state()["host_id"], host_id)
        room.reconnect(host_id, host_token)
        room.start(host_id, host_token)
        self.assertEqual(room.public_state()["phase"], "choosing")

    def test_reconnected_player_can_submit_again(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        room.disconnect(p2, t2)
        room.reconnect(p2, t2)
        room.submit_choice(host_id, host_token, "charm", "hi")
        room.submit_choice(p2, t2, "bonk", "hi")
        self.assertTrue(room.can_resolve())

    def test_inactive_player_cannot_submit(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        room.disconnect(p2, t2)
        with self.assertRaises(InactivePlayerError):
            room.submit_choice(p2, t2, "charm", "hi")


class PublicStatePrivacyTests(unittest.TestCase):
    def test_no_tokens_anywhere_in_public_state(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        state = room.public_state(viewer_player_id=p2)
        blob = repr(state)
        self.assertNotIn(host_token, blob)
        self.assertNotIn(t2, blob)

    def test_unsubmitted_choices_not_leaked_before_reveal(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        room.submit_choice(host_id, host_token, "charm", "a secret plan")
        state = room.public_state(viewer_player_id=p2)
        blob = repr(state)
        self.assertNotIn("a secret plan", blob)
        self.assertNotIn("charm", blob)
        host_entry = next(p for p in state["players"] if p["player_id"] == host_id)
        self.assertTrue(host_entry["submitted"])

    def test_choices_revealed_after_resolve(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        room.submit_choice(host_id, host_token, "charm", "a visible plan")
        room.resolve(host_id, host_token)
        state = room.public_state()
        self.assertIn("a visible plan", repr(state["last_round"]))


class FlavorOverlayTests(unittest.TestCase):
    def test_flavor_overlay_changes_display_not_score(self):
        _, room, host_id, host_token = _new_room(seed=7)
        room.start(host_id, host_token)
        encounter = room._current_encounter()
        room.submit_choice(host_id, host_token, encounter.resistant, "canonical text")
        room.set_flavor(f"move:{host_id}:0", "a whimsically rewritten line")
        record = room.resolve(host_id, host_token)
        self.assertEqual(record["choices"][0]["move_text"], "a whimsically rewritten line")
        # Scoring is unaffected by the overlay -- still counts as a backfire.
        self.assertEqual(record["backfires"], 1)
        self.assertEqual(record["damage"], 1)

    def test_encounter_flavor_overlay_reflected_in_public_state(self):
        _, room, host_id, host_token = _new_room(seed=7)
        room.start(host_id, host_token)
        encounter = room._current_encounter()
        room.set_flavor(f"encounter:{encounter.id}", "a rewritten encounter blurb")
        state = room.public_state()
        self.assertEqual(state["encounter"]["flavor"], "a rewritten encounter blurb")


class ReplayTests(unittest.TestCase):
    def _finish_game(self, room, host_id, host_token, others=()):
        for _ in range(len(ENCOUNTERS)):
            encounter = room._current_encounter()
            room.submit_choice(host_id, host_token, encounter.weakness, "clever")
            for pid, token in others:
                room.submit_choice(pid, token, encounter.weakness, "clever too")
            room.resolve(host_id, host_token)
            if room.public_state()["phase"] == "finished":
                break
            room.advance(host_id, host_token)

    def test_replay_requires_finished_phase(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        with self.assertRaises(InvalidPhaseError):
            room.replay(host_id, host_token)

    def test_replay_resets_state_and_keeps_roster(self):
        _, room, host_id, host_token = _new_room(seed=7)
        p2, t2 = room.join("Guest")
        room.start(host_id, host_token)
        self._finish_game(room, host_id, host_token, others=[(p2, t2)])

        room.replay(host_id, host_token)
        state = room.public_state()
        self.assertEqual(state["phase"], "lobby")
        self.assertEqual(state["hearts"], 3)
        self.assertEqual(state["round_index"], 0)
        self.assertEqual(state["history"], [])
        self.assertIsNone(state["finished_victory"])
        self.assertEqual(len(state["players"]), 2)

    def test_replay_with_explicit_seed_is_reproducible(self):
        _, room, host_id, host_token = _new_room(seed=7)
        room.start(host_id, host_token)
        self._finish_game(room, host_id, host_token)
        room.replay(host_id, host_token, seed=99)
        order_a = list(room._encounter_order)

        _, room_b, host_id_b, host_token_b = _new_room(seed=99)
        self.assertEqual(order_a, room_b._encounter_order)


class GameRegistryTests(unittest.TestCase):
    def test_create_get_remove_round_trip(self):
        registry = GameRegistry()
        room, host_id, host_token = registry.create_room("Host")
        self.assertIs(registry.get(room.room_id), room)
        self.assertTrue(room.verify_token(host_id, host_token))
        registry.remove(room.room_id)
        self.assertIsNone(registry.get(room.room_id))

    def test_unknown_room_id_returns_none(self):
        registry = GameRegistry()
        self.assertIsNone(registry.get("room_does_not_exist"))


if __name__ == "__main__":
    unittest.main()
