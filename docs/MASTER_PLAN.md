# BetterFingers Master Plan — 23 Features + UI/UX Overhaul

Researched and verified 2026-07-07 (web research pass + codebase audit). Assumes the
Electron migration (ELECTRON_MIGRATION_PLAN.md) is complete: sidecar hardened, PTT
working, packaging done, first-run state client-side, legacy tkinter tree deleted.

Item codes: **U1–U11** = user's list, **C1–C12** = companion list. Effort: S (≤2 days),
M (≤1 week), L (1–3 weeks), XL (3+ weeks).

---

## Part 1 — Verification matrix

Every item is feasible. Verified tech picks (licenses checked for commercial shipping):

| # | Item | Verdict | Verified tech pick |
|---|------|---------|-------------------|
| U1 | Screenshot QA of every page | ✅ Solid | Playwright `_electron` + `toHaveScreenshot()`, pinned Linux CI image, `reg-actions` for PR diffs. Tray/native dialogs must be stubbed. |
| U2 | Smart hardware detection + tradeoffs | ✅ Solid | Vulkan device enumeration as the universal probe (works for NVIDIA/AMD/Intel on Win+Linux, reports real VRAM) + `nvidia-ml-py` / `amdsmi` for precision. Borrow Ollama's discovery/dedupe design (MIT). Extends existing `hardware_report.py` + `assess_model_fit()`. |
| U3 | First-run wizard | ✅ Solid | Port `guided_tour.py` content into an Electron modal wizard; first-run flag client-side (already planned as Phase 2.6). |
| U4 | Hardware-aware model downloader | ✅ Solid | Backend already has `/models/download` + progress + `/whisper/download`. Add a recommendation layer: hardware tier → model shortlist with tradeoff copy. Needs download resume (gap found in audit). |
| U5 | Improved TTS | ✅ Solid | Keep Kokoro-82M (Apache) as default. Add: sentence-chunked streaming (RealtimeTTS pattern, MIT), token-aware smart-split (175/250/450 sentence-boundary chunking à la Kokoro-FastAPI), text normalization (numbers/abbrev/code symbols), RMS/BS.1770 loudness normalization, chunk crossfade, utterance cache. ⚠️ Piper is now GPL-3.0 under new maintainers — do not adopt; old MIT fork is frozen. |
| U6 | Voice cloning / customization | ✅ Solid | Two tiers. Customization: **Kokoro voice blending** — voice packs are tensors; weighted-average blends work today, save as new voicepacks (near-free feature). Cloning: **NeuTTS Air** (Apache, CPU, ~3s sample) or **Kyutai Pocket TTS** (CC-BY, 100M, CPU-realtime) on CPU; **Chatterbox** (MIT, 23 langs, ~10s sample) when GPU detected. Ship a consent checkbox (industry norm; Chatterbox watermarks output). Avoid XTTS-v2/F5-TTS/Fish Speech — non-commercial weights. |
| U7 | Persona overhaul | ✅ Solid | Today a persona = name + prompt only. Redefine (see Part 3). |
| U8 | Model updates | ✅ **Gemma 4 confirmed** | Gemma 4 released 2026-03-31, **Apache 2.0**: E2B, E4B (multimodal, native function calling), 12B Unified, 26B-A4B MoE (runs like a 4B — flagship local pick), 31B. GGUFs available. STT: Moonshine v3 streaming (34M–245M, true streaming, medium beats Whisper large-v3 on WER, CPU-realtime), faster-whisper distil-large-v3.5 (MIT), Parakeet-TDT 0.6B v3 (CC-BY, ONNX int8 runs on CPU). Intent-tier LLMs: Qwen3.5-2B, FunctionGemma-270M (tool-call router). |
| U9 | Cross-vendor efficiency | ✅ Solid | **llama.cpp Vulkan as universal default** (70–90% of native speed on AMD/Intel, fine on NVIDIA), CUDA build offered when NVIDIA detected. whisper.cpp shares the same GGML/Vulkan story (v1.8.3: 12× iGPU speedup). KV-cache quant `q8_0` (≈lossless). llama-server prompt/prefix caching — big win for persistent persona system prompts. Hot-swap via llama-server router mode or llama-swap. **Skip speculative decoding** below ~8B targets — overhead eats the gain. |
| U10 | Meetings mode | ✅ Feasible, CPU-constrained | Capture in sidecar: PyAudioWPatch (WASAPI loopback, Win) + SoundCard (Pulse/PipeWire monitor, Linux). Diarization: pyannote community-1 (CC-BY, gated, CPU=slow batch) or NeMo Sortformer (ungated) — **offline post-meeting processing on CPU; live diarization needs GPU**. Notes/action items via local LLM. |
| U11 | Brainstorm mode | ✅ Feasible | Streaming STT (Moonshine) + Silero VAD turn-taking + LLM question generation. `project_generator.py` already produces structured plans — seed for this. |
| C1 | Personal dictionary | ✅ Solid | faster-whisper's native `hotwords` param (~100–200 token budget) + post-ASR fuzzy/phonetic correction (rapidfuzz + metaphone) + **auto-learn from user corrections** (the Wispr Flow pattern — their accuracy went 88%→96%). |
| C2 | Voice editing commands | ✅ Solid | Talon-community pattern (reference implementation studied): phrase history (last ~40 utterances with emitted-keystroke counts) powers "scratch that"; a DictationFormat state machine handles "new paragraph"/"cap"/spoken punctuation. Command grammar layered before injection. |
| C3 | Per-app injection profiles | ✅ Win/X11; ⚠️ Wayland partial | `get-windows` npm (in Electron main) on Windows/X11. Wayland: per-compositor adapters (kdotool on KDE, D-Bus shell extension on GNOME, wlr-foreign-toplevel on Sway) + graceful default-profile fallback. Even Talon/Espanso don't fully solve Wayland — don't promise parity. |
| C4 | Confidence-gated review | ✅ Solid | faster-whisper exposes per-segment `avg_logprob` / `no_speech_prob`. Threshold: high-confidence → silent inject; low → review overlay. Per-profile sensitivity slider. |
| C5 | Wake word / hands-free | ✅ Solid | openWakeWord (code Apache) with a **self-trained model** (pre-trained ones are CC-BY-NC — train our own via their synthetic-TTS pipeline, <1hr) gated by Silero VAD v6 (MIT). Always-on cost: a few % of one core. Porcupine rejected ($6k+/yr). |
| C6 | Never lose audio | ✅ Trivial | Persist raw WAV per utterance (recorder already has the buffer); retention policy + "recovery bin" UI; re-transcribe action. |
| C7 | Privacy dashboard | ✅ Trivial | App is already offline-only except model downloads. Dashboard enumerates every network touchpoint, audio-retention settings, one-button data wipe. Competitive weapon: Wispr Flow is getting roasted for covert screenshots. |
| C8 | Searchable history | ✅ Solid | SQLite FTS5 (stdlib) in sidecar — replaces the 100-cap `draft_history.json`. `sqlite-vec` v0.1.9 later for semantic search. |
| C9 | Golden audio suite | ✅ Solid | WAV fixtures + expected transcripts, WER via `jiwer`, run per STT model in CI. Audit found tests use mock arrays only — no real-audio regression safety today. |
| C10 | Latency HUD | ✅ Trivial | Timestamp every pipeline stage (record→VAD→STT→LLM→inject), `/metrics` endpoint, debug HUD in renderer + status-rail glanceables. |
| C11 | Voice macros | ✅ Solid | Phrase table → snippet / keystroke sequence / shell command. Builds directly on C2's command grammar. Shell macros default-off + confirmation. |
| C12 | MCP client | ✅ Solid, newly viable | Official `mcp` Python SDK in the **sidecar** (not renderer), Claude-Desktop-style `mcpServers` JSON config, stdio servers. llama-server has native OpenAI-compatible `tools` support → schema bridge is trivial. Gemma 4's function-calling jump (~86% tool-call accuracy at E4B) is what makes this real at local scale. ~2–4 days for the loop; hard part is UX for tool permissions. |

**Corrections to earlier assumptions:** Gemma 4 is real (user was right). Piper is now
GPL. Speculative decoding is not worth it at our model sizes.

---

## Part 2 — UI/UX overhaul: "Speech is material"

One idea drives the whole overhaul: **everything you say becomes a visible, solid,
manipulable object.** Today the app's state is mostly invisible (audio vanishes into a
pipeline, drafts appear in a tab). The overhaul makes the pipeline itself the UI.

### Signature element: the Stream

The main surface is a chronological feed of **utterance cards**. Each card shows the
raw transcript morphing into the refined text (a brief, satisfying transition — you
*see* the persona work). Cards carry their audio (replayable), their confidence, their
destination app, and their actions (send / rewrite / speak / pin / macro-ify).

- **Confidence is rendered, not hidden** (C4): high-confidence words are solid ink;
  low-confidence words render slightly translucent with a soft underline. Say "fix
  word three" or click to correct — corrections feed the personal dictionary (C1),
  and the user *watches the app learn*. This is the genuinely-unique hook: no
  competitor shows uncertainty honestly.
- Recovery bin (C6) is just the Stream's "unprocessed" filter — failed audio stays
  visible as a card with a retry button, never silently lost.

### Information architecture — three spaces + a rail

Replaces the current 4 tabs. Nothing is more than one click deep.

1. **Talk** — the Stream + live mic state. The default, 90%-of-time view.
2. **Library** — history search (C8), Meetings (U10), Brainstorms (U11). Time on one
   axis, projects on the other.
3. **Studio** — Personas & Voices (U7/U6), Models & Hardware (U2/U4/U8), Macros (C11),
   Tools/MCP (C12), Privacy (C7).
- **Status rail** (persistent, bottom): mic level, loaded models with RAM/VRAM gauge,
  active persona, target app (C3), latency readout (C10). Every piece of hidden state,
  permanently glanceable. Click any element to jump to its settings.

### "Promotes brain activity"

- **Brainstorm constellation** (U11): ideas appear as nodes as you speak; the LLM
  links related nodes and asks one probing question at a time (visible as a pulsing
  node you answer by voice). Export as outline/plan via `project_generator.py`.
- **Threads**: while you dictate, the Library surfaces related past utterances/notes
  in a side rail (FTS5 now, sqlite-vec later) — your own ideas resurface in context.
- **Echo cards** (opt-in): after a meeting or brainstorm, the app generates 2–3 recall
  questions and resurfaces them a day later as Stream cards — active recall applied to
  your own work.

### Design language: "solid"

- **Tactile-physical, not glassy**: high-contrast type (one strong grotesque for UI,
  a serif for transcript ink), hard edges, real shadows, springy 120–200ms motion
  (scale/settle, no fades-of-mush). Dark "desk" theme default, paper-light theme.
- **Sound design**: three tiny earcons (record start, refined, sent) — a voice app
  should speak its own state. All optional.
- **Waveform ring**: while recording, a calm breathing ring around the overlay dot —
  ambient, alive, never distracting.
- **Plain CSS stays** (current custom-properties approach is fine): formalize into
  design tokens (`tokens.css`: color/space/type/motion/elevation scales). No framework
  migration — the renderer is small enough that vanilla + web components per card type
  is simpler and lighter than adopting React mid-flight.
- **Accessibility as identity**: full keyboard nav, visible focus, reduced-motion mode,
  ≥4.5:1 contrast everywhere, and — uniquely — **complete voice operability** (C2/C5/
  C11 mean the app itself can be driven hands-free; "BetterFingers" earns its name).

### Onboarding (U3) in this language

Five-step modal wizard, each step doing real work: (1) mic check with live waveform →
(2) hardware probe with plain-language verdict ("You can run these three models well")
→ (3) recommended downloads with tradeoff copy + progress (U4) → (4) say one test
sentence, watch it become a card and get refined (the aha moment) → (5) pick hotkey +
persona. Skippable, revisitable from Studio.

---

## Part 3 — Persona overhaul (U7 design)

A persona stops being a bare prompt and becomes the app's central object — *a way of
speaking*:

```yaml
persona:
  name: "Polished"
  prompt: "..."                  # rewrite instruction (as today)
  temperature: 0.3
  few_shot: [{raw: "...", out: "..."}]   # 0–3 examples — biggest quality lever
  voice: {base: af_heart, blend: {am_adam: 0.2}, speed: 1.05}   # U6 tie-in
  format: {caps: sentence, punctuation: full, signoff: null}    # C2 state-machine defaults
  dictionary_scope: [global, coding]                            # C1 tie-in
  tools: []                      # MCP tool allowlist (C12) — persona becomes an agent
  model_hint: gemma-4-e4b        # optional per-persona model
```

Studio editor with **live side-by-side preview**: dictate one sentence, see every
persona's rewrite rendered as cards, hear its voice. Personas keep YAML storage
(schema_version bump + migration for existing name+prompt entries).

---

## Part 4 — Phased implementation plan

Dependencies flow downward; phases 2–3 can overlap with 1 (different layers of the
stack). Backend work = Python sidecar; frontend = Electron renderer/main.

### Phase 0 — Measure first (foundation for everything) — ~2 wks
| Item | Work | Effort |
|---|---|---|
| C9 | `tests/golden_audio/` WAVs + jiwer WER harness; CI job per configured STT model | M |
| C10 | Pipeline stage timestamps in server.py; `/metrics`; renderer debug HUD | S |
| U1 | Playwright `_electron` harness; screenshot spec per view; pinned-Linux CI + reg-actions | M |
| U2 | `hardware_report.py` v2: Vulkan enumeration + nvidia-ml-py/amdsmi; tier classifier (`cpu-only / igpu / dgpu-8g / dgpu-12g+`) feeding `assess_model_fit` | M |

*Why first: every model/perf claim in later phases gets accepted or rejected by these numbers.*

### Phase 1 — Models, runtimes, onboarding — ~3 wks
| Item | Work | Effort |
|---|---|---|
| U8 | Model catalog: add Gemma 4 (E2B/E4B/12B/26B-A4B GGUF), Qwen3.5-2B, FunctionGemma-270M; add Moonshine + distil-large-v3.5 + Parakeet-ONNX as STT options behind the existing transcriber interface | L |
| U9 | Ship Vulkan llama-server/whisper.cpp builds as default, CUDA variant on NVIDIA detect; enable KV-cache q8_0 + prompt caching; llama-swap for hot-switching | L |
| U4 | Recommender: tier → shortlist w/ tradeoff copy; download resume; disk-space guard | M |
| U3 | First-run wizard (5 steps above); reuses U2 probe + U4 recommender | M |

*Gate: golden-suite WER + latency numbers must confirm each new model before it becomes a default.*

### Phase 2 — UI/UX overhaul shell — ~3 wks (overlaps Phase 1)
`tokens.css` design system → status rail → Stream (utterance cards over existing
draft/WS events — backend already pushes `preview_ready`/`draft_sent` etc.) → three-space
navigation, migrating the current 4 tabs → sound design + motion + reduced-motion +
keyboard nav. Screenshot QA (U1) locks each view as it lands.

### Phase 3 — Core dictation loop — ~3 wks
| Item | Work | Effort |
|---|---|---|
| C1 | `dictionary.py` (hotwords injection + rapidfuzz/metaphone post-correction); auto-learn from card edits; Studio UI | M |
| C4 | Confidence plumb-through → card rendering + silent-inject threshold per profile | S |
| C2 | Phrase history + DictationFormat state machine; command grammar pre-injection ("scratch that", "new paragraph", "fix word N") | L |
| C6 | Raw-audio retention + recovery cards + retention setting | S |
| C3 | `get-windows` in Electron main → active-app context to sidecar; per-app profile switching (extends context_rules.yaml + profiles); Wayland adapters best-effort | M |

### Phase 4 — Voice, TTS, personas — ~3 wks
| Item | Work | Effort |
|---|---|---|
| U5 | tts_engine: smart-split chunking, streaming playback, text normalization, loudness norm, crossfade, utterance cache | M |
| U6 | Kokoro blend editor (sliders → save voicepack); cloning engine plugin (NeuTTS Air CPU / Chatterbox GPU) + consent flow | L |
| U7 | Persona schema v2 + migration; Studio editor w/ live preview; per-persona voice/model | L |
| C5 | openWakeWord integration (self-trained "hey fingers" model) + Silero VAD v6 gating; hands-free mode toggle | M |

### Phase 5 — Knowledge features — ~4 wks
| Item | Work | Effort |
|---|---|---|
| C8 | SQLite FTS5 store replacing draft_history.json; Library search UI; sqlite-vec semantic pass later | M |
| U10 | Meetings: sidecar loopback+mic capture → chunked STT → offline diarization (pyannote/NeMo) → LLM notes/action items → Library timeline UI | XL |
| U11 | Brainstorm: streaming STT + VAD turn-taking + question-generating LLM loop; constellation UI; export via project_generator | L |
| — | Threads + Echo cards (uses C8) | M |

### Phase 6 — Power & trust — ~2 wks
| Item | Work | Effort |
|---|---|---|
| C11 | Macro table (phrase → snippet/keys/shell w/ confirm); Studio UI | M |
| C12 | `mcp` SDK client in sidecar; mcpServers config; llama-server tools bridge; per-persona tool allowlist + permission prompts in Stream | L |
| C7 | Privacy dashboard + data wipe | S |
| — | electron-updater (NSIS differential + AppImage) rollout channel | M |

### Cross-cutting risks
1. **CPU floor** (8GB, no GPU): every default must pass on the low-end tier — Moonshine
   + E2B/Qwen3.5-2B + Kokoro is the floor stack; bigger models are opt-in via U4 tradeoff UI.
2. **Wayland**: C3/C5-hotkey degrade — document per-feature fallbacks in one support matrix.
3. **License hygiene**: re-check weight licenses at integration time (Moonshine streaming
   weights, Qwen3.5 license unverified as of research date); keep an in-repo `LICENSES-MODELS.md`.
4. **Sidecar API growth**: bump `schema_version` per phase; version-gate renderer features.
5. **pyannote gating** (HF contact-info agreement) — decide whether to bundle NeMo as the
   ungated default for meetings diarization.
