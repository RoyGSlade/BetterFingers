import unittest

from macros import apply_macros


class ApplyMacrosTests(unittest.TestCase):
    DATA = [
        {"trigger": "my address", "expansion": "123 Main St, Springfield"},
        {"trigger": "sign off", "expansion": "Best regards, John"},
        {"trigger": "eta", "expansion": "estimated time of arrival"},
    ]

    def test_expands_multi_word_trigger(self):
        self.assertEqual(
            apply_macros("send it to my address today", self.DATA),
            "send it to 123 Main St, Springfield today",
        )

    def test_case_insensitive_trigger(self):
        self.assertEqual(apply_macros("My Address", self.DATA), "123 Main St, Springfield")

    def test_word_boundary_safe(self):
        # 'my addresses' must not expand; 'beta' must not trigger 'eta'.
        self.assertEqual(apply_macros("my addresses", self.DATA), "my addresses")
        self.assertEqual(apply_macros("the beta test", self.DATA), "the beta test")

    def test_standalone_word_trigger(self):
        self.assertEqual(
            apply_macros("what is the eta", self.DATA),
            "what is the estimated time of arrival",
        )

    def test_longest_trigger_wins(self):
        data = [
            {"trigger": "address", "expansion": "ADDR"},
            {"trigger": "my address", "expansion": "123 Main St"},
        ]
        self.assertEqual(apply_macros("my address", data), "123 Main St")

    def test_no_macros_or_empty(self):
        self.assertEqual(apply_macros("hello", []), "hello")
        self.assertEqual(apply_macros("", self.DATA), "")
        self.assertEqual(apply_macros(None, self.DATA), None)


if __name__ == "__main__":
    unittest.main()
