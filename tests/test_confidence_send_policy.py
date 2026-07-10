"""Confidence-gated send policy (Phase 12).

A draft may auto-send only when the ASR confidence is high, the draft is short,
and no no-audio gate fired; otherwise it must be reviewed first. Keeps a mumbled
or long utterance from silently injecting even in auto_send mode.
"""

import unittest
from unittest.mock import patch

import server
import utils


class ConfidenceSendPolicyPureTests(unittest.TestCase):
    BASE = {
        "confidence_force_review_enabled": True,
        "confidence_force_review_below": 0.55,
        "confidence_auto_send_above": 0.85,
    }

    def policy(self, confidence, long_text=False, gate_reasons=None, **overrides):
        cfg = {**self.BASE, **overrides}
        return server.evaluate_confidence_send_policy(confidence, long_text, gate_reasons, cfg)

    def test_disabled_always_allows_auto_send(self):
        result = self.policy(
            {"score": 0.1},
            long_text=True,
            gate_reasons=["silent"],
            confidence_force_review_enabled=False,
        )
        self.assertTrue(result["auto_send_ok"])
        self.assertFalse(result["force_review"])
        self.assertEqual(result["reason"], "")

    def test_audio_gate_forces_review_even_with_high_confidence(self):
        result = self.policy({"score": 0.99}, gate_reasons=["no_audio"])
        self.assertFalse(result["auto_send_ok"])
        self.assertTrue(result["force_review"])
        self.assertEqual(result["reason"], "audio_gate")

    def test_long_draft_forces_review(self):
        result = self.policy({"score": 0.99}, long_text=True)
        self.assertTrue(result["force_review"])
        self.assertEqual(result["reason"], "long_draft")

    def test_missing_or_bad_score_forces_review(self):
        for confidence in (None, {}, {"score": None}, {"score": "abc"}, "notadict"):
            with self.subTest(confidence=confidence):
                result = self.policy(confidence)
                self.assertTrue(result["force_review"])
                self.assertEqual(result["reason"], "confidence_missing")

    def test_low_confidence_forces_review(self):
        result = self.policy({"score": 0.4})
        self.assertFalse(result["auto_send_ok"])
        self.assertTrue(result["force_review"])
        self.assertEqual(result["reason"], "low_confidence")

    def test_high_confidence_auto_sends(self):
        result = self.policy({"score": 0.9})
        self.assertTrue(result["auto_send_ok"])
        self.assertFalse(result["force_review"])
        self.assertEqual(result["reason"], "")

    def test_moderate_confidence_is_neither(self):
        result = self.policy({"score": 0.7})
        self.assertFalse(result["auto_send_ok"])
        self.assertFalse(result["force_review"])
        self.assertEqual(result["reason"], "confidence_moderate")

    def test_threshold_boundaries(self):
        # score == force_review_below is NOT below (strict <) -> moderate band
        self.assertEqual(self.policy({"score": 0.55})["reason"], "confidence_moderate")
        # score == auto_send_above IS eligible (>=)
        self.assertTrue(self.policy({"score": 0.85})["auto_send_ok"])

    def test_custom_thresholds_respected(self):
        result = self.policy({"score": 0.6}, confidence_force_review_below=0.65)
        self.assertEqual(result["reason"], "low_confidence")


class ConfidenceSendPolicyProfileTests(unittest.TestCase):
    def test_defaults_present(self):
        defaults = utils._profile_defaults()
        self.assertTrue(defaults["confidence_force_review_enabled"])
        self.assertEqual(defaults["confidence_force_review_below"], 0.55)
        self.assertEqual(defaults["confidence_auto_send_above"], 0.85)

    def test_sanitize_clamps_thresholds(self):
        defaults = utils._profile_defaults()
        cfg = utils._sanitize_profile_values(
            {"confidence_force_review_below": 5, "confidence_auto_send_above": -2}, defaults
        )
        self.assertEqual(cfg["confidence_force_review_below"], 1.0)
        self.assertEqual(cfg["confidence_auto_send_above"], 0.0)

    def test_sanitize_coerces_enabled_to_bool(self):
        defaults = utils._profile_defaults()
        cfg = utils._sanitize_profile_values({"confidence_force_review_enabled": "no"}, defaults)
        self.assertFalse(cfg["confidence_force_review_enabled"])

    def test_validate_accepts_in_range(self):
        utils.validate_profile_settings(
            {"confidence_force_review_below": 0.3, "confidence_auto_send_above": 0.9}
        )

    def test_validate_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"confidence_force_review_below": 1.5})
        with self.assertRaises(ValueError):
            utils.validate_profile_settings({"confidence_auto_send_above": -0.1})


class ConfidenceSendPolicyDraftTests(unittest.TestCase):
    """update_draft_review_fields() must stamp the policy onto every draft."""

    def _draft(self, confidence, gate_reasons=None, final_text="hello there"):
        return {
            "final_text": final_text,
            "raw_text": final_text,
            "confidence": confidence,
            "gate_reasons": gate_reasons or [],
        }

    def test_low_confidence_draft_is_not_auto_send(self):
        cfg = utils._profile_defaults()
        with patch.object(server, "load_profile", return_value=cfg):
            draft = self._draft({"score": 0.2})
            server.update_draft_review_fields(draft)
        self.assertFalse(draft["auto_send_ok"])
        self.assertTrue(draft["force_review"])
        self.assertEqual(draft["force_review_reason"], "low_confidence")

    def test_high_confidence_short_draft_is_auto_send_ok(self):
        cfg = utils._profile_defaults()
        with patch.object(server, "load_profile", return_value=cfg):
            draft = self._draft({"score": 0.95})
            server.update_draft_review_fields(draft)
        self.assertTrue(draft["auto_send_ok"])
        self.assertFalse(draft["force_review"])
        self.assertEqual(draft["force_review_reason"], "")

    def test_disabled_policy_leaves_draft_auto_sendable(self):
        cfg = utils._profile_defaults()
        cfg["confidence_force_review_enabled"] = False
        with patch.object(server, "load_profile", return_value=cfg):
            draft = self._draft({"score": 0.1})
            server.update_draft_review_fields(draft)
        self.assertTrue(draft["auto_send_ok"])
        self.assertFalse(draft["force_review"])


if __name__ == "__main__":
    unittest.main()
