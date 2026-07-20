// Minimal state container + the one place server messages turn into state
// (infinite_stacks.md S22.3: "network calls, state mutation, timers, and DOM
// construction must not be interleaved in one large function"). This module
// only mutates plain data; it never calls fetch/WebSocket and never touches
// the DOM.

const LOG_LIMIT = 40;

export function createInitialState() {
  return {
    connection: "idle",
    you: { heroId: null, roomCode: null, accessCode: null, playerToken: null },
    revision: 0,
    worldRound: 1,
    requiredRooms: 0,
    maximumRooms: 0,
    heroes: {},
    rooms: {},
    privateClue: null,
    lastRoll: null,
    selectedAllyId: null,
    log: [],
    legalActions: null,
    lastError: null,
    reducedMotion: false,
    // Wave 2 (infinite_stacks.md S24.3/S24.4): server-populated wire objects
    // consumed via core/selectors.js's selectActiveScreen/selectEnteredRoomView.
    // Reducer wiring for the room-detail events lands with a later wave; wave
    // 2 exercised the room screen against committed JSON fixtures
    // (tests/fixtures/stacks_ui/) and it stays that way this wave -- see
    // selectors.js's comment on selectEnteredRoomView.
    enteredRoom: null,
    // Wave 3 (board task #10, docs/INFINITE_STACKS_CONTRACTS.md S5.2): the
    // REAL puzzle projection, keyed by room_id, folded in verbatim (snake_case,
    // matching the wire) from view.puzzles on every snapshot/reconnect and
    // patched incrementally by the puzzle_* events below. selectPuzzleView
    // (core/selectors.js) reads state.puzzles[<viewer's current room>].
    puzzles: {},
    // Client-local puzzle scratch state -- infinite_stacks.md S24.4 "private
    // clues have a deliberate Share control" / "shared notes support text,
    // simple ordering, linking, and marking contradictions". There is no
    // server command for any of this this wave (task #10 constraint: do not
    // invent a share command), so it lives entirely in this browser session
    // and does not sync to other players' clients yet.
    //   puzzleClues: room_id -> { clue_id -> {clueId, fallback, accessible} },
    //     every clue text this viewer has learned (private key fragments from
    //     private_clue_assigned + any object's revealed_clues from
    //     object_inspected), regardless of whether it's been shared yet.
    //   sharedClueIds: room_id -> clue_id[], which of the above the viewer
    //     has pressed "Share with party" on.
    //   puzzleManualNotes: room_id -> Note[] (party-visible shared notes:
    //     manual free-text adds, plus a copy made at the moment a clue is
    //     shared -- see core/commands.js-adjacent actions below).
    //   puzzleInspectedObjects: room_id -> object_id[], which objects this
    //     viewer has already clicked Inspect on (purely a "you already did
    //     this" UI indicator; the wire never tracks per-object inspection).
    puzzleClues: {},
    sharedClueIds: {},
    puzzleManualNotes: {},
    puzzleInspectedObjects: {},
    // Wave-3 combat projection (board task #9, stacks-conflict, EARLY DRAFT
    // posted 17:15 -- code hasn't landed in stacks_engine.py/stacks_projections.py
    // yet, so no live event populates this today). conflicts is room-keyed,
    // parallel to puzzles: view.conflict (top-level wire key, singular) ->
    // {room_id: {encounter_id, status, combat_round, heroes, enemies,
    // initiative_order, current_turn, last_intent_telegraph, threat_budget}}.
    // conflictIntents/conflictLastCheckReceipt are client-local scratch
    // folded from the raw combat/events.py event dicts embedded in
    // conflict_turn_resolved's payload.combat_events (see applyConflictEvent
    // below) -- the top-level conflict projection itself has no legal_actions
    // or check-receipt field, unlike the wave-2 UI fixture's guess.
    conflicts: {},
    conflictIntents: {},
    conflictLastCheckReceipt: {},
  };
}

export function createStore(initialState) {
  let state = initialState;
  const listeners = new Set();

  function getState() {
    return state;
  }

  function setState(patch) {
    state = typeof patch === "function" ? patch(state) : { ...state, ...patch };
    for (const listener of listeners) listener(state);
  }

  function subscribe(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  return { getState, setState, subscribe };
}

function appendLog(state, entry) {
  const log = [...state.log, entry];
  return log.length > LOG_LIMIT ? log.slice(log.length - LOG_LIMIT) : log;
}

// Upserts `clues` (each {clue_id, fallback, accessible}, the shape shared by
// both private_clue_assigned's payload.clues and object_inspected's
// payload.revealed_clues) into puzzleClues[roomId], keyed by clue_id so a
// re-delivered/duplicate clue (e.g. re-inspecting an already-claimed key
// object) never overwrites or duplicates an entry.
function mergeCluesIntoRoom(puzzleClues, roomId, clues) {
  if (!roomId || !clues || !clues.length) return puzzleClues;
  const forRoom = { ...(puzzleClues[roomId] || {}) };
  for (const clue of clues) {
    if (!clue || !clue.clue_id || forRoom[clue.clue_id]) continue;
    forRoom[clue.clue_id] = { clueId: clue.clue_id, fallback: clue.fallback, accessible: clue.accessible };
  }
  return { ...puzzleClues, [roomId]: forRoom };
}

// Snapshots/reconnects carry the authoritative view.puzzles dict; re-derive
// puzzleClues from every room's your_private_clues so a fresh client (or one
// that missed the private_clue_assigned event) still sees its own clues.
function mergeCluesFromPuzzles(puzzleClues, puzzlesByRoom) {
  let next = puzzleClues;
  for (const [roomId, puzzle] of Object.entries(puzzlesByRoom || {})) {
    next = mergeCluesIntoRoom(next, roomId, puzzle.your_private_clues);
  }
  return next;
}

function upsertPuzzle(puzzles, roomId, patch) {
  if (!roomId) return puzzles;
  return { ...puzzles, [roomId]: { ...(puzzles[roomId] || {}), ...patch } };
}

function appendUniqueToRoomList(byRoom, roomId, value) {
  if (!roomId) return byRoom;
  const existing = byRoom[roomId] || [];
  if (existing.includes(value)) return byRoom;
  return { ...byRoom, [roomId]: [...existing, value] };
}

function appendHintIfNew(hintsRevealed, hint) {
  if ((hintsRevealed || []).some((h) => h.fallback === hint.fallback)) return hintsRevealed || [];
  return [...(hintsRevealed || []), hint];
}

function applyView(state, view, revision) {
  const puzzles = view.puzzles || {};
  return {
    ...state,
    revision: typeof revision === "number" ? revision : view.revision,
    worldRound: view.world_round,
    requiredRooms: view.required_rooms,
    maximumRooms: view.maximum_rooms,
    heroes: view.heroes,
    rooms: view.rooms,
    privateClue: view.viewer && view.heroes[view.viewer] ? view.heroes[view.viewer].private_clue ?? null : state.privateClue,
    puzzles,
    puzzleClues: mergeCluesFromPuzzles(state.puzzleClues, puzzles),
    // "conflict" (singular) is the posted top-level wire key name for the
    // room-keyed encounter dict -- not yet emitted by any real snapshot this
    // wave, so this is a no-op (view.conflict undefined) until stacks-conflict's
    // code lands; conflictIntents/conflictLastCheckReceipt are event-derived
    // scratch and intentionally survive a snapshot refresh.
    conflicts: view.conflict || state.conflicts,
  };
}

// Wave-3 puzzle event handling folds docs/INFINITE_STACKS_CONTRACTS.md S5.1's
// wire event vocabulary (puzzle_instantiated/object_inspected/
// puzzle_hint_revealed/puzzle_solved/puzzle_solution_rejected/
// puzzle_force_progress/private_clue_assigned, all emitted by
// stacks_engine.py's event translation) into state.puzzles incrementally,
// the same pattern wave-1 already used for die_rolled. "object_inspected" is
// reused by the wave-1 plain-room inspect action too (payload {hero_id,
// room_id}, no object_id) -- payload.object_id is what disambiguates the
// puzzle-object variant.
function applyPuzzleEvent(state, event) {
  let next = state;
  const roomId = event.room_id;

  if (event.type === "puzzle_instantiated") {
    const payload = event.payload;
    const existing = next.puzzles[payload.room_id];
    next = {
      ...next,
      puzzles: upsertPuzzle(next.puzzles, payload.room_id, {
        instance_id: payload.instance_id,
        template_id: payload.template_id,
        difficulty: payload.difficulty,
        objects: payload.objects,
        solved: false,
        forced: false,
        attempts_used: 0,
        attempt_limit: existing ? existing.attempt_limit ?? null : null,
        hints_revealed: existing ? existing.hints_revealed || [] : [],
        your_private_clues: existing ? existing.your_private_clues || [] : [],
      }),
    };
  } else if (event.type === "private_clue_assigned") {
    const clues = event.payload.clues || [];
    if (state.you.heroId === event.actor_hero_id) {
      next = { ...next, privateClue: clues.map((c) => c.fallback).join(" ") };
    }
    if (roomId && clues.length) {
      const existing = next.puzzles[roomId] || {};
      const knownIds = new Set((existing.your_private_clues || []).map((c) => c.clue_id));
      const merged = [...(existing.your_private_clues || []), ...clues.filter((c) => !knownIds.has(c.clue_id))];
      next = {
        ...next,
        puzzles: upsertPuzzle(next.puzzles, roomId, { your_private_clues: merged }),
        puzzleClues: mergeCluesIntoRoom(next.puzzleClues, roomId, clues),
      };
    }
  } else if (event.type === "object_inspected" && event.payload.object_id) {
    next = {
      ...next,
      puzzleInspectedObjects: appendUniqueToRoomList(next.puzzleInspectedObjects, roomId, event.payload.object_id),
      puzzleClues: mergeCluesIntoRoom(next.puzzleClues, roomId, event.payload.revealed_clues),
    };
  } else if (event.type === "puzzle_hint_revealed") {
    const existing = next.puzzles[roomId] || {};
    next = {
      ...next,
      puzzles: upsertPuzzle(next.puzzles, roomId, {
        hints_revealed: appendHintIfNew(existing.hints_revealed, {
          fallback: event.payload.fallback,
          accessible: event.payload.accessible,
        }),
      }),
    };
  } else if (event.type === "puzzle_solved") {
    next = { ...next, puzzles: upsertPuzzle(next.puzzles, roomId, { solved: true, attempts_used: event.payload.attempts_used }) };
  } else if (event.type === "puzzle_solution_rejected") {
    next = {
      ...next,
      puzzles: upsertPuzzle(next.puzzles, roomId, {
        attempts_used: event.payload.attempts_used,
        attempt_limit: event.payload.attempt_limit,
        forced: event.payload.forced,
      }),
    };
  } else if (event.type === "puzzle_force_progress") {
    next = { ...next, puzzles: upsertPuzzle(next.puzzles, roomId, { forced: true }) };
  }
  return next;
}

// Folds the raw combat/events.py event dicts stacks-conflict's
// conflict_turn_resolved wire event embeds unchanged (payload.combat_events,
// per their 17:15 wave-3 post) into client-local per-room scratch: the
// currently-telegraphed intent per enemy (combat/intents.py's
// telegraph_intent payload: intent_id/telegraph_text/accessible_text/
// counterplay -- already-shipped, accepted wave-2 code) and the last
// resolved attack's S12.5 check receipt (combat/actions.py's attack_resolved
// payload: action/die_rolls/chosen_die/attribute/skill/total/defense/
// margin/hit/natural_20/natural_1 -- also already-shipped). ASSUMPTION
// pending stacks-conflict's confirmation: the wire event `type` string for
// this envelope is "conflict_turn_resolved", matching the domain event name
// they posted verbatim -- this codebase sometimes renames domain event names
// on their way to the wire (e.g. PRIVATE_CLUE_REVEALED -> "private_clue_assigned"),
// so this is the one part of this function that may need a one-line rename
// once their code lands (isolated here, nowhere else).
function outcomeFromAttackResolved(payload) {
  if (payload.natural_1) return "Critical miss";
  if (!payload.hit) return "Miss";
  if (payload.natural_20) return "Critical hit";
  return payload.margin >= 5 ? "Strong hit" : "Hit";
}

function applyConflictEvent(state, event) {
  if (event.type !== "conflict_turn_resolved") return state;
  const roomId = event.room_id;
  const combatEvents = event.payload.combat_events || [];
  let intents = state.conflictIntents[roomId] || {};
  let lastCheckReceipt = state.conflictLastCheckReceipt[roomId] || null;

  for (const combatEvent of combatEvents) {
    if (combatEvent.type === "intent_telegraphed" && combatEvent.actor_id) {
      intents = {
        ...intents,
        [combatEvent.actor_id]: {
          intentId: combatEvent.payload.intent_id,
          telegraphText: combatEvent.payload.telegraph_text,
          accessibleText: combatEvent.payload.accessible_text,
          counterplay: combatEvent.payload.counterplay,
        },
      };
    } else if (combatEvent.type === "attack_resolved") {
      const payload = combatEvent.payload;
      lastCheckReceipt = {
        action: payload.action,
        target: combatEvent.target_id,
        attribute: payload.attribute,
        skill: payload.skill,
        dieResult: payload.chosen_die,
        modifiers: [
          { source: payload.attribute, value: payload.total - payload.chosen_die },
        ],
        targetNumber: payload.defense,
        outcome: outcomeFromAttackResolved(payload),
      };
    }
  }

  if (intents === (state.conflictIntents[roomId] || {}) && lastCheckReceipt === (state.conflictLastCheckReceipt[roomId] || null)) {
    return state;
  }
  return {
    ...state,
    conflictIntents: { ...state.conflictIntents, [roomId]: intents },
    conflictLastCheckReceipt: { ...state.conflictLastCheckReceipt, [roomId]: lastCheckReceipt },
  };
}

function applyEvent(state, event) {
  let next = state;
  if (event.type === "die_rolled") {
    next = {
      ...next,
      lastRoll: {
        value: event.payload.value,
        family: event.payload.family,
        targetRoomId: event.payload.target_room_id,
        rollerHeroId: event.payload.roller_hero_id,
        worldRound: event.world_round,
      },
    };
  }
  next = applyPuzzleEvent(next, event);
  next = applyConflictEvent(next, event);
  return { ...next, log: appendLog(next, describeEvent(event)) };
}

function describeEvent(event) {
  return { eventId: event.event_id, type: event.type, actorHeroId: event.actor_hero_id, roomId: event.room_id, worldRound: event.world_round };
}

// Consumes one parsed server WebSocket/REST message and returns the patched
// store state. Called only from main.js's onMessage callback -- this
// function itself never touches the network or the DOM.
export function reduceServerMessage(state, message) {
  switch (message.kind) {
    case "reconnect_summary": {
      let next = applyView(state, message.snapshot.view, message.snapshot.revision);
      for (const event of message.missed_events) next = applyEvent(next, event);
      return { ...next, connection: "open", lastError: null };
    }
    case "snapshot":
      return applyView(state, message.view, message.revision);
    case "event":
      return applyEvent({ ...state, revision: typeof message.revision === "number" ? message.revision : state.revision }, message.event);
    case "command_ack":
      return { ...state, revision: message.revision, lastError: null };
    case "command_error":
      return { ...state, legalActions: message.legal_actions ?? state.legalActions, lastError: { code: message.code, message: message.message } };
    case "presence": {
      const hero = state.heroes[message.hero_id];
      if (!hero) return state;
      const patched = { ...hero };
      if (message.connected !== null && message.connected !== undefined) patched.connected = message.connected;
      if (message.ready !== null && message.ready !== undefined) patched.ready = message.ready;
      return { ...state, heroes: { ...state.heroes, [message.hero_id]: patched } };
    }
    default:
      return state;
  }
}

// -- Client-local puzzle scratch actions (infinite_stacks.md S24.4) --------
// No server command backs any of these this wave (task #10 constraint: the
// share/note mechanic is client-side only, do not invent a wire command for
// it), so they are plain state -> state functions main.js's handlers call
// via store.setState directly, never through sendCommand.

// A monotonic counter, deliberately not any random-number API -- this module
// is gameplay-facing (tests/test_stacks_static.py's randomness ban covers it
// same as selectors/components/screens; only core/commands.js's UUID
// fallback is the documented exception), and a note id only needs to be
// unique within this browser session, not unpredictable.
let noteIdCounter = 0;
function makeNoteId() {
  noteIdCounter += 1;
  return `note_${Date.now()}_${noteIdCounter}`;
}

// Copies a learned clue (state.puzzleClues[roomId][clueId]) into the
// party-visible shared-notes list and marks it shared, so its "Share with
// party" control (S24.4 "a deliberate Share control") only fires once.
export function shareClue(state, roomId, clueId, authorName) {
  const clue = (state.puzzleClues[roomId] || {})[clueId];
  if (!clue) return state;
  const alreadyShared = (state.sharedClueIds[roomId] || []).includes(clueId);
  if (alreadyShared) return state;
  const note = { id: makeNoteId(), text: clue.fallback, authorName: authorName || "You", linkedNoteIds: [], contradiction: false };
  return {
    ...state,
    sharedClueIds: appendUniqueToRoomList(state.sharedClueIds, roomId, clueId),
    puzzleManualNotes: { ...state.puzzleManualNotes, [roomId]: [...(state.puzzleManualNotes[roomId] || []), note] },
  };
}

export function addManualNote(state, roomId, text, authorName) {
  if (!roomId || !text) return state;
  const note = { id: makeNoteId(), text, authorName: authorName || "You", linkedNoteIds: [], contradiction: false };
  return { ...state, puzzleManualNotes: { ...state.puzzleManualNotes, [roomId]: [...(state.puzzleManualNotes[roomId] || []), note] } };
}

export function reorderManualNote(state, roomId, noteId, direction) {
  const notes = state.puzzleManualNotes[roomId] || [];
  const index = notes.findIndex((n) => n.id === noteId);
  const swapWith = direction === "up" ? index - 1 : index + 1;
  if (index === -1 || swapWith < 0 || swapWith >= notes.length) return state;
  const reordered = [...notes];
  [reordered[index], reordered[swapWith]] = [reordered[swapWith], reordered[index]];
  return { ...state, puzzleManualNotes: { ...state.puzzleManualNotes, [roomId]: reordered } };
}

export function linkManualNotes(state, roomId, noteId, otherNoteId) {
  if (noteId === otherNoteId) return state;
  const notes = state.puzzleManualNotes[roomId] || [];
  const next = notes.map((note) => {
    if (note.id === noteId && !note.linkedNoteIds.includes(otherNoteId)) return { ...note, linkedNoteIds: [...note.linkedNoteIds, otherNoteId] };
    if (note.id === otherNoteId && !note.linkedNoteIds.includes(noteId)) return { ...note, linkedNoteIds: [...note.linkedNoteIds, noteId] };
    return note;
  });
  return { ...state, puzzleManualNotes: { ...state.puzzleManualNotes, [roomId]: next } };
}

export function toggleManualNoteContradiction(state, roomId, noteId) {
  const notes = state.puzzleManualNotes[roomId] || [];
  const next = notes.map((note) => (note.id === noteId ? { ...note, contradiction: !note.contradiction } : note));
  return { ...state, puzzleManualNotes: { ...state.puzzleManualNotes, [roomId]: next } };
}

// Optimistic "you clicked Inspect" marker -- confirmed/overwritten by the
// object_inspected event's own puzzleInspectedObjects update above once the
// server round-trip lands, but set immediately so the button reflects the
// click without waiting on network latency.
export function markObjectInspected(state, roomId, objectId) {
  return { ...state, puzzleInspectedObjects: appendUniqueToRoomList(state.puzzleInspectedObjects, roomId, objectId) };
}
