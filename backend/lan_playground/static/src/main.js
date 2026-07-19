// Bootstrap for stacks.html (infinite_stacks.md S22.3: "rendering functions
// receive state and emit UI; network calls, state mutation, timers, and DOM
// construction must not be interleaved in one large function"). This module
// is the one place that IS allowed to interleave those concerns -- it wires
// core/{api,socket,store,commands}.js to screens/map.js and to the static
// join-panel markup in stacks.html. No other module in static/src/ does this.

import { createRoom, joinRoom, fetchSnapshot, submitCommandOverRest } from "./core/api.js";
import { createStacksSocket } from "./core/socket.js";
import { createStore, createInitialState, reduceServerMessage } from "./core/store.js";
import { moveCommand, breachCommand, observeCommand, inspectCommand, passCommand } from "./core/commands.js";
import { renderMapScreen } from "./screens/map.js";

const store = createStore(createInitialState());
let socket = null;

const joinPanel = document.getElementById("join-panel");
const mapScreen = document.getElementById("map-screen");
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
};

function render(state) {
  if (!mapScreen) return;
  renderMapScreen(mapScreen, state, handlers);
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
