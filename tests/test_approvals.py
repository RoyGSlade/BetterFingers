"""The signed-approval verifier (Phase 0 item 1) and full-preview binding (item 2)."""
import base64
import json
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from approval_support import TEST_KEY, sign_ticket, workflow_ticket
from backend.services import approvals
from backend.services.approvals import ApprovalError

REPO = Path(__file__).resolve().parents[1]
LINES = ["Open Notepad", "Switch persona to Streamer"]
STEPS = [{"action": "launch_app", "app_id": "notepad"}]


def verify_workflow(ticket, lines=LINES, steps=STEPS, subject="stream-time", **kw):
    return approvals.verify(
        ticket,
        purpose=approvals.PURPOSE_WORKFLOW_APPROVE,
        subject=subject,
        bind=approvals.workflow_bind(lines, steps),
        **kw,
    )


class DigestTests(unittest.TestCase):
    def test_fixed_test_vector_shared_with_the_node_broker(self):
        """app/tests/approvalBroker.test.mjs asserts the SAME values; if either
        side changes the framing the two suites fail together."""
        self.assertEqual(
            approvals.lines_digest(["Open Notepad", "héllo ☃", ""]),
            "a155a24a76eab50aa86eb05acf8f13b0a0242b5fc2e198a52216e9f27b96e55b",
        )
        self.assertEqual(
            approvals.steps_digest([{"action": "launch_app", "app_id": "notepad"}, {"action": "focus_app", "n": 1, "tag": "é"}]),
            "2a109c57823bd18ec9b1f3fcaef43e8a4f0ceb1cafd55131174180c83d063026",
        )
        self.assertEqual(
            approvals.draft_send_bind("paste", "Hello wörld", False)["text_sha256"],
            "6d1e91489f85c8e2029be2e905b54a773f23aa89325aef24c7ce7555f998a23d",
        )
        self.assertEqual(
            approvals.persona_example_bind("Streamer", "raw é", "out")["example_sha256"],
            "4b54f4d0277810671e855eedd541b4a2e7899678ef13d303f6bf3a413ce4de73",
        )

    def test_framing_prevents_boundary_games(self):
        self.assertNotEqual(approvals.lines_digest(["ab", "c"]), approvals.lines_digest(["a", "bc"]))
        self.assertNotEqual(approvals.lines_digest(["a\nb"]), approvals.lines_digest(["a", "b"]))
        self.assertNotEqual(approvals.lines_digest([]), approvals.lines_digest([""]))

    def test_digest_covers_the_complete_text(self):
        prefix = "x" * 240
        self.assertNotEqual(approvals.lines_digest([prefix + "A"]), approvals.lines_digest([prefix + "B"]))
        long_a = "y" * 100_000 + "a"
        long_b = "y" * 100_000 + "b"
        self.assertNotEqual(approvals.lines_digest([long_a]), approvals.lines_digest([long_b]))

    def test_steps_digest_is_order_independent_for_keys_only(self):
        self.assertEqual(
            approvals.steps_digest([{"a": 1, "b": 2}]), approvals.steps_digest([{"b": 2, "a": 1}])
        )
        self.assertNotEqual(approvals.steps_digest([{"a": 1}, {"b": 2}]), approvals.steps_digest([{"b": 2}, {"a": 1}]))


class VerifyTests(unittest.TestCase):
    def test_a_genuine_ticket_verifies_and_returns_a_proof(self):
        proof = verify_workflow(workflow_ticket("stream-time", LINES, STEPS))
        self.assertTrue(proof.is_genuine())
        self.assertTrue(approvals.require_verified(proof, purpose=approvals.PURPOSE_WORKFLOW_APPROVE,
                                                   subject="stream-time"))
        self.assertFalse(approvals.require_verified(proof, purpose=approvals.PURPOSE_DRAFT_SEND))
        self.assertFalse(approvals.require_verified(proof, purpose=approvals.PURPOSE_WORKFLOW_APPROVE,
                                                    subject="other"))

    def test_no_ticket_means_approval_required(self):
        with self.assertRaises(ApprovalError) as ctx:
            verify_workflow(None)
        self.assertEqual(ctx.exception.code, approvals.ERR_REQUIRED)

    def test_without_a_key_nothing_can_be_approved(self):
        approvals.reset()
        with self.assertRaises(ApprovalError) as ctx:
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS))
        self.assertEqual(ctx.exception.code, approvals.ERR_UNAVAILABLE)
        self.assertEqual(approvals.http_status_for(ctx.exception.code), 503)

    def test_a_ticket_signed_with_another_key_is_refused(self):
        forged = workflow_ticket("stream-time", LINES, STEPS, secret=b"\x01" * 32)
        with self.assertRaises(ApprovalError) as ctx:
            verify_workflow(forged)
        self.assertEqual(ctx.exception.code, approvals.ERR_INVALID)

    def test_tampering_with_the_payload_breaks_the_signature(self):
        ticket = workflow_ticket("stream-time", LINES, STEPS)
        payload = json.loads(base64.urlsafe_b64decode(ticket["payload"] + "=="))
        payload["subject"] = "other"
        forged = {
            "payload": base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("="),
            "sig": ticket["sig"],
        }
        with self.assertRaises(ApprovalError):
            verify_workflow(forged, subject="other")

    def test_malformed_tickets_are_refused_not_crashed_on(self):
        good = workflow_ticket("stream-time", LINES, STEPS)
        for bad in (
            "string", 42, [], {}, {"payload": 1, "sig": 2}, {"payload": "", "sig": "0" * 64},
            {"payload": good["payload"], "sig": "short"}, {"payload": good["payload"], "sig": 12345},
            {"payload": "A" * 5000, "sig": "0" * 64}, {"payload": "!!!", "sig": "0" * 64},
            {"payload": good["payload"], "sig": "z" * 64},
        ):
            with self.assertRaises(ApprovalError):
                verify_workflow(bad)

    def test_wrong_purpose_subject_or_content_is_refused(self):
        ticket = workflow_ticket("stream-time", LINES, STEPS)
        with self.assertRaises(ApprovalError):  # other workflow
            verify_workflow(ticket, subject="delete-stuff")
        with self.assertRaises(ApprovalError):  # one character changed in the preview
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS), lines=[LINES[0], LINES[1] + "!"])
        with self.assertRaises(ApprovalError):  # steps edited after the dialog
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS), steps=[{"action": "launch_app", "app_id": "evil"}])
        with self.assertRaises(ApprovalError):  # another purpose entirely
            approvals.verify(workflow_ticket("stream-time", LINES, STEPS),
                             purpose=approvals.PURPOSE_DRAFT_SEND, subject="stream-time",
                             bind=approvals.workflow_bind(LINES, STEPS))

    def test_extra_or_missing_bound_digests_are_refused(self):
        ticket = sign_ticket(approvals.PURPOSE_WORKFLOW_APPROVE, "w", {"preview_sha256": approvals.preview_digest(LINES)})
        with self.assertRaises(ApprovalError):
            verify_workflow(ticket, subject="w")

    def test_a_ticket_is_single_use(self):
        ticket = workflow_ticket("stream-time", LINES, STEPS)
        verify_workflow(ticket)
        with self.assertRaises(ApprovalError) as ctx:
            verify_workflow(ticket)
        self.assertEqual(ctx.exception.code, approvals.ERR_INVALID)

    def test_a_mismatching_attempt_does_not_spend_the_ticket(self):
        ticket = workflow_ticket("stream-time", LINES, STEPS)
        with self.assertRaises(ApprovalError):
            verify_workflow(ticket, lines=["something else"])
        verify_workflow(ticket)  # the genuine use still works

    def test_expired_and_far_future_tickets_are_refused(self):
        now = time.time()
        with self.assertRaises(ApprovalError):
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS, now=now - 500, ttl=60))
        with self.assertRaises(ApprovalError):
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS, now=now + 3600, ttl=60))

    def test_a_long_lived_ticket_is_refused_even_if_validly_signed(self):
        with self.assertRaises(ApprovalError):
            verify_workflow(workflow_ticket("stream-time", LINES, STEPS, ttl=approvals.MAX_TICKET_LIFETIME_S + 60))

    def test_bad_nonce_version_and_types_are_refused(self):
        for kw in ({"nonce": "short"}, {"version": 2}, {"extra": {"exp": True}}, {"extra": {"iat": "x"}}):
            with self.assertRaises(ApprovalError, msg=str(kw)):
                verify_workflow(workflow_ticket("stream-time", LINES, STEPS, **kw))

    def test_error_messages_do_not_echo_ticket_contents(self):
        with self.assertRaises(ApprovalError) as ctx:
            verify_workflow({"payload": "secret-payload", "sig": "0" * 64})
        self.assertNotIn("secret-payload", ctx.exception.message)


class ConfigurationTests(unittest.TestCase):
    def test_key_is_removed_from_the_environment_when_read(self):
        env = {"BETTERFINGERS_APPROVAL_KEY": TEST_KEY.hex(), "OTHER": "1"}
        approvals.reset()
        self.assertTrue(approvals.configure_from_env(env))
        self.assertNotIn("BETTERFINGERS_APPROVAL_KEY", env)
        self.assertIn("OTHER", env)
        self.assertTrue(approvals.is_configured())
        verify_workflow(workflow_ticket("w", LINES, STEPS), subject="w")

    def test_short_or_missing_keys_are_not_installed(self):
        approvals.reset()
        self.assertFalse(approvals.configure_from_env({"BETTERFINGERS_APPROVAL_KEY": "abcd"}))
        self.assertFalse(approvals.configure_from_env({}))
        self.assertFalse(approvals.is_configured())

    def test_the_production_default_enforces_approvals(self):
        """The test suite relaxes the gate per file (conftest); a fresh interpreter
        must come up enforcing, so a packaged app can never run with it off."""
        out = subprocess.run(
            [sys.executable, "-c", "from backend.services import approvals; print(approvals.ENFORCE)"],
            capture_output=True, text=True, cwd=REPO, check=True,
        )
        self.assertEqual(out.stdout.strip(), "True")


@unittest.skipUnless(shutil.which("node"), "node is required for the cross-language check")
class NodeBrokerInteropTests(unittest.TestCase):
    """The broker is JavaScript and the verifier is Python. These tests make the
    REAL Electron-side signer produce tickets and the REAL Python verifier accept
    or refuse them, so a drift in framing, canonicalisation or encoding cannot
    pass either suite alone."""

    SCRIPT = """
    const b = require(process.argv[1]);
    const key = Buffer.from(process.argv[2], 'hex');
    const cases = JSON.parse(process.argv[3]);
    const out = cases.map((c) => {
      const bind = c.kind === 'draft' ? b.draftSendBind(c.action, c.text, c.openChat)
        : c.kind === 'persona' ? b.personaExampleBind(c.persona, c.raw, c.out)
        : c.kind === 'few_shot' ? b.personaFewShotBind(c.persona, b.fewShotItems(c.before), b.fewShotItems(c.after))
        : c.kind === 'learned_delete' ? b.learnedDeleteBind(c.persona, c.exampleId, b.fewShotItems(c.before), b.fewShotItems(c.after))
        : c.kind === 'learned_add' ? b.learnedAddBind(c.persona, c.raw, c.out, c.before, c.after)
        : c.kind === 'learned_clear' ? b.learnedClearBind(c.persona, b.fewShotItems(c.before))
        : c.kind === 'persona_delete' ? b.personaDeleteBind(c.persona, b.fewShotItems(c.before))
        : c.kind === 'learned_clear_all' ? b.learnedClearAllBind(c.count)
        : c.kind === 'privacy_wipe' ? b.privacyWipeBind(c.mode, c.ids, { wipeVoices: c.wipeVoices, deleteModels: c.deleteModels })
        : { preview_sha256: b.linesDigest(c.lines), steps_sha256: c.steps_sha256 };
      return b.signTicket({ secret: key, purpose: c.purpose, subject: c.subject, bind });
    });
    console.log(JSON.stringify(out));
    """

    def tickets(self, cases):
        result = subprocess.run(
            ["node", "-e", self.SCRIPT, str(REPO / "app" / "src" / "main" / "approvalBroker.js"),
             TEST_KEY.hex(), json.dumps(cases)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        return json.loads(result.stdout)

    def test_node_signed_draft_persona_and_workflow_tickets_verify_in_python(self):
        text = "Héllo \u2603 wörld\nsecond line with 😀 and a\ttab"
        lines = ["1. Launch Obsidian (flatpak run md.obsidian.Obsidian)", "2. Say “ready” \u2603"]
        steps = [{"action": "launch_app", "app_id": "obsidian"}]
        draft, persona, workflow = self.tickets([
            {"kind": "draft", "purpose": "draft.send", "subject": "7", "action": "paste", "text": text, "openChat": False},
            {"kind": "persona", "purpose": "persona.example", "subject": "Coach", "persona": "Coach", "raw": "hey \u2603", "out": "Hey, 😀"},
            {"kind": "workflow", "purpose": "workflow.approve", "subject": "w", "lines": lines,
             "steps_sha256": approvals.steps_digest(steps)},
        ])
        approvals.verify(draft, purpose="draft.send", subject="7", bind=approvals.draft_send_bind("paste", text, False))
        approvals.verify(persona, purpose="persona.example", subject="Coach",
                         bind=approvals.persona_example_bind("Coach", "hey \u2603", "Hey, 😀"))
        approvals.verify(workflow, purpose="workflow.approve", subject="w", bind=approvals.workflow_bind(lines, steps))

    def test_node_signed_few_shot_list_tickets_verify_in_python(self):
        """Round 3, item 3: the bind is the complete ordered list before and after, normalised
        the same way on both sides (order, repeats, missing fields)."""
        before = [{"raw": "hey \u2603", "out": "Hey, 😀"}, {"raw": "second"}]
        after = [{"raw": "second", "out": None}, {"raw": "hey \u2603", "out": "Hey, 😀"}, {"raw": "second", "out": ""}, "junk"]
        (ticket, learned) = self.tickets([
            {"kind": "few_shot", "purpose": "persona.few_shot", "subject": "Coach", "persona": "Coach", "before": before, "after": after},
            {"kind": "learned_delete", "purpose": "persona.learned_delete", "subject": "Coach", "persona": "Coach",
             "exampleId": "ex_1", "before": before, "after": before[1:]},
        ])
        approvals.verify(ticket, purpose="persona.few_shot", subject="Coach",
                         bind=approvals.persona_few_shot_bind("Coach", approvals.few_shot_items(before), approvals.few_shot_items(after)))
        approvals.verify(learned, purpose="persona.learned_delete", subject="Coach",
                         bind=approvals.learned_delete_bind("Coach", "ex_1", approvals.few_shot_items(before), approvals.few_shot_items(before[1:])))

    def test_node_signed_round4_tickets_verify_in_python(self):
        """Round 4, items 3 and 5: learning with its resulting list, clearing one persona, deleting a
        persona, the global learned clear (its stated scope, round 5) and the privacy wipes, byte for byte."""
        items = [{"raw": "hey \u2603", "out": "Hey, 😀"}, {"raw": "second", "out": "Second."}]
        pairs = approvals.few_shot_items(items)
        ids = ["drafts", "persona_learning", "personas"]
        add, clear, delete, clear_all, wipe = self.tickets([
            {"kind": "learned_add", "purpose": "persona.example", "subject": "Coach", "persona": "Coach",
             "raw": " new ", "out": "New.", "before": [list(p) for p in pairs], "after": [list(p) for p in pairs] + [["new", "New."]]},
            {"kind": "learned_clear", "purpose": "persona.learned_clear", "subject": "Coach", "persona": "Coach", "before": items},
            {"kind": "persona_delete", "purpose": "persona.delete", "subject": "Coach", "persona": "Coach", "before": items},
            {"kind": "learned_clear_all", "purpose": "persona.learned_clear_all", "subject": "all", "count": 3},
            {"kind": "privacy_wipe", "purpose": "privacy.wipe", "subject": "clear_personal_data", "mode": "clear_personal_data",
             "ids": ids, "wipeVoices": True, "deleteModels": False},
        ])
        approvals.verify(add, purpose="persona.example", subject="Coach",
                         bind=approvals.learned_add_bind("Coach", " new ", "New.", pairs, pairs + [("new", "New.")]))
        approvals.verify(clear, purpose="persona.learned_clear", subject="Coach", bind=approvals.learned_clear_bind("Coach", pairs))
        approvals.verify(delete, purpose="persona.delete", subject="Coach", bind=approvals.persona_delete_bind("Coach", pairs))
        count = approvals.learned_example_count([("Coach", pairs), ("Zed", pairs[:1])])
        self.assertEqual(count, 3)
        approvals.verify(clear_all, purpose="persona.learned_clear_all", subject="all", bind=approvals.learned_clear_all_bind(count))
        approvals.verify(wipe, purpose="privacy.wipe", subject="clear_personal_data",
                         bind=approvals.privacy_wipe_bind("clear_personal_data", ids, wipe_voices=True))

    def test_node_and_python_agree_on_canonical_persona_names(self):
        """Round 4, item 1: main refuses an alias before any lookup; the backend refuses it too.
        Both sides must compute the same canonical form."""
        from backend.llm.llm_engine import canonical_persona_name

        names = ["Sample", "Sam!ple", " Sample ", "Sam\u200bple", "Café Noir", "Ünïcødé 2", "日本語", "a/b", "x\ny",
                 "Dr. Who-2_b", "²³", "e\u0301", "\u0661\u0662", "../workflows/approve", "", "!!!"]
        result = subprocess.run(
            ["node", "-e", "const b = require(process.argv[1]); console.log(JSON.stringify(JSON.parse(process.argv[2]).map(b.canonicalPersonaName)))",
             str(REPO / "app" / "src" / "main" / "approvalBroker.js"), json.dumps(names)],
            capture_output=True, text=True, check=True, timeout=60,
        )
        self.assertEqual(json.loads(result.stdout), [canonical_persona_name(n) for n in names])

    def test_a_node_ticket_for_one_text_is_refused_for_another_text(self):
        (ticket,) = self.tickets([
            {"kind": "draft", "purpose": "draft.send", "subject": "7", "action": "paste", "text": "A", "openChat": False},
        ])
        with self.assertRaises(ApprovalError):
            approvals.verify(ticket, purpose="draft.send", subject="7", bind=approvals.draft_send_bind("paste", "B", False))

    def test_a_node_ticket_signed_with_a_different_key_is_refused(self):
        result = subprocess.run(
            ["node", "-e", self.SCRIPT, str(REPO / "app" / "src" / "main" / "approvalBroker.js"),
             ("77" * 32), json.dumps([{"kind": "draft", "purpose": "draft.send", "subject": "7", "action": "paste", "text": "A", "openChat": False}])],
            capture_output=True, text=True, check=True, timeout=60,
        )
        (ticket,) = json.loads(result.stdout)
        with self.assertRaises(ApprovalError):
            approvals.verify(ticket, purpose="draft.send", subject="7", bind=approvals.draft_send_bind("paste", "A", False))


if __name__ == "__main__":
    unittest.main()
