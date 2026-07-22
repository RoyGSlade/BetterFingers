// Wave-6B part 4 real-module harness (docs/INFINITE_STACKS_CONTRACTS.md
// S5.11), same pattern as j12_legal_actions_check.mjs: runs the REAL client
// modules (core/store.js, core/selectors.js, core/commands.js) against a
// REAL snapshot captured from the live engine (tests/fixtures/stacks_ui/
// study_gothic_living_study.json, produced the same way
// puzzle_mystery_chamber.json was for wave 3) -- proving the exact code path
// the study screen, appeal picker, and converse ceremony use in the browser,
// not a reimplementation of it.
//
// Usage: node study_check.mjs < input.json (see readStdin's expected shape
// below, built by tests/test_stacks_study_ui.py from the fixture file).
// Prints one JSON object to stdout: {ok, reason, ...diagnostics}. Exit code
// 0 = pass, 1 = fail.

globalThis.window = globalThis.window || {};
if (!globalThis.window.crypto) globalThis.window.crypto = { randomUUID: () => "stub-uuid-for-node-harness" };

import { createInitialState, reduceServerMessage } from "../../backend/lan_playground/static/src/core/store.js";
import { selectActiveScreen, selectYouHero, selectStudyView, selectConverseView } from "../../backend/lan_playground/static/src/core/selectors.js";
import { interactCommand, converseCommand } from "../../backend/lan_playground/static/src/core/commands.js";

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function fail(reason, extra) {
  process.stdout.write(JSON.stringify({ ok: false, reason, ...extra }, null, 2) + "\n");
  process.exit(1);
}

function pass(extra) {
  process.stdout.write(JSON.stringify({ ok: true, ...extra }, null, 2) + "\n");
  process.exit(0);
}

const raw = await readStdin();
let input;
try {
  input = JSON.parse(raw);
} catch (e) {
  fail("stdin was not valid JSON: " + e.message);
}
const { heroId, otherHeroId, roomId, beforeInteractSnapshotMessage, snapshotMessage, socialCheckResolvedEvent } = input;
if (!heroId) fail("input JSON missing heroId");
if (!snapshotMessage) fail("input JSON missing snapshotMessage");

// -- 1. Baseline (before any interaction): active screen is "study", the
// object list is built entirely from the real projection, and interact
// commands are built by the real command builder ------------------------

let state = createInitialState();
state = { ...state, you: { ...state.you, heroId } };
state = reduceServerMessage(state, beforeInteractSnapshotMessage);

const you = selectYouHero(state);
if (!you) fail("selectYouHero(state) returned null after applying the real baseline snapshot");

const activeScreen = selectActiveScreen(state);
if (activeScreen !== "study") {
  fail("selectActiveScreen(state) did not return 'study' for a hero standing in a Study room", { activeScreen });
}

const studyViewBefore = selectStudyView(state);
if (!studyViewBefore) fail("selectStudyView(state) returned null for a hero standing in a Study room");
if (!studyViewBefore.objects.length) fail("selectStudyView(state).objects is empty against a real baseline snapshot");

const rugObject = studyViewBefore.objects.find((o) => o.id === "study_rug");
if (!rugObject) fail("baseline study view is missing the study_rug object", { objects: studyViewBefore.objects.map((o) => o.id) });
const rugMoveInteraction = rugObject.interactions.find((i) => i.id === "rug_move");
if (!rugMoveInteraction) fail("study_rug is missing its rug_move interaction in the real projection");
if (!rugMoveInteraction.legal) fail("rug_move should be legal in the baseline (undisturbed) state", { rugMoveInteraction });

// Build the actual interact command envelope the study screen would send,
// via the real command builder (core/commands.js) -- proves the
// button-click -> command pipeline, not just the projection read side.
const interactCmd = interactCommand(rugObject.id, rugMoveInteraction.id, state.revision);
if (interactCmd.type !== "interact" || interactCmd.payload.object_id !== "study_rug" || interactCmd.payload.interaction_id !== "rug_move") {
  fail("interactCommand() did not build the expected envelope", { interactCmd });
}

// -- 2. Full snapshot (after breach + interact + converse): appeal picker
// is built ONLY from projection data, never invented client-side ----------

let stateAfter = createInitialState();
stateAfter = { ...stateAfter, you: { ...stateAfter.you, heroId } };
stateAfter = reduceServerMessage(stateAfter, snapshotMessage);

const converseView = selectConverseView(stateAfter);
if (!converseView) fail("selectConverseView(state) returned null against a real snapshot with an NPC present");
if (!converseView.appealOptions.length) fail("selectConverseView(state).appealOptions is empty against a real snapshot");

const projectedRoom = stateAfter.studies[roomId];
if (!projectedRoom || !projectedRoom.npc) fail("state.studies[roomId].npc missing after folding the real snapshot", { roomId });
const projectedObjectiveIds = new Set(projectedRoom.npc.objectives.map((o) => o.id));
const pickerObjectiveIds = new Set(converseView.appealOptions.map((o) => o.id));
if (projectedObjectiveIds.size !== pickerObjectiveIds.size || [...projectedObjectiveIds].some((id) => !pickerObjectiveIds.has(id))) {
  fail("appeal picker's option set diverged from the real projection's npc.objectives -- picker must be built from EXACTLY that data", {
    projectedObjectiveIds: [...projectedObjectiveIds],
    pickerObjectiveIds: [...pickerObjectiveIds],
  });
}
// The ENGINE_ONLY hidden objective must never appear in the picker's source
// (this is the projection's own privacy guarantee -- tests/
// test_study_projection_privacy.py proves it server-side; this asserts the
// client never reintroduces it via a different code path).
if (pickerObjectiveIds.has("objective_hidden_avoid_confronting_death")) {
  fail("appeal picker exposed the ENGINE_ONLY hidden objective");
}

const converseCmd = converseCommand(converseView.npcId, converseView.appealOptions[0].id, stateAfter.revision);
if (converseCmd.type !== "converse" || converseCmd.payload.npc_id !== converseView.npcId) {
  fail("converseCommand() did not build the expected envelope", { converseCmd });
}
if ("motive_alignment" in converseCmd.payload) {
  fail("converseCommand() must never send a client-claimed motive_alignment field (standing rule #5)");
}

// -- 3. Ceremony renders the event payload verbatim (S24.2: the client never
// determines authoritative randomness) -------------------------------------

if (socialCheckResolvedEvent) {
  let ceremonyState = reduceServerMessage(stateAfter, { kind: "event", event: socialCheckResolvedEvent, revision: stateAfter.revision + 1 });
  const ceremonyView = selectConverseView(ceremonyState);
  if (!ceremonyView || !ceremonyView.lastCheckReceipt) {
    fail("selectConverseView(state).lastCheckReceipt did not populate after folding a real social_check_resolved event");
  }
  const receipt = ceremonyView.lastCheckReceipt;
  const wirePayload = socialCheckResolvedEvent.payload;
  for (const field of ["npc_id", "dc", "modifier", "evidence_tier", "motive_alignment", "die_rolls", "total", "margin", "outcome", "rich_outcome"]) {
    if (JSON.stringify(receipt[field]) !== JSON.stringify(wirePayload[field])) {
      fail(`selectConverseView(state).lastCheckReceipt.${field} diverged from the raw wire event payload -- the client must never recompute/alter this`, {
        field,
        receiptValue: receipt[field],
        wireValue: wirePayload[field],
      });
    }
  }
}

// -- 4. Privacy: selectActiveScreen/selectStudyView key off THIS viewer's
// own room_id, never a hardcoded or wrong hero's -- proven by resolving a
// genuinely nonexistent hero id (never in view.heroes at all) against the
// same real snapshot and confirming nothing resolves for them. -----------

let unknownState = createInitialState();
unknownState = { ...unknownState, you: { ...unknownState.you, heroId: "hero_never_joined_this_run" } };
unknownState = reduceServerMessage(unknownState, snapshotMessage);
if (selectYouHero(unknownState) !== null) {
  fail("selectYouHero resolved a hero id absent from view.heroes -- viewer identity is not being checked against the real snapshot");
}
if (selectActiveScreen(unknownState) === "study") {
  fail("selectActiveScreen resolved 'study' for a hero id absent from view.heroes entirely");
}

// otherHeroId in this fixture is a SECOND hero who genuinely shares the
// study room with heroId (captured that way on purpose, to prove the
// shared-room case) -- their own projection must still be independently
// derived from THEIR OWN state.studies[roomId] entry, not an alias of
// heroId's. The appeal picker's option set (party-scoped NPC objectives) is
// legitimately identical for both viewers sharing a room; what must NOT be
// true is that mutating one viewer's derived view object mutates the other's.
if (otherHeroId) {
  let otherState = createInitialState();
  otherState = { ...otherState, you: { ...otherState.you, heroId: otherHeroId } };
  otherState = reduceServerMessage(otherState, snapshotMessage);
  const otherConverseView = selectConverseView(otherState);
  if (!otherConverseView) fail("selectConverseView(state) returned null for a second hero genuinely sharing the study room");
  if (otherConverseView.appealOptions === converseView.appealOptions) {
    fail("two different viewers' selectConverseView() returned the SAME array reference for appealOptions -- must be independently derived, never aliased");
  }
  const otherObjectiveIds = new Set(otherConverseView.appealOptions.map((o) => o.id));
  if (otherObjectiveIds.has("objective_hidden_avoid_confronting_death")) {
    fail("second viewer's appeal picker exposed the ENGINE_ONLY hidden objective");
  }
}

pass({
  heroId: you.hero_id,
  activeScreen,
  objectCount: studyViewBefore.objects.length,
  appealOptionCount: converseView.appealOptions.length,
  interactCmd,
  converseCmd,
});
