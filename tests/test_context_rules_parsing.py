import os
import tempfile
import unittest

from llm_engine import _load_context_rules


class ContextRulesParsingTests(unittest.TestCase):
    def test_load_context_rules_reads_valid_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "context_rules.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    'context_rules:\n'
                    '  "meal/me": "If context implies drink/water, use Mio."\n'
                    '  "its/it\'s": "Fix apostrophes."\n'
                )

            rules = _load_context_rules(path)
            self.assertIn("meal/me", rules)
            self.assertIn("its/it's", rules)

    def test_load_context_rules_recovers_malformed_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "context_rules.yaml")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    'context_rules:\n'
                    '  "meal": "If context implies drink/water, use Mio."\n'
                    '  "gender":"if talking about modes or cleaning, use janitor"\n'
                )

            rules = _load_context_rules(path)
            self.assertEqual(
                rules.get("gender"),
                "if talking about modes or cleaning, use janitor",
            )


if __name__ == "__main__":
    unittest.main()
