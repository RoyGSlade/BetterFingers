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
    // consumed via core/selectors.js's selectActiveScreen/selectEnteredRoomView/
    // selectPuzzleView/selectCombatView. Reducer wiring for the events that
    // populate these lands with the effects/combat lanes; wave 2 exercises
    // the screens against committed JSON fixtures (tests/fixtures/stacks_ui/).
    enteredRoom: null,
    puzzle: null,
    combat: null,
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

function applyView(state, view, revision) {
  return {
    ...state,
    revision: typeof revision === "number" ? revision : view.revision,
    worldRound: view.world_round,
    requiredRooms: view.required_rooms,
    maximumRooms: view.maximum_rooms,
    heroes: view.heroes,
    rooms: view.rooms,
    privateClue: view.viewer && view.heroes[view.viewer] ? view.heroes[view.viewer].private_clue ?? null : state.privateClue,
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
  if (event.type === "private_clue_assigned" && state.you.heroId === event.actor_hero_id) {
    next = { ...next, privateClue: event.payload.clue };
  }
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
