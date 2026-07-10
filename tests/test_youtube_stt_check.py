"""Caption parsing for the YouTube STT accuracy check (§6.1 / C9).

Only the pure VTT-parsing logic is tested here (no network, no model): flatten a
WebVTT to plain reference text, window it by timestamp, strip inline tags and
non-spoken stage-directions, and drop the duplicate lines auto-captions repeat.
"""

import importlib.util
import os
import tempfile
import unittest

_TOOL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "youtube_stt_check.py")
_spec = importlib.util.spec_from_file_location("youtube_stt_check", _TOOL)
ysc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ysc)


SAMPLE_VTT = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000
Good morning. How are you?

00:00:03.000 --> 00:00:05.000
(Laughter)

00:00:05.000 --> 00:00:07.000
It's been <c>great</c>, hasn't it?

00:02:00.000 --> 00:02:02.000
This is way past the window.
"""


class VttReferenceTests(unittest.TestCase):
    def _write(self, text):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".vtt", delete=False, encoding="utf-8")
        tmp.write(text)
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name))
        return tmp.name

    def test_windows_by_timestamp(self):
        path = self._write(SAMPLE_VTT)
        ref = ysc.vtt_reference(path, max_start_s=10.0)
        self.assertIn("Good morning", ref)
        self.assertIn("hasn't it?", ref)
        self.assertNotIn("past the window", ref)  # cue at 2:00 excluded

    def test_strips_tags_and_annotations(self):
        path = self._write(SAMPLE_VTT)
        ref = ysc.vtt_reference(path, max_start_s=10.0)
        self.assertNotIn("<c>", ref)
        self.assertIn("great", ref)          # tag stripped, word kept
        self.assertNotIn("Laughter", ref)    # (Laughter) stage-direction removed
        self.assertNotIn("(", ref)

    def test_headers_and_cue_numbers_excluded(self):
        path = self._write(SAMPLE_VTT)
        ref = ysc.vtt_reference(path, max_start_s=10.0)
        for token in ("WEBVTT", "Kind:", "Language:"):
            self.assertNotIn(token, ref)

    def test_drops_consecutive_duplicate_lines(self):
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:02.000\nhello world\n\n"
            "00:00:02.000 --> 00:00:03.000\nhello world\n\n"  # auto-caption repeat
            "00:00:03.000 --> 00:00:04.000\nnext line\n"
        )
        ref = ysc.vtt_reference(self._write(vtt), max_start_s=10.0)
        self.assertEqual(ref, "hello world next line")

    def test_clean_caption_line_helper(self):
        self.assertEqual(ysc._clean_caption_line("[Music] hello (Applause)").strip(), "hello")
        self.assertEqual(ysc._clean_caption_line("a <00:00:01.000><c>b</c> c"), "a b c")


if __name__ == "__main__":
    unittest.main()
