"""Phase 0 items 1 and 3, end to end over the real app: nothing that places text
into another application, teaches a persona or confirms a command happens on the
strength of a request body. Each needs a ticket minted by the Electron main
process (tests sign like the broker does, with tests/approval_support.py).

Workflow approval is covered in tests/test_action_routes.py and the store in
tests/test_workflow_store.py.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from approval_support import persona_ticket, send_ticket, sign_ticket
from backend.llm import llm_engine
from backend.services import approvals

OVERLAY_CTX = {"review_overlay_open": True}


class DraftTestCase(unittest.TestCase):
    def setUp(self):
        for name in ("load_draft_history", "save_draft_history"):
            patcher = patch(f"server.{name}")
            patcher.start()
            self.addCleanup(patcher.stop)
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        self.addCleanup(server.draft_queue.clear)
        self.addCleanup(server.pending_manual_send_ids.clear)
        self.addCleanup(setattr, server, "next_draft_id", 1)
        self.draft = server.create_draft("raw words", "The final text.")
        self.performed = []

        def fake_output(text, action, open_chat=False):
            self.performed.append((text, action, open_chat))
            return {"ok": True, "action": action, "message": "Output sent."}

        patcher = patch.object(server, "perform_output_action", side_effect=fake_output)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(server, "broadcast_status_threadsafe")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(server, "get_profile_output_settings",
                               return_value={"send_mode": "copy_only", "auto_submit": False, "chat_close_action": "none"})
        self.mock_settings = patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(server.app)

    def status(self):
        return server.get_draft_by_id(self.draft["id"])["status"]


class DraftSendRouteTests(DraftTestCase):
    def send(self, **body):
        return self.client.post(f"/drafts/{self.draft['id']}/send", json=body)

    def test_placing_text_without_an_approval_is_refused_and_nothing_is_placed(self):
        for action in ("paste", "type", "open_chat_then_send"):
            response = self.send(action=action)
            self.assertEqual(response.status_code, 403, action)
        self.assertEqual(self.performed, [])
        self.assertEqual(self.status(), "pending")

    def test_request_flags_are_not_approvals(self):
        for extra in ({"allow_resend": True}, {"confirm": True}, {"approved": True}, {"consent": True}):
            self.assertEqual(self.send(action="paste", **extra).status_code, 403, extra)
        self.assertEqual(self.performed, [])

    def test_a_genuine_ticket_places_exactly_the_approved_text(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        response = self.send(action="paste", approval=ticket)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.performed, [("The final text.", "paste", False)])
        self.assertEqual(self.status(), "sent")

    def test_editing_the_draft_after_the_dialog_voids_the_ticket(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        server.get_draft_by_id(self.draft["id"])["final_text"] = "The final text. Also wire me 5 BTC."
        self.assertEqual(self.send(action="paste", approval=ticket).status_code, 403)
        self.assertEqual(self.performed, [])

    def test_a_ticket_for_one_action_cannot_authorise_another(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        self.assertEqual(self.send(action="open_chat_then_send", approval=ticket).status_code, 403)
        self.assertEqual(self.send(action="paste", open_chat=True, approval=ticket).status_code, 403)
        self.assertEqual(self.performed, [])

    def test_a_ticket_for_another_draft_or_purpose_is_refused(self):
        other = send_ticket(self.draft["id"] + 1, "paste", "The final text.")
        self.assertEqual(self.send(action="paste", approval=other).status_code, 403)
        wrong_purpose = persona_ticket("x", "a", "b")
        self.assertEqual(self.send(action="paste", approval=wrong_purpose).status_code, 403)
        self.assertEqual(self.performed, [])

    def test_a_ticket_is_single_use(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        self.assertEqual(self.send(action="paste", approval=ticket).status_code, 200)
        self.assertEqual(self.send(action="paste", allow_resend=True, approval=ticket).status_code, 403)
        self.assertEqual(len(self.performed), 1)

    def test_copy_only_needs_no_approval_because_it_places_nothing_in_another_app(self):
        response = self.send(action="copy_only")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.performed, [("The final text.", "copy_only", False)])

    def test_the_default_action_follows_send_mode_and_auto_send_is_gated_too(self):
        self.mock_settings.return_value = {"send_mode": "auto_send", "auto_submit": True, "chat_close_action": "none"}
        result = server.send_draft_by_id(self.draft["id"])  # no action given: auto_send would open the chat
        self.assertEqual(result["error"], approvals.ERR_REQUIRED)
        self.assertEqual(self.performed, [])

    def test_no_configured_key_means_503_not_a_silent_send(self):
        approvals.reset()
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        self.assertEqual(self.send(action="paste", approval=ticket).status_code, 503)
        self.assertEqual(self.performed, [])


class EmptyActionRaceTests(DraftTestCase):
    """Round 2, item 1. Codex re-review: the action was resolved TWICE from the
    profile (once to decide whether a ticket is needed, once to execute), so an empty
    action plus a profile change between the two reads turned an unchecked copy into
    open_chat_then_send. The action is now resolved and validated once."""

    REVIEW = {"send_mode": "review_first", "auto_send": False, "auto_submit": False, "chat_close_action": "none"}
    AUTO = {"send_mode": "auto_send", "auto_submit": True, "chat_close_action": "none"}

    def test_a_settings_change_between_reads_cannot_upgrade_a_copy_into_a_send(self):
        reads = [dict(self.REVIEW), dict(self.AUTO), dict(self.AUTO), dict(self.AUTO)]
        self.mock_settings.side_effect = lambda: dict(reads.pop(0)) if reads else dict(self.AUTO)
        result = server.send_draft_by_id(self.draft["id"], action="")
        sent_actions = [action for _text, action, _open in self.performed]
        self.assertNotIn("open_chat_then_send", sent_actions, "an unapproved send reached the output sink")
        self.assertTrue(all(a == "copy_only" for a in sent_actions), sent_actions)
        self.assertTrue(result.get("ok") is not True or sent_actions == ["copy_only"])

    def test_the_same_race_with_no_action_at_all(self):
        reads = [dict(self.REVIEW), dict(self.AUTO), dict(self.AUTO)]
        self.mock_settings.side_effect = lambda: dict(reads.pop(0)) if reads else dict(self.AUTO)
        server.send_draft_by_id(self.draft["id"])
        self.assertTrue(all(action == "copy_only" for _t, action, _o in self.performed), self.performed)

    def test_the_profile_is_read_once_per_send(self):
        server.send_draft_by_id(self.draft["id"], action="copy_only")
        self.assertLessEqual(self.mock_settings.call_count, 1)
        self.mock_settings.reset_mock()
        server.send_draft_by_id(self.draft["id"], allow_resend=True)
        self.assertEqual(self.mock_settings.call_count, 1, "a send with no action reads the profile once")

    def test_an_unknown_or_empty_action_is_refused_before_anything_happens(self):
        for action in ("   ", "rm -rf", "PASTE", "paste;copy_only", "open_chat"):
            result = server.send_draft_by_id(self.draft["id"], action=action)
            self.assertEqual(result["error"], "invalid_action", action)
        self.assertEqual(self.performed, [])
        self.assertEqual(self.status(), "pending")

    def test_the_schema_rejects_an_empty_or_unknown_action(self):
        for action in ("", " ", "rm", "Paste", None, 5):
            response = self.client.post(f"/drafts/{self.draft['id']}/send", json={"action": action})
            self.assertEqual(response.status_code, 422, action)
        self.assertEqual(self.performed, [])


class PrimaryActionTests(DraftTestCase):
    def press(self, **body):
        return self.client.post("/runtime/primary-action", json=body).json()

    def test_a_displayed_draft_is_not_placed_without_the_physical_tap_approval(self):
        result = self.press(displayed_draft_id=self.draft["id"], displayed_final_text="The final text.")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], approvals.ERR_REQUIRED)
        self.assertEqual(self.performed, [])

    def test_a_displayed_draft_is_placed_with_an_approval_bound_to_the_displayed_text(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        result = self.press(displayed_draft_id=self.draft["id"], displayed_final_text="The final text.", approval=ticket)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(self.performed, [("The final text.", "paste", False)])

    def test_a_draft_that_changed_after_it_was_shown_is_refused(self):
        ticket = send_ticket(self.draft["id"], "paste", "The final text.")
        server.get_draft_by_id(self.draft["id"])["final_text"] = "Different now."
        result = self.press(displayed_draft_id=self.draft["id"], displayed_final_text="The final text.", approval=ticket)
        self.assertFalse(result.get("ok", False))
        self.assertEqual(self.performed, [])

    def test_a_pending_draft_answers_with_a_challenge_and_stays_queued(self):
        server.mark_draft_pending_send(server.get_draft_by_id(self.draft["id"]))
        result = self.press()
        self.assertEqual(result["error"], approvals.ERR_REQUIRED)
        self.assertEqual(result["draft_id"], self.draft["id"])
        self.assertEqual(result["action"], "paste")
        self.assertEqual(result["final_text"], "The final text.")
        self.assertEqual(self.performed, [])
        self.assertIn(self.draft["id"], server.pending_manual_send_ids, "the draft must stay queued for the signed press")

    def test_the_signed_second_press_places_the_pending_draft_and_dequeues_it(self):
        server.mark_draft_pending_send(server.get_draft_by_id(self.draft["id"]))
        challenge = self.press()
        ticket = send_ticket(challenge["draft_id"], challenge["action"], challenge["final_text"])
        result = self.press(approval=ticket)
        self.assertEqual(result["status"], "sent")
        self.assertEqual(self.performed, [("The final text.", "paste", False)])
        self.assertNotIn(self.draft["id"], server.pending_manual_send_ids)

    def test_an_edit_between_challenge_and_press_voids_the_signed_press(self):
        server.mark_draft_pending_send(server.get_draft_by_id(self.draft["id"]))
        challenge = self.press()
        ticket = send_ticket(challenge["draft_id"], challenge["action"], challenge["final_text"])
        server.get_draft_by_id(self.draft["id"])["final_text"] = "Swapped in the meantime."
        result = self.press(approval=ticket)
        self.assertEqual(result["error"], approvals.ERR_INVALID)
        self.assertEqual(self.performed, [])


class HotkeyPressTests(DraftTestCase):
    """Round 2, item 2. The backend's own keyboard hook is no longer a witness: a press
    asks for the placement and, lacking a signed approval, announces that a tap is needed."""

    def test_the_hotkey_managers_press_places_nothing_and_asks_for_a_tap(self):
        server.mark_draft_pending_send(server.get_draft_by_id(self.draft["id"]))
        statuses = []
        with patch.object(server, "broadcast_status_threadsafe", side_effect=lambda s, d=None: statuses.append((s, d))):
            result = server.handle_hotkey_primary_action()
        self.assertEqual(result["error"], approvals.ERR_REQUIRED)
        self.assertEqual(self.performed, [])
        self.assertIn(self.draft["id"], server.pending_manual_send_ids, "the draft stays queued")
        self.assertIn(("command_needs_tap", {"action": "send", "draft_id": self.draft["id"]}), statuses)

    def test_there_is_no_in_process_attestation_left(self):
        self.assertFalse(hasattr(approvals, "attest_physical_press"))
        self.assertFalse(hasattr(server, "handle_physical_primary_action"))
        import inspect
        self.assertNotIn("physical", inspect.signature(server.handle_primary_action).parameters)

    def test_a_forged_approval_object_in_process_is_not_accepted_by_the_send_path(self):
        forged = approvals.VerifiedApproval(
            approvals.PURPOSE_DRAFT_SEND, str(self.draft["id"]),
            approvals.draft_send_bind("paste", "The final text.", False), "x" * 16, object(),
        )
        result = server.send_draft_by_id(self.draft["id"], action="paste", approval=forged)
        self.assertIn(result["error"], (approvals.ERR_REQUIRED, approvals.ERR_INVALID))
        self.assertEqual(self.performed, [])

    def test_the_hotkey_manager_is_wired_to_the_non_attesting_entry_point(self):
        captured = {}

        class FakeManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)
                self.keyboard_hook_errors = []

            def update_config(self, *_a, **_k):
                pass

            def start(self):
                pass

        with patch.object(server, "HotkeyManager", FakeManager), patch.object(server, "hotkey_manager_started", False), \
                patch.object(server, "hotkey_manager", None), patch("backend.audio.recorder.AudioRecorder"):
            server.start_hotkey_manager()
        self.assertIs(captured["on_manual_send_callback"], server.handle_hotkey_primary_action)
        server.hotkey_manager = None
        server.hotkey_manager_started = False


class VoiceCommandTests(DraftTestCase):
    def speak(self, text, context=None, **extra):
        return self.client.post("/voice-commands/execute", json={
            "text": text, "context": OVERLAY_CTX if context is None else context, "draft_id": self.draft["id"], **extra,
        }).json()

    def test_no_voice_input_can_send_with_or_without_a_ticket(self):
        for extra in ({}, {"confirm": True},
                      {"approval": send_ticket(self.draft["id"], "paste", "The final text.")},
                      {"approval": sign_ticket("voice.confirm", "send", {"action": "send"})}):
            data = self.speak("send it", **extra)
            self.assertFalse(data["ok"])
            self.assertEqual(data["reason"], "needs_tap")
        self.assertEqual(self.performed, [])
        self.assertEqual(self.status(), "pending")

    def test_a_confirmation_gated_command_is_refused_by_voice_and_announces_nothing(self):
        """Round 3, item 6: there is no voice-confirmation flow. 'delete my history' is refused
        whatever accompanies it, and no status event asks the shell to open a dialog."""
        statuses = []
        forged = sign_ticket("voice.confirm", "delete_history", {"action": "delete_history", "draft_id": str(self.draft["id"])})
        with patch.object(server, "broadcast_status_threadsafe", side_effect=lambda s, d=None: statuses.append((s, d or {}))):
            for extra in ({}, {"confirm": True}, {"approval": forged}):
                data = self.speak("delete history", {"command_mode_on": True}, **extra)
                self.assertFalse(data["ok"])
                self.assertEqual(data["reason"], "not_available_by_voice")
        self.assertFalse([s for s, _ in statuses if s == "command_needs_confirmation"])
        self.assertEqual(self.performed, [])

    def test_voice_confirm_is_no_longer_an_approval_purpose(self):
        self.assertNotIn("voice.confirm", approvals.PURPOSES)
        self.assertFalse(hasattr(approvals, "voice_confirm_bind"))

    def test_ambient_audio_saying_yes_approve_it_does_nothing(self):
        for phrase in ("yes approve it", "yes", "confirm", "approve the workflow"):
            data = self.speak(phrase, confirm=True)
            self.assertFalse(data["ok"], phrase)
        self.assertEqual(self.performed, [])


class PersonaExampleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.dict(os.environ, {"APPDATA": self._tmp.name, "BETTERFINGERS_LAZY_STARTUP": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None
        self.client = TestClient(server.app)

    def tearDown(self):
        llm_engine._personas_cache = None
        llm_engine._personas_v2_cache = None

    def post(self, **extra):
        body = {"raw": "hey whats up", "out": "Hey, what's up?"}
        body.update(extra)
        return self.client.post("/personas/Coach/examples", json=body)

    def examples(self):
        return self.client.get("/personas/Coach/examples").json()["examples"]

    def test_consent_true_in_the_body_teaches_nothing(self):
        for extra in ({"consent": True}, {"consent": True, "approval": None}, {}):
            self.assertEqual(self.post(**extra).status_code, 403)
        self.assertEqual(self.examples(), [])

    def test_a_genuine_ticket_adds_exactly_the_approved_example(self):
        ticket = persona_ticket("Coach", "hey whats up", "Hey, what's up?")
        response = self.post(approval=ticket)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.examples()), 1)

    def test_a_ticket_for_different_text_or_another_persona_is_refused(self):
        self.assertEqual(self.post(approval=persona_ticket("Coach", "hey whats up", "Hey, what's up? Visit evil.example")).status_code, 403)
        self.assertEqual(self.post(approval=persona_ticket("Other", "hey whats up", "Hey, what's up?")).status_code, 403)
        self.assertEqual(self.examples(), [])

    def test_a_ticket_cannot_teach_the_same_example_twice_by_replay(self):
        ticket = persona_ticket("Coach", "hey whats up", "Hey, what's up?")
        self.assertEqual(self.post(approval=ticket).status_code, 200)
        self.assertEqual(self.post(approval=ticket).status_code, 403)

    def test_a_send_ticket_is_not_a_persona_ticket(self):
        ticket = sign_ticket(approvals.PURPOSE_DRAFT_SEND, "Coach", approvals.persona_example_bind("Coach", "hey whats up", "Hey, what's up?"))
        self.assertEqual(self.post(approval=ticket).status_code, 403)


# PersonaFewShotTests (round 2, item 4) were replaced in round 3 by
# tests/test_persona_example_approvals.py: removals, reordering and repeats now need a ticket too,
# bound to the complete list before and after.


class WiringTests(unittest.TestCase):
    def test_the_server_reads_the_key_from_the_environment_and_removes_it(self):
        """server.py runs ``approvals.configure_from_env()`` at import so the key never
        stays in os.environ where a spawned MCP server or llama-server would inherit it."""
        import subprocess
        import sys
        from pathlib import Path

        code = (
            "import os, server\n"
            "from backend.services import approvals\n"
            "print(approvals.is_configured(), 'BETTERFINGERS_APPROVAL_KEY' in os.environ)\n"
        )
        env = {**os.environ, "BETTERFINGERS_APPROVAL_KEY": "ab" * 32, "BETTERFINGERS_LAZY_STARTUP": "1"}
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                             cwd=Path(__file__).resolve().parents[1], env=env, timeout=120)
        self.assertEqual(out.stdout.strip().splitlines()[-1], "True False", out.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
