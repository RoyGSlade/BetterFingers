"""Unit tests for backend.lan_playground.game -- The Lost Meaning engine.

Pure in-memory engine tests only -- no FastAPI app, network, or model
involved. Every test drives Room/GameRegistry directly.
"""

import random
import unittest

from backend.lan_playground.game import (
    ALL_MOVES,
    ENCOUNTERS,
    HERO_ROSTER,
    ITEM_STARTING_COUNT,
    MAX_PLAYERS,
    MOVES,
    REACTION_VERBS,
    SUPPORT_KINDS,
    AlreadySubmittedError,
    GameRegistry,
    InvalidMoveError,
    InvalidPhaseError,
    InvalidReactionVerbError,
    InvalidSupportKindError,
    InvalidTargetError,
    InvalidVariantsError,
    NoItemsRemainingError,
    NotAllSubmittedError,
    NotHostError,
    Room,
    RoomFullError,
    UnknownPlayerError,
    WrongTurnError,
)

HERO_IDS = [h.id for h in HERO_ROSTER]


def _new_room(seed=1, host_name="Host"):
    registry = GameRegistry()
    room, host_id, host_token = registry.create_room(host_name, seed=seed)
    return registry, room, host_id, host_token


def _join_all(room, count):
    """Join `count` additional players (beyond the host). Returns list of
    (player_id, token, hero_id)."""
    joined = []
    for i in range(count):
        pid, token = room.join(f"Guest{i}")
        hero_id = room.public_state(pid)["you"]["hero_id"]
        joined.append((pid, token, hero_id))
    return joined


def _make_four_human_room(seed=1):
    """Sets up a room with all 4 hero slots claimed by humans, no companions.
    Returns (registry, room, players_by_hero) where players_by_hero maps
    hero_id -> (player_id, token)."""
    registry, room, host_id, host_token = _new_room(seed=seed)
    rest = _join_all(room, 3)
    players_by_hero = {room.public_state(host_id)["you"]["hero_id"]: (host_id, host_token)}
    for pid, token, hero_id in rest:
        players_by_hero[hero_id] = (pid, token)
    assert set(players_by_hero.keys()) == set(HERO_IDS)
    return registry, room, players_by_hero


class LobbyAndHeroAssignmentTests(unittest.TestCase):
    def test_creator_becomes_host_and_first_hero(self):
        _, room, host_id, host_token = _new_room()
        state = room.public_state(host_id)
        self.assertEqual(state["host_id"], host_id)
        self.assertEqual(len(state["players"]), 1)
        self.assertTrue(state["players"][0]["is_host"])
        self.assertEqual(state["you"]["hero_id"], HERO_IDS[0])
        self.assertTrue(room.verify_token(host_id, host_token))

    def test_guests_bind_to_heroes_in_roster_order(self):
        _, room, host_id, _ = _new_room()
        joined = _join_all(room, MAX_PLAYERS - 1)
        expected = HERO_IDS[1:]
        self.assertEqual([hero_id for _, _, hero_id in joined], expected)

    def test_room_full_rejects_fifth_player(self):
        _, room, _, _ = _new_room()
        _join_all(room, MAX_PLAYERS - 1)
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
        self.assertEqual(room.public_state()["phase"], "spotlight_action")

    def test_player_name_bounded_and_defaulted(self):
        _, room, host_id, _ = _new_room()
        pid, _ = room.join("   ")
        state = room.public_state()
        guest = next(p for p in state["players"] if p["player_id"] == pid)
        self.assertEqual(guest["name"], "Adventurer")

        pid2, _ = room.join("x" * 500)
        state2 = room.public_state()
        guest2 = next(p for p in state2["players"] if p["player_id"] == pid2)
        self.assertLessEqual(len(guest2["name"]), 40)

    def test_unclaimed_hero_slots_are_companions_when_started_solo(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        heroes = room.public_state()["heroes"]
        companions = [h for h in heroes if h["is_companion"]]
        humans = [h for h in heroes if not h["is_companion"]]
        self.assertEqual(len(companions), MAX_PLAYERS - 1)
        self.assertEqual(len(humans), 1)


class RosterAndCatalogTests(unittest.TestCase):
    def test_exactly_four_heroes_with_unique_signature_moves(self):
        self.assertEqual(len(HERO_ROSTER), 4)
        sig_ids = {h.signature_move.id for h in HERO_ROSTER}
        self.assertEqual(len(sig_ids), 4)
        # Signature moves never collide with catalog move ids.
        self.assertFalse(sig_ids & set(MOVES.keys()))
        for h in HERO_ROSTER:
            self.assertEqual(len(h.deck), 3)
            for mid in h.deck:
                self.assertIn(mid, MOVES)

    def test_all_moves_registered_in_all_moves_lookup(self):
        for hero in HERO_ROSTER:
            self.assertIn(hero.signature_move.id, ALL_MOVES)
            for mid in hero.deck:
                self.assertIn(mid, ALL_MOVES)

    def test_named_moves_from_design_brief_all_present(self):
        required = {
            "empathic_mirror",
            "disarming_honesty",
            "cross_reference",
            "loophole_with_consequences",
            "precision_bonk",
            "defend_the_speaker",
            "smash_the_right_thing",
            "improvised_bonk",
        }
        self.assertEqual(required, set(MOVES.keys()))

    def test_reaction_verbs_all_representable_by_some_move(self):
        for verb in REACTION_VERBS:
            self.assertTrue(any(verb in m.verbs for m in ALL_MOVES.values()))

    def test_support_kinds_and_reaction_verbs_match_contract(self):
        self.assertEqual(SUPPORT_KINDS, ("clue", "item", "assist", "reaction"))
        self.assertEqual(REACTION_VERBS, ("interpret", "assist", "challenge", "protect"))


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
            self.assertIn(enc.true_target, enc.targets)
            self.assertEqual(len(enc.clues), 4)
            self.assertEqual(set(enc.clues.keys()), set(HERO_IDS))


class SpotlightRotationTests(unittest.TestCase):
    def test_spotlight_rotates_through_all_four_heroes(self):
        registry, room, players_by_hero = _make_four_human_room(seed=3)
        seen = []
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        for _ in range(5):
            hero_id = room.public_state()["spotlight_hero_id"]
            seen.append(hero_id)
            pid, token = players_by_hero[hero_id]
            room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "outcome")
            for hid in HERO_IDS:
                if hid == hero_id:
                    continue
                apid, atoken = players_by_hero[hid]
                room.submit_support(apid, atoken, "assist", "help")
            room.open_draft(host_id, host_token)
            room.submit_rough_text(pid, token, "we try our best")
            room.submit_variants(pid, token, ["a", "b", "c"])
            room.approve_message(pid, token, "a", "resolve it")
            for hid in HERO_IDS:
                if hid == hero_id:
                    continue
                apid, atoken = players_by_hero[hid]
                room.submit_reaction(apid, atoken, "assist", "help")
            room.resolve(host_id, host_token)
            if room.public_state()["phase"] == "finished":
                break
            room.advance(host_id, host_token)
        # 5 encounters, 4 heroes: the rotation wraps, so hero 0 gets a
        # second Spotlight turn in round 4.
        self.assertEqual(seen, HERO_IDS + [HERO_IDS[0]])


def MOVES_FOR(room, hero_id):
    hero = next(h for h in room.public_state()["heroes"] if h["hero_id"] == hero_id)
    return [hero["signature_move"]["id"]] + [m["id"] for m in hero["deck"]]


def _first_target(room):
    return room.public_state()["encounter"]["targets"][0]


def _advance_full_round(room, host_id, host_token, players_by_hero, move_id=None,
                         target_id=None, support_kind="assist", reaction_verb="assist"):
    """Exercises the full 7-step loop for the current round end to end."""
    hero_id = room.public_state()["spotlight_hero_id"]
    pid, token = players_by_hero[hero_id]
    if move_id is None:
        move_id = MOVES_FOR(room, hero_id)[0]
    if target_id is None:
        target_id = _first_target(room)
    room.submit_spotlight_action(pid, token, move_id, target_id, "we handle it")
    for hid in HERO_IDS:
        if hid == hero_id:
            continue
        apid, atoken = players_by_hero[hid]
        room.submit_support(apid, atoken, support_kind, "helping")
    room.open_draft(host_id, host_token)
    room.submit_rough_text(pid, token, "rough plan")
    room.submit_variants(pid, token, ["variant a", "variant b", "variant c"])
    room.approve_message(pid, token, "variant a", "resolve it")
    for hid in HERO_IDS:
        if hid == hero_id:
            continue
        apid, atoken = players_by_hero[hid]
        room.submit_reaction(apid, atoken, reaction_verb, "reacting")
    return room.resolve(host_id, host_token)


class ActionCardTransparencyTests(unittest.TestCase):
    def test_action_card_is_public_the_instant_it_is_declared(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        move_id = MOVES_FOR(room, hero_id)[0]
        target = _first_target(room)
        room.submit_spotlight_action(host_id, host_token, move_id, target, "we handle it")
        # A second, unrelated viewer sees the action card immediately.
        state = room.public_state(viewer_player_id=None)
        self.assertIsNotNone(state["current_action"])
        self.assertEqual(state["current_action"]["hero_id"], hero_id)
        self.assertEqual(state["current_action"]["move"]["id"], move_id)
        self.assertEqual(state["current_action"]["target_id"], target)
        self.assertIsNone(state["current_action"]["approved_text"])

    def test_invalid_move_and_target_rejected(self):
        _, room, host_id, host_token = _new_room()
        room.start(host_id, host_token)
        with self.assertRaises(InvalidMoveError):
            room.submit_spotlight_action(host_id, host_token, "not_a_real_move", _first_target(room), "x")
        with self.assertRaises(InvalidTargetError):
            hero_id = room.public_state()["spotlight_hero_id"]
            room.submit_spotlight_action(host_id, host_token, MOVES_FOR(room, hero_id)[0], "not a real target", "x")

    def test_only_spotlight_hero_can_declare_action(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        spotlight_hero = room.public_state()["spotlight_hero_id"]
        other_hero = next(h for h in HERO_IDS if h != spotlight_hero)
        pid, token = players_by_hero[other_hero]
        with self.assertRaises(WrongTurnError):
            room.submit_spotlight_action(pid, token, MOVES_FOR(room, other_hero)[0], _first_target(room), "x")


class SecretIsolationTests(unittest.TestCase):
    def test_private_clue_is_visible_only_to_own_hero(self):
        registry, room, players_by_hero = _make_four_human_room(seed=9)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        encounter = ENCOUNTERS[room._encounter_order[0]]
        for hero_id, (pid, token) in players_by_hero.items():
            state = room.public_state(viewer_player_id=pid)
            self.assertEqual(state["you"]["private_clue"], encounter.clues[hero_id])
            # No viewer ever sees another hero's clue text anywhere in the payload.
            serialized = str(state)
            for other_hero, other_clue in encounter.clues.items():
                if other_hero != hero_id:
                    self.assertNotIn(other_clue, serialized)

    def test_no_token_ever_appears_in_public_state(self):
        registry, room, players_by_hero = _make_four_human_room()
        for pid, token in players_by_hero.values():
            state = room.public_state(viewer_player_id=pid)
            self.assertNotIn(token, str(state))

    def test_support_content_hidden_until_resolve(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        room.submit_support(apid, atoken, "clue", "a very secret hint about the ledger")
        # Even the submitting ally's own viewer_state does not leak kind/detail pre-resolve.
        for viewer_pid, _ in players_by_hero.values():
            state = room.public_state(viewer_player_id=viewer_pid)
            self.assertNotIn("a very secret hint about the ledger", str(state))
            hero_entry = next(h for h in state["heroes"] if h["hero_id"] == ally_hero)
            self.assertTrue(hero_entry["submitted_current_step"])

    def test_reaction_content_hidden_until_resolve(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "resolve it")
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        room.submit_reaction(apid, atoken, "challenge", "a very secret challenge line")
        for viewer_pid, _ in players_by_hero.values():
            state = room.public_state(viewer_player_id=viewer_pid)
            self.assertNotIn("a very secret challenge line", str(state))

    def test_draft_visible_only_to_spotlight_not_even_host(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "a very private rough draft line")
        spotlight_state = room.public_state(viewer_player_id=pid)
        self.assertEqual(spotlight_state["you"]["draft"]["rough_text"], "a very private rough draft line")
        if pid != host_id:
            host_state = room.public_state(viewer_player_id=host_id)
            self.assertNotIn("a very private rough draft line", str(host_state))
        other_hero = next(h for h in HERO_IDS if h != hero_id)
        other_pid, _ = players_by_hero[other_hero]
        other_state = room.public_state(viewer_player_id=other_pid)
        self.assertNotIn("a very private rough draft line", str(other_state))


class ApprovalGateTests(unittest.TestCase):
    def test_cannot_open_draft_until_all_support_in(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        self.assertFalse(room.can_open_draft())
        with self.assertRaises(NotAllSubmittedError):
            room.open_draft(host_id, host_token)

    def test_cannot_submit_variants_before_rough_text(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        with self.assertRaises(InvalidPhaseError):
            room.submit_variants(pid, token, ["a", "b", "c"])

    def test_variants_must_be_exactly_three(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        with self.assertRaises(InvalidVariantsError):
            room.submit_variants(pid, token, ["only one"])

    def test_cannot_resolve_until_all_reactions_in(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        self.assertFalse(room.can_resolve())
        with self.assertRaises(NotAllSubmittedError):
            room.resolve(host_id, host_token)

    def test_double_submission_rejected(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        # The round has already moved on to ally_support by this point, so a
        # repeat call is rejected as a phase mismatch, not a re-submission.
        with self.assertRaises(InvalidPhaseError):
            room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        room.submit_support(apid, atoken, "assist", "help")
        with self.assertRaises(AlreadySubmittedError):
            room.submit_support(apid, atoken, "item", "help again")

    def test_spotlight_cannot_submit_support_or_reaction(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        with self.assertRaises(WrongTurnError):
            room.submit_support(pid, token, "assist", "help")

    def test_invalid_support_kind_and_reaction_verb_rejected(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        with self.assertRaises(InvalidSupportKindError):
            room.submit_support(apid, atoken, "not_a_kind", "help")
        room.submit_support(apid, atoken, "assist", "help")
        for hid in HERO_IDS:
            if hid in (hero_id, ally_hero):
                continue
            xpid, xtoken = players_by_hero[hid]
            room.submit_support(xpid, xtoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        with self.assertRaises(InvalidReactionVerbError):
            room.submit_reaction(apid, atoken, "not_a_verb", "x")


class ItemScarcityTests(unittest.TestCase):
    def test_item_support_consumes_the_single_starting_item(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        self.assertEqual(ITEM_STARTING_COUNT, 1)
        hero_id = room.public_state()["spotlight_hero_id"]
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        hero_entry = next(h for h in room.public_state()["heroes"] if h["hero_id"] == ally_hero)
        self.assertEqual(hero_entry["items_remaining"], 1)
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        room.submit_support(apid, atoken, "item", "using our one gadget")
        hero_entry = next(h for h in room.public_state()["heroes"] if h["hero_id"] == ally_hero)
        self.assertEqual(hero_entry["items_remaining"], 0)

    def test_no_items_remaining_raises_when_used_a_second_time(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        # Round 0's Spotlight is always HERO_IDS[0]; otis_barnstorm (index 2)
        # is an ally both this round and next round's (HERO_IDS[1]'s turn).
        ally_hero = "otis_barnstorm"
        self.assertNotEqual(room.public_state()["spotlight_hero_id"], ally_hero)
        apid, atoken = players_by_hero[ally_hero]
        _advance_full_round(room, host_id, host_token, players_by_hero, support_kind="item")
        hero_entry = next(h for h in room.public_state()["heroes"] if h["hero_id"] == ally_hero)
        self.assertEqual(hero_entry["items_remaining"], 0)
        room.advance(host_id, host_token)
        self.assertNotEqual(room.public_state()["spotlight_hero_id"], ally_hero)
        spotlight_hero = room.public_state()["spotlight_hero_id"]
        spid, stoken = players_by_hero[spotlight_hero]
        room.submit_spotlight_action(spid, stoken, MOVES_FOR(room, spotlight_hero)[0], _first_target(room), "x")
        with self.assertRaises(NoItemsRemainingError):
            room.submit_support(apid, atoken, "item", "gadget again")


class ModifierLedgerAndDiceTests(unittest.TestCase):
    def test_seeded_die_matches_recomputation_from_seed_and_round(self):
        registry, room, players_by_hero = _make_four_human_room(seed=77)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        record = _advance_full_round(room, host_id, host_token, players_by_hero)
        expected_rng = random.Random(77 * 1_000_003 + 0)
        expected_die = expected_rng.randint(1, 6)
        self.assertEqual(record["die_roll"], expected_die)
        self.assertEqual(record["score"], sum(m["value"] for m in record["modifiers"] if m["affects"] == "score"))

    def test_replaying_the_same_seed_reproduces_the_same_round_record(self):
        registry, room_a, players_a = _make_four_human_room(seed=55)
        host_id_a = room_a.host_id
        host_token_a = next(t for pid, t in players_a.values() if pid == host_id_a)
        room_a.start(host_id_a, host_token_a)
        record_a = _advance_full_round(room_a, host_id_a, host_token_a, players_a)

        registry, room_b, players_b = _make_four_human_room(seed=55)
        host_id_b = room_b.host_id
        host_token_b = next(t for pid, t in players_b.values() if pid == host_id_b)
        room_b.start(host_id_b, host_token_b)
        record_b = _advance_full_round(room_b, host_id_b, host_token_b, players_b)

        self.assertEqual(record_a["die_roll"], record_b["die_roll"])
        self.assertEqual(record_a["score"], record_b["score"])
        self.assertEqual(record_a["damage"], record_b["damage"])

    def test_target_insight_bonus_applied_only_for_true_target(self):
        registry, room, players_by_hero = _make_four_human_room(seed=1)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        encounter = ENCOUNTERS[room._encounter_order[0]]
        record = _advance_full_round(
            room, host_id, host_token, players_by_hero, target_id=encounter.true_target
        )
        target_mod = next(m for m in record["modifiers"] if m["source"] == "target")
        self.assertEqual(target_mod["value"], 1)

        registry2, room2, players2 = _make_four_human_room(seed=1)
        host_id2 = room2.host_id
        host_token2 = next(t for pid, t in players2.values() if pid == host_id2)
        room2.start(host_id2, host_token2)
        wrong_target = next(t for t in encounter.targets if t != encounter.true_target)
        record2 = _advance_full_round(
            room2, host_id2, host_token2, players2, target_id=wrong_target
        )
        target_mod2 = next(m for m in record2["modifiers"] if m["source"] == "target")
        self.assertEqual(target_mod2["value"], 0)

    def test_card_synergy_bonus_when_cited_move_matches_verb(self):
        registry, room, players_by_hero = _make_four_human_room(seed=4)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        allies = [h for h in HERO_IDS if h != hero_id]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        synergy_ally = allies[0]
        empathic = MOVES["empathic_mirror"]  # verbs include "assist"
        hero_moves = MOVES_FOR(room, synergy_ally)
        # empathic_mirror is on both Bram's and Ilona's decks; fall back to
        # any deck move whose verbs include "assist" for whichever ally this is.
        candidate_move_id = next(
            (mid for mid in hero_moves if "assist" in ALL_MOVES[mid].verbs), None
        )
        apid, atoken = players_by_hero[synergy_ally]
        room.submit_reaction(apid, atoken, "assist", "help", move_id=candidate_move_id)
        for hid in allies[1:]:
            xpid, xtoken = players_by_hero[hid]
            room.submit_reaction(xpid, xtoken, "assist", "help")
        record = room.resolve(host_id, host_token)
        if candidate_move_id is not None:
            self.assertTrue(any(m["source"] == f"synergy:{synergy_ally}" for m in record["modifiers"]))

    def test_citing_a_move_not_owned_raises(self):
        registry, room, players_by_hero = _make_four_human_room()
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        allies = [h for h in HERO_IDS if h != hero_id]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        ally = allies[0]
        apid, atoken = players_by_hero[ally]
        foreign_move = next(
            mid for hid, hd in [(h.id, h) for h in HERO_ROSTER] for mid in [hd.signature_move.id] if hid != ally
        )
        with self.assertRaises(InvalidMoveError):
            room.submit_reaction(apid, atoken, "assist", "help", move_id=foreign_move)


class AbilityTests(unittest.TestCase):
    def _room_with_hero_as_spotlight(self, hero_id, seed=1):
        # Spotlight rotation is fixed by round index (bram=0, nadia=1,
        # otis=2, ilona=3), independent of seed -- so reaching a given
        # hero's turn means advancing through the preceding rounds first,
        # using a safe (assist-heavy) default strategy that never risks
        # ending the game early.
        registry, room, players_by_hero = _make_four_human_room(seed=seed)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        target_round = HERO_IDS.index(hero_id)
        while room.encounter_index < target_round:
            _advance_full_round(room, host_id, host_token, players_by_hero)
            self.assertNotEqual(room.public_state()["phase"], "finished")
            room.advance(host_id, host_token)
        self.assertEqual(room.public_state()["spotlight_hero_id"], hero_id)
        return registry, room, host_id, host_token, players_by_hero

    def test_otis_follow_through_adds_one_when_playing_his_weakness(self):
        # Otis's whole kit is bonk, so this only applies when his round's
        # encounter happens to be bonk-weak -- search seeds for one.
        for seed in range(1, 60):
            registry, room, host_id, host_token, players_by_hero = self._room_with_hero_as_spotlight(
                "otis_barnstorm", seed=seed
            )
            encounter = ENCOUNTERS[room._encounter_order[room.encounter_index]]
            if encounter.weakness == "bonk":
                move_id = next(
                    mid for mid in MOVES_FOR(room, "otis_barnstorm") if ALL_MOVES[mid].school == encounter.weakness
                )
                record = _advance_full_round(room, host_id, host_token, players_by_hero, move_id=move_id)
                self.assertTrue(any(m["source"] == "ability:follow_through" for m in record["modifiers"]))
                return
        self.fail("no seed put a bonk-weak encounter in Otis's round")

    def test_nadia_loophole_sense_adds_extra_on_her_own_challenge(self):
        registry, room, host_id, host_token, players_by_hero = self._room_with_hero_as_spotlight("bram_correctly")
        # Nadia must be an ally this round (she is, since Bram is spotlight).
        allies = [h for h in HERO_IDS if h != "bram_correctly"]
        pid, token = players_by_hero["bram_correctly"]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, "bram_correctly")[0], _first_target(room), "x")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            verb = "challenge" if hid == "nadia_quickwit" else "assist"
            room.submit_reaction(apid, atoken, verb, "help")
        record = room.resolve(host_id, host_token)
        self.assertTrue(any(m["source"] == "ability:loophole_sense" for m in record["modifiers"]))

    def test_ilona_protect_reduces_damage_by_two(self):
        registry, room, host_id, host_token, players_by_hero = self._room_with_hero_as_spotlight("otis_barnstorm")
        encounter = ENCOUNTERS[room._encounter_order[0]]
        # Play the resistant school to guarantee a backfire this round.
        move_id = next(
            mid for mid in MOVES_FOR(room, "otis_barnstorm")
            if ALL_MOVES[mid].school == encounter.resistant
        )
        allies = [h for h in HERO_IDS if h != "otis_barnstorm"]
        pid, token = players_by_hero["otis_barnstorm"]
        room.submit_spotlight_action(pid, token, move_id, _first_target(room), "x")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "reaction", "")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            verb = "protect" if hid == "ilona_softword" else "assist"
            room.submit_reaction(apid, atoken, verb, "help")
        record = room.resolve(host_id, host_token)
        protect_mod = next(m for m in record["modifiers"] if m["source"] == "reaction:ilona_softword")
        self.assertEqual(protect_mod["value"], -2)

    def test_bram_steady_hand_reduces_damage_on_eligible_moves(self):
        registry, room, host_id, host_token, players_by_hero = self._room_with_hero_as_spotlight("bram_correctly")
        pid, token = players_by_hero["bram_correctly"]
        allies = [h for h in HERO_IDS if h != "bram_correctly"]
        room.submit_spotlight_action(pid, token, "precision_bonk", _first_target(room), "x")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "reaction", "")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_reaction(apid, atoken, "assist", "help")
        record = room.resolve(host_id, host_token)
        self.assertTrue(any(m["source"] == "ability:steady_hand" for m in record["modifiers"]))


class ChallengeRiskTests(unittest.TestCase):
    def test_challenge_adds_risk_only_on_backfire(self):
        registry, room, players_by_hero = _make_four_human_room(seed=1)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        encounter = ENCOUNTERS[room._encounter_order[0]]
        move_id = next(
            mid for mid in MOVES_FOR(room, hero_id) if ALL_MOVES[mid].school == encounter.resistant
        )
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, move_id, _first_target(room), "x")
        allies = [h for h in HERO_IDS if h != hero_id]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "reaction", "")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_reaction(apid, atoken, "challenge", "help")
        record = room.resolve(host_id, host_token)
        if record["score"] < 0:
            self.assertTrue(any(m["source"] == "challenge_risk" for m in record["modifiers"]))

    def test_no_challenge_risk_modifier_when_not_backfiring(self):
        registry, room, players_by_hero = _make_four_human_room(seed=1)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        encounter = ENCOUNTERS[room._encounter_order[0]]
        move_id = next(
            mid for mid in MOVES_FOR(room, hero_id) if ALL_MOVES[mid].school == encounter.weakness
        )
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, move_id, encounter.true_target, "x")
        allies = [h for h in HERO_IDS if h != hero_id]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_support(apid, atoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            room.submit_reaction(apid, atoken, "assist", "help")
        record = room.resolve(host_id, host_token)
        self.assertGreaterEqual(record["score"], 0)
        self.assertFalse(any(m["source"] == "challenge_risk" for m in record["modifiers"]))


class RevealedCluesTests(unittest.TestCase):
    def test_clue_support_and_interpret_reveal_the_clue_after_resolve(self):
        registry, room, players_by_hero = _make_four_human_room(seed=2)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        encounter = ENCOUNTERS[room._encounter_order[0]]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        allies = [h for h in HERO_IDS if h != hero_id]
        clue_giver = allies[0]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            kind = "clue" if hid == clue_giver else "assist"
            room.submit_support(apid, atoken, kind, "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        interpreter = allies[1]
        for hid in allies:
            apid, atoken = players_by_hero[hid]
            verb = "interpret" if hid == interpreter else "assist"
            room.submit_reaction(apid, atoken, verb, "help")
        record = room.resolve(host_id, host_token)
        revealed_ids = {c["hero_id"] for c in record["revealed_clues"]}
        self.assertIn(clue_giver, revealed_ids)
        self.assertIn(interpreter, revealed_ids)
        self.assertNotIn(hero_id, revealed_ids)
        for c in record["revealed_clues"]:
            self.assertEqual(c["clue_text"], encounter.clues[c["hero_id"]])
        self.assertEqual(record["true_target_id"], encounter.true_target)


def _worst_available_move(room, hero_id):
    """Prefer a move matching the encounter's resistant school (a genuine
    backfire); fall back to neutral; only as a last resort (a hero whose
    entire kit happens to be their weakness school, e.g. Otis vs a
    bonk-weak encounter) does this end up being a good play regardless."""
    hero_moves = MOVES_FOR(room, hero_id)
    encounter = ENCOUNTERS[room._encounter_order[room.encounter_index]]
    resistant_matches = [mid for mid in hero_moves if ALL_MOVES[mid].school == encounter.resistant]
    if resistant_matches:
        return resistant_matches[0]
    neutral_matches = [mid for mid in hero_moves if ALL_MOVES[mid].school == encounter.neutral]
    if neutral_matches:
        return neutral_matches[0]
    return hero_moves[0]


class VictoryDefeatTests(unittest.TestCase):
    def test_correct_target_and_full_assist_guarantees_victory(self):
        # Every hero's kit spans at most 3 schools and the worst possible
        # single-round total (resistant base -2, worst die -2) is always
        # more than offset by a correct target (+1) plus 3 assisting allies
        # in both the support and reaction phases (+3 each) -- this holds
        # regardless of which move the Spotlight happens to play, so no
        # weakness-matching is needed for this strategy to be safe.
        registry, room, players_by_hero = _make_four_human_room(seed=13)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        rounds = 0
        while room.public_state()["phase"] != "finished":
            hero_id = room.public_state()["spotlight_hero_id"]
            encounter = ENCOUNTERS[room._encounter_order[room.encounter_index]]
            pid, token = players_by_hero[hero_id]
            room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], encounter.true_target, "x")
            allies = [h for h in HERO_IDS if h != hero_id]
            for hid in allies:
                apid, atoken = players_by_hero[hid]
                room.submit_support(apid, atoken, "assist", "help")
            room.open_draft(host_id, host_token)
            room.submit_rough_text(pid, token, "rough")
            room.submit_variants(pid, token, ["a", "b", "c"])
            room.approve_message(pid, token, "a", "intent")
            for hid in allies:
                apid, atoken = players_by_hero[hid]
                room.submit_reaction(apid, atoken, "assist", "help")
            room.resolve(host_id, host_token)
            rounds += 1
            if room.public_state()["phase"] == "reveal":
                room.advance(host_id, host_token)
            self.assertLess(rounds, 10)
        self.assertTrue(room.public_state()["finished_victory"])
        self.assertEqual(room.public_state()["hearts"], room.public_state()["max_hearts"])

    def test_worst_available_play_can_cause_defeat(self):
        # Not every hero's kit contains a move matching every encounter's
        # resistant school (e.g. Otis is bonk-only), so this searches a
        # range of seeds for one where playing each Spotlight's worst
        # available matchup on the wrong target actually depletes hearts to
        # 0. Allies react with "assist" rather than "protect": protect
        # would trigger Ilona's own damage-reduction ability whenever she's
        # an (unavoidably frequent) ally, which -- being a flat, larger
        # reduction than a single "assist" -- would otherwise cancel almost
        # every round's backfire regardless of how badly the Spotlight played.
        for seed in range(1, 60):
            registry, room, players_by_hero = _make_four_human_room(seed=seed)
            host_id = room.host_id
            host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
            room.start(host_id, host_token)
            rounds = 0
            while room.public_state()["phase"] != "finished":
                hero_id = room.public_state()["spotlight_hero_id"]
                encounter = ENCOUNTERS[room._encounter_order[room.encounter_index]]
                move_id = _worst_available_move(room, hero_id)
                wrong_target = next(t for t in encounter.targets if t != encounter.true_target)
                pid, token = players_by_hero[hero_id]
                room.submit_spotlight_action(pid, token, move_id, wrong_target, "x")
                allies = [h for h in HERO_IDS if h != hero_id]
                for hid in allies:
                    apid, atoken = players_by_hero[hid]
                    room.submit_support(apid, atoken, "reaction", "")
                room.open_draft(host_id, host_token)
                room.submit_rough_text(pid, token, "rough")
                room.submit_variants(pid, token, ["a", "b", "c"])
                room.approve_message(pid, token, "a", "intent")
                for hid in allies:
                    apid, atoken = players_by_hero[hid]
                    room.submit_reaction(apid, atoken, "assist", "")
                room.resolve(host_id, host_token)
                rounds += 1
                if room.public_state()["phase"] == "reveal":
                    room.advance(host_id, host_token)
                self.assertLess(rounds, 10)
            if room.public_state()["finished_victory"] is False:
                self.assertEqual(room.public_state()["hearts"], 0)
                return
        self.fail("no seed in range produced a defeat under worst-available play")


class ReplayTests(unittest.TestCase):
    def test_replay_reseeds_resets_state_and_keeps_roster(self):
        registry, room, players_by_hero = _make_four_human_room(seed=8)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        ally_hero = next(h for h in HERO_IDS if h != hero_id)
        apid, atoken = players_by_hero[ally_hero]
        pid, token = players_by_hero[hero_id]
        room.submit_spotlight_action(pid, token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x")
        room.submit_support(apid, atoken, "item", "gadget")
        for hid in HERO_IDS:
            if hid == hero_id or hid == ally_hero:
                continue
            xpid, xtoken = players_by_hero[hid]
            room.submit_support(xpid, xtoken, "assist", "help")
        room.open_draft(host_id, host_token)
        room.submit_rough_text(pid, token, "rough")
        room.submit_variants(pid, token, ["a", "b", "c"])
        room.approve_message(pid, token, "a", "intent")
        for hid in HERO_IDS:
            if hid == hero_id:
                continue
            xpid, xtoken = players_by_hero[hid]
            room.submit_reaction(xpid, xtoken, "assist", "help")
        room.resolve(host_id, host_token)
        original_seed = room.seed
        # Force straight to finished for a clean replay test regardless of hearts.
        room.hearts = 0
        room.phase = "finished"
        room.finished_victory = False
        room.replay(host_id, host_token)
        self.assertEqual(room.phase, "lobby")
        self.assertEqual(room.hearts, room.max_hearts)
        self.assertEqual(room.encounter_index, 0)
        self.assertNotEqual(room.seed, original_seed)
        self.assertEqual(room.seed, original_seed + 1)
        ally_entry = next(h for h in room.public_state()["heroes"] if h["hero_id"] == ally_hero)
        self.assertEqual(ally_entry["items_remaining"], ITEM_STARTING_COUNT)
        self.assertEqual(set(room._player_hero.values()), set(HERO_IDS))

    def test_replay_with_explicit_seed_is_reproducible(self):
        _, room, host_id, host_token = _new_room(seed=1)
        room.start(host_id, host_token)
        room.hearts = 0
        room.phase = "finished"
        room.finished_victory = False
        room.replay(host_id, host_token, seed=999)
        self.assertEqual(room.seed, 999)


class DisconnectHostSuccessionTests(unittest.TestCase):
    def test_host_disconnect_promotes_next_active_player(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.disconnect(host_id, host_token)
        self.assertEqual(room.host_id, p2)
        self.assertTrue(room.public_state()["players"][1]["is_host"])

    def test_solo_host_disconnect_does_not_deadlock_and_hero_becomes_companion(self):
        _, room, host_id, host_token = _new_room()
        room.disconnect(host_id, host_token)
        self.assertEqual(room.host_id, host_id)
        hero_id = room.public_state()["you"]["hero_id"] if False else next(iter(room._player_hero.values()))
        self.assertTrue(room._hero_is_companion_locked(hero_id))
        room.reconnect(host_id, host_token)
        self.assertFalse(room._hero_is_companion_locked(hero_id))

    def test_disconnect_mid_spotlight_turn_autoplays_and_unblocks_the_room(self):
        # The host is always bound to hero_order[0], which is also always
        # round 0's Spotlight -- so round 1 (a different hero) is where the
        # disconnecting player is guaranteed not to be the host.
        registry, room, players_by_hero = _make_four_human_room(seed=5)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        _advance_full_round(room, host_id, host_token, players_by_hero)
        room.advance(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        pid, token = players_by_hero[hero_id]
        self.assertNotEqual(pid, host_id)
        room.disconnect(pid, token)
        # Spotlight hero is now a companion; their action should already be filled.
        self.assertIsNotNone(room._action)
        self.assertEqual(room.phase, "ally_support")


class SoloCompanionPathTests(unittest.TestCase):
    def test_solo_game_reaches_finished_via_companion_autoplay(self):
        _, room, host_id, host_token = _new_room(seed=11)
        room.start(host_id, host_token)
        rounds = 0
        while room.public_state()["phase"] != "finished":
            phase = room.public_state()["phase"]
            if phase == "ally_support":
                you = room.public_state(host_id)["you"]
                if you["pending_step"] == "submit_support":
                    room.submit_support(host_id, host_token, "assist", "help")
                elif you["pending_step"] == "open_draft":
                    room.open_draft(host_id, host_token)
            elif phase == "spotlight_draft":
                # Either the human is spotlight (submit their own draft) or a
                # companion already auto-completed it.
                you = room.public_state(host_id)["you"]
                if you["hero_id"] == room.public_state()["spotlight_hero_id"] and you["draft"] is not None:
                    if you["draft"]["rough_text"] is None:
                        room.submit_rough_text(host_id, host_token, "we handle it")
                    elif you["draft"]["variants"] is None:
                        room.submit_variants(host_id, host_token, ["a", "b", "c"])
                    elif you["draft"]["approved_text"] is None:
                        room.approve_message(host_id, host_token, "a", "resolve it")
            elif phase == "ally_reaction":
                if room.can_resolve():
                    room.resolve(host_id, host_token)
                else:
                    you = room.public_state(host_id)["you"]
                    if you["pending_step"] == "submit_reaction":
                        room.submit_reaction(host_id, host_token, "assist", "help")
            elif phase == "reveal":
                room.advance(host_id, host_token)
            elif phase == "spotlight_action":
                you = room.public_state(host_id)["you"]
                if you["pending_step"] == "declare_action":
                    hero_id = room.public_state()["spotlight_hero_id"]
                    room.submit_spotlight_action(
                        host_id, host_token, MOVES_FOR(room, hero_id)[0], _first_target(room), "x"
                    )
            rounds += 1
            self.assertLess(rounds, 200)
        self.assertIn(room.public_state()["finished_victory"], (True, False))


class VoiceProfileTests(unittest.TestCase):
    def test_update_voice_profile_bounds_and_stores_only_allowed_scalars(self):
        _, room, host_id, host_token = _new_room()
        room.update_voice_profile(
            host_id, host_token, {"utterance_count": 99999, "confidence": 5.0, "calibrated": True, "raw_audio": b"nope"}
        )
        state = room.public_state(viewer_player_id=host_id)
        self.assertEqual(state["you"]["voice_profile"]["utterance_count"], 9999)
        self.assertEqual(state["you"]["voice_profile"]["confidence"], 1.0)
        self.assertTrue(state["you"]["voice_profile"]["calibrated"])
        self.assertNotIn("raw_audio", state["you"]["voice_profile"])

    def test_voice_profile_never_leaks_to_other_viewers(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        room.update_voice_profile(host_id, host_token, {"calibrated": True})
        other_state = room.public_state(viewer_player_id=p2)
        self.assertEqual(other_state["you"]["voice_profile"], {})
        host_hero = next(h for h in other_state["heroes"] if h["player_id"] == host_id)
        self.assertTrue(host_hero["voice_calibrated"])


class ExceptionAndAuthTests(unittest.TestCase):
    def test_unknown_player_and_bad_token_rejected(self):
        _, room, host_id, host_token = _new_room()
        with self.assertRaises(UnknownPlayerError):
            room.start("not_a_real_id", "whatever")
        with self.assertRaises(Exception):
            room.start(host_id, "wrong-token")

    def test_non_host_cannot_start_resolve_advance_replay(self):
        _, room, host_id, host_token = _new_room()
        p2, t2 = room.join("Guest")
        with self.assertRaises(NotHostError):
            room.start(p2, t2)

    def test_verify_token_never_raises(self):
        _, room, host_id, host_token = _new_room()
        self.assertTrue(room.verify_token(host_id, host_token))
        self.assertFalse(room.verify_token(host_id, "garbage"))
        self.assertFalse(room.verify_token("nope", "garbage"))


class SetFlavorCosmeticTests(unittest.TestCase):
    def test_set_flavor_never_changes_score_or_damage(self):
        registry, room, players_by_hero = _make_four_human_room(seed=6)
        host_id = room.host_id
        host_token = next(t for pid, t in players_by_hero.values() if pid == host_id)
        room.start(host_id, host_token)
        hero_id = room.public_state()["spotlight_hero_id"]
        encounter = ENCOUNTERS[room._encounter_order[0]]
        room.set_flavor(f"encounter:{encounter.id}", "A dramatically rewritten scene description.")
        record = _advance_full_round(room, host_id, host_token, players_by_hero)
        self.assertEqual(record["encounter"]["flavor"], "A dramatically rewritten scene description.")
        expected_rng = random.Random(room.seed * 1_000_003 + 0)
        self.assertEqual(record["die_roll"], expected_rng.randint(1, 6))


if __name__ == "__main__":
    unittest.main()
