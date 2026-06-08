# The Backlot — Studio Media Engine & Model Dispatcher

**Status:** Design doc. Combines `Dispatcher.md` (CPU floor-manager + GPU-transient model
orchestration) with the **Visual Prompt Compiler**, **music/ambience generation**, and a
**pluggable voice engine (Kokoro → Chatterbox)** into one media architecture. Supersedes
`Dispatcher.md` for the media/model-hosting layer (keep that file as the original dispatcher
rationale).

Companion docs: [STUDIO_OVERHAUL_PLAN.md](STUDIO_OVERHAUL_PLAN.md) (the storytelling spine —
already built), [CHECKPOINT_FIRST_CUT.md](CHECKPOINT_FIRST_CUT.md) (state/handoff).

---

## 0. Where this plugs into what's already built

The storytelling spine is done and **already exposes the exact seams every model department
drops into** — none of this is greenfield:

| Seam (exists today) | What it is now | What this doc fills it with |
|---|---|---|
| `studio_render.set_renderer(fn)` / `render_scenes` | Pluggable image **render queue** (queued→rendering→done/failed/unavailable, asset persistence, `image_path`) | An **in-process Diffusers/SDXL backend** (no external app) behind the Visual Prompt Compiler |
| `studio_audio.set_synth(fn)` / `synthesize_scenes` | Pluggable per-beat **audio queue** | **Kokoro** (default) and **Chatterbox** (premium) voice backends |
| `studio_visual.build_image_prompt()` | Deterministic prompt assembly from world+character bibles | Promote to the full **Visual Prompt Compiler** (style/character/location bibles → prompt packet) |
| `model_manager.AVAILABLE_MODELS` + `llm_engine` (sidecar on **port 8080**) | One llama-server | A **two-lane ModelHost**: resident CPU Dispatcher (8080) + transient GPU worker (8081) |
| `hardware_report._detect_gpu()` / `assess_model_fit()` | VRAM probe + fit check | The **VRAM budget** the dispatcher enforces |
| `studio_workflow` stages (`render`, `voice`, `scene_continuity`…) | Reachable cinematic stages | Music/ambience stages + dispatcher-driven scheduling |

**Design rule (the whole point):** *Agents decide what should exist. Deterministic code decides
how to ask the model and whether the result is canon.* The LLM never writes a final image prompt,
never picks a seed, never manages VRAM. Dumb, strict code does — because dumb code is reliable code.

---

## 1. The cast (departments)

```
                         ┌────────────────────────────────────────────┐
                         │  Dispatcher (Gemma 4B/E4B, CPU/RAM, always-on) │  ← "Floor Manager"
                         │  reads State Packet → suggests next action     │
                         └───────────────┬────────────────────────────┘
                                         │ (suggestion, validated by code)
                ┌────────────────────────┴───────────────────────────┐
                │            ModelHost  (deterministic)               │  ← VRAM landlord
                │  resident CPU lane (8080)  +  transient GPU lane (8081) │
                └───┬───────────┬───────────┬───────────┬─────────────┘
                    │           │           │           │
            ┌───────▼──┐  ┌─────▼─────┐ ┌───▼─────┐ ┌───▼──────────┐
            │  Writer  │  │  Visual   │ │  Voice  │ │  Sound       │
            │ 12B LLM  │  │ Compiler+ │ │ Kokoro/ │ │ Music: ACE-  │
            │ (GPU)    │  │ ComfyUI   │ │ Chatter │ │ Step; Ambi:  │
            │          │  │ (GPU)     │ │ box(GPU)│ │ StableAudio  │
            └──────────┘  └───────────┘ └─────────┘ └──────────────┘
```

- **Dispatcher** — tiny resident coordinator on CPU. Stateless: it reads a compact *State Packet*
  compiled from SQLite, suggests the next stage, and code validates+executes. Never touches VRAM.
- **ModelHost** — the deterministic landlord. Owns the **GPU lane** and enforces the VRAM budget
  by loading exactly one heavy worker at a time and unloading it when done.
- **Departments** — Writer (12B), Visual (Compiler + ComfyUI), Voice (Kokoro/Chatterbox), Sound
  (music + ambience). Each is a GPU-transient worker behind a uniform adapter.

---

## 2. The hard constraint: a 16 GB GPU is a single stage, not a warehouse

RTX 4060 Ti 16 GB. Rough resident cost of the heavy workers:

| Worker | Approx VRAM (this card) | Notes |
|---|---|---|
| Gemma-4 **12B** Q4_K_M | ~7–8 GB | the Writer |
| **SDXL** anime checkpoint | ~6–8 GB | 512/768 panels |
| **FLUX.1-schnell** (fp8) | ~11–13 GB | premium image; load alone |
| **Kokoro-82M** TTS | <1 GB | trivial |
| **Chatterbox** TTS | ~3–5 GB | premium voice |
| **ACE-Step** music | <4 GB (per model card) | full-song |
| **Stable Audio Open Small** | ~3–4 GB | 11s ambience/SFX |

You **cannot** co-resident 12B + SDXL (~15 GB before activations/OS) safely, and Flux wants the
whole card. Therefore:

- **The GPU is a serialized lane.** ModelHost runs one heavy job to completion, unloads, then the
  next. The render/voice/music queues feed this single lane.
- **The Dispatcher (4B/2B) is pinned to CPU/RAM** (`n_gpu_layers=0`) and never competes for VRAM —
  it's the always-on brain that keeps the pipeline moving while the GPU cycles workers.
- **Two resource profiles** (from `Dispatcher.md`, kept): *Background VRAM Saver* (unload after every
  job — default) vs *Speedy Pipeline* (keep a worker hot if there's headroom, e.g. Kokoro + 12B).

VRAM truth comes from `hardware_report._detect_gpu()`; the ModelHost asserts "freed" after unload.

---

## 3. ModelHost — device-aware load/unload (extends `model_manager.py` + `llm_engine.py`)

Today: one `llama-server` on `SIDECAR_PORT = 8080`. We add a second lane and a uniform worker API.

```python
# model_host.py  (new) — the deterministic VRAM landlord
class Worker:                     # one heavy model behind a process/endpoint
    id: str                       # "writer-12b", "comfyui", "kokoro", "ace-step"
    device: str                   # "cpu" | "gpu"
    est_vram_mb: int
    def ensure_loaded(self): ...
    def unload(self): ...         # free VRAM (terminate subprocess / API unload)
    def healthcheck(self) -> bool: ...

class ModelHost:
    def __init__(self, profile): self.profile = profile      # "saver" | "speedy"
    def run(self, worker_id, task): ...   # ensure_loaded → execute → (saver: unload)
    def free_gpu(self, keep=()): ...      # unload everything on the GPU lane except keep
    def vram(self): ...                   # hardware_report._detect_gpu()
```

**Concrete hooks (per `Dispatcher.md` §4A):**
- Dispatcher model: `model_manager` loads `gemma-4-e4b-q4` (or `e2b` for low-RAM) with
  `n_gpu_layers=0` on **port 8080**, resident for the whole Studio session.
- Writer model: 12B launched on **port 8081** with CUDA layers, **on demand**, unloaded after its
  stage in Saver mode. `llm_engine` gains a `lane` arg (cpu/gpu) so existing
  `process_custom_prompt` routing is unchanged for callers.
- Media workers (ComfyUI/Kokoro/Chatterbox/ACE-Step) are subprocesses or local HTTP services the
  ModelHost starts/stops; the **GPU lane is mutually exclusive** with the Writer.

---

## 4. Visual department — the Prompt Compiler (promote `studio_visual.py`)

The single most important rule: **the LLM produces a structured visual *spec*, code compiles the
*prompt*.** That's what stops melted hands, wandering outfits, and continuity drift.

### 4.1 Data the compiler reads (project-local JSON, mirrors the bibles)
- `style_bible.json` — project visual identity (palette, line style, camera language, lighting
  rules, `avoid[]`). *(We already have world palette/lighting in the world bible — formalize it.)*
- `character_visuals.json` — per character: base_description, body, outfit, palette,
  expression_range, `negative_locks[]`. *(We already store `visual` + `voice_profile` per character —
  extend with negative locks + expression range.)*
- `location_visuals.json` — per location: visual_identity, mood, recurring_props.
- **Per-character seed lock** — a stable seed per character/scene so a re-roll keeps identity.

### 4.2 The split
```
Visual Agent (LLM)   →  scene_visual_spec  (WHAT is seen: shot, action, mood, continuity_locks)
prompt_compiler.py   →  PromptPacket       (HOW to ask: positive/negative, model, steps, cfg, seed…)
render worker        →  image.png          (ComfyUI executes)
continuity/critic    →  canon?             (accept/reject/refine)
```
`studio_visual.build_image_prompt()` already assembles positive/negative from structured parts —
**evolve it into `prompt_compiler.compile_visual_prompt(spec, style_bible, characters, locations,
model_profile) -> PromptPacket`** (the `PromptPacket` dataclass + `join_clean` exactly as sketched
by the user). It stays deterministic and unit-tested.

### 4.3 Render job (extends the existing `render_queue`)
`studio_render` already has the queue + states + asset persistence. Add: a **PromptPacket per scene**
saved to `renders/jobs/<id>.prompt.json`, a stable `seed`, `attempt`, and the ComfyUI lifecycle
`queued → loading_model → rendering → saving_asset → complete → awaiting_approval`.

### 4.4 Backend adapter (fills `studio_render.set_renderer`)

**Studio IS the app — no external generator required.** The default backend runs **in-process via
`diffusers` + torch/CUDA**, exactly like the llama.cpp sidecar and Kokoro TTS already run inside the
backend. The user downloads a checkpoint through Studio (same `model_manager` HuggingFace flow that
pulls the GGUFs) and Studio loads + generates itself. ComfyUI is an *optional* power-user backend
behind the same interface, never a requirement.

```python
class ImageBackend:                       # uniform interface, never hardwire one tool
    def healthcheck(self) -> bool: ...
    def list_models(self) -> list[str]: ...
    def render(self, packet: PromptPacket) -> str: ...   # -> local png path
    def unload(self): ...                 # free VRAM (ModelHost GPU lane)

class DiffusersBackend(ImageBackend): ... # DEFAULT — in-process SDXL/Flux via diffusers+torch
class ComfyUIBackend(ImageBackend): ...   # OPTIONAL — for users who already run ComfyUI (LoRA/ControlNet)
# later: Automatic1111Backend, CloudBackend (optional, never default)
```

**Why in-process is the right default here (verified on this machine):** torch 2.12 + CUDA is live on
the 4060 Ti; `transformers`/`safetensors`/`huggingface_hub`/`PIL` are already installed. The only new
deps are **`diffusers` + `accelerate`**. SDXL fits in fp16; FLUX.1-schnell fits in fp8 (load alone).

**Model download = the existing machinery.** Add image checkpoints to `model_manager.AVAILABLE_MODELS`
as ordinary entries (HF `resolve/main` URLs / repo ids), so Studio's download UI, progress, and
on-disk management work unchanged — an image model is downloaded the same way as a GGUF.

**Load/unload = the ModelHost GPU lane** (§3): `DiffusersBackend.render` ensures the pipeline is
loaded (`StableDiffusionXLPipeline.from_pretrained(..., torch_dtype=fp16).to("cuda")`), runs, and in
Saver mode unloads (`del pipe; torch.cuda.empty_cache()`) so the 12B writer can reclaim VRAM.

Wire it: `studio_render.set_renderer(DiffusersBackend(model_id).render)` at Studio-Mode start once the
checkpoint is present; otherwise the existing gradient fallback stands (honest, never faked).

---

## 5. Voice department — Kokoro (default) → Chatterbox (premium)

`studio_audio.py` is already pluggable. Each engine is just a `synth(text, out_path, voice) -> bool`:

- **Kokoro-82M** (default) — tiny, fast, Apache-licensed; render many narration/dialogue lines
  without hogging VRAM. Already wired via `studio_audio.kokoro_synth`.
- **Chatterbox** (premium, MIT) — higher expression; load on the GPU lane for "premium voice render"
  passes. Add `studio_audio.chatterbox_synth(project_name)` returning the `synth` callable; selected
  per-project in settings. (Dia/Dia2 Apache-2.0 is an alternative premium path.)

Per-speaker voice is already routed via `voice_for(speaker)`; map each character's `voice_profile`
to an engine voice id. Premium mode is a per-scene/zone choice so the user spends GPU time only where
it matters (hero dialogue), keeping Kokoro for bulk narration.

---

## 6. Sound department — music + ambience (new)

Two new GPU-transient workers, same adapter shape as image/voice, driven by the story's `tone`,
`motifs`, and the blueprint `emotional_arc` (already produced by the Showrunner):

- **Music — ACE-Step 1.5** (MIT, <4 GB, full-song, commercial-OK) → **default**. One score cue per
  reel or per act, keyed to `emotional_arc` (build → climax → release). Stable Audio 3 Small is an
  optional higher-quality path (community license — not the clean default).
- **Ambience/SFX — Stable Audio Open Small** → 11s stereo loops: room tone, rain, club murmur,
  footsteps, keyed to each scene's `location` + `mood`. (Community license — optional, not pure-OSS.)
- **Synced foley (V2)** — MMAudio / FoleyCrafter once animatics exist; not MVP.

```python
class AudioBackend:                       # music + ambience share this
    def healthcheck(self) -> bool: ...
    def generate(self, spec) -> str: ...  # -> local wav/mp3 path
    def unload(self): ...
```
Outputs land in `assets/audio/` (music) and `assets/audio/ambience/`; scenes gain `music_path` /
`ambience_path`; the cinematic player ducks ambience+music under narration (it already sequences
beat audio — add two looping layers).

---

## 7. Settings screen additions (the new controls)

A **Studio › Media Engine** settings section (bind to `settings.json` via the existing settings
mixins). All default to the safe/local option.

**Studio Mode gate** (from `Dispatcher.md` §2 — keep verbatim):
- Modal on entering Studio Mode: *"Are you ready for Studio Mode? It's a lot."* with
  `[Cancel] [Proceed]`, storing `studio_mode_active`.
- **Resource profile:** `Background VRAM Saver` (default) | `Speedy Pipeline`.

**Model placement & dispatcher:**
- Dispatcher model: `gemma-4-e4b-q4` (default) | `gemma-4-e2b-q4` (low-RAM) — pinned CPU.
- Writer model: `gemma-4-12b-q4` (default) | smaller — GPU transient.
- VRAM budget cap (MB) + "unload workers after each job" toggle (maps to profile).

**Per-department backend + model pickers** (each with a healthcheck dot + "not configured" honest state):
- Image: backend (**In-process Diffusers** default | ComfyUI URL | off), checkpoint download/picker
  (SDXL-anime | FLUX-schnell), steps/cfg/sampler/scheduler, base resolution, upscaler
  (Real-ESRGAN/SwinIR | off).
- Voice: engine (Kokoro default | Chatterbox premium), premium-voice scope (narration | dialogue | hero-only).
- Music: engine (ACE-Step | off), scope (per-reel | per-act | off).
- Ambience: engine (Stable Audio Open | off).

**Honesty everywhere:** every picker shows live/loaded vs fallback, mirroring the production-desk
status strip already shipped (so a user never mistakes a gradient/browser-speech/silent-reel for the
real thing). Reuse the corrupt-model lesson: surface device + load state plainly.

---

## 8. Dispatcher loop (the tie-it-together)

Per `Dispatcher.md` §3–4, made concrete against the built pipeline:

1. **Compile State Packet** — `studio_memory.compile_compact_state_packet(project, id)` →
   `{completed_stages, current_stage, roster_names, scene_count, render_counts, audio_counts,
   pending_approvals, continuity_high, grounding}`. Cheap, deterministic, the single source of truth.
2. **Ask the Dispatcher** (CPU 4B): *"Floor Manager: given this State Packet, what runs next, or do
   we need the user?"* → short structured suggestion (e.g. `{"next":"render","reason":"6 scenes
   written, 0 images"}`).
3. **Validate** against deterministic rules (prereqs on the blackboard, approval gates honored —
   never render before blueprint approval, never export before continuity).
4. **Dispatch to the GPU lane** via ModelHost: `free_gpu()`, load worker, run the stage
   (`run_showrunner` / `run_scenes` / `run_render_images` / `run_scene_audio` / music / ambience),
   write results to SQLite, unload (Saver).
5. **Loop** until a gate needs the user (blueprint approval, per-scene accept/reject) or the reel is
   export-ready.

This is the same Producer integration the overhaul plan defers to coordination with gpt — the
Dispatcher becomes the Producer's "what next" brain, with ModelHost as its hands.

---

## 9. Build order

- **P1 — Visual Prompt Compiler (no GPU).** Promote `studio_visual` → `prompt_compiler` + the three
  bibles + `PromptPacket`. *Done when:* every scene saves a structured packet + stable seed. (Unit-testable, zero VRAM.)
- **P2 — In-process Diffusers backend.** `pip install diffusers accelerate`; add an SDXL checkpoint to
  `model_manager`; `DiffusersBackend.render` wired to `studio_render.set_renderer`. *Done when:* one
  button downloads (if needed) + renders one scene PNG into the project folder — no external app.
  (ComfyUIBackend is a later optional sibling for users who already run it.)
- **P3 — ModelHost + two-lane sidecars.** CPU dispatcher (8080) + transient GPU writer (8081);
  VRAM assert on unload. *Done when:* 12B and SDXL never co-resident; VRAM returns to baseline.
- **P4 — Dispatcher loop.** State Packet compiler + Floor-Manager prompt + Producer consults it.
- **P5 — Voice premium (Chatterbox) + Music (ACE-Step) + Ambience (Stable Audio Open)** as departments.
- **P6 — Visual critic (vision model)** checks characters/outfit/location/mood/defects → continuity.
- **P7 — Settings UI** for everything in §7 + the Studio Mode gate.

Each phase keeps the honest fallback (gradient image / browser voice / silent track) so a missing or
unconfigured backend degrades, never crashes.

---

## 10. Model stack (4060 Ti 16 GB) + licensing

| Department | Default | Premium / alt | License posture |
|---|---|---|---|
| Dispatcher (CPU) | Gemma-4 E4B Q4 | E2B (low RAM) | Gemma terms |
| Writer (GPU) | Gemma-4 12B Q4 | — | Gemma terms |
| Image (GPU) | **In-process Diffusers** + SDXL anime/comic | FLUX.1-schnell (Apache-2.0, load alone); ComfyUI optional | SDXL: OpenRAIL++-M |
| Image edit/text (V2) | — | Qwen-Image-Edit (Apache-2.0, 20B — offload/quant only) | Apache-2.0 |
| Upscale | Real-ESRGAN / SwinIR / ComfyUI nodes | Upscayl (desktop) | permissive |
| Voice | **Kokoro-82M** (Apache-2.0) | **Chatterbox** (MIT) / Dia (Apache-2.0) | permissive |
| Music | **ACE-Step 1.5** (MIT, <4 GB) | Stable Audio 3 Small | ACE: MIT / SA: community |
| Ambience/SFX | Stable Audio Open Small | — | community license |
| Synced foley (V2) | — | MMAudio / FoleyCrafter | varies |

**Rule of thumb:** clean permissive (Apache/MIT) for defaults; community-licensed models are optional
"premium" toggles, never the out-of-box path. The trick was never one god model — it's the boring,
strict, repeatable machinery that makes the models behave like departments instead of raccoons in a
server rack.
