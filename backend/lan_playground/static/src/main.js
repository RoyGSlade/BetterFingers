// Bootstrap for stacks.html (infinite_stacks.md S22.3: "rendering functions
// receive state and emit UI; network calls, state mutation, timers, and DOM
// construction must not be interleaved in one large function"). This module
// is the one place that IS allowed to interleave those concerns -- it wires
// core/{api,socket,store,commands}.js to screens/map.js and to the static
// join-panel markup in stacks.html. No other module in static/src/ does this.

import { createRoom, joinRoom, fetchSnapshot, submitCommandOverRest } from "./core/api.js";
import { createStacksSocket } from "./core/socket.js";
import {
  createStore,
  createInitialState,
  reduceServerMessage,
  shareClue,
  addManualNote,
  reorderManualNote,
  linkManualNotes,
  toggleManualNoteContradiction,
  markObjectInspected,
} from "./core/store.js";
import {
  moveCommand,
  breachCommand,
  observeCommand,
  inspectCommand,
  passCommand,
  buildCommand,
  inspectObjectCommand,
  submitSolutionCommand,
  requestHintCommand,
  combatAttackCommand,
  combatManeuverCommand,
  combatReactionCommand,
} from "./core/commands.js";
import { selectActiveScreen, selectYouHero } from "./core/selectors.js";
import { renderMapScreen } from "./screens/map.js";
import { renderRoomScreen } from "./screens/room.js";
import { renderPuzzleScreen } from "./screens/puzzle.js";
import { renderCombatScreen } from "./screens/combat.js";

const store = createStore(createInitialState());
let socket = null;

const joinPanel = document.getElementById("join-panel");
const mapScreen = document.getElementById("map-screen");
const roomScreen = document.getElementById("room-screen");
const puzzleScreen = document.getElementById("puzzle-screen");
const combatScreen = document.getElementById("combat-screen");
const joinStatus = document.getElementById("join-status");

function setJoinStatus(text) {
  if (joinStatus) joinStatus.textContent = text;
}

function applyRestResult(resp) {
  store.setState((s) => reduceServerMessage(s, { kind: "command_ack", revision: resp.revision }));
  for (const event of resp.events || []) {
    store.setState((s) => reduceServerMessage(s, { kind: "event", event, revision: resp.revision }));
  }
}

function applyRestError(err) {
  const detail = err && err.detail;
  const code = detail && typeof detail === "object" ? detail.code : "request_failed";
  const legalActions = detail && typeof detail === "object" ? detail.legal_actions : null;
  store.setState((s) => reduceServerMessage(s, { kind: "command_error", code, legal_actions: legalActions, message: "" }));
}

function sendCommand(command) {
  const you = store.getState().you;
  const sentOverSocket = socket ? socket.sendCommand(command) : false;
  if (sentOverSocket) return;
  submitCommandOverRest({
    accessCode: you.accessCode,
    roomCode: you.roomCode,
    playerToken: you.playerToken,
    command,
  })
    .then(applyRestResult)
    .catch(applyRestError);
}

function currentRevision() {
  return store.getState().revision;
}

// The room the puzzle/notes actions below apply to: the viewer's own current
// room (selectYouHero mirrors the map screen's "current room" notion).
function currentRoomId() {
  const you = selectYouHero(store.getState());
  return you ? you.room_id : null;
}

function currentHeroName() {
  const state = store.getState();
  const hero = state.heroes[state.you.heroId];
  return hero ? hero.name : state.you.heroId;
}

function currentEncounterId() {
  const state = store.getState();
  const roomId = currentRoomId();
  const conflict = roomId ? state.conflicts[roomId] : null;
  return conflict ? conflict.encounter_id : null;
}

const handlers = {
  onMove: (toRoomId) => sendCommand(moveCommand(toRoomId, currentRevision())),
  onBreach: (direction) => sendCommand(breachCommand(direction, currentRevision())),
  onObserve: (direction) => sendCommand(observeCommand(direction, currentRevision())),
  onInspect: () => sendCommand(inspectCommand(currentRevision())),
  onPass: () => sendCommand(passCommand(currentRevision())),
  onSelectAlly: (heroId) => {
    const current = store.getState().selectedAllyId;
    store.setState({ selectedAllyId: current === heroId ? null : heroId });
  },
  // Generic entered-room screen (room.js) has no live wire projection yet
  // (docs/INFINITE_STACKS_CONTRACTS.md's project() carries no per-room
  // occupants/objects/exits detail beyond the map's rooms[room_id] outside of
  // puzzle rooms) -- it stays fixture-driven this wave, same as wave 2;
  // onUseExit is kept only so that screen still renders against its fixture.
  onUseExit: (direction) => sendCommand(buildCommand("use_exit", { direction }, { expectedRevision: currentRevision() })),
  // Live wave-3 puzzle commands (docs/INFINITE_STACKS_CONTRACTS.md S2):
  // inspect_object/submit_solution/request_hint round-trip through the real
  // server. markObjectInspected is an optimistic local UI marker (the wire
  // never tracks per-object inspection); the object_inspected event that
  // comes back confirms it (core/store.js).
  onInspectObject: (objectId) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => markObjectInspected(s, roomId, objectId));
    sendCommand(inspectObjectCommand(objectId, currentRevision()));
  },
  onRequestHint: () => sendCommand(requestHintCommand(currentRevision())),
  onSubmitSolution: (solution) => sendCommand(submitSolutionCommand(solution, currentRevision())),
  // Clue Share + shared notes (infinite_stacks.md S24.4) are client-side only
  // this wave -- no server command exists for them (task #10 constraint), so
  // these mutate the store directly instead of calling sendCommand.
  onShareClue: (clueId) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => shareClue(s, roomId, clueId, currentHeroName()));
  },
  onAddNote: (text) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => addManualNote(s, roomId, text, currentHeroName()));
  },
  onReorderNote: (noteId, direction) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => reorderManualNote(s, roomId, noteId, direction));
  },
  onLinkNotes: (noteId, otherNoteId) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => linkManualNotes(s, roomId, noteId, otherNoteId));
  },
  onToggleContradiction: (noteId) => {
    const roomId = currentRoomId();
    if (roomId) store.setState((s) => toggleManualNoteContradiction(s, roomId, noteId));
  },
  // Wave-3 combat commands (stacks-conflict's 17:15 vocabulary post): no
  // client-supplied numeric modifiers, just target/attribute/skill(/maneuver).
  onAttack: (targetId, attribute, skill) => sendCommand(combatAttackCommand(targetId, attribute, skill, currentRevision(), currentEncounterId())),
  onDeclareManeuver: (maneuver, targetId, attribute, skill) =>
    sendCommand(combatManeuverCommand(maneuver, targetId, attribute, skill, currentRevision(), currentEncounterId())),
  onReact: (reaction) => sendCommand(combatReactionCommand(reaction, currentRevision(), currentEncounterId())),
};

// Exactly one non-map screen is visible at a time, selected by
// selectActiveScreen (core/selectors.js) -- combat > puzzle > room > map.
function render(state) {
  if (!mapScreen) return;
  const activeScreen = selectActiveScreen(state);

  mapScreen.hidden = activeScreen !== "map";
  if (roomScreen) roomScreen.hidden = activeScreen !== "room";
  if (puzzleScreen) puzzleScreen.hidden = activeScreen !== "puzzle";
  if (combatScreen) combatScreen.hidden = activeScreen !== "combat";

  if (activeScreen === "map") renderMapScreen(mapScreen, state, handlers);
  else if (activeScreen === "room" && roomScreen) renderRoomScreen(roomScreen, state, handlers);
  else if (activeScreen === "puzzle" && puzzleScreen) renderPuzzleScreen(puzzleScreen, state, handlers);
  else if (activeScreen === "combat" && combatScreen) renderCombatScreen(combatScreen, state, handlers);
}

function watchReducedMotion() {
  const query = window.matchMedia("(prefers-reduced-motion: reduce)");
  store.setState({ reducedMotion: query.matches });
  query.addEventListener("change", (evt) => store.setState({ reducedMotion: evt.matches }));
}

function openGameSocket({ accessCode, roomCode, playerToken }) {
  socket = createStacksSocket({
    roomCode,
    accessCode,
    playerToken,
    onMessage: (message) => store.setState((s) => reduceServerMessage(s, message)),
    onConnectionChange: (connection) => store.setState({ connection }),
  });
  socket.connect();
}

function enterRun({ heroId, roomCode, accessCode, playerToken, revision }) {
  store.setState((s) => ({
    ...s,
    you: { heroId, roomCode, accessCode, playerToken },
    revision,
  }));
  if (joinPanel) joinPanel.hidden = true;
  if (mapScreen) mapScreen.hidden = false;
  openGameSocket({ accessCode, roomCode, playerToken });
  fetchSnapshot({ accessCode, roomCode, playerToken })
    .then((resp) => store.setState((s) => reduceServerMessage(s, { kind: "snapshot", view: resp.view, revision: resp.revision })))
    .catch(() => {});
}

function wireJoinPanel() {
  const accessCodeInput = document.getElementById("access-code-input");
  const displayNameInput = document.getElementById("display-name-input");
  const roomCodeInput = document.getElementById("room-code-input");
  const createButton = document.getElementById("create-room-button");
  const joinButton = document.getElementById("join-room-button");

  if (createButton) {
    createButton.addEventListener("click", () => {
      const accessCode = accessCodeInput ? accessCodeInput.value.trim() : "";
      const hostName = displayNameInput ? displayNameInput.value.trim() : "";
      if (!accessCode || !hostName) {
        setJoinStatus("Enter an access code and a display name first.");
        return;
      }
      setJoinStatus("Creating room...");
      createRoom({ accessCode, hostName, seed: null })
        .then((resp) =>
          enterRun({
            heroId: resp.hero_id,
            roomCode: resp.room_code,
            accessCode,
            playerToken: resp.player_token,
            revision: resp.revision,
          }),
        )
        .catch((err) => setJoinStatus(`Could not create room: ${err.message}`));
    });
  }

  if (joinButton) {
    joinButton.addEventListener("click", () => {
      const accessCode = accessCodeInput ? accessCodeInput.value.trim() : "";
      const displayName = displayNameInput ? displayNameInput.value.trim() : "";
      const roomCode = roomCodeInput ? roomCodeInput.value.trim() : "";
      if (!accessCode || !displayName || !roomCode) {
        setJoinStatus("Enter an access code, display name, and room code first.");
        return;
      }
      setJoinStatus("Joining room...");
      joinRoom({ accessCode, roomCode, displayName })
        .then((resp) =>
          enterRun({
            heroId: resp.hero_id,
            roomCode,
            accessCode,
            playerToken: resp.player_token,
            revision: resp.revision,
          }),
        )
        .catch((err) => setJoinStatus(`Could not join room: ${err.message}`));
    });
  }
}

function main() {
  wireJoinPanel();
  watchReducedMotion();
  store.subscribe(render);
  render(store.getState());
}

main();
