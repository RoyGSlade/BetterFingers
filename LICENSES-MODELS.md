# Model and Runtime Licenses

Source inventory checked 2026-10-04 against worktree base `33b7cf4` and the
primary upstream pages linked below; the bundled `base.en` entries were updated
the same day against base `49aa64f`. This records licenses, packaging intent,
and unresolved provenance; it is **not legal clearance or proof that an
installer contains the required notices**. No model/runtime was loaded for this
inventory. SHA-256 values referenced here are code pins, not recomputed hashes,
except the four `base.en` digests in `backend/stt/bundled_manifest.json`, which
were hashed from a local snapshot of the pinned revision.

"Bundled" means the build collects a dependency into the frozen backend;
"downloaded" means app code obtains it separately at runtime. The actual release
manifest still needs comparison. `app/scripts/build-backend.js`
(`collectAllPackages`, `hiddenImports`, `dataSources`) collects runtime packages,
including eSpeak NG. It also stages exactly one speech model into the installer:
Systran `base.en` at a pinned revision, verified against
`backend/stt/bundled_manifest.json` before PyInstaller runs and added at
`_internal/bundled_models/base.en/` (`bundledModelTarget`). No other speech, LLM,
TTS or wake weights are bundled; every other model below is downloaded at runtime.

The Apache-2.0/CC0-1.0/MIT catalog gate is project policy, explicitly enforced
for wake models in `wake_models.py::ALLOWED_LICENSES`. It does not make every
dependency permissive or imply that other licenses forbid commercial use.
GPL and NVIDIA proprietary runtime terms require separate handling.
Integrity hashes establish identity, not licensing rights.

### Local source evidence

Anchors below refer to this worktree at base `33b7cf4`, except the
`build-backend.js`, `build-installer.yml` and bundled-`base.en` rows, which refer
to base `49aa64f` plus the BF-U3 build wiring. Symbols remain the primary
identifiers after file reorganization; recheck line numbers when porting.

| Claim | Local file:line / symbol |
|---|---|
| Speech catalog and repo mapping | `backend/stt/transcriber.py:179` — `SUPPORTED_MODEL_SIZES`; `backend/stt/transcriber.py:216` — `_repo_id_for_model` |
| Speech acquisition / loader | `backend/stt/transcriber.py:329` — `download_whisper_model`; `backend/stt/transcriber.py:418` — `Transcriber` |
| Gemma revisions and six artifacts | `backend/models/model_manager.py:34` — `_GEMMA4_E2B_REVISION` and following revision constants; `backend/models/model_manager.py:38` — `AVAILABLE_MODELS` |
| llama.cpp archive pins / selection | `backend/models/model_manager.py:137` — `RUNTIME_ARTIFACT_SHA256`; `backend/models/model_manager.py:157` — `_LLAMA_RELEASE`; `backend/models/model_manager.py:245` — `resolve_runtime_spec` |
| Native/ONNX TTS acquisition and integrity behavior | `backend/tts/tts_engine.py:830` — `ReviewTTSEngine._load_kokoro_backend`; `backend/tts/tts_engine.py:881` — `_load_kokoro_onnx_backend`; `backend/tts/tts_engine.py:993` — `_ensure_artifact` |
| Frozen data and runtime package collection | `app/scripts/build-backend.js:19` — `dataSources`; `app/scripts/build-backend.js:62` — `collectAllPackages`; `app/scripts/build-backend.js:68` — `hiddenImports` |
| Bundled `base.en` pin, staging, source selection, shipping | `backend/stt/bundled_manifest.json:5` — pinned revision and per-file SHA-256; `backend/stt/bundle_staging.py:30` — `stage_bundled_model`; `app/scripts/build-backend.js:201` — `resolveModelBundlePlan`; `app/scripts/build-backend.js:314` — `planBackendBuild`; `backend/stt/bundled_models.py:107` — `bundled_model_dir` (runtime locator) |
| Windows speech/TTS runtime versions | `requirements-win.lock:331` — CTranslate2; `requirements-win.lock:372` — loader; `requirements-win.lock:384` — faster-whisper; `requirements-win.lock:481` — Kokoro ONNX; `requirements-win.lock:544` — ONNX Runtime; `requirements-win.lock:578` — phonemizer-fork |
| Linux CPU installer lock / native fallback versions | `.github/workflows/build-installer.yml:483` — lock installation; `requirements-linux-cpu.lock:661` — Kokoro; `requirements-linux-cpu.lock:780` — Misaki; `requirements-linux-cpu.lock:2005` — CPU PyTorch |
| Wake release, two hashes and license gate | `wake_models.py:30` — `WAKE_BACKBONE_RELEASE`; `wake_models.py:36` — `AVAILABLE_WAKE_MODELS`; `wake_models.py:59` — `ALLOWED_LICENSES`; `wake_models.py:297` — `import_wake_model` |
| Kanade pins / vocoder delegation | `backend/tts/voice_clone_engine.py:69` — `KANADE_TOKENIZER_REPO` and following pin constants; `backend/tts/voice_clone_engine.py:173` — `_ensure_loaded` |
| Optional clone runtime / WavLM pin / refused provisioning | `backend/tts/voice_clone_engine.py:306` — `CLONE_RUNTIME_CATALOG`; `backend/tts/voice_clone_engine.py:332` — `CLONE_WAVLM_PIN`; `backend/tts/voice_clone_engine.py:462` — `provision_clone_runtime` |

## Speech-to-text (backend/stt/transcriber.py)

### Default catalog — MIT model cards

`SUPPORTED_MODEL_SIZES` and `_repo_id_for_model` cover all seven rows.
`base.en` is **bundled in the installer** at a pinned revision (see the next
subsection). The other six are **downloaded at runtime**, including
tokenizer/configuration files. The runtime downloader and model loader supply
no Hugging Face commit or artifact digest pin: source IDs are exact, downloaded
revisions are not. Only the installer's copy of `base.en` is pinned and
hash-verified, at build time and again at load: the runtime loader
(`Transcriber._resolve_model_source`) prefers a verified bundle for `base.en`
and loads it local-only, so an installed build never downloads `base.en`. Other
sizes, and development runs without a bundle, load from the local Hub cache only;
only the explicit Download route can fetch, and that download remains unpinned.

| Model | Exact source repo / revision used | License / primary source |
|---|---|---|
| `tiny.en` | `Systran/faster-whisper-tiny.en`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-whisper-tiny.en) |
| `base.en` | `Systran/faster-whisper-base.en`, **bundled** at pinned `3d3d5dee26484f91867d81cb899cfcf72b96be6c`; the runtime downloader for this ID is unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-whisper-base.en) |
| `small.en` | `Systran/faster-whisper-small.en`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-whisper-small.en) |
| `medium.en` | `Systran/faster-whisper-medium.en`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-whisper-medium.en) |
| `large-v3` | `Systran/faster-whisper-large-v3`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-whisper-large-v3) |
| `distil-medium.en` | `Systran/faster-distil-whisper-medium.en`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-distil-whisper-medium.en) |
| `distil-large-v3` | `Systran/faster-distil-whisper-large-v3`, unpinned | MIT — [conversion card](https://huggingface.co/Systran/faster-distil-whisper-large-v3) |

The first five cards identify OpenAI Whisper conversions, the last two
Distil-Whisper conversions. Preserve original and conversion copyright/MIT
permission notices with redistributed copies. MIT permits commercial use and
redistribution subject to its notice requirement; these cards impose no
non-commercial restriction. **UNVERIFIED** for the six downloaded rows: exact
fetched revisions and complete artifact-level notices. Next check: freeze
selected repo commits, record all fetched filenames/digests, and retain their
licenses/attributions before bundling or mirroring them. For `base.en` the
revision and per-file digests are now frozen (next subsection); its notice text
is still open.

Arbitrary slash-containing repo IDs are also accepted by `_repo_id_for_model`.
Those are user-selected sources, not blanket approval under this inventory;
their weights, tokenizer and license require separate verification.

### Pinned installer speech payload — base.en

The owner approved bundling `Systran/faster-whisper-base.en` revision
`3d3d5dee26484f91867d81cb899cfcf72b96be6c` in the installer on 2026-10-04.
The [public model metadata](https://huggingface.co/api/models/Systran/faster-whisper-base.en)
declares MIT and identified this pin as the current `main` commit that day.
The weights are OpenAI Whisper `base.en` converted to CTranslate2 format by
SYSTRAN; both the upstream OpenAI Whisper release and the SYSTRAN conversion
are MIT. `backend/stt/bundled_manifest.json` records the pinned source URL and
size/SHA-256 for `config.json`, `model.bin`, `tokenizer.json` and
`vocabulary.txt`. All four files were hashed locally from a cached snapshot, and
`model.bin`'s SHA-256 was cross-checked against the
[upstream LFS oid](https://huggingface.co/api/models/Systran/faster-whisper-base.en/tree/main).
The complete model payload is 147,769,510 bytes (147.769510 decimal MB).

Packaging uses the build-only, explicit-source `tools.bundle_models` step
(`backend/stt/bundle_staging.py`). The build takes the bytes from a local
snapshot (`BETTERFINGERS_BUNDLED_MODEL_SOURCE`) or, only when
`BETTERFINGERS_ALLOW_MODEL_DOWNLOAD=1`, from a pinned-revision fetch; every file
is verified against the manifest before PyInstaller runs and again inside the
frozen backend afterwards. The release workflow sets the download switch for
both installers. This inventory file is itself added to the frozen backend
(`_internal/LICENSES-MODELS.md`) as the provenance record.

**Notices:** the four manifest files carry no license file, so the OpenAI
Whisper (`Copyright (c) 2022 OpenAI`) and SYSTRAN faster-whisper
(`Copyright (c) 2023 SYSTRAN`) MIT copyright and permission notices were copied
verbatim from the upstream LICENSE files on 2026-10-04 into
`licenses/bundled-base.en-NOTICE.txt`, which the build ships as required data
(`_internal/bundled-base.en-NOTICE.txt`, next to this inventory; the build fails
without it). **UNVERIFIED:** the signed installer's actual file manifest has not
been inventoried yet, and none of this proves inference readiness.

### Bundled speech runtime

| Artifact | Exact version/source | License | Distribution / notices |
|---|---|---|---|
| faster-whisper | `1.2.1`, SYSTRAN, Windows/Linux locks | MIT — [versioned LICENSE](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/LICENSE) | Bundled via `collectAllPackages`; retain SYSTRAN copyright/MIT text. |
| CTranslate2 | `4.8.1`, OpenNMT, Windows/Linux locks | MIT — [versioned LICENSE](https://github.com/OpenNMT/CTranslate2/blob/v4.8.1/LICENSE) | Bundled via hidden import; retain copyright/permission and wheel third-party notices. |

**UNVERIFIED:** complete native-library contents/notices of the packaged
CTranslate2 wheel. MIT does not cover separately supplied CUDA/cuDNN libraries.
`requirements-win.lock` has no NVIDIA runtime wheels; Linux installer CI uses
`requirements-linux-cpu.lock`. The alternate `requirements-linux.lock` includes
NVIDIA CUDA 13 family wheels, including cuDNN; this is not evidence that they
are in the CPU installer. Next check: compare the actual backend manifest and
chosen lock to vendor license files; inventory each additional GPU component.

## LLM cleanup (backend/models/model_manager.py)

### Gemma 4 GGUF — Apache-2.0 cards, one unresolved exact pin

All six `AVAILABLE_MODELS` entries are **downloaded at runtime** from Unsloth.
The code pins repo commit, SHA-256 and byte count. Filenames/case follow code.
Use this family's cards, not older Gemma or Unsloth tooling license assumptions.

| Model | File | Exact repo / pinned revision | License / primary source |
|---|---|---|---|
| `gemma-4-e2b-q4` | `gemma-4-E2B-it-Q4_K_M.gguf` | `unsloth/gemma-4-E2B-it-GGUF` @ `739965d73654c0ead8020786aa998fc813070087` | Current card Apache-2.0; **UNVERIFIED exact pin** — [current card](https://huggingface.co/unsloth/gemma-4-E2B-it-GGUF) |
| `gemma-4-e2b-q8` | `gemma-4-E2B-it-Q8_0.gguf` | Same E2B repo / revision | Same status |
| `gemma-4-e4b-q4` | `gemma-4-E4B-it-Q4_K_M.gguf` | `unsloth/gemma-4-E4B-it-GGUF` @ `0720adb23527c2cd5ea01d1db067cd960327fdac` | Apache-2.0 — [pinned card](https://huggingface.co/unsloth/gemma-4-E4B-it-GGUF/blob/0720adb23527c2cd5ea01d1db067cd960327fdac/README.md) |
| `gemma-4-e4b-q8` | `gemma-4-E4B-it-Q8_0.gguf` | Same E4B repo / revision | Apache-2.0 — same pinned card |
| `gemma-4-12b-q4` | `gemma-4-12b-it-Q4_K_M.gguf` | `unsloth/gemma-4-12b-it-GGUF` @ `d997c805aafe035a8024f961c6e1afd6b30d79a5` | Apache-2.0 — [pinned card](https://huggingface.co/unsloth/gemma-4-12b-it-GGUF/blob/d997c805aafe035a8024f961c6e1afd6b30d79a5/README.md) |
| `gemma-4-12b-q8` | `gemma-4-12b-it-Q8_0.gguf` | Same 12b repo / revision | Apache-2.0 — same pinned card |

The cards link Google's [Apache-2.0 license](https://ai.google.dev/gemma/docs/gemma_4_license).
For redistribution preserve license/copyright/attribution, any supplied NOTICE,
and modification notices for changed files. Commercial use is permitted by
Apache-2.0, with its patent/trademark conditions. Attribute Google DeepMind and
Unsloth's conversion; retain actual notices rather than only README links.

**UNVERIFIED:** E2B pinned README could not be retrieved, although the current
primary card says Apache-2.0. Next check: retrieve README/LICENSE/NOTICE text
at that exact commit before declaring its pinned artifacts verified.
**UNVERIFIED:** complete accompanying notice set for all six GGUFs; next check
repo trees at each pin. Weight bytes were not fetched.

### llama.cpp runtime builds and NVIDIA DLLs

`_LLAMA_RELEASE`, `RUNTIME_ARTIFACT_SHA256` and `resolve_runtime_spec` select
these archives, all **downloaded at runtime**, not installer data:

| Artifact | Exact source | License / primary source |
|---|---|---|
| Windows NVIDIA server | `ggml-org/llama.cpp` release `b9548`, `llama-b9548-bin-win-cuda-12.4-x64.zip` | llama.cpp MIT — [b9548 LICENSE](https://github.com/ggml-org/llama.cpp/blob/b9548/LICENSE); separately licensed native dependencies |
| Windows NVIDIA support DLL archive | Same release, `cudart-llama-bin-win-cuda-12.4-x64.zip` | NVIDIA proprietary CUDA terms for CUDA runtime/cuBLAS/cuBLASLt; not MIT |
| Windows Vulkan/CPU server | Same release, `llama-b9548-bin-win-vulkan-x64.zip` | llama.cpp MIT; native third-party notices also apply |
| Linux Vulkan/CPU server | Same release, `llama-b9548-bin-ubuntu-vulkan-x64.tar.gz` | llama.cpp MIT; native third-party notices also apply |

Retain llama.cpp copyright/permission text. NVIDIA's
[CUDA 12.4.1 EULA](https://docs.nvidia.com/cuda/archive/12.4.1/eula/index.html)
is a primary reference for the archives' CUDA 12.4 family. Attachment A lists
Windows runtime and BLAS DLLs as distributable subject to distribution
requirements/restrictions, including additional app functionality, access
through the app, compatible distribution terms, NVIDIA GPU scope, and vendor
rights. Preserve applicable NVIDIA and embedded third-party notices.
Direct upstream hosting does not remove redistribution obligations.

**UNVERIFIED:** exact DLL filenames/toolkit patch, Vulkan/native dependency
provenance, and full notice payload inside the hashed archives. Next check:
inspect an authorized existing archive/installed manifest without execution,
map every native binary to its exact vendor version/license, and compare its
redistribution list/notices. The 12.4.1 EULA does not prove that every
unidentified DLL in a 12.4-named archive is redistributable.

## Text-to-speech (backend/tts/tts_engine.py)

### Downloaded Kokoro weights and voices

`ReviewTTSEngine._load_kokoro_onnx_backend` downloads a chosen ONNX variant
and voice pack from `thewh1teagle/kokoro-onnx` release `model-files-v1.0`:

| Artifact | Exact source / pin | License / primary source |
|---|---|---|
| FP32 weights | `kokoro-v1.0.onnx`, release tag `model-files-v1.0` | Apache-2.0 model declaration — [publisher package](https://pypi.org/project/kokoro-onnx/0.5.0/), [model-files release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0) |
| FP16 weights | `kokoro-v1.0.fp16.onnx`, same tag | Same model declaration |
| INT8 weights | `kokoro-v1.0.int8.onnx`, same tag | Same model declaration |
| Voice embeddings | `voices-v1.0.bin`, same tag | Kokoro repo Apache-2.0 declaration; **UNVERIFIED exact converted pack provenance/notices** — [original model](https://huggingface.co/hexgrad/Kokoro-82M), [voice list](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md) |

These are **downloaded**, not bundled weights. The release documents conversion
provenance; the package distinguishes MIT code from Apache-2.0 weights.
Preserve hexgrad/Kokoro and conversion attribution, Apache license/NOTICE and
modification notices with redistributed artifacts. The upstream voice list
identifies CC BY source credits for some Japanese voices and `ff_siwis`;
preserve those credits if included. Do not infer that this pack contains every
current upstream voice.

**UNVERIFIED:** asset digests, original model commit, exact voice membership and
inherited credits. `_ensure_artifact` accepts an existing nonempty file and
downloads by URL without an artifact SHA-256 pin. Next check: freeze all four
asset digests and conversion/voice manifests with upstream license/NOTICE;
map included voices to upstream credits. The Apache model card states no
non-commercial restriction; source attribution still needs accounting.

### Bundled TTS runtime and GPL phonemization

| Artifact | Exact source/version used | License / primary source | Distribution / notices |
|---|---|---|---|
| `kokoro-onnx` | `0.5.0`, thewh1teagle | MIT — [pinned package](https://pypi.org/project/kokoro-onnx/0.5.0/), [source LICENSE](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE) | Bundled via `collectAllPackages`; retain code copyright/MIT text. |
| ONNX Runtime | `onnxruntime==1.27.0`, Microsoft | MIT — [versioned LICENSE](https://github.com/microsoft/onnxruntime/blob/v1.27.0/LICENSE) | Backend dependency for TTS/wake; retain Microsoft/MIT and native third-party notices; packaged file set **UNVERIFIED**. |
| `espeakng_loader` Python wrapper | `0.2.4`, thewh1teagle | MIT wrapper — [source LICENSE](https://github.com/thewh1teagle/espeakng-loader/blob/main/LICENSE), [pinned package](https://pypi.org/project/espeakng-loader/0.2.4/) | Explicitly bundled via `collectAllPackages`, including binaries/data. Retain wrapper MIT notice; exact 0.2.4 source-to-wheel notice match **UNVERIFIED**. |
| eSpeak NG native library and language/phoneme data carried by loader | Native version/patch not separately pinned; platform wheel `espeakng-loader==0.2.4` | **GPL-3.0-or-later** — [upstream license information](https://github.com/espeak-ng/espeak-ng/blob/master/README.md#license-information), [COPYING](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING); Windows `getopt.c` BSD-2-Clause | Bundled; wrapper MIT does not cover it. Preserve GPL/copyright and applicable BSD notices; establish corresponding source and applicable distribution obligations. |
| `phonemizer-fork` | `3.3.2`, thewh1teagle's bootphon fork | **GPL-3.0-or-later** — [exact package license](https://pypi.org/project/phonemizer-fork/3.3.2/) | Locked TTS dependency; verify frozen inclusion. Preserve Mathieu Bernard copyright/GPL and matching corresponding source. |

**UNVERIFIED release compliance:** exact eSpeak NG source revision, patches,
build scripts/data and corresponding source for distributed platform wheels;
GPL notices/source delivery in the installer; scope of GPL obligations for the
combined packaged program. Next check: map the actual 0.2.4 wheel's native
files to its build/source commit and establish compliant source/notice
distribution before release, or separately decide an implementation change.
This documentation does not resolve the combined-work question.
GPL permits commercial distribution under its conditions; describing this
whole stack as "MIT/Apache only" would be inaccurate.

### Optional native Kokoro and platform voices

`ReviewTTSEngine._load_kokoro_backend` can fall back to `kokoro.KPipeline`.
Linux locks include `kokoro==0.9.4` for Python below 3.13 and
`misaki[en]==0.9.4`; Windows does not include native Kokoro.
Kokoro code is Apache-2.0 ([pinned package](https://pypi.org/project/kokoro/0.9.4/),
[source LICENSE](https://github.com/hexgrad/kokoro/blob/main/LICENSE)).
Misaki code is also Apache-2.0, independently declared by its
[0.9.4 package](https://pypi.org/project/misaki/0.9.4/); retain its license,
copyright/NOTICE and third-party data credits.
The app passes no native model repo/revision to `KPipeline`.
**UNVERIFIED:** exact transitive model, voice, G2P dictionary and any spaCy model
downloads/notices for that version; complete Misaki dictionary/notice set.
Next check: inspect pinned package loader/dependency code and existing manifest,
pin each fetched artifact, and inventory its own license. Kokoro's license
does not cover Misaki/dictionary artifacts by association. Native installer
inclusion also needs confirmation: it is lazy-imported, not explicitly
`collect-all`. Windows SAPI uses already-installed OS/user voices; this code
does not bundle/download them and their terms follow their suppliers.

## Wake word (backend/wake/wake_models.py)

### Catalog backbones — Apache-2.0

| Model | File | License | Source |
|---|---|---|---|
| Melspectrogram feature extractor | `melspectrogram.onnx` | Apache-2.0 | [openWakeWord v0.5.1](https://github.com/dscripka/openWakeWord/blob/v0.5.1/README.md), reimplementation of Google's TFHub speech_embedding backbone |
| Speech embedding model | `embedding_model.onnx` | Apache-2.0 | Same source; README architecture section explicitly identifies backbone license |

These phrase-agnostic feature extractors are **downloaded at runtime**, not
bundled. Exact release base:
`https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/`.
`AVAILABLE_WAKE_MODELS` pins SHA-256 for melspectrogram
`ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f`
and embedding
`70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f`.
The [code LICENSE](https://github.com/dscripka/openWakeWord/blob/v0.5.1/LICENSE)
is Apache-2.0 too. Preserve Google/openWakeWord attribution, license/NOTICE and
conversion/change notices. Commercial use is permitted under those terms.
**UNVERIFIED:** exact release-asset notice/conversion file set; next check asset
provenance and retained upstream notices at v0.5.1.

### NOT shippable — verified and excluded

The upstream phrase classifiers `alexa`, `hey_mycroft`, `hey_jarvis`,
`hey_rhasspy`, `timer` and `weather` are CC-BY-NC-SA-4.0.
The [v0.5.1 README License section](https://github.com/dscripka/openWakeWord/blob/v0.5.1/README.md#license)
distinguishes those restricted pretrained models from the Apache backbone.
They fail project policy's permissive gate and carry a non-commercial
restriction. **None is in `AVAILABLE_WAKE_MODELS` or downloaded by its catalog.**
Community models require individual license verification; none is approved by
association with openWakeWord.

### User-imported and locally trained classifiers

`import_wake_model` copies user-supplied ONNX files into app data and records
`license="user-provided"`, `origin="user-imported"`; these are not redistributed
by this project. Integrity verification does not verify legal permission.
The runtime also recognizes `self-trained` artifacts; provenance of recordings,
training sources and any redistribution must be established separately.
A permissively licensed "hey fingers" default classifier remains future work.

## Voice cloning (backend/tts/voice_clone_engine.py, M5/M6 U6)

### Kanade — MIT declarations, optional downloaded weights

| Artifact | License | Exact source |
|---|---|---|
| kanade-tokenizer code | MIT declaration | `frothywater/kanade-tokenizer` @ `961f20bf892c59f391d0b6c5f7b88e70ed919b99`; [pinned README](https://raw.githubusercontent.com/frothywater/kanade-tokenizer/961f20bf892c59f391d0b6c5f7b88e70ed919b99/README.md) |
| `frothywater/kanade-12.5hz` weights | Current card MIT; **UNVERIFIED exact pin license** | `bfc4a8a753ea71394cf98e752ca68c7fbc847f0d`; [current card](https://huggingface.co/frothywater/kanade-12.5hz), pinned README fetch failed |

Kanade code is optional in the developer environment or intended preinstalled
in the separately downloaded clone runtime, not an explicit default bundle
dependency. Weights download via `from_pretrained` with the code revision
above. Preserve original copyright/MIT permission with copies; those
declarations impose no non-commercial restriction.
**UNVERIFIED:** full code copyright/license text at its commit and checkpoint
license/notice at its exact pin. Next check those text files before publishing
the clone runtime; a current model card is not historical proof.

### Vocoder and optional side-runtime dependency closure

| Artifact | Exact source/pin used | License / primary source | Distribution / next check |
|---|---|---|---|
| Vocos checkpoint/config | Kanade's pinned `src/kanade_tokenizer/util.py::load_vocoder` calls `charactr/vocos-mel-24khz` without revision | Current model card MIT — [card](https://huggingface.co/charactr/vocos-mel-24khz); [code LICENSE](https://github.com/gemelo-ai/vocos/blob/main/LICENSE) | Optional downloaded weights; retain MIT copyright/permission. **UNVERIFIED** exact checkpoint/license pin; freeze commit/digests. |
| HiFT alternative, if model config requests `hift` | Same loader calls `FunAudioLLM/CosyVoice2-0.5B`, `hift.pt`, without revision | Current card Apache-2.0 — [card](https://huggingface.co/FunAudioLLM/CosyVoice2-0.5B) | Conditional download, not claimed used by selected 12.5hz model. **UNVERIFIED** pinned config/HiFT notices; inspect config then pin/license reachable files. |
| Windows clone runtime | `RoyGSlade/BetterFingers` tag `clone-runtime-v1`, `clone-runtime-windows-x86_64.tar.gz` | **UNVERIFIED** unpublished artifact manifest/license set | Optional path, SHA-256 `None`; provisioning refuses it. |
| Linux clone runtime | Same tag, `clone-runtime-linux-x86_64.tar.gz` | **UNVERIFIED**, same status | Same refusal; no verified distributable runtime in catalog. |

The [exact pinned Kanade loader](https://raw.githubusercontent.com/frothywater/kanade-tokenizer/961f20bf892c59f391d0b6c5f7b88e70ed919b99/src/kanade_tokenizer/util.py)
establishes the extra downloads. App code passes `model.config.vocoder_name` or
defaults to `vocos`; the current 12.5hz card says Vocos. Its pinned config
could not be fetched, so HiFT reachability is unresolved. Do not substitute a
newer checkpoint silently.

The side-runtime plan includes standalone Python 3.12, CPU PyTorch,
TorchAudio, Kanade and dependencies. **UNVERIFIED:** exact Python build,
torch/torchaudio/Vocos versions, archive hashes and full native dependency
licenses. Next check before producing those archives: record immutable
source/build/wheel manifests, notices and source obligations for every packaged
component. [PyTorch](https://github.com/pytorch/pytorch/blob/v2.13.0/LICENSE)
uses BSD-style terms plus third-party notices;
[TorchAudio](https://github.com/pytorch/audio/blob/main/LICENSE) uses BSD-2-Clause.
These are license references, not verified versions of future archives.
Linux native fallback locks `torch==2.13.0+cpu`; that does not pin the clone
runtime. Retain the actual build's Python/PyTorch/TorchAudio/Vocos/native notices.

### NOT vendored under our own release — pin-to-upstream instead

| Artifact | License | Source / policy |
|---|---|---|
| WavLM-base-plus pretrained weights | **CC BY-SA 3.0 Unported** | [Microsoft model card](https://huggingface.co/microsoft/wavlm-base-plus) explicitly links [UniSpeech LICENSE](https://github.com/microsoft/UniSpeech/blob/main/LICENSE). Its code's MIT license does not cover these weights. Excluded from our rehosting under project policy. |

`CLONE_WAVLM_PIN` identifies the original publisher download;
`_provision_wavlm_pin` downloads it separately into the optional runtime cache.
CC BY-SA is not a non-commercial license: credit/ShareAlike and other conditions
matter when copies/adaptations are shared. Upstream hosting is not a general
exemption from license requirements.

**Pinned artifact** (`CLONE_WAVLM_PIN`), recorded in code; bytes not fetched:

| Field | Value |
|---|---|
| URL | `https://download.pytorch.org/torchaudio/models/wavlm_base_plus.pth` |
| SHA-256 | `136a3e720c04f2c77bf7a4dc6a3868b14d5a2c145a988114b733cb1a8428be98` |
| Size | 377,604,347 bytes (code pin) |
| License / credit | CC BY-SA 3.0; Microsoft WavLM, [UniSpeech](https://github.com/microsoft/UniSpeech), [Chen et al., WavLM paper](https://arxiv.org/abs/2110.13900) |

If sharing copies/adaptations, retain appropriate credit/license link, identify
changes and apply ShareAlike to adaptations as required by
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/).
The app does not fine-tune/rehost WavLM in this source; this inventory does not
decide the legal scope of an adaptation or combination.
**UNVERIFIED:** publisher provenance tying this exact TorchAudio-format
`.pth` to the licensed checkpoint, and retained optional-runtime attribution.
Next check that mapping and preserve applicable notice text.

User reference recordings/embeddings are local user-generated artifacts;
runtime MIT/Apache licenses do not grant permission to use another person's voice.

## How this list is kept current

On catalog, runtime URL/hash, package lock or build-collection changes, update
the matching row from the **actual pinned** upstream license/card/NOTICE.
Reconcile built installer and downloaded-runtime manifests, retain notices
and any required corresponding source, and cover transitive model/voice/
dictionary downloads. A mutable current card cannot verify an older artifact.
Resolve `UNVERIFIED` only through the named check. This inventory does not itself
deliver license texts, source archives or vendor permissions for a release.
