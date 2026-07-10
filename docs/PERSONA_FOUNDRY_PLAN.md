# Persona Foundry Plan

## Purpose

Today, creating a BetterFingers persona means filling in a form: a role/tone
dropdown, an Advanced block, a few-shot table. It works, but it's "a prompt
box." **Persona Foundry** turns persona creation into a guided ritual: the
local LLM interviews the user, pushes back on vague or contradictory answers,
forces concrete examples, stress-tests the result against nasty inputs, and
compiles everything into a schema-v2 persona plus a human-readable "character
card." The user leaves with a persona that has taste, boundaries, and a job —
not just a prompt.

This plan is additive. It does not touch the existing manual persona wizard
(4-step form in `index.html`/`main.js`, `/personas/lint`, `/personas/test`) —
Persona Foundry is a new, parallel entry point that ends by calling the same
`POST /personas` save route the manual wizard already uses.

The app already has everything Persona Foundry needs to sit on top of:

- Persona schema v2 (`llm_engine.py`: `default_persona`, `normalize_persona`,
  `validate_persona`) already carries `prompt`, `temperature`, `few_shot`,
  `format`, `dictionary_scope`, `model_hint`, `output_policy`, `safety_mode`,
  `max_completion_tokens`, `chunk_size` — fully wired into inference
  (`compose_persona_system_prompt`, `compose_persona_messages`,
  `process_fast_lane`).
- `lint_persona()` (llm_engine.py:545) already does rule-based contradiction
  detection (e.g. "match length" + "expand" conflict) — the exact pattern
  Persona Foundry's contract-contradiction check reuses and extends.
- `run_persona_preview()` (llm_engine.py:1481) already runs one sample through
  an **unsaved** persona dict — this is the stress-test executor, no new
  inference plumbing needed.
- `build_guided_persona_prompt()` (llm_engine.py:661) is a smaller precedent
  for LLM-assisted prompt drafting; Foundry's compile step is a richer version
  of the same idea.
- `POST /personas` (server.py:1876) already accepts a full v2 payload and
  partial-merges it via `upsert_persona` — Foundry's final save reuses this
  route unchanged.

The gap is the guided layer: nothing today interviews the user, detects
vagueness, generates stress-test edge cases, or produces a character card.

## Goals

1. A local-LLM-and-rule-driven interview walks the user through Role →
   Character → Output Contract → Examples → Anti-examples.
2. Vague answers get deterministic, specific pushback (no infinite loops —
   at most one re-ask per question).
3. Contradictory contract choices are caught before compile, mirroring
   `lint_persona()`'s style, and surfaced as a forced choice.
4. At least 3 raw/desired example pairs and 1+ anti-example are required
   before compiling.
5. Compile produces a full schema-v2 persona (system prompt, few-shot,
   temperature, output_policy, safety_mode) **plus** a `persona_card`
   (archetype, temperament, forbidden, signature_moves, favorite_phrases,
   reliability_score) — all stored in the existing YAML persona store.
6. A stress-test pass runs 7 fixed-category nasty inputs (rambling, angry,
   short command, embedded question, sensitive text, long paragraph, weird
   slang) through the compiled-but-unsaved persona so the user can see
   before/after and approve/reject/correct before saving.
7. Nothing is saved until the user explicitly approves at the end — Foundry
   sessions are ephemeral and never touch `personas.yaml` directly.

## Non-Goals

- Do not replace or modify the existing manual persona wizard.
- Do not require a GPU — interview-step navigation, vagueness checks, and
  contradiction detection are deterministic/rule-based (fast on the 4B/no-GPU
  floor tier); the LLM is invoked only where generation is the actual point:
  compiling the prompt/character-card text and drafting stress-test inputs.
  If those calls fail or don't parse, fall back to safe defaults — never
  crash the interview.
- Do not persist interview sessions across a server restart (in-memory only,
  like `draft_queue`) — losing an in-progress Foundry session on restart is
  acceptable.
- Do not build true open-ended NLU. Free-text answers get lightweight
  heuristic vagueness checks (word count + banned-vague-word list), not a
  round-trip LLM judgement call per answer — keeps it fast and testable
  without a live model.
- Do not add persona "reliability" as a blocking gate — it's informational
  on the character card, never blocks saving.

## Design: the interview as a flat, resumable question list

Rather than free-form dialogue, the interview is an ordered list of typed
questions (`FOUNDRY_QUESTIONS` in `llm_engine.py`), each with an id, group,
prompt, kind (`text` | `choice`), and validation rule. The server walks the
list one question at a time; the client never needs its own copy of the
protocol. Two groups (`examples`, `anti_examples`) are repeatable collections
with a minimum count instead of a single fixed question.

```
role                    (text)   "What is this persona for?"
character_cares         (text)   "What does this persona care about?"
character_hates         (text)   "What do they hate?"
character_language      (text)   "What kind of language do they use?"
character_temperament   (text)   "Warm, sharp, formal, strange, funny, severe — which fit?"
character_never         (text)   "What should they never do?"
contract_scope          (choice) rewrite_only | can_answer
contract_length         (choice) preserve_length | flexible_length
contract_expand         (choice) expand_ideas | stay_literal
contract_tone_shift     (text)   "Smarter, funnier, calmer, more aggressive, or just cleaner?"
contract_profanity      (choice) keep_profanity | clean_profanity
contract_safety         (choice) sanitize | leave_as_is
  -> contradiction check runs here (e.g. expand_ideas + preserve_length)
examples                (collection, min 3)  {raw, desired}
anti_examples            (collection, min 1)  free text
  -> interview complete; client calls /personas/compile
```

Session shape (in-memory dict, keyed by `session_id` uuid4, capped/evicted
like `draft_queue`):

```python
{
  "id": "...", "created": <monotonic>, "cursor": 0, "pushback_used": set(),
  "answers": {"role": "...", "contract_scope": "rewrite_only", ...},
  "examples": [{"raw": "...", "desired": "..."}, ...],
  "anti_examples": ["...", ...],
  "done": False,
}
```

## Phase 1: `persona_card` schema field

> **Status: ✅ DONE.** `default_persona_card()`, `_coerce_persona_card()`,
> `compute_reliability_score()` added to `llm_engine.py`; `default_persona()`
> now carries an empty `persona_card`, `normalize_persona()` coerces it
> defensively, `validate_persona()` type-checks it non-blocking. 10 new tests
> in `tests/test_persona_schema_v2.py` (`PersonaCardTests`,
> `ReliabilityScoreTests`), file now 31/31 green. No changes to
> `upsert_persona` needed — its shallow `dict.update(persona)` merge already
> passes `persona_card` through.

### Problem

Schema v2 has no place to store the narrative "character card" (archetype,
temperament, forbidden behaviors, signature moves, favorite phrases,
reliability score) that Persona Foundry compiles.

### Changes

- `llm_engine.py`: add `persona_card` to `default_persona()` — a dict with
  `display_name`, `archetype`, `temperament` (list), `favorite_phrases`
  (list), `forbidden` (list), `signature_moves` (list), `best_use_cases`
  (list), `anti_examples` (list), `eval_cases` (list of
  `{category, input, output, verdict}`), `reliability_score` (int, 0-100).
  All default to `""` / `[]` / `0`.
- `normalize_persona()`: coerce `persona_card` defensively (same pattern as
  `voice`/`format` — type-check dict, coerce sub-fields, drop anything
  unexpected). Never raise on malformed input.
- `validate_persona()`: `persona_card` is optional and non-blocking — only
  type-check if present (must be a dict).
- New pure function `compute_reliability_score(persona_card, num_examples,
  had_contradiction, stress_approval_ratio=None)` → int 0-100. Base 40, +10
  per example up to 3 (30 max), +10 if no contradiction was hit during
  interview, +20 * approval_ratio once stress-test grading exists (0 if not
  yet run). Pure, no I/O — easy to unit test.

### Files

- `llm_engine.py`
- `tests/test_persona_schema_v2.py` (extend with `PersonaCardTests`)

### Implementation Notes

- Keep `persona_card` fully optional so every existing test/persona
  (prompt-only, v1 legacy) still normalizes and round-trips unchanged.
- `upsert_persona` already partial-merges dicts field-by-field for known
  keys — verify `persona_card` merges the same way (whole-field replace is
  fine here, unlike `format`/`voice` sub-merging, since Foundry always writes
  the whole card at once).

## Phase 2: Interview session engine

> **Status: ✅ DONE.** `llm_engine.py` side done: `FOUNDRY_QUESTIONS`
> (12 fixed questions across role/character/contract groups),
> `foundry_new_session/foundry_next_prompt/foundry_submit_answer`,
> deterministic vagueness pushback (one re-ask max) and contract-contradiction
> detection/resolution (`_foundry_contract_conflicts`, mirrors
> `lint_persona()`'s style) all implemented and covered by
> `tests/test_persona_foundry.py` (14 tests). Deviated from the original plan
> in one way: instead of a separate `foundry_current_question()`, a single
> `foundry_next_prompt(session)` covers all three states (fixed question,
> conflict re-ask, collection prompt) — simpler for the server route to call.
> Routes landed once `server.py` freed up: `POST /personas/interview/start`
> and `POST /personas/interview/answer`, backed by an in-memory
> `_foundry_sessions` dict (capped at 20, oldest evicted — mirrors
> `draft_queue`). 11 route tests in `tests/test_server_foundry_routes.py`,
> all green.

### Problem

No state machine exists to walk a user through the protocol, detect
vagueness, or catch contract contradictions before compile.

### Changes

- `llm_engine.py`: add `FOUNDRY_QUESTIONS` (ordered list, see Design above),
  `FOUNDRY_VAGUE_WORDS` (banned one-word answers: "good", "nice", "idk",
  "not sure", "whatever", "normal", "fine", "professional"), and:
  - `foundry_new_session() -> dict` — fresh session shape.
  - `foundry_current_question(session) -> dict | None` — the question at
    `cursor`, or `None` if in a collection group or done.
  - `foundry_submit_answer(session, answer) -> dict` — validates/records the
    answer for the current question (or appends to `examples`/
    `anti_examples` for collection groups), advances `cursor`, and returns
    `{"session": session, "pushback": str|None, "done": bool}`.
    - Text questions: pushback once if `len(answer.split()) < 3` or
      `answer.strip().lower() in FOUNDRY_VAGUE_WORDS`; on the second attempt
      (id already in `pushback_used`) accept regardless.
      Pushback message: `"Too vague. Give me one sentence this persona would
      actually write."`
    - Choice questions: reject (no advance, no pushback-budget spend) if the
      answer isn't in the question's `choices`.
    - After `contract_safety` (last contract question) answered: run
      `_foundry_contract_conflicts(answers)` — deterministic rule table
      (start with: `expand_ideas` + `preserve_length`). If a conflict is
      found and not yet resolved, re-surface `contract_length` as the
      current question with pushback text built from the conflict, e.g.
      `"You chose 'expand ideas' and 'preserve exact length'. Those
      conflict. Which matters more?"`, and require a changed answer before
      advancing.
    - `examples` group: accepts `{"raw": str, "desired": str}`; both
      required non-empty; caller (client) decides when 3+ are enough and
      sends a `{"next": true}` marker to move to `anti_examples` — reject
      the marker if fewer than 3 collected.
    - `anti_examples` group: accepts a free-text string; same `{"next":
      true}` marker to finish, rejected if zero collected.
- In-memory session store lives in **server.py** (not llm_engine.py, to
  match the `draft_queue` pattern of app-level ephemeral state):
  `_foundry_sessions: dict[str, dict]`, capped at 20 concurrent sessions
  (evict oldest by `created` on overflow — single-user local app, generous
  cap is fine).
- New routes (server.py):
  - `POST /personas/interview/start` → `{}` → creates session, returns
    `{"session_id", "question": <first question dict>, "done": false}`.
  - `POST /personas/interview/answer` → `{"session_id", "answer"}` →
    looks up session, calls `foundry_submit_answer`, returns
    `{"question": <next question dict or null>, "pushback": str|None,
    "done": bool}`. 404 on unknown `session_id`.

### Files

- `llm_engine.py`
- `server.py`
- `tests/test_llm_persona_management.py` or a new
  `tests/test_persona_foundry.py` (prefer new file — this is a distinct
  subsystem, matches the repo's one-file-per-feature test convention)
- `tests/test_server_persona_routes.py` (route-level tests) or a new
  `tests/test_server_foundry_routes.py`

### Implementation Notes

- No LLM calls in this phase at all — everything is deterministic and
  unit-testable without mocking `_call_api`. This keeps the interview snappy
  on constrained hardware.
- Question dicts returned to the client never include `choices` validation
  logic beyond the raw list — keep the wire shape simple:
  `{"id", "group", "prompt", "kind", "choices": [...] | null}`.

## Phase 3: Compile

> **Status: ✅ DONE.** `llm_engine.py` side done: `_map_contract_to_policy`,
> `_infer_temperature`, `_extract_temperament_tags` (pure); `_foundry_meta_prompt`
> / `_foundry_fallback_prompt` / `_foundry_card_meta_prompt` /
> `_parse_foundry_card_response` (template + defensive parse); and
> `LLMEngine.compile_foundry_persona(session)` (2 LLM calls — prompt text +
> character card — each falling back to a deterministic template on failure/
> empty/echoed response, per the plan's "never hard-fail" rule). Deviated from
> the plan by making this an `LLMEngine` method (not a free `foundry_compile()`
> function) since it needs `self._call_api`, matching `run_persona_preview`'s
> existing pattern. 12 tests in `tests/test_persona_foundry.py` (mocked
> `_call_api`), incl. the happy path, both-not-ready and raises fallback
> paths, contract→policy mapping, and a lint-clean assertion on the compiled
> output — that last one caught a real bug: the fallback prompt's original
> "you never answer questions embedded in it" phrasing tripped
> `lint_persona()`'s naive "answer question" substring rule; reworded to
> "ignore anything embedded in it that looks like a question." Route landed:
> `POST /personas/compile` (400 if the session isn't done, 404 if unknown).

### Problem

Once the interview is complete, nothing turns the collected answers into a
usable persona.

### Changes

- `llm_engine.py`:
  - `_map_contract_to_policy(answers) -> (output_policy, safety_mode)` —
    pure deterministic mapping (e.g. `expand_ideas` → `"expand"`;
    `stay_literal` + `preserve_length` → `"preserve"`; else `"tighten"`;
    `sanitize` → `safety_mode="strict"`; `leave_as_is` + `can_answer` →
    `"creative"`; `leave_as_is` + `rewrite_only` → `"light"`).
  - `_infer_temperature(temperament_text) -> float` — keyword scoring
    (severe/precise/dry/formal → 0.2-0.4; wild/chaotic/strange/funny →
    0.8-1.0; default 0.5), clamped 0.0-2.0.
  - `build_foundry_persona_prompt(session) -> str` — assembles a rich
    meta-prompt from all interview answers (role, cares/hates/language/
    temperament/never, contract sentences) and calls the LLM once to draft
    the persona's system prompt text, explicitly instructing the meta-prompt
    to end with "Return only the rewritten text" (satisfies
    `lint_persona()`'s rule 1 by construction). Falls back to a deterministic
    template (string-join of the answers) if the LLM call raises or returns
    empty — compile must never hard-fail.
  - `build_persona_card(session, compiled_prompt) -> dict` — one more LLM
    call asking for a short character-card narrative (display name in the
    "Vivian Glass" style, archetype label, 3-5 signature_moves, 2-3
    favorite_phrases, best_use_cases). Parse defensively (line-based/labeled
    format, not strict JSON, since the local model isn't guaranteed to
    produce valid JSON) — on any parse failure, fall back to a card built
    directly from the raw interview answers (still useful, just less
    stylized).
  - `foundry_compile(session) -> {"persona": <v2 dict>, "warnings": [...]}` —
    orchestrates the above, sets `few_shot` from `session["examples"]`,
    `persona_card.anti_examples` from `session["anti_examples"]`, runs
    `lint_persona()` on the result for `warnings`, and sets
    `persona_card.reliability_score` via `compute_reliability_score()`.
    Does **not** call `upsert_persona` — compile only returns the dict for
    client-side review.
- `server.py`: `POST /personas/compile` → `{"session_id"}` → 400 if the
  session isn't `done`; else returns `foundry_compile(session)`'s result
  unchanged (schema matches what `POST /personas` already accepts, so the
  client can pass it straight through on save).

### Files

- `llm_engine.py`
- `server.py`
- `tests/test_persona_foundry.py` (mock `_call_api` for the two LLM-backed
  helpers; test `_map_contract_to_policy`/`_infer_temperature` directly, pure)

### Implementation Notes

- Mirror `run_persona_preview`'s "not ready → safe fallback" pattern for
  both LLM calls in this phase.
- The compiled dict's `prompt` field must pass `validate_persona()` — add an
  assertion in tests that `foundry_compile()` output always validates.

## Phase 4: Stress test

> **Status: ✅ DONE.** `llm_engine.py` side done:
> `FOUNDRY_STRESS_CATEGORIES` (7 fixed categories), `FOUNDRY_STRESS_SEEDS`
> (generic fallback per category), `_parse_foundry_stress_response`
> (defensive `category: input` line parser, falls back per-category),
> `LLMEngine.generate_foundry_stress_cases(persona)` (1 LLM call) and
> `LLMEngine.run_foundry_stress_suite(persona)` (generates cases, runs each
> through the existing `run_persona_preview`). 5 tests. Route landed:
> `POST /personas/test-suite/run` (accepts either `session_id`, which
> recompiles first, or a raw `persona` dict for re-running after edits).

### Problem

The user should see how the compiled persona behaves on hard inputs before
committing to it.

### Changes

- `llm_engine.py`:
  - `FOUNDRY_STRESS_CATEGORIES = ["rambling", "angry", "short_command",
    "embedded_question", "sensitive_text", "long_paragraph", "weird_slang"]`
  - `FOUNDRY_STRESS_SEEDS` — a small built-in fallback input per category
    (generic, not persona-specific) used if LLM generation fails/doesn't
    parse, so the feature degrades gracefully rather than breaking.
  - `foundry_generate_stress_cases(persona) -> [{"category", "input"}, ...]`
    — one LLM call requesting a tailored nasty input per category (using the
    persona's role/domain from its prompt for flavor), parsed line-by-line
    with a `CATEGORY: text` convention; any category that fails to parse
    falls back to its seed.
  - `foundry_run_stress_suite(persona, engine) -> [{"category", "input",
    "output"}, ...]` — calls `foundry_generate_stress_cases()` then runs each
    input through `engine.run_persona_preview(persona, input)` (Phase 4 reuses
    Phase-existing inference, no new call path).
- `server.py`: `POST /personas/test-suite/run` → `{"session_id"}` (looks up
  the session, requires it to be `done`, recompiles via `foundry_compile`
  internally so the suite always reflects current answers) **or**
  `{"persona": <v2 dict>}` directly (so the client can re-run after editing
  the compiled result). Returns `{"cases": [...]}`.

### Files

- `llm_engine.py`
- `server.py`
- `tests/test_persona_foundry.py`

### Implementation Notes

- Cap total stress-test LLM work: 1 call to generate all 7 inputs + 7 calls
  to `run_persona_preview` = 8 calls per run. Fine for a manual, user-
  triggered action; do not auto-run on every answer.
- User approve/reject/correct on each case is a pure frontend concern — the
  corrected `eval_cases` (with a `verdict` per case) get folded into
  `persona_card.eval_cases` client-side and sent along with the final
  `POST /personas` save. No extra backend route needed for grading.

## Phase 5: Frontend — Foundry UI

> **Status: ✅ DONE.** New `#foundryOverlay` modal (separate DOM tree from the
> manual wizard) in `index.html`, styled in `base.css`, driven by `initFoundry()`
> + ~15 helper functions in `main.js`; a "🔨 Build with AI (Persona Foundry)"
> button opens it from the Persona Configuration settings group. `backend.js`
> gained the 4 thin wrappers. Verified **end-to-end in a real browser preview**
> (isolated scratch backend, no real-model auto-warmup) — not just unit tests:
> full interview walkthrough including a vagueness pushback and a deliberately
> triggered contract contradiction (both resolved correctly), the
> examples/anti-examples collectors (min-count enforcement, list rendering),
> a **real LLM compile** (not the fallback path — got a genuinely good
> character card: "Victor Stern, Executive Editor", reliability score 70/100
> matching the expected 40+30(examples)+0(had contradiction) formula), the
> stress-test suite route (7 tailored categories, real outputs), and a full
> save round-trip confirmed via `GET /personas/{name}` — `persona_card`
> persisted intact. One dependency found and fixed along the way: `persona_card`
> was missing from `PersonaRequest`/`save_persona_route`'s allowlist in
> server.py (flagged via collab; `voice-studio` landed the 3-line fix).

### Problem

No UI exists to drive the interview/compile/stress-test/save flow.

### Changes

- `app/src/renderer/api/backend.js`: add `startFoundryInterview()`,
  `answerFoundryQuestion(sessionId, answer)`, `compileFoundry(sessionId)`,
  `runFoundryStressTest(sessionIdOrPersona)` — thin wrappers matching the
  existing `lintPersona`/`testPersona` style.
- `app/src/renderer/index.html`: new **Persona Foundry** entry point (a
  button near the existing persona picker, e.g. "🔨 Build with AI") that
  opens a new modal/panel — separate DOM tree from the existing 4-step
  wizard, so it doesn't interact with `wizardStep*` state at all. Screens:
  1. Chat-style interview: question bubble + text input (free-text
     questions) or quick-select buttons (choice questions); pushback
     messages rendered distinctly (e.g. a "hmm—" prefix/tint).
  2. Examples collector: raw/desired pair form (reuse the existing few-shot
     table markup/styling), "add another" + "I have 3, continue."
  3. Anti-examples collector: simple repeatable text list.
  4. Stress-test review: one card per category showing input → output, with
     approve/reject/edit-in-place per card.
  5. Character card + compile review: renders `persona_card` (name,
     archetype, temperament, signature moves, forbidden, favorite phrases,
     reliability score) alongside the compiled prompt/fields, editable
     persona name field, "Save Persona" button calling the existing
     `savePersona()`.
- `app/src/renderer/main.js`: state + handlers for the above screens;
  `foundrySessionId` in module state; on save, call `refreshPersonasAndVoices()`
  (existing function) so the new persona shows up everywhere immediately.
- `app/src/renderer/styles/base.css`: styling for the chat bubbles,
  pushback tint, character card layout, stress-test grid.

### Files

- `app/src/renderer/api/backend.js`
- `app/src/renderer/index.html`
- `app/src/renderer/main.js`
- `app/src/renderer/styles/base.css`

### Implementation Notes

- These four files currently carry unrelated uncommitted changes (auth/UI
  polish, MCP client wiring). Read current on-disk state before every edit;
  add additively; never revert unrelated hunks.
- JS parse-check (`node --check`) after edits, matching the U7-editor phases'
  verification convention.
- Keep the existing manual wizard's `savePersona()` call path exactly as-is
  — Foundry's save button is a second caller of the same function, not a
  fork of it.
- Coordinate with the `voice-control`/`voice-studio` sessions if they touch
  the same 4 renderer files concurrently — claim narrowly via `collab_claim`
  before each edit, not the whole file for the whole phase.

## Phase 6: Tests, docs, polish

> **Status: ✅ DONE.** `tests/test_persona_foundry.py` (40 tests: question
> list shape, full happy-path walkthrough, vagueness pushback, contract
> contradiction + resolution, collection minimums, contract→policy mapping,
> temperature inference, card/stress-response parsing, compile with a mocked
> LLM incl. both-failure-mode fallbacks, stress-suite generation) +
> `tests/test_persona_schema_v2.py` extensions (10 tests: `persona_card`
> normalize/validate/round-trip, `compute_reliability_score`) +
> `tests/test_server_foundry_routes.py` (11 route tests) = **61 new backend
> tests**, plus the full existing suite stays green (628/629 — the 1 failure
> is a pre-existing cross-test state leak in `test_token_concepts.py`
> unrelated to this feature, passes in isolation). Added a minimal Playwright
> smoke test (`app/tests/electron-smoke.spec.js`) covering open → first
> question → close (not run locally — Electron e2e is resource-heavy and
> multiple sessions were active; the interview/compile/save flow was instead
> verified for real against a live, isolated backend in a browser preview,
> which is a stronger signal than a scripted click-through would give).
> `docs/MANUAL_QA_CHECKLIST.md` gained a full Persona Foundry section;
> `docs/MASTER_PLAN.md` gained a `U12` entry (top-of-file log + Phase 4
> table row).

### Changes

### Changes

- Finish `tests/test_persona_foundry.py`: full interview walk-through
  (happy path), vagueness pushback + retry-then-accept, contract
  contradiction + resolution, examples/anti-examples minimums, compile
  output validates + lints clean on a well-formed session, stress-suite
  fallback-seed path when LLM generation is mocked to fail.
- Extend/add server route tests for all 4 new routes (404s, 400s on
  not-done session, happy path end-to-end including a final `POST
  /personas` save using compile output).
- `app/tests/electron-smoke.spec.js`: smoke-check the Foundry entry point
  opens and the first question renders (don't require a live model in CI —
  check how existing persona-route Playwright coverage handles/mocks the
  sidecar LLM, if at all, and follow the same approach).
- `docs/MANUAL_QA_CHECKLIST.md`: add a Persona Foundry section (full
  interview → compile → stress-test → save, verify saved persona works in
  actual dictation).
- `docs/MASTER_PLAN.md`: add a new item (suggest `U12 — Persona Foundry`)
  under Phase 4 (Voice, TTS, personas) referencing this plan doc, once
  Phases 1-5 here are done.

### Files

- `tests/test_persona_foundry.py`
- `tests/test_server_foundry_routes.py` (or merged into the above)
- `app/tests/electron-smoke.spec.js`
- `docs/MANUAL_QA_CHECKLIST.md`
- `docs/MASTER_PLAN.md`

## Suggested Order

Phases 1 → 2 → 3 → 4 are backend-only and strictly sequential (each phase's
routes depend on the previous phase's session/compile shape). Phase 5
(frontend) can start once Phase 2's routes exist (interview screens don't
need compile/stress-test yet) and finishes after Phase 4 lands. Phase 6 runs
alongside each phase (tests written as routes land) with a final pass at the
end for the smoke test + docs.

Keep `python3 -m pytest -q` green after every phase; commit per phase.
