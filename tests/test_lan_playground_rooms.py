"""Tests for backend.lan_playground.rooms (board task #2).

Exercises RoomManager/VariantGenerator/NarrationComposer/GameAdapter against
the real game.GameRegistry/Room (backend/lan_playground/game.py, board
task #1) -- no fakes for the engine itself, since that contract is frozen
and tested independently in tests/test_lan_game_engine.py. These tests
cover what rooms.py actually adds on top: idle-room TTL pruning, room-count
capping, engine-error translation, the BetterFingers draft-variant
generator, and the post-resolve narration composer, both with their
deterministic/never-hangs fallbacks.
"""

import threading
import time
import unittest

from backend.lan_playground import game
from backend.lan_playground.rooms import (
    GameAdapter,
    NarrationComposer,
    RoomManager,
    RoomNotFoundError,
    TooManyRoomsError,
    VariantGenerator,
    translate_engine_error,
)


def _manager(**kwargs):
    defaults = dict(clock=time.monotonic)
    defaults.update(kwargs)
    return RoomManager(**defaults)


class CreateRoomTests(unittest.TestCase):
    def test_create_room_returns_short_code_and_real_engine_room(self):
        mgr = _manager()
        code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=1)
        self.assertEqual(len(code), 8)
        self.assertIsInstance(room, game.Room)
        self.assertEqual(room.host_id, host_id)
        self.assertTrue(room.verify_token(host_id, host_token))
        # The engine's own long room_id must never equal the short public code.
        self.assertNotEqual(code, room.room_id)

    def test_room_cap_enforced(self):
        mgr = _manager(max_rooms=2)
        mgr.create_room(host_name="A", seed=1)
        mgr.create_room(host_name="B", seed=2)
        with self.assertRaises(TooManyRoomsError):
            mgr.create_room(host_name="C", seed=3)

    def test_room_codes_do_not_collide_in_practice(self):
        mgr = _manager(max_rooms=50)
        codes = set()
        for i in range(20):
            code, _room, _hid, _tok = mgr.create_room(host_name=f"P{i}", seed=i)
            codes.add(code)
        self.assertEqual(len(codes), 20)


class GetRoomTests(unittest.TestCase):
    def test_get_room_returns_same_instance_by_public_code(self):
        mgr = _manager()
        code, room, _hid, _tok = mgr.create_room(host_name="Ava")
        self.assertIs(mgr.get_room(code), room)

    def test_get_unknown_room_raises(self):
        mgr = _manager()
        with self.assertRaises(RoomNotFoundError):
            mgr.get_room("NOPE0000")

    def test_engine_room_id_does_not_work_as_a_lookup_code(self):
        mgr = _manager()
        _code, room, _hid, _tok = mgr.create_room(host_name="Ava")
        with self.assertRaises(RoomNotFoundError):
            mgr.get_room(room.room_id)


class TokenLookupTests(unittest.TestCase):
    def test_player_id_for_token_resolves_host_and_guest(self):
        mgr = _manager()
        code, room, host_id, host_token = mgr.create_room(host_name="Ava")
        guest_id, guest_token = room.join("Beau")
        mgr.record_token(code, guest_id, guest_token)
        self.assertEqual(mgr.player_id_for_token(code, host_token), host_id)
        self.assertEqual(mgr.player_id_for_token(code, guest_token), guest_id)

    def test_player_id_for_token_rejects_unknown_or_empty_token(self):
        mgr = _manager()
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        self.assertIsNone(mgr.player_id_for_token(code, "not-a-real-token"))
        self.assertIsNone(mgr.player_id_for_token(code, ""))


class ExpiryTests(unittest.TestCase):
    def test_stale_room_is_pruned_and_then_not_found(self):
        clock = {"t": 0.0}
        mgr = _manager(clock=lambda: clock["t"], ttl_s=100.0)
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        clock["t"] = 50.0
        mgr.touch(code)  # still alive, refreshes activity
        clock["t"] = 200.0  # 150s since last touch > ttl_s=100
        with self.assertRaises(RoomNotFoundError):
            mgr.get_room(code)

    def test_active_room_survives_within_ttl(self):
        clock = {"t": 0.0}
        mgr = _manager(clock=lambda: clock["t"], ttl_s=100.0)
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        clock["t"] = 90.0
        mgr.get_room(code)  # should not raise

    def test_prune_stale_returns_removed_codes_and_frees_capacity(self):
        clock = {"t": 0.0}
        mgr = _manager(clock=lambda: clock["t"], ttl_s=10.0, max_rooms=1)
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        clock["t"] = 100.0
        removed = mgr.prune_stale()
        self.assertEqual(removed, [code])
        # Capacity freed -- a second room can now be created despite max_rooms=1.
        mgr.create_room(host_name="Zed")

    def test_untouched_but_never_created_code_does_not_error_on_touch(self):
        mgr = _manager()
        mgr.touch("NEVER000")  # must not raise

    def test_pruning_also_clears_narration_cache(self):
        clock = {"t": 0.0}
        mgr = _manager(clock=lambda: clock["t"], ttl_s=10.0)
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        mgr.set_narration(code, 0, "The clerk nods.")
        clock["t"] = 100.0
        mgr.prune_stale()
        self.assertIsNone(mgr.get_narration(code, 0))


class NarrationCacheTests(unittest.TestCase):
    def test_set_and_get_narration_roundtrip(self):
        mgr = _manager()
        code, _room, _hid, _tok = mgr.create_room(host_name="Ava")
        self.assertIsNone(mgr.get_narration(code, 0))
        mgr.set_narration(code, 0, "A dazzling save.")
        self.assertEqual(mgr.get_narration(code, 0), "A dazzling save.")
        # Different round index is independent.
        self.assertIsNone(mgr.get_narration(code, 1))


class EngineErrorTranslationTests(unittest.TestCase):
    def test_translate_known_error_types(self):
        self.assertEqual(translate_engine_error(game.RoomFullError()), "room_full")
        self.assertEqual(translate_engine_error(game.InvalidPhaseError()), "wrong_phase")
        self.assertEqual(translate_engine_error(game.NotHostError()), "not_host")
        self.assertEqual(translate_engine_error(game.WrongTurnError()), "wrong_turn")
        self.assertEqual(translate_engine_error(game.UnknownPlayerError()), "invalid_player_token")
        self.assertEqual(translate_engine_error(game.InvalidTokenError()), "invalid_player_token")
        self.assertEqual(translate_engine_error(game.AlreadySubmittedError()), "already_submitted")
        self.assertEqual(translate_engine_error(game.NotAllSubmittedError()), "not_all_submitted")
        self.assertEqual(translate_engine_error(game.InvalidMoveError()), "invalid_move")
        self.assertEqual(translate_engine_error(game.InvalidTargetError()), "invalid_target")
        self.assertEqual(translate_engine_error(game.InvalidSupportKindError()), "invalid_support_kind")
        self.assertEqual(translate_engine_error(game.InvalidReactionVerbError()), "invalid_reaction_verb")
        self.assertEqual(translate_engine_error(game.NoItemsRemainingError()), "no_items_remaining")
        self.assertEqual(translate_engine_error(game.InvalidVariantsError()), "invalid_variants")

    def test_unknown_player_and_invalid_token_are_indistinguishable_on_the_wire(self):
        # Deliberate: both map to the same code so a caller can't use the
        # HTTP response to probe whether a given player_id exists.
        self.assertEqual(
            translate_engine_error(game.UnknownPlayerError()),
            translate_engine_error(game.InvalidTokenError()),
        )

    def test_translate_unknown_error_falls_back(self):
        self.assertEqual(translate_engine_error(ValueError("whatever")), "engine_error")

    def test_translation_reflects_real_engine_rejection(self):
        mgr = _manager()
        _code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=1)
        # Auth happens before the host check, so an unknown player_id raises
        # UnknownPlayerError here, not NotHostError -- confirm that path
        # translates to the same fixed code invalid tokens do.
        with self.assertRaises(game.UnknownPlayerError) as ctx:
            room.start("not-a-real-player", "bad-token")
        self.assertEqual(translate_engine_error(ctx.exception), "invalid_player_token")

        guest_id, guest_token = room.join("Beau")
        with self.assertRaises(game.NotHostError) as ctx2:
            room.start(guest_id, guest_token)
        self.assertEqual(translate_engine_error(ctx2.exception), "not_host")


class VariantGeneratorTests(unittest.TestCase):
    def test_generate_returns_three_named_variants(self):
        def call_fn(messages):
            import json

            return json.dumps(
                {"assessment": {}, "variants": {"faithful": "We cite the ledger.", "clearer": "Per the ledger.", "alternate": "Ledger, please."}}
            )

        gen = VariantGenerator(call_fn=call_fn)
        variants = gen.generate(rough_text="we point at the ledger")
        self.assertEqual(variants, ["We cite the ledger.", "Per the ledger.", "Ledger, please."])

    def test_no_call_fn_returns_none(self):
        gen = VariantGenerator(call_fn=None)
        self.assertIsNone(gen.generate(rough_text="raw text"))

    def test_engine_not_ready_returns_none(self):
        gen = VariantGenerator(call_fn=lambda messages: "unused", engine_ready_fn=lambda: False)
        self.assertIsNone(gen.generate(rough_text="raw text"))

    def test_call_fn_exception_falls_back_to_rough_text(self):
        # rescue_message() itself shields call_fn exceptions (converts them
        # into its own fallback result rather than propagating) -- so this
        # never hits VariantGenerator's own try/except, it just produces an
        # all-empty variants dict that our per-slot fallback fills with
        # rough_text, same as the malformed-output case.
        def broken(messages):
            raise RuntimeError("model exploded")

        gen = VariantGenerator(call_fn=broken)
        variants = gen.generate(rough_text="raw text")
        self.assertEqual(variants, ["raw text"] * 3)

    def test_malformed_output_falls_back_to_rough_text_per_slot(self):
        gen = VariantGenerator(call_fn=lambda messages: "not json at all {{{")
        variants = gen.generate(rough_text="call me back at 555-1234")
        self.assertEqual(len(variants), 3)
        self.assertTrue(all(v == "call me back at 555-1234" for v in variants))

    def test_start_and_bounded_wait_returns_result(self):
        def call_fn(messages):
            import json

            return json.dumps({"assessment": {}, "variants": {"faithful": "a", "clearer": "b", "alternate": "c"}})

        gen = VariantGenerator(call_fn=call_fn)
        event, box = gen.start(rough_text="raw")
        self.assertTrue(event.wait(timeout=5))
        self.assertEqual(box["variants"], ["a", "b", "c"])

    def test_start_with_slow_model_bounded_wait_never_hangs(self):
        release = threading.Event()

        def slow_call_fn(messages):
            release.wait(timeout=5)
            return "too slow to matter"

        gen = VariantGenerator(call_fn=slow_call_fn)
        event, box = gen.start(rough_text="raw")
        started = time.monotonic()
        finished = event.wait(timeout=0.05)
        elapsed = time.monotonic() - started
        self.assertFalse(finished)
        self.assertLess(elapsed, 1.0)
        self.assertIsNone(box["variants"])  # not filled yet -- caller must fall back
        release.set()

    def test_start_with_no_call_fn_sets_event_immediately(self):
        gen = VariantGenerator(call_fn=None)
        event, box = gen.start(rough_text="raw")
        self.assertTrue(event.is_set())
        self.assertIsNone(box["variants"])


class NarrationComposerTests(unittest.TestCase):
    _ROUND_RECORD = {
        "round": 0,
        "encounter": {"id": "goblin_hr_department", "name": "The Goblin HR Department"},
        "action": {"move": "Empathic Mirror", "move_id": "empathic_mirror", "target_id": "the tiny rubber stamp", "desired_outcome": "settle it"},
        "true_target_id": "the tiny rubber stamp",
        "revealed_clues": [],
        "modifiers": [{"source": "school_match", "label": "Empathic Mirror vs Goblin HR", "value": 1, "affects": "score"}],
        "die_roll": 4,
        "score": 2,
        "damage": 0,
        "hearts_before": 3,
        "hearts_after": 3,
    }

    def test_narrate_returns_model_text(self):
        composer = NarrationComposer(call_fn=lambda messages: "The clerk nods, satisfied.")
        text = composer.narrate(round_record=self._ROUND_RECORD)
        self.assertEqual(text, "The clerk nods, satisfied.")

    def test_no_call_fn_falls_back_deterministically(self):
        composer = NarrationComposer(call_fn=None)
        text = composer.narrate(round_record=self._ROUND_RECORD)
        self.assertTrue(text)
        self.assertEqual(text, composer.fallback(self._ROUND_RECORD))

    def test_call_fn_exception_falls_back(self):
        def broken(messages):
            raise RuntimeError("boom")

        composer = NarrationComposer(call_fn=broken)
        text = composer.narrate(round_record=self._ROUND_RECORD)
        self.assertEqual(text, composer.fallback(self._ROUND_RECORD))

    def test_fallback_never_empty_and_reflects_damage(self):
        composer = NarrationComposer(call_fn=None)
        no_damage = dict(self._ROUND_RECORD, damage=0)
        with_damage = dict(self._ROUND_RECORD, damage=2)
        self.assertNotEqual(composer.fallback(no_damage), composer.fallback(with_damage))
        self.assertTrue(composer.fallback(no_damage))
        self.assertTrue(composer.fallback(with_damage))

    def test_prompt_never_promises_to_invent_facts(self):
        captured = {}

        def call_fn(messages):
            captured["system"] = messages[0]["content"]
            return "fine"

        composer = NarrationComposer(call_fn=call_fn)
        composer.narrate(round_record=self._ROUND_RECORD)
        self.assertIn("do not invent", captured["system"].lower())

    def test_facts_context_never_includes_approved_text(self):
        captured = {}

        def call_fn(messages):
            captured["user"] = messages[1]["content"]
            return "fine"

        record = dict(self._ROUND_RECORD)
        record["action"] = dict(record["action"], approved_text="a very specific secret-ish phrase")
        composer = NarrationComposer(call_fn=call_fn)
        composer.narrate(round_record=record)
        self.assertNotIn("a very specific secret-ish phrase", captured["user"])

    def test_start_with_slow_model_bounded_wait_never_hangs(self):
        release = threading.Event()

        def slow_call_fn(messages):
            release.wait(timeout=5)
            return "too slow"

        composer = NarrationComposer(call_fn=slow_call_fn)
        event, box = composer.start(round_record=self._ROUND_RECORD)
        started = time.monotonic()
        finished = event.wait(timeout=0.05)
        elapsed = time.monotonic() - started
        self.assertFalse(finished)
        self.assertLess(elapsed, 1.0)
        self.assertIsNone(box["narration"])
        release.set()


class GameAdapterEngineIntegrationTests(unittest.TestCase):
    """End-to-end through the real engine: draft variants -> approve ->
    resolve, confirming the modifier ledger only ever reads move_id/
    target_id/verb + the seeded die, never the free-text draft/approved
    message this module generates -- and that narration composed from the
    resulting round_record never blocks."""

    def test_variant_and_narration_pipeline_against_real_engine(self):
        mgr = _manager()
        _code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=1)
        adapter = GameAdapter(room)
        adapter.start(host_id, host_token)

        state = adapter.public_state(host_id)
        spotlight_hero = next(h for h in state["heroes"] if h["hero_id"] == state["spotlight_hero_id"])
        move_id = spotlight_hero["deck"][0]["id"]
        target_id = state["encounter"]["targets"][0]
        adapter.submit_spotlight_action(host_id, host_token, move_id, target_id, "handle it")
        adapter.open_draft(host_id, host_token)  # host, once support autoplay-completes for companions

        adapter.submit_rough_text(host_id, host_token, "we point at the target plainly")
        variants = ["We cite the precedent.", "Per the record.", "As documented."]
        adapter.submit_variants(host_id, host_token, variants)
        adapter.approve_message(host_id, host_token, variants[1], "resolve calmly")

        record = adapter.resolve(host_id, host_token)
        self.assertEqual(record["action"]["approved_text"], "Per the record.")
        self.assertEqual(record["action"]["move_id"], move_id)  # scoring input untouched by approved_text

        composer = NarrationComposer(call_fn=lambda messages: "The record speaks for itself.")
        narration = composer.narrate(round_record=record)
        self.assertEqual(narration, "The record speaks for itself.")

    def test_narration_prompt_excludes_approved_text_end_to_end(self):
        mgr = _manager()
        _code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=2)
        adapter = GameAdapter(room)
        adapter.start(host_id, host_token)
        state = adapter.public_state(host_id)
        spotlight_hero = next(h for h in state["heroes"] if h["hero_id"] == state["spotlight_hero_id"])
        move_id = spotlight_hero["deck"][0]["id"]
        target_id = state["encounter"]["targets"][0]
        adapter.submit_spotlight_action(host_id, host_token, move_id, target_id, "handle it")
        adapter.open_draft(host_id, host_token)
        adapter.submit_rough_text(host_id, host_token, "raw draft")
        adapter.submit_variants(host_id, host_token, ["a", "b", "c"])
        adapter.approve_message(host_id, host_token, "a very singular phrase nobody else would say", "resolve it")
        record = adapter.resolve(host_id, host_token)

        captured = {}

        def call_fn(messages):
            captured["user"] = messages[1]["content"]
            return "narration"

        NarrationComposer(call_fn=call_fn).narrate(round_record=record)
        self.assertNotIn("a very singular phrase nobody else would say", captured["user"])


if __name__ == "__main__":
    unittest.main()
