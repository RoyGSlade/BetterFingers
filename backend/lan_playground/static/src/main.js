// Bootstrap for stacks.html (infinite_stacks.md S22.3: "rendering functions
// receive state and emit UI; network calls, state mutation, timers, and DOM
// construction must not be interleaved in one large function"). This module
// is the one place that IS allowed to interleave those concerns -- it wires
// core/{api,socket,store,commands}.js to screens/map.js and to the static
// join-panel markup in stacks.html. No other module in static/src/ does this.

import { createRoom, joinRoom, fetchSnapshot, fetchContentCatalog, submitCommandOverRest } from "./core/api.js";
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
  setContentCatalog,
  updateCharacterDraft,
  openHelp,
  closeHelp,
  setPendingAction,
  clearPendingAction,
  inspectCard,
  clearInspectedCard,
  setAppealDraft,
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
  resolveReactionCommand,
  rollAttributeDiceCommand,
  createHeroCommand,
  drawCardsCommand,
  playCardCommand,
  safeRestCommand,
  pickupItemCommand,
  dropItemCommand,
  tradeItemCommand,
  recoverBodyLootCommand,
  useAbilityCommand,
  interactCommand,
  converseCommand,
} from "./core/commands.js";
import { selectActiveScreen, selectYouHero, selectMoveCost, selectBreachCost, selectHintText } from "./core/selectors.js";
import { renderMapScreen } from "./screens/map.js";
import { renderRoomScreen } from "./screens/room.js";
import { renderPuzzleScreen } from "./screens/puzzle.js";
import { renderStudyScreen } from "./screens/study.js";
import { renderCombatScreen } from "./screens/combat.js";
import { renderCharacterBuilderScreen } from "./screens/character-builder.js";
import { renderCharacterPanel } from "./screens/character-panel.js";
import { renderHandDock } from "./screens/hero-panel.js";
import { renderConfirmBar } from "./components/confirm-dialog.js";
import { renderRulesOverlay, renderHelpButton, renderHintBar } from "./components/rules-overlay.js";

const store = createStore(createInitialState());
let socket = null;

const joinPanel = document.getElementById("join-panel");
const mapScreen = document.getElementById("map-screen");
const roomScreen = document.getElementById("room-screen");
const puzzleScreen = document.getElementById("puzzle-screen");
const studyScreen = document.getElementById("study-screen");
const combatScreen = document.getElementById("combat-screen");
const characterBuilderScreen = document.getElementById("character-builder-screen");
const characterPanel = document.getElementById("character-panel");
const handDock = document.getElementById("hand-dock");
const chrome = document.getElementById("stacks-chrome");
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

// Wave-6B part 4: object_state_changed's wire payload ({object_id,
// from_state, to_state, interaction_id}) has no updated prose/legal-
// interaction data -- only a full re-projection (study_projection.py) can
// rebuild an object's disclosure-filtered fallback/accessible text and
// which of its interactions are newly (il)legal. core/store.js's
// applyStudyEvent already folds every ledger/scalar field it CAN derive
// from the event stream alone (so a WS-connected second viewer sees partial
// updates immediately); this refetch is what guarantees the ACTING client's
// objects list itself never goes stale after interact/converse, per this
// wave's "state changes re-render from the next snapshot/event" requirement.
function refreshSnapshotForStudy() {
  const you = store.getState().you;
  if (!you.roomCode) return;
  fetchSnapshot({ accessCode: you.accessCode, roomCode: you.roomCode, playerToken: you.playerToken })
    .then((resp) => store.setState((s) => reduceServerMessage(s, { kind: "snapshot", view: resp.view, revision: resp.revision })))
    .catch(() => {});
}

// interact/converse always follow up with a snapshot refetch (see
// refreshSnapshotForStudy's comment) regardless of transport: over REST,
// once the command's own response has already been folded in; over WS, the
// broadcast event(s) normally arrive first, but the fetch is scheduled
// right after sending either way so the objects list is never left stale
// waiting on a slow/lost broadcast.
function sendStudyCommand(command) {
  const you = store.getState().you;
  const sentOverSocket = socket ? socket.sendCommand(command) : false;
  if (sentOverSocket) {
    refreshSnapshotForStudy();
    return;
  }
  submitCommandOverRest({
    accessCode: you.accessCode,
    roomCode: you.roomCode,
    playerToken: you.playerToken,
    command,
  })
    .then((resp) => {
      applyRestResult(resp);
      refreshSnapshotForStudy();
    })
    .catch(applyRestError);
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

// Wave-6 playtest response (docs/PLAYTEST_FINDINGS_2026-07-19.md A4/C1): a
// move/breach/card-play click never calls sendCommand directly anymore --
// it stages a plain-data pendingAction here, and only the confirm bar's own
// Confirm button (onConfirmPendingAction below) actually dispatches.
function heroLabel(heroId) {
  const hero = store.getState().heroes[heroId];
  return hero ? hero.name : heroId;
}

const handlers = {
  onRequestMove: (toRoomId) => {
    const cost = selectMoveCost(store.getState(), toRoomId);
    store.setState((s) =>
      setPendingAction(s, { kind: "move", toRoomId, energyCost: cost, label: `Move here for ${cost} Energy?`, confirmLabel: "Move" }),
    );
  },
  onRequestBreach: (direction) => {
    const cost = selectBreachCost(store.getState(), direction);
    store.setState((s) =>
      setPendingAction(s, { kind: "breach", direction, energyCost: cost, label: `Breach ${direction} for ${cost} Energy?`, confirmLabel: "Breach" }),
    );
  },
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
  // §21.4 reaction interrupt window (board task #16/#17): reactionId ties
  // the response to the exact pending interrupt combat.js's
  // renderReactionPrompt is showing.
  onReact: (reactionId, reaction) => sendCommand(resolveReactionCommand(reactionId, reaction, currentRevision(), currentEncounterId())),
  // Wave-5 hero commands (docs/INFINITE_STACKS_CONTRACTS.md S5.4, board task
  // #17): character creation, hand/deck, and inventory.
  onRollAttributeDice: () => sendCommand(rollAttributeDiceCommand(currentRevision())),
  onCreateHero: (draft) => sendCommand(createHeroCommand(draft, currentRevision())),
  onUpdateCharacterDraft: (patch) => store.setState((s) => updateCharacterDraft(s, patch)),
  onDrawCards: (count) => sendCommand(drawCardsCommand(count, currentRevision())),
  onSafeRest: () => sendCommand(safeRestCommand(currentRevision())),
  onPickupItem: (itemInstanceId) => sendCommand(pickupItemCommand(itemInstanceId, currentRevision())),
  onDropItem: (itemId) => sendCommand(dropItemCommand(itemId, currentRevision())),
  onTradeItem: (toHeroId, itemId) => sendCommand(tradeItemCommand(toHeroId, itemId, currentRevision())),
  onRecoverBodyLoot: (deadHeroId, itemIds) => sendCommand(recoverBodyLootCommand(deadHeroId, itemIds, currentRevision())),
  onUseAbility: (abilityId) => sendCommand(useAbilityCommand(abilityId, currentRevision())),

  // -- Wave-6B part 4 study/converse (docs/INFINITE_STACKS_CONTRACTS.md S5.11) --
  onInteract: (objectId, interactionId) => sendStudyCommand(interactCommand(objectId, interactionId, currentRevision())),
  onSelectAppeal: (roomId, appealObjectiveId) => store.setState((s) => setAppealDraft(s, roomId, appealObjectiveId)),
  onConverse: (npcId, appealObjectiveId) => sendStudyCommand(converseCommand(npcId, appealObjectiveId, currentRevision())),

  // -- Wave-6 playtest response (A1-A5, B1/B2, C1) ------------------------
  onOpenHelp: () => store.setState((s) => openHelp(s)),
  onCloseHelp: () => store.setState((s) => closeHelp(s)),
  // A4: click = inspect only, never plays. Toggles the expanded card.
  onInspectCard: (cardId) => store.setState((s) => inspectCard(s, cardId)),
  // A4: the expanded card's own "Play card" button stages a pendingAction
  // instead of sending play_card directly -- committing still requires the
  // confirm bar's explicit Confirm press.
  onRequestPlayCard: (card, target) => {
    const targetName = target && target.targetHeroId ? heroLabel(target.targetHeroId) : target && target.targetEnemyId ? target.targetEnemyId : null;
    store.setState((s) =>
      setPendingAction(s, {
        kind: "play_card",
        cardId: card.id,
        targetHeroId: target ? target.targetHeroId : null,
        targetEnemyId: target ? target.targetEnemyId : null,
        label: `Play ${card.name}${targetName ? ` on ${targetName}` : ""}?`,
        confirmLabel: "Play card",
      }),
    );
  },
  onConfirmPendingAction: (action) => {
    store.setState((s) => clearPendingAction(clearInspectedCard(s)));
    if (action.kind === "move") sendCommand(moveCommand(action.toRoomId, currentRevision()));
    else if (action.kind === "breach") sendCommand(breachCommand(action.direction, currentRevision()));
    else if (action.kind === "play_card") {
      sendCommand(
        playCardCommand(action.cardId, { targetHeroId: action.targetHeroId, targetEnemyId: action.targetEnemyId }, currentRevision(), currentEncounterId()),
      );
    }
  },
  onCancelPendingAction: () => store.setState((s) => clearPendingAction(s)),
};

// The Veil (Ritual Spire motion language): a wall of ichor sweeps across the
// viewport whenever the active screen changes mid-run -- crimson-edged when
// combat wakes, gilt-edged otherwise. Pure CSS animation (stacks.css
// .stacks-veil); reduced-motion swaps the sweep for a 200ms crossfade via
// the stylesheet's kill switch, so nothing here needs a timer. The element
// lives on document.body, not #stacks-chrome, because renderChrome rebuilds
// chrome's children on every state change and would cut the sweep short.
let lastActiveScreen = null;

function spawnVeil(enteringCombat) {
  const veil = document.createElement("div");
  veil.className = "stacks-veil" + (enteringCombat ? " stacks-veil--combat" : "");
  veil.setAttribute("aria-hidden", "true");
  const remove = () => veil.remove();
  veil.addEventListener("animationend", remove, { once: true });
  veil.addEventListener("animationcancel", remove, { once: true });
  document.body.appendChild(veil);
}

// Exactly one non-map screen is visible at a time, selected by
// selectActiveScreen (core/selectors.js) -- character-builder > combat >
// puzzle > room > map.
function render(state) {
  if (!mapScreen) return;
  const activeScreen = selectActiveScreen(state);

  if (lastActiveScreen !== null && lastActiveScreen !== activeScreen && state.you.heroId) {
    spawnVeil(activeScreen === "combat");
  }
  lastActiveScreen = activeScreen;

  mapScreen.hidden = activeScreen !== "map";
  if (roomScreen) roomScreen.hidden = activeScreen !== "room";
  if (puzzleScreen) puzzleScreen.hidden = activeScreen !== "puzzle";
  if (studyScreen) studyScreen.hidden = activeScreen !== "study";
  if (combatScreen) combatScreen.hidden = activeScreen !== "combat";
  if (characterBuilderScreen) characterBuilderScreen.hidden = activeScreen !== "character-builder";

  if (activeScreen === "character-builder" && characterBuilderScreen) {
    renderCharacterBuilderScreen(characterBuilderScreen, state, handlers);
  } else if (activeScreen === "map") renderMapScreen(mapScreen, state, handlers);
  else if (activeScreen === "room" && roomScreen) renderRoomScreen(roomScreen, state, handlers);
  else if (activeScreen === "puzzle" && puzzleScreen) renderPuzzleScreen(puzzleScreen, state, handlers);
  else if (activeScreen === "study" && studyScreen) renderStudyScreen(studyScreen, state, handlers);
  else if (activeScreen === "combat" && combatScreen) renderCombatScreen(combatScreen, state, handlers);

  // Wave-6 persistent chrome (playtest D1/D2/A1/B1/B2): rendered on every
  // screen except character creation itself (no sheet/hand/inventory to
  // show until a hero exists).
  const showPersistentPanels = activeScreen !== "character-builder";
  if (characterPanel) {
    if (showPersistentPanels) renderCharacterPanel(characterPanel, state, handlers);
    else {
      characterPanel.hidden = true;
      characterPanel.replaceChildren();
    }
  }
  if (handDock) {
    if (showPersistentPanels) renderHandDock(handDock, state, handlers);
    else {
      handDock.hidden = true;
      handDock.replaceChildren();
    }
  }
  renderChrome(state);
}

// Help button + persistent hint line (B1/B2) + the first-run rules overlay
// + the A4/C1 confirm bar -- all rendered into one fixed-position container
// so they stay visible/above every screen regardless of which is active.
//
// Wave-6A fix (wavebasedgame.md S3.1 "pre-join rules modal"): helpOpen
// defaults to true (store.js's createInitialState) so the overlay still
// greets a player the first time they actually have a hero to onboard --
// but rendering it unconditionally meant it ALSO covered the pre-join
// "Enter the Spire" screen on first page load, before selectYouHero(state)
// is even truthy, blocking the "Kindle a New Run" CTA underneath it. The
// help button and hint bar were already correctly gated on selectYouHero;
// the overlay itself was the one piece of chrome that wasn't. Same gate,
// applied consistently: no hero yet means nothing in #stacks-chrome renders
// except the confirm bar (which has its own pendingAction-is-null guard and
// can't fire before a hero exists anyway).
function renderChrome(state) {
  if (!chrome) return;
  chrome.replaceChildren();
  if (selectYouHero(state)) {
    chrome.appendChild(renderHelpButton({ onOpen: handlers.onOpenHelp }));
    chrome.appendChild(renderHintBar(selectHintText(state)));
    const overlay = renderRulesOverlay(state.helpOpen, { onClose: handlers.onCloseHelp });
    if (overlay) chrome.appendChild(overlay);
  }
  const confirmBar = renderConfirmBar(state.pendingAction, { onConfirm: handlers.onConfirmPendingAction, onCancel: handlers.onCancelPendingAction });
  if (confirmBar) chrome.appendChild(confirmBar);
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
  // Reserves layout room for the fixed character panel/hand dock only once
  // a run is actually entered (stacks.css scopes their padding under this
  // class) -- keeps the pre-join screen centered instead of permanently
  // offset by space for chrome that has nothing to show yet.
  document.body.classList.add("stacks-in-run");
  openGameSocket({ accessCode, roomCode, playerToken });
  fetchSnapshot({ accessCode, roomCode, playerToken })
    .then((resp) => store.setState((s) => reduceServerMessage(s, { kind: "snapshot", view: resp.view, revision: resp.revision })))
    .catch(() => {});
  // Static background/card/item catalog for the character-builder screen
  // (board task #17) -- fetched once per run, independent of the snapshot.
  fetchContentCatalog({ accessCode })
    .then((catalog) => store.setState((s) => setContentCatalog(s, catalog)))
    .catch(() => {});
}

// J1 (playtest 07-20): joining used to ask for the hero's name up front,
// conflating "get into the run" with "decide who you are" -- identity
// belongs in the creation flow (character-builder.js), which already asks
// for a name plus background/attributes/cards/token. Join is now minimal
// (access code, plus a room code to join an existing run); host_name/
// display_name are OPTIONAL on the wire (stacks_api.py's CreateRoomRequest/
// JoinRoomRequest) and the server assigns a placeholder transport label
// when omitted (StacksRoomManager) -- no client-invented identity value
// crosses the wire, so this stays "client renders, server owns truth."
function wireJoinPanel() {
  const accessCodeInput = document.getElementById("access-code-input");
  const roomCodeInput = document.getElementById("room-code-input");
  const createButton = document.getElementById("create-room-button");
  const joinButton = document.getElementById("join-room-button");

  if (createButton) {
    createButton.addEventListener("click", () => {
      const accessCode = accessCodeInput ? accessCodeInput.value.trim() : "";
      if (!accessCode) {
        setJoinStatus("Enter an access code first.");
        return;
      }
      setJoinStatus("Creating room...");
      createRoom({ accessCode, seed: null })
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
      const roomCode = roomCodeInput ? roomCodeInput.value.trim() : "";
      if (!accessCode || !roomCode) {
        setJoinStatus("Enter an access code and a room code first.");
        return;
      }
      setJoinStatus("Joining room...");
      joinRoom({ accessCode, roomCode })
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
