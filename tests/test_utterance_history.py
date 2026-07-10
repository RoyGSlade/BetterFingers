import unittest

from utterance_history import Utterance, UtteranceHistory


def _utt(text, ts=0.0):
    return Utterance(
        raw_transcript=text,
        final_text=text,
        emitted_length=len(text),
        target_draft_id="draft-1",
        timestamp=ts,
        injected=True,
    )


class UtteranceHistoryTests(unittest.TestCase):
    def test_empty_history_returns_none(self):
        history = UtteranceHistory()
        self.assertIsNone(history.last())
        self.assertIsNone(history.pop_last())

    def test_record_and_last(self):
        history = UtteranceHistory()
        history.record(_utt("hello"))
        history.record(_utt("world"))
        self.assertEqual(history.last().raw_transcript, "world")
        self.assertEqual(len(history), 2)

    def test_pop_last_removes_and_returns_most_recent(self):
        history = UtteranceHistory()
        history.record(_utt("first"))
        history.record(_utt("second"))
        popped = history.pop_last()
        self.assertEqual(popped.raw_transcript, "second")
        self.assertEqual(history.last().raw_transcript, "first")
        self.assertEqual(len(history), 1)

    def test_capacity_drops_oldest(self):
        history = UtteranceHistory(capacity=3)
        for i in range(5):
            history.record(_utt(str(i)))
        self.assertEqual(len(history), 3)
        self.assertEqual([u.raw_transcript for u in history.all()], ["2", "3", "4"])

    def test_clear(self):
        history = UtteranceHistory()
        history.record(_utt("hello"))
        history.clear()
        self.assertEqual(len(history), 0)
        self.assertIsNone(history.last())

    def test_all_returns_copy_not_live_reference(self):
        history = UtteranceHistory()
        history.record(_utt("hello"))
        snapshot = history.all()
        history.record(_utt("world"))
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(history), 2)


if __name__ == "__main__":
    unittest.main()
