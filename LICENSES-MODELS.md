# Downloaded Model Licenses

Every model the app can download at runtime, and the license under which we
verified it's safe to redistribute/bundle-by-reference. Only Apache-2.0,
CC0-1.0, or MIT licensed models may appear in a catalog's default entries
(§11 supply-chain discipline). See `model_manager.py`'s `AVAILABLE_MODELS`
and `wake_models.py`'s `AVAILABLE_WAKE_MODELS` for the pinned URL/sha256 for
each entry below.

## Wake word (wake_models.py)

### Shippable — Apache-2.0

| Model | File | License | Source |
|---|---|---|---|
| Melspectrogram feature extractor | `melspectrogram.onnx` | Apache-2.0 | [openWakeWord](https://github.com/dscripka/openWakeWord) v0.5.1 release, re-hosting Google's [TFHub speech_embedding](https://tfhub.dev/google/speech_embedding/1) module (Apache-2.0) |
| Speech embedding model | `embedding_model.onnx` | Apache-2.0 | Same as above |

These two files are the shared, phrase-agnostic feature-extraction backbone
(raw audio → mel spectrogram → 96-dim embedding vector). They contain no
wake-phrase-specific weights and are the only wake-word model files listed
in the default catalog.

### NOT shippable — verified and excluded

openWakeWord's own repository ships six pre-trained wake-phrase classifier
models: `alexa`, `hey_mycroft`, `hey_jarvis`, `hey_rhasspy`, `timer`,
`weather`. Verified directly against the upstream README's "License of
Pre-trained Models" section:

> "All of the included pre-trained models are licensed under the Creative
> Commons Attribution-NonCommercial-ShareAlike 4.0 International license due
> to the inclusion of datasets with unknown or restrictive licensing as part
> of the training data."
> — https://github.com/dscripka/openWakeWord (README, retrieved 2026-07-15)

CC-BY-NC-SA-4.0 is a non-commercial license and fails our Apache-2.0/CC0/MIT
gate. **None of these six models are listed in `AVAILABLE_WAKE_MODELS` or
downloadable through the app.** This includes `hey_jarvis`, which the
original wake-word plan draft had floated as a candidate — it is explicitly
excluded once its real license was checked.

The community model library at openwakeword.com/library may contain
individually differently-licensed models, but its per-model license metadata
could not be verified programmatically (JS-rendered page, no accessible
license field via automated fetch) — nothing from it is listed here without
a verified license text.

### User-imported classifiers

Because the catalog ships zero wake-phrase classifiers, `wake_models.py`
offers a user-import path (`import_wake_model`) that copies a user-supplied
`.onnx` classifier into app data. Imported models are recorded with
`license="user-provided"` and `origin="user-imported"` — they are never
redistributed by this project, and the UI states plainly that their
licensing is the user's own responsibility. They are still verified by
SHA-256 at import time and on every subsequent load (§11), same as any other
on-disk model — that discipline is about integrity, not licensing.

Training a permissively-licensed "hey fingers" classifier from scratch
(Apache-2.0/CC0/MIT-clean, using the Apache-2.0 backbone above) is tracked as
future work, out of scope for the M3 slice.
