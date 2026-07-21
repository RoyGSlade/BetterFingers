// Generic entered-room screen (infinite_stacks.md S9, S24.1/S24.4): shows
// who else is here, which objects are inspectable, and which exits are
// available with their Energy cost on the action button itself -- plus
// room family and any corruption tells (observable emotional/corruption
// signs, S9.1/S5.4). Receives state+handlers and only builds DOM; main.js
// is the sole place that wires network/store/timers together.

import { selectEnteredRoomView } from "../core/selectors.js";
import { renderStatusList } from "../components/status.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderOccupants(room) {
  const panel = el("section", "stacks-room-occupants");
  panel.setAttribute("aria-label", "Who is here");
  panel.appendChild(el("h2", "stacks-panel-heading", "Present"));
  const list = el("ul", "stacks-room-occupants-list");
  for (const occupant of room.occupants) {
    const item = el("li", "stacks-room-occupant" + (occupant.isYou ? " is-you" : ""));
    const name = el("span", "stacks-room-occupant-name", occupant.name + (occupant.isYou ? " (you)" : ""));
    item.appendChild(name);
    const kind = el("span", "stacks-room-occupant-kind", occupant.kind);
    item.appendChild(kind);
    if (occupant.statuses && occupant.statuses.length) {
      item.appendChild(renderStatusList(occupant.statuses));
    }
    list.appendChild(item);
  }
  panel.appendChild(list);
  return panel;
}

// Objects are individually selectable/inspectable buttons -- never buried in
// a prose paragraph (S24.4 applies to any inspectable object, not just
// puzzle rooms).
function renderObjects(room, handlers) {
  const panel = el("section", "stacks-room-objects");
  panel.setAttribute("aria-label", "Inspectable objects");
  panel.appendChild(el("h2", "stacks-panel-heading", "Objects"));
  const list = el("div", "stacks-room-objects-list");
  for (const object of room.objects) {
    const button = el("button", "stacks-room-object" + (object.inspected ? " is-inspected" : ""), object.label);
    button.type = "button";
    button.dataset.objectId = object.id;
    button.setAttribute("aria-label", object.inspected ? `${object.label} (already inspected)` : `Inspect ${object.label}`);
    button.addEventListener("click", () => handlers.onInspectObject(object.id));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

// Every exit shows its Energy cost directly on the action button (S8.1
// move=1/breach=3, S24.1) so the cost is never a hidden fact players
// discover only after committing.
function renderExits(room, handlers) {
  const panel = el("section", "stacks-room-exits");
  panel.setAttribute("aria-label", "Exits");
  panel.appendChild(el("h2", "stacks-panel-heading", "Exits"));
  const list = el("div", "stacks-room-exits-list");
  for (const exit of room.exits) {
    const button = el("button", "stacks-room-exit");
    button.type = "button";
    button.disabled = !exit.legal;
    const label = el("span", "stacks-room-exit-label", `${exit.direction}: ${exit.label}`);
    button.appendChild(label);
    const cost = el("span", "stacks-room-exit-cost", `${exit.energyCost} Energy`);
    button.appendChild(cost);
    button.setAttribute("aria-label", `${exit.direction} exit, ${exit.label}, costs ${exit.energyCost} Energy`);
    button.addEventListener("click", () => handlers.onUseExit(exit.direction));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

function renderCorruptionTells(room) {
  if (!room.corruptionTells || !room.corruptionTells.length) return null;
  const panel = el("section", "stacks-room-corruption-tells");
  panel.setAttribute("aria-label", "Corruption tells");
  panel.appendChild(el("h2", "stacks-panel-heading", "Corruption tells"));
  const list = el("ul", "stacks-room-corruption-tells-list");
  for (const tell of room.corruptionTells) {
    list.appendChild(el("li", null, tell.text));
  }
  panel.appendChild(list);
  return panel;
}

function renderHeading(room) {
  const heading = el("header", "stacks-room-heading");
  heading.appendChild(el("h1", "stacks-room-family", room.familyLabel));
  if (room.subtypeLabel) heading.appendChild(el("p", "stacks-room-subtype", room.subtypeLabel));
  return heading;
}

export function renderRoomScreen(container, state, handlers) {
  const room = selectEnteredRoomView(state);
  container.replaceChildren();
  if (!room) return;

  container.appendChild(renderHeading(room));
  const layout = el("div", "stacks-room-layout");
  layout.appendChild(renderOccupants(room));
  layout.appendChild(renderObjects(room, handlers));
  layout.appendChild(renderExits(room, handlers));
  const tells = renderCorruptionTells(room);
  if (tells) layout.appendChild(tells);
  container.appendChild(layout);
}
