# Studio Overhaul Plan — The Bible

**Status:** Active build doc. This is the single source of truth for the Studio
storyteller overhaul. Update it as phases land. Every contributor (human + agents)
works off this file.

**Companion docs:** [CHECKPOINT_FIRST_CUT.md](CHECKPOINT_FIRST_CUT.md) (what's built /
blockers / handoff) and [STUDIO_CINEMATIC_STORYTELLING_RECOMMENDATIONS.md](STUDIO_CINEMATIC_STORYTELLING_RECOMMENDATIONS.md)
(gpt's recommendations — reviewed and folded into **§9** below).

**Goal in one sentence:** Turn Studio from a 12-panel comic assembler into a
**cinematic, scene-based storyteller** — variable-length scenes, each an evocative
background image with *authored* narration/dialogue that scrolls (Star-Wars style)
while TTS reads it — built by structured agents that read the **whole** story, hold
deep character/world memory, and let the user approve and refine scene by scene.

---

## 0. The core diagnosis (why it's weak today)

The model is **not** the bottleneck. Gemma 12B is plenty for a scene at a time. The
system starves and mis-tasks it. The four root causes, in priority order:

1. **The story is amputated before any agent sees it.**
   `STORY_CONTEXT_CHARS = 6000` (`studio_workflow.py:27`); the test story is 22,777
   chars. `_story_excerpt` keeps head+tail and splices `"[... middle omitted ...]"`.
   ~73% of the story — the betrayal (the inciting incident) and the Father Time /
   burning-barrel awakening — is **invisible to every LLM stage**. This is the real
   cause of "it doesn't know what's important." Not memory wiring. Missing input.

2. **Everything is crushed into "60 seconds / 3 beats / 12 panels."**
   Hardcoded in the treatment prompt (`:1405`), the planner (`:1460`, `:1484`), the
   analyzer (`segment_beats(n=3)`), and `assemble_panels` (`target=12`, `:1709`). A
   slow-burn novella cannot breathe in 3 beats.

3. **The unit of generation is a comic balloon, not a scene.**
   The back half (`run_shot_list → assemble_panels → _apply_dialogue`) makes the model
   do layout math ("a comic balloon, keep each line short", `:1833`). Dialogue is
   sliced to fit boxes (`_distribute_dialogue`, `:1592`). This is the "how many words
   go on there" confusion.

4. **There is no narration author.** When no quote exists, "narration" is
   `sentence_safe_trim(shot.action, 160)` (`:1739`) — a clipped stage direction.
   No agent ever writes the flowing prose that gets read aloud. (The image side,
   `studio_visual.py`, *is* structured + deterministic — which is exactly why it's the
   strongest component today.)

Secondary causes:

5. **Hollow characters** — the bible schema is already rich
   (`backstory, core_wounds, secrets, relationships, character_arc`,
   `studio_workflow.py:45`), but `_expand_character` (`:1264`) fills it from a
   2-sentence premise + one quote, and runs *before* the story is understood. Slots
   exist; nothing fills them with real substance.

6. **No real Director / no setup→payoff data.** The "storyboard" is `{name,summary}×3`.
   Nothing in the data model represents a planted seed paid off later (the Batman
   "you sacrificed your footing" callback is mechanically impossible).

7. **The gate isn't a gate.** `Producer.run` (`studio_agents.py:142`) runs all 9
   agents straight through; the storyboard "needs_user_review" status is written but
   never halts the run. No per-scene reject/refine loop.

8. **Two half-connected pipelines.** A Director/physics path (`casting →
   run_scene_round → finalization`, GEST graph, `studio_scene.py`) and a narrative
   path (`treatment → planner → shots → panels`) both run and don't reconcile. (The
   "small version + big version" the project owner described.)

---

## 1. Design principles (the spirit of the build)

- **Retrieve all context first, generate later.** No agent writes prose until the
  whole story has been read and distilled. Reading is cheap; regret is expensive.
- **One small, focused ask per call.** Gemma thrives summarizing a 3k chunk or
  writing one scene. It drowns swallowing 22k or emitting a whole reel. Keep every
  call schema-checked and small (reuse `studio_generation` tiers + batching).
- **Separate the three jobs:** *decide the scenes* (Showrunner) ≠ *write the scene*
  (Scriptwriter) ≠ *draw the scene* (Cinematographer = existing `studio_visual`).
- **The user steers at gates, not in the weeds.** Hard pause after the blueprint;
  per-scene accept/reject/refine after each scene draft. Effort is opt-in: one button
  makes a story from nothing; giving a manuscript makes it richer.
- **Deterministic fallbacks never vanish.** Every LLM stage keeps a grounded
  procedural fallback so a missing sidecar degrades, never crashes.
- **Keep what's good.** `studio_visual.py`, the blackboard, the rich schema, the
  model-tier batching, the fallback discipline. Retire the 12-panel forcing and the
  GEST/physics path from the default flow (flag, don't delete).

---

## 2. Target architecture

Pipeline (default cinematic path):

```
understanding → world → characters → storyboard ──[USER GATE]──┐
                                                               │
            ┌──────────── per scene, iterated ────────────────┘
            ▼
   scriptwriter → cinematographer (→ sound) ──[USER ACCEPT/REJECT/REFINE per scene]
            │
            ▼
   continuity (verifies scene-to-scene + setups actually pay off) → export
```

### Agents / modules

| Module | Role | Status | Reads | Writes |
|---|---|---|---|---|
| `studio_loremaster.py` *(new)* | **Loremaster/Analyst** — map-reduce the *whole* story | BUILD | full source text | `story_understanding` |
| `studio_workflow.run_world_building` | World Builder | KEEP, repoint | `story_understanding` | `world` |
| `studio_workflow.run_character_building` | Character Creator | KEEP schema, repoint | `story_understanding`, `world` | `characters` |
| `studio_showrunner.py` *(new)* | **Showrunner** — dynamic scene count + blueprint + setup/payoff | BUILD | understanding, world, characters | `storyboard` (scenes) |
| `studio_scriptwriter.py` *(new)* | **Scriptwriter** — authored narration + dialogue per scene | BUILD | one scene + memory | scene `narration_script` |
| `studio_visual.py` | **Cinematographer** — one image prompt per scene | KEEP, call per-scene | scene + world + chars | scene `image_prompt` |
| `kokoro_sound_engineer.py` | Sound cue per scene | LATER | scene | scene `audio` |
| `run_continuity_audit` | Continuity + payoff verification | KEEP, repoint | scenes | `continuity` |

Retire from default path (keep behind a `legacy_panels` flag): `run_shot_list`,
`assemble_panels`, `_distribute_dialogue`, the 12-panel mapping in
`run_dialogue_and_panels`, and the `studio_scene.py` / GEST physics.

---

## 3. The data contracts

### 3.1 `story_understanding` (Loremaster output, the new universal input)

```json
{
  "title": "...",
  "premise": "2-3 sentences, faithful",
  "themes": ["loyalty vs betrayal", "..."],
  "tone": "atmospheric noir with mystical interludes",
  "motifs": ["smoke/ash = truth", "jazz = the past", "fire/steel = binding"],
  "timeline": [
    {"order": 1, "event": "Louis waits in the car, reflects, 'one last job'",
     "location": "...", "characters": ["Louis"], "significance": "establishes mood"}
  ],
  "character_dossiers": [
    {"name": "Louis", "role": "protagonist",
     "traits": ["watchful", "petty under the calm", "masterful"],
     "want": "...", "need": "...", "wound": "...", "secret": "...",
     "relationships": [{"who": "Goldstein", "bond": "mentor-turned-betrayer"}],
     "voice": "clipped, dry, says less than he means",
     "key_lines": ["<quoted from the text>"]}
  ],
  "world_facts": ["Grimstow City", "Darkside = decayed district", "..."],
  "setup_payoff_candidates": [
    {"setup": "Father Time: 'truth reveals itself in smoke'", "possible_payoff": "..."}
  ],
  "_grounding": "map-reduce | analyzer-fallback"
}
```

**How it's produced (map-reduce — the keystone fix):**
1. **Chunk** full text into ~3,000-char windows on paragraph boundaries.
2. **Map:** one small LLM call per chunk → structured chunk notes (events, who's
   present, what changes, notable quoted lines, motifs glimpsed).
3. **Reduce:** merge chunk notes → dossiers, timeline, themes, motifs, setups.
4. **Fallback:** `studio_analyzer.analyze()` provides a deterministic version of every
   field when the sidecar is down. Never crash, always degrade.

This is the change that makes the betrayal and Father Time *exist* for the model.

### 3.2 `storyboard` (Showrunner output) — replaces the 3-beat plan

```json
{
  "summary": "...",
  "scene_count": 8,
  "scenes": [
    {"id": "s1", "title": "One Last Cigarette", "location": "...",
     "characters": ["Louis"], "purpose": "establish mood + 'one last job'",
     "emotional_shift": "calm → unease", "target_seconds": 12,
     "setup_seeds": ["the ritual cigarette"], "pays_off": []}
  ],
  "setups": [{"id": "seed-footing", "planted_in": "s2", "paid_off_in": "s8",
              "note": "the line Louis throws back at the end"}]
}
```

- **Scene count is dynamic:** ~1 scene per major `timeline` event, clamped to a sane
  range (e.g. 4–12), scaled by the model tier. No hardcoded 12.
- `setups[]` makes callbacks a first-class, machine-checkable object.

### 3.3 `scenes` (the new spine — replaces `panels`)

```json
{"scene_number": 1, "title": "...", "image_prompt": "...", "negative_prompt": "...",
 "narration_script": [
   {"speaker": "Narrator", "line": "Cold settled over the car like a verdict.",
    "emotion": "weary", "delivery": "slow, low"},
   {"speaker": "Louis", "line": "One last job.", "emotion": "resolved", "delivery": "quiet"}
 ],
 "duration_seconds": 12, "setup_refs": ["seed-footing"], "status": "draft|approved"}
```

`narration_script` is **prose and real dialogue**, paced to the source — *not*
balloons. The only constraint is target read-aloud duration.

---

## 4. The orchestrator (gate-aware, scene-iterative)

`Producer` (currently `studio_agents.py`; **gpt owns this file right now — coordinate
before editing**) gains two behaviors:

1. **Blueprint gate.** Run `understanding → world → characters → storyboard`, then
   return to the UI with `status="awaiting_blueprint_approval"`. Nothing expensive
   runs until the user approves/edits the scene list (reuse the existing storyboard
   editor + `apply_storyboard_edits`).
2. **Scene loop.** After approval, for each scene: `scriptwriter →
   cinematographer (→ sound)`, persist as `draft`, present, and
   **accept / reject / refine that scene only**. New entry point
   `regenerate_scene(scene_id, target, feedback)` rebuilds one field (script *or*
   image) with the user's note, leaving the rest intact.

---

## 5. Frontend (cinematic player)

`app/src/renderer/main.js` + `index.html`:
- Per scene: background image + a **scrolling narration column** synced to TTS, then a
  transition to the next scene.
- Per-scene **Accept / Reject / Refine** controls bound to the new endpoints.
- The Storyboard editor becomes the **blueprint-approval gate**.

---

## 6. Build phases (sequence to stop throwing darts)

- **Phase 0 — Input fix (keystone).** `studio_loremaster.py` map-reduce →
  `story_understanding` artifact. *Done when:* the betrayal and Father Time appear in
  the artifact for `burningbarreltest.md`.
- **Phase 1 — Deep characters.** Dossiers feed `_expand_character`; move after
  understanding. *Done when:* Louis's bible cites real text-derived traits, not
  generic noir filler.
- **Phase 2 — Dynamic Showrunner + blueprint gate.** Variable scene count +
  setup/payoff + Producer halt. *Done when:* a long story yields 6–10 editable scenes.
- **Phase 3 — Scriptwriter + scene image.** Replace panels with scenes; reuse
  `studio_visual`. *Done when:* scene narration reads as authored prose.
- **Phase 4 — Per-scene reject/refine loop + cinematic player UI.**
- **Phase 5 — Sound; retire GEST/panel path behind a flag.**

Each phase ships with tests in `tests/` and keeps the deterministic fallback path
green so a missing LLM sidecar never breaks a run.

---

## 7. Coordination notes

- **gpt is in `studio_agents.py` / Producer.** Build new modules
  (`studio_loremaster.py`, `studio_showrunner.py`, `studio_scriptwriter.py`) and wire
  them through `studio_workflow.py` first; integrate into Producer last, together.
- Don't delete the panel/GEST code — gate it. It's good engineering we may reuse for
  validated choreography later.

---

## 8. Progress log

- **Phase 0 — DONE.** `studio_loremaster.py` map-reduce understanding pass built and
  wired into `studio_workflow.py` (`run_loremaster()` / `_understanding()`), persisted
  to the bible (`story_understanding`) and blackboard (`understanding`). Verified
  against `burningbarreltest.md`: timeline went 3 → 9 events; Rodney/Wesley/Goldstein/
  Darkside (all in the previously-omitted 17–91% middle) now recovered even offline.
  Tests: `tests/test_studio_loremaster.py` (9, green).
- **Phase 1 — DONE.** Loremaster dossiers now drive `_character_roster` and
  `_expand_character`; roster casts the real middle-of-story characters with
  differentiated roles; offline fallback grounds personality/wound/arc/voice in the
  dossier. Also fixed a latent bug: the character fallback was missing required keys
  `backstory`/`core_wounds`/`character_arc` (would have failed shape validation).
- **ENVIRONMENT FINDING (blocker for LLM quality):** the local model on this machine,
  `models/gemma-3-4b-it-Q4_K_M.gguf`, is **corrupted** (`llama_model_load: error
  loading model: tensor 'blk.27.ffn_gate.weight' data is not within the file bounds`).
  Every LLM call silently falls back to deterministic mocks. If this is the model the
  app actually loads, a large part of "the AI isn't good at its job" is that **no LLM
  is running at all** — the procedural fallbacks are what's been shipping. Re-download/
  re-verify the GGUF (and confirm the 12B you intend to use is the one selected) before
  judging narration quality. This is independent of the overhaul but gates all of it.
- **Phase 2 — DONE.** `studio_showrunner.py` built and wired as
  `studio_workflow.run_showrunner()`. Dynamic scene count (≈1 per timeline event,
  floored at 4, tier-capped 6/9/12 — no more hardcoded 3), per-scene blueprint, and a
  first-class setup→payoff registry (a seed planted early references its payoff scene by
  id). Persists `scene_blueprint` to the bible + blackboard (`needs_user_review` = the
  gate) and mirrors onto the legacy storyboard via `blueprint_to_storyboard` so the
  existing editor/approval plumbing keeps working. Tests: `tests/test_studio_showrunner.py`
  (9, green). Full studio suite: 84 pass.
- **Known pre-existing failures (NOT from this work, verified against clean baseline):**
  `test_studio_export.py` (4) + `test_studio_scene.py` (1) fail because the panel
  dialogue path raises "Dialogue text is required" on an empty narration slot
  (`run_dialogue_and_panels` → `add_dialogue_line`). This is the exact comic-layer
  fragility **Phase 3 retires** — fix it there by replacing panels with authored scenes.
- **Phase 3 — DONE.** `studio_scriptwriter.py` built (the missing narrator) and wired as
  `studio_workflow.run_scenes()` + `_persist_scenes_as_panels()` + `regenerate_scene()`.
  Per scene it writes an authored `narration_script` (flowing narration + in-voice
  dialogue paced to the scene length — not balloons) and one evocative image prompt by
  reusing `studio_visual` at scene scale. Persists a `scenes` artifact (the new spine) to
  the bible + blackboard and mirrors each scene onto panel + dialogue rows so export/UI
  keep working. `regenerate_scene(scene_id, target, feedback)` gives the per-scene
  reject/refine loop (script-only, image-only, or both). Tests:
  `tests/test_studio_scriptwriter.py` (8, green).
  Verified end-to-end on `burningbarreltest.md`: 6 scenes written, persisted, regenerated.
- **Legacy panel bug FIXED** as a side effect: `run_dialogue_and_panels` now guards
  against empty narration before `add_dialogue_line`, clearing 4 of the 5 pre-existing
  failures. Remaining failure (`test_studio_scene.py::test_scene_endpoint_commits_and_rejects`)
  is an unrelated `studio_capabilities` registry mismatch (an action that should be
  unsupported at a POI is now permitted) — part of the GEST path slated for retirement.
- **Studio suite: 96 pass / 1 unrelated fail.** New-module tests total 34 (loremaster 9,
  showrunner 9, scriptwriter 8, + integration), all green.
- **Phase 4 — DONE.** Cinematic player shipped.
  - Backend: `studio/workflow/stage` now dispatches `loremaster` / `showrunner` /
    `scenes`; new `GET /studio/projects/{name}/scenes` (the player's data source) and
    `POST /studio/workflow/scene/regenerate` (per-scene reject/refine). CORS is already
    `*`, so the standalone player can fetch the backend.
  - Client: `studioGetScenes` / `studioRunScenes` / `studioRegenerateScene` in
    `app/src/renderer/api/backend.js`.
  - Player: `app/src/renderer/cinema.html` — a self-contained full-screen player. Each
    scene shows an atmospheric background (rendered image when present, else a
    deterministic gradient) with a Star-Wars-style narration crawl, read aloud by TTS
    (browser SpeechSynthesis; swap to Kokoro later), beat-synced highlighting, scene
    title cards, auto-advance, and keyboard control. Per-scene **Accept / Reject /
    Refine** (with a script/image/both target + free-text note) call `regenerate_scene`
    and reload just that scene. Registered as a vite renderer input.
  - UI hooks: "Generate Scenes" + "▶ Cinematic Player" buttons in the Studio export row
    (`index.html`), wired in `main.js` (`handleStudioGenerateScenes` / `handleStudioPlayCinema`).
  - Verified end-to-end through the real HTTP API (TestClient): intake → world →
    characters → loremaster(9) → showrunner(6) → scenes → GET scenes → regenerate, all 200.
  - Note: scenes carry an `image_prompt` but no rendered image yet — image generation is a
    separate backend step to wire later; the player degrades to gradient backgrounds until then.
- **Phase 5 / Producer swap — coordinated with gpt.** Point `Producer` at
  `understanding → world → characters → showrunner(gate) → scenes` and retire the panel/
  GEST agents behind a `legacy_panels` flag. This is the step that makes the cinematic
  path the default end to end.

---

## 9. Review of gpt's recommendations + craft refinements (2026-06-07)

gpt's [STUDIO_CINEMATIC_STORYTELLING_RECOMMENDATIONS.md](STUDIO_CINEMATIC_STORYTELLING_RECOMMENDATIONS.md)
is solid and aligns with this plan. This section says what to **adopt as-is**, then adds the
layer both docs underweight — **storytelling craft** — plus two gaps (Genesis, taste memory)
and throughput reality. The north star is the owner's own words: callbacks, the hero's
journey, the Bilbo transformation, the Batman "you sacrificed your footing" payoff. Plumbing
is necessary but it is not the product; **the product is a reel that lands emotionally.**

### 9.1 Adopt from gpt as-is (don't re-litigate)
- **Cinematic as default + `legacy_panels` flag.** Yes. (§4 here, gpt §"Make Cinematic The Default".)
- **Blueprint as a true gate**, with edit/reorder/delete/rename before any expensive work.
- **Image render stage with a queue** (`queued/rendering/done/failed`), assets project-local,
  write `image_url` back onto the scene. Biggest *visible* win — the player already prefers it.
- **Local TTS (Kokoro) over browser speech**, per-beat audio + timing on each beat; browser
  speech stays as fallback only.
- **Continuity repointed to `scenes[]` + `scene_blueprint.setups[]`** as the source of truth.
- **Production-desk UX** with the four mode controls — **`Just make it` / `Ask me first` /
  `Approve every stage` / `Producer mode`** — and **honest model/fallback status**. This is
  excellent and exactly on-vision; build it. (Honest fallback status is non-negotiable given
  the corrupt-model finding — a user must never mistake mock output for live LLM quality.)

### 9.2 The gap both docs share: strong on plumbing, thin on CRAFT
If we build only what's written, we ship a *competent-but-soulless* reel generator. These four
additions are what make it "evocative." They are cheap (mostly prompt + data-contract changes)
and high-leverage.

**(a) Dramatic structure, not mechanical chunking — *Showrunner upgrade*.**
Today scene count = number of timeline events (`decide_scene_count`). That's faithful *chunking*,
not *shaping*. A pivotal beat (the betrayal) gets the same weight as a throwaway. Fix:
- Give the Showrunner an explicit **structure template** chosen to fit the material
  (Hero's Journey / three-act / Save-the-Cat / "organic"). Map scenes to **dramatic functions**
  (setup, inciting incident, rising try/fail, midpoint reversal, dark night, climax, denouement),
  not just chronology.
- **Weight scenes by `significance`** (already on each timeline event) so big moments get their
  own scene and slow stretches compress. Add a per-scene `function` field to the blueprint.
- This is also what lets *seed mode* and *thin manuscripts* become real stories instead of
  evenly-sliced summaries. Grok's beat-sheet instinct was right; wire it into the Showrunner.

**(b) Author the payoff, don't just track it — *Scriptwriter + Continuity*.**
`setups[]` records that s2 pays off in s8, but nothing makes the Scriptwriter *land* it with
weight. Fix:
- When writing a scene that has `pays_off`, pass the **original setup text + its planted line**
  into the Scriptwriter prompt with an explicit instruction: "this scene must call back to X —
  land it." 
- Continuity then verifies the payoff line *actually exists and echoes the setup* (string/semantic
  echo), not merely that a `pays_off` id is present. A tracked-but-unwritten callback is the
  failure mode to guard against.

**(c) Emotional contour across the whole reel — *blueprint-level*.**
Per-scene `emotional_shift` exists, but nothing shapes the *whole reel's* rhythm (quiet→loud,
tension→release, build→climax→breath). Add a blueprint-level `emotional_arc` (a short ordered
contour) the Showrunner fills and the Scriptwriter/sound stages read, so the reel has a shape,
not a flat affect. This is the Bilbo "transformation you can feel" requirement.

**(d) Cross-scene voice consistency — *Scriptwriter memory*.**
Characters must sound the same in s8 as in s1. The Scriptwriter gets `speech_style` per scene but
has no cross-scene voice anchor. Carry a tiny **voice guide** (locked phrasing/verbal tics per
character, mirrors the existing `visual_consistency_guide` pattern in
`_apply_visual_prompts`) and feed it into every scene's script call. Continuity flags drift.

### 9.3 The missing "make it from nothing" path — *Genesis* (owner-requested)
The owner explicitly wants: *"click a button and it generates a beautiful story regardless of
whether I gave it anything."* Today **seed mode has no manuscript → `run_loremaster` returns
None → the Showrunner has no timeline to shape.** Build a **Genesis/Inventor** stage that, when
there is no source story, *fabricates* a `story_understanding` (premise → logline → outline →
timeline → dossiers → motifs) using the same contract the Loremaster emits — so every downstream
stage is identical whether the story was *read* or *invented*. Giving a manuscript should enrich,
not be required. This is a first-class path, not an afterthought.

### 9.4 Personalization / taste memory — the owner's "RAG"
The owner explicitly asked for *"a separate system to understand the user's preferences."* Neither
doc covers it. Add a lightweight, project-spanning **taste memory**: every Accept/Reject/Refine
(we already capture these via `regenerate_scene` + approvals) writes a small preference signal
(liked tone, rejected clichés, favored pacing, voice notes). Feed a compact digest into the
Showrunner/Scriptwriter system prompts. This is what turns "generic slop" into *the user's* taste —
and it compounds: the more they use it, the more it sounds like them. Start dead-simple
(append-only notes + a summarizer), not a vector DB.

### 9.5 Throughput & streaming UX (local-12B reality)
A 6–9 scene reel is ~25–40 **sequential** LLM calls on a local 12B (loremaster map+synth +
world + N characters + showrunner + N scenes). That is minutes, not seconds. Plan for it:
- **Stream scenes to the player as each is authored** (don't block on the whole reel). The player
  already loads a `scenes[]` array — have it poll/append so the user watches it build.
- **Cache aggressively** (understanding + dossiers are stable; only re-run on edits).
- **Parallelize only where safe** (independent per-character expansion; never within a scene's
  dependent chain). gpt's render queue handles images; this handles the *text* latency, which is
  the real wait.
- Honest, specific progress ("Writing scene 4 of 7…") — `_progress` posts already exist; surface them.

### 9.6 Measure craft, not just shape
Every test today checks *shape* (keys present, counts), never *quality*. Add a small **craft rubric**
the user (or an LLM-judge in a dev script, not the hot path) scores a reel against: Does the payoff
land? Do characters sound distinct? Is there an arc? Did it stay faithful? Keep one or two **golden
reels** for `burningbarreltest.md` to eyeball after prompt changes. Without this we can't tell if a
"tuning" change actually improved storytelling or just moved tokens around.

### 9.7 Sequencing tweak vs gpt's order
gpt: Producer integration → Blueprint UI → Image → TTS → Continuity/Export. One change:
- **The blueprint approval UI (Phase 2) must land *with* the Producer swap (Phase 1), not after.**
  Making cinematic the default *without* the gate recreates the exact "one-shot pipeline races past
  you" problem the owner hates. Ship them together.
- **Fold §9.2 craft items into the Showrunner/Scriptwriter now** (they're prompt/contract changes,
  not new infra) — they're the difference between "it works" and "it's worth watching," and they're
  cheap. Do them before/alongside image+TTS polish.
- Then gpt's order holds: Image render → Kokoro TTS → scene continuity → folder reel → MP4.

### 9.8 Robustness notes on what's already built
- **`_grounding` honesty** (`studio_loremaster`): reports `"map-reduce"` whenever an `llm_call`
  is passed even if every call fell back (corrupt model). Tie the label to real LLM use
  (`runner.model_status.used_fallback`). Cosmetic but it currently *lies* in logs.
- **Showrunner idempotency** (`run_showrunner` / `_persist_scenes_as_panels`): re-running creates
  fresh episodes/minutes each time. Make it reuse the project's episode (mirror `assemble_panels`'
  existing-panel reuse) so re-runs don't pile up duplicate rows.
- **`regenerate_scene` ripple**: feedback edits the blueprint scene's `purpose` only — it does not
  update `story_understanding` or `setups[]`. Fine for v1; note it so a refined scene that breaks a
  planted callback gets caught by continuity (§9.2b) rather than silently.
- **Scene weighting**: see §9.2a — don't let scene count be a pure function of event *count*.

### 9.10 Build log — §9 + gpt recs (2026-06-07, all green)
All nine craft/UX pieces are built, wired, and tested (130 studio tests pass; the 1 remaining
failure is the unrelated pre-existing GEST registry drift). Renderer build is green incl.
`cinema.html`.
- **P1 Showrunner craft** — dramatic-function arc (`assign_functions`), significance-weighted
  bucketing, per-scene `function`, blueprint `emotional_arc`, and `run_showrunner` idempotency.
- **P2 Scriptwriter craft** — authored payoffs (resolves `pays_off`→setup note, lands it; fallback
  writes a real callback beat) + a cross-scene `voice_guide` fed to every scene + persisted.
- **P3 Genesis** (`studio_genesis.py`) — invents a full `story_understanding` in seed mode; `_understanding()`
  falls through to it; `genesis` stage. The "make a story from nothing" button now works end-to-end.
- **P4 Taste memory** (`studio_taste.py`) — accept/reject/refine → digest injected into Genesis/
  Showrunner/Scriptwriter prompts; recorded in `regenerate_scene`.
- **P5 grounding honesty** — Loremaster labels `analyzer-fallback` when a dead model falls back.
- **P6 Image render** (`studio_render.py`) — pluggable queue (queued/rendering/done/failed/unavailable),
  project-local assets, `image_path`; honest "unavailable" with no generator; `render` stage + status endpoint.
- **P7 Scene continuity** (`studio_continuity.py`) — verifies every setup is echoed in its payoff
  scene (high warning if not) + roster/length/arc checks, each with a `repair_target`; `scene_continuity` stage.
- **P8 Scene audio** (`studio_audio.py`) — per-beat local TTS via Kokoro path, `audio_path`; player
  prefers stored audio over browser speech; `voice` stage.
- **P9 Production desk** — Cinematic Production panel (Blueprint→Approve→Generate→Render→Voice→
  Continuity→Player) with an **honest status strip** (scene/image/voice counts + live-model-vs-
  fallback) and continuity warnings; enriched `GET /scenes` (grounding + media counts).
- New tests: loremaster +1, showrunner +3, scriptwriter +3, genesis 7, taste 5, render 4,
  continuity 7, audio 4.

### 9.9 One-line verdict
gpt's recs are the right *engineering* backbone — adopt them. This section adds the *craft* layer
(structure, authored payoffs, emotional contour, voice consistency), the *Genesis* path, and *taste
memory* — without those, we will have built a beautiful machine that tells forgettable stories. With
them, it tells the owner's stories.
