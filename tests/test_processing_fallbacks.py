import unittest
from unittest.mock import Mock, patch

from main import App


class ProcessingFallbackTests(unittest.TestCase):
    def test_resolve_final_text_returns_transcript_when_llm_disabled(self):
        app = App()
        app.llm_enabled = False

        with patch("main.get_engine") as get_engine:
            result = app._resolve_final_text("  rotate back post  ")

        self.assertEqual(result, "rotate back post")
        get_engine.assert_not_called()

    def test_resolve_final_text_falls_back_when_llm_raises(self):
        app = App()
        app.llm_enabled = True
        app.current_preset = "True Janitor"
        app.true_gen = False

        with patch("main.get_engine") as get_engine:
            engine = Mock()
            engine.process_fast_lane.side_effect = RuntimeError("boom")
            get_engine.return_value = engine
            result = app._resolve_final_text("clear callout")

        self.assertEqual(result, "clear callout")

    def test_resolve_final_text_handles_non_string_llm_output(self):
        app = App()
        app.llm_enabled = True
        app.current_preset = "True Janitor"
        app.true_gen = False

        with patch("main.get_engine") as get_engine:
            engine = Mock()
            engine.process_fast_lane.return_value = {"message": "hello"}
            get_engine.return_value = engine
            result = app._resolve_final_text("input")

        self.assertTrue(isinstance(result, str))
        self.assertEqual(result, "input")

    def test_resolve_final_text_rejects_assistant_style_reply_in_true_janitor(self):
        app = App()
        app.llm_enabled = True
        app.current_preset = "True Janitor"
        app.true_gen = True

        source = "Share what you offer and how you'll use your page."
        assistant_style = (
            "I offer grammar, spelling, and punctuation correction, filler removal, "
            "and adherence to contextual rules. I will use this page to fulfill this task."
        )

        with patch("main.get_engine") as get_engine:
            engine = Mock()
            engine.process_fast_lane.return_value = assistant_style
            get_engine.return_value = engine
            result = app._resolve_final_text(source)

        self.assertEqual(result, source)

    def test_resolve_final_text_does_not_apply_janitor_guard_to_other_personas(self):
        app = App()
        app.llm_enabled = True
        app.current_preset = "Formal"
        app.true_gen = True

        source = "Share what you offer and how you'll use your page."
        model_output = "I offer concise business writing support."

        with patch("main.get_engine") as get_engine:
            engine = Mock()
            engine.process_fast_lane.return_value = model_output
            get_engine.return_value = engine
            result = app._resolve_final_text(source)

        self.assertEqual(result, model_output)

    def test_split_text_by_token_limit_chunks_long_text(self):
        app = App()
        words = [f"w{i}" for i in range(1100)]
        text = " ".join(words)

        chunks = app._split_text_by_token_limit(text, 900)

        self.assertEqual(len(chunks), 2)
        self.assertLessEqual(app._token_count(chunks[0]), 900)
        self.assertLessEqual(app._token_count(chunks[1]), 900)
        self.assertEqual(app._token_count(" ".join(chunks)), 1100)

    def test_route_output_queues_when_review_window_is_busy(self):
        app = App()
        app.send_mode = "review_first"
        app.preview_overlay = Mock()
        app.preview_overlay.enabled = True
        app.preview_overlay.is_review_active.return_value = True
        app.notification_overlay = Mock()
        app.notification_overlay_enabled = True
        app._safe_after = lambda _delay, callback: callback()

        app._route_output("hello", "raw", "manual")

        self.assertEqual(len(app.draft_queue), 1)
        self.assertEqual(app.draft_queue[0]["status"], "review_pending")
        self.assertEqual(app.pipeline_state, "queued")
        app.notification_overlay.show_message.assert_called_once()

    def test_route_output_shows_next_review_when_available(self):
        app = App()
        app.send_mode = "review_first"
        app.preview_overlay = Mock()
        app.preview_overlay.enabled = True
        app.preview_overlay.is_review_active.return_value = False
        app._safe_after = lambda _delay, callback: callback()

        app._route_output("hello", "raw", "manual")

        app.preview_overlay.show_review.assert_called_once_with(
            1,
            "hello",
            token_count=1,
            token_limit=1100,
        )


if __name__ == "__main__":
    unittest.main()
