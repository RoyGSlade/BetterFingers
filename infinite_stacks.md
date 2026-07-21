# The Lost Meaning: Infinite Stacks

> Comprehensive game design, systems specification, architecture plan, content plan,
> and implementation roadmap.
>
> **Status:** Canonical direction for the next game iteration. This document supersedes
> the campaign and encounter scope in `SPELLCHECK_SORCERY_REDESIGN.md`; the earlier
> document remains useful background for the communication mechanics and LAN security
> model.

## 1. Executive decision

Build a cooperative, GM-less, procedural dungeon-crawling roguelike in which players
enter damaged books inside ancient Spires, recover knowledge that the world lost, and
repair those books to cure the Spires and the regions around them.

The game combines three kinds of fun:

1. **Communication and interpretation:** players express plans, infer meaning, share
   incomplete clues, negotiate, and recover from misunderstandings.
2. **Tactical cooperation:** players explore a persistent tile map, split the party at
   real risk, fight through a readable d20 combat system, combine cards and equipment,
   and manage health, Energy, injuries, and limited supplies.
3. **Campaign discovery:** runs produce lasting world changes, repaired books, character
   stories, trophies, unlocks, and increasingly strange Spires.

BetterFingers is part of the game rather than a filter attached to it. It preserves each
hero's voice, helps turn rough speech into deliberate dialogue, exposes intent when the
player approves it, narrates established game facts, and writes persistent books from
events that genuinely happened. It never secretly decides whether prose is "good," invents
mechanical outcomes, or creates an unverified puzzle answer.

This design is inspired by familiar tabletop structures, including the user-supplied
*Infinite Ages Genesis* reference: quick character identity, d20 checks, initiative,
actions and reactions, called attacks, equipment, injuries, and collaborative storytelling.
All rules text, balance, content, names, implementation, and game-specific mechanics in
this plan are original and intentionally simplified.

---

## 2. Locked product decisions

These decisions are no longer open questions for the initial implementation:

- The initial target is **one to four human players**, with reconnect-safe companions
  available when a seat is empty.
- Every hero occupies a room on the map. Heroes **may split up**.
- Combat threat is calculated from the total living party, not only the heroes who enter
  the room. Splitting is therefore faster and sometimes strategically correct, but very
  dangerous.
- Each hero has **5 Exploration Energy** per world round.
- Entering an already discovered adjacent room costs 1 Energy.
- Breaching and entering an unexplored tile costs 3 Energy.
- Energy refreshes only after every living, conscious hero has completed or passed their
  world turn.
- Combat uses initiative, movement, one main action, one quick interaction, brief speech,
  and one reaction. It does not add a second five-point Energy economy.
- Zero HP means **Downed**, not automatically dead.
- As long as at least one hero remains alive, the run continues and Downed or Stable
  friends can be revived.
- Permanent death exists. A hero becomes permanently dead after failed death checks,
  certain clearly telegraphed fatal consequences, being lost or abandoned, or a total
  party failure.
- Traps can wound, sicken, Down, or permanently kill a hero, but unavoidable random
  instant death is forbidden.
- Statuses, sicknesses, and injuries exist, but each has one clear effect and a visible
  treatment path. Bookkeeping must stay light.
- The game is a roguelike with persistent metaprogression.
- There is no generic XP bar. Persistent progression comes from meaningful,
  performance-based **Accomplishments** and their Trophy rewards.
- Trophy upgrade prices escalate. Players cannot cheaply buy every permanent advantage.
- A run produces repaired knowledge, character history, discoveries, and world changes
  even when it ends in failure.
- The world contains multiple corrupted Spires. Restoring the damaged books inside a
  Spire cures the Spire and gradually heals its surrounding region.
- Mechanical content is deterministic, validated, and replayable from a seed. The LLM
  supplies bounded description, persona expression, dialogue, summaries, and book prose.

---

## 3. Player-facing promise

> Enter a dying library that has forgotten what its books mean. Explore a dungeon that
> rewrites itself, solve rooms that require real understanding, survive tactical fights,
> recover lost knowledge, and decide what deserves to be remembered. Your heroes can
> separate, become injured, rescue one another, grow through meaningful accomplishments,
> and die permanently. Every restored book helps cure the Spireâ€”and changes the world
> outside it.

The game should regularly create stories like these:

- A hero opens a suspicious chest alone, recognizes the mimic's punctuation-shaped
  teeth, and spends their last Energy escaping while the party races across the map.
- Two players hold different halves of a logic clue. They initially contradict each
  other, use BetterFingers to state exactly what each clue proves, and realize both are
  true from different time periods.
- The party's strongest fighter enters a combat room alone. The encounter is still sized
  for four heroes, so the other players must choose between abandoning their discoveries
  and traveling to the rescue or trusting the fighter to barricade the door.
- A hero dies to a trap they knowingly triggered to save the others. Their final words,
  recovered equipment, and accomplishments become a permanent memorial volume in the
  library.
- A repaired farming manual cures the blight surrounding one Spire. On later visits, the
  region has food, new shops, living NPCs, and a safer route into the next corrupted
  district.

---

## 4. Design pillars and anti-pillars

### 4.1 The pillars

#### Meaning produces state

A spoken or written message matters when a room explicitly asks players to communicate.
The player confirms its target, intent, facts, and commitment before it becomes a game
action. Other players or NPC rules may then interpret it. Language is never graded by a
hidden style score.

#### Every important failure creates play

A failed check should reveal danger, change a route, introduce an injury, spend a tool,
raise corruption, awaken an enemy, or force a hard choice. "Nothing happens" is not an
acceptable major-action result.

#### Information enables risk

Danger must have observable tells. Players can still gamble, split up, open the chest,
or trigger the forbidden mechanism, but they should be able to explain afterward what
they knew, what they missed, and why they took the risk.

#### The party creates combinations

Cards, statuses, room objects, positions, clues, and persona actions should interact.
The strongest move is often something another player enabled rather than a high solo
number.

#### The dungeon remembers

Rooms remain changed after the party leaves. Doors stay opened, traps remain disarmed,
merchants remember bargains, dead enemies stay dead unless a rule revives them, and
books preserve important events.

#### Content is data, rules are code, prose is generated presentation

Designers must be able to add enemies, items, rooms, puzzles, and achievements without
editing the core reducer. The LLM can restyle facts but cannot mutate them.

### 4.2 The anti-pillars

Do not build:

- five rooms that are narrative skins over one resolution formula;
- a game where rough text is mechanically identical to random keyboard input;
- unverified LLM riddles that may have no correct answer;
- long sequences where three players watch one player fill out a form;
- combat based only on larger HP and damage numbers;
- invisible instant-death probabilities with no counterplay;
- dozens of weak status modifiers that players cannot remember;
- permanent upgrades that eventually erase all danger;
- generated books that contradict the event log or established world facts;
- a single 2,000-line engine or client file containing every system.

---

## 5. World, Spires, and damaged books

### 5.1 The world

Long ago, the Spires preserved civilization's accumulated knowledge. They were not
ordinary libraries. Each book held a navigable memory-world: its facts, arguments,
instructions, mistakes, people, and emotional context formed physical places inside
the text.

Something severed words from meaning. The Spires continued preserving sentences while
forgetting why they mattered. Damaged books began producing contradictory rooms,
misremembered creatures, false histories, hostile metaphors, broken instructions, and
characters trapped inside unfinished events.

Corruption leaks from each Spire into its surrounding region:

- a damaged medical archive spreads incurable sickness;
- a broken agricultural collection produces blight and impossible weather;
- a corrupted civic archive makes contracts and roads contradict themselves;
- a ruined engineering Spire causes machines and structures to forget their purpose;
- an erased cultural archive removes names, songs, and relationships from living memory.

### 5.2 The player objective

Players are **Menders**: people able to enter a book without losing their own identity.
They explore book-realms, recover missing Knowledge Fragments, resolve contradictions,
defeat corruption, and reconstruct each volume's **True Meaning**.

Repairing enough ordinary volumes exposes a Spire's Keystone Volume. Repairing the
Keystone cures the Spire. Curing a Spire permanently changes the overworld, opens new
regions, unlocks content, and reveals more of the event that damaged the archive network.

### 5.3 Campaign hierarchy

```text
World
  -> Region
    -> Spire
      -> Chapter / Book
        -> Floor
          -> Room tile
            -> Encounter and persistent objects
```

- A **run** is one expedition into a Spire.
- A **floor** is a generated connected map with an objective and exit.
- A **chapter** is a sequence of one to three floors inside the same damaged book.
- A **book** is repaired when its chapters and final contradiction are resolved.
- A **Spire** is cured after enough supporting books and its Keystone Volume are repaired.
- The **campaign** continues across runs, hero deaths, repaired books, and cured Spires.

### 5.4 Corruption and restoration

Each Spire exposes three readable tracks:

- **Knowledge Restored:** permanent progress from repaired books and recovered fragments.
- **Corruption:** run-level pressure that changes room tables, enemies, and complications.
- **Stability:** how many unresolved contradictions the current run can tolerate before
  the floor mutates or collapses.

Corruption is not merely a difficulty number. At thresholds it changes content:

- low corruption adds misleading descriptions and minor anomalies;
- medium corruption adds contradictory doors, elite enemies, and unreliable NPCs;
- high corruption rewrites known rooms, infects equipment, and introduces false copies;
- maximum corruption starts a collapse sequence in which the party must repair, escape,
  or accept severe consequences.

---

## 6. Session and campaign loops

### 6.1 Between-run loop

1. Review the current region, cured Spires, active corruption, and available books.
2. Visit the library, memorial shelves, merchants, and Trophy Cabinet.
3. Spend Trophy Marks, select up to three equipped Trophy Perks, and choose an heirloom.
4. Create a new hero or prepare a surviving hero.
5. Choose a Spire, book, difficulty layer, and known objective.
6. Enter the run with a limited starting loadout.

### 6.2 Run loop

1. Generate the floor seed, entrance room, visible exits, and initial corruption state.
2. Explore rooms, split or regroup, recover fragments, fight, solve, trade, and rest.
3. Spend supplies and accept injuries while deciding how deeply to explore.
4. Meet the floor's repaired-room threshold and reveal an exit, objective, or boss route.
5. Leave early with reduced rewards, continue exploring for accomplishments, or confront
   the floor objective.
6. Complete the chapter, retreat, collapse, or lose the party.
7. Convert established outcomes into repaired books, trophies, memorials, world changes,
   and the next available decisions.

### 6.3 Room loop

1. **Approach:** show exits, obvious hazards, sounds, occupants, and corruption tells.
2. **Commit:** enter, observe from the doorway, spend a scouting ability, or retreat.
3. **Instantiate:** roll the visible d8 for a new tile and create its validated content.
4. **Discover:** inspect public objects and distribute any private clues.
5. **Act:** heroes spend actions, cards, items, speech, or checks.
6. **React:** affected heroes and eligible allies respond.
7. **Resolve:** deterministic rules emit events and update room state.
8. **Persist:** the room remains cleared, altered, hostile, looted, or unresolved.

---

## 7. Floor map and procedural room generation

### 7.1 Map topology

Use an orthogonal tile graph. Every room has:

- integer `x` and `y` coordinates;
- north, east, south, and west connector states;
- room type and content seed;
- discovered, entered, cleared, and exhausted flags;
- persistent objects and hazards;
- occupant and encounter IDs;
- corruption and stability modifiers;
- public description and viewer-filtered secrets;
- links to books, quests, shops, and prior events.

The generator may place loops, forks, locked shortcuts, stairs, one-way passages, and
secret connectors. It must never create overlapping rooms, unreachable required rooms,
an exit that cannot be reached, or an objective that depends on an already destroyed
unique item.

### 7.2 The visible d8 room roll

When a hero breaches an unexplored connector, the client displays a shared polyhedral
d8 roll. The raw result determines the room family:

| d8 | Room family | Primary decision |
|---:|---|---|
| 1 | Mystery Chamber | What is the verified solution, and what risk is worth taking? |
| 2 | Passage | Which route, shortcut, hazard, or positional advantage matters? |
| 3 | Study | What should the party learn, repair, copy, or disturb? |
| 4 | Wild Place | How should terrain, weather, creatures, and resources be used? |
| 5 | Conflict | Fight, evade, bargain, manipulate the environment, or retreat? |
| 6 | Shop | What is worth buying, selling, repairing, stealing, or negotiating? |
| 7 | Social Encounter | What does this character mean, want, fear, or misunderstand? |
| 8 | Anomaly | Is a rare, rule-changing opportunity worth its unusual danger? |

Bosses, mandatory objectives, entrances, and exits are placed by floor rules rather
than consuming random room results.

Repeated rolls remain valid but receive varied subtypes. A second Shop can become a
traveling merchant, abandoned counter, hostile auction, false storefront, or mimic
market. The engine does not secretly alter the displayed die; it selects a legal
subtype within the rolled family.

### 7.3 Floor size

Use resolved rooms, not merely revealed rooms, to unlock progress.

```text
required_rooms = min(6 + chapter_floor_index, 12)
maximum_rooms  = required_rooms + 3
```

`chapter_floor_index` is zero-based, so the first floor requires six resolved rooms.

- Secret rooms do not count against `maximum_rooms`, but have a per-floor cap.
- A floor exit becomes discoverable when the requirement is met.
- Players may continue until the maximum, corruption collapse, or voluntary departure.
- Floor objectives may substitute specific requirements, such as repairing three
  fragments, defeating a named threat, or recovering a missing index.

### 7.4 Splitting the party

Every hero has an independent room position. The party may split without a vote.

Splitting provides real benefits:

- reveal more of the map before Energy refresh;
- hold multiple switches or investigate distributed clues;
- reach a wounded ally or closing exit;
- distract an enemy while another hero recovers an objective;
- pursue mutually exclusive timed opportunities.

Splitting also creates explicit risk:

- encounter threat uses the total living party size;
- private information becomes harder to share;
- reactions usually require the same room or a specific ranged ability;
- injured heroes can be isolated from treatment;
- some doors close or mutate after entry;
- rescue costs time, Energy, supplies, and possible objective failure.

When combat starts, distant heroes are not frozen. During each global world round they
may spend their turn traveling toward the fight, continue exploring, or prepare a remote
effect. One combat round equals one world round for scheduling. A hero who reaches the
combat room joins at the start of the next initiative cycle.

Boss entrances show a clear full-party threat warning. They do not force regrouping;
entering alone remains a legal and usually terrible decision.

---

## 8. Exploration Energy and global rounds

### 8.1 Energy economy

Every conscious hero begins a world round with 5 Energy.

| Exploration action | Energy |
|---|---:|
| Move to a discovered adjacent room | 1 |
| Breach and enter an unexplored room | 3 |
| Observe through an open connector | 1 |
| Inspect, search, pick up, or operate a simple object | 1 |
| Attempt a major skill interaction | 2 |
| Treat a light condition with the correct supply | 1 |
| Trade or perform a normal shop action | 1 |
| Guard, prepare, or assist a nearby hero | 1 |
| Pass and preserve a prepared reaction | 0 |

The exact same interaction cannot be repeated indefinitely in one round unless its
definition permits it. Breaching a new room ends the hero's movement for that turn,
although remaining Energy may be spent inside the room if no encounter interrupts.

### 8.2 Round completion

A world round resolves after every living, conscious hero has submitted a turn, passed,
or timed out into a safe default. Then:

1. scheduled hazards and enemies act;
2. room clocks and sicknesses advance;
3. simultaneous conflicts resolve in deterministic initiative order;
4. every eligible hero refreshes to 5 Energy;
5. the next world round begins.

Turn planning may happen simultaneously. Players should not wait for the complete
animation of unrelated rooms before choosing their action.

### 8.3 Why combat does not spend Exploration Energy

Combat already contains movement, an action, interaction, speech, and reaction. Adding
five spendable points would produce two overlapping action economies and make balancing
equipment needlessly difficult. A hero's combat turn consumes that hero's world turn.
When combat ends, the normal Energy system resumes at the next world-round boundary.

---

## 9. Room family specifications

### 9.1 Mystery Chamber

Contains one verified puzzle, four meaningful interactables, up to three hint layers,
one or more fail-forward consequences, and at least one reward tied to understanding.
Mystery rooms cannot be cleared by a generic d20 roll alone.

### 9.2 Passage

A Passage must alter routing, tempo, information, or positioning. Valid subtypes include:

- forked corridor with incomplete signs;
- stairs between elevation layers;
- collapsing bridge or timed door;
- loop that changes when unobserved;
- shortcut requiring repair or sacrifice;
- narrow terrain that affects a future fight;
- quiet camp location with limited recovery;
- trapped hall with readable tells;
- gallery that previews a boss mechanic;
- moving shelves that reconnect existing rooms.

A blank hallway containing only a "continue" button is invalid content.

### 9.3 Study

Studies are knowledge-work rooms. Players might:

- reconstruct a damaged page;
- research an enemy family;
- identify an item or sickness;
- copy a temporary recipe;
- translate a clue using BetterFingers;
- bind a loose Knowledge Fragment into a book;
- learn a card for the current run;
- awaken the author, reader, or subject of a book;
- choose which of two contradictory histories to preserve.

### 9.4 Wild Place

These rooms represent outdoor locations inside a book: gardens, battlefields, frozen
seas, rooftops, deserts, villages, forests, farms, ruins, and pocket skies. They provide
terrain, foraging, weather, wildlife, long sight lines, alternate connectors, and
environmental combat options.

### 9.5 Conflict

Conflict includes more than elimination combat:

- defeat or rout enemies;
- survive for a number of rounds;
- protect a person or object;
- reach an exit while pursued;
- interrupt a ritual or rewrite;
- capture rather than kill;
- negotiate during a dangerous standoff;
- manipulate terrain to avoid a stronger enemy;
- rescue a swallowed, restrained, or copied hero.

### 9.6 Shop

Shops have limited seeded inventories, a merchant persona, repair services, buy and sell
rules, one rumor, and one relationship complication. Prices are authoritative game data.
Dialogue may change discounts only through declared actions and visible modifiers.

Shops can sell:

- weapons, armor, and card modifications;
- medicine, antidotes, splints, and revival supplies;
- puzzle tools and portable light;
- recipes and partial maps;
- books, rumors, keys, and suspicious containers;
- services such as repair, treatment, identification, and book binding.

### 9.7 Social Encounter

Social rooms use NPC needs, fears, beliefs, boundaries, knowledge, relationships, and
memory. Valid goals include obtaining information, correcting a misunderstanding,
forming an alliance, refusing a demand, identifying an impostor, negotiating passage,
or deciding whether a trapped character should be restored.

At least one route must involve listening or evidence rather than selecting a charisma
button.

### 9.8 Anomaly

Anomalies are rare and allowed to bend one ordinary rule. Examples include:

- a room whose exits lead to different periods of the same event;
- a book that offers a permanent boon in exchange for a true memory;
- a temporary duplicate of one hero with a slightly altered persona;
- a chest that contains the room currently containing the chest;
- a page where spoken commitments become physical objects;
- a safe room that heals injuries but increases Spire corruption;
- an archive index that reveals any room and alerts everything between it and the party.

Every anomaly declares exactly which rule changes and when the change ends.

---

## 10. Mystery and puzzle framework

### 10.1 Non-negotiable puzzle contract

The mechanical puzzle is created from a verified template. The template owns the
solution, acceptable alternatives, clue graph, validation function, hint sequence,
state transitions, and failure consequences. The LLM may name and describe those facts
but cannot alter them.

Each puzzle instance stores:

```yaml
id: string
template_id: string
seed: integer
difficulty: 1-5
objects: []
clues: []
private_clue_assignments: {}
solution: structured-value
accepted_solutions: []
hint_steps: []
attempt_limit: integer-or-null
failure_events: []
success_events: []
reward_table: string
validator_version: string
```

CI must generate and solve thousands of instances from every template. An instance that
has no solution, multiple unintended solutions where uniqueness is required, an
unreachable clue, or a mismatch between hint and answer fails validation.

### 10.2 Four-object structure

The default Mystery Chamber exposes four inspectable objects:

- **Anchor:** proves one dependable fact.
- **Key:** directly manipulates or identifies the solution.
- **Contradiction:** reveals that an apparent fact is conditional, false, or from a
  different context.
- **Red herring:** plausible and informative but not required.

The four roles are design functions, not labels shown to the player. Advanced templates
may use more objects if every object has a meaningful interaction.

### 10.3 Initial puzzle families

1. Ordering and sequence constraints.
2. Logic-grid deduction.
3. Symbol substitution and damaged alphabets.
4. Weighted objects and limited measurements.
5. Switch routing and state machines.
6. Spatial paths and rotating room pieces.
7. Contradictory witnesses with truth conditions.
8. Distributed clues where no player has the full solution.
9. Temporal clues describing the same room at different times.
10. Instruction repair: restore missing or ambiguous steps.
11. Intent reconstruction: determine what a damaged message was trying to accomplish.
12. Physical alternatives: solve the mechanism, sacrifice a tool, or deliberately
    trigger a known consequence.

### 10.4 Hints and failure

Puzzles are not permanent hard locks.

- Hint 1 focuses attention without removing choices.
- Hint 2 explains a relationship between clues.
- Hint 3 reveals the next valid operation, not necessarily the final answer.
- After the final hint, players may force progress by accepting a defined consequence.

Consequences include corruption, injury, lost Energy next round, broken equipment,
reduced loot, enemy alert, closed route, or a changed later room. They should never be
"the game generates a new arbitrary answer."

### 10.5 Speed accomplishments and accessibility

Puzzle speed can award accomplishments, but it cannot gate ordinary progression.

- The timer starts only after every participating player confirms the puzzle is visible.
- Pausing, connection loss, accessibility narration, and system-generated speech do not
  consume measured solve time.
- A speed trophy is one route among accuracy, no-hint, complete-exploration, rescue, and
  creative-solution trophies.
- No required mechanic assumes fast typing, fluent speech, perfect hearing, or color
  perception.

---

## 11. Character creation

Character creation should take two to four minutes for a first-time player and under a
minute for a returning player using a saved persona template.

### 11.1 Attributes

Roll four visible d4s simultaneously, then assign one die to each attribute. This keeps
the fun of rolling without forcing a player into a character they do not want.

| Attribute | Governs |
|---|---|
| **Force** | endurance, lifting, resisting, melee force, maximum HP |
| **Finesse** | initiative, movement, precision, ranged actions, dodging |
| **Insight** | puzzles, observation, medicine, mechanisms, emotional evidence |
| **Presence** | persuasion, leadership, deception, performance, communication magic |

A background adds +1 to one listed attribute, to a starting maximum of 5.

Derived statistics:

```text
Maximum HP = 8 + (Force * 2)
Defense    = 10 + Finesse + equipment
Initiative = d20 + Finesse + situational modifiers
Carry slots = 4 + Force
```

### 11.2 Five skills

Skills have ranks 0â€“3 and add directly to relevant checks. The chosen approach decides
which attribute pairs with a skill.

| Skill | Typical uses |
|---|---|
| **Bonk** | melee, breaking, pushing, restraining, intimidating through demonstrated force |
| **Scheme** | stealth, traps, deception, ambushes, sleight of hand, dirty tricks |
| **Tinker** | mechanisms, repairs, crafting, medicine tools, environmental manipulation |
| **Read** | clues, people, intent, danger, tracks, sickness, contradictions |
| **Wordcraft** | persuasion, rewriting, leadership, riddles, social magic, precise refusal |

Examples:

- pushing a statue may be `Force + Bonk`;
- throwing a lever through a gap may be `Finesse + Tinker`;
- noticing that an NPC is repeating memorized language may be `Insight + Read`;
- delivering a calm threat may be `Presence + Wordcraft`;
- creating a false trail may be `Insight + Scheme`.

### 11.3 Four starting backgrounds

#### Exiled Court Scribe

- +1 Presence.
- Rank 1 Wordcraft and Read.
- Starts with the **Questionable Seal** and a blank contract card.
- Once per floor, mark one exact phrase as binding or explicitly non-binding before it
  is spoken.

#### Back-Alley Fixer

- +1 Insight.
- Rank 1 Tinker and Scheme.
- Starts with **Improvised Tools** and one repair patch.
- Once per room, convert a visible harmless object into a one-use tool if the table can
  explain its function.

#### Retired Monster Hunter

- +1 Force.
- Rank 1 Bonk and Read.
- Starts with a **Battered Buckler** and family notes for one enemy type.
- The first time each fight an enemy reveals its intent, mark one weakness or false tell.

#### Traveling Charlatan

- +1 Finesse.
- Rank 1 Scheme and Wordcraft.
- Starts with a **Counterfeit Charm** and a concealed item slot.
- Once per floor, present an ordinary item as something more important; the deception
  works until evidence directly contradicts it.

### 11.4 Persona builder

The persona changes expression and roleplay, never base statistics. Ask for:

1. name and pronouns;
2. two personality traits;
3. one desire;
4. one fear;
5. "When stressed, I...";
6. preferred sentence energy: quiet, grounded, animated, or theatrical;
7. sentence style: blunt, conversational, precise, or poetic;
8. one short writing or speech sample;
9. phrases, implications, or commitments the rewrite must never add.

The player previews and edits a line before accepting the persona. Custom game personas
remain separate from private BetterFingers productivity personas.

---

## 12. Checks and transparent resolution

### 12.1 Standard check

```text
d20 + chosen attribute + skill rank + item/card modifiers
```

Suggested visible difficulties:

| Difficulty | Target |
|---|---:|
| Routine under pressure | 8 |
| Standard | 11 |
| Difficult | 14 |
| Severe | 17 |
| Extraordinary | 20+ |

Do not roll when the action is safe, obvious, and consequence-free. Do not permit a
roll when the described action cannot affect the stated target.

### 12.2 Advantage and disadvantage

- Advantage: roll two d20s and keep the higher.
- Disadvantage: roll two d20s and keep the lower.
- Multiple sources cancel one-for-one.
- After cancellation, at most one Advantage or Disadvantage applies. Avoid escalating
  stacks of special cases.

### 12.3 Degrees of outcome

| Margin | Result |
|---:|---|
| +5 or more | Strong success plus an opportunity |
| 0 to +4 | Clean success |
| -1 to -4 | Progress with cost, exposure, or reduced effect |
| -5 or less | Meaningful setback and changed state |

Natural 20 and natural 1 may add an opportunity or complication, but neither overrides
an impossible action, validated puzzle answer, or explicit immunity.

### 12.4 Opposed checks

Both sides roll when each is actively determining the outcome. Highest total wins.
Ties favor the current state: a locked door remains locked, a hidden hero remains
hidden, and a held object stays with its holder. This removes repeated tie rolls.

### 12.5 Resolution receipt

The UI must show:

- chosen action, target, attribute, and skill;
- die result;
- every bonus, penalty, Advantage, and Disadvantage source;
- target number or opposing roll;
- factual outcome events;
- generated narration only after those facts are committed.

---

## 13. Cards, decks, equipment, and inventory

### 13.1 Base actions remain available

Every hero can always Move, Attack, Defend, Assist, Interact, Use Item, Retreat, and
Speak. Cards create special choices; losing a card must not make a basic turn impossible.

### 13.2 Deck structure

Each hero begins a run with:

- four background cards;
- two selected general cards;
- one persona signature card;
- up to two equipment-granted cards.

Draw four cards. Played cards enter discard or Exhaust depending on the card. A safe
rest reshuffles discard; Exhausted cards require a stronger recovery rule. Reaction
cards can be played on another hero's turn if range and room rules allow it.

### 13.3 Card contract

Every card declares:

- timing;
- action or reaction cost;
- range and legal targets;
- required room state, tags, or equipment;
- exact base effect;
- check and outcome table if uncertain;
- combination tags;
- discard or Exhaust behavior;
- generated-description fallback text;
- accessible text equivalent.

### 13.4 Equipment philosophy

Items should change options before they increase numbers. Good items:

- add or modify a card;
- change targeting or range;
- create a new reaction;
- reveal a kind of information;
- make one risk safer while creating another;
- interact with a room family or enemy behavior;
- provide a limited treatment or escape route.

Flat bonuses are allowed but should be secondary.

### 13.5 Initial item examples

| Item | Effect |
|---|---|
| Argumentative Buckler | A successful Block lets the hero Challenge the attacker's stated intent. |
| Comma Blade | A called Break can separate an enemy from one aura or linked ally. |
| Boots of Premature Entrance | Breach a tile for 2 Energy; become Startled if it contains immediate danger. |
| Lantern of Subtext | Once per room, reveal one observable emotional or corruption tell. |
| Emergency Semicolon | Combine two weaker allied setup effects into one action. |
| Field Suture | Stabilize a Downed hero or treat Bleeding; consumed on use. |
| Bottled Footnote | Ask for the first puzzle hint without increasing corruption. |
| Index Hook | Pull an object, card, or willing ally between nearby positions. |
| Suspicious Sandwich | Heal modest HP; roll its known spoilage check if carried across three floors. |
| Red String Spool | Connect two clues so all players can inspect them as one evidence set. |

### 13.6 Inventory

- Every item consumes one or more carry slots.
- Shared floor storage exists only in secured rooms.
- A dead hero's carried items remain with the body unless a specific effect destroys or
  steals them.
- Encumbrance is slot-based, not weight arithmetic.
- Quest knowledge and repaired pages do not consume ordinary slots unless their room
  explicitly makes physical transport the challenge.

---

## 14. Combat system

### 14.1 Starting combat

When a Conflict begins:

1. reveal enemies, terrain, obvious hazards, exits, objective, and enemy opening intents;
2. identify heroes physically present;
3. calculate the encounter threat from the total living party;
4. present distant heroes with routes and estimated arrival rounds;
5. every combatant rolls initiative;
6. resolve from highest to lowest, with deterministic tie rules;
7. begin the next world round after every living hero and enemy group has acted.

Surprise requires a prior state or failed observation; it is not an unexplained coin
flip. A surprised combatant loses their reaction and has limited movement during the
opening cycle rather than losing an entire ordinary turn.

### 14.2 Player turn

A combat turn contains:

- movement within the room;
- one quick interaction with a simple object;
- one short in-character thought of free speech, with accessibility-equivalent text;
- one main action;
- one reaction available until the hero's next turn.

Talking longer, conducting a Meaning Check, or negotiating during active danger may use
the main action.

### 14.3 Attack

```text
Attack roll = d20 + relevant attribute + Bonk or another declared skill + weapon
Hit when attack roll >= target Defense
Damage = weapon die + explicit card/item bonuses
```

Use d4, d6, d8, and rare d10 weapon dice. Attributes normally affect accuracy and
options rather than adding large damage bonuses.

### 14.4 Called maneuvers

A hero may accept -4 accuracy to attempt one additional effect:

- **Disarm:** reduced damage and remove a held object.
- **Trip:** reduced damage and inflict Prone.
- **Drive Back:** move the target or change engagement position.
- **Break:** damage armor, a shield, a body part explicitly defined by the enemy, or an
  environmental object.
- **Crushing Blow:** add one weapon die but expose the attacker on failure.
- **Rattle:** replace physical damage with Frightened, Provoked, or Distracted when the
  target can understand or read the action.

Enemies and bosses define which effects they resist, convert, or expose as weaknesses.

### 14.5 Reactions

- **Dodge:** oppose the attack with Finesse; move to a legal nearby position on success.
- **Block:** reduce damage using a shield or defensive item; the item may take Wear.
- **Protect:** become the target of an attack against a nearby ally.
- **Counter:** attack after an enemy misses by 5 or more, if a card or item permits it.
- **Escape:** oppose a grapple, swallow, restraint, or environmental hold.
- **Prepared Trigger:** execute an action prepared during the hero's previous turn.

Each hero normally has one reaction per round.

### 14.6 Enemy intent

Enemies telegraph their next behavior through icons, animation, and plain text. Players
should make tactical decisions based on intent rather than memorize hidden scripts.

Examples:

- a goblin marks the shelf it plans to ignite;
- a mimic focuses on the hero carrying the most items;
- a punctuation spider prepares to split one active buff into two weaker effects;
- a redaction knight covers an ally and erases the last played card from public view;
- a corrupted librarian begins Silencing a room unless interrupted.

### 14.7 Alternative victory

At least half of standard combat encounters should support one non-elimination outcome:
escape, surrender, bargain, capture, environmental resolution, objective completion, or
removal of the corruption controlling the enemies.

---

## 15. Threat balance and split-party danger

### 15.1 Threat budget

Each enemy definition has a threat cost:

- minion: 1;
- standard: 2;
- specialist: 3;
- elite: 4â€“5;
- boss phase: separately authored.

Initial standard encounter budget:

```text
budget = (2 * total_living_heroes)
       + floor_danger
       + corruption_modifier
       + objective_modifier
```

The number of heroes physically present does not reduce this budget. If one hero from a
four-person party enters alone, the room still produces a four-person threat. Content
may spend budget on delayed reinforcements so a lone hero has a chance to barricade,
hide, flee, or survive until rescued.

### 15.2 Fairness rules

Split-party danger must be severe but legible:

- room approach text indicates likely danger where clues exist;
- scouting and Luck may expose additional tells;
- the entering player sees a risk confirmation for boss-tier or obviously lethal rooms;
- at least one retreat, barricade, hide, or delay route exists unless prior choices
  explicitly removed it;
- distant heroes see the event immediately without learning private room secrets;
- rewards do not automatically multiply because fewer heroes were present;
- special solo-survival accomplishments reward exceptional play without making
  intentional farming optimal.

### 15.3 Rescue play

When an ally is in danger, distant heroes can:

- spend Energy to traverse known rooms;
- use a map, portal, shortcut, or communication item;
- send a ranged card effect if its rules permit;
- open an alternate connector into the encounter;
- finish a local objective that weakens corruption globally;
- abandon the ally and accept the resulting relationship and memorial consequences.

---

## 16. Health, Downed state, revival, injury, sickness, and death

### 16.1 State model

```text
Healthy / Wounded
  -> Downed at 0 HP
  -> Stable after treatment or successful death checks
  -> Revived by aid, item, ability, or safe recovery

Downed
  -> Dead after three failed death checks or an explicit fatal event

Dead
  -> Permanent memorial; no ordinary resurrection
```

### 16.2 Death checks

At the beginning of a Downed hero's world turn:

```text
d20 + Force vs 10
```

- success adds one stabilization success;
- failure adds one death failure;
- three successes make the hero Stable;
- three failures cause permanent death;
- taking damage while Downed adds one failure;
- a clearly tagged severe trap or execution may add two failures;
- an ally using the correct aid can stabilize without waiting for three successes.

### 16.3 Revival

As long as one living hero remains, the run does not automatically end.

- A Stable hero can be revived to 1 HP with appropriate aid.
- A Downed hero can be stabilized or revived by medicine, a skill action, a card, or a
  safe room rule.
- Reviving without proper supplies may create an Injury.
- A permanently Dead hero cannot be restored by ordinary healing.
- The entire party Downed or Dead with no scheduled rescue ends the run.

### 16.4 Light status system

Every status has one primary effect, a visible duration, and a treatment rule. Initial
statuses:

| Status | Primary effect | Typical removal |
|---|---|---|
| Bleeding | Lose 1 HP after strenuous action | Bandage, medicine, safe rest |
| Burning | Take damage at round end | Water, roll, extinguish action |
| Frightened | Cannot willingly approach the source | Rally, distance, source removed |
| Confused | First targeted action shows two possible targets | Read/Wordcraft aid, room end |
| Silenced | Cannot use speech-tagged cards | Break source, writing tool, room end |
| Sickened | Disadvantage on Force recovery checks | Antidote, diagnosis and treatment |
| Exhausted | Begin next world round with 3 Energy | Full safe rest |
| Marked | Named enemy gains an effect against the hero | Hide, cleanse, defeat marker |
| Prone | Movement required before normal repositioning | Stand or allied assist |

A hero should rarely track more than two temporary statuses. Applying a third should
normally replace, escalate, or consolidate an existing condition.

### 16.5 Injuries

Injuries persist across rooms and may survive a run. Each creates one understandable
restriction rather than a modifier cloud.

Examples:

- **Sprained Leg:** discovered-room movement costs +1 Energy until treated.
- **Concussion:** the first Insight check in a room has Disadvantage.
- **Deep Cut:** healing above half HP requires proper medicine.
- **Cracked Ribs:** Crushing Blow and sprint actions cost 1 HP.
- **Inkburn:** persona magic may accidentally reveal one private emotion unless treated.

Treatment exists at shops, safe Studies, healers, through items, or between runs. Severe
care may cost money, a favor, a Trophy-related resource, or time while corruption grows.

### 16.6 Sickness

Sicknesses are authored condition arcs, not random stat debris. Each has:

- exposure source;
- visible or discoverable symptoms;
- one mechanical effect per stage;
- progression trigger;
- diagnosis options;
- at least two cures or management routes;
- possible knowledge unlocked when cured.

Examples include Ink Fever, Index Rot, Goblin Flu, and Redaction Cough.

### 16.7 Traps and permanent death

Traps may kill, but fatal outcomes require a chain of readable events:

1. environmental or object tell;
2. opportunity to inspect, prepare, or choose haste;
3. declared trigger or failed check;
4. damage, status, isolation, or death-check consequence;
5. rescue window when fiction permits.

A fake chest may be a mimic and may swallow a hero. It cannot silently delete a healthy
hero because an invisible percentage roll failed. Luck can improve warning quality,
initiative, escape routes, or loot-table composition; it does not replace agency.

### 16.8 Memorials and inheritance

Permanent death creates a **Legacy Volume** containing:

- hero persona and portrait data;
- recovered accomplishments;
- major choices and relationships;
- cause and location of death;
- approved last words when available;
- a short factual chronicle rendered in the hero's voice;
- one eligible heirloom or lesson for future heroes.

The death remains consequential while allowing the campaign to value the lost hero.

---

## 17. Roguelike progression without XP

### 17.1 Three progression layers

#### Run progression

Temporary power found during an expedition:

- cards and card modifications;
- equipment and consumables;
- temporary skill ranks;
- book blessings and curses;
- maps, recipes, relationships, and room-specific knowledge.

Most is lost, damaged, or converted when the run ends.

#### Hero progression

Surviving heroes retain:

- persona and history;
- treated or untreated injuries;
- selected mastered cards;
- one or more heirlooms within caps;
- relationships and book annotations;
- accomplishments personally earned.

Permanent death ends that hero's mechanical progression.

#### Player / archive progression

The player profile retains:

- Trophy Cabinet and spendable Trophy Marks;
- unlocked backgrounds, cards, items, and room variants;
- cured Spires and restored world state;
- repaired books and memorials;
- equipped metaprogression perks;
- discovered enemy and puzzle knowledge.

### 17.2 Accomplishments

Accomplishments replace generic XP. They reward how something was achieved, not how
many low-risk enemies were farmed.

Every accomplishment has:

- a permanent cabinet entry;
- a title, description, date, hero, Spire, and run seed;
- a transparent completion condition;
- a Trophy Mark reward;
- zero or one perk unlock;
- anti-farming and difficulty requirements;
- optional tiers such as bronze, silver, and gold.

Initial categories:

| Category | Examples |
|---|---|
| Puzzle | Solve quickly, solve without hints, discover alternate solution, recover after wrong answer |
| Exploration | Reveal every legal room, find all secrets, map a floor while split, escape a collapse |
| Combat | Win without anyone Downed, win through environment, defeat an elite while isolated |
| Rescue | Stabilize multiple allies, cross the map to save someone, carry a body to safety |
| Knowledge | Repair a complete collection, identify every enemy tell, cure a sickness from research |
| Communication | Correctly interpret intent, repair a misunderstanding, refuse without adding a commitment |
| Survival | Complete with one HP, survive being swallowed, return as sole living hero |
| Restraint | Clear a floor without killing, spare a boss, leave a cursed treasure untouched |
| Legacy | Honor a fallen hero, recover their heirloom, finish their unresolved book |

### 17.3 Trophy Marks and escalating costs

Accomplishments award **Trophy Marks**. The cabinet entry is permanent; spending Marks
does not erase the accomplishment.

Suggested rank cost curve:

```text
rank 1 = 1 Mark
rank 2 = 3 additional Marks
rank 3 = 6 additional Marks
rank 4 = 10 additional Marks
rank 5 = 15 additional Marks
```

The exact curve is balance data. Refunds should be available between runs for a modest
cost so experimentation does not require a new profile.

### 17.4 Upgrade families

#### Aptitude

- begin with one chosen skill closer to its first upgrade;
- gain limited control over attribute dice assignment or one reroll;
- unlock a fifth background option later;
- preserve one temporary skill lesson after a successful run.

Permanent attribute power must be capped. A profile may gain at most +1 starting
attribute before higher difficulty layers are unlocked.

#### Momentum

- reach the first in-run card choice sooner;
- reduce the Knowledge Fragment cost of the first upgrade;
- improve recovery after the first cleared room;
- increase the chance that optional challenges appear.

#### Fortune

- reveal an extra tell on suspicious containers;
- slightly improve rare-item table weighting;
- gain a reroll when identifying a mimic, not immunity to mimics;
- reduce the chance that a normal chest table is replaced by a deceptive subtype;
- increase recovery choices after a failed trap check.

#### Preparation

- start with a chosen basic healing item;
- add one carry slot;
- bring a low-tier puzzle tool;
- preview one floor modifier before selecting the run.

#### Mastery

- begin with one known behavior for Goblins, Mimics, Redactions, or another enemy family;
- unlock family-specific cards;
- gain a narrow first-round bonus against a mastered family;
- improve salvage or negotiation options after defeating that family.

"Stronger against Goblins" should mean informed, buildable specializationâ€”not a large
unconditional damage multiplier.

#### Legacy

- recover one additional item from a fallen hero;
- improve memorial-derived heirlooms;
- begin a rescue run with the last known location of a lost hero;
- convert a completed deceased-hero goal into a library blessing.

### 17.5 Equipped Trophy Perks

A player may equip at most three Trophy Perks for a run. The cabinet may contain many
unlocks, but limited slots prevent accumulated metaprogression from removing challenge
and encourage builds such as explorer, mimic hunter, goblin specialist, medic, or speed
solver.

### 17.6 Anti-farming rules

- Repeating an identical seed never awards first-completion Marks again.
- Trivial difficulty layers cannot award high-tier accomplishments.
- Performance trophies require the relevant room or enemy to be naturally eligible.
- Abandoning and restarting cannot reroll a known room without recording the attempt.
- Common accomplishment progress may continue, but its Mark rewards have tier caps.
- Creative achievements use explicit event combinations, not opaque LLM judgment.

---

## 18. Books, the library, and repairing knowledge

### 18.1 Book roles

| Book type | Mechanical role |
|---|---|
| Field Manual | Unlocks a recipe, card, treatment, or enemy behavior |
| Bestiary | Records creatures, intents, resistances, and negotiation routes |
| History | Restores factions, locations, causes, and world routes |
| Chronicle | Records events that actually happened during a run |
| Instructional Volume | Repairs a world system such as farming, medicine, or engineering |
| Cursed Book | Offers power while introducing a declared complication |
| Living Book | Contains a persistent character, settlement, or unresolved quest |
| Legacy Volume | Memorializes a permanently dead hero |
| Keystone Volume | Repairs the central meaning of a Spire and cures its region |

### 18.2 Book lifecycle

```text
Fragment discovered
  -> facts verified through rooms and clues
  -> missing relationships reconstructed
  -> player chooses interpretation when evidence permits alternatives
  -> structured book record becomes complete
  -> generated prose is rendered from the record
  -> book enters the persistent library
  -> restoration effect changes the Spire and world
```

### 18.3 Structured truth before prose

Every book stores an authoritative record:

```yaml
book_id: string
spire_id: string
category: string
status: fragment|damaged|repaired|corrupted
facts: []
disputed_claims: []
chosen_interpretations: []
source_event_ids: []
mechanical_unlocks: []
world_effects: []
authors_and_subjects: []
player_annotations: []
rendered_versions: []
```

The LLM receives only the approved facts, persona, desired length, and style constraints.
It may not introduce a new mechanical unlock, enemy weakness, historical fact, or world
effect.

### 18.4 Progressive reading

Do not generate a ten-page book when it drops.

1. Generate title, cover copy, classification, and a two-sentence summary.
2. Generate a short excerpt only when a player opens the book.
3. Generate a full chapter or chronicle only when requested or when the book becomes a
   major campaign artifact.
4. Cache all approved text by content hash and preserve previous editions.

This controls cost and makes opening a book feel intentional.

### 18.5 The physical library

The library is a navigable campaign hub with:

- repaired-book shelves by Spire and category;
- a Trophy Cabinet;
- a memorial wing;
- a map table showing cured and corrupted regions;
- research desks for combining books and clues;
- a bindery for repairing fragments;
- NPC readers and authors restored from Living Books;
- player-authored marginalia and voice-preserved notes.

New shelves, rooms, NPCs, services, and visual life appear as knowledge returns.

### 18.6 Curing a Spire

Each Spire declares a restoration recipe rather than a generic percentage bar. Example:

- repair two Instructional Volumes;
- resolve one disputed History;
- recover a missing author from a Living Book;
- identify the source of the Spire's contradiction;
- repair the Keystone Volume through a multi-stage finale.

The cure should produce visible world effects, new game systems, and narrative
consequences. A cured Spire remains explorable through optional deeper layers, but its
ordinary rooms and region are no longer presented as uncured.

---

## 19. BetterFingers communication mechanics

### 19.1 Compose flow

For communication actions:

```text
rough speech or text
  -> local transcription when spoken
  -> current public and player-owned context
  -> hero persona
  -> faithful, clearer, and characterful variants
  -> preservation receipt
  -> player edit and approval
  -> explicit game command
```

The preservation receipt shows:

- target;
- goal;
- stance;
- facts;
- negations;
- promises or commitments;
- requested action;
- unresolved ambiguity.

The player can use the raw line, select a variant, edit, or answer one clarification.

### 19.2 Meaning Checks

Selected social and mystery beats use another human's interpretation as the mechanic:

1. The speaker privately receives or chooses an intent.
2. They prepare and approve a message.
3. Other eligible players see the message but not the intent.
4. They select the meaning, emotional stance, or commitment they believe it expresses.
5. The game compares structured choices.
6. Agreement produces Clarity, trust, or tactical coordination.
7. Mismatch produces a specific misunderstanding and a chance to repair it.

The LLM does not grade the sentence. Human interpretation and confirmed structured
fields determine the result.

### 19.3 NPC communication

NPCs have authored goals, fears, facts, lies, boundaries, and state transitions. The LLM
may express the next authored dialogue act through a persona. A negotiation succeeds
because rules such as evidence, trust, leverage, and stated commitments were satisfied,
not because a model assigned a persuasion probability.

### 19.4 Privacy and accessibility

- Never provide one player's private clue to another player's compose context.
- Typed and spoken input are mechanically equivalent.
- Emotion-related delivery signals are opt-in presentation data, not diagnostic truth.
- Speech speed, pauses, accent, spelling, dyslexia, or motor input speed never modifies
  success chance.
- TTS is optional, captioned, interruptible, and never blocks state resolution.

---

## 20. LLM generation boundary and cost controls

### 20.1 The LLM may generate

- one-to-three sentence room descriptions from structured facts;
- funny but accurate object descriptions;
- NPC dialogue implementing an authored dialogue act;
- hero-persona rewrites and narration;
- book titles, summaries, excerpts, and chronicles from event IDs;
- recap text, memorial text, rumors, and shop flavor;
- fallback variations that preserve declared facts and tags.

### 20.2 The LLM may not generate or decide

- puzzle solutions or validator logic at runtime;
- item statistics, card effects, enemy actions, or achievement rewards;
- room connectivity or whether an exit is reachable;
- die results or hidden bonuses;
- whether a character permanently dies;
- a player's emotion as a fact;
- whether prose is sufficiently "good" to succeed;
- new history that is not present in the book record;
- secret information not authorized for the requesting viewer.

### 20.3 Structured generation contract

Every generation request declares:

- schema version;
- content purpose;
- authorized facts;
- prohibited additions;
- persona and tone;
- maximum length;
- safety and privacy constraints;
- deterministic fallback key;
- cache key and timeout.

Every response is schema-validated. On failure, use authored fallback prose and continue
the game immediately.

### 20.4 Cost and latency policy

- Generate short descriptions in batches when the floor seed is instantiated.
- Generate private text only for the intended viewer.
- Cache by structured input hash, not by mutable display state.
- Do not regenerate unchanged text after polling, reconnect, or animation replay.
- Generate book detail lazily.
- Use the least expensive model that reliably satisfies the schema.
- Keep gameplay independent of model availability.
- Record latency and fallback counts locally for testing without transmitting user data.

---

## 21. Multiplayer and interaction design

### 21.1 No gameplay host privilege

The host may configure and start a run, but does not manually advance every room or
resolve other players' turns. State advances from validated player commands, timers,
and engine rules.

### 21.2 Live transport

Use a room WebSocket as the primary transport:

- authoritative revisioned state;
- idempotent command IDs;
- expected-revision conflict handling;
- public events and viewer-filtered private projections;
- reconnect from latest snapshot plus missed-event summary;
- REST snapshot fallback;
- visible connection, ready, composing, reacting, and reconnecting states.

### 21.3 Split-screen information model

The shared display prioritizes:

- full discovered map;
- hero locations and immediate danger;
- public room descriptions and encounter state;
- initiative, enemy intent, world-round progress, and Spire tracks;
- recent factual events and narration.

Each player's device prioritizes:

- their hero, Energy, hand, equipment, health, and conditions;
- private clues and unfinished compose drafts;
- legal movement and action choices;
- reaction prompts and rescue routes;
- intent receipts and approval controls.

No player view receives another player's hand, private clue, unfinished message, token,
or hidden room data.

### 21.4 Waiting limits

- Simultaneous planning is allowed whenever actions do not conflict.
- Non-active players receive reactions, clue work, map planning, or inventory decisions.
- A normal decision timer uses a safe pass rather than an arbitrary action.
- A player should not lack a meaningful interaction for more than 30 seconds during
  ordinary play.
- Animations can be accelerated or skipped without changing results.

### 21.5 Reconnection and companions

- A disconnected hero remains in their current room.
- After a grace period, a deterministic companion may choose defensive actions.
- Reconnecting restores the original player capability without exposing secrets.
- Companion policy prioritizes survival, regrouping, and explicit party pings.
- AI companions do not solve final puzzle inputs or Meaning Checks for human players;
  they can provide authored hints or abstain.

---

## 22. Technical architecture

### 22.1 Authoritative event-driven core

Use commands and events:

```text
validate(command, state, viewer) -> accepted command or error
handle(command, state, rng)      -> ordered events
reduce(state, event)             -> new state
project(state, viewer)           -> authorized view
```

Replaying the initial seed and event log must reproduce authoritative state exactly.
Generated prose is presentation data referenced by content hash, not an input to replay.

### 22.2 Suggested backend modules

```text
backend/lan_playground/
  api/
    routes_rooms.py
    routes_game.py
    websocket.py
    schemas.py
  domain/
    state.py
    commands.py
    events.py
    reducer.py
    projections.py
    rng.py
  systems/
    turns.py
    map_generation.py
    room_generation.py
    exploration.py
    checks.py
    combat.py
    cards.py
    inventory.py
    conditions.py
    death.py
    puzzles.py
    shops.py
    books.py
    spires.py
    accomplishments.py
    trophies.py
  content/
    schemas.py
    loader.py
    validators.py
    packs/
      core/
        backgrounds.yaml
        cards.yaml
        items.yaml
        enemies.yaml
        conditions.yaml
        accomplishments.yaml
        puzzles/
        spires/
  services/
    compose.py
    narration.py
    book_writer.py
    speech.py
  persistence/
    database.py
    saves.py
    migrations.py
```

No module should become a second monolith. As a soft review trigger, any production file
above 500 lines requires an explicit reason or extraction issue before new features are
added to it.

### 22.3 Suggested client modules

```text
static/src/
  core/
    api.js
    socket.js
    store.js
    commands.js
    selectors.js
  screens/
    lobby.js
    character-builder.js
    map.js
    room.js
    puzzle.js
    combat.js
    shop.js
    compose.js
    library.js
    trophy-cabinet.js
    memorial.js
  components/
    die.js
    card.js
    item.js
    hero.js
    room-tile.js
    status.js
    check-receipt.js
    intent-receipt.js
    event-log.js
```

Rendering functions receive state and emit UI. Network calls, state mutation, timers,
and DOM construction must not be interleaved in one large function.

### 22.4 Core state aggregates

- `WorldState`: regions, Spires, cured effects, library, unlocks.
- `ProfileState`: Trophy Cabinet, Marks, perks, settings, saved persona templates.
- `RunState`: seed, heroes, map, world round, corruption, stability, objective.
- `HeroState`: position, HP, Energy, cards, items, conditions, death state.
- `RoomState`: topology, family, objects, occupants, persistent encounter state.
- `EncounterState`: combat, puzzle, social, shop, or anomaly state machine.
- `BookRecord`: verified facts, sources, interpretations, prose versions, unlocks.

### 22.5 Concurrency

Commands include `run_id`, `hero_id`, `encounter_id` when applicable,
`expected_revision`, and `idempotency_key`.

- Commands touching different heroes and rooms may be prepared concurrently.
- The authoritative reducer applies them in a deterministic order at the world-round
  boundary or immediately when the action is explicitly real-time safe.
- Per-encounter locks prevent double resolution.
- A stale command receives the current legal-action summary, not a generic server error.
- Every event records actor, causal command, world round, room, and visibility.

### 22.6 Persistence

Use SQLite for local campaign persistence with explicit schema migrations and atomic
transactions. Store:

- world and profile state;
- active and completed runs;
- event logs and replay metadata;
- repaired books and rendered versions;
- trophies, marks, perks, and memorials;
- content-pack and rules versions.

Secrets, room capability tokens, raw audio, and unfinished drafts are not campaign
history. Provide export, backup, import, and privacy-wipe paths.

---

## 23. Content schemas and authoring

### 23.1 Content rules

- IDs are stable and globally unique within their type.
- Mechanics reference IDs, never display names.
- Display prose has authored fallbacks.
- Secret fields declare their authorized viewer scope.
- Every effect compiles to known engine events.
- Content cannot execute arbitrary code.
- Versioned migrations handle renamed or removed content referenced by saves.

### 23.2 Validator requirements

CI fails for:

- unknown card, item, enemy, room, book, or achievement references;
- unreachable puzzle solutions or endings;
- invalid map connectors;
- effects without engine handlers;
- permanent rewards from repeatable unbounded accomplishments;
- missing treatment for a sickness or injury;
- an enemy without readable intent or counterplay;
- a trap capable of untelegraphed instant permanent death;
- private fields present in public projections;
- missing accessible descriptions;
- missing deterministic fallback narration.

### 23.3 Initial content target

| Content | First playable | Complete first Spire |
|---|---:|---:|
| Backgrounds | 4 | 4 |
| Skills | 5 | 5 |
| General/background/persona cards | 24 | 48 |
| Items and consumables | 20 | 50 |
| Enemy families | 3 | 5 |
| Individual enemies | 6 | 15 |
| Puzzle templates | 8 | 12 |
| Passage subtypes | 6 | 12 |
| Study subtypes | 4 | 10 |
| Wild Place subtypes | 4 | 10 |
| Shop archetypes | 1 | 4 |
| Social encounter frameworks | 3 | 8 |
| Anomalies | 3 | 10 |
| Statuses | 6 | 9 |
| Injuries | 3 | 8 |
| Sicknesses | 1 | 4 |
| Accomplishments | 20 | 60 |
| Bosses | 1 | 3 |
| Repairable books | 4 | 12 plus Keystone |

---

## 24. User interface and presentation

### 24.1 Map

- Fog of war hides undiscovered tiles without implying false map boundaries.
- Hero portraits show current rooms, health danger, and whether they are in combat.
- Connectors show open, locked, unstable, secret-discovered, and one-way states.
- Selecting a distant ally previews route length and arrival rounds.
- Split-party warnings communicate threat without blocking player choice.

### 24.2 Dice

- Use a lightweight rendered polyhedral with physics-like anticipation, not slow
  mandatory simulation.
- All players see shared room and major combat rolls.
- Private checks remain private until their event becomes public.
- Reduced-motion mode replaces rolling animation with an immediate readable result.
- The server supplies results; the client never determines authoritative randomness.

### 24.3 Combat

- Enemy intent appears before action selection.
- Legal targets and expected base effects are visible.
- Called-maneuver accuracy cost is shown before confirmation.
- Initiative and reaction availability remain visible.
- The factual check receipt precedes comic narration.

### 24.4 Puzzle interaction

- Objects are selectable and inspectable rather than buried in prose.
- Private clues have a deliberate Share control.
- Shared notes support text, simple ordering, linking, and marking contradictions.
- Inputs use accessible labels and cannot depend only on image coordinates or color.
- The hint route and cost are visible.

### 24.5 Library

- Books show repair state, known facts, disputed claims, unlocks, and source run.
- Generated prose can be regenerated only as a new edition; approved prior editions are
  preserved.
- Players can add voice-preserved marginalia without modifying authoritative facts.
- Memorials are solemn enough to make death matter while matching the wider comic tone.

---

## 25. Audio, speech, and accessibility

- Typed input is always available.
- Push-to-talk uses explicit start and stop, size and duration limits, and local-network
  transport.
- Raw recordings are not persisted by default.
- Transcripts require review before becoming a game command.
- TTS is optional, captioned, stoppable, and non-blocking.
- Do not treat volume, speed, hesitation, or pause timing as objective emotion.
- Delivery analysis, when enabled, may suggest presentation such as "sounds urgent" but
  the player confirms or removes it.
- Provide reduced motion, scalable text, keyboard navigation, controller navigation,
  contrast-safe status encoding, text equivalents for art, and no color-only puzzles.
- Timers pause or adjust for reconnect and accessibility narration.
- Persona preservation must not mock speech differences, disability, literacy, or accent.

---

## 26. Testing and balance strategy

### 26.1 Unit and property tests

- deterministic seed and event replay;
- map connectivity and exit reachability;
- floor room-count constraints;
- split-party movement and rescue arrival;
- Energy refresh after every eligible hero acts;
- combat initiative, reactions, conditions, Downed state, revival, and death;
- threat budgets based on total party size;
- puzzle generation and solver agreement across thousands of seeds;
- item/card reference integrity;
- trophy cost curves, caps, and anti-farming;
- book facts never expanded beyond authorized sources;
- viewer projections contain no forbidden private fields.

### 26.2 Integration tests

- two players generate different rooms in the same world round;
- one player enters combat while another travels to rescue them;
- disconnected hero becomes a companion and reconnects safely;
- simultaneous item pickup produces one owner and an understandable stale-action reply;
- Downed ally survives across rooms and is revived by the last living hero;
- fatal trap produces the correct memorial and item/body state;
- completed floor awards exactly the eligible accomplishments once;
- repaired book changes Spire and overworld state after save/reload;
- LLM timeout uses fallback without blocking a turn;
- WebSocket reconnect restores state and event summaries.

### 26.3 Simulation

Build headless agents with simple strategies:

- cautious regrouping party;
- aggressive split party;
- exploration-maximizing party;
- combat-only party;
- low-supply injured party;
- random legal-action party.

Run thousands of seeded floors to measure:

- completion, retreat, Downed, and permanent-death rates;
- average rooms and rounds;
- time-to-rescue by map distance;
- damage and item economy;
- room-family frequency;
- trophy acquisition rate and upgrade pace;
- unwinnable or stalled state count;
- dominant cards, items, and backgrounds.

Simulation cannot establish fun, but it can expose broken economics and impossible
states before human playtesting.

### 26.4 Human playtest questions

After every session, collect concise answers:

1. What was the best story from the run?
2. When did you feel responsible for another player's outcome?
3. Which decision felt obvious or fake?
4. When were you waiting without anything useful to do?
5. Did a room failure create an interesting new problem?
6. Did BetterFingers change what another player understood?
7. Was a death or injury fair based on visible information?
8. What would make you immediately play one more run?

### 26.5 Target experience metrics

These are investigation thresholds, not substitutes for judgment:

- a meaningful player choice at least every two minutes;
- ordinary inactive waiting below 30 seconds;
- first-time character creation under four minutes;
- ordinary combat under six rounds;
- no standard room requiring more than three screens of rules explanation;
- multiple viable builds across the four backgrounds;
- no unavoidable permanent death in verified seeds;
- at least one memorable cooperative or rescue moment in most full floors;
- players can explain why they succeeded or failed without referencing hidden AI quality.

---

## 27. Implementation roadmap

The phases below are dependency-ordered. Within a phase, lanes may proceed in parallel
after their shared schemas and acceptance fixtures are committed.

### Phase 0 â€” Ratify rules and contracts

**Goal:** prevent architecture and content teams from inventing incompatible rules.

Tasks:

- `DESIGN-001`: approve the locked decisions and numerical defaults in this document.
- `DESIGN-002`: write short ADRs for event sourcing, content/data separation, SQLite,
  LLM authority boundary, and split-party world rounds.
- `SCHEMA-001`: define versioned IDs, command, event, content-effect, visibility, and
  save-game envelopes.
- `FIXTURE-001`: create one hand-authored floor transcript covering movement, split,
  combat, rescue, puzzle, book repair, and a trophy award.

Exit gate:

- the fixture can be reviewed without implementation ambiguity;
- every state change has an owning command and event;
- unresolved rules are listed explicitly rather than buried in code.

### Phase 1 â€” Dismantle the monolith and establish the engine

**Goal:** create boundaries before adding systems.

Parallel lanes:

- **Engine:** state, commands, events, reducer, seeded RNG, replay.
- **Content:** schemas, loaders, validators, fallback content.
- **Transport:** revisioned commands, projections, WebSocket snapshot protocol.
- **Client:** store, selectors, screen router, command adapter, reusable components.
- **QA:** contract tests, replay fixtures, projection privacy tests.

Exit gate:

- a minimal lobby and one no-op room run through command/event/reducer flow;
- replay reproduces the state hash;
- client receives viewer-filtered WebSocket state;
- old monolithic behavior is behind an adapter or removed without parallel rule sources.

### Phase 2 â€” World rounds, map, and Energy

**Goal:** make procedural exploration enjoyable before adding combat.

Tasks:

- `MAP-001`: coordinate graph and connector rules.
- `MAP-002`: deterministic new-tile generation and visible d8 result.
- `TURN-001`: five-Energy hero turns and all-hero refresh boundary.
- `TURN-002`: simultaneous planning and deterministic conflict order.
- `SPLIT-001`: independent hero positions and route estimation.
- `ROOM-001`: persistent room lifecycle and family interface.
- `UI-MAP-001`: interactive map, hero positions, fog, connectors, route preview.

Exit gate:

- four simulated heroes can split, reveal rooms, regroup, and reach a valid exit;
- replay and reconnect preserve exact positions and room results;
- property tests find no overlaps or unreachable required exits.

### Phase 3 â€” Character builder, skills, cards, and inventory

**Goal:** give players distinct identities and decisions.

Tasks:

- `HERO-001`: four-d4 assignment UI and derived statistics.
- `HERO-002`: four backgrounds and five skills.
- `PERSONA-001`: game-persona schema, preview, edit, and privacy boundary.
- `CARD-001`: draw, discard, Exhaust, targeting, and effect compilation.
- `ITEM-001`: slot inventory, pickup conflicts, use, drop, trade, and recovery.
- `CONTENT-START-001`: first 24 cards and 20 items.

Exit gate:

- each background produces a mechanically different legal-action set;
- item and card effects are data-driven;
- two heroes can trade and combine effects without direct reducer branches per item.

### Phase 4 â€” Combat, rescue, and survival

**Goal:** deliver tactical fights whose state remains readable.

Tasks:

- `COMBAT-001`: initiative and combat/world-round synchronization.
- `COMBAT-002`: movement, attack, defense, assists, and six called maneuvers.
- `COMBAT-003`: reactions and enemy intent.
- `THREAT-001`: party-total threat budget and reinforcement spending.
- `RESCUE-001`: distant travel, joining combat, barricade, retreat, and carry actions.
- `LIFE-001`: HP, Downed, death checks, stabilization, revival, and permanent death.
- `STATUS-001`: initial statuses, injuries, and treatment.
- `ENEMY-001`: six enemies across three families.

Exit gate:

- a solo entrant faces four-player threat and can delay while allies travel;
- at least three combat encounters support non-elimination victory;
- no tested fight stalls after all legal targets or exits change;
- death, rescue, and item recovery persist through reconnect and save/load.

### Phase 5 â€” Puzzle and noncombat room framework

**Goal:** ensure exploration is not merely a path between fights.

Parallel lanes:

- **Puzzle engine:** validators, object state, hints, accepted solutions, failure events.
- **Room content:** Passage, Study, Wild Place, Shop, Social, and Anomaly interfaces.
- **Communication:** Meaning Check and explicit intent comparison.
- **Client:** shared puzzle workspace, private clues, shop, dialogue, inspectable objects.
- **QA:** generated-instance solver and accessibility tests.

Exit gate:

- eight puzzle templates pass large-seed solver validation;
- every room family has at least one complete subtype;
- a Meaning Check changes room state through human interpretation;
- no room requires generated prose to know its legal actions or solution.

### Phase 6 â€” Shops, equipment depth, treatment, and economy

**Goal:** make resources and injuries affect routing and build decisions.

Tasks:

- `SHOP-001`: seeded inventory, prices, services, relationship modifiers.
- `ECON-001`: rewards, selling, repair, scarcity, and anti-loop rules.
- `GEAR-001`: Wear, card modification, identification, and cursed items.
- `MED-001`: healing, treatment, sickness diagnosis, and consumables.
- `CONTENT-GEAR-001`: expand to 50 items, 8 injuries, and 4 sicknesses.

Exit gate:

- no infinite buy/sell, repair, or healing loop;
- at least three builds value different shop inventory;
- every condition has a discoverable treatment route.

### Phase 7 â€” Runs, accomplishments, trophies, and permadeath legacy

**Goal:** create the "one more run" loop without generic XP.

Tasks:

- `RUN-001`: entry, retreat, floor completion, collapse, and run summary.
- `ACCOMP-001`: event-based accomplishment evaluator and anti-farming.
- `TROPHY-001`: Marks, escalating costs, respec, perk unlocks, three-slot loadout.
- `LEGACY-001`: memorial, last words, item recovery, and heirlooms.
- `PROFILE-001`: local profile save, export/import, and migrations.
- `CONTENT-TROPHY-001`: initial 20 accomplishments, then expand after playtests.

Exit gate:

- no generic XP is awarded;
- every Trophy can cite the exact causal events;
- repeated seeds and trivial difficulty cannot duplicate restricted rewards;
- permanent death creates a complete memorial and preserves only allowed legacy value.

### Phase 8 â€” Books, library, Spires, and world restoration

**Goal:** make knowledge recovery the campaign's purpose.

Tasks:

- `BOOK-001`: structured facts, fragments, disputes, interpretations, and repair states.
- `LIBRARY-001`: shelves, research, bindery, memorial wing, and player notes.
- `SPIRE-001`: restoration recipes, Keystone state machine, corruption, and stability.
- `WORLD-001`: region changes, unlocks, and post-cure exploration.
- `BOOK-PROSE-001`: lazy generated title, summary, excerpt, chapter, and version cache.
- `CONTENT-SPIRE-001`: first Spire with 12 supporting books and one Keystone.

Exit gate:

- book facts trace to event IDs;
- generated prose cannot add mechanics or unsupported history;
- repairing a book and curing a Spire survive save/load and visibly change the hub;
- a failed run still contributes only the knowledge actually secured.

### Phase 9 â€” Full BetterFingers integration

**Goal:** make communication central without allowing AI to arbitrate fairness.

Tasks:

- `BF-COMPOSE-001`: faithful, clearer, and characterful variants.
- `BF-RECEIPT-001`: target, intent, facts, negations, commitments, and ambiguity UI.
- `BF-NPC-001`: authored dialogue-act rendering.
- `BF-SPEECH-001`: bounded local transcription and review.
- `BF-TTS-001`: optional local hero voice and captions.
- `BF-FALLBACK-001`: complete offline/authored behavior.

Exit gate:

- raw text remains playable;
- every transformation requires approval;
- model timeout does not delay state progression beyond the configured bound;
- private context and preservation tests pass.

### Phase 10 â€” First complete Spire and content expansion

**Goal:** turn systems into an authored, replayable campaign.

Build:

- one region transformed by its Spire;
- three chapters with distinct book themes;
- three bosses with authored phases;
- 12 puzzle templates and all room subtype targets;
- 15 enemies across five families;
- 50 items and 48 cards;
- 60 accomplishments;
- 12 supporting books and one Keystone;
- multiple Spire endings based on what knowledge the players preserve.

Exit gate:

- the same party can complete multiple materially different runs;
- room repetition does not reveal one universal solution pattern;
- the final Keystone reflects earlier recovered knowledge and choices;
- human playtesters voluntarily begin another run.

### Phase 11 â€” Hardening, balance, and release quality

**Goal:** make the game trustworthy enough for long campaigns.

Tasks:

- cross-platform Windows and Linux multiplayer testing;
- save migration and corruption recovery;
- disconnect, crash, resume, and duplicate-command testing;
- performance and low-end hardware profiling;
- accessibility audit;
- security and privacy audit;
- large-seed generation and combat simulation;
- repeated human playtests and balance passes;
- content authoring documentation and mod-pack validation.

Exit gate:

- zero known save-loss or privacy-critical defects;
- deterministic replays pass across supported platforms;
- no known unwinnable generated floor without an authored consequence route;
- published content meets the Definition of Fun and Definition of Done.

---

## 28. Parallel work rules

Parallel contributors should own separate directories or content packs and communicate
through committed schemas and fixtures.

Recommended lanes:

| Lane | Owns | Must not own |
|---|---|---|
| Engine | domain reducer, RNG, core systems | UI presentation or generated prose |
| Content | YAML/JSON packs and validators | ad hoc reducer branches |
| Client | screens, components, state selectors | authoritative game decisions |
| Transport | WebSocket, commands, projections | room mechanics |
| AI services | compose, narration, books, fallbacks | game-state mutation |
| QA | fixtures, properties, simulations, E2E | silent changes to product rules |

Before a phase starts:

1. commit schemas and one golden fixture;
2. assign file ownership;
3. define acceptance tests;
4. identify shared touchpoints;
5. integrate small vertical slices rather than merging several untested systems at once.

After each phase:

1. review code and content separately;
2. replay the golden fixture;
3. run privacy and determinism tests;
4. document rule changes;
5. conduct at least one human playtest when the phase changes player decisions.

---

## 29. Major risks and mitigations

| Risk | Mitigation |
|---|---|
| Procedural rooms feel like shuffled templates | Persistent consequences, subtypes, cross-room clues, authored objectives, and book context |
| LLM creates contradictions or latency | Structured facts, strict schemas, short bounded prompts, caching, and complete fallbacks |
| Split party creates waiting or impossible rescue | Simultaneous world turns, route estimates, delay options, remote preparation, and tested rescue windows |
| Permadeath feels arbitrary | Telegraphs, Downed window, death checks, rescue, fair trap contract, and memorial value |
| Metaprogression erases challenge | escalating costs, caps, three equipped perks, higher layers, and narrow specialization |
| Puzzles become stale | verified template families, variable clue graphs, cross-room context, alternate costs, and regular content packs |
| Combat dominates every build | noncombat objectives, five broadly useful skills, alternate victories, and knowledge rewards |
| Status bookkeeping becomes heavy | one effect per condition, visible treatment, low simultaneous cap, and concise UI |
| Generated books become unreadable filler | progressive generation, short summaries, fact provenance, player-requested expansion, and mechanical relevance |
| Monolith returns | module ownership, file-size review trigger, data-driven effects, ADRs, and phase review |
| Trophy farming replaces play | event-based criteria, seed/difficulty restrictions, tier caps, and creative non-grind accomplishments |
| BetterFingers remains cosmetic | explicit Meaning Checks, intent receipts, preserved commitments, NPC dialogue acts, and books from real events |

---

## 30. Definition of Fun

The game is becoming fun when playtests consistently demonstrate all of these:

- players discuss whether to split rather than always choosing one obvious formation;
- opening an unknown tile creates anticipation because the d8 changes the kind of
  decision, not just the artwork;
- at least one room per floor makes players combine information;
- combat produces rescue, positioning, timing, target, and resource decisions;
- a failed room creates a story players retell instead of a dead screen;
- equipment causes players to invent new plans;
- character personas are recognizable without forcing players to perform;
- a BetterFingers rewrite changes what another human understands;
- a repaired book is interesting to open because it records something true and useful;
- permanent death feels painful, fair, and memorable;
- accomplishments make players proud of *how* they played;
- players choose "one more room" or "one more run" for reasons beyond a generic XP bar.

---

## 31. Definition of Done for the first complete Spire

The first Spire is complete only when:

- one to four humans can create heroes, reconnect, save, and resume;
- heroes can split, explore concurrently, regroup, and rescue one another;
- all eight room families are mechanically distinct;
- procedural floors are valid, replayable, and bounded;
- combat is tactical, transparent, and supports alternative outcomes;
- puzzles are automatically verified and accessibility-safe;
- shops, items, cards, injuries, sickness, healing, death, and memorials work end to end;
- accomplishments and Trophy Marks replace XP and resist simple farming;
- book repair and Spire cure permanently change the world;
- BetterFingers expression is visible, approved, and relevant to selected mechanics;
- the game remains fully playable with deterministic fallback prose;
- Windows and Linux hosts can play with multiple LAN clients reliably;
- automated tests cover deterministic state, privacy, map validity, content references,
  split-party concurrency, survival states, saves, and reconnect;
- repeated human playtests confirm that the game creates decisions and stories rather
  than merely presenting additional screens.

---

## 32. Defaults to revisit through playtesting

These are implementation defaults, not promises that should survive contrary evidence:

- four-hero maximum party;
- five Exploration Energy;
- 3 Energy to breach a new room and 1 to enter a known room;
- six required rooms on the first floor and three optional rooms;
- d20 checks with direct 1â€“5 attributes and 0â€“3 skill ranks;
- HP equal to `8 + Force * 2`;
- three stabilization successes or death failures;
- -4 accuracy for called maneuvers;
- one reaction per combat round;
- four-card hand;
- three equipped Trophy Perks;
- the Trophy Mark cost curve `1, 3, 6, 10, 15`;
- one permanent starting-attribute increase before higher difficulty unlocks;
- a complete first Spire containing three chapters and three bosses.

Change these through data and documented balance decisions. Do not scatter replacement
constants through UI, content, and engine files.

---

## 33. Immediate next action

Do not begin by generating hundreds of room descriptions.

Build one golden playable floor containing:

- two heroes who can split;
- five-Energy world rounds;
- a visible d8 room roll;
- one verified four-object Mystery Chamber;
- one useful Passage;
- one Study with a damaged book fragment;
- one combat balanced for the total party;
- one rescue from the Downed state;
- one shop treatment;
- one Meaning Check;
- one accomplishment and Trophy Mark;
- one repaired book whose structured facts are turned into a short library entry.

That slice crosses every critical architectural boundary. Once it is deterministic,
reconnect-safe, understandable, and genuinely enjoyable with two humans, expand content
and floor length without rebuilding the foundations.