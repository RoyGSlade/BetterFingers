# Automatic model selection

BF-D3 design proposal, 2026-10-04. Source baseline: assigned worktree HEAD `f6aaa6f937a3a2c808ee35eadf324a998770eec3`. This specifies future behavior; it does not implement selection, package a GPU runtime, or qualify a release.

## Decision

Ship automatic selection of a **working, already-installed configuration**. Start with pinned `base.en`, CPU `int8`, cleanup off. Recommend optional upgrades only after local readiness and quality checks. A GPU name, a successful constructor, and enough total RAM are insufficient evidence that a configuration is usable.

The selector never starts a download, repairs a cache over the network, installs drivers, or activates cleanup/wake. Acquisition is a separate user-approved operation. This is the contract shared with the companion D1 modes and D2 first-run specifications: modes request intent; five-second setup covers human decisions, not guaranteed model readiness. Missing assets yield a truthful unavailable state. Local-use consent must be durably acknowledged before runtime probing/tuning; microphone diagnostic consent and network grants are separate.

## Evidence and limits

Local citations below refer to the assigned D3 worktree unless marked **main audit**. The main checkout is read-only during its reorganization. Its `docs/arc/MODELS_HARDWARE.md` was read in full, but some observations predate the worktree's thread/probe changes. Preserve that distinction when integrating.

| Evidence | What it establishes |
|---|---|
| `transcriber.py:69`, `109` | Current CPU policy caps ordinary loads at 8 threads, adapts to measured CPU load, and bounds by physical cores. The diagnostics environment override bypasses the caps. |
| `transcriber.py:578`, `622`, `689` | Current CUDA load consumes a real lazy transcription iterator before declaring GPU inference verified; failure then falls back to CPU and records a process-wide failure memo. This supersedes the audit's constructor-only load description. |
| `transcriber.py:73`, `902` | CUDA failure memo survives model reloads until process restart. Later decode recovery remains limited to the recognized missing-runtime family. An unrecognized constructor failure can still abort before fallback (`:615`). |
| `transcriber.py:599`, `668` | Cache/load failures still retry with `local_files_only=False`. This is a consent violation risk to fix before the proposed selector is enabled. |
| `utils.py:890`, `921`, `950`, `954`, `956` | Existing defaults: streaming on, STT pinned, LLM/TTS unpinned, cleanup off, GPU preference on, base.en. Proposed fresh CPU preference deliberately differs. |
| `backend/models/hardware_report.py:126`, `195`, `394` | Hardware reporting uses NVIDIA total VRAM or installed llama.cpp Vulkan enumeration; tiers do not prove faster-whisper readiness. |
| `backend/models/model_recommender.py:16`, `152`, `187`; `server.py:3225` | Static recommendation favors parameter count and total RAM. Recommendation routes report choices; they do not apply them. Roles, free VRAM and latency are missing inputs. |
| `backend/models/model_manager.py:39`, `99`, `131`, `248` | Catalog includes E2B/E4B rewrite models and 12B writer-only models; default E2B Q4. NVIDIA detection selects a CUDA 12.4 llama.cpp archive, independently of STT dependencies. |
| `backend/runtime/model_runtime_coordinator.py:126`, `221`, `336` | Existing read/write leases and RAM admission are useful foundations; the ledger has no VRAM accounting and permits a load when RAM telemetry is absent (`:366`). It is not an OOM guarantee. |
| `backend/tts/tts_engine.py:54`, `241`, `896`, `966`; `wake_models.py:42`, `472` | TTS uses a flat resident estimate and provider discovery; wake backbone explicitly uses CPU. Neither should borrow an STT GPU-ready flag. |
| **Main audit** `docs/arc/MODELS_HARDWARE.md:191`, `206`, `218`, `237` | Owner laptop: Ryzen AI 9 HX 370, 12 physical cores, 32 GB RAM, RTX 5070 Laptop with 8,151 MiB VRAM, CT2 4.8.1, no NVIDIA wheels; missing reachable cuBLAS/cuDNN. Capability enumeration does not prove decode. Point-in-time measurements, not the whole support matrix. |

Prior measurements are recorded in commit `b9fed85` (verified with `git show -s --format=%B b9fed85`): on a 10.7-second speech fixture, CPU int8/beam 5, `base.en` improved from 1.42 to 1.10 seconds and `small.en` from 2.34 to 1.81 seconds with the 4-to-8-thread policy; 16+ threads regressed. The commit also reports small.en first-dictation A/B 2.11 to 1.62 seconds, steady-state 2.33 to 1.86 seconds, and background load 0.60 to 1.42 seconds because load now includes the probe. **Measured previously by that implementation run, not rerun here; no distribution/raw per-run dataset is attached to this spec.** These are decode observations, not end-to-end p95 or a release promise. Commit `06c73bc` records the subsequent failed second CUDA probe hanging while holding the model lock, which motivated process-wide memoization. The main audit's latency ranges at `:293` remain hypotheses.

Numeric labels: **source constant** = present in code; **measured snapshot** = earlier recorded observation; **estimate** = arithmetic/heuristic; **proposed gate** = requirement to qualify; **unknown** = not measured. Product tier names are nominal classes; actual decisions use bytes/free resources. Memory estimates copied from fields named `*_mb` are treated as MiB-like binary units because their probes divide by 1024 squared. Do not mix them with decimal download MB.

## Selection inputs and rerun rules

Persist intent separately from effective runtime: `selection_policy=auto|manual`, mode, language, quality preference, requested model/device, cleanup/wake opt-ins and asset grant references. Migrating an existing profile preserves its manual choices and its off settings. Selection must never silently rewrite `llm_enabled` or listening consent.

Collect locally, after setup permits runtime work:

- CPU physical/logical cores, current utilization, available RAM/swap and free space in the actual asset directory; unknown fields remain unknown.
- GPU vendor/device identity, total **and free** dedicated VRAM, driver version, compute capability, and power/battery state if available. Shared iGPU memory is RAM, not extra dedicated VRAM. NPU presence is informational; no NPU backend is qualified.
- Installed, digest-verified asset revisions; exact engine/build/ABI; loadable library versions and provenance. A directory or `model.bin` alone is not integrity/readiness.
- Independent per-engine readiness: STT CUDA decode; LLM runtime startup plus bounded generation; TTS synthesis/provider; wake classifier plus CPU backbone. No network, no user transcript and no microphone are required for a synthetic readiness test.
- Qualification receipts for language/task quality, cold load, first inference, warm p50/p95, peak RAM/VRAM and mode contention. Missing receipts produce baseline or an experimental suggestion, not invented timing.

Cache receipts by device/driver, runtime/library digest, model/revision/compute, decode settings, language/fixture, mode and policy version. Free RAM/VRAM and load are resampled at every admission, not taken from cached receipts. Rerun a cheap readiness test after runtime/model/driver changes or a previous failure; rerun latency comparison only explicitly or during a user-enabled idle tuning session. Restart clears the existing per-process CUDA memo; a button must explain that a restart is required after repairing libraries until a safe isolated probe exists.

Mode change, AC/battery change, resource pressure or user override recomputes eligibility without benchmarks or asset acquisition. Freeze the effective configuration for an in-flight recording/draft. Apply changes under runtime write leases at an idle boundary; expose pending transition rather than swapping during capture. Use hysteresis: retain the current qualified choice if resources permit; do not oscillate models on each CPU sample. No periodic full benchmark on launch.

## Selection algorithm

1. Apply consent, language and mode restrictions. Gamer forces CPU and nonstreaming regardless of hardware or a diagnostics override. No language mismatch: `.en` is English-only; unsupported language enters the model-choice/unavailable path rather than pretending English is suitable.
2. Filter to approved catalog roles, installed complete artifacts, verified digests, compatible engines and available grants. Missing model becomes a separate upgrade/repair recommendation. Manual models still pass safety/readiness gates.
3. Compute RAM/VRAM admission using currently free resources, concurrent STT/LLM/TTS/wake/renderer costs and reservations below. Reject unknown automatic GPU fit. Unknown CPU telemetry allows only the baseline attempted with bounded failure handling, not an upgrade.
4. Require real inference proof for the exact configuration. A consumed silent STT iterator establishes execution only. Compare speech quality on a rights-cleared corpus before qualifying a new model/beam/quantization.
5. Among candidates within the mode cap and quality gate, choose the lowest qualified warm p95 for latency intents; accuracy intents choose the best measured quality that still meets their latency cap. Tie favors the current choice, then less resident memory. Without comparative receipts retain base.en CPU. Never select by parameter count alone.
6. Publish requested and effective configuration, readiness status, evidence confidence and a stable reason code. Speech-ready requires hash/revision verification plus `probe_passed && inference_ready` for the exact model/device/compute/backend-process generation. Ready to dictate additionally requires a valid capture device and qualified mode/binding/delivery. Skipping microphone setup leaves Talk explicitly unverified. An old process receipt is insufficient. Store a local bounded receipt with no audio/transcript/prompt text; deletion uses the privacy registry.

Suggested reason codes: `baseline_cpu`, `manual_override`, `gamer_cpu_cap`, `gpu_runtime_missing`, `gpu_probe_failed`, `gpu_memory_pressure`, `ram_pressure`, `asset_missing`, `asset_integrity_failed`, `quality_not_qualified`, `language_not_supported`, `tuning_pending`, `transition_pending`. User copy: “Using local CPU speech recognition. GPU acceleration is unavailable.” Offer details/repair separately; do not repeat technical errors after every utterance.

## Hardware classes and upgrade ceilings

All fresh profiles start `base.en` CPU int8 and cleanup/wake off. **Initial alpha keeps wake disabled in every mode, even with cached assets.** D1 Hands-free means manual-start/silence-stop; the wake column describes future qualification ceilings only, requiring a separately approved feature slice and listening consent. Entries below are **ceilings after opt-in and qualification**, not automatic activation or promises that all models fit. CPU threads use the existing load-aware physical-core policy, capped at 8 (**source constant**) except the stricter Gamer proposal below. Speech beam 5 for audio at least 2 seconds is current behavior (`transcriber.py:879`); beam 1 is a future candidate requiring quality evidence, not a default change in this design task.

| Nominal class | STT ceiling / compute | Cleanup / LLM ceiling | TTS | Wake |
|---|---|---|---|---|
| CPU-only, 8 GB RAM | `base.en` CPU int8; keep quality floor. Do not auto-select tiny.en to make a timing target. | Off; no automatic cleanup offer in minimal setup. Manual experimental E2B only if available RAM and preservation gates pass; it cannot consume the dictation budget. | Installed Windows SAPI on demand; Kokoro CPU only if installed, approved and admitted. | Off; explicit accessible hands-free request can enable a verified CPU classifier/backbone if resources permit. |
| iGPU, 16 GB RAM | `base.en` CPU int8; `small.en` CPU int8 after comparative proof. iGPU detection does not grant STT CUDA. | Off initially; E2B Q4 on CPU or actually proven llama.cpp Vulkan on demand, outside latency-critical dictation if slow. | Kokoro CPU on demand or SAPI; no implicit GPU provider. | Optional CPU, explicit listening consent and classifier required. |
| NVIDIA, 6–8 GB dedicated VRAM | `small.en` CUDA float16 only after decode+headroom proof; int8_float16 is a separate qualified candidate. CPU base.en remains recovery baseline. | Off initially; E2B Q4 short-context rewrite after preservation proof and memory admission. Never 12B writer model on cleanup hot path. | CPU Kokoro on demand or SAPI; GPU TTS deferred. | Optional CPU; never automatically on because a GPU exists. |
| NVIDIA, 12 GB+ dedicated VRAM | `medium.en` or `distil-large-v3` CUDA float16 after quality/latency proof; `large-v3` only as deliberate accuracy preference. | Off initially; E4B Q4 rewrite after proof. 12B writer-only is an explicit Ideas/long-form operation outside capture, not hot-path cleanup. | CPU Kokoro or SAPI; a TTS GPU upgrade needs its own provider/pack qualification. | Same explicit CPU policy. |

For 6 GB cards, cap by **free** VRAM even if the current classifier labels them `dgpu-8g` (`backend/models/hardware_report.py:412`). AMD/Intel discrete GPUs also require engine-specific Vulkan proof; they do not enter NVIDIA STT class. Downloadable=false alternatives in `backend/models/model_recommender.py:48` stay informational; no silent Moonshine/Parakeet/FunctionGemma/Qwen engine swap.

## Mode caps

These agree with D1's Work / Gamer / Ideas / Messages / Hands-free contract. Resource numbers not already coded are **proposed conservative gates**, to be changed only with named hardware/workload evidence.

| Mode | Intent and selection cap | Residency / optional work |
|---|---|---|
| Work | Accuracy within qualified dictation latency; no larger than hardware ceiling. Cleanup remains separate opt-in. | Keep admitted STT warm; cleanup warm only by explicit choice and adequate headroom. No writer-model preload. |
| Gamer | `use_gpu=false`, `streaming_transcription_enabled=false`, default base.en CPU int8. Proposed cap `min(existing thread policy, max(1, floor(physical cores/2)), 4)`. Gamer cap applies after environment override. | Cleanup, TTS and wake off. Release idle GPU STT/LLM/TTS under leases before showing mode active. No benchmark, acquisition, background GPU upgrade or writer preload. |
| Ideas | Accuracy ceiling as Work; explicit long-form writer task may use a separately admitted 12B model while capture is idle. | Writer unloads when operation completes; its ownership/resources cannot displace an active recording. |
| Messages | Latency intent, normally base.en or proven small.en. Optional E2B rewrite with short output/context, never 12B cleanup. | Raw transcript remains reviewable if cleanup exceeds its budget or fails. Review/accept is separate from external sending. |
| Hands-free | Latency intent; same speech cap as Messages. Initial alpha is manual-start/silence-stop with wake disabled. Enabling the mode requests intent, not listening consent or downloads. | STT may stay warm. TTS on demand. Future wake requires its own approved slice, explicit listening consent and verified CPU backbone/classifier. Missing/disabled wake offers manual start, not an inert “listening” indicator. |

Gamer availability is gated on tested PTT, an independently working stop path and qualified safe delivery; selection alone cannot unlock it. Gamer's D1 30-second recording watchdog is a recording safety ceiling, not a latency promise. Existing gaming manual-path bounds (50 completion tokens, two 90-character sentences, queue disabled) do not enable cleanup in Gamer. Game frame-time/CPU contention limits require a named-game measurement; thread count alone cannot guarantee unchanged FPS.

Default language remains explicit English until a qualified multilingual catalog is added. Accuracy gates must include names, numbers, negation and accents: satisfying a latency target by losing words is a failed candidate.

## Residency and resource accounting

Use one coordinator for actual loads with independent system-RAM and dedicated-VRAM budgets. Reserve all active/pinned components and pending admissions atomically, then resample after release. Estimate overlap during replacement if an old runtime is still resident; only credit memory after it is actually freed. The current RAM admission self-credit (`backend/runtime/model_runtime_coordinator.py:355`) is insufficient to prove transition peaks safe. Cancel-and-wait never silently discards a draft or starts network repair.

- Keep the current 1,500 MiB RAM floor (**source constant**) as minimum. Proposed automatic-load floor is the larger of that floor and 15% of total physical RAM (**proposed gate**). OS/app/game pressure may raise it; user pins never override a failed safety admission.
- GPU auto-load must leave the greater of 1 GiB or 20% of dedicated total VRAM free (**proposed gate**), after STT, optional LLM KV/cache/workspace and other processes. Unknown free VRAM means no automatic GPU upgrade. This deliberately leaves room for desktop/game spikes; it is not measured optimal.
- Track model/engine/device, actual or estimated resident RAM/VRAM, estimate confidence, pin owner and last-use time. iGPU offload consumes shared RAM; do not count the same shared allocation twice. Peak sampling validates estimate envelopes; steady working set is not the peak.
- STT: preload only after readiness/consent, consume a synthetic inference and pin while the mode needs fast capture and headroom permits. Hands-free also requires separate listening readiness. Under pressure release idle optional components before baseline speech; stop readiness work if recording begins.
- LLM: disabled means unloaded. CPU/iGPU opt-in loads on demand; current idle sweep is 300 seconds (**source constant**, coordinator `:131`). GPU cleanup may pin only with explicit user choice and a qualified joint STT+LLM budget. Unqualified cold startup cannot block first dictation; retain raw text and show cleanup preparing.
- TTS: on demand; current 30-second idle unload (**source constant**, TTS `:241`) prevents repeated reload between review sentences. CPU fallback does not install torch. TTS never runs during Gamer capture.
- Wake: CPU backbone and one verified classifier only after opt-in; idle listener costs and classifier memory must be measured. Backbone file size is not a resident-memory budget. Training, Qwen enrollment, cloning and OCR never preload through automatic selection.

Illustrative component footprints, **estimates, not fit guarantees**: base.en STT ~300 MiB; small.en ~700 MiB; medium.en ~1,800 MiB; distil-large-v3 ~1,700 MiB (`transcriber.py:39`). TTS ~450 MiB (flat source heuristic). E2B Q4 ~4,157 MiB and E4B Q4 ~6,209 MiB under the existing CPU formula `GGUF MiB*1.15+750`; their true GPU weights/KV/workspace and host overhead need measurement (`backend/models/hardware_report.py:33`, `251`). Main audit `:311` observed app/backend around 1 GB combined working set at one moment, which may already contain resident model memory. Component overlap is unknown: adding those observations to model estimates can double-count. Measure a model-unloaded baseline and incremental/peak allocations before publishing a session total. These large cleanup components support a conservative 8 GB cleanup default; they do not establish installer size or a universal peak.

## GPU packaging: decide CPU now, qualify optional pack next

The Windows lock pins faster-whisper 1.2.1 and CTranslate2 4.8.1 (`requirements-win.lock:331`, `384`). It pins no NVIDIA runtime wheels. The llama.cpp CUDA archive's DLLs are a separate component; pointing STT at that folder is not a qualified fix.

Upstream faster-whisper requires cuBLAS for CUDA 12 plus cuDNN 9 for CUDA 12; its pip example is explicitly Linux-only. Windows needs an app-owned qualified DLL deployment/search path, not a copied Linux install command. [faster-whisper requirements](https://github.com/SYSTRAN/faster-whisper#gpu)

For the RTX 5070/sm_120 qualification candidate, NVIDIA cuDNN 9.10.2's matrix includes Blackwell with CUDA 12.8/12.9 and Windows driver at least 570.65. The owner's previously measured driver 616.92 exceeds that minimum, but does not prove CT2 kernels. Do not switch to CUDA 13 simply because nvidia-smi displays CUDA 13.4: that is driver capability. CT2 4.8.1 plus exact runtime files must execute actual decode on this architecture. [NVIDIA pinned support matrix](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.10.2/reference/support-matrix.html)

Candidate dependency sizes, **verified publisher file metadata on 2026-10-04**, not installed/measured here:

| Candidate Windows x86-64 wheel | Compressed decimal size | Qualification status |
|---|---|---|
| `nvidia-cublas-cu12==12.8.4.1` | 567.5 MB | Candidate only; SHA-256 `47e9b82132fa8d2b4944e708049229601448aaad7e6f296f630f2d1a32de35af`. [NVIDIA PyPI files](https://pypi.org/project/nvidia-cublas-cu12/12.8.4.1/#files) |
| `nvidia-cudnn-cu12==9.10.2.21` | 693.0 MB | Candidate only; SHA-256 `c6288de7d63e6cf62988f0923f96dc339cea362decb1bf5b3141883392a7d65e`. [NVIDIA PyPI files](https://pypi.org/project/nvidia-cudnn-cu12/9.10.2.21/#files) |

Their sum is ~1.26 GB compressed (**estimate from publisher rounded sizes**), excluding CUDA runtime/other resolved dependencies, extraction staging and expanded disk usage. Expanded pack size and complete DLL closure are **unknown** until manifest inspection. Do not advertise “a small GPU fix.” Required load family includes `cublas64_12.dll`, `cublasLt64_12.dll`, `cudart64_12.dll`, `cudnn64_9.dll` plus cuDNN's required component/engine DLLs; copying only a loader stub is insufficient (**main audit** `:218`). Qualification enumerates exact required files from the chosen Windows distribution; never guess closure from Linux package names.

NEXT packaging must pin every artifact/version/hash, validate architecture/driver, stage and verify atomically, and establish an isolated trusted DLL directory before engine import. Keep DLL-directory handles alive as required by Python; avoid writable-CWD/PATH DLL discovery, shared global PATH edits, and mixing llama.cpp/CT2 cuBLAS versions in one process. Prefer an isolated GPU worker if version conflicts cannot be excluded. Failed installation leaves CPU intact and offers explicit repair/retry; nothing fetches during selection. Do not bundle torch to solve a faster-whisper dependency: it adds another large stack.

The CPU baseline can ship without a GPU pack. D2's proposed bundled base.en installer is roughly 379.6 MB (**estimate**) versus V3 231,819,753 B / 231.8 decimal MB (**main audit measured artifact**, `docs/arc/SETUP_AUDIT.md:106`, `248`): base.en model.bin 145,216,508 B plus approximately 2.55 MB support adds ~147.8 MB, assuming no further compression (~64% growth). This is not a newly built installer. The [publisher base.en tree](https://huggingface.co/Systran/faster-whisper-base.en/tree/main) reports rounded 148 MB and MIT; freeze revision/digests and retain attribution before bundling.

## License and provenance gates

Every selected artifact needs the actual artifact's license, upstream attribution, immutable revision/digest and runtime compatibility record. Library licenses do not license all model weights or voices. Populate missing entries in `LICENSES-MODELS.md` before publishing catalogs/packages; its current heading promises complete coverage but does not cover all baseline families (**main audit** `:107`). This design does not edit that file.

| Family | Checked upstream status / release requirement |
|---|---|
| faster-whisper code / base.en weights | MIT: [code license](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE), [Systran model](https://huggingface.co/Systran/faster-whisper-base.en). Retain notices; verify each other conversion separately. |
| CTranslate2 / llama.cpp | MIT: [CT2 4.8.1](https://github.com/OpenNMT/CTranslate2/blob/v4.8.1/LICENSE), [llama.cpp](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE). Vendor runtime components carry their own licenses. |
| Gemma 4 E2B | Official publisher currently lists Apache-2.0, not older Gemma-family terms: [Google model card](https://huggingface.co/google/gemma-4-E2B-it). Check pinned Unsloth GGUF derivative metadata and notices for each shipped conversion; a family assumption is insufficient. |
| Kokoro | [Upstream weights](https://huggingface.co/hexgrad/Kokoro-82M) Apache-2.0; [ONNX code](https://github.com/thewh1teagle/kokoro-onnx/blob/main/LICENSE) MIT. Exact converted ONNX/voice/espeak components and attribution need a complete manifest before distribution. |
| NVIDIA libraries | Proprietary runtime terms, separate from the model catalog's MIT/Apache/CC0 gate. [cuBLAS metadata](https://pypi.org/project/nvidia-cublas-cu12/12.8.4.1/), [cuDNN agreement](https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html). Verify redistribution files/conditions/notices for the exact versions before shipping; this is not a legal approval. |
| Wake | Existing permitted backbone is Apache-2.0; built-in upstream phrase classifiers are excluded by `LICENSES-MODELS.md:27` and `wake_models.py:264`. Never fill a missing classifier with an unapproved noncommercial model. |

## Fallback ladder

1. Respect mode/manual intent and attempt only locally verified, admitted assets. Missing/corrupt assets are not CUDA errors and never authorize remote cache refresh. Preserve recovery audio/draft through all failures.
2. CUDA unavailable or failed real inference: tear down the unusable runtime, memoize the failure, try the **same model** CPU int8 if admitted. Proposed bounded worker timeout must contain native hangs; the current in-process probe has no safe native-call timeout. Never reattempt failed CUDA in the same process.
3. Same-model CPU cannot meet resources or latency: use installed verified base.en CPU as the explicitly disclosed automatic recovery baseline in Auto policy. A Manual model stays requested; report the effective fallback and keep user confirmation available. Do not change to tiny.en, alter language, or silently reduce quality below base.en. If base.en is missing/integrity-failed or cannot be admitted, show unavailable, retain captured work and offer explicit repair/close-apps choices.
4. Optional cleanup fails/is slow/needs loading: deliver reviewable raw transcription with “Cleanup skipped” or “Cleanup preparing.” Never claim successful rewriting. No implicit different model or network service.
5. Optional TTS fails: try installed local Windows SAPI; if unavailable keep visible review. No cloud voice or torch installation. Wake failure disables that listener with a hotkey alternative, never a false active indicator.

Backend unavailable and microphone unavailable are separate failures. A functioning fallback model cannot repair either. Later CUDA OOM/kernel/driver/context errors need bounded fallback beyond the current missing-DLL string classifier; unknown errors retain sanitized class/reason rather than raw paths or user data. Do not retry corrupted weights under a new device indefinitely.

## Verification plan and definition of done

This is a plan; **no benchmarks, model loads, downloads or installs ran for BF-D3**. Reuse existing tools only when their side effects are understood and the execution is separately authorized.

NOW, before activating Auto:

1. Offline packaged clean-user test with bundled base.en: no outbound DNS/HTTP before consent; denying optional acquisition still permits baseline dictation. Exercise missing/partial cache, CUDA failure, mode entry, TTS read-back and cleanup startup under network denial. A single centralized acquisition grant must gate all downloads, including the current implicit retries.
2. Unit policy matrix with synthetic telemetry: each nominal class, unknown metrics, manual intent, language mismatch, digest mismatch, role/lane mismatch, Gamer GPU/env-override rejection, CPU load changes, admission failure and active leases. Verify disabling cleanup/wake survives migration and reruns. Tests cannot prove native GPU support.
3. GPU readiness containment: constructor success then lazy-generator DLL failure, unknown kernel error, timeout/hang and OOM; same audio is retried at most once on CPU and failed CUDA is not revisited. Test packaged-worker teardown, no deadlocks, capture recovery and pending mode transition.
4. Read `GET /runtime/status` (`server.py:3287`) without loading; record requested/effective state. Once authorized, `POST /runtime/warmup` (`:5648`) proves real inference. Stage timing does not prove placement; `/metrics` (`:3894`) lacks queue/hotkey/injection coverage (**main audit** `:389`).
5. Qualified speech comparison on rights-cleared fixtures: proposed 20 warm repetitions per candidate plus separate cold/first-inference runs; 4/8/physical-core thread counts only where applicable, base.en/small.en installed assets only, beam 5 versus proposed beam 1, streaming on/off. Measure names, numbers, negation/accents, RAM peaks, free/peak VRAM and end-to-end hotkey-release-to-visible-review/placement. Do not read the user's history as a corpus. The existing performance benchmark uses silence and one cold sample (`tools/performance_benchmark.py:71`) and can download/play audio; it cannot establish warm speech p95.

NEXT, GPU pack and optional cleanup:

6. Candidate GPU stack on RTX 5070/sm_120 and a named older NVIDIA GPU, packaged normal-user environment with no developer CUDA/PATH. Verify binary closure/digests/licenses, real decode, repeat restarts, cold JIT, driver mismatch, free-VRAM pressure, install cancellation and atomic rollback. Proposed STT target <=1.5 seconds warm p95 after release for ~10 seconds of speech is a **qualification target**, not today's measured result; Gamer/nonstreaming may need a separately declared larger budget. If quality or named-game frame time fails, retain baseline and publish measured limitations.
7. Reuse `tools/live_model_harness.py:48` for a healthy existing LLM server's structural preservation report; it is one Message Rescue sample, a proxy rather than dictation-cleanup latency. Test actual cleanup prompts separately, preservation corpus, joint STT+LLM memory and cancellation. Short context candidates 2,048/4,096 tokens are **proposed**, versus existing 16,384 context (**main audit** `:62`). Record true token counts rather than the performance tool's whitespace-word count.
8. Wire actual F38 stage runners before using its UI results for selection. `app/src/renderer/lib/latencyProbe.mjs:81` returns unavailable without a runner; its 3/8/12 run counts are **source constants**, not evidence that those measurements happened. `tools/injection_probe.py` types into a focused app; use an isolated Notepad target and explicit output path. Do not use the YouTube STT tool, which downloads external media.

LATER: NPU/DirectML/alternate STT engines, GPU TTS, Qwen wake training and automatic writer selection. These introduce independent engines/licenses/support matrices; they cannot ride on a GPU-detected badge.

Done for implementation means automatic choices are local, consent-safe, role/language-correct, inference-proven, admitted and visibly explained; Gamer never touches GPU; failed acquisition never breaks baseline; captures survive failures; actual clean-user packaged evidence covers hardware classes and named mode workloads. Done for this design means the policy, dependency gates, measured-vs-estimated limits, integration points and verification plan are reviewable. Performance and packaging qualification remain open.
