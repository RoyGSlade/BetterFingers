import unittest
from unittest.mock import Mock, patch

from main import App


class MainTokenCapRuntimeTests(unittest.TestCase):
    def _base_app(self):
        app = App()
        app.injector = Mock()
        app.transcriber = None
        app.tts_engine = None
        app.overlay = None
        app.notification_overlay = None
        app.preview_overlay = None
        return app

    @patch("main.load_profile")
    def test_apply_runtime_settings_clamps_token_limit_low(self, load_profile):
        load_profile.return_value = {"output_token_limit": 100, "organic_formatting_enabled": True}
        app = self._base_app()

        app._apply_runtime_settings("Default")

        self.assertEqual(app.output_token_limit, 900)
        self.assertTrue(app.organic_formatting_enabled)

    @patch("main.load_profile")
    def test_apply_runtime_settings_clamps_token_limit_high(self, load_profile):
        load_profile.return_value = {"output_token_limit": 5000, "organic_formatting_enabled": False}
        app = self._base_app()

        app._apply_runtime_settings("Default")

        self.assertEqual(app.output_token_limit, 1200)
        self.assertFalse(app.organic_formatting_enabled)


if __name__ == "__main__":
    unittest.main()
