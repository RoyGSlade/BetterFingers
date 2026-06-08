# Studio Cinematic Storytelling Recommendations

## Summary

BetterFingers Studio should continue evolving into a local-first cinematic storytelling studio: a place where users can provide a seed, a voice note, or a full manuscript, then shape that material into scene-based reels with persistent canon memory, authored narration, user approval gates, local media generation, and continuity checks.

The important recommendation is not to restart. Much of the cinematic spine already exists:

- `studio_loremaster.py` reads the whole story and distills source material into structured understanding.
- `studio_showrunner.py` creates dynamic scene blueprints with setup/payoff tracking.
- `studio_scriptwriter.py` writes per-scene narration and dialogue instead of forcing comic balloons.
- `app/src/renderer/cinema.html` plays scenes as a scrolling cinematic reel.
- `server.py` exposes stage endpoints, scene retrieval, and scene regeneration.
- Focused tests already cover the Loremaster, Showrunner, and Scriptwriter paths.

The next work should finish integration and user experience around that spine so the default Studio workflow becomes cinematic, reviewable, and media-producing.

## Key Recommendations

### Make Cinematic The Default Pipeline

The current Producer still defaults to the older panel-oriented chain:

```text
intake -> casting -> world -> characters -> treatment -> planner -> scene -> panels -> continuity
```

The default Studio path should become:

```text
intake -> loremaster -> world -> characters -> showrunner -> blueprint approval -> scenes -> continuity -> export
```

Keep the old panel/GEST flow available behind a clear mode flag such as `legacy_panels` or `director_simulation`. That preserves useful experimental work without letting it compete with the cinematic reel path users are trying to experience first.

### Strengthen The Approval Model

The Showrunner blueprint should become a real user gate, not just an artifact marked `needs_user_review`.

Recommended behavior:

- Add a blueprint approval screen before scene generation.
- Let users edit, reorder, delete, and rename scenes before expensive script, image, and audio work.
- Keep the existing per-scene Accept / Reject / Refine controls in the cinematic player.
- Store approval state in project memory so accepted scenes become canon only after user approval.

The user should feel like a producer approving a scene list, then refining individual scenes, instead of watching a one-shot prompt pipeline race past them.

### Turn Scene Prompts Into Real Media

Scenes already include strong image prompts, but the player currently falls back to gradients unless `scene.image_url` exists. Add a rendering stage that consumes each scene's `image_prompt` and writes the generated local asset back onto the scene.

Recommended behavior:

- Add a backend image-rendering stage for scene assets.
- Persist generated images under the project-local asset folder.
- Update scenes with `image_url` or `image_path`.
- Prefer local-first rendering when available.
- Preserve the deterministic gradient fallback when rendering is unavailable.
- Add a simple render queue with `queued`, `rendering`, `done`, and `failed` states.

This is likely the biggest visible upgrade because the cinematic player is already built to use rendered images when they exist.

### Upgrade Narration And Sound

Browser `SpeechSynthesis` is useful as a zero-dependency fallback, but it should not be the primary Studio voice path. Use Kokoro or another local TTS path to render narration beats into project-local audio files.

Recommended behavior:

- Render each narration beat to local audio.
- Store audio paths and timing metadata on each beat.
- Update the cinematic player to play stored audio when present.
- Fall back to browser speech when local audio is missing.
- Add scene-level ambience, music, and sound cues later, ducked under narration.

The goal is for a generated reel to feel performed, not merely read by the browser.

### Repoint Continuity Around Scenes

Continuity should audit the new scene spine rather than only panel rows. Panels can remain a compatibility mirror, but `scenes[]` and `scene_blueprint.setups[]` should become the source of truth for cinematic story quality.

Recommended behavior:

- Audit `scenes[]`, `scene_blueprint.setups[]`, and approved canon.
- Verify every setup has a payoff or is intentionally unresolved.
- Check scene-to-scene emotional and timeline continuity.
- Emit user-readable continuity warnings with repair suggestions.
- Route warnings into scene-level regeneration where possible.

This turns callbacks, motifs, and planted details into things the system can protect.

### Improve Studio UX Identity

Studio Mode should feel like a compact production desk, not a prompt box. The first screen should make the current project state obvious.

Recommended first-screen signals:

- Current project and source/story seed.
- Blueprint status.
- Scene count and scene status.
- Render queue status.
- Model status and whether fallback output was used.
- Approval queue.
- Continuity warnings.

Recommended mode controls:

- `Just make it`
- `Ask me first`
- `Approve every stage`
- `Producer mode`

Also surface model/fallback status honestly. Procedural fallback output is useful, but users should never mistake it for live LLM quality.

## Suggested Implementation Phases

### 1. Producer Integration

- Update `studio_agents.py` so the default registry uses the cinematic stages.
- Halt after Showrunner when the blueprint status is `needs_user_review`.
- Add a resume path that continues from an approved blueprint into `run_scenes`.
- Keep legacy panel/GEST behavior behind an explicit mode flag.

### 2. Blueprint Approval UI

- Add a scene blueprint editor in the Studio tab.
- Bind it to existing storyboard and blueprint memory.
- Let users edit, reorder, delete, and rename scenes.
- Only enable `Generate Scenes` once the blueprint is approved or the user explicitly bypasses approval.

### 3. Image Rendering Stage

- Add backend support for rendering scene images from `image_prompt`.
- Persist generated assets under the project-local asset folder.
- Update scenes with `image_url` or `image_path`.
- Keep the existing cinematic player fallback behavior.

### 4. Local TTS Scene Audio

- Add a stage that renders each narration beat through Kokoro or another local TTS engine.
- Store audio timing metadata on each beat.
- Update `cinema.html` to play stored audio when present.
- Fall back to browser speech when no local audio exists.

### 5. Scene Continuity And Export

- Add a scene-based continuity audit.
- Verify setup/payoff threads.
- Export cinematic scene data, images, audio, subtitles, and timing as a preview reel folder first.
- Add MP4 export after the folder-based reel path is stable.

## Test Plan

Run the existing focused tests for the new cinematic spine:

```bash
.venv/bin/python -m pytest tests/test_studio_loremaster.py tests/test_studio_showrunner.py tests/test_studio_scriptwriter.py -q
```

Add or update tests for:

- Producer defaults to the cinematic pipeline.
- Producer halts at blueprint approval.
- Resume after approval generates scenes.
- Scene regeneration changes only the requested target: script, image, or both.
- Scene image rendering writes project-local asset paths.
- TTS rendering stores per-beat audio metadata.
- Continuity audit detects unpaid setup/payoff threads.
- Cinematic player endpoints return scenes, blueprint, media paths, and statuses.

Run the broader Studio regression after implementation work:

```bash
.venv/bin/python -m pytest tests/ -q -k studio
```

## Assumptions And Defaults

- BetterFingers continues mutating into Source Arcanum Studio for now rather than splitting repos immediately.
- The default output target is a cinematic scene reel with scrolling authored narration, not a fixed 12-panel comic.
- The default approval behavior is to pause at blueprint approval, then allow per-scene refinement.
- Project-local database and assets remain the source of truth.
- Media generation is local-first when available, with deterministic fallbacks when unavailable.
- The panel/GEST path remains preserved behind a flag until it is integrated cleanly or retired.
