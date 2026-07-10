import unittest

from voice_preview import preview

OVERLAY_CTX = {"review_overlay_open": True}


class PreviewTests(unittest.TestCase):
    def test_app_command_only(self):
        result = preview("send it", OVERLAY_CTX)
        self.assertEqual(result["text"], "send it")
        self.assertIsNotNone(result["app_command"])
        self.assertEqual(result["app_command"]["action"], "send")
        self.assertTrue(result["app_command"]["requires_confirmation"])
        self.assertIsNone(result["edit_command"])

    def test_edit_command_only(self):
        result = preview("scratch that")
        self.assertIsNone(result["app_command"])
        self.assertIsNotNone(result["edit_command"])
        self.assertEqual(result["edit_command"]["action"], "scratch_that")

    def test_neither_recognized(self):
        result = preview("just plain dictation")
        self.assertIsNone(result["app_command"])
        self.assertIsNone(result["edit_command"])

    def test_app_command_requires_context_but_edit_command_does_not(self):
        # "send it" alone (no context) resolves to no app command; a plain
        # editing phrase still resolves regardless of context.
        result = preview("send it")
        self.assertIsNone(result["app_command"])

        result = preview("delete last word")
        self.assertIsNotNone(result["edit_command"])

    def test_switch_persona_includes_target(self):
        result = preview("switch to formal", OVERLAY_CTX)
        self.assertEqual(result["app_command"]["action"], "switch_persona")
        self.assertEqual(result["app_command"]["target"], "formal")

    def test_replace_command_includes_args(self):
        result = preview("replace foo with bar")
        self.assertEqual(result["edit_command"]["args"], {"old": "foo", "new": "bar"})


if __name__ == "__main__":
    unittest.main()
