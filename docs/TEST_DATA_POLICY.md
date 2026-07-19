# Test-Data Policy — synthetic speech-signal fixtures (Phase 2, F2.4)

Governs `tests/fixtures/speech_signals/` — the fixture corpus used to exercise
`backend.services.speech_signals.compute_speech_signals` (F2.1).

## Provenance

Every fixture in this directory is **hand-authored synthetic text**, written
directly by the contributor for this repository. None of it was recorded,
transcribed, or derived from any real person's speech, dictation, voice
memo, or any other captured audio. Sentences are generic office/workplace
phrasing chosen only to exercise a specific timing, pacing, pause, filler,
self-correction, or energy pattern — never to represent an actual utterance
by a real individual.

No audio files are checked in. `compute_speech_signals` only needs segment
timing (`start_s`/`end_s`/`text`) and, optionally, numeric per-window energy
summaries (e.g. RMS) — never a raw waveform — so the fixtures store exactly
that: text and numbers, in JSON. If a future fixture ever needs an actual
`.wav`, it must be synthesized from a checked-in deterministic recipe (e.g.
`numpy`-generated tones/noise with a fixed seed) — real speech recordings of
any person, including project contributors, are never permitted here.

## License / ownership

Fixture content is original text authored for this project and is covered by
this repository's existing license. There is no third-party or scraped
content in this directory.

## Intended use

- Input to `compute_speech_signals` in `tests/test_speech_signal_fixtures.py`
  and any other test/tooling that needs representative timing/energy shapes
  (e.g. F2.7 rescue-prompt construction, I3.1 pipeline wiring).
- Not intended as a corpus for training, benchmarking accuracy against a
  "ground truth" label, or anything requiring realistic acoustic content —
  the energy numbers are illustrative shapes (e.g. "mostly flat," "wide
  swings"), not calibrated measurements.

## Privacy limits

- **No personal data.** No names, emails, phone numbers, addresses, account
  numbers, or any other identifying or sensitive content appears in any
  fixture `text` field. `test_speech_signal_fixtures.py::test_fixtures_contain_no_pii_markers`
  enforces this with pattern checks (email/phone-shaped strings) on every run.
- **No emotion labels.** Fixture text and any assertions against it must not
  encode a claimed emotional state (e.g. "angry," "anxious") — `compute_speech_signals`
  itself is contractually forbidden from inferring emotion (see F2.1's
  docstring), and fixtures must not smuggle that framing in through the back
  door.
- **Evidence stays content-free.** `compute_speech_signals` never echoes raw
  transcript text into its `evidence` field; the fixture corpus's own test
  reaffirms this (`test_signals_never_echo_fixture_text`) so this guarantee
  is checked against real fixture content, not just the synthetic secret used
  in F2.1's own unit tests.

## Fixture schema

Each `<id>.json` file is a flat object:

```json
{
  "id": "quiet",
  "description": "human-readable summary of what this scenario exercises",
  "segments": [{"start_s": 0.0, "end_s": 2.0, "text": "..."}],
  "audio_duration_s": 4.0,
  "energy_windows": [0.01, 0.015, 0.012, 0.01]
}
```

- `id` matches the filename stem and is unique across the corpus.
- `segments` maps 1:1 onto `backend.domain.contracts.TimedSegment(start_s, end_s, text)`
  positional fields (only these three; `avg_logprob`/`no_speech_prob` are not
  needed by `compute_speech_signals` so fixtures omit them).
- `audio_duration_s` and `energy_windows` are optional (`null`/omitted) and
  map directly onto `compute_speech_signals`'s matching keyword arguments.
- Fixtures never carry expected-output values inline; assertions about
  relative/bounded behavior live in the test file next to the scenario they
  check, so the fixture stays a pure input description.

The corpus covers eight scenarios: `quiet`, `fast`, `slow`, `paused`, `empty`,
`noisy`, `filler_heavy`, `self_correcting` — chosen to span every axis
`compute_speech_signals` derives a signal from (pace, pause structure, energy
variation, filler density, self-correction density, and the all-zero/no-input
case).

## Regeneration and checksum rules

`manifest.json` in the same directory records a `sha256` checksum for every
other file in the directory. `test_speech_signal_fixtures.py::test_manifest_checksums_match`
fails if any fixture file's content drifts from its recorded checksum without
the manifest being updated in the same change — this makes fixture edits
visible in review instead of silently changing test inputs.

To add or edit a fixture:

1. Edit or add the `<id>.json` file following the schema above.
2. Regenerate `manifest.json`:

   ```bash
   python3 - <<'EOF'
   import hashlib, json, pathlib

   d = pathlib.Path("tests/fixtures/speech_signals")
   entries = {
       f.name: hashlib.sha256(f.read_bytes()).hexdigest()
       for f in sorted(d.glob("*.json"))
       if f.name != "manifest.json"
   }
   manifest = {
       "schema_version": 1,
       "generated_by": "tests/fixtures/speech_signals/ - see docs/TEST_DATA_POLICY.md for regeneration rules",
       "checksum_algorithm": "sha256",
       "files": entries,
   }
   (d / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
   EOF
   ```

3. Run `python3 -m pytest -q tests/test_speech_signal_fixtures.py` and confirm
   it passes before committing.
