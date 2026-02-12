import unittest
from unittest.mock import Mock, patch

from main import App


class MainReviewRewriteTests(unittest.TestCase):
    def _app_with_draft(self):
        app = App()
        app.llm_enabled = True
        app.organic_formatting_enabled = True
        app.output_token_limit = 1100
        app.draft_queue = [{"id": 1, "status": "review_pending", "final_text": "hello"}]
        return app

    def test_format_rewrite_action(self):
        app = self._app_with_draft()
        result = app.on_preview_rewrite(1, "i  think ,this is fine!!", "format")
        self.assertTrue(result.get("ok"))
        self.assertIn("I think, this is fine!", result.get("text", ""))

    def test_rewrite_returns_error_when_llm_disabled(self):
        app = self._app_with_draft()
        app.llm_enabled = False
        result = app.on_preview_rewrite(1, "hello there", "expand")
        self.assertFalse(result.get("ok"))

    @patch("main.get_engine")
    def test_rewrite_uses_llm_engine(self, get_engine):
        app = self._app_with_draft()
        engine = Mock()
        engine.rewrite_text.return_value = "rewritten text"
        get_engine.return_value = engine

        result = app.on_preview_rewrite(1, "hello there", "rephrase")

        self.assertTrue(result.get("ok"))
        self.assertEqual(result.get("text"), "rewritten text")
        engine.rewrite_text.assert_called_once()


if __name__ == "__main__":
    unittest.main()
