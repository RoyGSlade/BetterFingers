"""Real-thread concurrency/race tests for backend.lan_playground.game (board task #2).

Closes the same gap the old suite closed for the Charm/Scheme/Bonk engine:
sequential-call tests alone don't prove thread safety under real races.
Every test here uses real `threading.Thread` + `threading.Barrier` races
(no mocked locking, no sleeps where a barrier will do) against `Room`/
`GameRegistry` directly, exercising the Lost Meaning phase machine (lobby ->
spotlight_action -> ally_support -> spotlight_draft -> ally_reaction ->
reveal -> finished).

Every test is deterministic and bounded: threads line up on a Barrier so
they all attempt the racing call at (as close to) the same instant, and
every `Thread.join()` uses a timeout with an explicit `assertFalse(t.is_alive())`
-- a real deadlock fails the test in ~5s instead of hanging the suite.
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


def _spotlight_move_and_target(room):
    state = room.public_state()
    hero = next(h for h in state["heroes"] if h["hero_id"] == state["spotlight_hero_id"])
    return hero["deck"][0]["id"], state["encounter"]["targets"][0]


def _declare_spotlight_action(room, host_id, host_token, desired_outcome="handle it"):
    move_id, target_id = _spotlight_move_and_target(room)
    room.submit_spotlight_action(host_id, host_token, move_id, target_id, desired_outcome)


def _fill_support(room, allies, detail="backing them up"):
    for pid, token in allies:
        room.submit_support(pid, token, "assist", detail)


def _complete_draft(room, host_id, host_token, text="we handle it"):
    room.submit_rough_text(host_id, host_token, text)
    room.submit_variants(host_id, host_token, [text, text, text])
    room.approve_message(host_id, host_token, text, "resolve it")


def _fill_reactions(room, allies, detail="helping out"):
    for pid, token in allies:
        room.submit_reaction(pid, token, "assist", detail)


def _to_ally_reaction(room, players, host_id, host_token):
    allies = [p for p in players if p[0] != host_id]
    _declare_spotlight_action(room, host_id, host_token)
    _fill_support(room, allies)
    room.open_draft(host_id, host_token)
    _complete_draft(room, host_id, host_token)


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
        # Every joined player bound a distinct hero slot.
        hero_ids = {p["hero_id"] for p in state["players"]}
        self.assertEqual(len(hero_ids), MAX_PLAYERS)


class ConcurrentSupportTests(unittest.TestCase):
    def test_concurrent_distinct_ally_support_all_recorded_no_lost_state(self):
        room, players = _start_room(n_players=MAX_PLAYERS, seed=2)
        host_id, host_token = players[0]
        _declare_spotlight_action(room, host_id, host_token)
        allies = players[1:]
        barrier = threading.Barrier(len(allies))
        errors = []

        def worker(i):
            pid, token = allies[i]
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_support(pid, token, "assist", f"support-{i}")
            except Exception as exc:
                errors.append((pid, repr(exc)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(allies))]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "submit_support() deadlocked under concurrency")

        self.assertEqual(errors, [])
        self.assertTrue(room.can_open_draft())
        room.open_draft(host_id, host_token)
        self.assertEqual(room.phase, "spotlight_draft")

    def test_same_ally_racing_support_exactly_one_wins_rest_rejected(self):
        room, players = _start_room(n_players=2, seed=3)
        host_id, host_token = players[0]
        guest_id, guest_token = players[1]
        _declare_spotlight_action(room, host_id, host_token)
        n_racers = 8
        barrier = threading.Barrier(n_racers)
        results = [None] * n_racers

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_support(guest_id, guest_token, "assist", f"attempt-{i}")
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
            self.assertFalse(t.is_alive(), "racing submit_support() deadlocked")

        self.assertEqual(results.count("ok"), 1, "double-submit race let more than one attempt through")
        self.assertEqual(results.count("already"), n_racers - 1)
        self.assertNotIn(None, results)

        # State wasn't corrupted by the race: room still opens the draft cleanly.
        self.assertTrue(room.can_open_draft())
        room.open_draft(host_id, host_token)
        self.assertEqual(room.phase, "spotlight_draft")


class ConcurrentOpenDraftTests(unittest.TestCase):
    def test_concurrent_open_draft_calls_produce_exactly_one_transition(self):
        room, players = _start_room(n_players=2, seed=4)
        host_id, host_token = players[0]
        guest_id, guest_token = players[1]
        _declare_spotlight_action(room, host_id, host_token)
        room.submit_support(guest_id, guest_token, "assist", "")
        self.assertTrue(room.can_open_draft())

        n_racers = 6
        barrier = threading.Barrier(n_racers)
        results = [None] * n_racers

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.open_draft(host_id, host_token)
                results[i] = "ok"
            except InvalidPhaseError:
                results[i] = "rejected"
            except Exception as exc:  # unexpected -- surfaced via assertion below
                results[i] = ("error", exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_racers)]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "racing open_draft() deadlocked")

        self.assertEqual([r for r in results if isinstance(r, tuple)], [])
        self.assertEqual(results.count("ok"), 1, "concurrent open_draft() calls produced more than one transition")
        self.assertEqual(results.count("rejected"), n_racers - 1)
        self.assertEqual(room.phase, "spotlight_draft")


class ConcurrentReactionTests(unittest.TestCase):
    def test_concurrent_distinct_ally_reactions_all_recorded(self):
        room, players = _start_room(n_players=MAX_PLAYERS, seed=6)
        host_id, host_token = players[0]
        allies = players[1:]
        _declare_spotlight_action(room, host_id, host_token)
        _fill_support(room, allies)
        room.open_draft(host_id, host_token)
        _complete_draft(room, host_id, host_token)
        self.assertEqual(room.phase, "ally_reaction")

        barrier = threading.Barrier(len(allies))
        errors = []

        def worker(i):
            pid, token = allies[i]
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_reaction(pid, token, "assist", f"reaction-{i}")
            except Exception as exc:
                errors.append((pid, repr(exc)))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(allies))]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "submit_reaction() deadlocked under concurrency")

        self.assertEqual(errors, [])
        self.assertTrue(room.can_resolve())
        record = room.resolve(host_id, host_token)
        self.assertEqual(len(record["reactions"]), len(allies))

    def test_same_ally_racing_reaction_exactly_one_wins(self):
        room, players = _start_room(n_players=2, seed=7)
        host_id, host_token = players[0]
        guest_id, guest_token = players[1]
        _to_ally_reaction(room, players, host_id, host_token)
        self.assertEqual(room.phase, "ally_reaction")

        n_racers = 8
        barrier = threading.Barrier(n_racers)
        results = [None] * n_racers

        def worker(i):
            barrier.wait(timeout=JOIN_TIMEOUT)
            try:
                room.submit_reaction(guest_id, guest_token, "assist", f"attempt-{i}")
                results[i] = "ok"
            except AlreadySubmittedError:
                results[i] = "already"
            except Exception as exc:
                results[i] = f"error:{exc!r}"

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_racers)]
        for t in threads:
            t.start()
        _join_all(threads)
        for t in threads:
            self.assertFalse(t.is_alive(), "racing submit_reaction() deadlocked")

        self.assertEqual(results.count("ok"), 1)
        self.assertEqual(results.count("already"), n_racers - 1)
        self.assertTrue(room.can_resolve())


class ConcurrentResolveTests(unittest.TestCase):
    def test_concurrent_resolve_calls_produce_exactly_one_round(self):
        room, players = _start_room(n_players=3, seed=8)
        host_id, host_token = players[0]
        allies = players[1:]
        _declare_spotlight_action(room, host_id, host_token)
        _fill_support(room, allies)
        room.open_draft(host_id, host_token)
        _complete_draft(room, host_id, host_token)
        _fill_reactions(room, allies)
        self.assertTrue(room.can_resolve())

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
        self.assertEqual(oks[0][1], state["history"][0])


class PublicStateDuringMutationTests(unittest.TestCase):
    def test_public_state_reads_never_raise_or_leak_during_concurrent_mutation(self):
        _, room, host_id, host_token = _new_room(seed=9)
        p2, t2 = room.join("Guest2")
        p3, t3 = room.join("Guest3")
        players = [(host_id, host_token), (p2, t2), (p3, t3)]
        tokens = [token for _, token in players]
        secret_support_detail = "do-not-leak-support-detail"
        secret_reaction_detail = "do-not-leak-reaction-detail"
        valid_phases = {
            "lobby",
            "spotlight_action",
            "ally_support",
            "spotlight_draft",
            "ally_reaction",
            "reveal",
            "finished",
        }

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
                    if state["phase"] not in valid_phases:
                        errors.append(f"invalid phase observed mid-mutation: {state['phase']!r}")
                    if not (0 <= state["hearts"] <= state["max_hearts"]):
                        errors.append(f"hearts out of range mid-mutation: {state['hearts']}")
                    if state["phase"] in ("ally_support", "ally_reaction"):
                        if secret_support_detail in blob or secret_reaction_detail in blob:
                            errors.append(f"pre-reveal support/reaction content leaked in phase {state['phase']!r}")

        def mutator():
            start_barrier.wait(timeout=JOIN_TIMEOUT)
            room.start(host_id, host_token)
            _declare_spotlight_action(room, host_id, host_token)
            room.submit_support(p2, t2, "clue", secret_support_detail)
            room.submit_support(p3, t3, "assist", "")
            room.open_draft(host_id, host_token)
            _complete_draft(room, host_id, host_token)
            room.submit_reaction(p2, t2, "challenge", secret_reaction_detail)
            room.submit_reaction(p3, t3, "assist", "")
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
        # Both secrets are legitimately visible now that the round resolved.
        record_blob = repr(final["history"][0])
        self.assertIn(secret_support_detail, record_blob)
        self.assertIn(secret_reaction_detail, record_blob)


class HostDisconnectRaceTests(unittest.TestCase):
    def test_host_disconnect_concurrent_with_support_promotes_without_deadlock(self):
        # Repeat the race window several times with fresh rooms -- a single
        # run could get lucky with thread scheduling and hide a real bug.
        for rep in range(10):
            _, room, host_id, host_token = _new_room(seed=100 + rep)
            p2, t2 = room.join("Guest2")
            p3, t3 = room.join("Guest3")
            room.start(host_id, host_token)
            _declare_spotlight_action(room, host_id, host_token)  # host is round-0 spotlight

            barrier = threading.Barrier(3)
            errors = []

            def do_disconnect():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.disconnect(host_id, host_token)
                except Exception as exc:
                    errors.append(repr(exc))

            def do_support(pid, token, label):
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.submit_support(pid, token, "assist", label)
                except Exception as exc:
                    errors.append(repr(exc))

            threads = [
                threading.Thread(target=do_disconnect),
                threading.Thread(target=do_support, args=(p2, t2, "p2 support")),
                threading.Thread(target=do_support, args=(p3, t3, "p3 support")),
            ]
            for t in threads:
                t.start()
            _join_all(threads)
            for t in threads:
                self.assertFalse(t.is_alive(), f"host disconnect/support race deadlocked (rep {rep})")

            self.assertEqual(errors, [], f"unexpected error in rep {rep}")
            state = room.public_state()
            # Deterministic regardless of interleaving: promotion always picks
            # the next *active* player in join order, and submit_support
            # never touches active status, so p2 is always promoted.
            self.assertEqual(state["host_id"], p2, f"promotion picked the wrong host (rep {rep})")
            self.assertTrue(room.can_open_draft(), f"support lost in the race (rep {rep})")

    def test_host_disconnect_racing_own_open_draft_no_deadlock_and_single_transition(self):
        for rep in range(10):
            _, room, host_id, host_token = _new_room(seed=200 + rep)
            p2, t2 = room.join("Guest2")
            room.start(host_id, host_token)
            _declare_spotlight_action(room, host_id, host_token)
            room.submit_support(p2, t2, "assist", "")
            self.assertTrue(room.can_open_draft())

            barrier = threading.Barrier(2)
            outcome = {}

            def do_open_draft():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.open_draft(host_id, host_token)
                    outcome["open_draft"] = "ok"
                except GameError as exc:
                    outcome["open_draft"] = ("rejected", exc)

            def do_disconnect():
                barrier.wait(timeout=JOIN_TIMEOUT)
                try:
                    room.disconnect(host_id, host_token)
                    outcome["disconnect"] = "ok"
                except GameError as exc:
                    outcome["disconnect"] = ("rejected", exc)

            threads = [threading.Thread(target=do_open_draft), threading.Thread(target=do_disconnect)]
            for t in threads:
                t.start()
            _join_all(threads)
            for t in threads:
                self.assertFalse(t.is_alive(), f"open_draft/disconnect self-race deadlocked (rep {rep})")

            # disconnect() has no phase precondition -- it always succeeds.
            self.assertEqual(outcome.get("disconnect"), "ok", f"rep {rep}")
            state = room.public_state()
            self.assertNotEqual(state["host_id"], host_id, f"host role never moved off disconnected host (rep {rep})")
            self.assertEqual(state["host_id"], p2, f"promotion picked the wrong host (rep {rep})")

            # open_draft() either won the race (host authority still valid
            # when it ran) or lost it cleanly (host authority had already
            # moved, raising NotHostError) -- in both cases phase never ends
            # up somewhere invalid.
            self.assertIn(outcome["open_draft"][0] if isinstance(outcome["open_draft"], tuple) else outcome["open_draft"], ("ok", "rejected"), f"rep {rep}")
            self.assertIn(state["phase"], ("ally_support", "spotlight_draft"), f"rep {rep}")


if __name__ == "__main__":
    unittest.main()
