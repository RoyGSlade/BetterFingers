import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from betterfingers_env import load_local_env


class BetterFingersEnvTests(unittest.TestCase):
    def test_load_local_env_reads_simple_values_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env.local").write_text(
                "HF_TOKEN=hf_test\n"
                "EXISTING=from_file\n"
                "# ignored\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"EXISTING": "from_env"}, clear=True):
                loaded = load_local_env(tmp)
                self.assertEqual(os.environ["HF_TOKEN"], "hf_test")
                self.assertEqual(os.environ["EXISTING"], "from_env")

            self.assertEqual(loaded, {"HF_TOKEN": "hf_test"})


if __name__ == "__main__":
    unittest.main()
