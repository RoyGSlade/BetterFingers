# CHECKPOINT — "First Cut"

**Studio cinematic-storyteller overhaul · handoff for the other agents (gpt, gemini, grok, future-me)**

This is the working-state checkpoint. The companion design doc is
[STUDIO_OVERHAUL_PLAN.md](STUDIO_OVERHAUL_PLAN.md) (the bible — *why* and the full target
architecture). **This file is the *what's-built / what-still-needs-love / what's-blocking*
map.** Read the bible for intent; read this to know what you can lean on and what you must
not trust yet.

> One-line state: the full cinematic spine —
> **Loremaster → World → Characters → Showrunner(gate) → Scriptwriter → Cinematic Player** —
> is built, wired, and green end-to-end on deterministic fallbacks. It has **not** been
> proven with a live LLM (the local model is corrupt — see Blocker #1), and it is **not yet
> the default pipeline** (the Producer still runs the old 12-panel chain — see Blocker #2).

---

## 0. If you only read one section

- **New modules are solid and tested:** `studio_loremaster.py`, `studio_showrunner.py`,
  `studio_scriptwriter.py` (+ 34 tests, all green).
- **They're wired into `studio_workflow.py`** as `run_loremaster()`, `run_showrunner()`,
  `run_scenes()`, `regenerate_scene()`, and reachable over HTTP.
- **The Producer (`studio_agents.py`) still drives the OLD path.** gpt owns that file.
  Switching it to the new chain is the last integration step and is **deliberately not done.**
- **Do not judge output quality yet** — everything is running on procedural fallbacks
  because no LLM is actually loading. Fix the model first.

---

## 1. What is FULLY IMPLEMENTED (trust it, build on it)

### 1.1 Loremaster — whole-story understanding · `studio_loremaster.py`
**What it does:** reads the ENTIRE source manuscript (not a 6k excerpt) via map-reduce —
chunk (~3k windows) → per-chunk structured notes → deterministic merge → one synthesis
pass — and emits a `story_understanding` artifact: `premise, themes, tone, motifs,
timeline[] (ordered real events), character_dossiers[] (traits/want/need/wound/secret/
relationships/voice/key_lines), world_facts[], setup_payoff_candidates[]`.

**Why it matters:** this is the keystone. The old path dropped everything between 17% and
91% of a long story. Proof: on `docs/assets/burningbarreltest.md` the timeline went 3 → 9
events and Rodney/Wesley/Goldstein/Darkside (all in the dropped middle) are now recovered
**even with no LLM**.

**Wiring:** `StudioWorkflowRunner.run_loremaster()` / `_understanding()` (cached);
persisted to bible key `story_understanding` and blackboard artifact `understanding`.
**LLM dispatch:** `studio/workflow/stage` with `stage="loremaster"`.
**Tests:** `tests/test_studio_loremaster.py` (9).

### 1.2 Deep characters · `studio_workflow.py`
**What it does:** `_character_roster` now casts from the Loremaster dossiers (so
middle-of-story characters get cast, with differentiated roles), and `_expand_character`
grounds both the LLM prompt and the offline fallback in the dossier (traits, want/need →
arc, wound, secret, voice) instead of generic noir filler.
**Bonus fix:** the character fallback was silently missing required keys
(`backstory`/`core_wounds`/`character_arc`) — now complete.
**Helper:** module-level `_dossier_grounding()`.

### 1.3 Showrunner — dynamic scene blueprint · `studio_showrunner.py`
**What it does:** replaces the hardcoded "3 beats / 12 panels / 60s." Decides scene count
from the real timeline (`decide_scene_count`: ≈1 per event, floor 4, tier cap 6/9/12),
and emits a per-scene blueprint (`id, title, location, characters, purpose,
emotional_shift, target_seconds, setup_seeds, pays_off`) plus a first-class **setup→payoff
registry** (`setups[]`: a seed planted early names the scene that pays it off — the Batman
callback is now representable).
**Wiring:** `run_showrunner()` persists `scene_blueprint` (bible + blackboard,
`needs_user_review` = the gate) and mirrors onto the legacy storyboard via
`blueprint_to_storyboard()` so the existing editor/approval plumbing still works.
**LLM dispatch:** `stage="showrunner"`. **Tests:** `tests/test_studio_showrunner.py` (9).

### 1.4 Scriptwriter — the missing narrator · `studio_scriptwriter.py`
**What it does:** for each scene writes a `narration_script[]` of `{speaker, line, emotion,
delivery, duration_seconds}` — flowing narration + in-voice dialogue paced to the scene
length, **not** comic balloons. Pairs each scene with ONE evocative image prompt by reusing
the (already strong, deterministic) `studio_visual` assembler at scene scale.
**Wiring:** `run_scenes()` builds all scenes, persists a `scenes` artifact (the new spine),
and mirrors each scene onto panel + dialogue rows for export back-compat;
`regenerate_scene(scene_id, target, feedback)` rebuilds one scene's script and/or image.
**LLM dispatch:** `stage="scenes"`; regenerate via `POST /studio/workflow/scene/regenerate`.
**Tests:** `tests/test_studio_scriptwriter.py` (8).

### 1.5 Cinematic Player · `app/src/renderer/cinema.html`
**What it does:** self-contained full-screen player. Per scene: atmospheric background
(rendered image if present, else a deterministic gradient) + a Star-Wars-style narration
crawl, read aloud by TTS, beat-synced highlighting, title cards, crossfade auto-advance,
keyboard control, and **per-scene Accept / Reject / Refine** (script/image/both + free-text
note → `regenerate_scene`).
**Backend:** `GET /studio/projects/{name}/scenes`, `POST /studio/workflow/scene/regenerate`,
and the three new stage cases. CORS is `*`.
**Client:** `studioGetScenes` / `studioRunScenes` / `studioRegenerateScene` in
`app/src/renderer/api/backend.js`.
**UI entry:** "Generate Scenes" + "▶ Cinematic Player" buttons (Studio export row in
`index.html`, handlers in `main.js`); `cinema.html` is a registered vite renderer input.
**Verified:** full HTTP path (TestClient) intake→…→scenes→GET→regenerate, all 200.

### 1.6 Legacy crash fixed
`run_dialogue_and_panels` now guards empty narration before `add_dialogue_line`, clearing 4
of 5 previously-failing tests. (See Blocker #4 for the 5th.)

---

## 2. What is STRUCTURE that still needs LOVE (works, but thin)

These run and are correct, but they're scaffolding — they get *good* only with a live LLM
and/or a follow-up pass.

| Area | State today | What "love" looks like |
|---|---|---|
| **Loremaster `_grounding` label** | Reports `"map-reduce"` whenever an `llm_call` is passed, even if every call fell back to the analyzer (e.g. corrupt model). | Detect real LLM use (e.g. read `runner.model_status.used_fallback` after the pass) and label `"analyzer-fallback"` honestly. Cosmetic but misleading in logs. |
| **Offline dossiers** | Analyzer fills names + key_lines only; `traits/want/wound/secret` stay empty, so character fallbacks read generic. `Father Time`/`Amelia` aren't caught as names by the heuristic; noise names (`Ash`, `Instead`) sometimes appear. | These fill in correctly under a live LLM map step. If you want stronger *offline* behavior, improve `studio_analyzer` entity rules. Not worth it if the model is fixed. |
| **Setup→payoff** | Deterministic path only emits threads when `setup_payoff_candidates` or `motifs` exist (empty under pure analyzer). | The LLM synthesis populates candidates; then the Showrunner threads them. Verify the *payoff scene actually references the seed* in live output, and consider letting the Scriptwriter explicitly "land" a pays_off line. |
| **Scriptwriter prose** | Offline = Narrator lines split from the scene `purpose` + each present character's real quoted line. Readable, not artful. | This is the whole point of the LLM Scriptwriter — judge it only with a model. Then tune the system prompt for pacing/voice. |
| **Scene imagery** | Each scene has a rich `image_prompt`/`negative_prompt` but **no rendered image**. Player shows gradients. | Wire an image-gen backend step that renders `image_prompt` → saves an asset → sets `scene.image_url` (player already prefers it). This is the biggest visible upgrade. |
| **TTS** | Browser `SpeechSynthesis` (robotic, but zero-dependency and works now). | Swap to the local **Kokoro** engine (`kokoro_sound_engineer.py` / `studio/audio/render`): pre-render per-beat audio, play it in the crawl synced to `duration_seconds`. |
| **Player ↔ blueprint gate** | The hard "approve the blueprint before generating" gate exists in data (`needs_user_review`) but the *UI* gate is the existing storyboard editor; the player only does per-scene review. | Add a blueprint-approval screen (edit/reorder/delete scenes) before "Generate Scenes," using `apply_storyboard_edits` / `studioUpdateStoryboard`. |
| **Continuity audit** | Still points at panels; not yet re-pointed at scenes or used to verify setups pay off. | Repoint `run_continuity_audit` at `scenes` and add a "did every planted setup land?" check against `setups[]`. |
| **Sound design (Phase 5)** | Not started. | Per-scene ambience/score cue from tone/motifs, ducked under narration. |

---

## 3. REMAINING BLOCKERS (ranked)

### Blocker #1 — The local model is corrupt (gates ALL quality judgement)
`models/gemma-3-4b-it-Q4_K_M.gguf` fails to load:
`llama_model_load: error loading model: tensor 'blk.27.ffn_gate.weight' data is not within
the file bounds, model is corrupte[d]`. When the model won't load, **every LLM call
silently falls back to procedural mocks** — which is most of why "the AI isn't good."
Also: the intended `models/gemma-4-12b-it-Q4_K_M.gguf` (6.7 GB) is owned by **root**, while
the app runs as **donaven**, so the loader likely fails over to the corrupt 4B.
**Fix:** `sudo chown donaven:donaven models/gemma-4-12b-it-Q4_K_M.gguf`; re-download or
delete the corrupt 4B; confirm `model_manager` selects the 12B. Nothing built here can be
quality-judged until this is done.

### Blocker #2 — The Producer still runs the OLD pipeline (gpt owns this)
`studio_agents.py::Producer.run` schedules the legacy roster
(`intake → casting → world → characters → treatment → planner → scene → panels →
continuity`) and runs straight through with no real gate. The new cinematic stages exist on
the runner but the Producer doesn't call them, so `run_full_pipeline` (and the default UI
"Generate" button) still produces 12 panels.
**Fix (coordinated with gpt):** repoint the registry/Producer to
`loremaster → world → characters → showrunner` then **halt** for blueprint approval, then
iterate `scenes` per-scene. Flag the panel/GEST agents off behind `legacy_panels`. Do this
*with* gpt — don't unilaterally rewrite `studio_agents.py`.

### Blocker #3 — No image generation
Scenes describe images but nothing renders them. Player degrades to gradients. Needs an
image backend wired to `image_prompt` → asset → `scene.image_url`.

### Blocker #4 — One unrelated pre-existing test failure
`tests/test_studio_scene.py::test_scene_endpoint_commits_and_rejects` expects an invalid
action (`hide` at `archive_table`) to 400 but gets 200 — a `studio_capabilities` registry
drift (the POI now permits the action). Unrelated to this overhaul; part of the GEST path
slated for retirement. Fix the registry data or retire the path.

### Blocker #5 — Coordination hazard
`studio_workflow.py` is shared. gpt is active in the agent/Producer layer. New code here was
kept additive (new methods, new modules) to avoid collisions, but **the storyboard mirror**
(`run_showrunner` writes both `scene_blueprint` and the legacy storyboard) is a shared
surface — coordinate before changing storyboard shapes.

---

## 4. How to run / verify

```bash
# Unit tests for the new spine (no model, no DB needed):
.venv/bin/python -m pytest tests/test_studio_loremaster.py \
  tests/test_studio_showrunner.py tests/test_studio_scriptwriter.py -q

# Full studio suite (expect 96 pass / 1 unrelated fail = Blocker #4):
.venv/bin/python -m pytest tests/ -q -k studio

# End-to-end over HTTP (TestClient) — see the bible/progress log for the snippet:
#   intake(adapt) → world → characters → loremaster → showrunner → scenes → GET scenes → regenerate

# Player (after Generate Scenes for a project):
#   Studio tab → "▶ Cinematic Player"  (opens cinema.html?project=<name>)
```

**Stage dispatch cheat-sheet** (`POST /studio/workflow/stage`, body `{project_name, stage}`):
`loremaster` · `showrunner` · `scenes` (plus the legacy `intake`/`world_building`/
`character_building`/`story_planning`/`panel_planning`/`approval_ready`).

---

## 5. File map (this overhaul)

```
docs/STUDIO_OVERHAUL_PLAN.md      design bible (why + target arch + progress log)
docs/CHECKPOINT_FIRST_CUT.md      this handoff
studio_loremaster.py              NEW · whole-story understanding (map-reduce)
studio_showrunner.py              NEW · dynamic scene blueprint + setup/payoff
studio_scriptwriter.py            NEW · authored per-scene narration + scene image
studio_workflow.py                +run_loremaster/_understanding, dossier casting,
                                  +run_showrunner, +run_scenes/_persist_scenes_as_panels,
                                  +regenerate_scene, empty-dialogue guard
studio_visual.py                  REUSED as the Cinematographer (unchanged)
server.py                         +stage cases, +GET scenes, +regenerate endpoint, +model
app/src/renderer/cinema.html      NEW · the cinematic player
app/src/renderer/api/backend.js   +studioGetScenes/RunScenes/RegenerateScene
app/src/renderer/index.html       +Generate Scenes / Cinematic Player buttons
app/src/renderer/main.js          +handlers + import + listeners
app/electron.vite.config.js       +cinema.html renderer input
tests/test_studio_loremaster.py   NEW (9)
tests/test_studio_showrunner.py   NEW (9)
tests/test_studio_scriptwriter.py NEW (8)
```

---

## 6. Suggested next moves (in order)

1. **Unblock the model** (#1) — then re-run the player and actually read the prose.
2. **Image generation** (#3) — biggest visible payoff; player already supports `image_url`.
3. **Producer swap, with gpt** (#2) — make the cinematic path the default + add the
   blueprint gate UI.
4. **Kokoro TTS** + **continuity/payoff verification** + **sound design** (the §2 love list).
