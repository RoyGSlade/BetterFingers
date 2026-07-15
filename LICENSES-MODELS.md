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

## Voice cloning (voice_clone_engine.py, M5/M6 U6)

### Shippable — MIT

| Artifact | License | Source |
|---|---|---|
| kanade-tokenizer (code) | MIT | [github.com/frothywater/kanade-tokenizer](https://github.com/frothywater/kanade-tokenizer), README "License" section |
| `frothywater/kanade-12.5hz` checkpoint (weights) | MIT | HF repo card, `license: mit` frontmatter tag, verified 2026-07-15 |

### NOT vendored under our own release — pin-to-upstream instead

| Artifact | License | Why |
|---|---|---|
| WavLM-base-plus pretrained weights (torchaudio's `WAVLM_BASE_PLUS` bundle, the SSL front end kanade's local/global encoders run on) | **CC BY-SA 3.0** | The `microsoft/wavlm-base-plus` HF model card explicitly points to [github.com/microsoft/UniSpeech/blob/main/LICENSE](https://github.com/microsoft/UniSpeech/blob/main/LICENSE) as the weights' license — verified directly, it is Creative Commons Attribution-ShareAlike 3.0 Unported, not MIT. (`microsoft/unilm`'s own repo-root LICENSE *is* MIT, but that covers the training/inference *code*, not this specific weights artifact — the HF card is explicit that the weights carry the UniSpeech CC BY-SA terms.) CC BY-SA fails the Apache-2.0/CC0/MIT-only gate for catalog default entries (§11) — same class of exclusion as the wake-word CC-BY-NC-SA classifiers above. |

Because we cannot redistribute WavLM-base-plus's weights from our own
`clone-runtime-v1` release under our license gate, the clone-runtime
provisioning pins the ORIGINAL upstream-hosted URL (the same one
torchaudio's `WAVLM_BASE_PLUS` bundle itself fetches from) plus our own
computed sha256 — using/running a CC BY-SA model is fine; redistributing our
own re-hosted copy of it is what the gate exists to prevent. Same discipline
as `model_manager.py`'s llama-server binary, which is likewise pinned
straight to its upstream GitHub release rather than re-hosted by us.

**Pinned artifact** (`voice_clone_engine.CLONE_WAVLM_PIN`), verified against
upstream directly (§11):

| Field | Value |
|---|---|
| URL | `https://download.pytorch.org/torchaudio/models/wavlm_base_plus.pth` |
| SHA-256 | `136a3e720c04f2c77bf7a4dc6a3868b14d5a2c145a988114b733cb1a8428be98` |
| Size | 377,604,347 bytes |
| License | CC BY-SA 3.0 Unported (attribution: Microsoft WavLM, [github.com/microsoft/UniSpeech](https://github.com/microsoft/UniSpeech), original paper [Chen et al., "WavLM: Large-Scale Self-Supervised Pre-Training for Full Stack Speech Processing"](https://arxiv.org/abs/2110.13900)) |

Attribution notice (WavLM-base-plus, CC BY-SA 3.0): this weights file is
downloaded at runtime from its original publisher and used for inference
only — it is never redistributed by this project. Derivative model weights
produced by fine-tuning it would need to carry forward the same
Attribution-ShareAlike terms; BetterFingers does not fine-tune or
redistribute WavLM, so this obligation does not extend to the app itself.
