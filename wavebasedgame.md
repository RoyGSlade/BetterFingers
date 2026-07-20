# The Lost Meaning: Infinite Stacks — Remaining Work (Wave Plan)

> Forward plan for everything left between the end of wave 5 and the
> first-complete-Spire Definition of Done in `infinite_stacks.md` §31.
> What has already shipped is recorded in `plangamereporting.md`.
>
> Last updated: 2026-07-19 (end of wave 5; PR chain
> #65→#66→#67→#68→#69→#70). Wave 5 SHIPPED — the game is human-playable
> end to end, and the playtest checkpoint below is now ACTIVE.

## Working model

Each wave = 3 parallel worker lanes with disjoint file ownership, a
designated domain-schema owner, contracts posted to room chat early, and
director-run verification before anything is accepted. Big systems arrive
pure-package-first, domain-wired the following wave. All estimates below
assume that cadence; waves regularly absorb one or two small unplanned
fixes (budget for it).

Standing gates for every wave: all existing stacks suites, the two
architecture gates (`test_architecture_report.py`,
`test_architecture_smoke.py`), the old game's suites untouched, and
`node --check` on the client.

---

## ✅ Wave 5 — SHIPPED (PR #70)

All three lanes (tasks #16/#17/#18) landed: enemy to-hit + live reaction
interrupts with the pending-reaction window and transport auto-pass
timer, the full hero WS/REST surface + character-builder/hand/inventory
UI, and shops wired into the world with the layering cleanup and
server-side `share_clue`. Exit gate met: a human can create a hero in
the browser, explore, solve a puzzle, fight with real reactions, shop,
and finish a floor. Details in `plangamereporting.md`.

### ⚠ Playtest checkpoint — NOW ACTIVE

The spec's Definition of Fun (§30) gates further progress on **human
playtests** — simulation cannot establish fun (§26.3). Schedule 1–4
player sessions on the golden floor and collect the §26.4 questions
before or during wave 6. Worker agents cannot do this part. Findings
feed directly into wave-6 scope (balance changes go through §32's
documented-defaults process, never scattered constants).

---

## Wave 6 — Run lifecycle + remaining room families (Phase 5/6 remainder)

- **Run lifecycle (RUN-001):** enter/retreat/floor-completion/collapse as
  domain state; the end-of-run summary screen driven by the shops
  package's already-tested run-summary fold; between-run hub loop (§6.1).
- **Room families:** Passage, Study, Wild Place, Social, Anomaly
  interfaces so every d8 face is mechanically distinct (§9; currently
  Mystery/Conflict/Shop are real). Passage subtypes must alter
  routing/tempo/information; Studies do knowledge-work incl. binding
  fragments; at least one Social route must run on listening/evidence.
- **More puzzle templates:** grow from 1 toward the 8 needed for first
  playable (§23.3), each with generator + independent solver at 1,000+
  seeds (logic-grid, symbol substitution, switch routing, distributed
  clues are the natural next four).
- **Meaning Checks (§19.2):** speaker intent → other players interpret →
  structured comparison; human interpretation is the mechanic, the LLM
  grades nothing.

## Wave 7 — Progression: accomplishments, trophies, legacy (Phase 7)

- Event-based accomplishment evaluator with anti-farming (seed/difficulty
  restrictions, tier caps) — ACCOMP-001.
- Trophy Marks, escalating costs (1/3/6/10/15), respec, perk unlocks,
  three-slot equipped loadout — TROPHY-001.
- Memorials and Legacy Volumes: last words, item recovery, heirlooms —
  LEGACY-001.
- Profile persistence: SQLite campaign store, export/import, migrations
  (§22.6) — PROFILE-001. (First real persistence work; everything so far
  is in-memory + replay.)
- Initial 20 accomplishments in content.

## Wave 8 — Books, library, Spires, world restoration (Phase 8)

- BookRecord: structured facts, fragments, disputes, chosen
  interpretations, repair states; facts trace to event IDs — BOOK-001.
- The library hub: shelves, research desks, bindery, memorial wing,
  map table — LIBRARY-001.
- Spire restoration recipes, Keystone state machine, corruption and
  stability tracks driving room-table changes — SPIRE-001.
- Region/world changes on cure; post-cure exploration — WORLD-001.
- Progressive prose generation (title → summary → excerpt → chapter),
  cached by content hash, versioned editions — BOOK-PROSE-001. Note: this
  is presentation-layer only; deterministic fallbacks keep the game fully
  playable with no model.

## Wave 9 — BetterFingers integration (Phase 9)

- Compose flow: faithful/clearer/characterful variants + the preservation
  receipt (target, intent, facts, negations, commitments, ambiguity) —
  BF-COMPOSE/RECEIPT-001. Reuse the shipped `rescue_message` machinery
  from the main app.
- NPC dialogue acts rendered through personas (rules decide outcomes,
  never the model) — BF-NPC-001.
- Bounded local transcription + review; optional captioned TTS —
  BF-SPEECH/TTS-001.
- Complete offline/authored fallback behavior; model timeout never blocks
  state progression — BF-FALLBACK-001.
- Privacy tests: one player's private clue never enters another player's
  compose context.

## Waves 10–11 — First complete Spire + hardening (Phases 10–11)

Content expansion to the §23.3 "complete first Spire" targets: 3 chapters,
3 bosses with authored phases, 12 puzzle templates, 15 enemies across 5
families, 50 items / 48 cards, 60 accomplishments, 12 supporting books +
Keystone, multiple endings. Then hardening: cross-platform LAN testing,
save migration + corruption recovery, disconnect/resume/duplicate-command
testing, performance, accessibility audit, security/privacy audit,
large-seed simulation with the §26.3 headless strategy agents, and
repeated human playtests against the §31 Definition of Done.

Realistically this is 2+ waves and is content-bound, not systems-bound;
expect it to stretch based on playtest findings.

---

## Known debts and open items (tracked, not lost)

| Item | Where tracked | Target |
|---|---|---|
| Interrupt window has no live caller (enemy attacks are flat damage) | board task #16 | wave 5 |
| No WS/REST surface or UI for creation/cards/items | board task #17 | wave 5 |
| Shops unwired; `content/loader.py → shops.models` backwards edge | board task #18 | wave 5 |
| once_per_fight signature-charge helper published but uncalled | herowire handoff note | wave 5 |
| Clue Share / shared notes are client-local (no cross-browser sync) | board note 14 | wave 5–6 |
| `attempt_treat` charges gold but has no condition model | shops contract doc | wave 5 |
| `grant_check` / `emit_fact` ops are LIVE but minimally consumed | contracts doc §5 | wave 6 |
| No persistence (SQLite) — replay-from-log only | spec §22.6 | wave 7 |
| Zero LLM-generated prose anywhere yet (fallback text only) | spec §20 | waves 8–9 |
| Human playtests not yet run — Definition of Fun unverified | §26.4/§30 | from wave 5 |

## Rules that must survive every remaining wave

- Deterministic seed + event replay; events store randomness results only.
- The LLM never decides mechanics, solutions, deaths, dice, or "quality."
- No raw numeric modifiers from the wire; server derives or verifies.
- Viewer-filtered projections; private data never crosses players.
- Content is data referencing IDs; effects compile to known engine ops.
- Package `__init__` files docstring-only or lazy; modules ≤ ~500 lines.
- Fail-forward: "nothing happens" is never a major-action result.
