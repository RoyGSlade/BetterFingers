// J12 regression harness (docs/PLAYTEST_FINDINGS_2026-07-20.md): runs the
// REAL client modules (core/store.js, core/selectors.js, core/commands.js)
// against a REAL snapshot captured from the live engine over the real
// transport (tests/test_stacks_e2e.py::LegalActionsLockoutRegressionTests
// drives that half and shells out to this script with the snapshot JSON
// piped in on stdin), proving the exact code path the map screen and hint
// line use in the browser -- not a reimplementation of it.
//
// Node has no DOM here, but none of the functions this script calls need
// one: reduceServerMessage/applyView, selectLegalActionsSummary,
// selectHintText, and commands.js's command builders are all pure
// data -> data functions (screens/map.js is the only place that touches
// document, and it only *reads* legalActions.can_inspect/can_pass/
// can_move_to/can_breach_directions off the exact same selector this script
// calls -- see that file's renderMapGrid/renderYouPanel). commands.js's
// generateId() does touch `window.crypto`, so a minimal stub is provided
// below purely so the import doesn't crash in a browser-less runtime; it is
// never used to fabricate gameplay data.
//
// Usage: node j12_legal_actions_check.mjs < snapshot.json
// Prints one JSON object to stdout: {ok, reason, ...diagnostics}. Exit code
// 0 = pass, 1 = fail (mirrors the "test must fail if the regression
// recurs" requirement -- the calling Python test asserts on both).

globalThis.window = globalThis.window || {};
if (!globalThis.window.crypto) globalThis.window.crypto = { randomUUID: () => "stub-uuid-for-node-harness" };

import { createInitialState, reduceServerMessage } from "../../backend/lan_playground/static/src/core/store.js";
import { selectLegalActionsSummary, selectHintText, selectYouHero } from "../../backend/lan_playground/static/src/core/selectors.js";
import { moveCommand, breachCommand, inspectCommand, passCommand } from "../../backend/lan_playground/static/src/core/commands.js";

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
const { heroId, snapshotMessage } = input;
if (!heroId) fail("input JSON missing heroId");
if (!snapshotMessage) fail("input JSON missing snapshotMessage");

// main.js's enterRun() sets state.you from the join/create-room REST
// response BEFORE any snapshot/event ever reaches reduceServerMessage --
// replicated here so selectYouHero (which reads state.you.heroId) resolves
// exactly as it would in the browser.
let state = createInitialState();
state = { ...state, you: { ...state.you, heroId } };

// This is the exact reducer branch main.js's onMessage callback dispatches a
// server "snapshot" (REST) or "reconnect_summary" (WS reconnect) message
// through -- see core/store.js's reduceServerMessage.
state = reduceServerMessage(state, snapshotMessage);

const you = selectYouHero(state);
if (!you) fail("selectYouHero(state) returned null after applying the real snapshot -- viewer hero missing from view.heroes");

const legalActions = selectLegalActionsSummary(state);
if (!legalActions) {
  fail("selectLegalActionsSummary(state) is null/undefined after a real engine snapshot was applied -- this is the exact J12 regression: the map screen's buttons and the hint line both read this field (screens/map.js, core/selectors.js's selectHintText) and both default to fully locked out when it is missing.");
}

const canMoveTo = legalActions.can_move_to || [];
const canBreach = legalActions.can_breach_directions || [];
const canInspect = !!legalActions.can_inspect;
const canPass = !!legalActions.can_pass;

const anyLegal = canMoveTo.length > 0 || canBreach.length > 0 || canInspect || canPass;
if (!anyLegal) {
  fail("no legal Move/Breach/Inspect/Pass action found in selectLegalActionsSummary(state) -- entrance-room lockout regression", { legalActions });
}

// The hint line (selectHintText) must NOT fall into the "No moves
// available..." branch when at least one action is actually legal --
// this is the "hint line and buttons read the SAME source" check the
// playtest doc flagged as a suspect. Both already read state.legalActions
// (this test's whole point is proving that field is populated), so this
// assertion mostly guards against a future divergence being reintroduced.
const hintText = selectHintText(state);
const LOCKOUT_HINT = "No moves available from here right now";
if (hintText.startsWith(LOCKOUT_HINT)) {
  fail("selectHintText(state) still reports the lockout hint even though a legal action exists -- hint line has diverged from the button source", { hintText, legalActions });
}

// Build the actual command envelope the map screen would send for whichever
// action is legal, via the real command builders (core/commands.js) -- this
// is the "selectable/executable through the client's own code path" half of
// the requirement. The calling Python test submits this exact envelope
// through the real transport and asserts the server accepts it.
let command;
if (canPass) {
  command = passCommand(state.revision);
} else if (canInspect) {
  command = inspectCommand(state.revision);
} else if (canMoveTo.length > 0) {
  command = moveCommand(canMoveTo[0], state.revision);
} else {
  command = breachCommand(canBreach[0], state.revision);
}

pass({
  heroId: you.hero_id,
  legalActions,
  hintText,
  command,
});
