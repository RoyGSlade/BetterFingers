# Image Generation — Plan & Status

Scope: rendering one image per cinematic scene, with the prompts pre-compiled and queued, fed to
an in-process image model, played back in the reel. Grounded in the actual code as of 2026-06-08.

## TL;DR — it's already wired and ready on this machine

The image pipeline is **fully built**. On Bulldozer right now:

- `studio_image_backend.image_model_installed()` → **True** (Animagine XL 4.0 downloaded)
- `studio_image_backend.diffusers_available()` → **True** (diffusers + `torch 2.12.0+cu130`, CUDA on)
- Prompts are **pre-compiled and attached to every scene** before rendering.

The only thing that was blocking it is the same VRAM contention that broke the score: the 12B was
never unloaded, so the SDXL pipe had no room. That fix (`_free_llm_for_media("image rendering")`
at the top of `run_render_images`) is now in place. **So: restart the backend, click "Render
Images", and the 9 scenes should render.**

## Architecture (what exists today)

```
scene.image_prompt ──► studio_prompt_compiler.compile_for_scenes()
                          └─ attaches scene["prompt_packet"] = {positive, negative,
                             width, height, steps, cfg, seed, sampler, scheduler}
                                   │
run_render_images() ──► _free_llm_for_media("image rendering")   # unload 12B → free VRAM
                     ──► studio_image_backend.make_image_backend(prefs) → DiffusersBackend
                     ──► studio_render.set_renderer(fn)
                     ──► studio_render.render_scenes(...)         # queue: queued→rendering→done
                                   │  renderer(packet, out_path) -> bool
                                   ▼
                          assets/images/scene-<id>.png  +  scene["image_path"]/["image_status"]
```

Key files:
- `studio_prompt_compiler.py` — turns each scene + world/character bibles into a reproducible
  `PromptPacket` (positive/negative + steps/cfg/seed/sampler). **This is the "preloaded prompts"
  the request asked for — already done.** Seed is derived deterministically from scene id + cast
  (`stable_seed`) so re-renders are reproducible.
- `studio_image_backend.py` — `DiffusersBackend` loads Animagine XL 4.0 (diffusers format, avoids
  the broken single-file CLIP conversion against transformers 5.x), renders, and `unload()`s VRAM.
  `make_image_backend()` returns a `render(packet, out_path)` callable or `None` (→ gradient
  fallback, never faked). Unloads after each render unless `resource_profile == "speedy"`.
- `studio_render.py` — backend-agnostic queue; persists per-scene state to `render_queue`; honest
  `unavailable` when no renderer. Also ships an optional `http_renderer` for ComfyUI/A1111 later.
- `run_render_images()` in `studio_workflow.py` — orchestrates the above; `/studio/workflow/stage`
  with `stage="render"` and the **Render Images** UI button call it.

## Status checklist

- [x] Image model catalog + background download (`IMAGE_MODELS`, `start_download`)
- [x] In-process diffusers SDXL backend (load / render / unload)
- [x] Visual Prompt Compiler → per-scene `prompt_packet` (positive/negative/steps/cfg/seed)
- [x] Render queue with explicit states + persistence
- [x] Self-installing renderer in `run_render_images` (no manual `set_renderer` needed)
- [x] **VRAM: unload the 12B before rendering** (the fix that unblocks it)
- [x] Honest gradient fallback when unavailable
- [x] Animagine XL 4.0 installed + diffusers/CUDA present on this machine
- [ ] **Verify end-to-end on GPU** (restart → Render Images → 9 PNGs) — not yet confirmed
- [ ] Live per-scene progress in the production desk (currently only a rollup count)
- [ ] Per-scene "re-roll this image" button in the player/approval view
- [ ] Resolution/aspect control (currently fixed 768×768; reels likely want portrait/landscape)
- [ ] Character-consistency pass (seed lock is in; consider IP-Adapter/reference later)
- [ ] Error surfacing when a render fails (status flips to `failed` but UI message is thin)

## Plan — remaining work (priority order)

### P0 — Verify it actually renders (no code; needs the GPU box)
1. Restart the backend so the VRAM-unload + renderer changes are live.
2. Open the project → **Render Images**.
3. Watch `debug.log`: `Unloading the LLM to free VRAM for image rendering` → `Rendering image for
   scene 1 of 9 …` → `Rendered 9/9 scene images (renderer available)`.
4. Confirm PNGs in `<project>/assets/images/scene-*.png` and that the player shows them.
   - If it OOMs: SDXL at 768² + Animagine needs ~6–8 GB; with the 12B unloaded that should fit.
     If not, lower `width/height` in the compiler profile or keep `unload_after_render` on (default).

### P1 — Live progress + per-scene status
- The stage already calls `progress("Rendering image for scene i of N…")`; surface that in the
  Cinematic Production panel (it currently only refreshes the rollup `Images: x/9` after the run).
- Add per-scene image state to `/studio/projects/{name}/scenes` (already returns `image_done`)
  and show a small per-scene badge.

### P2 — Per-scene re-roll
- Reuse `regenerate_scene(scene_id, target="image")` (exists) wired to a button on each scene card
  / player frame, so a bad image can be re-rolled without re-running all 9. Re-roll should bump the
  seed (the compiler's `stable_seed` makes the default reproducible; a re-roll should randomize).

### P3 — Aspect ratio / resolution
- Add a project setting (portrait 832×1216 / landscape 1216×832 / square 1024²) → compiler profile
  → packet `width/height`. SDXL is trained for ~1024²; 768² is conservative for VRAM.

### P4 — Quality / consistency (optional, later)
- Stronger default negative prompt; per-character visual anchor (seed already locked by cast).
- IP-Adapter / reference image for face consistency across scenes (bigger effort).
- ComfyUI path via `studio_render.http_renderer` for users who run Comfy instead of in-process.

## VRAM / serialization rule

One GPU, serialized lanes. Each heavy model must have the card to itself:

`12B writer` → (unload) → `image diffusers` → (unload) → `Chatterbox TTS` → (unload) → `ACE-Step`

`run_render_images` unloads the 12B first; `DiffusersBackend` unloads after each render (saver
profile). When chaining stages, run them sequentially (the per-stage `_free_llm_for_media` +
`unload_after_render` keep the card clear for the next model).

## Open questions for the user
- Aspect ratio preference for the reel (portrait for phone-style scroll, or landscape/cinematic)?
- Re-roll UX: per-scene button in the **player**, the **approval cards**, or both?
- Keep the model resident between scenes for speed ("speedy" profile, more VRAM) or unload after
  each for safety ("saver", default)?
