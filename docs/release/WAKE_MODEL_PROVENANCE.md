# Wake model provenance

**Wave 8A, package G.** Audited 2026-07-28. Machine-readable sidecar:
[`wake_model_provenance.json`](wake_model_provenance.json) — kept in sync with
`wake_models.AVAILABLE_WAKE_MODELS` by `tests/test_wake_model_provenance.py`,
so this document cannot drift from the code without a red test.

Scope: every wake-word model artifact this repository ships, downloads,
generates, or accepts from the user. The general model-license finding it
builds on is [`LICENSES-MODELS.md`](../../LICENSES-MODELS.md); this document is
the release-gate view — what is bundled, under what terms, and what is
deliberately absent.

## Headline

**Nothing with incompatible terms is bundled.** No wake model binary is
tracked in this repository at all — not one `.onnx`, `.tflite`, `.npz`,
`.pth`, or `.safetensors`. Every wake model file arrives at runtime by one of
three paths, each with its own provenance record:

| Path | License | Redistributed by us |
|---|---|---|
| Downloaded from a pinned upstream URL | Apache-2.0 | No — the pin points at the original publisher |
| Imported by the user | `user-provided` | No |
| Trained locally on this machine | `self-trained` | No |

## Catalog: the shared backbone

Two files, both Apache-2.0, both phrase-agnostic (raw audio → mel spectrogram
→ 96-dim embedding). Neither contains wake-phrase-specific weights.

| Model | File | SHA-256 | Bytes | License |
|---|---|---|---|---|
| Melspectrogram feature extractor | `melspectrogram.onnx` | `ba2b0e0f…eb176f` | 1,087,958 | Apache-2.0 |
| Speech embedding model | `embedding_model.onnx` | `70d16429…3075c1f` | 1,326,578 | Apache-2.0 |

Source: [openWakeWord](https://github.com/dscripka/openWakeWord) v0.5.1
release assets, which re-host Google's
[TFHub `speech_embedding`](https://tfhub.dev/google/speech_embedding/1) module
(also Apache-2.0).

The app downloads these from the pinned upstream release URL rather than
re-hosting copies. Each is verified by SHA-256 at download time **and again on
every load** (`wake_models.verify_wake_model_file`), so a file swapped in later
is never silently trusted; a digest mismatch quarantines the file.

## Deliberately absent: wake-phrase classifiers

**The catalog ships zero wake-phrase classifiers, and that is a license
outcome, not an oversight.**

openWakeWord's own repository ships six pre-trained classifiers — `alexa`,
`hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`, `weather`. Its README's
"License of Pre-trained Models" section states they are **CC BY-NC-SA 4.0**,
"due to the inclusion of datasets with unknown or restrictive licensing as part
of the training data" (verified directly, retrieved 2026-07-15).

CC BY-NC-SA is non-commercial and fails the Apache-2.0 / CC0-1.0 / MIT gate.
None of the six are listed in `AVAILABLE_WAKE_MODELS` or reachable through the
app — including `hey_jarvis`, which an early wake-word plan draft had floated
before its real license was checked.

The community library at `openwakeword.com/library` may contain individually
differently-licensed models, but its per-model license metadata could not be
verified programmatically (JS-rendered page, no accessible license field).
Nothing from it is listed without verified license text.

### What that means for the product

A fresh install has a working feature pipeline and **no phrase model**. That
is a setup step, not a broken feature, and Wave 8A gives it its own status
word: `audio_status.wake_status()` returns `classifier_missing` (distinct from
`unavailable`), so the UI can say "train or import a phrase" instead of "wake
word is broken".

## User-supplied models show their provenance

Both dynamic classes are recorded in one manifest
(`<user data>/wake_models/imported_models.json`) with the fields the UI needs
to be honest about where a model came from:

| Class | `origin` | `license` | Provenance shown |
|---|---|---|---|
| User-imported `.onnx` | `user-imported` | `user-provided` | Yes — the app states plainly that licensing is the user's own responsibility |
| Locally trained `.npz` head | `trained` | `self-trained` | Yes — no third-party weights are incorporated |

Both are SHA-256 verified at registration and on every subsequent load; a
digest mismatch quarantines the file and removes its manifest entry. That
discipline is about integrity, not licensing — it applies equally to a model
whose license is entirely the user's business.

Locally-trained heads sit on top of the Apache-2.0 backbone and are fitted to
the user's own recordings plus Kokoro-synthesized renderings. Kokoro was chosen
over the Piper TTS that openWakeWord uses for the same purpose precisely
because Piper is GPL.

## Findings

| ID | Severity | Status | Finding |
|---|---|---|---|
| WMP-1 | info | clean | Zero wake model binaries are tracked in the repository. Nothing unlicensed is bundled. |
| WMP-2 | info | clean | The catalog ships zero classifiers by design; the missing-classifier state now has its own honest status word. |
| WMP-3 | low | open | `wake_models.ALLOWED_LICENSES` is enforced by a test over the checked-in catalog, never at runtime. A catalog entry added without running the suite would not be refused by the code itself. Suggested fix: assert the gate inside `list_wake_models()` / the download path. |
| WMP-4 | low | open | Kokoro's weights license is asserted in source comments (`wake_trainer.py`, `wake_training_service.py`) but was **not** independently verified in this audit. It affects the provenance story for locally-trained models; it does not affect anything this repository redistributes. Verification belongs to the TTS lane. |

Both open findings are low severity and neither blocks Gate 8: neither one can
cause an incompatibly-licensed artifact to be bundled today, because nothing is
bundled today.

## How this stays true

`tests/test_wake_model_provenance.py` asserts that:

1. every catalog entry in `wake_models.AVAILABLE_WAKE_MODELS` appears in the
   JSON sidecar with a matching SHA-256, size, license, and source URL, and
   vice versa;
2. every recorded license is inside the allowed set;
3. no wake model binary has appeared in the working tree.

A new catalog entry therefore fails the suite until its provenance is recorded
here.
