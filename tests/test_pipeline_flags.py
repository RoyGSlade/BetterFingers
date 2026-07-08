import unittest
from unittest.mock import patch

import server


class GetPipelineFlagsTests(unittest.TestCase):
    def test_reads_profile_only_once(self):
        with patch.object(server, "load_profile", return_value={}) as mock_load:
            server.get_pipeline_flags()
            mock_load.assert_called_once()

    def test_defaults_both_on_when_absent(self):
        with patch.object(server, "load_profile", return_value={}):
            flags = server.get_pipeline_flags()
        self.assertEqual(flags, {"voice_commands": True, "macros": True})

    def test_reads_explicit_values(self):
        with patch.object(
            server,
            "load_profile",
            return_value={"voice_commands_enabled": False, "macros_enabled": True},
        ):
            flags = server.get_pipeline_flags()
        self.assertEqual(flags, {"voice_commands": False, "macros": True})

    def test_falls_back_to_enabled_on_load_profile_error(self):
        with patch.object(server, "load_profile", side_effect=RuntimeError("boom")):
            flags = server.get_pipeline_flags()
        self.assertEqual(flags, {"voice_commands": True, "macros": True})

    def test_voice_commands_enabled_delegates(self):
        with patch.object(server, "load_profile", return_value={"voice_commands_enabled": False}):
            self.assertFalse(server.voice_commands_enabled())

    def test_macros_enabled_delegates(self):
        with patch.object(server, "load_profile", return_value={"macros_enabled": False}):
            self.assertFalse(server.macros_enabled())


if __name__ == "__main__":
    unittest.main()
