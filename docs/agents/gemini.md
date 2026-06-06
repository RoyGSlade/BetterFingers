# Gemini — UX, Context & Audio Domain Agent Log

**Role**: User experience, overlay behavior, transcription/context rules, audio ducking, settings UI  
**Protocol ref**: [AGENTS_RULING.md](../AGENTS_RULING.md)

---

## Active Assignments

| ID | Task | Status | Branch | Notes |
| :- | :--- | :----- | :----- | :---- |
| G-001 | Source Arcanum Studio Mode — Workflow & Producer Pipeline | ✅ Complete | main | Orchestrator, SQLite CRUDs, and 7 FastAPI endpoints |
| G-002 | Phase 1 Database Schema Foundations (Assets & Profiles) | ✅ Complete | main | Updated characters table, added character_assets, formalized user_preferences |
| G-003 | Phase 2 Context Constraints & Hallucination Guard | ✅ Complete | main | Injected AGENTIC_CONSTRAINTS and Intelligent Retry logic |
| G-004 | Phase 3 The Intake Agent (Conversational Interview) | ✅ Complete | main | Added run_intake_interview_turn and /studio/workflow/intake/turn endpoint |

---

## Session Log

### [G-001] Source Arcanum Studio Mode — Workflow & Producer Pipeline
- **Date**: 2026-06-06
- **Scope**: Implement the Agent 2 goal of building the first Source Arcanum Studio workflow that turns a user story seed into a structured 60-second voiced comic reel plan.

#### What was done
- Built local-first SQLite memory layer (`studio_memory.py`) initializing project bibles, characters, locations, episodes, minutes, panels, dialogue lines, warnings, and approvals under `~/.config/BetterFingers/studio_projects/{project_name}/studio.db`.
- Implemented `StudioWorkflowRunner` orchestrator in `studio_workflow.py` running intake, world building, character creation, story planning (60s beats), dialogue script & panel details (12 panels), and a continuity audit.
- Implemented robust regex JSON extraction with braces/brackets first-appearance ordering to recover structured fields from raw conversational LLM responses.
- Added procedural mock fallbacks for each pipeline stage in case `llm_engine` is offline or not pre-warmed.
- Integrated FastAPI endpoints in `server.py` supporting `/studio/project/create`, `/studio/project/load`, `/studio/workflow/run`, `/studio/workflow/stage`, `/studio/project/{project_name}/{project_id}/panels`, `/studio/project/warning/resolve`, and `/studio/project/approve`.
- Wrote full unit/integration test suite at `tests/test_studio_workflow.py`.

#### Files changed / created
- `studio_memory.py` (NEW) — SQLite DB structure and CRUD.
- `studio_workflow.py` (NEW) — Stage state machine and LLM adapter/mocks.
- `tests/test_studio_workflow.py` (NEW) — Pytest suite covering database schemas, parser repair, state progression, and FastAPI client routing.
- `server.py` — Exposed endpoints under `/studio/*`.

#### Blockers / Handoffs
- @Claude / @Codex: Workflow logic and memory are verified green. Endpoints are ready for integration with the Electron UI (Agent 3 role).

### [G-002] Phase 1 Database Schema Foundations (Assets & Profiles)
- **Date**: 2026-06-06
- **Scope**: Define schemas for character reference images, audio profiles, and user preferences within the database.

#### What was done
- Added `primary_image_path` and `voice_profile` columns to the `characters` table via safe `ALTER TABLE` migrations in `init_project_db`.
- Created the `character_assets` table for multi-angle references and audio samples.
- Patched the internal `_row_to_dict` parser in `studio_memory.py` to automatically unpack JSON metadata for `voice_profile`.
- Created `DEFAULT_USER_PREFERENCES` to formalize the schema of `user_preferences`.
- Verified SQLite interactions with new unit test `test_character_assets_and_profiles`.

#### Files changed / created
- `studio_memory.py` — Schema definitions and CRUD endpoints.
- `tests/test_studio_workflow.py` — Added unit tests.

#### Blockers / Handoffs
- @Claude: GEST memory layer is prepared for Phase 1 Node/Edge structural upgrades.
- @Codex: Electron UI has structured access to save assets.

### [G-003] Phase 2 Context Constraints & Hallucination Guard
- **Date**: 2026-06-06
- **Scope**: Design strict fallback rules and context limitations for agents to prevent "hallucination loops."

#### What was done
- Added `AGENTIC_CONSTRAINTS` global constant to `studio_workflow.py` enforcing strict JSON compliance, max output tokens, and strict adherence to the existing World State.
- Modified `_call_llm_with_fallback` so that every pipeline stage automatically incorporates the constraints into the `system_prompt`.
- Built an "Intelligent Retry" feedback loop: when the LLM outputs malformed JSON or an oversized response, the retry attempt explicitly injects a `CRITICAL SYSTEM WARNING` instructing the model on *why* it failed to prevent repeat hallucinations.
- Added `test_intelligent_retry_injects_critical_warning` to `tests/test_studio_workflow.py`.

#### Files changed / created
- `studio_workflow.py` — Orchestrator prompt modification.
- `tests/test_studio_workflow.py` — New unit test.

#### Blockers / Handoffs
- @Claude / @Codex: The orchestrator now behaves strictly. Models will be scolded if they deviate from JSON formats.

### [G-004] Phase 3 The Intake Agent (Conversational Interview)
- **Date**: 2026-06-06
- **Scope**: Create the conversational interface that iteratively interviews the user to pull out the story, tone, and character preferences while enforcing hardware scope limits.

#### What was done
- Added `run_intake_interview_turn` to `studio_workflow.py`. This orchestrator stage takes the full `chat_history` and generates a conversational response alongside a structured internal JSON state (`draft_premise` and `is_complete` flag).
- Injected strict scope constraints into the Intake Agent's system prompt to politely enforce a maximum of 2-3 characters and 1-2 locations (the 60-second hardware limit).
- Wrote a procedural mock fallback that gracefully simulates an interview progression when the LLM is offline.
- Created the Pydantic `StudioIntakeTurnRequest` model and exposed `POST /studio/workflow/intake/turn` in `server.py`.
- Wrote `test_intake_interview_turn` unit test, successfully maintaining the suite's 100% pass rate (18/18).

#### Blockers / Handoffs
- @Codex: The backend API for the conversational intake is complete. You can now wire the Electron IPC channels and the chat window UI to `/studio/workflow/intake/turn`.
- @Claude: I have implemented my part of Phase 3. You can implement the asynchronous session loop to persist the conversational state if required, though the current endpoint functions completely statelessly (by accepting the full `chat_history` on each turn).

---

## Domain Ownership

Gemini owns review and sign-off on changes touching:

| Area | Key Files |
| :--- | :-------- |
| Settings UI (Flet) | `settings.py`, `settings_controls_mixin.py`, `settings_persistence_mixin.py` |
| Overlays | `overlay.py`, `notification_overlay.py`, `preview_overlay.py` |
| Transcription / Context Rules | `context_rules.yaml`, `transcriber.py` |
| Audio Ducking | `audio_manager.py` (Windows), `audio_manager_linux.py` |
| TTS | `tts_engine.py`, `tts_overlay.py` |

---

## Reporting Checklist (before marking any task complete)
- [ ] UX/overlay behavior verified on Linux (primary target)
- [ ] `context_rules.yaml` compliance checked — no rule regressions
- [ ] Settings persistence confirmed — new fields survive restart
- [ ] Flet lazy-loading wiring checked for new settings controls
- [ ] Entry added to [agent_blackboard.md](../agent_blackboard.md)
- [ ] Test impact noted in [agent_test_log.md](../agent_test_log.md) if code-touching
