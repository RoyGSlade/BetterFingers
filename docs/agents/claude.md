# Claude — Architecture & Strategy Agent Log

**Role**: Architecture, API boundaries, structural patterns, system design, dev tooling  
**Protocol ref**: [AGENTS_RULING.md](../AGENTS_RULING.md)

---

## Active Assignments

| ID | Task | Status | Branch | Notes |
| :- | :--- | :----- | :----- | :---- |
| C-001 | Dev desktop shortcut — Linux launcher | ✅ Complete | main | See Session Log below |
| C-002 | Architecture pass + Linux test stabilisation | ✅ Complete | main | See Session Log below |
| C-003 | Phase 1 GEST graph schema (+ Director Casting) | ✅ Complete | main | See Session Log below |
| C-004 | Scene Builder — round-based state machine (Scene Planning → GEST) | ✅ Complete | main | See Session Log below |
| C-005 | Director Phase 4 Finalization — cross-scene temporal linking + timeline | ✅ Complete | main | See Session Log below |

---

## Session Log

---

### [C-001] Dev Desktop Shortcut
- **Date**: 2026-06-05 → 2026-06-06
- **Scope**: Create a one-click dev launcher on the Cinnamon desktop that always runs from latest source, cleans up all processes on close, and leaves no ghost processes in the background.

#### What was done
1. **Fixed `BetterFingers.desktop`** — paths were hardcoded to original developer's home (`/home/roygslade/Desktop/BetterFingers`). Updated `Exec=`, `Path=`, and `Icon=` to the correct `donaven/BetterFingers-1` paths.
2. **Added `HUP` to cleanup trap** in `scripts/start-betterfingers-linux.sh` — ensures cleanup fires when terminal window is closed (gnome-terminal sends SIGHUP on close, not just INT/TERM).
3. **Created `~/Desktop/BetterFingers-Dev.desktop`** — copy of the fixed file on the actual desktop, `chmod +x` and `gio set metadata::trusted true` so Cinnamon recognises it.
4. **Diagnosed and fixed gnome-terminal cgroup bug** — on kernel 6.17, `gnome-terminal` via `Terminal=true` silently fails with VTE scope creation error. Switched to `Terminal=false` with `Exec=systemd-run --scope --user -- gnome-terminal -- <script>`. The `systemd-run --scope` creates a valid user scope first, which VTE can then use as a parent cgroup.
5. **Confirmed `.venv` setup required** — venv was absent, user ran `pip install -r requirements.txt` to resolve.

#### Files changed
- `BetterFingers.desktop` (project root)
- `scripts/start-betterfingers-linux.sh` (line 176 — trap)
- `~/Desktop/BetterFingers-Dev.desktop` (new, on OS desktop)

#### Launch behavior after fix
- Click shortcut → systemd scope created → gnome-terminal window opens → sudo prompt → backend starts on :8000 → Electron hot-reload dev server starts
- Close app → Electron exits → `wait` returns → EXIT trap kills all process groups
- Close terminal window → SIGHUP → EXIT trap kills all process groups
- Click shortcut while running → `kill_previous_launch` kills old instance first → clean restart with latest code
- Frontend edits → electron-vite hot-reloads automatically
- Backend edits → click shortcut to restart with updated code

#### Blockers encountered
- gnome-terminal VTE cgroup failure on Linux kernel 6.17 (see above fix)
- No `.venv` present — user resolved manually

---

---

### [C-002] Architecture Pass + Linux Test Stabilisation
- **Date**: 2026-06-06
- **Scope**: Architecture/API boundary decision for platform-specific imports + fixing all remaining pytest failures. Picked up from GPT's P-002 handoff.

#### Decision: inline platform stub (no adapter module)
The scope of the platform problem was narrow: `pydirectinput` uses `ctypes.windll` at import time. All other methods (`keyboard`, `pyperclip`) are already cross-platform. A full platform adapter module would be over-engineering. Instead, a `sys.platform == "win32"` guard in `injector.py` stubs out `pydirectinput` on Linux with a `types.SimpleNamespace` no-op. This keeps the module's public API identical on both platforms, all existing mocks still work, and Windows production behavior is completely unchanged.

#### What was done
1. **`injector.py`** — wrapped `import pydirectinput` in `sys.platform == "win32"` guard; Linux gets a `SimpleNamespace` stub with `PAUSE`, `keyDown`, `keyUp`, `press` no-ops.
2. **`sudo apt-get install python3-tk`** — resolved 11 collection errors (all `main.py`/overlay tests import `tkinter`).
3. **`tests/test_hotkey_manager_tts.py`** — rewrote 3 tests that patched `hotkey_manager.keyboard.add_hotkey` / `remove_hotkey`. Those hooks no longer exist in the module (`start()` now says `# Native hooks removed` — hotkeys are handled by Electron IPC). Tests now assert actual current behavior: `_running` state, hotkey normalization via `_normalize_hotkey`, and `_review_tts_trigger()` callback dispatch.
4. **`tests/test_settings_external_url.py`** — added `create=True` to `@patch("settings.os.startfile", ...)` so the patch works on Linux where `os.startfile` doesn't exist.
5. **`tests/test_server_drafts.py`** `setUp`/`tearDown` — added `server.tts_engine` to the saved/restored global set. An earlier TTS test was leaving `tts_engine` populated; its `on_stop` callback then fired `draft_tts_stopped` into later tests' `broadcast_status_threadsafe` mocks, causing ordering-dependent failures.

#### Files changed
- `injector.py` (lines 6–17 — import block)
- `tests/test_hotkey_manager_tts.py` (3 test methods rewritten)
- `tests/test_settings_external_url.py` (1 patch decorator — `create=True`)
- `tests/test_server_drafts.py` (`setUp` line ~117, `tearDown` line ~129)

#### Result
**222 passed, 1 skipped, 0 failed** (full suite, `.venv/bin/python -m pytest`)

#### Blockers / Handoffs
- None. Baseline is clean. @GPT: can proceed with any new implementation tasks. @Gemini: no UX/audio impact from these changes.

---

## Session — C-003: Phase 1 GEST Graph Schema + Director Casting (2026-06-06)

**Task**: My Phase 1 assignment per the G-002 handoff ("@Claude: the database is now ready for GEST Nodes/Edges and Temporal Constraints"). Roadmap = `docs/TheagentPrompts.md`; §5 defines GEST as the formal directed graph `G=(V,E)` with Allen's-interval edges and temporal cycle rejection (Floyd-Warshall in the spec; DFS reachability is sufficient at our scale).

#### Architecture decision: GEST lives in the deterministic memory backend, not an agent
Per the doc's central thesis (narrative LLM vs. programmatic state backend), constraint enforcement must be code, not prompt. So the GEST graph and its temporal validity are pure `studio_memory.py` functions. Agents (Director/Scene Builder) will *call* these tools; the backend rejects invalid edges deterministically, making the graph "executable by construction."

#### What was done
1. **`studio_memory.py`** — GEST backend:
   - `gest_nodes` + `gest_edges` tables (+ 3 indexes) in `init_project_db`. Nodes: `node_type` ∈ {exists, action, event, location}, optional `episode_id` and `ref_type/ref_id` grounding. Edges: `relation_class` + `relation`, FK to nodes with cascade.
   - Relation vocabularies: temporal (Allen: before/after/same_time/concurrent), logical (causes/enables/prevents/requires), semantic (observes/interrupts/motivates/sets_context_for/contrasts_with), plus a `GEST_RELATION_CLASS` lookup so callers pass just the relation name.
   - `add_gest_node`/`get_gest_nodes`, `add_gest_edge`/`get_gest_edges`/`get_gest_graph`.
   - **Temporal cycle detection**: ordering relations (before/after) normalized to a canonical "precedes→follows" pair (`_ordered_pair`); `_creates_temporal_cycle` does DFS reachability over existing precedence edges and `add_gest_edge` raises `ValueError` if the new edge would close a loop. Also rejects self-loops, unknown relations, and mismatched `relation_class`.
   - `gest` added to `export_project_json`.
2. **Director Casting (additive — Codex's Director lane)** — `studio_capabilities.validate_casting`/`default_casting` (registry-grounded validation + deterministic fallback), `StudioWorkflowRunner.run_director_casting` (Absolute Grounding; repairs invalid model picks; anchors region as a location + records casting to bible/prefs), `POST /studio/workflow/cast`, `casting` stage alias.

#### Files changed
- `studio_memory.py` (GEST constants ~line 25; 2 tables + 3 indexes in `init_project_db`; node/edge functions before `export_project_json`; export line)
- `studio_capabilities.py` (`validate_casting`, `default_casting`)
- `studio_workflow.py` (`run_director_casting`)
- `server.py` (`POST /studio/workflow/cast`, `casting` stage alias)
- `tests/test_studio_memory.py` (GEST table assertion + `test_gest_graph_nodes_edges_and_temporal_cycle_detection`)
- `tests/test_studio_workflow.py` (`studio_capabilities` import, casting tests, integration cast step)

#### Result
**247 passed, 1 skipped, 0 failed** (full suite, `.venv/bin/python -m pytest`)

#### Blockers / Handoffs
- None blocking. @Codex/GPT: Casting is in your Director lane — fold it into your sequencing or have me hand it over. @Gemini: GEST builds cleanly on your G-002 asset/profile schema, no migration conflicts. Director Scene Planning + Finalization can now write directly into GEST via the new node/edge tools.

---

## Session — C-004: Scene Builder, round-based state machine (2026-06-06)

**Task**: The Phase-3 scene-planning handoff (P-014: "scene planning can rely on `bible.casting`, anchored `locations`, character `metadata.skin_id`"; G-003: "ready for Scene Planning / GEST node population"). Build the deterministic backend that turns narrative intent into a *physically valid* scene committed to the GEST graph.

#### Architecture decision: deterministic Scene Builder, separate from the LLM Director
The doc's hallmark is the Director (narrative) vs. Scene-Builder (simulator validity) split — "executable by construction." So the Scene Builder is a pure state machine with **no LLM**: it validates each action against the capability registry and current state, and only writes to GEST on a clean `end_round`. The LLM Director (Codex's lane) will produce a structured `scene_spec` and call it; invalid actions come back as descriptive errors for agentic self-correction, so no hallucinated action ever reaches the graph.

#### What was done
1. **`studio_scene.py`** (new) — `SceneBuilder` + `SceneError`:
   - Round-based state machine: `start_round` (anchor actors at a region, return state payload), `start_chain` (open a transactional chain on a deep-copied working state), `add_action`/`continue_chain`, `do_interaction` (synchronized two-actor), `end_round` (commit + merge state), `abort_chain` (discard).
   - Constraint enforcement against `studio_capabilities`: posture prerequisites (`requires_posture`/`result_posture`), POI `supports`, POI `capacity`/exclusive-use, held-object (`requires_object`) and receiver (`requires_receiver`) rules, and action-chain `next_actions` ordering.
   - Commits to GEST via the C-003 tools: one `exists` node per actor, an `action` node per step chained with `before` edges, and a Give→INV-Give `event` synchronized with a `same_time` edge. Transactional: validation happens on a working copy, so a rejected chain leaves committed state untouched.
2. **`studio_workflow.py`** — `run_scene_round(scene_spec)`: drives `SceneBuilder` from a deterministic spec (defaults region to `bible.casting`), returns `{ok, nodes, edges, state, graph}` or `{ok: False, error}`.
3. **`server.py`** — `POST /studio/workflow/scene` (`StudioSceneRequest`); invalid chains map to **400**, never partial writes.

#### Files changed
- `studio_scene.py` (new module)
- `studio_workflow.py` (`run_scene_round`)
- `server.py` (`StudioSceneRequest`, `POST /studio/workflow/scene`)
- `tests/test_studio_scene.py` (new — 8 tests: valid commit, POI/ordering/capacity rejection, give interaction + sync, abort, runner + endpoint)

#### Result
**255 passed, 1 skipped, 0 failed** (full suite, `.venv/bin/python -m pytest`)

#### Blockers / Handoffs
- None blocking. @Codex/GPT: have the Director's LLM scene step emit a `scene_spec` and call `run_scene_round`. @Gemini/@anyone: Relation Subagents (logical `causes/enables/...`, semantic `observes/...`) can enrich GEST edges via `studio_memory.add_gest_edge`; Finalization (cross-scene temporal linking) is the next Director phase.

---

## Session — C-005: Director Phase 4 Finalization (2026-06-06)

**Task**: The "Phase 4 finalization / cross-scene temporal linking" item left open in P-015/Active Task. This completes the Director's four-phase workflow (Exploration → Casting → Scene Planning → Finalization) from the doc (§2: "Finalization — cross-scene temporal linking, resolving dependencies to create a unified narrative flow"; §5: "Temporal Orchestration — resolve Allen's-interval constraints into a valid execution timeline").

#### Architecture decision: scenes tag themselves; Finalization links + a pure solver validates
Scenes are built in isolation by the Scene Builder (C-004), so they need a grouping key to be linked later. Rather than infer scene boundaries, I tag each committed node with a `scene_id` at the source (`SceneBuilder(scene_id=...)`, set by `run_scene_round`). Finalization then groups by `scene_id` and only *adds* cross-scene edges; the actual ordering is a **pure function** (`compute_gest_timeline`) so timeline validity is deterministic and testable independent of the linking heuristic.

#### What was done
1. **`studio_memory.compute_gest_timeline`** — deterministic Kahn topological sort over ordering edges only (`before`; `after` normalized to reversed precedence). Ties broken by node id (min-heap) for stable output. Returns `{valid, has_cycle, order, node_count}`; `valid=False` iff a cycle blocks a complete ordering.
2. **`studio_scene.py`** — `SceneBuilder` gained a `scene_id` param and a `_meta()` helper that stamps `scene_id` onto every committed node's metadata (action/exists/event).
3. **`studio_workflow.py`**:
   - `run_scene_round` now assigns a `scene_id` (`scene-{n}` from the count of existing distinct scene ids, or an explicit `scene_spec["scene_id"]`) and returns it.
   - `run_finalization(scene_order=None)` — groups action/event nodes by `scene_id`, orders scenes (explicit order else creation order), links each scene's last event → next scene's first event with a cross-scene `before` edge (idempotent: skips pairs already linked; skips a link that would cycle), computes + persists `gest_timeline`.
4. **`server.py`** — `POST /studio/workflow/finalize` (`StudioFinalizeRequest`) + `finalization`/`finalize` stage alias.

#### Files changed
- `studio_memory.py` (`compute_gest_timeline`)
- `studio_scene.py` (`scene_id` param + `_meta`)
- `studio_workflow.py` (`run_scene_round` scene_id; `run_finalization`)
- `server.py` (`StudioFinalizeRequest`, `POST /studio/workflow/finalize`, stage alias)
- `tests/test_studio_memory.py` (timeline assertions), `tests/test_studio_scene.py` (two-scene linking, idempotency, endpoint)

#### Result
**259 passed, 1 skipped, 0 failed** (full suite, `.venv/bin/python -m pytest`)

#### Blockers / Handoffs
- None blocking. Deliberately did **not** touch `run_full_pipeline` (Codex's active production-sequence surface) — `run_finalization` is the capstone to append after scene planning when they're ready. Relation Subagents (logical/semantic edges) compose cleanly since only before/after affect the timeline.

---

## Reporting Checklist (before marking any task complete)
- [ ] Architectural side-effects on existing modules documented
- [ ] Files changed listed with line-level notes for anything non-obvious
- [ ] Blockers cleared or handed off to @Gemini / @GPT
- [ ] Entry added to [agent_blackboard.md](../agent_blackboard.md)
- [ ] Test impact noted in [agent_test_log.md](../agent_test_log.md) if code-touching
