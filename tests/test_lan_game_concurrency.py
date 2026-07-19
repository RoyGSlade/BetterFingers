"""Real-thread concurrency/race tests for backend.lan_playground.game (board #43).

game-audit-sonnet's board #42 handoff flagged that "concurrent joins/submits/
resolve: PASS by construction (single threading.Lock per Room guards every
mutating method) but NOT stress-tested -- only sequential-call tests exist,
no actual multi-thread race test." This module closes that gap with real
`threading.Thread` + `threading.Barrier` races (no mocked locking, no sleeps
where a barrier will do) against `Room`/`GameRegistry` directly.

Every test is deterministic and bounded: threads are lined up on a Barrier so
they all attempt the racing call at (as close to) the same instant, and every
`Thread.join()` uses a timeout with an explicit `assertFalse(t.is_alive())` --
a real deadlock fails the test in ~5s instead of hanging the suite forever.
"""

import threading
import unittest

from backend.lan_playground.game import (
    MAX_PLAYERS,
    AlreadySubmittedError,
    GameError,
    GameRegistry,
    InvalidPhaseError,
    NotAllSubmittedError,
    RoomFullError,
    Room,
)

JOIN_TIMEOUT = 5


def _new_room(seed=1, host_name="Host"):
    registry = GameRegistry()
    room, host_id, host_token = registry.create_room(host_name, seed=seed)
    return registry, room, host_id, host_token


def _start_room(n_players=MAX_PLAYERS, seed=1):
    """Create a room with n_players (host + guests) and start it."""
    _, room, host_id, host_token = _new_room(seed=seed)
    players = [(host_id, host_token)]
    for i in range(n_players - 1):
        pid, token = room.join(f"Guest{i}")
        players.append((pid, token))
    room.start(host_id, host_token)
    return room, players


def _join_all(threads, timeout=JOIN_TIMEOUT):
    for t in threads:
        t.join(timeout=timeout)


class ConcurrentJoinTests(unittest.TestCase):
    def test_concurrent_joins_never_exceed_capacity_and_ids_tokens_are_unique(self):
        room = Room("room_join_race", seed=1)
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        results = [None] * n_threads

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                pid, token = room.join(f"Player{i}")
                results[i] = ("ok", pid, token)
            except RoomFullError:
                results[i] = ("full", None, None)
            except Exception as exc:  # unexpected -- surfaced via assertion below
                results[i] = ("error", repr(exc), None)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "join() deadlocked under concurrency")

        self.assertEqual([r for r in results if r[0] == "error"], [])
        oks = [r for r in results if r[0] == "ok"]
        fulls = [r for r in results if r[0] == "full"]
        self.assertEqual(len(oks), MAX_PLAYERS)
        self.assertEqual(len(fulls), n_threads - MAX_PLAYERS)

        player_ids = [r[1] for r in oks]
        tokens = [r[2] for r in oks]
        self.assertEqual(len(set(player_ids)), MAX_PLAYERS, "duplicate player_id minted under a race")
        self.assertEqual(len(set(tokens)), MAX_PLAYERS, "duplicate token minted under a race")

        state = room.public_state()
        self.assertEqual(len(state["players"]), MAX_PLAYERS)
        self.assertEqual(sum(1 for p in state["players"] if p["active"]), MAX_PLAYERS)


class ConcurrentSubmitTests(unittest.TestCase):
    def test_concurrent_distinct_player_submits_all_recorded_no_lost_state(self):
        room, players = _start_room(n_players=MAX_PLAYERS, seed=2)
        approach_cycle = ["charm", "scheme", "bonk", "charm"]
        barrier = threading.Barrier(len(players))
        errors = []

        def worker(i):
            pid, token = players[i]
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_choice(pid, token, approach_cycle[i], f"move-{i}")
            except Exception as exc:
                errors.append((pid, repr(exc)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(players))]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "submit_choice() deadlocked under concurrency")

        self.assertEqual(errors, [])
        self.assertTrue(room.can_resolve())
        host_id, host_token = players[0]
        record = room.resolve(host_id, host_token)
        self.assertEqual(len(record["choices"]), len(players), "a concurrent submission was lost")
        recorded = {c["player_id"]: c["approach"] for c in record["choices"]}
        expected = {players[i][0]: approach_cycle[i] for i in range(len(players))}
        self.assertEqual(recorded, expected)

    def test_same_player_racing_submits_exactly_one_wins_rest_rejected(self):
        room, players = _start_room(n_players=2, seed=3)
        host_id, host_token = players[0]
        guest_id, guest_token = players[1]
        n_racers = 8
        barrier = threading.Barrier(n_racers)
        results = [None] * n_racers

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_choice(guest_id, guest_token, "charm", f"attempt-{i}")
                results[i] = "ok"
            except AlreadySubmittedError:
                results[i] = "already"
            except Exception as exc:  # unexpected -- surfaced via assertion below
                results[i] = f"error:{exc!r}"

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_racers)]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "racing submit_choice() deadlocked")

        self.assertEqual(results.count("ok"), 1, "double-submit race let more than one attempt through")
        self.assertEqual(results.count("already"), n_racers - 1)
        self.assertNotIn(None, results)

        # State wasn't corrupted by the race: room still resolves cleanly.
        room.submit_choice(host_id, host_token, "scheme", "host move")
        self.assertTrue(room.can_resolve())
        record = room.resolve(host_id, host_token)
        self.assertEqual(len(record["choices"]), 2)


class ConcurrentResolveTests(unittest.TestCase):
    def test_concurrent_resolve_calls_produce_exactly_one_round(self):
        room, players = _start_room(n_players=3, seed=4)
        encounter = room._current_encounter()
        for pid, token in players:
            # Everyone plays the weakness so the round can never end the game
            # (damage stays 0), keeping the post-race phase assertion simple.
            room.submit_choice(pid, token, encounter.weakness, "safe move")
        host_id, host_token = players[0]

        n_racers = 6
        barrier = threading.Barrier(n_racers)
        results = [None] * n_racers

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                record = room.resolve(host_id, host_token)
                results[i] = ("ok", record)
            except (InvalidPhaseError, NotAllSubmittedError) as exc:
                results[i] = ("rejected", exc)
            except Exception as exc:  # unexpected -- surfaced via assertion below
                results[i] = ("error", exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_racers)]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "racing resolve() deadlocked")

        self.assertEqual([r for r in results if r[0] == "error"], [])
        oks = [r for r in results if r[0] == "ok"]
        rejected = [r for r in results if r[0] == "rejected"]
        self.assertEqual(len(oks), 1, "concurrent resolve() calls produced more than one resolution")
        self.assertEqual(len(rejected), n_racers - 1)

        state = room.public_state()
        self.assertEqual(len(state["history"]), 1, "resolve() race left more than one history entry")
        self.assertEqual(state["phase"], "reveal")
        self.assertEqual(state["hearts"], state["max_hearts"])
        # The single successful call's return value matches the room's own record.
        self.assertEqual(oks[0][1], state["history"][0])


class PublicStateDuringMutationTests(unittest.TestCase):
    def test_public_state_reads_never_raise_or_leak_during_concurrent_mutation(self):
        # Room is left in "lobby" here (not started) -- the mutator thread
        # below drives start() itself so the reader can observe every phase
        # transition, including the pre-choosing window.
        _, room, host_id, host_token = _new_room(seed=5)
        p2, t2 = room.join("Guest2")
        p3, t3 = room.join("Guest3")
        players = [(host_id, host_token), (p2, t2), (p3, t3)]
        tokens = [token for _, token in players]
        secret_texts = [f"do-not-leak-{i}" for i in range(len(players))]

        stop_event = threading.Event()
        start_barrier = threading.Barrier(2)
        errors = []

        def reader():
            start_barrier.wait(timeout=JOIN_TIMEOUT)
            viewers = [pid for pid, _ in players] + [None]
            while not stop_event.is_set():
                for viewer_id in viewers:
                    try:
                        state = room.public_state(viewer_player_id=viewer_id)
                    except Exception as exc:  # a raise here is the bug under test
                        errors.append(f"public_state() raised: {exc!r}")
                        continue
                    blob = repr(state)
                    for token in tokens:
                        if token in blob:
                            errors.append(f"token leaked in public_state(): {token}")
                    if state["phase"] == "choosing":
                        for text in secret_texts:
                            if text in blob:
                                errors.append(f"pre-reveal move_text leaked: {text}")
                    if state["phase"] not in ("lobby", "choosing", "reveal", "finished"):
                        errors.append(f"invalid phase observed mid-mutation: {state['phase']!r}")
                    if not (0 <= state["hearts"] <= state["max_hearts"]):
                        errors.append(f"hearts out of range mid-mutation: {state['hearts']}")

        def mutator():
            start_barrier.wait(timeout=JOIN_TIMEOUT)
            room.start(host_id, host_token)
            for i, (pid, token) in enumerate(players):
                room.submit_choice(pid, token, "charm", secret_texts[i])
            room.resolve(host_id, host_token)

        reader_thread = threading.Thread(target=reader)
        mutator_thread = threading.Thread(target=mutator)
        reader_thread.start()
        mutator_thread.start()
        mutator_thread.join(timeout=JOIN_TIMEOUT)
        self.assertFalse(mutator_thread.is_alive(), "mutation path deadlocked while reader was polling")
        stop_event.set()
        reader_thread.join(timeout=JOIN_TIMEOUT)
        self.assertFalse(reader_thread.is_alive(), "reader thread never observed stop_event")

        self.assertEqual(errors, [])
        final = room.public_state()
        self.assertEqual(len(final["history"]), 1)


class HostDisconnectRaceTests(unittest.TestCase):
    def test_host_disconnect_concurrent_with_submit_promotes_without_deadlock(self):
        # Repeat the race window several times with fresh rooms -- a single
        # run could get lucky with thread scheduling and hide a real bug.
        for rep in range(10):
            _, room, host_id, host_token = _new_room(seed=100 + rep)
            p2, t2 = room.join("Guest2")
            p3, t3 = room.join("Guest3")
            room.start(host_id, host_token)
            encounter = room._current_encounter()

            barrier = threading.Barrier(3)
            errors = []

            def do_disconnect():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.disconnect(host_id, host_token)
                except Exception as exc:
                    errors.append(repr(exc))

            def do_submit(pid, token, label):
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.submit_choice(pid, token, encounter.weakness, label)
                except Exception as exc:
                    errors.append(repr(exc))

            threads = [
                threading.Thread(target=do_disconnect),
                threading.Thread(target=do_submit, args=(p2, t2, "p2 move")),
                threading.Thread(target=do_submit, args=(p3, t3, "p3 move")),
            ]
            for t in threads:
                t.start()
            _join_all(threads)
            for t in threads:
                self.assertFalse(t.is_alive(), f"host disconnect/submit race deadlocked (rep {rep})")

            self.assertEqual(errors, [], f"unexpected error in rep {rep}")
            state = room.public_state()
            # Deterministic regardless of interleaving: promotion always picks
            # the next *active* player in join order, and submit_choice never
            # touches active status, so p2 is always promoted.
            self.assertEqual(state["host_id"], p2, f"promotion picked the wrong host (rep {rep})")
            self.assertTrue(room.can_resolve(), f"submission lost in the race (rep {rep})")
            record = room.resolve(p2, t2)
            self.assertEqual(len(record["choices"]), 2)
            self.assertEqual(record["damage"], 0)

    def test_host_disconnect_racing_own_resolve_no_deadlock_and_single_resolution(self):
        for rep in range(10):
            _, room, host_id, host_token = _new_room(seed=200 + rep)
            p2, t2 = room.join("Guest2")
            room.start(host_id, host_token)
            encounter = room._current_encounter()
            room.submit_choice(host_id, host_token, encounter.weakness, "host move")
            room.submit_choice(p2, t2, encounter.weakness, "p2 move")
            self.assertTrue(room.can_resolve())

            barrier = threading.Barrier(2)
            outcome = {}

            def do_resolve():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    outcome["resolve"] = ("ok", room.resolve(host_id, host_token))
                except GameError as exc:
                    outcome["resolve"] = ("rejected", exc)

            def do_disconnect():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.disconnect(host_id, host_token)
                    outcome["disconnect"] = "ok"
                except GameError as exc:
                    outcome["disconnect"] = ("rejected", exc)

            threads = [threading.Thread(target=do_resolve), threading.Thread(target=do_disconnect)]
            for t in threads:
                t.start()
            _join_all(threads)
            for t in threads:
                self.assertFalse(t.is_alive(), f"resolve/disconnect self-race deadlocked (rep {rep})")

            # disconnect() has no phase precondition -- it always succeeds.
            self.assertEqual(outcome.get("disconnect"), "ok", f"rep {rep}")
            state = room.public_state()
            self.assertNotEqual(state["host_id"], host_id, f"host role never moved off disconnected host (rep {rep})")
            self.assertEqual(state["host_id"], p2, f"promotion picked the wrong host (rep {rep})")

            # resolve() either won the race (host authority still valid when it
            # ran) or lost it cleanly (host authority had already moved) -- in
            # both cases there is never more than one history entry.
            self.assertIn(outcome["resolve"][0], ("ok", "rejected"), f"rep {rep}")
            self.assertLessEqual(len(state["history"]), 1, f"rep {rep}")
            if outcome["resolve"][0] == "ok":
                self.assertEqual(len(state["history"]), 1, f"rep {rep}")


if __name__ == "__main__":
    unittest.main()
