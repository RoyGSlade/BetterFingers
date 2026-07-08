"""Phase 3: sentence-aware chunking for long LLM inputs."""

import unittest

from llm_engine import split_text_for_llm_chunks


class SplitTextForLLMChunksTest(unittest.TestCase):
    def test_empty_text_returns_empty(self):
        self.assertEqual(split_text_for_llm_chunks("", 100), [])
        self.assertEqual(split_text_for_llm_chunks("   \n  ", 100), [])

    def test_short_text_single_chunk(self):
        chunks = split_text_for_llm_chunks("Hello world. This is short.", 100)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["context"], "")
        self.assertIn("Hello world.", chunks[0]["text"])

    def test_splits_on_sentence_boundaries(self):
        # Ten 5-word sentences; target 12 words → each chunk holds ~2 sentences
        # and must end on a sentence terminator, never mid-sentence.
        text = " ".join(f"Sentence number {i} ends here." for i in range(10))
        chunks = split_text_for_llm_chunks(text, 12, overlap_words=0)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertTrue(c["text"].rstrip().endswith("."), c["text"])

    def test_no_word_is_lost_or_duplicated(self):
        text = " ".join(f"Word{i} filler here now." for i in range(40))
        chunks = split_text_for_llm_chunks(text, 15, overlap_words=10)
        rejoined = " ".join(c["text"] for c in chunks)
        # Partition property: concatenating chunk text reproduces every token in
        # order (overlap lives in "context", not "text", so nothing duplicates).
        self.assertEqual(rejoined.split(), text.split())

    def test_chunks_respect_target_unless_single_long_sentence(self):
        text = " ".join(f"This is sentence {i} of the batch." for i in range(12))
        target = 16
        chunks = split_text_for_llm_chunks(text, target, overlap_words=0)
        for c in chunks:
            wc = len(c["text"].split())
            is_single_sentence = c["text"].count(".") <= 1
            self.assertTrue(wc <= target or is_single_sentence, (wc, c["text"]))

    def test_single_oversized_sentence_becomes_one_chunk(self):
        long_sentence = "word " * 300 + "end."
        chunks = split_text_for_llm_chunks(long_sentence, 50)
        self.assertEqual(len(chunks), 1)
        self.assertGreater(len(chunks[0]["text"].split()), 50)

    def test_overlap_context_is_previous_tail(self):
        text = " ".join(f"Alpha{i} beta gamma delta epsilon." for i in range(20))
        chunks = split_text_for_llm_chunks(text, 10, overlap_words=4)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(chunks[0]["context"], "")
        for i in range(1, len(chunks)):
            expected = " ".join(chunks[i - 1]["text"].split()[-4:])
            self.assertEqual(chunks[i]["context"], expected)

    def test_prefers_paragraph_boundaries(self):
        text = "First para sentence one. First para sentence two.\n\nSecond para only."
        chunks = split_text_for_llm_chunks(text, 100, overlap_words=0)
        # Under a large target everything fits in one chunk, but paragraph text
        # is preserved in order.
        rejoined = " ".join(c["text"] for c in chunks)
        self.assertEqual(rejoined.split(), text.split())


if __name__ == "__main__":
    unittest.main()
