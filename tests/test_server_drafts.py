import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from backend.domain.contracts import TimedSegment, TranscriptionResult


class DummyTranscriber:
    def __init__(self, preload=False, profile_name=None, *args, **kwargs):
        self.preload = preload
        self.calls = []

    def transcribe(self, audio_data):
        self.calls.append(audio_data)
        return "raw transcript"


class EmptyTranscriber(DummyTranscriber):
    def transcribe(self, audio_data):
        self.calls.append(audio_data)
        return ""


class FakeStructuredTranscriber(DummyTranscriber):
    """Exposes I3.1's combined transcribe_with_structured() API (single decode:
    raw text, legacy confidence dict, structured TranscriptionResult)."""

    def transcribe_with_structured(self, audio_data, hotwords=None):
        self.calls.append(audio_data)
        segments = [TimedSegment(start_s=0.0, end_s=1.0, text="raw transcript", avg_logprob=-0.1, no_speech_prob=0.01)]
        confidence = {"score": 0.93, "avg_logprob": -0.1, "no_speech_prob": 0.01}
        result = TranscriptionResult(text="raw transcript", segments=segments, confidence=0.93, audio_duration_s=1.0)
        return "raw transcript", confidence, result


class EmptyStructuredTranscriber(EmptyTranscriber):
    """Same combined API, but for the no-usable-audio case (empty text/segments)."""

    def transcribe_with_structured(self, audio_data, hotwords=None):
        self.calls.append(audio_data)
        confidence = {"score": None, "avg_logprob": None, "no_speech_prob": None}
        result = TranscriptionResult(text="", segments=[], confidence=None, audio_duration_s=0.1)
        return "", confidence, result


class DummyEngine:
    def process_fast_lane(self, text, preset, max_output_tokens=None, chunk_size=None, progress_callback=None, stitch_pass=False):
        return f"{preset}: {text}"


class ProgressReportingEngine:
    """Simulates the engine's chunk-progress callbacks for long recordings."""

    def process_fast_lane(self, text, preset, max_output_tokens=None, chunk_size=None, progress_callback=None, stitch_pass=False):
        if progress_callback:
            progress_callback({"status": "chunking_started", "chunk_count": 3})
            for i in range(1, 4):
                progress_callback({"status": "chunking_progress", "chunk_index": i, "chunk_count": 3})
            if stitch_pass:
                progress_callback({"status": "chunking_stitching", "chunk_count": 3})
        return f"{preset}: cleaned"


class LongTranscriber(DummyTranscriber):
    def transcribe(self, audio_data):
        self.calls.append(audio_data)
        return " ".join(["word"] * 60)


class DummyRewriteEngine:
    def rewrite_text(self, text, action="clearer", custom_instruction="", max_output_tokens=None, chunk_size=None):
        suffix = f" {custom_instruction}" if custom_instruction else ""
        return f"{action}: {text}{suffix}"


class DummyTTSEngine:
    def __init__(self):
        self.calls = []

    def speak(self, text, speed=1.0, voice_hint="english", blend=None, modulation=None):
        self.calls.append({
            "text": text, "speed": speed, "voice_hint": voice_hint,
            "blend": blend, "modulation": modulation,
        })
        return {"ok": True, "backend": "kokoro_onnx", "fallback": False, "message": "queued"}


class DummyRecordingResult:
    audio_data = [0.1, 0.2, 0.3]
    sample_rate = 16000
    duration_seconds = 1.0
    frame_count = 3
    sample_count = 3
    max_amplitude = 0.2
    rms_amplitude = 0.05
    stop_reason = "manual"


class SilentRecordingResult:
    audio_data = []
    sample_rate = 16000
    duration_seconds = 0.1
    frame_count = 0
    sample_count = 0
    max_amplitude = 0.0
    rms_amplitude = 0.0
    stop_reason = "manual"


class ImmediateThread:
    def __init__(self, target, daemon=False, name=None):
        self.target = target
        self.daemon = daemon
        self.name = name

    def start(self):
        self.target()


class DummyOutputInjector:
    def __init__(self):
        self.stopped = False
        self.released = False

    def stop_typing(self):
        self.stopped = True

    def release_mute_key(self):
        self.released = True


class FailingSendInjector:
    def reload_config(self, profile_name="Default"):
        self.profile_name = profile_name

    def open_chat(self):
        self.opened_chat = True

    def send_output(self, text, auto_submit=False, close_action="none"):
        raise RuntimeError("paste exploded")


class DummyRecordingManager:
    def __init__(self):
        self.stop_reason = None

    def request_stop(self, reason="manual"):
        self.stop_reason = reason


class ServerDraftTests(unittest.TestCase):
    def setUp(self):
        self._load_draft_patcher = patch("server.load_draft_history")
        self._load_draft_patcher.start()
        self._save_draft_patcher = patch("server.save_draft_history")
        self._save_draft_patcher.start()
        self._transcriber = server.transcriber
        self._output_injector = server.output_injector
        self._hotkey_manager = server.hotkey_manager
        self._tts_engine = server.tts_engine
        server.transcriber = None
        server.output_injector = None
        server.hotkey_manager = None
        server.tts_engine = None
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def tearDown(self):
        self._load_draft_patcher.stop()
        self._save_draft_patcher.stop()
        server.transcriber = self._transcriber
        server.output_injector = self._output_injector
        server.hotkey_manager = self._hotkey_manager
        server.tts_engine = self._tts_engine
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def test_create_draft_assigns_id_and_caps_history(self):
        first = server.create_draft("raw", "final")

        self.assertEqual(first["id"], 1)
        self.assertEqual(first["raw_text"], "raw")
        self.assertEqual(first["final_text"], "final")
        self.assertEqual(first["preset"], "True Janitor")
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["metadata"], {})
        self.assertEqual(first["error"], "")
        self.assertEqual(first["gate_reasons"], [])
        self.assertEqual(first["token_count"], 1)
        self.assertGreater(first["token_limit"], 0)
        self.assertFalse(first["long_text"])

        original_max = server.MAX_DRAFT_HISTORY
        server.MAX_DRAFT_HISTORY = 25
        try:
            for index in range(25):
                server.create_draft(f"raw {index}", f"final {index}")

            self.assertEqual(len(server.draft_queue), server.MAX_DRAFT_HISTORY)
            self.assertEqual(server.draft_queue[0]["id"], 2)
        finally:
            server.MAX_DRAFT_HISTORY = original_max

    def test_draft_endpoints_list_latest_accept_and_decline(self):
        draft = server.create_draft("raw", "final")

        with TestClient(server.app) as client:
            drafts = client.get("/drafts")
            self.assertEqual(drafts.status_code, 200)
            self.assertEqual(drafts.json()["drafts"][0]["id"], draft["id"])

            latest = client.get("/drafts/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertEqual(latest.json()["draft"]["final_text"], "final")

            accepted = client.post(f"/drafts/{draft['id']}/accept")
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.json()["status"], "accepted")
            self.assertTrue(accepted.json()["pending_send"])
            self.assertEqual(server.pending_manual_send_ids, [draft["id"]])

            declined = client.post(f"/drafts/{draft['id']}/decline")
            self.assertEqual(declined.status_code, 200)
            self.assertEqual(declined.json()["status"], "declined")
            self.assertFalse(declined.json()["pending_send"])
            self.assertEqual(server.pending_manual_send_ids, [])

            missing = client.post("/drafts/999/accept")
            self.assertEqual(missing.status_code, 404)

    def test_latest_draft_returns_null_when_empty(self):
        with TestClient(server.app) as client:
            latest = client.get("/drafts/latest")
            self.assertEqual(latest.status_code, 200)
            self.assertIsNone(latest.json()["draft"])

    def test_process_recording_result_creates_draft_and_broadcasts_preview(self):
        statuses = []

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertEqual(draft["final_text"], "True Janitor: raw transcript")
        self.assertEqual(draft["status"], "pending")
        self.assertEqual([status for status, _data in statuses], ["transcribing", "rewriting", "preview_ready", "idle"])
        self.assertEqual(statuses[2][1]["draft_id"], draft["id"])
        self.assertEqual(statuses[2][1]["raw_text"], "raw transcript")
        self.assertEqual(statuses[2][1]["final_text"], "True Janitor: raw transcript")
        self.assertEqual(draft["metadata"]["sample_rate"], 16000)
        self.assertEqual(draft["metadata"]["stop_reason"], "manual")

    def test_process_recording_result_persists_structured_transcription_and_speech_signals(self):
        """I3.1: a transcriber exposing transcribe_with_structured() gets its
        structured result + computed speech signals attached to the finalized
        draft, with the legacy raw/final text and confidence-driven send-policy
        fields completely unaffected."""
        with patch.object(server, "Transcriber", FakeStructuredTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertEqual(draft["final_text"], "True Janitor: raw transcript")
        self.assertEqual(draft["confidence"]["score"], 0.93)
        self.assertIn("auto_send_ok", draft)

        tr = draft["transcription_result"]
        self.assertIsNotNone(tr)
        self.assertEqual(set(tr.keys()), {"text", "segments", "confidence", "audio_duration_s"})
        self.assertEqual(tr["text"], "raw transcript")
        self.assertEqual(tr["segments"][0]["text"], "raw transcript")

        signals = draft["speech_signals"]
        self.assertIsNotNone(signals)
        self.assertIn("words_per_minute", signals)
        self.assertIn("evidence", signals)
        # SpeechSignals evidence is counts/metrics only, never raw dictated text.
        self.assertNotIn("raw transcript", " ".join(signals["evidence"]))

    def test_process_recording_result_without_structured_api_leaves_new_fields_none(self):
        """A transcriber exposing only the legacy tuple API (no
        transcribe_with_structured) behaves exactly as before I3.1."""
        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertIsNone(draft["transcription_result"])
        self.assertIsNone(draft["speech_signals"])

    def test_blocked_no_audio_draft_also_carries_structured_data_when_available(self):
        with patch.object(server, "Transcriber", EmptyStructuredTranscriber), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not run for blocked audio")
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(SilentRecordingResult())

        self.assertEqual(draft["status"], "blocked")
        self.assertIsNotNone(draft["transcription_result"])
        self.assertEqual(draft["transcription_result"]["segments"], [])
        self.assertIsNotNone(draft["speech_signals"])
        self.assertEqual(draft["speech_signals"]["evidence"], ["no speech segments provided"])

    def test_cancellation_does_not_persist_structured_data(self):
        class CancellingStructuredTranscriber(FakeStructuredTranscriber):
            def transcribe_with_structured(self, audio_data, hotwords=None):
                server.cancellation_event.set()
                return super().transcribe_with_structured(audio_data, hotwords=hotwords)

        with patch.object(server, "Transcriber", CancellingStructuredTranscriber), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not run when cancelled")
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "error")
        self.assertIn("Operation cancelled by user", draft["error"])
        self.assertIsNone(draft["transcription_result"])
        self.assertIsNone(draft["speech_signals"])

    def test_llm_failure_does_not_persist_structured_data(self):
        with patch.object(server, "Transcriber", FakeStructuredTranscriber), patch.object(
            server, "get_engine", side_effect=RuntimeError("llm offline")
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "error")
        self.assertIsNone(draft["transcription_result"])
        self.assertIsNone(draft["speech_signals"])

    def test_speech_signal_computation_failure_never_breaks_pipeline(self):
        """If compute_speech_signals somehow raises, the dictation pipeline must
        still complete normally — signals simply stay absent (I3.1 is additive
        and must never be able to break the hot path)."""
        with patch.object(server, "Transcriber", FakeStructuredTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "compute_speech_signals", side_effect=RuntimeError("boom")), patch.object(
            server, "broadcast_status_threadsafe"
        ):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "pending")
        self.assertEqual(draft["final_text"], "True Janitor: raw transcript")
        self.assertIsNotNone(draft["transcription_result"])
        self.assertIsNone(draft["speech_signals"])

    def test_long_recording_emits_progress_statuses(self):
        import os
        import tempfile
        import utils

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))

        profile = utils._profile_defaults()
        profile["llm_chunk_size"] = 50  # 60-word transcript will chunk
        utils.save_profile("LongTest", profile)
        utils.set_last_active_profile("LongTest")

        statuses = []
        with patch.object(server, "Transcriber", LongTranscriber), patch.object(
            server, "get_engine", return_value=ProgressReportingEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(DummyRecordingResult())

        names = [s for s, _ in statuses]
        self.assertIn("long_recording_detected", names)
        self.assertIn("chunking_started", names)
        self.assertIn("chunking_progress", names)
        # Stitch pass is enabled by default, so the engine also reports stitching.
        self.assertIn("chunking_stitching", names)
        # long_recording_detected carries word count + chunk size.
        lrd = next(d for s, d in statuses if s == "long_recording_detected")
        self.assertEqual(lrd["chunk_size"], 50)
        self.assertGreater(lrd["word_count"], 50)
        # chunking_progress carries chunk index/count.
        prog = [d for s, d in statuses if s == "chunking_progress"]
        self.assertEqual(prog[0]["chunk_index"], 1)
        self.assertEqual(prog[0]["chunk_count"], 3)
        # Detection precedes the first chunk-progress update; still ends ready.
        self.assertLess(names.index("long_recording_detected"), names.index("chunking_progress"))
        self.assertEqual(draft["status"], "pending")

    def test_stitch_pass_disabled_skips_stitching(self):
        import os
        import tempfile
        import utils

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))

        profile = utils._profile_defaults()
        profile["llm_chunk_size"] = 50
        profile["long_recording_stitch_pass_enabled"] = False
        utils.save_profile("NoStitch", profile)
        utils.set_last_active_profile("NoStitch")

        statuses = []
        with patch.object(server, "Transcriber", LongTranscriber), patch.object(
            server, "get_engine", return_value=ProgressReportingEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            server.process_recording_result(DummyRecordingResult())

        names = [s for s, _ in statuses]
        self.assertIn("chunking_progress", names)
        self.assertNotIn("chunking_stitching", names)

    def test_short_recording_does_not_emit_long_recording_status(self):
        statuses = []
        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            server.process_recording_result(DummyRecordingResult())

        names = [s for s, _ in statuses]
        self.assertNotIn("long_recording_detected", names)
        self.assertNotIn("chunking_progress", names)

    def test_on_recording_complete_processes_recording_via_dispatcher(self):
        # on_recording_complete now hands the recording to the held-queue
        # dispatcher (a real thread by design — see _ensure_recording_dispatcher)
        # and returns immediately, so the draft lands asynchronously. The wait
        # runs INSIDE the patch context and holds until the pipeline's terminal
        # "idle" broadcast — exiting on the draft alone would let the tail of
        # the pipeline race the patch teardown (and the next test).
        import threading as _threading

        pipeline_idle = _threading.Event()

        def _observe(status, data=None):
            if status == "idle":
                pipeline_idle.set()

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=_observe):
            server.on_recording_complete(DummyRecordingResult())
            self.assertTrue(pipeline_idle.wait(timeout=10.0))

        self.assertEqual(len(server.draft_queue), 1)
        self.assertEqual(server.draft_queue[0]["final_text"], "True Janitor: raw transcript")

    def test_process_recording_result_blocks_no_audio_before_llm(self):
        statuses = []

        with patch.object(server, "Transcriber", EmptyTranscriber), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not run for blocked audio")
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(SilentRecordingResult())

        self.assertEqual(draft["status"], "blocked")
        self.assertIn("clip_too_short", " ".join(draft["gate_reasons"]))
        self.assertIn("near_silent", " ".join(draft["gate_reasons"]))
        self.assertIn("empty_transcript", draft["gate_reasons"])
        self.assertEqual([status for status, _data in statuses], ["transcribing", "draft_blocked", "idle"])

    def test_process_recording_result_creates_error_draft_when_llm_fails(self):
        statuses = []

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", side_effect=RuntimeError("llm offline")
        ), patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "error")
        self.assertEqual(draft["raw_text"], "raw transcript")
        self.assertIn("llm offline", draft["error"])
        draft_statuses = [status for status, _data in statuses if status != "draft_tts_stopped"]
        self.assertEqual(draft_statuses, ["transcribing", "rewriting", "draft_error", "error", "idle"])

    def test_retry_endpoint_reprocesses_stored_recording(self):
        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", side_effect=RuntimeError("llm offline")
        ), patch.object(server, "broadcast_status_threadsafe"):
            failed = server.process_recording_result(DummyRecordingResult())

        with patch.object(server, "Transcriber", DummyTranscriber), patch.object(
            server, "get_engine", return_value=DummyEngine()
        ), patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                retried = client.post(f"/drafts/{failed['id']}/retry")

        self.assertEqual(retried.status_code, 200)
        self.assertEqual(retried.json()["status"], "pending")
        self.assertEqual(retried.json()["final_text"], "True Janitor: raw transcript")
        self.assertEqual(len(server.draft_queue), 2)

    def test_edit_draft_updates_review_fields_and_broadcasts(self):
        draft = server.create_draft("raw", "final")
        statuses = []

        with patch.object(server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/edit", json={"final_text": "edited text now"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["final_text"], "edited text now")
        self.assertEqual(data["token_count"], 3)
        self.assertEqual(statuses[0][0], "draft_updated")
        self.assertEqual(statuses[0][1]["draft_id"], draft["id"])

    def test_rewrite_draft_updates_final_text_and_broadcasts(self):
        draft = server.create_draft("raw", "final")
        statuses = []

        with patch.object(server, "get_engine", return_value=DummyRewriteEngine()), patch.object(
            server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    f"/drafts/{draft['id']}/rewrite",
                    json={"action": "custom", "custom_instruction": "make it cozy"},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["final_text"], "custom: final make it cozy")
        self.assertEqual(data["status"], "pending")
        rewrite_statuses = [(status, payload) for status, payload in statuses if status.startswith("draft_rewrit")]
        self.assertEqual([status for status, _payload in rewrite_statuses], ["draft_rewriting", "draft_rewritten"])
        self.assertEqual(rewrite_statuses[1][1]["draft_id"], draft["id"])

    def test_draft_tts_uses_selected_text_payload(self):
        draft = server.create_draft("raw", "final")
        statuses = []
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "broadcast_status_threadsafe", side_effect=lambda status, data=None: statuses.append((status, data or {}))
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    f"/drafts/{draft['id']}/tts",
                    json={"text": "selected words", "voice_id": "standard_female", "speed": 1.4},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["backend"], "kokoro_onnx")
        self.assertEqual(data["text_length"], len("selected words"))
        self.assertEqual(tts.calls[0], {
            "text": "selected words", "speed": 1.4, "voice_hint": "af_heart",
            "blend": None,
            "modulation": {"pitch": 0.0, "energy": 0.5, "warmth": 0.0, "brightness": 0.0, "pause_style": "natural"},
        })
        self.assertEqual(statuses[0][0], "draft_tts_requested")

    def test_tts_speak_calls_runtime_engine(self):
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={"text": "hello there", "voice_id": "standard_male", "speed": 1.2},
                )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["status"], "success")
        self.assertEqual(tts.calls[0], {
            "text": "hello there", "speed": 1.2, "voice_hint": "am_puck",
            "blend": None,
            "modulation": {"pitch": 0.0, "energy": 0.5, "warmth": 0.0, "brightness": 0.0, "pause_style": "natural"},
        })

    def test_tts_speak_passes_through_blend_and_modulation_fields(self):
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={
                        "text": "hello", "voice_id": "af_heart", "speed": 1.0,
                        "blend": {"am_adam": 0.3}, "pitch": 2.0, "energy": 0.9,
                        "warmth": 0.4, "brightness": 0.1, "pause_style": "dramatic",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["blend"], {"am_adam": 0.3})
        self.assertEqual(
            tts.calls[0]["modulation"],
            {"pitch": 2.0, "energy": 0.9, "warmth": 0.4, "brightness": 0.1, "pause_style": "dramatic"},
        )

    def _isolate_user_data(self):
        import os
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # Seed a residency-off profile, mirroring tests/conftest.py. On Windows
        # APPDATA (set below) IS the profile root, so a pristine dir would get
        # default keep-loaded settings and the TestClient startup would begin a
        # real multi-GB model download mid-test — whose open .part handle then
        # breaks TemporaryDirectory cleanup with WinError 32.
        profiles = os.path.join(tmp.name, "BetterFingers", "profiles")
        os.makedirs(profiles, exist_ok=True)
        with open(os.path.join(profiles, "Default.yaml"), "w") as fh:
            fh.write(
                "model_keep_llm_loaded: false\n"
                "model_keep_stt_loaded: false\n"
                "model_keep_tts_loaded: false\n"
            )
        original = os.environ.get("APPDATA")
        os.environ["APPDATA"] = tmp.name
        if original is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", original))

    def test_tts_speak_uses_preset_when_no_explicit_fields(self):
        self._isolate_user_data()
        import voice_presets
        voice_presets.save_preset(
            "Warm Assistant", base="af_bella", blend={"am_adam": 0.2}, speed=1.1, pitch=1.0,
        )
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={"text": "hello", "preset_name": "Warm Assistant"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "af_bella")
        self.assertEqual(tts.calls[0]["speed"], 1.1)
        self.assertEqual(tts.calls[0]["blend"], {"am_adam": 0.2})
        self.assertEqual(tts.calls[0]["modulation"]["pitch"], 1.0)

    def test_tts_speak_explicit_fields_override_preset(self):
        self._isolate_user_data()
        import voice_presets
        voice_presets.save_preset("Warm Assistant", base="af_bella", speed=1.1)
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={"text": "hello", "preset_name": "Warm Assistant", "voice_id": "am_puck", "speed": 2.0},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "am_puck")
        self.assertEqual(tts.calls[0]["speed"], 2.0)

    def test_tts_speak_dangling_preset_name_falls_back_gracefully(self):
        self._isolate_user_data()
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={"text": "hello", "preset_name": "does not exist"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        # Dangling preset falls back to the profile default (unchanged pre-existing
        # behavior), not a hardcoded "standard_female" — that's the config-less fallback.
        self.assertEqual(tts.calls[0]["voice_hint"], "english")

    def test_voice_presets_crud_routes(self):
        self._isolate_user_data()

        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                empty = client.get("/voice-presets")
                self.assertEqual(empty.json()["presets"], [])

                saved = client.post("/voice-presets", json={"name": "Crisp Editor", "base": "am_puck", "speed": 1.2})
                self.assertEqual(saved.status_code, 200)
                self.assertEqual(len(saved.json()["presets"]), 1)
                self.assertEqual(saved.json()["presets"][0]["base"], "am_puck")

                listed = client.get("/voice-presets")
                self.assertEqual(len(listed.json()["presets"]), 1)

                deleted = client.delete("/voice-presets/Crisp Editor")
                self.assertEqual(deleted.json()["presets"], [])

    def test_voice_presets_blank_name_rejected(self):
        self._isolate_user_data()
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                response = client.post("/voice-presets", json={"name": "   "})
        self.assertEqual(response.status_code, 400)

    def test_tts_speak_uses_persona_voice_when_persona_has_identity(self):
        self._isolate_user_data()
        import llm_engine
        llm_engine.upsert_persona("Narrator", {
            "prompt": "Read it clearly.",
            "voice": {"base": "bm_george", "pitch": -1.0, "energy": 0.8},
        })
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post("/tts/speak", json={"text": "hello", "persona": "Narrator"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "bm_george")
        self.assertEqual(tts.calls[0]["modulation"]["pitch"], -1.0)
        self.assertEqual(tts.calls[0]["modulation"]["energy"], 0.8)

    def test_tts_speak_persona_without_voice_identity_falls_through_to_profile(self):
        self._isolate_user_data()
        import llm_engine
        # A persona whose voice was never configured (all defaults) must not
        # override the profile default with its inert base="" / energy=0.5 etc.
        llm_engine.upsert_persona("Plain", {"prompt": "Just rewrite it."})
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post("/tts/speak", json={"text": "hello", "persona": "Plain"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "english")  # profile default, not persona's inert ""

    def test_tts_speak_persona_preset_used_when_persona_base_unset(self):
        self._isolate_user_data()
        import llm_engine
        import voice_presets
        voice_presets.save_preset("Presentation Voice", base="am_michael", speed=1.05)
        llm_engine.upsert_persona("Presenter", {
            "prompt": "Present it.", "voice": {"preset": "Presentation Voice"},
        })
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post("/tts/speak", json={"text": "hello", "persona": "Presenter"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "am_michael")
        self.assertEqual(tts.calls[0]["speed"], 1.05)

    def test_tts_speak_explicit_field_overrides_persona(self):
        self._isolate_user_data()
        import llm_engine
        llm_engine.upsert_persona("Narrator", {
            "prompt": "Read it.", "voice": {"base": "bm_george"},
        })
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak", json={"text": "hello", "persona": "Narrator", "voice_id": "am_puck"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "am_puck")

    def test_tts_speak_request_preset_wins_over_persona(self):
        self._isolate_user_data()
        import llm_engine
        import voice_presets
        voice_presets.save_preset("Explicit Preset", base="af_sarah")
        llm_engine.upsert_persona("Narrator", {"prompt": "Read it.", "voice": {"base": "bm_george"}})
        tts = DummyTTSEngine()

        with patch.object(server, "ensure_tts_initialized", return_value=tts), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/speak",
                    json={"text": "hello", "persona": "Narrator", "preset_name": "Explicit Preset"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(tts.calls[0]["voice_hint"], "af_sarah")

    def test_send_draft_copy_only_marks_sent(self):
        draft = server.create_draft("raw", "final")

        with patch.object(server, "copy_text_to_clipboard", return_value={"ok": True, "action": "copy_only", "message": "copied"}):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/send", json={"action": "copy_only"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "sent")
        self.assertFalse(data["pending_send"])
        self.assertTrue(data["send_result"]["ok"])

    def test_send_draft_falls_back_to_copy_when_injection_unsupported(self):
        draft = server.create_draft("raw", "final")

        with patch.object(server, "get_capabilities", return_value={"supports_input_injection": False}), patch.object(
            server, "copy_text_to_clipboard", return_value={"ok": True, "action": "copy_only", "message": "copied"}
        ):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/send", json={"action": "paste"})

        self.assertEqual(response.status_code, 200)
        result = response.json()["send_result"]
        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["fallback_reason"], "input_injection_unsupported")
        self.assertEqual(result["requested_action"], "paste")
        self.assertEqual(result["actual_action"], "copy_only")
        self.assertEqual(result["action"], "copy_only")
        self.assertFalse(result["input_injection_supported"])

    def test_send_draft_reports_injection_failure_copy_fallback(self):
        draft = server.create_draft("raw", "final")
        server.output_injector = FailingSendInjector()

        with patch.object(server, "get_capabilities", return_value={"supports_input_injection": True, "platform": "Windows", "session_type": "desktop"}), patch.object(
            server, "copy_text_to_clipboard", return_value={"ok": True, "action": "copy_only", "message": "copied"}
        ):
            with TestClient(server.app) as client:
                response = client.post(f"/drafts/{draft['id']}/send", json={"action": "paste"})

        self.assertEqual(response.status_code, 200)
        result = response.json()["send_result"]
        self.assertTrue(result["ok"])
        self.assertTrue(result["fallback"])
        self.assertEqual(result["fallback_reason"], "injection_failed")
        self.assertEqual(result["requested_action"], "paste")
        self.assertEqual(result["actual_action"], "copy_only")
        self.assertTrue(result["input_injection_supported"])
        self.assertTrue(result["injection_attempted"])

    def test_empty_send_result_fails_cleanly(self):
        draft = server.create_draft("raw", "")

        with TestClient(server.app) as client:
            response = client.post(f"/drafts/{draft['id']}/send", json={"action": "paste"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "send_error")
        self.assertEqual(data["send_result"]["error"], "empty_text")
        self.assertFalse(data["send_result"]["ok"])

    def test_primary_action_sends_pending_draft_first(self):
        draft = server.create_draft("raw", "final")
        with TestClient(server.app) as client:
            client.post(f"/drafts/{draft['id']}/accept")

        with patch.object(server, "perform_output_action", return_value={"ok": True, "action": "paste", "message": "sent"}):
            result = server.handle_primary_action()

        self.assertEqual(result["status"], "sent")
        self.assertEqual(server.pending_manual_send_ids, [])

    def test_primary_action_captures_selection_when_no_pending_draft(self):
        capture_result = {"ok": True, "text": "selected text", "message": "Captured selected text."}

        with patch("clipboard_capture.capture_selection_text_with_restore", return_value=capture_result), patch.object(
            server, "broadcast_status_threadsafe"
        ) as broadcast:
            result = server.handle_primary_action()

        self.assertEqual(result, capture_result)
        broadcast.assert_called_with("selection_captured", capture_result)

    def test_emergency_stop_stops_recording_typing_and_pending_sends(self):
        injector = DummyOutputInjector()
        manager = DummyRecordingManager()
        server.output_injector = injector
        server.hotkey_manager = manager
        server.pending_manual_send_ids.append(123)

        with patch.object(server, "broadcast_status_threadsafe"):
            result = server.emergency_stop_runtime()

        self.assertTrue(result["ok"])
        self.assertEqual(manager.stop_reason, "emergency_stop")
        self.assertTrue(injector.stopped)
        self.assertTrue(injector.released)
        self.assertEqual(server.pending_manual_send_ids, [])

    def test_clear_draft_history_route(self):
        server.create_draft("raw text", "final text")
        self.assertEqual(len(server.draft_queue), 1)

        with patch.object(server, "save_draft_history"), patch.object(server, "broadcast_status_threadsafe") as broadcast:
            with TestClient(server.app) as client:
                response = client.delete("/drafts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "message": "Draft history cleared."})
        self.assertEqual(len(server.draft_queue), 0)
        broadcast.assert_called_with("draft_history_cleared")

    def test_mock_draft_production_gating(self):
        with patch.dict(server.os.environ, {"BETTERFINGERS_ENV": "development"}), patch.object(server, "broadcast_status_threadsafe"):
            with TestClient(server.app) as client:
                response = client.post("/drafts/test-mock")
                self.assertEqual(response.status_code, 200)

        with patch.dict(server.os.environ, {"BETTERFINGERS_ENV": "production"}):
            with TestClient(server.app) as client:
                response = client.post("/drafts/test-mock")
                self.assertEqual(response.status_code, 403)
                self.assertIn("Mock endpoints are disabled", response.json()["detail"])

    def test_draft_persistence_save_and_load(self):
        server.create_draft("raw persist", "final persist")
        
        # Stop the global mock so we can test the real save function. The save
        # is atomic now: it writes a temp file and os.replace()s it into place.
        self._save_draft_patcher.stop()
        try:
            # os.path.join is separator-aware, so build the expected paths the
            # same way the implementation does (backslashes on Windows).
            data_dir = "/tmp"
            tmp_path = os.path.join(data_dir, "draft_history.json.tmp")
            final_path = os.path.join(data_dir, "draft_history.json")
            with patch("server.get_user_data_path", return_value=data_dir), \
                 patch("builtins.open", new_callable=unittest.mock.mock_open) as mock_file, \
                 patch("server.os.replace") as mock_replace:
                server.save_draft_history()
                mock_file.assert_called_with(tmp_path, "w", encoding="utf-8")
                mock_replace.assert_called_with(tmp_path, final_path)
        finally:
            self._save_draft_patcher.start()

        import json
        mock_data = json.dumps([
            {
                "id": 42,
                "raw_text": "loaded raw",
                "final_text": "loaded final",
                "preset": "True Janitor",
                "status": "pending",
                "metadata": {},
                "error": "",
                "gate_reasons": [],
                "token_count": 2,
                "token_limit": 1000,
                "long_text": False
            }
        ])
        # Stop the global mock so we can test the real load function. SQLite is
        # canonical now (P1): mock history_store as empty/unrecoverable so the
        # load falls back to the JSON fixture below, exactly like a fresh
        # install migrating pre-existing draft_history.json.
        self._load_draft_patcher.stop()
        try:
            with patch("server.get_user_data_path", return_value=data_dir), \
                 patch("server.os.path.exists", return_value=True), \
                 patch("server.os.replace") as mock_load_replace, \
                 patch("builtins.open", unittest.mock.mock_open(read_data=mock_data)), \
                 patch("server.history_store.init"), \
                 patch("server.history_store.verify_schema", return_value={"ok": True}), \
                 patch("server.history_store.load_recent_full", return_value=[]), \
                 patch("server.history_store.migrate_from_json", return_value=0):
                server.load_draft_history()
                self.assertEqual(len(server.draft_queue), 1)
                self.assertEqual(server.draft_queue[0]["id"], 42)
                self.assertEqual(server.next_draft_id, 43)
                # The JSON fallback is imported into SQLite and retired as a
                # migration backup, never read as canonical again.
                history_path = os.path.join(data_dir, "draft_history.json")
                mock_load_replace.assert_called_with(history_path, history_path + ".migrated")
        finally:
            self._load_draft_patcher.start()

    def test_load_draft_history_prefers_sqlite_over_json(self):
        # When history_store already has records, it is canonical: the JSON
        # file must not be read, imported, or touched at all (P1).
        self._load_draft_patcher.stop()
        try:
            with patch("server.get_user_data_path", return_value="/tmp"), \
                 patch("server.os.path.exists", return_value=True) as mock_exists, \
                 patch("server.os.replace") as mock_replace, \
                 patch("builtins.open", unittest.mock.mock_open()) as mock_file, \
                 patch("server.history_store.init"), \
                 patch("server.history_store.verify_schema", return_value={"ok": True}), \
                 patch("server.history_store.load_recent_full", return_value=[{"id": 7, "final_text": "from db"}]), \
                 patch("server.history_store.migrate_from_json") as mock_migrate:
                server.load_draft_history()
                self.assertEqual(len(server.draft_queue), 1)
                self.assertEqual(server.draft_queue[0]["id"], 7)
                self.assertEqual(server.next_draft_id, 8)
                mock_file.assert_not_called()
                mock_migrate.assert_not_called()
                mock_replace.assert_not_called()
                mock_exists.assert_not_called()
        finally:
            self._load_draft_patcher.start()

    def test_cancellation_semantics_in_processing(self):
        class CancellingTranscriber(DummyTranscriber):
            def transcribe(self, audio_data):
                server.cancellation_event.set()
                return "raw transcript"

        with patch.object(server, "Transcriber", CancellingTranscriber), patch.object(
            server, "get_engine", side_effect=AssertionError("LLM should not run when cancelled")
        ), patch.object(server, "broadcast_status_threadsafe"):
            draft = server.process_recording_result(DummyRecordingResult())

        self.assertEqual(draft["status"], "error")
        self.assertIn("Operation cancelled by user", draft["error"])

    def _wav_bytes(self, seconds=3, silent=False):
        import io
        import wave
        import numpy as np

        sample_rate = 24000
        if silent:
            audio = np.zeros(int(seconds * sample_rate), dtype=np.float32)
        else:
            t = np.linspace(0, seconds, int(seconds * sample_rate), endpoint=False)
            audio = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        pcm16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(pcm16.tobytes())
        buf.seek(0)
        return buf

    def test_tts_clone_requires_consent(self):
        self._isolate_user_data()
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/clone",
                    files={"file": ("sample.wav", self._wav_bytes(), "audio/wav")},
                    data={"name": "My Voice", "consent": "false"},
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn("consent", response.json()["detail"].lower())

    def test_tts_clone_rejects_bad_sample(self):
        self._isolate_user_data()
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/clone",
                    files={"file": ("sample.wav", self._wav_bytes(seconds=3, silent=True), "audio/wav")},
                    data={"name": "Silent Voice", "consent": "true"},
                )
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertIn("warnings", detail)
        self.assertTrue(detail["warnings"])

    def test_tts_clone_saves_valid_sample_with_meta(self):
        self._isolate_user_data()
        import json
        import os
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/clone",
                    files={"file": ("sample.wav", self._wav_bytes(), "audio/wav")},
                    data={"name": "My Voice", "consent": "true"},
                )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["voice_id"], "cloned_My_Voice")

        meta_path = os.path.join(str(server.get_voices_path()), "cloned_My_Voice.meta.json")
        self.assertTrue(os.path.exists(meta_path))
        with open(meta_path, encoding="utf-8") as handle:
            meta = json.load(handle)
        self.assertTrue(meta["cloned_voice"])
        self.assertTrue(meta["consent"])
        self.assertIn("qa", meta)
        self.assertIn("created_at", meta)

    def test_tts_clone_blank_name_rejected(self):
        self._isolate_user_data()
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                response = client.post(
                    "/tts/clone",
                    files={"file": ("sample.wav", self._wav_bytes(), "audio/wav")},
                    data={"name": "   ", "consent": "true"},
                )
        self.assertEqual(response.status_code, 400)

    def test_tts_voices_surfaces_clone_meta(self):
        self._isolate_user_data()
        with patch.object(server, "Transcriber", DummyTranscriber):
            with TestClient(server.app) as client:
                client.post(
                    "/tts/clone",
                    files={"file": ("sample.wav", self._wav_bytes(), "audio/wav")},
                    data={"name": "My Voice", "consent": "true"},
                )
                voices = client.get("/tts/voices").json()

        cloned = next((v for v in voices["cloned"] if v["id"] == "cloned_My_Voice"), None)
        self.assertIsNotNone(cloned)
        self.assertTrue(cloned["meta"]["cloned_voice"])
        self.assertTrue(cloned["meta"]["consent"])


if __name__ == "__main__":
    unittest.main()
