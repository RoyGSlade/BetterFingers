# Room/object/NPC/Meaning-Lattice content schemas -- wave 6B lane B (board note #30)

Pure content + schemas, following the same discipline as `content/schemas.py`
+ `content/loader.py` + `content/validators.py`: content is data referencing
IDs, every effect compiles to a `content.schemas.KNOWN_OPS` entry (unknown
ops rejected at construction, never runtime), secret/gated fields declare
their `ViewerScope`/disclosure layer, `__init__.py` stays docstring-only/lazy,
modules stay near the repo's ~500-line convention. **No import of
`domain`/`systems`/`heroes`/`combat`/`shops`/`brain`** anywhere in this
slice -- verified by `tests/test_stacks_study_content.py::
test_rooms_npcs_lattice_modules_do_not_import_forbidden_packages` via AST,
not just code review.

Covers `wavebasedgame.md` §2.1/§2.2 (Meaning Lattice), §3.3 (room/object
templates), §3.4 (NPC templates), §3.8 (books) and the matching
`infinite_stacks.md` §7 (floor/room generation), §9.7 (Social Encounter),
§18.3 (structured truth before prose), §19.3 (NPC communication), §20.2-20.3
(LLM generation boundary), §29 (procedural-risk mitigations).

## 1. Module map

```text
content/
  lattice.py          Meaning Lattice component types (Truth, Memory,
                       Binding, Identity, Sequence), LatticeContribution
                       (what a resolved room repairs), LatticeRecipe (a
                       floor's required component thresholds + pure
                       is_satisfied()/missing() checks). NOT a room counter.
  rooms.py             Object instances (ObjectState/StateTransition/
                       ObjectInteraction/RoomObject), BookContent/
                       BookProvenance (§3.8/§18.3), and RoomTemplate (the
                       full §3.3 field set) + PayoffInteraction (§29).
  npcs.py              NPCTemplate (§3.4 full field set): Provenance,
                       KnowledgeAtom (with DisclosureLayer), Tell, Objective
                       (main/hidden), InventoryEntry, Relationship, Trigger,
                       EmotionalPhysicalState. Disclosure-leak check lives in
                       NPCTemplate.__post_init__ (construction-time).
  study_common.py      Shared prose/effects/viewer_scope YAML-loading
                       helpers + a require_keys re-export, used by both
                       loader modules below.
  room_loader.py       Strict YAML -> rooms.py/lattice.py dataclasses.
  npc_loader.py        Strict YAML -> npcs.py dataclasses.
  study_loader.py       Aggregate: load_study_pack() -> StudyContentPack
                       (rooms + npcs + lattice_recipes), re-exports
                       LoaderError and the individual load_* functions.
  study_validators.py   CI-style cross-file checks: unknown room->NPC
                       links, unreachable lattice recipes, disclosure-leak
                       re-check (defense-in-depth), optional inventory
                       item-id check against a caller-supplied known set.
  packs/core/
    study.yaml          The authored Gothic Living Study room.
    npcs.yaml           Elara Vance, bound to that room.
    lattice.yaml        One minimal, one-room-satisfiable floor recipe.
```

`content/__init__.py` lazily re-exports `load_study_pack`, `StudyContentPack`,
`validate_study_pack`, `validate_study_pack_strict` alongside the existing
core-pack exports, same pattern (`_EXPORTS` dict + `__getattr__`).

## 2. Why a separate `StudyContentPack`, not `schemas.ContentPack`

`schemas.ContentPack` is the core pack's dataclass (backgrounds, skills,
cards, items, conditions, enemies, puzzle templates) and is engine-lane
territory other packages already depend on (`heroes/`, `shops/`,
`systems/heroes_wire.py`, etc.). This wave's brief is explicitly
"pure content + schemas only... domain wiring is the next part," so rooms/
NPCs/lattice content is kept in its own additive `StudyContentPack` container
rather than growing `ContentPack`'s surface before a wiring wave decides how
domain state actually consumes it. **Open question for the director /
wiring wave:** should `RoomTemplate`/`NPCTemplate`/`LatticeRecipe` eventually
merge into `ContentPack`, or stay a parallel pack loaded alongside it? This
doc does not presume an answer.

## 3. Object instances (§3.3)

Every physical object (`RoomObject`) is a versioned instance (`version: int`,
enforced `>= 1`) with:

- **States** (`ObjectState`): each carries a `visibility` tier --
  `free` (always narratable), `noticed` (requires a prior discovery),
  `hidden` (never narrated until promoted). `RoomObject.__post_init__`
  requires `initial_state` to be one of the declared `states`.
- **Interactions** (`ObjectInteraction`): the 0/1/many supported intents.
  Each declares a `verb` from a closed vocabulary (`OBJECT_INTENT_VERBS`:
  look, inspect, move, open, close, search, take, use, read, light,
  extinguish, sit, hide, listen, smell, combine), the `legal_states` it may
  fire in, and **must** carry a real effect or a `state_transition_id` --
  construction rejects a flavor-only entry (§3.3's "real secondary
  interactions, not just flavor text" requirement enforced structurally, not
  by convention).
- **Transitions** (`StateTransition`): deterministic `from_state ->
  to_state` moves fired by a named `trigger`, with their own effects.
- **Multiple uses**: `ObjectInteraction.repeatable` defaults `True`; the
  payoff interaction (`rug_move`) is explicitly `repeatable: false` since
  moving the rug is a one-shot reveal.
- **Deterministic effects**: every `Effect` is `content.schemas.Effect`,
  unchanged -- construction rejects any op not in `schemas.KNOWN_OPS`.

Books (`BookContent`/`BookProvenance`, §3.8/§18.3) are an optional field on
`RoomObject`. Every fact carries `is_reliable` + `source` (provenance);
`BookContent.__post_init__` rejects an `is_reliable=False` fact whose
`source` string doesn't self-flag as `"fiction"` or `"unreliable"` --
misleading text must be *explicitly authored*, never an accidental
hallucination slipping through unflagged.

## 4. Room template (§3.3)

`RoomTemplate` carries the full field set the director's brief lists:
archetype/purpose/layout, objects, atmosphere/condition/cleanliness, visible
facts, subtle inconsistencies, secrets, clue graph, mechanisms (via object
state machines), interactables (via `ObjectInteraction`), NPC links
(`npc_ids`), subobjectives, hazards, encounter hooks, a `persistent` flag,
`lattice_contribution`, and `narration_facts` (the bounded fact set a
Narrator packet may draw from, per §3.5/§20.3's "authorized facts" field).

**Payoff-first placement (§29 mitigation, restated by §3.3):** every
`RoomTemplate` declares a `payoff_interaction` (`PayoffInteraction`) naming
the one distinctive object+interaction the room was built around.
Construction validates that pair actually exists in the room's own objects
-- the payoff can never dangle as objects change. The Gothic Living Study's
payoff is `study_rug` / `rug_move` (see §7 below for the full chain).

**Clue graph** (`ClueLink`): each edge names the clue it reveals, the
object+interaction that reveals it, and optional prerequisite clue ids.
Construction validates every reference resolves within the same room and
that prerequisite ids exist somewhere in the graph.

## 5. NPC template (§3.4)

`NPCTemplate` carries: `archetype_pool`, `age`, `sex_gender_presentation`,
`visual_traits`, `persona_voice`, `stats`, `boundaries`, `preferences`,
`fears`, `knowledge` (provenance-backed atoms), `lies`, `tells`, `inventory`,
`relationships`, `objectives` (exactly 3 `MAIN` + 1 `HIDDEN`, enforced),
`triggers`, and `state` (`EmotionalPhysicalState`: disposition + physical
state -- NPCs are "not uniformly neutral," per §3.4).

**Provenance-backed knowledge**: every `KnowledgeAtom` requires at least one
`Provenance` entry (`knower_id` + `method`) -- who could plausibly know this,
and how. This is checked at construction, not left to authoring discipline.

**Lies**: an atom's `is_true=False` makes it eligible; `NPCTemplate.
__post_init__` requires every `is_true=False` atom to be listed in `lies`
(never silently mixed into the "true belief" pool) and requires at least one
lie to exist at all (§3.4's "lies" field is not optional in practice).

**Disclosure layers and the leak check (the director's core ask):** every
atom declares `DisclosureLayer.FREE` or `GATED`. `NPCTemplate.__post_init__`
rejects:
  - a `FREE`-scoped `Tell` whose `hints_at_atom_id` points at a `GATED` atom
    (a gated fact must be unreachable from the free layer -- a tell that
    lets any player infer it for free is exactly that leak);
  - an atom id appearing in both the free and gated sets simultaneously.

`study_validators.check_npc_disclosure_no_leak` re-derives the same check
at the pack level (defense-in-depth, matching `validators.py`'s existing
style for effects/prose/card-anatomy). Tests exercise both layers directly
(`tests/test_stacks_study_content.py::
test_npc_template_rejects_disclosure_leak_from_free_tell_to_gated_atom`,
`::test_npc_disclosure_leak_check_passes_when_gated_atom_has_no_free_tell`).

**Hidden objective privacy**: `Objective(kind=HIDDEN, viewer_scope=PUBLIC)`
is rejected at construction -- a hidden objective's *value* must never be
publicly scoped, even though its *existence* (the objective record itself)
is visible in authored content for tests/authors to reason about.

## 6. Meaning Lattice (§2.1)

`LatticeComponent` is a growable enum, currently: `TRUTH`, `MEMORY`,
`BINDING`, `IDENTITY`, `SEQUENCE` (the wavebasedgame.md §2 locked-decision
"at minimum" list).

`LatticeContribution` is what a *resolved* room repairs -- a mapping of
component -> positive amount. `RoomTemplate.lattice_contribution` is a
required field; entering a room contributes nothing on its own (per the
locked decision: "the room must resolve"), and this module has no opinion on
what "resolve" means operationally -- that is systems/domain wiring, out of
scope here.

`LatticeRecipe` is a floor's required threshold set, **not** a room counter.
`is_satisfied(contributions)` sums a sequence of `LatticeContribution`s per
component and compares against the recipe's thresholds -- a pure function,
no room-count fallback anywhere in its logic. `missing(contributions)`
returns the remaining gap per component (for a future narration/UI hint).
`tests/test_stacks_study_content.py::test_lattice_recipe_is_not_a_room_counter`
asserts a recipe satisfied by one room's large contribution behaves
identically to the same total spread across many rooms.

The authored `recipe_test_floor_study_only` (`packs/core/lattice.yaml`)
requires `truth: 2, memory: 1` -- exactly what `gothic_living_study` alone
contributes, so it is satisfiable from this single room (the director's
"minimal but real, one-room-satisfiable" requirement).

## 7. The authored instance: Gothic Living Study

Room id `gothic_living_study` (archetype `study`, matching
`infinite_stacks.md` §7.2 d8=3 / §9.3). Generation order followed §29:
**the payoff was picked first**, then the room was built around it.

**Payoff chain:**
1. `study_rug` starts in state `rug_undisturbed`. Its `rug_look` interaction
   (any state) surfaces the subtle inconsistency: the rug's curled corner
   doesn't match its wear pattern (`fact_rug_curled_corner_noticed`).
2. `rug_move` (legal only in `rug_undisturbed`, `repeatable: false`) fires
   `state_transition_id: rug_reveal_compartment`, promoting `study_rug` to
   `rug_displaced` and promoting `hidden_compartment` from `visibility:
   hidden` to noticed (`fact_hidden_compartment_found`).
3. `hidden_compartment`'s `compartment_open_action` (legal in
   `compartment_closed`) reveals the contents: a bundle of letters and a
   locked diary (`fact_compartment_contents_revealed`), plus a `grant_check`
   effect (Insight+Read DC 10) for whoever opens it.
4. `study_diary`'s `diary_read_action` reveals its structured book facts,
   including one explicitly-flagged unreliable claim (Elara's final diary
   entry, contradicted by the true fact about her sister's death).

This is exactly the `payoff_interaction` declared on the room
(`study_rug` / `rug_move`), validated to exist at construction time.

**Furniture/set dressing with real secondary interactions:** fireplace
(search reveals a burned scrap; light/extinguish toggle state; using it
lit removes the room's dust hazard's Confused condition), desk (open then
search reveals correspondence), chairs (sit/inspect reveal usage patterns
hinting at a second, absent visitor), portrait (look names Elara Vance;
move reveals nothing behind it -- a red herring), bookshelf (search reveals
a hidden ledger; read exposes the Field Manual's book content; a thorough
search costs Energy and reveals a passage north).

**All six LIVE effect ops exercised in the authored room** (cross-checked
against `systems.effects.LIVE_OPS` in
`tests/test_stacks_study_content.py::
test_every_known_live_effect_op_is_exercised_in_the_authored_room`):
`emit_fact`, `grant_check` (compartment open), `spend_energy` +
`reveal_room` (thorough bookshelf search, revealing a north connector),
`apply_condition` (dust hazard) + `remove_condition` (warming at the lit
fireplace).

**Connected NPC**: `elara_vance`, archetype pool `spire_born` +
`living_book_character`, bound to the room via `npc_ids: [elara_vance]`.
Three main objectives (protect the letters, maintain the study, be
addressed as Keeper) + one hidden objective (avoid confronting her own
death, `viewer_scope: engine_only`). One lie
(`atom_elara_believes_sister_escaped`, a self-deception, not a conscious
con) with a matching tell (repetitive paper-straightening). Provenance-
backed knowledge throughout, including a `gated` atom
(`atom_elara_sister_died_in_spire`) with no free-layer tell pointing at it
-- the disclosure-leak check passes because nothing free-layer reaches it.

**Lattice wiring**: `gothic_living_study` contributes `truth: 2, memory: 1`,
which exactly satisfies `recipe_test_floor_study_only`.

## 8. Validators + loader integration

`room_loader.py`/`npc_loader.py` follow `loader.py`'s existing discipline
exactly: `require_keys` rejects unknown fields, `yaml.safe_load` only,
`LoaderError` (a `ContentError` subclass) on any structural problem,
duplicate ids rejected per file. Every dataclass construction (via
`rooms.py`/`npcs.py`/`lattice.py`'s own `__post_init__`) is where the
"unknown op," "dangling id," and "disclosure leak" rejections actually
happen -- the loader's job is only to get well-typed data to that
construction call, mirroring how `content/loader.py` relates to
`content/schemas.py`.

`study_validators.py` adds the cross-file checks a single dataclass can't
see: `check_room_npc_links` (a room's `npc_ids` must resolve),
`check_room_lattice_recipe_reachable` (a recipe must be satisfiable from at
least the pack's own rooms' summed contributions), and
`check_npc_disclosure_no_leak` (defense-in-depth re-check of the
constructor's disclosure-leak rule). `validate_study_pack_strict` raises
`ValidationError` with every `Finding` attached, same shape as
`validators.ValidationError`.

## 9. Tests

`tests/test_stacks_study_content.py` (43 tests): happy-path construction for
each schema family; rejection paths (unknown verb, flavor-only interaction,
unknown effect op, dangling initial/legal state, dangling payoff reference,
dangling clue-graph reference, empty objects, unflagged unreliable book
fact, wrong main/hidden objective counts, missing lies, lie not matching a
false atom, missing tells, hidden objective with public scope, the
disclosure-leak check from both directions); lattice recipe satisfaction
logic including the "not a room counter" assertion; the authored instance
loading end-to-end with every LIVE op exercised and the payoff chain
verified field-by-field; seeded-bad YAML fixture rejection at the loader
layer (unknown field, duplicate ids); and an AST-based check that none of
`rooms.py`/`npcs.py`/`lattice.py`/`study_loader.py`/`study_validators.py`
import `domain`/`systems`/`heroes`/`combat`/`shops`/`brain`.

## 10. Verification

`python3 -m pytest -q tests/test_stacks_*.py tests/test_architecture_report.py
tests/test_architecture_smoke.py tests/test_lan_game_*.py`:

**1740 passed, 1 skipped, 722 subtests passed** (baseline before this wave:
1697 passed + 722 subtests; this wave added 43 new tests in
`tests/test_stacks_study_content.py`, 0 regressions). Architecture gates
(no import cycles, isolated-subprocess import, PyInstaller analysis) all
still pass.

## 11. Open questions for the director

1. Should `RoomTemplate`/`NPCTemplate`/`LatticeRecipe` eventually merge into
   `schemas.ContentPack`, or stay a parallel `StudyContentPack` loaded
   alongside it once domain wiring starts? (See §2 above.)
2. `EncounterHook` currently just records `id`/`kind`/`trigger` as a pointer
   -- it does not model what a "social" or "conflict" encounter payload
   looks like when triggered from a room. That shape presumably belongs to
   whichever package eventually owns Social Encounters (§9.7) and to
   `combat/`'s existing conflict machinery; this wave deliberately left it
   as a thin pointer rather than guessing that contract.
3. `RoomObject.book` and lane A's `brain/` package (Narrator/NPC-performer
   packet contracts) will need to agree on exactly how `NarrationFact`/
   `BookProvenance`'s "authorized facts" surface to a generation request --
   this module defines the authoring-side shape (§20.3's contract fields)
   but does not implement packet assembly.
4. `ObjectVisibility`/disclosure-layer *enforcement* (who has "noticed" what,
   server-side) is explicitly systems/domain wiring, not modeled here. This
   wave only guarantees construction-time non-leakage of the authored data
   itself (a gated fact can't be reached via a free tell); runtime
   visibility tracking per viewer is the next part's job.
5. `stats: Mapping[str, int]` on `NPCTemplate` is intentionally loose (no
   fixed stat-id vocabulary like `schemas.ATTRIBUTE_IDS`/`SKILL_IDS`) since
   §3.4 doesn't specify one; the wiring wave should decide whether NPC stats
   reuse the hero attribute/skill ids or get their own vocabulary.
