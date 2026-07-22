# Brain package -- wave 6B (lane A, `wave6b/intents-package`)

Standalone BetterFingers/Brain contract package: `backend/lan_playground/brain/**`.
Same discipline as `combat/` (wave 2), `heroes/` (wave 3), and `shops/`
(wave 4): zero I/O, zero imports of `domain`/`systems`/`content`/`heroes`/
`combat`/`shops`/`stacks_*.py`, no third-party dependencies -- stdlib and
`brain.*` only. Nothing in this package is called from `stacks_engine.py`,
`domain/`, or `systems/` yet. Domain/reducer wiring (the next part) decides
*when* to build a packet, *which* handler/trigger set applies to a given
room/NPC/object, and *how* a resolved `ResponseArtifact`/`SocialCheckResult`
becomes real committed state and a real player-visible message.

Source: wavebasedgame.md §2.3 (intent decomposition, always a response),
§2.4 (social degrees), §3.2 (revised core loop), §3.5 (BetterFingers/Brain +
intents), §3.6 (social degrees detail); infinite_stacks.md §4.1 (pillars),
§12.1-12.3 (checks and degree table), §19.4 (privacy/accessibility), §20
(LLM generation boundary).

## 1. Module map

```text
brain/
  packets.py     Bounded per-call generation packets for the four roles
                 (Interpreter, NPC Performer, Narrator, event-to-book
                 prose): GenerationEnvelope (the §20.3 structured-
                 generation-contract fields) + one frozen dataclass per
                 role + a build_*_packet() factory per role. No packet
                 type has a history/memory/session-cache field, and no
                 build_*_packet() reads or writes anything outside its
                 own arguments -- verified by
                 test_packets_carry_no_history_field and
                 test_build_interpreter_packet_is_pure_and_uncached.
  intents.py     The Interpreter output contract: IntentCandidate
                 (confidence 1-100, target, method, offer/request,
                 leverage, keywords, requested_outcome, ambiguous flag),
                 InterpretationResult (0-3 candidates, hard-capped),
                 and parse_raw_intents() -- the defensive boundary
                 between a model's raw output and the rest of the
                 engine. Never raises; malformed output degrades to
                 ZERO_INTENT_RESULT.
  handlers.py    HandlerRegistry: versioned global handlers, object-/
                 NPC-scoped overrides (scoped always wins), a global
                 "*" wildcard fallback. Engine-side validation hooks
                 (validate_target_exists, validate_action_economy,
                 validate_compound_ordering) and
                 requires_confirmation(ambiguous, high_impact) as a
                 free function the caller applies before dispatch.
  response.py    ResponseArtifact (§2.3 always-a-response): ZERO_INTENT/
                 HARMLESS/UNSUPPORTED/RESOLVED/CLARIFICATION_NEEDED/
                 CONFIRMATION_NEEDED kinds. ContentGapRecord: a real,
                 JSON-serializable, persistable data structure logging
                 unsupported interaction demand (never a print/log
                 side effect) -- every UNSUPPORTED artifact carries one,
                 enforced in ResponseArtifact.__post_init__.
  triggers.py    ImmediateTrigger data shape (trigger_id, condition,
                 match_value, state_delta, priority) + evaluate_triggers()
                 (deterministic priority-then-id ordering) +
                 fold_trigger_state_deltas() (pure concatenation). The
                 package only decides which triggers fire and in what
                 order; applying a state_delta to real state is the
                 domain-wiring lane's job.
  degrees.py     Social-degree DC/modifier/outcome machinery (§3.6):
                 SocialOutcome + outcome_for_margin() (a literal,
                 drift-guarded duplicate of systems.checks.Outcome/
                 outcome_for_margin -- see §2 below), EvidenceTier/
                 MotiveAlignment enums + authored ModifierTier data,
                 compute_contextual_modifier() (clamped to -5..+5,
                 reads only the two enums + small int nudges),
                 SocialDCInputs + compute_social_dc(), RichOutcomeKind +
                 ELIGIBLE_RICH_OUTCOMES (per-margin-bucket eligibility
                 table), and resolve_social_check() tying it together
                 from an already-rolled d20 value (this package never
                 rolls dice itself).
  fallback.py    Deterministic, no-model authored fallback text for
                 every role: fallback_for_interpreter/_npc_performer/
                 _narrator/_event_to_book, dispatched by
                 resolve_fallback(role, packet). Pure functions of the
                 packet's own declared facts; never invents content
                 beyond what's already authorized on the packet.
```

Every module is comfortably under the repo's ~500-line pure-package
convention (largest is `packets.py` at ~330 lines). `__init__.py` is
docstring-only, per the repo's package-`__init__` rule.

## 2. Why `degrees.py` duplicates the engine's outcome table instead of importing it

`systems/checks.py` already implements the exact §12.3 degree table
(`Outcome` enum + `outcome_for_margin()`) as part of the live engine. `brain/`
cannot import `systems/` (pure-package rule -- `systems/` itself imports
`domain/`, which would pull the whole engine graph into a package that must
stay standalone this wave). Rather than reinvent a *different* table,
`brain.degrees.SocialOutcome`/`outcome_for_margin` are a **literal,
byte-for-byte duplicate** of the engine's values, the same resolution as
`heroes.creation.ATTRIBUTE_NAMES`/`SKILL_NAMES` literally duplicating
`combat.models.ATTRIBUTE_NAMES`/`SKILL_NAMES` in wave 3.

`tests/test_stacks_brain.py::test_social_outcome_matches_systems_checks_outcome_values_drift_guard`
is the drift guard: it's the one place in the brain test suite allowed to
import both `brain.degrees` and `systems.checks`, and it asserts identical
enum values and identical `outcome_for_margin()` output across a wide range
of margins. If either table changes independently, this test fails loudly
instead of the two silently diverging. Whoever wires `brain/` into the
domain next should either keep relying on this drift guard, or (cleaner
long-term) have the domain-wiring layer call `systems.checks.outcome_for_margin`
directly for the *authoritative* resolution and treat `brain.degrees`'s copy
as existing only so this package's own tests/docs can demonstrate the
mapping without an engine dependency.

## 3. The accessibility guarantee, as code and as a test

wavebasedgame.md §3.6 requires the `-5..+5` contextual modifier's inputs to
be in-world evidence/leverage/motive signals, **never** grammar, eloquence,
verbosity, disability, or "flattering the model" -- restating
infinite_stacks.md §19.4's ban on delivery-based scoring as a concrete,
numeric contract.

This is enforced at the type level, not just by docstring promise:

- `SocialModifierInputs` (the only accepted input to
  `compute_contextual_modifier()`) has exactly two enum-typed fields
  (`EvidenceTier`, `MotiveAlignment`) plus two small-int "author nudge"
  fields (`evidence_nudge`/`motive_nudge`, for content authors to fine-tune
  *within* an already-authored tier's own range). There is no `str` field
  anywhere on this dataclass a caller could route free text, a transcript,
  or a computed eloquence score into.
- `test_modifier_inputs_are_structurally_enums_not_free_text` locks this in
  by inspecting the dataclass fields directly.
- `compute_contextual_modifier()` sums the two tiers' clamped values and
  clamps the total again as a backstop, so the property
  `MIN_MODIFIER <= modifier <= MAX_MODIFIER` holds for every possible
  `(evidence, motive, nudge, nudge)` combination --
  `test_compute_contextual_modifier_never_exceeds_bounds_property` sweeps
  the full enum cross-product plus a wide nudge range to prove it.
- The worked examples from §3.6 are locked in as exact tests: "no leverage /
  plausible cover story" -> 0, "forged, verifiable evidence in hand" ->
  +3..+5, "threatens a stated fear, no offsetting motive" -> -3..-5.

## 4. What the domain-wiring wave will call, in what order

This section is the actual wiring surface -- what a future
`systems/brain_wire.py` (or similar) should call, and the guarantees it can
rely on without re-deriving them.

1. **Build a bounded packet** via the matching `packets.build_*_packet()`
   for whichever role is about to run. Pass only this call's own scene
   facts/allowed disclosures/resolved degree/state delta -- there is
   nothing to "carry forward" from a previous call; each call is a fresh
   packet by construction. `packet.envelope.cache_key` is safe to use as a
   generation-adapter cache key (per §20.4, "cache by structured input hash,
   not by mutable display state").
2. **Call the model adapter** (owned elsewhere -- not this package) with
   `packet.to_dict()`, honoring `packet.envelope.timeout_seconds`.
3. **On success**, for the Interpreter role specifically: pass the model's
   raw output through `intents.parse_raw_intents()` before touching it
   anywhere else. This is the only supported entry point for turning model
   output into `IntentCandidate`s; it never raises, so the caller does not
   need its own try/except around it.
4. **On failure/timeout/absence** (any role): call
   `fallback.resolve_fallback(role, packet)` for authored, deterministic
   text and continue immediately -- do not retry, do not block, do not wait
   longer than `timeout_seconds`. For the Interpreter role, pair this with
   `intents.ZERO_INTENT_RESULT` on the structured side.
5. **For each parsed `IntentCandidate`** (Interpreter role only, 0-3 of
   them): run `handlers.validate_target_exists` /
   `validate_action_economy` / `validate_compound_ordering` before
   dispatch, and check `handlers.requires_confirmation(ambiguous=...,
   high_impact=...)` -- if true, the engine must get an explicit player
   confirmation before running the resolved handler.
6. **Resolve the handler** via `HandlerRegistry.resolve(method, scope)` --
   pass the object/NPC id as `scope` so a scoped override is preferred over
   the global handler automatically; the caller never needs its own
   override-precedence logic.
7. **Evaluate immediate triggers** via `triggers.evaluate_triggers(candidate,
   triggers_in_scope)` *before* any check resolves, and fold their
   `state_delta`s with `triggers.fold_trigger_state_deltas()`. This must run
   before step 8's check, per §3.5's bacon/dragon example -- a trigger can
   change the DC inputs (e.g. NPC disposition) that step 8 then reads.
8. **For social/negotiation beats**, roll the d20 with the engine's own RNG
   (this package never rolls dice), then call
   `degrees.resolve_social_check(d20_roll=..., attribute_score=...,
   skill_rank=..., dc_inputs=..., modifier_inputs=...)`. `dc_inputs` and
   `modifier_inputs` are built from real NPC/scene state by the caller --
   this package only combines them. The returned `SocialCheckResult.outcome`
   is a `SocialOutcome` matching `systems.checks.Outcome`'s values exactly
   (§2 above); `eligible_rich_outcomes` bounds which `RichOutcomeKind`s the
   caller may pick from for that margin bucket, but the caller (with real
   NPC content data) still picks the specific one.
9. **Always produce a `ResponseArtifact`** via the matching `response.*`
   builder -- `zero_intent_response` (0 candidates),
   `unsupported_response` (understood but no handler; always attaches a
   `ContentGapRecord` the caller should persist, e.g. append to a content-
   gap log table), `harmless_response`, `resolved_response`, or
   `clarification_response`/`confirmation_response` when step 5 flagged
   confirmation. There is no legitimate path that skips producing an
   artifact -- `ResponseArtifact.__post_init__` enforces the
   kind-specific required fields (e.g. `UNSUPPORTED` without a
   `content_gap` raises immediately, at construction time).
10. **Build a Narrator (or NPC Performer) packet** from the resolved
    degree/state delta/allowed disclosures and repeat steps 1-4 for the
    narration/performance text.

## 5. Guarantees the next wave can rely on without re-verifying

- **No model-owned memory is structurally possible**: every packet
  dataclass is built from explicit constructor arguments only; there is no
  module-level cache, no class holding prior packets, and no field shaped
  like a history/session handle anywhere in `packets.py` (see
  `test_brain_package_has_no_engine_imports`'s sibling purity tests and
  `test_packets_carry_no_history_field`).
- **`parse_raw_intents()` never raises**, for any input shape -- `None`, a
  bare dict, a list of garbage, a tuple, deeply malformed nested values.
  Swept across 500 random-garbage samples plus a fixed table of adversarial
  shapes in `tests/test_stacks_brain.py`.
- **The modifier can never exceed +-5**, for any combination of evidence
  tier, motive tier, and author nudge -- swept exhaustively over the enum
  cross-product.
- **Every unsupported/zero-intent utterance yields a real
  `ResponseArtifact`** -- never `None`, never a bare exception, never a
  silent no-op. Unsupported demand always carries a persistable
  `ContentGapRecord` (JSON-round-trip-tested).
- **Immediate triggers evaluate in a fully deterministic order** (priority,
  then trigger_id) regardless of the input tuple's order, so the same
  intent + trigger set always produces the same fired-trigger sequence
  across replay.
- **A model timeout/absence can never block resolution**: every packet
  declares a non-empty `deterministic_fallback_key`, and every role has a
  pure, deterministic fallback function in `fallback.py` that needs no
  model call at all.
- **`brain/` imports nothing but stdlib and its own modules** -- enforced
  by `test_brain_package_has_no_engine_imports` and
  `test_brain_package_imports_only_stdlib_and_itself`, run over every file
  in the package directory (so a new module added later is automatically
  covered, no list to remember to update).

## 6. Open questions for the director / next wave

- **Where does `ContentGapRecord` get persisted?** This package only
  builds the record; there's no storage here (pure package, no I/O). The
  domain-wiring wave needs to decide the sink (event log? a dedicated
  content-gap table once wave 8's SQLite persistence lands? an in-memory
  list surfaced via a debug endpoint in the meantime?).
- **Should `degrees.SocialOutcome` be deleted in favor of calling
  `systems.checks.outcome_for_margin` directly once wiring exists?** §2
  above flags this explicitly -- keeping both means the drift-guard test
  must keep running forever; collapsing to one call site removes that
  maintenance cost but means `brain/` alone can no longer demonstrate its
  own degree-table mapping in isolation. Director's call.
  Recommend: keep the duplicate (matches the `heroes`/`combat` precedent
  and preserves `brain/`'s standalone-package invariant) but make sure the
  domain-wiring lane calls the *engine's* `outcome_for_margin`, not
  `brain.degrees`'s, for the authoritative resolution -- treat `brain.degrees`
  purely as this package's own self-contained demonstration/test surface.
- **Compound-intent ordering rules are stubbed to a count check only.**
  `validate_compound_ordering()` currently only enforces "at most 3 atomic
  intents, non-empty is fine" -- it does not (and structurally cannot,
  without game knowledge) know that e.g. "unlock then open" and "open then
  unlock" have different validity. The actual per-method-pair ordering
  rules need to live in the domain-wiring lane's own data, applied as a
  wrapper around this hook. Flagging so it isn't mistaken for a complete
  ordering-validation implementation.
- **`RichOutcomeKind` selection within a margin bucket is not automated.**
  `ELIGIBLE_RICH_OUTCOMES` only bounds *which* kinds are eligible for a
  given `SocialOutcome`; picking the specific kind for a given NPC/scene
  (e.g. "this NPC lies on a COST_PROGRESS margin, that one gives a
  behavioral tell instead") needs NPC-authored content data the
  domain-wiring wave supplies -- this package deliberately doesn't guess.
- **NPC disclosure validation (§3.4's "disposition changes over the
  encounter", "disclosure is validated server-side") is only partially
  covered here.** `NPCPerformerPacket.allowed_disclosures` is the channel
  for it, but the actual *validation* that a given fact is allowed for a
  given viewer at a given moment is domain/NPC-state logic this package
  doesn't own -- the caller must only ever put pre-filtered facts into the
  packet in the first place. Worth an explicit test in the domain-wiring
  wave (e.g. "one player's private clue never enters another player's
  compose context", per §19.4) once real NPC state exists to test against.
