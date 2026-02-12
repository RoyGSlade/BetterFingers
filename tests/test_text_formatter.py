import unittest

from text_formatter import TextFormatter, format_text


class _Seg:
    def __init__(self, start, end, text):
        self.start = start
        self.end = end
        self.text = text


class TextFormatterTests(unittest.TestCase):
    def test_empty_segments_returns_empty_string(self):
        self.assertEqual(TextFormatter.format_segments([]), "")

    def test_short_gap_uses_space(self):
        segments = [
            _Seg(0.0, 0.5, "Hello"),
            _Seg(0.6, 1.0, "world"),
        ]
        self.assertEqual(TextFormatter.format_segments(segments, paragraph_threshold=1.2), "Hello world")

    def test_long_gap_creates_paragraph_break(self):
        segments = [
            _Seg(0.0, 0.5, "Alpha"),
            _Seg(2.0, 2.5, "Bravo"),
        ]
        self.assertEqual(TextFormatter.format_segments(segments, paragraph_threshold=1.2), "Alpha\n\nBravo")

    def test_accepts_dict_segments(self):
        segments = [
            {"start": 0.0, "end": 0.3, "text": "One"},
            {"start": 0.35, "end": 0.8, "text": "Two"},
        ]
        self.assertEqual(TextFormatter.format_segments(segments, paragraph_threshold=1.2), "One Two")

    def test_handles_missing_and_invalid_timing_fields(self):
        segments = [
            {"text": "Hello", "end": "x"},
            {"text": "world", "start": None, "end": "n/a"},
        ]
        self.assertEqual(TextFormatter.format_segments(segments), "Hello world")

    def test_format_text_polishes_spacing_and_pronouns(self):
        raw = "i  think ,this is fine!!"
        self.assertEqual(format_text(raw), "I think, this is fine!")

    def test_format_text_strips_simple_disfluency_and_repeated_words(self):
        raw = "um this is is a test"
        self.assertEqual(format_text(raw), "this is a test")


if __name__ == "__main__":
    unittest.main()
