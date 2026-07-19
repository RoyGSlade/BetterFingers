"""Tests for backend.lan_playground.rooms (board task #40).

Exercises RoomManager/MovePolisher against the real game.GameRegistry/Room
(backend/lan_playground/game.py, board #39) -- no fakes for the engine
itself, since that contract is now frozen and tested independently in
tests/test_lan_game_engine.py. These tests cover what rooms.py actually
adds on top: idle-room TTL pruning, room-count capping, engine-error
translation, and the move-text polish background job with its deterministic
fallback.
"""

import threading
import time
import unittest

from backend.lan_playground import game
from backend.lan_playground.rooms import (
    MovePolisher,
    RoomManager,
    RoomNotFoundError,
    TooManyRoomsError,
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


class HostCredentialsTests(unittest.TestCase):
    def test_host_credentials_returns_creator_by_default(self):
        mgr = _manager()
        code, room, host_id, host_token = mgr.create_room(host_name="Ava")
        creds = mgr.host_credentials(code, room)
        self.assertEqual(creds, (host_id, host_token))

    def test_host_credentials_follows_succession_after_record_token(self):
        mgr = _manager()
        code, room, host_id, host_token = mgr.create_room(host_name="Ava")
        guest_id, guest_token = room.join("Beau")
        mgr.record_token(code, guest_id, guest_token)

        room.disconnect(host_id, host_token)  # promotes Beau to host
        self.assertEqual(room.host_id, guest_id)

        creds = mgr.host_credentials(code, room)
        self.assertEqual(creds, (guest_id, guest_token))

    def test_host_credentials_returns_none_if_token_never_recorded(self):
        mgr = _manager()
        code, room, host_id, host_token = mgr.create_room(host_name="Ava")
        guest_id, guest_token = room.join("Beau")
        # Deliberately not calling record_token for the guest.
        room.disconnect(host_id, host_token)
        self.assertEqual(room.host_id, guest_id)
        self.assertIsNone(mgr.host_credentials(code, room))


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


class EngineErrorTranslationTests(unittest.TestCase):
    def test_translate_known_error_types(self):
        self.assertEqual(translate_engine_error(game.RoomFullError()), "room_full")
        self.assertEqual(translate_engine_error(game.InvalidPhaseError()), "wrong_phase")
        self.assertEqual(translate_engine_error(game.NotHostError()), "not_host")
        self.assertEqual(translate_engine_error(game.UnknownPlayerError()), "invalid_player_token")
        self.assertEqual(translate_engine_error(game.InvalidTokenError()), "invalid_player_token")
        self.assertEqual(translate_engine_error(game.InactivePlayerError()), "inactive_player")
        self.assertEqual(translate_engine_error(game.AlreadySubmittedError()), "already_submitted")
        self.assertEqual(translate_engine_error(game.NotAllSubmittedError()), "not_all_submitted")
        self.assertEqual(translate_engine_error(game.InvalidApproachError()), "invalid_approach")

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


class MovePolisherTests(unittest.TestCase):
    def test_start_and_resolve_returns_polished_text(self):
        def call_fn(messages):
            return "A dashing one-liner!"

        polisher = MovePolisher(call_fn=call_fn, timeout_s=5.0)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="charm", move_text="I try to charm the dragon")
        text = polisher.resolve(("room1", 0, "p_a"))
        self.assertEqual(text, "A dashing one-liner!")

    def test_resolve_without_start_returns_none(self):
        polisher = MovePolisher(call_fn=lambda messages: "unused")
        self.assertIsNone(polisher.resolve(("room1", 0, "p_a")))

    def test_model_unavailable_returns_none(self):
        polisher = MovePolisher(call_fn=lambda messages: "should not be used", engine_ready_fn=lambda: False)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="bonk", move_text="raw move")
        self.assertIsNone(polisher.resolve(("room1", 0, "p_a")))

    def test_call_fn_exception_returns_none(self):
        def broken_call_fn(messages):
            raise RuntimeError("model exploded")

        polisher = MovePolisher(call_fn=broken_call_fn)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="scheme", move_text="raw move")
        self.assertIsNone(polisher.resolve(("room1", 0, "p_a")))

    def test_slow_model_beyond_timeout_returns_none_without_hanging(self):
        release = threading.Event()

        def slow_call_fn(messages):
            release.wait(timeout=5)
            return "too slow to matter"

        polisher = MovePolisher(call_fn=slow_call_fn, timeout_s=0.05)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="charm", move_text="raw move")
        started = time.monotonic()
        text = polisher.resolve(("room1", 0, "p_a"))
        elapsed = time.monotonic() - started
        self.assertIsNone(text)
        self.assertLess(elapsed, 2.0)
        release.set()

    def test_no_call_fn_means_no_op(self):
        polisher = MovePolisher(call_fn=None)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="charm", move_text="raw move")
        self.assertIsNone(polisher.resolve(("room1", 0, "p_a")))

    def test_empty_model_output_returns_none(self):
        polisher = MovePolisher(call_fn=lambda messages: "   ")
        polisher.start(("room1", 0, "p_a"), persona=None, approach="charm", move_text="raw move")
        self.assertIsNone(polisher.resolve(("room1", 0, "p_a")))

    def test_output_is_length_bounded_to_engine_move_text_max(self):
        def call_fn(messages):
            return "y" * 5000

        polisher = MovePolisher(call_fn=call_fn)
        polisher.start(("room1", 0, "p_a"), persona=None, approach="charm", move_text="raw move")
        text = polisher.resolve(("room1", 0, "p_a"))
        self.assertEqual(len(text), game.MOVE_TEXT_MAX_CHARS)

    def test_prompt_never_promises_to_invent_facts(self):
        captured = {}

        def call_fn(messages):
            captured["system"] = messages[0]["content"]
            return "fine"

        polisher = MovePolisher(call_fn=call_fn)
        polisher.start(("k",), persona=None, approach="charm", move_text="raw")
        polisher.resolve(("k",))
        self.assertIn("do not invent new", captured["system"])

    def test_double_resolve_second_call_returns_none(self):
        # resolve() pops the job -- a retried reveal computation should not
        # re-wait on (and re-consume) the same background thread's result.
        polisher = MovePolisher(call_fn=lambda messages: "polished")
        polisher.start(("k",), persona=None, approach="charm", move_text="raw")
        first = polisher.resolve(("k",))
        second = polisher.resolve(("k",))
        self.assertEqual(first, "polished")
        self.assertIsNone(second)


class MovePolisherEngineIntegrationTests(unittest.TestCase):
    """End-to-end: polish -> set_flavor -> resolve() actually bakes the
    polished line into the round_record, exactly as docs/LAN_GAME_SPEC.md's
    persona/LLM rewrite integration point describes."""

    def test_set_flavor_before_resolve_changes_revealed_move_text(self):
        mgr = _manager()
        _code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=1)
        room.start(host_id, host_token)

        polisher = MovePolisher(call_fn=lambda messages: "A dazzlingly polished line!")
        key = (room.room_id, room.encounter_index, host_id)
        polisher.start(key, persona=None, approach="charm", move_text="I say something nice")
        room.submit_choice(host_id, host_token, "charm", "I say something nice")

        polished = polisher.resolve(key)
        self.assertIsNotNone(polished)
        room.set_flavor(f"move:{host_id}:{room.encounter_index}", polished)

        record = room.resolve(host_id, host_token)
        self.assertEqual(record["choices"][0]["move_text"], "A dazzlingly polished line!")
        self.assertEqual(record["choices"][0]["approach"], "charm")  # scoring input untouched

    def test_no_set_flavor_falls_back_to_original_raw_move_text(self):
        mgr = _manager()
        _code, room, host_id, host_token = mgr.create_room(host_name="Ava", seed=1)
        room.start(host_id, host_token)

        polisher = MovePolisher(call_fn=None)  # feature effectively off
        key = (room.room_id, room.encounter_index, host_id)
        polisher.start(key, persona=None, approach="charm", move_text="my original line")
        room.submit_choice(host_id, host_token, "charm", "my original line")

        polished = polisher.resolve(key)
        self.assertIsNone(polished)
        # No set_flavor call -- engine's own default must be the raw text.
        record = room.resolve(host_id, host_token)
        self.assertEqual(record["choices"][0]["move_text"], "my original line")


if __name__ == "__main__":
    unittest.main()
