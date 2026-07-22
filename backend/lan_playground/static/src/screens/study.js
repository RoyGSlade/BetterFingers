// Wave-6B part 4 (docs/INFINITE_STACKS_CONTRACTS.md S5.11, wavebasedgame.md
// S3.2 core loop, S3.1 row J4/J11): the Gothic Living Study room screen.
// Object list with currently-legal interactions (verb + object, driven
// entirely by the projection's own `legal` flag -- disabled, never hidden,
// when not legal, so the player can see what exists even before it's
// actionable), the interact round-trip over the existing command
// transport, and the response-artifact narration text as a real
// presentation block (this is the game's voice, not a console line). J11:
// this screen does not touch the character sidebar at all. J4: dice/check
// presentation is entirely components/check-receipt.js's existing
// server-result ceremony (via components/converse.js) -- no dice are
// rolled or rendered here beyond that shared, already-existing seam.
//
// Receives state+handlers and only builds DOM -- main.js is the sole place
// that wires network/store/timers together, same discipline as every other
// screen in this directory.

import { selectStudyView, selectConverseView } from "../core/selectors.js";
import { renderConversePanel } from "../components/converse.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// The narration block: the most recent response_artifact_emitted's
// narration_facts, given a real presentation block (heading + prose,
// role="status" so a screen reader announces new narration) rather than a
// console/log line -- this is the game's voice per the task brief.
function renderNarration(lastNarration) {
  const panel = el("section", "stacks-study-narration");
  panel.setAttribute("aria-label", "What just happened");
  panel.appendChild(el("h2", "stacks-panel-heading", "The Study Speaks"));
  if (!lastNarration) {
    panel.appendChild(el("p", "stacks-study-narration-text stacks-study-narration-empty", "The room is quiet, waiting for you to act."));
    return panel;
  }
  for (const fact of lastNarration.narrationFacts) {
    panel.appendChild(el("p", "stacks-study-narration-text", fact));
  }
  if (lastNarration.kind === "unsupported") {
    panel.appendChild(el("p", "stacks-study-narration-unsupported", "That isn't something this room understands yet."));
  }
  return panel;
}

// One object with its legal interactions rendered as individually
// selectable/inspectable buttons -- never buried in prose (same discipline
// screens/room.js and screens/puzzle.js already use for their own object
// lists). An interaction the projection marks illegal renders disabled
// (visible, not hidden) so the player can see the object's full repertoire.
function renderObject(object, handlers) {
  const card = el("article", "stacks-study-object");
  card.setAttribute("aria-label", object.accessible || object.name);
  card.appendChild(el("h3", "stacks-study-object-name", object.name));
  card.appendChild(el("p", "stacks-study-object-text", object.fallback));

  const actions = el("div", "stacks-study-object-actions");
  for (const interaction of object.interactions) {
    const button = el("button", "stacks-study-interaction-button", `${interaction.verb}`);
    button.type = "button";
    button.disabled = !interaction.legal;
    button.setAttribute(
      "aria-label",
      interaction.legal
        ? `${interaction.verb} ${object.name}: ${interaction.accessible || interaction.fallback}`
        : `${interaction.verb} ${object.name} (not available right now)`,
    );
    button.addEventListener("click", () => handlers.onInteract(object.id, interaction.id));
    actions.appendChild(button);
  }
  card.appendChild(actions);
  return card;
}

function renderObjects(studyView, handlers) {
  const panel = el("section", "stacks-study-objects");
  panel.setAttribute("aria-label", "Study objects");
  panel.appendChild(el("h2", "stacks-panel-heading", "Objects"));
  const list = el("div", "stacks-study-objects-list");
  for (const object of studyView.objects) list.appendChild(renderObject(object, handlers));
  panel.appendChild(list);
  return panel;
}

function renderHeading(studyView) {
  const heading = el("header", "stacks-study-heading");
  heading.appendChild(el("h1", "stacks-study-title", "The Gothic Living Study"));
  if (studyView.resolved) heading.appendChild(el("p", "stacks-study-status", "This room's meaning has been repaired."));
  return heading;
}

export function renderStudyScreen(container, state, handlers) {
  const studyView = selectStudyView(state);
  container.replaceChildren();
  if (!studyView) return;

  container.appendChild(renderHeading(studyView));
  const layout = el("div", "stacks-study-layout");
  layout.appendChild(renderNarration(studyView.lastNarration));
  layout.appendChild(renderObjects(studyView, handlers));

  const converseView = selectConverseView(state);
  if (converseView) layout.appendChild(renderConversePanel(converseView, handlers));

  container.appendChild(layout);
}
