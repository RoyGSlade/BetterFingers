// Wave-6B part 4 (docs/INFINITE_STACKS_CONTRACTS.md S5.11): the Elara Vance
// converse/appeal ceremony. Pure DOM construction from plain wire data; no
// network, no store access, no timers -- same discipline as
// components/check-receipt.js, whose "the client never rolls or computes
// anything, only presents the resolution" contract this component follows
// for the SOCIAL check exactly the way that one follows it for a combat
// check (infinite_stacks.md S24.2/S24.3, S24.2's "the client never
// determines authoritative randomness").
//
// SEAM FOR THE DICE-UI-OVERHAUL SESSION: renderConverseCeremony(receipt) is
// the ONE function that turns a raw social_check_resolved payload into DOM.
// It reads nothing from the store and computes nothing -- every field it
// shows (die_rolls, modifier, evidence_tier, motive_alignment, outcome,
// rich_outcome) is taken verbatim from the server event payload
// (core/selectors.js's selectConverseView.lastCheckReceipt passes it through
// unchanged). Restyling the ceremony (e.g. swapping in real 3D dice) means
// replacing this function's body only -- callers (screens/study.js) never
// need to change, since they only ever pass the receipt object through.

import { renderCheckReceipt } from "./check-receipt.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Appeal picker: one radio-style button per disclosed NPC objective (EXACTLY
// converseView.appealOptions -- built server-side from study.npc.objectives,
// which is already disclosure-filtered, so this component never needs its
// own visibility logic) plus a synthetic "No appeal" default every picker
// offers. Selecting an option only updates client-local draft state
// (handlers.onSelectAppeal) -- nothing is sent to the server until the
// Converse button itself is pressed.
function renderAppealPicker(converseView, handlers) {
  const panel = el("section", "stacks-converse-appeal-picker");
  panel.setAttribute("aria-label", "Choose an appeal");
  panel.appendChild(el("h3", "stacks-panel-heading", "Appeal to"));

  const list = el("div", "stacks-converse-appeal-list");

  const noAppealButton = el("button", "stacks-converse-appeal-option" + (!converseView.selectedAppealObjectiveId ? " is-selected" : ""), "No appeal -- speak plainly");
  noAppealButton.type = "button";
  noAppealButton.setAttribute("aria-pressed", String(!converseView.selectedAppealObjectiveId));
  noAppealButton.addEventListener("click", () => handlers.onSelectAppeal(converseView.roomId, null));
  list.appendChild(noAppealButton);

  for (const option of converseView.appealOptions) {
    const selected = converseView.selectedAppealObjectiveId === option.id;
    const button = el("button", "stacks-converse-appeal-option" + (selected ? " is-selected" : ""));
    button.type = "button";
    button.setAttribute("aria-pressed", String(selected));
    button.setAttribute("aria-label", option.accessible || option.fallback);
    button.appendChild(el("span", "stacks-converse-appeal-option-text", option.fallback));
    button.addEventListener("click", () => handlers.onSelectAppeal(converseView.roomId, option.id));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

// The check ceremony: reuses components/check-receipt.js's factual-receipt
// contract (attribute/skill/die result/modifiers/target number/outcome, S12.5)
// for the shared shape, then appends the social-specific fields
// check-receipt.js has no vocabulary for (evidence tier, motive alignment,
// appeal recognition, and the rich-outcome kind/line) as a second block.
// Every value is read straight off `receipt` (the raw wire payload) --
// nothing here is computed.
const OUTCOME_LABELS = {
  strong_success: "Strong success",
  clean_success: "Clean success",
  cost_progress: "Progress with cost",
  setback: "Meaningful setback",
};

const EVIDENCE_LABELS = {
  none: "No leverage",
  verifiable: "Verifiable evidence in hand",
};

const MOTIVE_LABELS = {
  neutral: "Neutral",
  strongly_aligned: "Strongly aligned with a stated objective",
  threatens_stated_fear: "Threatens a stated fear",
  contradicts_objective: "Contradicts a stated objective",
};

export function renderConverseCeremony(receipt) {
  const wrap = el("section", "stacks-converse-ceremony");
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "Social check ceremony");

  const dieResult = (receipt.die_rolls || [])[0];
  const outcomeLabel = OUTCOME_LABELS[receipt.outcome] || receipt.outcome;
  const modifiers = [];
  if (receipt.evidence_tier && receipt.evidence_tier !== "none") {
    modifiers.push({ source: "Evidence", value: null, label: EVIDENCE_LABELS[receipt.evidence_tier] || receipt.evidence_tier });
  }
  modifiers.push({ source: "Motive", value: null, label: MOTIVE_LABELS[receipt.motive_alignment] || receipt.motive_alignment });

  const baseReceipt = {
    action: "Converse",
    target: receipt.npc_id,
    attribute: "insight",
    skill: "social",
    dieResult: dieResult !== undefined ? dieResult : "?",
    modifiers: [{ source: "Contextual modifier (evidence + motive)", value: receipt.modifier }],
    targetNumber: receipt.dc,
    outcome: outcomeLabel,
  };
  wrap.appendChild(renderCheckReceipt(baseReceipt));

  // Social-specific breakdown check-receipt.js has no fields for.
  const breakdown = el("dl", "stacks-converse-breakdown");
  function addFact(term, value) {
    breakdown.appendChild(el("dt", null, term));
    breakdown.appendChild(el("dd", null, value));
  }
  addFact("Evidence", EVIDENCE_LABELS[receipt.evidence_tier] || receipt.evidence_tier);
  addFact("Motive alignment", MOTIVE_LABELS[receipt.motive_alignment] || receipt.motive_alignment);
  addFact("Appeal recognized", receipt.appeal_recognized ? "Yes" : "No");
  addFact("Margin", String(receipt.margin));
  wrap.appendChild(breakdown);

  if (receipt.rich_outcome) {
    const richLine = el("p", "stacks-converse-rich-outcome", `Beyond the roll: ${richOutcomeLine(receipt.rich_outcome)}`);
    richLine.setAttribute("role", "status");
    wrap.appendChild(richLine);
  }

  return wrap;
}

const RICH_OUTCOME_LINES = {
  lie: "She tells you something that doesn't add up.",
  behavioral_tell: "A small, telling gesture gives something away.",
  disposition_change: "How she feels about you has shifted.",
  objective_change: "Something she wants has changed.",
  partial_concession: "She gives a little ground, not everything.",
  counteroffer: "She offers different terms than you asked for.",
  new_danger: "Something about this conversation raises new risk.",
};

function richOutcomeLine(richOutcome) {
  return RICH_OUTCOME_LINES[richOutcome] || richOutcome;
}

// Full converse panel: appeal picker (hidden once a ceremony result exists
// for THIS conversation attempt -- selecting a new appeal always starts a
// fresh Converse press) + Converse button + the ceremony once resolved.
export function renderConversePanel(converseView, handlers) {
  const panel = el("section", "stacks-converse-panel");
  panel.setAttribute("aria-label", `Converse with ${converseView.npcId}`);
  panel.appendChild(el("h2", "stacks-panel-heading", "Converse"));
  panel.appendChild(el("p", "stacks-converse-disposition", `Disposition: ${converseView.disposition}`));

  panel.appendChild(renderAppealPicker(converseView, handlers));

  const converseButton = el("button", "stacks-converse-submit-button", "Converse");
  converseButton.type = "button";
  converseButton.addEventListener("click", () => handlers.onConverse(converseView.npcId, converseView.selectedAppealObjectiveId));
  panel.appendChild(converseButton);

  if (converseView.lastCheckReceipt) {
    panel.appendChild(renderConverseCeremony(converseView.lastCheckReceipt));
  }

  return panel;
}
