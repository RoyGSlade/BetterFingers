# Golden audio regression fixtures

This directory holds real-audio regression fixtures for the STT pipeline. Each
fixture is a pair:

```
<name>.wav    # 16 kHz mono PCM utterance
<name>.txt    # expected reference transcript (plain UTF-8, one utterance)
```

The harness transcribes each `.wav` with the configured STT model and scores the
hypothesis against the matching `.txt` using word-error-rate from
[`wer.py`](../../wer.py):

```python
from wer import compare_transcripts
result = compare_transcripts(reference_text, hypothesis_text)
assert result["wer"] <= THRESHOLD   # e.g. 0.10 for a clean model
```

`compare_transcripts` normalizes case, punctuation and whitespace before
aligning, so references should be written naturally (no need to lowercase or
strip punctuation yourself).

## Status

- ✅ **WER scoring core** — `wer.py`, pure/stdlib, fully unit-tested
  (`tests/test_wer.py`). No `jiwer`/`numpy` dependency.
- ⏳ **Deferred** — checked-in `.wav` fixtures and a CI job that runs them per
  configured STT model. This requires real recorded audio plus a model download
  in CI; add fixtures here and a `test_golden_audio.py` runner that skips
  gracefully when no STT model is available.

## Adding a fixture (once audio is available)

1. Record/trim a short utterance to 16 kHz mono WAV, name it `something.wav`.
2. Write the exact expected transcript to `something.txt`.
3. The (future) `test_golden_audio.py` runner will discover the pair
   automatically and assert WER is under the per-model threshold.
