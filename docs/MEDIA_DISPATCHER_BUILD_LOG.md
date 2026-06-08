# Media Dispatcher — Build Log

Tracks the implementation of [MEDIA_DISPATCHER.md](MEDIA_DISPATCHER.md) (the media engine + model
dispatcher). Each entry: what changed, why, how it was verified. Newest at the bottom.

Build order (from the doc §9): **P1 Visual Prompt Compiler → P2 in-process Diffusers backend →
P3 ModelHost (CPU/GPU lanes) → P4 Dispatcher loop → P5 voice/music/ambience workers → P6 visual
critic → P7 settings UI.**

---

## Headstart (gpt) — download hardening + model roles + media settings
- `model_manager.py`: resumable, atomic LLM downloads (`.part` + HTTP range resume; final file only
  on completion; truncated files no longer count as installed).
- `server.py`: LLM downloads are background jobs (UI survives long downloads; duplicate clicks reuse
  the active job; state reports active/resumable/partial).
- Model catalog taxonomy added: each entry now carries `group` ("studio"), `roles`
  (`dispatcher`/`writer`), `lane` (`cpu`/`gpu-transient`), `recommended_for`, `server_args`.
- UI (`index.html`/`main.js`): "BetterFingers Core LLM" vs "Studio Media Engine"; role cards for
  Dispatcher, Smart Writer, Voice, Image, Music, Ambience, Speech Input; download polling reconnects
  to background jobs.
- Studio media settings: resource profile, dispatcher model, smart writer model, voice engine
  (Kokoro/Chatterbox), image backend, music engine, ambience engine, VRAM cap (validated).
- Tests: `tests/test_model_manager_status.py`, `tests/test_server_settings_models.py` (18 passed).
- **Not yet:** actual Diffusers/ACE-Step/Stable Audio/Chatterbox download-and-run workers — controls
  exist and the downloader is ready; the workers are the next chunks.

---

## P1 — Visual Prompt Compiler ✅ DONE
_The LLM produces a structured visual spec; deterministic code compiles the prompt + generation
params. This is the keystone that stops melted hands / wandering outfits / continuity drift._

**What changed**
- New `studio_prompt_compiler.py`:
  - `PromptPacket` dataclass (positive/negative + model/width/height/steps/cfg/seed/sampler/scheduler/metadata).
  - `build_style_bible(world)`, `build_character_visuals(characters)`, `build_location_visuals(world)` —
    derive the three visual bibles from the data the studio already holds, so a working compile needs
    no new authoring; hand-authored bibles (incl. `negative_locks`) simply improve it.
  - `stable_seed(scene_id, cast)` — deterministic, order-independent seed so re-rolls reproduce the
    same base composition and characters keep identity.
  - `compile_visual_prompt(...) -> PromptPacket` and `compile_for_scenes(scenes, world, characters,
    model_profile)` which attaches `scene['prompt_packet']` and keeps the flat `image_prompt`/
    `negative_prompt` fields in sync.
  - Default model profile tuned for 16 GB SDXL-anime (768², 24 steps, cfg 6.5, dpmpp_2m/karras).
- `studio_render.py`: **renderer contract upgraded to `renderer(packet, out_path)`** (was
  `(prompt, negative, out_path)`) so backends receive the full PromptPacket; `http_renderer` payload
  reads packet fields; module docstring updated.
- `studio_workflow.run_render_images`: compiles packets from the world/character bibles + a per-project
  `image_model_profile` preference before rendering, so every render carries reproducible params.

**Verified**
- `tests/test_studio_prompt_compiler.py` (6) + updated `tests/test_studio_render.py` (4) green.
- Full studio suite: **137 passed**, 1 unrelated pre-existing GEST failure.
- E2E smoke: `run_render_images` → backend receives a packet with positive(incl. location), stable
  seed, model/steps/cfg; image asset written.

**Notes / next**
- The compiler reads optional `negative_locks` on characters and `avoid[]` on the world — the
  settings UI / character studio can surface these later (P7) for tighter continuity control.
- Ready for **P2: in-process `DiffusersBackend`** to fill `studio_render.set_renderer` — it consumes
  exactly this packet (model/steps/cfg/seed/sampler), so no further compiler work is needed first.

---

## P2 — In-process Diffusers image backend ✅ DONE (code), ⏳ activation pending
_Studio is the app: SDXL/Flux runs in-process via diffusers+torch, no external generator._

**What changed**
- New `studio_image_backend.py`:
  - `DiffusersBackend` — lazy-imports `diffusers` only inside `ensure_loaded`, so the module imports
    fine without the dep. `render(packet, out_path)` maps the PromptPacket → pipeline call (steps→
    num_inference_steps, cfg→guidance_scale, seed→torch.Generator, scheduler via `resolve_scheduler_name`),
    saves a PNG. `unload()` frees VRAM (`del pipe; empty_cache()`) for the ModelHost GPU lane.
  - Pure, unit-tested helpers: `packet_to_kwargs`, `resolve_scheduler_name`, `diffusers_available`.
  - `make_image_backend(settings)` factory → a `render` callable or **None** (off / deps-missing /
    no-CUDA / no-model → gradient fallback, never faked).
- `studio_workflow.run_render_images`: self-installs the configured backend via
  `studio_render.set_renderer` when available; no-op otherwise.

**Verified**
- `tests/test_studio_image_backend.py` (6, pure logic — no model load) green; full studio suite **143 passed**.
- Module imports + healthchecks False cleanly on this box (diffusers not yet installed).

**Activation (the remaining, user-gated step)**
1. `pip install diffusers accelerate` (torch+CUDA already present and working).
2. Get an SDXL-anime/comic checkpoint into the models dir (ideally as a catalog entry so Studio's own
   hardened resumable downloader pulls it — see P2.5 below).
3. Set project/settings `image_settings = {"image_backend":"diffusers","image_model_path":"<path>"}`.
   Then `run_render_images` renders real scene images; the player already prefers `image_path`.

**Next: P2.5 — image model in the catalog.** Add a media-model descriptor (kind=diffusers,
single-file safetensors) so the existing download UI/queue installs it; coordinate with gpt's
`model_manager` catalog (currently GGUF/llama-server-oriented).

---

## P2.5 — Activation: in-app image model download + real render ✅
_User chose full activation. Studio downloads + runs the model itself; verified a real image._

**What changed**
- `pip install diffusers accelerate` (torch 2.12+cu130 + transformers/safetensors/hf_hub/PIL were
  already present). `diffusers_available()` → True on the 4060 Ti.
- `studio_image_backend.py` gained an **image-model catalog** (`IMAGE_MODELS`) + downloader that
  reuses `huggingface_hub` into the app's models dir: `image_model_path/installed`, `ensure_image_model`,
  threaded `start_download`/`download_state`, `list_image_models`. Default model: **Animagine XL 4.0**.
- Server endpoints (Studio is the app it's run through): `GET /studio/models/image`,
  `POST /studio/models/image/{key}/download`, `GET /studio/models/image/{key}/download-state`.
- **Auto-activation:** `make_image_backend({})` defaults to the catalog model's local path, so once the
  model is present `run_render_images` installs the renderer with zero settings (gradient fallback otherwise).

**Real-world finding (and fix):** the single-file `from_single_file` SDXL path **crashes against
transformers 5.x** (`CLIPTextModel has no attribute 'text_model'` — diffusers 0.38's LDM→CLIP
conversion). transformers 5 is **pinned by Kokoro TTS**, so downgrading is off the table. Fix:
download + load the repo's **diffusers-format layout via `from_pretrained`** (catalog
`format: "diffusers"`, `snapshot_download` skipping the redundant root single-file). The backend
loader now prefers a diffusers directory; single-file remains a fallback for other models.

**Verified:** unit tests green (16); real 768² render completed end-to-end:
downloaded diffusers snapshot → compiled PromptPacket → loaded pipeline → wrote
`/tmp/studio_render_test.png` (768×768 RGB, ~1.0 MB) → VRAM dropped back under 1 GB after unload.

**Follow-up verification/fixes (Codex, 2026-06-08)**
- Fixed `DiffusersBackend.render` to honor the packet's `sampler`/`scheduler` instead of always
  using the default scheduler. This keeps the Visual Prompt Compiler's render parameters real.
- Wrapped the default Diffusers renderer in VRAM-saver behavior: unless settings choose `speedy`,
  the backend unloads after each render and frees CUDA cache.
- Hardened image-model background downloads with a lock + active thread reuse so repeated clicks
  don't spawn duplicate snapshot downloads.
- Removed the now-unusable single-file checkpoint
  `/home/donaven/BetterFingers/models/animagine-xl-4.0-opt.safetensors` and kept the working
  diffusers-format snapshot.
- Verification:
  - `.venv/bin/python -m pytest tests/test_studio_image_backend.py tests/test_studio_render.py tests/test_studio_prompt_compiler.py -q`
    → 18 passed.
  - `.venv/bin/python -m pytest tests/ -q -k "studio and not scene_endpoint_commits_and_rejects"`
    → 145 passed, known unrelated GEST test excluded.
  - `npm run build` from `app/` → passed.
