# The Lost Meaning: Infinite Stacks — Remaining Work (Wave Plan)

> Forward plan for everything left between the current shipped build and the
> first-complete-Spire Definition of Done in `infinite_stacks.md` §31.
> What has already shipped is recorded in `plangamereporting.md`.
>
> **Last updated: 2026-07-21 — OWNER DESIGN LOCK / REVISED ROADMAP.**
> This revision replaces the 2026-07-19 wave plan. It is written directly
> against seven owner decisions dated 2026-07-21 (§2 below), which are
> **locked and binding** — where they conflict with earlier text in
> `infinite_stacks.md`, the 2026-07-21 decision governs and the spec text
> is superseded, not deleted (call-outs below say exactly which lines).
> Two human playtests (`docs/PLAYTEST_FINDINGS_2026-07-19.md`,
> `docs/PLAYTEST_FINDINGS_2026-07-20.md`) are the other primary input to
> this revision.

## 0. How to read this document

Four different confidence levels appear below; they are labeled explicitly
because conflating them causes rework:

- **Shipped** — true today, evidenced in `plangamereporting.md`. Nothing in
  this file should claim something is fixed/shipped without that evidence.
- **Locked decision (2026-07-21)** — binding for all future waves; not
  reopened by playtesting or worker judgment.
- **Proposed default** — an existing `infinite_stacks.md` §32-style number
  or shape, still revisable through the documented playtest process.
- **Unimplemented** — scheduled here, not started.

## 1. Status recap (as of 2026-07-21)

- Waves 1–5 shipped per `plangamereporting.md` (PRs #66–#70): golden-floor
  engine, live puzzles/combat, heroes package wired, shops package, live
  reaction interrupts. The game became human-playable end to end in wave 5.
- **Wave 6 shipped** (commit `ae739f3`, PR #71 per the 07-20 playtest doc):
  playtest-response UI overhaul, cards-vs-abilities redesign, abilities
  engine. A follow-up restyle (`9551b85`, Ritual Spire UI theme) landed on
  top of it. Its `plangamereporting.md` entry was backfilled at the wave-6A
  close-out (2026-07-21), sourced from board notes 24–26 and commit history.
- **Wave 6A shipped 2026-07-21** (branches `wave6a/j12-legal-actions` +
  `wave6a/join-creation-flow` merged): the §3.1 correctness rows — J12
  (with its required regression test), J8, the pre-join modal, and the J1
  join/creation split — are closed with evidence in `plangamereporting.md`.
  The exit gate holds: a fresh session can join → create a hero → take a
  first legal map action, proven by `LegalActionsLockoutRegressionTests`,
  not manual QA. Remaining §3.1 rows (J2/J3, J7, J9, J4–J6, A–G
  re-confirmation) stay open as polish/coordination work.
- The §26.4 playtest checkpoint opened at the end of wave 5 is **active but
  not yet satisfied**: two solo owner playtests ran (07-19 against the
  wave-5 build, 07-20 against the wave-6 build) and both ended at a UI
  wall before most Definition-of-Fun questions could be answered. The
  07-20 session ended on a session-ending bug (J12, §3.1 below). Fun cannot
  be evaluated until the stop-ship gate in §3.1 is cleared.
- A second live session, `dice-ui-overhaul`, is currently working the
  static client from `designhelp/uioverhaul.zip` — 3D physics dice with
  shared rolls and custom dice presets. That work covers J4 (dice) and
  overlaps J5/J6 (token upload/crop, color-ring customization). Coordinate
  through the collab room rather than duplicating that scope.

---

## 2. LOCKED OWNER DECISIONS — 2026-07-21

These seven decisions are binding for every wave below. Each note names what
in `infinite_stacks.md` it supersedes or extends.

1. **Meaning Lattice floor completion.** Resolved rooms repair lattice
   components (Truth, Memory, Binding, Identity, Sequence, ...); a
   floor-specific required *recipe* over those components reveals the
   stair/objective. Entering a room alone does not repair it — the room
   must resolve. Optional rooms grant advantages/secrets/alt paths/rewards
   but are never part of the required recipe.
   **Supersedes** §7.3's `required_rooms = min(6 + floor, 12)` as the
   *completion gate* — that formula, and the "six required rooms" default
   listed in §32, described a raw resolved-room counter. The counter is
   demoted to a floor-size/pacing dial only; the actual unlock condition
   is now "the floor's lattice recipe is satisfied," which may or may not
   require exactly that many rooms. Do not reintroduce a bare room-count
   gate anywhere in wave 7+ work.
2. **Connected NPC casts.** Each floor normally carries 2–5 NPCs in a
   relationship web: conflicting objectives, dependencies, lies, shared
   events. Types include trapped outsiders, Spire-born, living-book
   characters, merchants, prisoners, corruption agents, and others. Some
   NPCs may remain independent of the cast. Cross-room knowledge needs
   provenance (who could plausibly know this, and how). **Extends** §9.7
   (Social Encounter) and §19.3 (NPC communication) with a cast-level
   structure neither section specified.
3. **Intent decomposition, always a response.** One player utterance/
   action decomposes into 0–3 atomic intents. Even a zero-intent,
   harmless, or mechanically-unsupported action earns a fitting world
   response — never "nothing happens." Ambiguity gets clarified;
   deterministic fallbacks apply where a mechanic exists; unsupported
   interaction demand gets logged (a real content-gap signal, not a
   silent dead end). **Formalizes** the §4.1 "every important failure
   creates play" pillar and the closing rule in the old wavebasedgame.md
   ("fail-forward: 'nothing happens' is never a major-action result") into
   a concrete parsing contract — see §3.5 below.
4. **Social degrees.** `d20 + attribute + skill + contextual schmoozing
   modifier (-5..+5)`, resolved by the existing §12.3 degree table. The
   modifier's magnitude comes from in-world evidence, leverage,
   relationship, motive alignment, or a strongly counterproductive
   approach — never from grammar, eloquence, verbosity, disability, or
   flattering the model. **Extends** §12.1 (which had no modifier slot)
   and makes the existing §19.4 privacy/accessibility ban on
   delivery-based scoring into a numeric, testable contract.
5. **Party scaling locks on Ready.** When all 1–4 players click Ready, the
   run generates for that count and never rebalances — not mid-run, not on
   split, not on disconnect/reconnect (which preserves the locked seat). A
   run begun with one player is solo-scaled permanently. **Extends** §15.1
   (threat budget already keys off "total living party") by fixing the
   moment that count is sampled: at Ready-click, not per-room. Split heroes
   remain exposed to the locked threat level but must always have a
   telegraphed escape, delay, barricade, hide, negotiate, or
   staggered-arrival option — this is not new (§15.2) but is restated
   because locked scaling raises the stakes of getting it wrong.
6. **Spire/Keystone structure.** Every Spire has a finite summit/Keystone
   and its own reward package. Floor-count profiles: 5, 10, or 15 floors
   now; 20 is future content. Initial scope is **three Spires**,
   reasonably sized 5/10/15. Curing a Spire changes its region and expands
   library/world/content. **Extends** §5.2/§18.6 (which described the
   Keystone mechanic but not a floor-count menu) and narrows §31's
   "first complete Spire" target to a specific profile set.
7. **vLLM is optional and unimplemented.** A feature-flagged performance
   experiment for concurrent split-party inference only. Not a rules
   component, not required, not built. Whatever ships must preserve
   queues, per-player privacy, timeout/caching, deterministic/authored
   fallback, and a working non-vLLM route at all times. No wave below may
   treat vLLM as a dependency for anything.

---

## 3. Design contracts

### 3.1 Stop-ship bug/UX gate

Source: both playtest docs. **Nothing below may be checked off without a
`plangamereporting.md` entry recording it — a commit message, a self-report,
or this file's own text is not evidence.**

| ID | Problem | Fix contract |
|---|---|---|
| **J12 (P0, session-ending)** | From the entrance room, live `legalActions` return no legal Move/Inspect/Pass — both the hint line and the buttons agree the player is locked out from turn one. | Root-cause the legal-actions projection for the entrance room (suspects per the playtest doc: stale/empty projection, wave-6 per-connector move/breach cost gating not matching what the map screen reads, or the hint line and the buttons reading different legality sources). Add a **browser integration test**: join → create hero → assert at least one legal map action (move/breach/inspect/pass) is selectable and executes. This test must exist before J12 is marked closed. |
| **J8 (P0)** | Hero name input drops focus after one keystroke on the creation screen (likely a re-render stealing focus on every state change). | Fix whenever the creation screen is next touched — do not defer past this gate given J1/J9 also touch that screen. |
| **Pre-join rules modal** | A rules modal blocks "Kindle a New Run" before join. | Modal must not gate the primary CTA; onboarding content moves to the persistent help/first-run overlay described in the old B1/B2 findings, not a blocking pre-join dialog. |
| **J1** | Joining asks for hero identity too soon; join should be minimal, identity belongs in the creation flow. | Split join (minimal) from creation (identity) as two distinct steps. |
| **J2/J3** | Attributes, skills, and background powers have no in-UI explanation; background powers hide under the generic label "signature ability" instead of a unique name. | Every attribute/skill needs a surfaced description (what it governs, when it's rolled); every background power gets a unique display name, never the generic label. |
| **J7** | `careful_approach` / `steady_nerve` present as "choose two" with exactly two options — not a real choice, and one is a restatement of the E1 "look around" offense from 07-19. | Either add real alternatives or reframe as a genuine binary with distinct mechanical effects; do not ship a fake choice. |
| **J9** | The build-preview card is stat soup — doesn't sell the character for a roleplay-forward game. | Preview redesign is content/presentation work, not urgent relative to J12/J8, but tracked here so it isn't lost. |
| **J10** | Card content is scrapped pending owner direction; the cards-vs-abilities *structure* from wave 6 stands. | **Do not redesign card content again until the owner supplies direction.** Structural work (ability engine, card/ability split) may continue. |
| J4 | Dice presentation is a placeholder. | Owned by the `dice-ui-overhaul` session (3D physics dice, shared rolls, presets). This roadmap's requirement: whatever ships must be an **authoritative server-result ceremony** — the client renders, the server supplies the result, per the existing §24.2 rule ("the client never determines authoritative randomness"). Coordinate rather than duplicate. |
| J5/J6 | Token upload/crop/guide-overlay; color as animated ring border with presets/JSON export. | Tracked, **lower priority than correctness** (J12/J8/J1 first). Overlaps `dice-ui-overhaul` scope — confirm ownership in the collab room before starting. |
| J11 | Character sidebar bones are good. | **Preserve** through any restyle — do not regress this while fixing the rest. |
| A/B/C/D/F/G (07-19) | Card anatomy/affordance, onboarding, movement click-to-act, character sheet numbers, map tokens, overall theme. | Mostly addressed structurally by wave 6 (tokens, cards-vs-abilities) per the 07-20 doc's own "verified better" list — but unverified in `plangamereporting.md`. Re-confirm against the 07-20 doc's "regressed/still failing" list before closing any A–G row. |

Gothic living-manuscript presentation polish (theme, ring animation flavor,
etc.) is real work but is explicitly **below correctness** in priority —
it does not block J12/J8/J1 fixes and should not be scheduled ahead of them.

### 3.2 Revised core loop

```text
structured room
  -> BetterFingers narrates only visible facts
  -> players inspect/talk/use objects
  -> stateless intent interpretation
  -> engine validates triggers/check/DC
  -> player rolls
  -> engine resolves degree
  -> BetterFingers performs/narrates only the allowed resolved outcome
  -> engine commits room/NPC/object/lattice state
  -> next choice
```

**BetterFingers may be stateless; the game state is not.** The engine owns
truth, memory, secrets, randomness, DCs, outcomes, state deltas, and
disclosure. Every generation call in this loop is a fresh, bounded packet
(see §3.5) — never a running conversation the model remembers.

### 3.3 Room/object templates

Rooms carry: archetype/purpose/layout, objects, atmosphere/condition/
cleanliness, visible facts, subtle inconsistencies, secrets, clue graph,
mechanisms, interactables, NPC links, subobjectives, hazards, encounter
hooks, persistence, **lattice contribution** (§2.1), and narration facts.

Every physical object is its own **versioned instance**: state, visibility,
transitions, triggers, 0/1/many supported intents, multiple uses,
deterministic effects. Furniture and set dressing (fireplace, rugs, desks,
chairs, decor, books) deserve secondary interactions, not just flavor text.

Procedural placement works **backward** from a distinctive interaction/
consequence, so a room reads as intentional rather than shuffled — this
extends the existing §29 risk mitigation ("shuffled templates") into a
concrete generation order: pick the payoff, then place the room around it.

### 3.4 NPC templates

Per NPC: archetype pool, age, sex/gender presentation, visual traits,
persona/voice, stats, boundaries, preferences, fears, true/false beliefs,
**provenance-backed knowledge**, free vs. gated information, lies, tells,
inventory, relationships, **three main objectives**, **one hidden
objective**, triggers, emotional/physical state, disclosure layers.

NPCs are not uniformly neutral; disposition changes over the encounter.
Purposes include clues, alternate solutions, conflict, trade, companionship,
betrayal, rest, subobjectives, world consequences. The model is fed only
**currently allowed scene facts** for that NPC — disclosure is validated
server-side so a secret cannot leak through a generated line.

### 3.5 BetterFingers/Brain + intents

No model-owned memory, anywhere. The engine builds fresh bounded packets
per call for four distinct roles: **Interpreter**, **NPC Performer**,
**Narrator**, and **event-to-book/note prose**.

The Interpreter returns **stable intent candidates** — 0 to 3 per
utterance/action — each with: confidence 1–100 (this is *interpretation
confidence*, i.e. how sure the parser is what the player meant, never a
success chance), target, method, offer/request, leverage/evidence,
keywords/triggers, requested outcome, and any ambiguity flag.

Global intent handlers are versioned; object- and NPC-specific handlers can
override them. The engine validates compound ordering, targets, action
economy, support, and requires confirmation for ambiguous or high-impact
acts. Engine-defined **immediate triggers** may alter state before a check
resolves (offering bacon can raise a dragon's hunger or change its
objective before any roll happens) — the model never defines or applies a
trigger, it only narrates one the engine already decided. The engine
supplies the resolved degree, the allowed facts, and the state delta to the
Narrator role; nothing upstream of that is ever inferred by the model.

### 3.6 Social degrees

DC is computed by the engine from: concession value, NPC stats/resolve,
risk, disposition, objectives, relationship, evidence, approach. The
`-5..+5` contextual modifier (§2.4) needs explicit tier guidance —
authored ranges (e.g. "no leverage / plausible cover story" → 0,
"forged, verifiable evidence in hand" → +3 to +5, "directly threatens the
NPC's stated fear with no offsetting motive" → -3 to -5) with accessibility
guardrails baked in from the start, not bolted on later.

Outcomes are richer than pass/fail: partial concession, counteroffer, lie,
changed disposition/objective, new danger, or a behavioral tell — mapped
onto the existing §12.3 degree table rather than replacing it.

### 3.7 Items

Roles: Offensive / Defensive / Utility, across equipment, consumables,
quest/knowledge, and unique/magical items, with clear rarity tiers.
Deterministic effects and supported intents per item; keywords, ownership,
slots, charges/wear, crafting/trade hooks, provenance/discoverability, and
bounded generated presentation (title/flavor text only — mechanics are
always data, per §20.2). This extends §13.4–13.6 rather than replacing
them: items still change options before they inflate numbers, and quest/
knowledge items still don't consume ordinary carry slots.

### 3.8 Puzzles/riddles/notes/books

Generate **backward** from authoritative answers: answer → constraint
graph → instance → independent solver → clue allocation → bounded
BetterFingers wording. **Never ship an unverified LLM riddle** — this is
already the §10.1/§23.2 contract; restated because Wave 7's puzzle
compositor is where it gets tooled, not just asserted.

Compose simple deterministic visual/minigame primitives — symbols, routes,
switches, mirrors, ordering, substitution, placement — reusable within and
across rooms rather than one-off puzzle code per room.

Notes work backward from a distinctive *later* interaction they set up, and
declare purpose/provenance/allowed facts plus subtle foreshadowing. Books
use structured facts and provenance (§18.3) and may be mechanically useful,
in-world fiction, or curated real-world history; real-world claims require
trusted curated sources. Misleading text must be **explicitly authored** as
fiction or an unreliable narrator — never an accidental hallucination
slipping through the §20.3 generation contract.

### 3.9 Rest/chill

Merchant, bed, food, fireplace/sanctuary, and reconnect zones need
concurrent, fast activities: ready-up advances immediately, everyone has a
useful short action, and the party is never forced to watch one player's
shopping UI in sequence. This extends the existing §21.4 waiting-limit rule
("no player lacks a meaningful interaction for more than 30 seconds") into
a specific room-family requirement.

### 3.10 Multiplayer

One authoritative event-sourced simulation (§22.1, unchanged); privacy-
filtered per-player scene packets (§21.3, unchanged). What's new here is
locked-Ready party scaling (§2.5) and the optional-only vLLM benchmark
(§2.7) — both must be explainable to a new contributor from this file
without reading the full spec.

---

## 4. Revised wave order

Wave 6 already shipped (§1). Everything from here is renumbered against
that reality; old wave-6 content (run lifecycle, room-family interfaces,
puzzle template growth, Meaning Checks) is redistributed below rather than
lost.

| Wave | Scope |
|---|---|
| **6A** | Stop-ship playable spine. Clear §3.1's gate: J12 legal-actions lockout + its browser integration test, J8 focus bug, pre-join modal, J1 join/creation split. Exit gate: a fresh browser session can join → create a hero → take a first legal map action, proven by the integration test, not by manual QA. |
| **6B** | One polished **Gothic Living Study** vertical slice, cutting across the full §3.2 loop: an immaculate study room, a displaced rug hiding a secret compartment, one connected NPC (§3.4), object interactions on room dressing (§3.3), stateless intent parsing (§3.5), a social-degree check (§3.6), server-authoritative visible dice (coordinate with `dice-ui-overhaul`), a persistent room/NPC state change, and one Meaning Lattice contribution (§2.1). This is the earliest full-stack proof that BetterFingers narration + engine truth actually work together — deliberately pulled forward of old Wave 9 per the 2026-07-21 lock. |
| **7** | Reusable room/NPC/object/intent/item schemas generalized from the 6B slice; verified puzzle compositor (§3.8); Meaning Lattice component types + floor-recipe authoring (§2.1); connected-cast generation (§3.4) beyond the single 6B NPC; Meaning Checks (§19.2) as one of the cast's social routes; `grant_check`/`emit_fact` op consumption grows beyond minimal. |
| **8** | Run lifecycle (RUN-001: enter/retreat/floor-completion/collapse, run summary), profile persistence (PROFILE-001: SQLite, migrations — first real persistence, everything before is in-memory + replay), accomplishments/trophies/legacy (ACCOMP-001/TROPHY-001/LEGACY-001), book/note provenance (BOOK-001), the library hub (LIBRARY-001), first 5-floor Spire (§2.6) with its Keystone. |
| **9** | Economy/rest room family (§3.9), broader content pass, second 10-floor Spire (§2.6), split-party concurrency/performance work, and the **optional** vLLM benchmark (§2.7) — feature-flagged, never a dependency for anything else in this wave. |
| **10–11+** | Third 15-floor Spire; 20-floor profile as explicit future content (§2.6); content scale-up toward the §23.3 "complete first Spire" targets; hardening (cross-platform, save migration, disconnect/resume, performance, accessibility, security/privacy, large-seed simulation, repeated human playtests against §31). |

---

## 5. Known debts and open items (tracked, not lost)

Rows below are **cleaned against `plangamereporting.md`**: rows the report
proves shipped are removed with the evidence cited; nothing is marked
fixed on the strength of a commit message alone.

| Item | Where tracked | Target |
|---|---|---|
| `grant_check` / `emit_fact` ops are LIVE but minimally consumed | contracts doc §5 | wave 7 |
| No persistence (SQLite) — replay-from-log only | spec §22.6 | wave 8 (PROFILE-001) |
| Zero LLM-generated prose/narration wired to the live loop yet | spec §20 | **wave 6B** — moved earlier per the 2026-07-21 lock; do not let this slip back to "waves 8–9" |
| UI/UX debt from both playtest docs (A–G, J1–J12) | `docs/PLAYTEST_FINDINGS_2026-07-19.md`, `docs/PLAYTEST_FINDINGS_2026-07-20.md` | wave 6A (correctness) / 6B+ (polish) — see §3.1 |
| Six-required-rooms floor-completion gate | old §7.3 formula | **superseded** by the Meaning Lattice (§2.1) — not a debt to pay down, a mechanic to replace in wave 7 |

Removed rows, with evidence:

- ~~Interrupt window has no live caller (enemy attacks are flat damage)~~ —
  shipped wave 5: "enemy attack intents resolve through `attack()`... the
  wave-4 interrupt window finally has a live caller" (`plangamereporting.md`,
  Wave 5).
- ~~No WS/REST surface or UI for creation/cards/items~~ — shipped wave 5:
  "all wave-4 hero commands round-trip over WS/REST... one-screen character
  builder... hand/deck/inventory panel" (`plangamereporting.md`, Wave 5).
- ~~Shops unwired; `content/loader.py → shops.models` backwards edge~~ —
  shipped wave 5: "layering cleanup done properly — shop content loading
  moved *into* `shops/content_loader.py`, and `content/` no longer imports
  `shops/`" (`plangamereporting.md`, Wave 5).
- ~~`once_per_fight` signature-charge helper published but uncalled~~ —
  shipped: "room/floor signature-charge refresh" is listed as shipped
  domain wiring in `plangamereporting.md`, Wave 4, and confirmed by the
  follow-up commit `2c9611d` ("call once_per_fight refresh").
- ~~Clue Share / shared notes are client-local (no cross-browser sync)~~ —
  shipped wave 5: "server-side `share_clue` command with a
  `party_shared_clues` projection" (`plangamereporting.md`, Wave 5).
- ~~`attempt_treat` charges gold but has no condition model~~ — shipped
  wave 5 under its current name: "`shop_treat` consumes gold and applies
  real condition treatments" (`plangamereporting.md`, Wave 5).
- ~~Human playtests not yet run — Definition of Fun unverified~~ —
  superseded: two playtests have now run (07-19, 07-20); the finding is no
  longer "not yet run," it's "run twice, both times gated by UI bugs before
  most Definition-of-Fun questions could be asked" — see §1 and §3.1.

---

## 6. Rules that must survive every remaining wave

- Deterministic seed + event replay; events store randomness results only.
- The LLM never decides mechanics, solutions, deaths, dice, or "quality."
- No raw numeric modifiers from the wire; server derives or verifies.
- Viewer-filtered projections; private data never crosses players.
- Content is data referencing IDs; effects compile to known engine ops.
- Package `__init__` files docstring-only or lazy; modules ≤ ~500 lines.
- Fail-forward: "nothing happens" is never a major-action result — and per
  §2.3/§3.5, this now applies explicitly to zero-intent and unsupported
  actions too, not just failed checks.
- BetterFingers is stateless; the game state is not (§3.2).
- Party threat scaling locks at Ready-click and never rebalances (§2.5).
- vLLM stays optional, feature-flagged, and non-blocking wherever it
  eventually lands (§2.7).
