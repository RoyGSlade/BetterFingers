"""In-memory draft queue plus its durable persistence (JSON snapshot + SQLite
mirror via history_store), extracted out of server.py (A1.5).

server.py still owns everything about *what happens* to a draft (routes,
sending, rewriting, TTS, wipe orchestration); this module owns only *where
drafts live* and *how they get there durably*: the queue/lock/id-counter, the
coalesced revision-guarded writer, startup load, and crash-recovery
reclassification of interrupted sends.

Paths and the process-lifetime send token are injected rather than read from
globals, and callbacks that reach back into server.py behavior (persisting via
whatever `save_draft_history` currently resolves to, computing review-gate
fields) are passed in per call so patched test doubles in server.py keep
working unchanged.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone


class DraftStore:
    def __init__(self, data_dir_fn, history_store, send_process_token, max_history=100):
        # data_dir_fn is called fresh on every use (not resolved once here) so
        # that patching the underlying path resolver in the owning module
        # keeps working the same way it did before extraction.
        self._data_dir_fn = data_dir_fn
        self._history_store = history_store
        self.send_process_token = send_process_token
        self.max_history = max_history

        self.draft_queue = []
        self.draft_recordings = {}
        self.next_draft_id = 1
        self.lock = threading.RLock()

        # Draft-history persistence writer state. Every mutation calls
        # save_history (outside self.lock). Two problems the naive "snapshot +
        # os.replace" had:
        #   1. Lost updates: two concurrent savers each os.replace their own
        #      snapshot; if the older snapshot lands last, the JSON on disk
        #      regresses to a stale state (memory + SQLite mirror stay
        #      correct, so it only bites after a restart).
        #   2. Redundant IO: a burst of mutations each does a full disk+SQLite
        #      write.
        # Fix: a monotonic request revision tags each save; a single-writer
        # lock serializes the actual write; a saver whose revision is already
        # covered by a newer flush skips entirely (coalescing).
        # _written_rev is only ever set to a revision the on-disk state is
        # guaranteed to be at least as new as, so skips never drop an update
        # -- at worst an extra (correct) write happens.
        self._persist_lock = threading.Lock()   # guards the counters + pending mirror set
        self._write_lock = threading.Lock()      # serializes the write-to-disk step
        self._request_rev = 0                     # bumped once per save_history call
        self._written_rev = 0                     # highest revision flushed to disk
        self._pending_full_mirror = False          # a full-queue mirror was requested
        self._pending_changed_ids = set()          # narrowed mirror ids awaiting a flush

    def _history_file(self):
        return os.path.join(self._data_dir_fn(), "draft_history.json")

    def save_history(self, changed_draft_id=None):
        """Persist the draft queue durably, ordered, and coalesced.

        Every mutation calls this (outside self.lock). A monotonic revision
        tags the request; a single-writer lock serializes the actual write;
        whoever writes always snapshots the *latest* queue and stamps
        _written_rev, so a concurrent saver whose revision is already covered
        skips (coalescing) and a stale snapshot can never regress the file
        (ordering). changed_draft_id narrows the searchable-archive mirror to
        the drafts that actually changed; coalesced requests accumulate their
        ids so a single flush mirrors them all. The JSON snapshot is still
        written in full (bounded at max_history) and atomically (temp +
        os.replace) so a crash mid-write cannot corrupt it.
        """
        # 1) Register intent: claim a revision and record what the mirror owes.
        with self._persist_lock:
            self._request_rev += 1
            my_rev = self._request_rev
            if changed_draft_id is None:
                self._pending_full_mirror = True
            else:
                self._pending_changed_ids.add(changed_draft_id)

        # 2) Serialize writers. If a newer-or-equal flush already ran while we
        #    waited for the lock, our state is already on disk -- coalesce away.
        with self._write_lock:
            with self._persist_lock:
                if self._written_rev >= my_rev:
                    return
                # Claim everything pending up to now; the snapshot below covers it.
                claimed_rev = self._request_rev
                mirror_full = self._pending_full_mirror
                mirror_ids = None if mirror_full else set(self._pending_changed_ids)
                self._pending_full_mirror = False
                self._pending_changed_ids.clear()

            history_file = self._history_file()
            try:
                with self.lock:
                    serializable_drafts = [dict(draft) for draft in self.draft_queue]
                tmp_file = history_file + ".tmp"
                with open(tmp_file, "w", encoding="utf-8") as f:
                    json.dump(serializable_drafts, f, indent=2)
                os.replace(tmp_file, history_file)
                # Mark persisted only after the file is in place. claimed_rev is
                # a lower bound on how new the snapshot is, so skips stay safe.
                with self._persist_lock:
                    if claimed_rev > self._written_rev:
                        self._written_rev = claimed_rev
                # Mirror into the searchable, uncapped archive (C8). Defensive:
                # never fatal. On failure the ids are re-queued so the next
                # flush retries.
                if mirror_full:
                    self._history_store.upsert_many(serializable_drafts)
                elif mirror_ids:
                    changed = [d for d in serializable_drafts if d.get("id") in mirror_ids]
                    self._history_store.upsert_many(changed)
            except Exception as exc:
                logging.exception(f"Failed to save draft history to {history_file}: {exc}")
                # Re-arm the mirror debt so a subsequent save reattempts it.
                with self._persist_lock:
                    if mirror_full:
                        self._pending_full_mirror = True
                    elif mirror_ids:
                        self._pending_changed_ids.update(mirror_ids)

    def _load_history_json(self, history_file):
        """Read draft_history.json into a list of draft dicts. Never raises."""
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and "id" in d]
        except Exception as exc:
            logging.exception(f"Failed to load draft history from {history_file}: {exc}")
        return []

    def load_history(self, max_history=None):
        """Populate the working draft queue at startup, SQLite-first.

        history_store (SQLite) holds complete draft records and is the
        canonical store; draft_history.json is consulted only as a fallback
        when the database is empty or unrecoverable. When that fallback is
        used, the JSON is imported into SQLite once and renamed to a
        migration backup so it is never read as an authority again -- no
        parallel canonical store.
        """
        limit = max_history if max_history is not None else self.max_history
        history_file = self._history_file()

        records = []
        try:
            self._history_store.init()
            if self._history_store.verify_schema().get("ok"):
                records = self._history_store.load_recent_full(limit=limit)
        except Exception as exc:
            logging.warning(f"history_store unavailable at startup, falling back to JSON: {exc}")
            records = []

        if not records and os.path.exists(history_file):
            records = self._load_history_json(history_file)
            try:
                self._history_store.migrate_from_json(history_file)
                os.replace(history_file, history_file + ".migrated")
            except Exception as exc:
                logging.warning(f"JSON->SQLite migration/backup failed: {exc}")

        with self.lock:
            self.draft_queue.clear()
            max_id = 0
            for d in records:
                if isinstance(d, dict) and "id" in d:
                    self.draft_queue.append(d)
                    if d["id"] > max_id:
                        max_id = d["id"]
            self.next_draft_id = max_id + 1
        logging.info(f"Loaded {len(self.draft_queue)} drafts from history, next draft ID is {self.next_draft_id}")

    def recover_interrupted_sends(self, save_fn):
        """Reconcile drafts a previous process left mid-send.

        A draft persisted as "sending" whose ``send_process_token`` is not
        this process's token was interrupted by a crash while injecting.
        Injection is not idempotent (re-sending re-types the text), and the
        text may or may not have already landed, so such a draft must NOT be
        auto-resent and must NOT be quietly reverted to a resendable state as
        if the send never happened -- either could double-paste or hide that
        content may already be out. It is moved to the honest terminal state
        "send_interrupted" (outcome unknown); the user explicitly decides
        whether to resend.

        Idempotent and safe to call at startup after load_history(). Returns
        the list of recovered draft ids. save_fn is called (with no args) to
        persist the reclassification if anything changed -- injected so
        callers keep control of exactly how/when persistence happens.
        """
        recovered = []
        with self.lock:
            for draft in self.draft_queue:
                if draft.get("status") == "sending" \
                        and draft.get("send_process_token") != self.send_process_token:
                    draft["status"] = "send_interrupted"
                    draft["send_outcome"] = "interrupted"
                    draft["pending_send"] = False
                    draft.pop("send_process_token", None)
                    recovered.append(draft["id"])
        if recovered:
            logging.warning(
                "Recovered %d draft(s) interrupted mid-send (injection outcome "
                "unknown, marked send_interrupted): %s", len(recovered), recovered)
            # One full save (bounded at max_history) mirrors every reclassified
            # row rather than N narrowed writes.
            save_fn()
        return recovered

    def create_draft(self, raw_text, final_text, preset="True Janitor", status="pending",
                      metadata=None, error="", gate_reasons=None, recording_result=None,
                      confidence=None, review_fields_fn=None,
                      save_fn=None, max_history=None,
                      transcription_result=None, speech_signals=None):
        """transcription_result/speech_signals are additive, optional, already-
        serialized (plain dict, e.g. via backend.domain.contracts.to_dict) data
        from I3.1's structured-transcription/speech-signal pipeline stages.
        Default None so callers that never compute them (and old drafts loaded
        from disk, which won't even have these keys) are unaffected."""
        limit = max_history if max_history is not None else self.max_history
        with self.lock:
            draft = {
                "id": self.next_draft_id,
                "raw_text": raw_text or "",
                "final_text": final_text or "",
                "preset": preset,
                "status": status or "pending",
                "metadata": metadata or {},
                "error": error or "",
                "gate_reasons": list(gate_reasons or []),
                "confidence": confidence or {"score": None, "avg_logprob": None, "no_speech_prob": None},
                "transcription_result": transcription_result,
                "speech_signals": speech_signals,
                "pending_send": False,
                "send_result": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if review_fields_fn is not None:
                review_fields_fn(draft)
            self.next_draft_id += 1
            self.draft_queue.append(draft)
            if recording_result is not None:
                self.draft_recordings[draft["id"]] = recording_result

            if len(self.draft_queue) > limit:
                removed = self.draft_queue[: len(self.draft_queue) - limit]
                del self.draft_queue[: len(self.draft_queue) - limit]
                for removed_draft in removed:
                    self.draft_recordings.pop(removed_draft["id"], None)

            response = dict(draft)
            new_id = draft["id"]

        # Persist outside the lock (§9): serializing + JSON + SQLite while
        # holding the reentrant draft lock made every create stall concurrent
        # draft reads.
        if save_fn is not None:
            save_fn(changed_draft_id=new_id)
        return response

    def get_draft_by_id(self, draft_id):
        with self.lock:
            for draft in self.draft_queue:
                if draft["id"] == draft_id:
                    return draft
        return None
