# STT engine seam: faster-whisper default, optional whisper.cpp Vulkan

BF-H7; research only; 2026-10-04. Repository baseline **76141f4** in `codex/h7-stt-engine-seam`. **V** means source or metadata read; **I** means a proposed design, estimate or consequence; **U** means unmeasured/unverified. No binaries/models were downloaded, compiled, launched or loaded. The director's speed spike is **U** here.

**I — Recommendation:** retain faster-whisper as the default; add one engine boundary under the existing Transcriber, then qualify a separately supervised Vulkan implementation. A faster transcript is useful only if draft preservation, cancellation, dictionary terms, timestamps and review protection survive. The smallest first qualification uses already-local `base.en`, final-pass dictation, and mandatory review; streaming and automatic engine selection follow separately.

## 1. Verified baseline and scope corrections

- **V** The Windows lock pins CTranslate2 **4.8.1** and faster-whisper **1.2.1** (`requirements-win.lock:331`, `requirements-win.lock:384`). BetterFingers nevertheless constructs only `device="cuda"`/`"cpu"`, with float16/int8 respectively (`backend/stt/transcriber.py:590`, `backend/stt/transcriber.py:658`). The brief's 4.7.0 context is history, not this dependency pin. [CTranslate2 v4.7.0](https://github.com/OpenNMT/CTranslate2/releases/tag/v4.7.0) introduced ROCm HIP support; **U** the claimed Windows HIP SDK mismatch was not independently reproduced. It does not establish Intel support or justify changing this task into a CT2 installation experiment.
- **V** Normal BetterFingers decoding passes **beam_size**, and **hotwords** when dictionary terms exist (`backend/stt/transcriber.py:885`). The CUDA probe additionally passes `without_timestamps=True` (`backend/stt/transcriber.py:697`). This baseline does **not** explicitly pass VAD parameters, initial_prompt, temperature, word_timestamps or language. [faster-whisper 1.2.1, `WhisperModel.transcribe`](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) supplies their inherited defaults: VAD off, word timestamps off, prompt/language unset, temperature sequence 0 through 1 in 0.2 steps, previous-text conditioning on. These are not the differently configured `BatchedInferencePipeline` defaults.
- **V** The app consumes segment text/start/end/avg_logprob/no_speech_prob. Its `TimedSegment` has exactly those five fields (`backend/domain/contracts.py:14`). Compression ratio and word probabilities are **not direct BetterFingers downstream consumers** in the searched `backend/` and `server.py`; compression-based fallback still affects upstream decoding. Do not invent a missing app-level word-confidence filter.
- **V** STT inventory/download/delete live in `backend/stt/transcriber.py:180`, `:232`, `:283`, `:330`, rather than `model_manager.py`. The latter manages LLM models and llama-server runtime artifacts (`backend/models/model_manager.py:137`, `:245`, `:1527`). Its supply-chain pattern is reusable; its model catalog is not already a whisper.cpp registry.
- **V** Upstream tag **v1.9.4** resolves to `927cfce34f31707e17f2bff35c349632fb9e2c3a`; release metadata gives 2026-09-11 UTC and no uploaded binary assets. Binary release **b5130** points at the same commit. Its x64 Windows assets are CPU, BLAS and cuBLAS; it also includes ARM64 CPU/OpenCL-Adreno/CUDA artifacts. None is named Windows Vulkan. This is a bounded release inventory, not a claim about every third-party build. [v1.9.4 metadata](https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/v1.9.4), [b5130 metadata](https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/b5130), [release workflow](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/.github/workflows/release.yml).

## 2. Dependency inventory

All source locations in this table are **V** for baseline 76141f4. The engine requirements in the final column are **I** design constraints derived from those consumers. They are not implementation claims.

| Dependency | Repository evidence | What the engine boundary must supply/preserve |
|---|---|---|
| Imported concrete engine and HF cache | `backend/stt/transcriber.py:10`, `:11`, `:436` | Keep heavy imports inside the faster-whisper implementation; engine-owned, resolved local artifact paths. |
| Load/preference/config | `backend/stt/transcriber.py:514`, `:529`, `:562` | Separate requested model/device from actual loaded artifact/device; profile reload must not pretend a load succeeded. |
| CUDA compute/CPU compute | `backend/stt/transcriber.py:590`, `:658`, `:665` | Device/backend/precision facts; ggml quantization is not CT2's compute_type. |
| CPU thread policy | `backend/stt/transcriber.py:110`, `:138`, `:659`, `:866` | Apply chosen threads at engine construction; keep the override and load-aware cap, but remeasure its suitability for Vulkan/ggml. |
| CUDA DLL availability | `backend/stt/cuda_runtime.py:74`, `backend/stt/transcriber.py:588` | Adapter-specific library initialization; Vulkan must not call the CT2 CUDA helper or advertise cuDNN requirements. |
| Load-time inference probe | `backend/stt/transcriber.py:628`, `:694` | Construction and actual decode readiness are different states; a successful child process launch/health is insufficient. |
| Process-wide CUDA failure memo | `backend/stt/transcriber.py:78`, `:83`, `:87`, `:579` | Retain existing CT2 behavior; a new failure cache must distinguish engine, runtime build, adapter and failure class. |
| Model lock and lazy iteration | `backend/stt/transcriber.py:890`, `:896`, `:899` | Entire decode/result materialization remains under the inference lease; no model switch while consuming a response. |
| Bounded same-audio CPU retry | `backend/stt/transcriber.py:857`, `:907`, `:932` | One qualified fallback attempt; no repeated GPU crash/reload loop and no retry-induced acquisition. |
| Beam policy | `backend/stt/transcriber.py:885` | Beam 1 below two seconds, beam 5 otherwise; preserve policy, separately evaluate implementation semantics. |
| Dictionary bias | `backend/stores/dictionary.py:104`, `server.py:961`, `server.py:2260`, `backend/stt/transcriber.py:888` | Explicit bias terms and support level. Multiword terms matter because post-correction handles only single-word terms (`backend/stores/dictionary.py:118`). |
| Inherited decoding settings | `backend/stt/transcriber.py:886`, `:899` | Record VAD/prompt/language/temperature/timestamp defaults explicitly in the adapter; omit unsupported options rather than silently mislabel them. |
| Audio shape/duration | `backend/stt/transcriber.py:884`, `:1016`, `:1021` | 16 kHz mono float32 and duration in seconds; validate framing without introducing an unnecessary disk-audio copy. |
| Segment formatting | `backend/stt/text_formatter.py:121`, `backend/stt/transcriber.py:1034` | Normalized start/end/text; preserve 1.2-second paragraph-gap formatting. |
| Hallucination rejection | `backend/stt/transcriber.py:151`, `:1037` | Same engine-independent text guard; rejected text and structured segments must both disappear. |
| Confidence aggregation | `backend/stt/transcriber.py:971`, `:990`, `:997` | Finite avg_logprob and no_speech_prob with provenance, plus engine-specific calibration status. Current score is duration-weighted exp(logprob) multiplied by the worst silence penalty. |
| Review gating | `backend/output/send_policy.py:16`, `:35`, `:52`, `:64`, `backend/config/utils.py:848` | Keep missing confidence conservative. Existing 0.55/0.85 thresholds cannot be assumed portable. |
| Structured/public results | `backend/stt/transcriber.py:1064`, `backend/domain/contracts.py:14`, `:23` | One decode returns legacy text/confidence plus normalized segments; preserve callers and JSON field names. |
| Speech signals and pause timing | `backend/services/speech_signals.py:60`, `:94`, `server.py:2281` | Original-audio timeline; misaligned timestamps alter pause ratios and later cleanup signals. |
| Incremental batch cutter | `backend/stt/streaming_transcriber.py:31`, `:143`, `:198`, `:230`, `:260` | Existing ordered batch callback can stay; transport errors must raise, poison the session and retain the full-pass fallback. Empty speech and infrastructure failure must remain distinct. |
| Streaming lease/client lifecycle | `server.py:964`, `server.py:2266`, `backend/stt/streaming_transcriber.py:286` | No dangling in-flight request after cancel/wipe; preserve single-flight ownership and privacy discard. |
| Residency/admission/unload | `backend/stt/transcriber.py:36`, `:741`, `:838`, `server.py:682`, `server.py:3079`, `backend/runtime/model_runtime_coordinator.py:192`, `:204`, `:336` | Include child RSS and GPU/shared-memory use in the ledger; model_loaded is not merely a Python object truth test. |
| STT catalog/HF snapshots | `backend/stt/transcriber.py:217`, `:232`, `:283`, `:330`, `:709` | Engine-qualified format/revision/hash/readiness/install/delete records; retain existing Systran cache support. |
| Model HTTP surface | `backend/api/routes/models.py:71`, `:216`, `:229`, `:237`, `:247`, `:264` | Existing model_size/prefer_gpu alone cannot identify format/adapter; add compatible engine/artifact metadata before sharing IDs. The current test endpoint checks construction, not real inference. |
| Hardware/recommendations | `backend/models/hardware_report.py:96`, `:126`, `:394`, `backend/models/model_recommender.py:20`, `:187` | Llama-server enumeration and hardware tier are not proof whisper.cpp supports/uses a specific adapter or model. Recommend only qualified engine/model/device tuples. |
| Runtime/doctor/support diagnostics | `backend/stt/transcriber.py:498`, `server.py:841`, `server.py:890`, `backend/api/routes/diagnostics.py:85`, `server.py:3974` | Existing status sanitizer permits only cuda/cpu and float16/int8; extend it deliberately for Vulkan/ggml, adapter ID, runtime build, model hash, construction/probe/decode states and privacy-safe errors. |
| Child supervision precedent | `backend/llm/llm_engine.py:1824`, `:2171`, `:2188`, `:2281` | Reuse principles: hidden Windows process, bounded startup, retained process ownership, redacted stderr and targeted shutdown. Do not reuse the LLM singleton, PID/port or kill-all behavior for STT. |
| Hash-pinned runtime/archives | `backend/models/model_manager.py:137`, `:986`, `:1149`, `:1677` | Pinned artifact digest, bounded validated extraction, staged promotion and launch-time verification; separate namespace from llama-server. |
| Frozen packaging/privacy wipe | `app/scripts/build-backend.js:35`, `:38`, `backend/privacy/data_paths.py:321` | Keep faster-whisper/CT2 in default build; include new runtime/model notices and ensure new app-owned model/runtime paths participate in privacy inventory. |

### Tests that pin the seam

**V** These tests were read, not rerun for this documentation-only card:

| Test source | Behaviors to retain / supplement (**I**) |
|---|---|
| `tests/test_stt_load_policy.py:300`, `:365`, `:448`, `:471` | Load-time decode probe, CPU threads, CUDA release/failure memo, one bounded fallback. Keep CT2-specific cases; add independent Vulkan supervisor cases. |
| `tests/test_cuda_runtime.py:30`, `:47`, `:56` | CUDA PATH helper idempotence/missing-library behavior remains CT2-only. |
| `tests/test_transcriber_device_status.py:39`, `:53` | Preferred GPU differs from active backend; reset status on unload/reload. |
| `tests/test_transcriber_lifecycle.py:53`, `:110`, `:164`, `:208`, `:255` | Distil repo mapping, admission, lazy inference recovery, actual probe state and legacy acquisition behavior. Reconcile acquisition cases with H2 instead of restoring implicit downloads. |
| `tests/test_transcriber_confidence.py:44`, `:57`, `:88` | Score provenance, valid zero logprob, streaming confidence reaching the draft gate. |
| `tests/test_transcriber_hallucination.py:10`, `tests/test_transcriber_structured.py:100`, `:217` | Rejection removes text and segments; combined result decodes once. |
| `tests/test_streaming_transcriber.py:136`, `:166`, `:178`, `:217`, `:237` | Batch order, failure/full-pass recovery, abort/discard, weighted confidence and malformed score rejection. |
| `tests/test_server_settings_models.py:153`, `tests/test_profile_whisper_models.py:10`, `tests/test_model_recommender.py:46` | Model routes, persisted model identity, tier recommendations; preserve default-engine compatibility. |

## 3. Verified upstream equivalence matrix

**V** Entries are from tag v1.9.4, not current master or an OpenAI-compatible API assumption. `S` below identifies [`examples/server/server.cpp`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/server/server.cpp), particularly `get_req_parameters`, `whisper_params_parse`, inference serialization and route registration. `H` identifies [`include/whisper.h`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/include/whisper.h). `W` identifies [`src/whisper.cpp`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/src/whisper.cpp). The [server README](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/server/README.md) documents the multipart transport and startup flags.

| BetterFingers need | Upstream source/symbol and equivalent (**V**) | Consequence / adapter rule (**I**) |
|---|---|---|
| Encoded audio request | Server README: `/inference`, multipart `file`; [`examples/common-whisper.cpp`, `read_audio_data`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/common-whisper.cpp) accepts memory bytes. | Encode bounded in-memory mono 16 kHz WAV; no ffmpeg dependency or temporary transcript/audio file needed. |
| Normalized detailed output | S: `response_format=verbose_json`. | Request explicitly; plain json cannot populate the segment contract. |
| Beam size | S/get_req_parameters: `beam_size`, `best_of`. | Map the short-audio policy; greedy/beam strategy and sampling behavior need comparison fixtures. |
| Thread count | Server README: `--threads`, `--processors`; S has no multipart thread override. | Choose once per child launch; processors stays 1 unless separately measured. |
| GPU/CPU/adapter | S/whisper_params_parse: `--device`, `--no-gpu`; H/whisper_context_params: `use_gpu`, `gpu_device`. | Startup/context selection, not per-request toggling. Verify actual inference, not just requested device. |
| Precision/compute_type | H/context and W/model loader: ggml model tensor types; no CT2 compute_type equivalent. | Report model quantization plus execution backend; do not rename q5_0 to int8. |
| VAD enable/threshold | S/get_req_parameters: `vad`, `vad_threshold`. | Preserve baseline off; enabling it is a separate decode-policy change. |
| VAD timing/padding | S/get_req_parameters: `vad_min_speech_duration_ms`, `vad_min_silence_duration_ms`, `vad_max_speech_duration_s`, `vad_speech_pad_ms`, `vad_samples_overlap`. | Map units explicitly; validate boundaries and original-audio timestamps. |
| VAD model artifact | S/startup: `--vad-model`; H/full params: `vad_model_path`. | No multipart vad_model path. Need a separately verified local ggml VAD artifact before VAD can be offered. |
| Initial prompt | S/get_req_parameters: `prompt`, `carry_initial_prompt`; H/full params: `initial_prompt`. | Optional bias text, not instructions to a cleanup model. Keep sensitive terms out of logs. |
| Dedicated hotwords | S/get_req_parameters: no `hotwords`. H supplies prompt tokens, not an HTTP hotword option. | Prompt-based bias is approximate; dictionary recognition/multiword names need separate acceptance. |
| Temperature fallback | S/get_req_parameters: `temperature`, `temperature_inc`, `logprob_thold`, `entropy_thold`, `no_speech_thold`; README: `--no-fallback`. | An increment schedule is not an arbitrary temperature tuple; entropy is not compression ratio. |
| Language/translation | S/get_req_parameters: `language`, `detect_language`, `translate`; verbose fields `language`, `detected_language_probability`. | Pass the desired policy explicitly; don't inherit English for multilingual BF models. |
| Previous-text conditioning | H/full params: `no_context`; S defaults true, no multipart toggle. | Baseline faster-whisper conditions on previous text. A pinned server patch or deliberate documented policy difference is needed for exact control. |
| Segment boundaries/text | H: `whisper_full_get_segment_t0/t1/text`; S verbose: `start`, `end`, `text`. | Convert seconds without changing the original-audio origin; validate finite, ordered, bounded times. |
| Avg log probability | S verbose: `avg_logprob`; H/token data: `plog`. | Present raw metric with engine provenance; recalibrate aggregate confidence before auto-send eligibility. |
| Silence probability | W: `whisper_full_get_segment_no_speech_prob`; S verbose: `no_speech_prob`. | It exists in v1.9.4 despite a stale neighboring TODO. Never synthesize absent silence probability as measured zero. |
| Compression ratio | S verbose: no field; W fallback uses entropy/logprob criteria. | No equivalent. A text-derived zlib statistic would be an adapter-derived metric, not proof matching decode decisions. Current BF contract doesn't need it. |
| Word/token probability | H: `whisper_token_data.p`, `.plog`, `.t0/.t1`, `t_dtw`; S verbose `words`, `probability`. | Token timing/bias confidence is not guaranteed lexical-word alignment. Don't promise a feature BF doesn't currently consume. |
| Load/reload | Server README: `/load`, multipart `model` path; S uses existing context parameters. | Validate artifact locally before use. Prefer supervised restart initially for rollback and device/threads changes. |
| Unload/status/probe | H: `whisper_free`; Server routes: `/health`; no HTTP unload/capabilities endpoint. | Owned child shutdown implements unload; health is construction readiness, app-owned decode establishes inference readiness. |
| Incremental stream/cancel | H callbacks: new segment/progress/abort; S abort callback detects disconnect; no chunked-transcript HTTP route. | Existing BF batch loop can issue bounded requests. Cancellation must close/abort the transport and verify completion; no fake native streaming claim. |
| CUDA error memo/runtime libraries | No HTTP equivalent; Vulkan has a different runtime. | Leave CT2 memo/classifier in its adapter. Normalize Vulkan-specific errors without relabeling them cuda_runtime_missing. |
| Catalog/acquisition/leases/review | No upstream application equivalent. | BetterFingers owns those decisions; a child must never fetch models or grant send permission. |

### Losses that matter to the user

**V** `H` documents experimental token timestamps and distinguishes raw token-data times from original-audio token accessors when VAD removes silence. `W/whisper_full_default_params` and its fallback loop use logprob/entropy/silence criteria. **I** Thus matching field names is insufficient: changed segmentation affects `TextFormatter`, confidence duration weighting and speech-signal pause ratios. Add silence-leading/trailing, multi-pause, multilingual and Unicode fixtures before accepting normalization.

**V** S averages summed emitted token log probabilities over `n_tokens`; special tokens are skipped from the sum, and UTF-8 token fragments can be merged. **I** Treat the result as engine-specific evidence, not calibrated equivalence to faster-whisper. Keep aggregate score unavailable for the new adapter until corpus calibration; otherwise its seemingly compatible number can quietly loosen the 0.85 auto-send gate. The existing missing-confidence path forces review only while that gate is enabled (`backend/output/send_policy.py:33`), so qualification must explicitly enforce review for this adapter and cover users who disabled the old gate.

**I** Retain the engine-independent text hallucination guard and confidence/review policy in BetterFingers. Passing similar fallback thresholds does not establish equivalent hallucination suppression. The first valuable comparison is WER plus preserved names/numbers and false confident outputs, alongside cold/warm latency and total resource use; silence-only and adversarial/noisy audio belong in that corpus.

## 4. Smallest proposed SpeechEngine interface

Everything in this section is **I**, not an implemented API. Put the interface and normalized data under `backend/stt/`; keep pure contracts free of FastAPI/process/model imports. Transcriber remains the orchestration/formatting/guard facade, preserving its public `transcribe*`, reload and reporter methods. Faster-whisper's adapter is the default.

```text
SpeechEngine.load(LocalLoadPlan) -> EngineStatus
SpeechEngine.unload() -> EngineStatus
SpeechEngine.transcribe(float32_mono_audio, DecodeOptions,
                        cancel_event=None) -> DecodeResult
SpeechEngine.status() -> EngineStatus            # cached, non-blocking, no probe
SpeechEngine.capabilities() -> EngineCapabilities
```

**I — LocalLoadPlan:** engine ID, verified runtime/model identity and absolute path, requested backend/adapter, thread count and allowed local fallback. It contains no URL or download permission. Local path resolution uses `backend.config.app_paths` and the privacy inventory; load cannot invoke acquisition. `DecodeOptions` first contains the existing duration-based beam choice and dictionary bias; it later owns explicit language, VAD and other inherited defaults with capability validation.

**I — DecodeResult:** text-ready normalized segments with `start`, `end`, `text`, optional finite `avg_logprob`, `no_speech_prob`, `compression_ratio`, optional alignment records, plus original audio duration and raw language metadata. Add an explicit alignment kind (`none`/`token`/`word`) and metric provenance; unsupported values are absent/None, never optimistic zeros. Existing `TimedSegment` serialization stays unchanged initially; token extras need not leak into drafts. Distinguish empty/no-speech success from load/transport/inference failure with typed internal errors. Existing facade maps failures into its conservative public results and privacy-safe reporter.

**I — EngineStatus:** requested versus actual backend/device/adapter, artifact revision/hash, quantization, child build/PID ownership, constructed, probe_passed, inference_ready, loaded/resident, thread count and stable error/fallback codes. Store/cache status under a short state lock, not the long HTTP/model lock. No diagnostics endpoint performs a load/probe merely to report readiness. Extend existing backend sanitizers before showing Vulkan, otherwise `server.py:890` erases the new backend as invalid.

**I — EngineCapabilities:** explicit support levels for local load, backend/device control, prompt bias versus exact hotwords, VAD/model requirement, temperature policy, segment statistics, alignment kind, cancellation, batch requests and calibrated confidence. Unsupported requested options fail visibly; they do not become invisible default changes. A GPU name or installed SDK is not a successful-inference capability.

**I — Ownership:** keep `model_runtime.read_lease("stt")` through HTTP completion/normalization; write lease protects restart/reload/unload. One child per active engine, one inference owner, bounded timeouts, PID-targeted stop, and no automatic restart/acquisition after cancellation/privacy wipe. Use one qualified local CPU fallback at most. Do not duplicate the parent `gc.collect()` assumption for child memory: actual child exit/release and measured memory must update the ledger.

**V** S's `/load` can leave loading state after rejected input and exits on failed model initialization; its default headers allow wildcard CORS and its handlers have no bearer validation. **I** Therefore production supervision must include an authenticated local command channel: minimally patch bearer/Origin checks into the pinned server build, restrict model paths and disable unintended public/static exposure. Existing Python sidecar auth (`backend/api/security.py:1`) does not authenticate a second listening child. Loopback alone is not a substitute. The adapter should use owned process identity plus authenticated health, not adopt any service returning `{status: ok}` on a port.

## 5. Build, package and model plan

### Windows Vulkan runtime

**V** Required upstream inputs: complete source at the pinned commit including vendored ggml; a Windows C++17 toolchain; CMake; Vulkan SDK providing headers/library and **glslc**; **SPIRV-Headers CONFIG**. Vulkan's own CMake file requires CMake **3.19**, even though the project root advertises a lower minimum. MSVC code paths and generated shaders are present. [root CMake](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/CMakeLists.txt), [Vulkan CMake](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/ggml/src/ggml-vulkan/CMakeLists.txt), [examples CMake](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/examples/CMakeLists.txt).

**I** Proposed CI recipe, **not run in this task**: VS 2022 x64 tools/Windows SDK, pinned CMake and Vulkan SDK, resolved SPIRV-Headers package, and a manifest recording source/patch/toolchain revisions. Start with CPU+Vulkan only, portable CPU instructions; no CUDA, SDL microphone capture, FFmpeg conversion or model-fetch step in the runtime build. CMake 4 users need to resolve the project's old policy minimum explicitly rather than assume configure succeeds.

```powershell
# Illustrative future CI commands, after toolchain/package provisioning.
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 `
  -DGGML_VULKAN=ON -DGGML_CUDA=OFF -DGGML_NATIVE=OFF `
  -DWHISPER_BUILD_EXAMPLES=ON -DWHISPER_BUILD_SERVER=ON `
  -DWHISPER_BUILD_TESTS=OFF -DWHISPER_SDL2=OFF `
  -DBUILD_SHARED_LIBS=OFF
cmake --build build --config Release --target whisper-server
```

**V** `GGML_VULKAN` is the documented backend flag ([README Vulkan section](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/README.md#vulkan-gpu-support)); the example/server/test/SDL2 switches exist in root CMake, and CUDA/native/static choices are defined by root and [ggml CMake](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/ggml/CMakeLists.txt). **I** Static library selection reduces app DLL surface but still requires checking the produced PE imports/MSVC runtime and Windows Vulkan loader/driver dependencies. Do not ship the compiler/entire Vulkan SDK to users, and do not claim every GPU driver qualifies. Pin a signing procedure to `docs/release/WINDOWS_SIGNING.md:1`; sign executables/owned DLLs, then hash the final signed archive, retain notices and SBOM, and verify on an AMD-only and Intel-only Windows machine.

**I — Size budget:** initially reserve **10–50 MB compressed / 20–100 MB extracted** for a stripped x64 server/runtime, excluding models. This is a planning allowance, not a built artifact measurement. **V** b5130's existing x64 CPU archive is 8,573,270 B and BLAS archive 21,360,234 B; neither bounds Vulkan shader/code size or the final signed build. Replace the allowance with measured artifacts before installer copy or release claims. [b5130 metadata](https://api.github.com/repos/ggml-org/whisper.cpp/releases/tags/b5130).

**I** Use the same pattern, with separate STT namespace, as `RUNTIME_ARTIFACT_SHA256` (`backend/models/model_manager.py:137`), verified download (`:1677`), safe staged extraction (`:1149`) and installed-runtime verification (`:986`). Add a `whisper.cpp/<build>/<platform>/<backend>` runtime record and app-owned path; don't overwrite llama-server or trust an arbitrary PATH executable. Optional user acquisition must preserve H2's separation of implicit local loads from explicit existing download routes. Durable consent grants are a required future design if introduced, not an H2 implementation claim. Alternatively ship the signed runtime in installer resources: that requires a separate stage/include integration patch, not invoking current network provisioning at startup.

### Model formats, sizes and notices

**V** The official converted model source is `ggerganov/whisper.cpp`, referenced by upstream [`models/download-ggml-model.sh`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/models/download-ggml-model.sh) and [`models/README.md`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/models/README.md). Metadata read on 2026-10-04 reports revision `5359861c739e955e79d9a303bcbc70fb988958b1`. These are ggml `.bin` models, not Systran/CTranslate2 `model.bin` directories. A filename ending `.bin` is not interchangeability.

| Artifact (**V**, metadata only) | Bytes / approximate MiB | HF LFS SHA-256 | Pinned source |
|---|---|---|---|
| `ggml-base.en.bin` | 147,964,211 / 141.11 | `a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002` | [base.en metadata page](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.en.bin) |
| `ggml-small.en.bin` | 487,614,201 / 465.03 | `c6138d6d58ecc8322097e0f987c32f1be8bb0a18532a3f88f734d1bbf9c41e5d` | [small.en metadata page](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-small.en.bin) |
| Optional `ggml-silero-v6.2.0.bin` | 885,098 / 0.844 | `2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987` | [VAD metadata page](https://huggingface.co/ggml-org/whisper-vad/blob/9ffd54a1e1ee413ddf265af9913beaf518d1639b/ggml-silero-v6.2.0.bin) |

**V** Source model cards declare MIT; whisper.cpp and OpenAI Whisper license files are MIT. VAD comes from `ggml-org/whisper-vad`, revision `9ffd54a1e1ee413ddf265af9913beaf518d1639b`, with MIT metadata, and upstream's VAD script names v5.1.2/v6.2.0. [Whisper weights card](https://huggingface.co/ggerganov/whisper.cpp/blob/main/README.md), [VAD card](https://huggingface.co/ggml-org/whisper-vad/blob/9ffd54a1e1ee413ddf265af9913beaf518d1639b/README.md), [whisper.cpp license](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/LICENSE), [OpenAI Whisper license](https://github.com/openai/whisper/blob/main/LICENSE), [VAD download script](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/models/download-vad-model.sh). **I** Include original notices plus dependency/converted-weight provenance in the artifact and model license inventory; source-card metadata alone is not a completed distribution audit. **U** No bytes were retrieved here to verify those advertised digests locally.

**V** H3's separate brief/manifest targets the four-file **Systran faster-whisper-base.en** directory, revision `3d3d5dee26484f91867d81cb899cfcf72b96be6c` (`C:/Users/Laptop/Documents/Codex/2026-08-16/p/BetterFingers-wt/h3-bundled-base-en/backend/stt/bundled_manifest.json:3`, `:5`, `:11`, `:16`, `:21`, `:26`; cross-worktree, unintegrated). **I** To have both engines work offline immediately, ship a **second** ggml model artifact with its own manifest, resolver and license entry. The H3 CT2 artifact cannot be passed to whisper.cpp; replacing it would break the still-default engine. The second base weight adds 147,964,211 B before compression/runtime overhead. Together with H3's four manifest sizes totaling 147,769,510 B CT2 payload, arithmetic gives **295,733,721 B** of model payload, not a measured installer size. Do not silently double the bundle: the owner approved CT2 base.en, not every optional second-engine payload. Best first slice is optional, explicitly acquired ggml base.en with the existing bundled/default CT2 engine retained.

## 6. Effort, failure modes and acceptance

**I — Estimate: six bounded implementation/qualification cards**, conditional on a useful speed/accuracy spike. This is scope, not a calendar promise; integration with H2/H3 and in-flight round-3 ownership can change it.

| Card (**I**) | Concrete done condition |
|---|---|
| S1: pure contract/default adapter | Existing Transcriber calls delegate through SpeechEngine; default CT2 fake suites and public structured/confidence results remain unchanged. No acquisition in engine load. |
| S2: pinned signed runtime + supervisor | CI build/import inventory, authenticated loopback channel, bounded launch/health/decode probe, targeted shutdown/cancellation/restart, malformed-request fakes and crash recovery; no orphan child or privacy logs. |
| S3: normalization and review calibration | Stored/fake verbose responses normalize correctly; token/segment/VAD origins explicit, hotword approximation measured, no fabricated statistics, mandatory review before calibration. |
| S4: engine-qualified artifacts/acquisition | Separate verified ggml registry, local-only load, permitted acquisition/store/delete, H3 reconciliation, size/notices/build stage. Missing/corrupt artifact never causes surprise network repair. |
| S5: status/device/residency plumbing | Sanitizers show actual Vulkan/adapter/quantization/probe state; admission accounts child/shared memory, requested preference never masquerades as readiness, default recommendations unchanged without qualification. |
| S6: real qualification and streaming | AMD+Intel+mixed GPUs, repeated/cold/warm CPU/GPU runs, latency/WER/name-number retention, resource limits, abort/profile switch/wipe and driver-failure recovery. Existing batch/full-pass recovery works; only then opt-in availability. |

| Failure mode | Evidence / uncertainty | Smallest mitigation (**I**) |
|---|---|---|
| Radeon 890M + RTX 5070 selects the wrong adapter | **V** [`ggml/src/ggml-vulkan/ggml-vulkan.cpp`](https://github.com/ggml-org/whisper.cpp/blob/v1.9.4/ggml/src/ggml-vulkan/ggml-vulkan.cpp) supports `GGML_VK_VISIBLE_DEVICES`, device filtering and physical-device enumeration. **U** indices/order and actual selected inference adapter on the owner's system. | Record stable identity, map qualified child selection, test both adapters individually. Llama/CUDA device numbering is not a Vulkan index. Don't auto-promote from adapter names. |
| Driver/shader/feature failure or GPU hang | **V** Vulkan CMake probes shader extensions; **U** runtime compatibility/driver failure rates. | Bounded request/child deadlines, disable failed tuple for the session, one verified local CPU fallback, truthful status. Never benchmark/start repeated children in the user's dictation loop. |
| Confidence/accuracy drift creates false auto-send eligibility | **V** BF confidence/review dependencies above; **U** comparative WER and calibrated confidence. | Mandatory review initially, matched audio fixtures, per-engine calibration and numbers/names/error-type analysis; performance gain alone cannot open the gate. |
| Prompt substitute loses dictionary terms | **V** dedicated HTTP hotwords absent; **U** semantic equivalence. | Expose bias support honestly and test proper nouns/multiword terms; retain downstream single-word correction. |
| Child takeover/port collision/local unauthorized request | **V** upstream server is not the Python authenticated sidecar; **U** integration threat qualification. | Authenticate the child command channel; bind loopback only, verify owned PID/build, restrict paths, separate ports and preserve drafts on failure. |
| Timeout/abort leaves model alive or returns stale text | **V** BF session abort/full-pass and runtime leases exist; **U** actual HTTP disconnect/GPU abort timing. | Request-generation IDs, cancellation closes transport, wait/terminate owned PID if stuck, ignore stale result, update residency after verified release. |
| Runtime growth/antivirus/SmartScreen | **U** final artifact size and AV behavior. | Own CI/signing/provenance, PE/import/SBOM checks, trusted pinned update path, real Windows release smoke; don't ship an unsigned ad-hoc exe. |
| Optional engine regresses consent/bootstrap | **V** baseline CT2 cached-load failure can retry remote (`backend/stt/transcriber.py:606`, `:674`); H2 changes are separate. | Reconcile H2 local-only policy before seam integration; no load-time acquisition, no implicit model conversion or second bundle. |
| Status code/lock edits collide with round 3 | **V** brief reserves status/locks and build-backend ownership; **U** final integrated lines. | Rebase/re-resolve symbols after those cards merge; no parallel blind patch to those files. |

**I — NOW:** review this seam against the independently observed spike, H2's local-only loads and explicit download separation and H3's unapplied bundle patches. **NEXT:** S1 with unchanged faster-whisper behavior, then a bounded final-pass Vulkan prototype behind explicit engine selection and mandatory review. **LATER:** native streaming, VAD changes, quantized variants, automatic selection and a second bundled model, each with its own qualification decision.

## 7. Research validation and limits

**V** Read `docs/DEVELOPMENT.md` first; searched `backend/`, `server.py`, tests, lock files and build packaging with `rg`; read referenced functions and tests. Read tag-pinned upstream server/header/core/Vulkan/CMake/model scripts and release/HF JSON metadata over HTTPS. Release/HF metadata was queried with `Invoke-RestMethod`; raw source with browser/`Invoke-WebRequest`, held in memory, never as a binary/model download. Citation checks validate repository paths/line numbers and the required sections/claim labels; `git diff --check` checks the document patch.

**V** Final static audit passed: 147 citation occurrences (138 unique file/line pairs), all existing and nonblank; seven numbered sections; five interface methods; V/I/U labels; balanced code fences; 29 dependency rows and 24 upstream rows. H3 manifest arithmetic was independently summed from its four sizes. `git diff --no-index --check -- NUL docs/design/STT_ENGINE_SEAM.md` produced no whitespace diagnostics (exit 1 because the untracked document differs from NUL); `git status --short` showed only this new document.

**U** No source compilation, native API exercise, benchmark, model hash recomputation, real audio, GPU/driver test, signing/AV qualification or integration test was performed. This document is cost/compatibility research, not evidence whisper.cpp is faster or ready to replace the default. No code/runtime tests were needed or represented as passing for H7.
