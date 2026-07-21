// One map tile (infinite_stacks.md S24.1; playtest C1/F1): fog of war
// without a false boundary, connector states (open/locked/undiscovered/
// none/unstable/secret-discovered/one-way) with a text label alongside the
// glyph so nothing is color-only, Energy cost shown at the point of click
// (C1), and hero TOKENS (art + color, not name text) showing danger state
// (F1). Pure DOM construction from the plain data selectors.js already
// computed -- no network, no store access, no timers. Clicking a legal move
// tile or breach connector only ever calls onRequestMove/onRequestBreach --
// main.js stages a pendingAction from that and the confirm bar is what
// actually sends a command, never this component.

import { renderToken } from "./token.js";

function renderConnector(connector, { interactive, onActivate, costLabel } = {}) {
  const el = document.createElement(interactive ? "button" : "span");
  el.className = `stacks-connector stacks-connector--${connector.state}` + (interactive ? " is-actionable" : "");
  if (interactive) {
    el.type = "button";
    el.addEventListener("click", () => onActivate(connector.direction));
  }
  const glyph = document.createElement("span");
  glyph.className = "stacks-connector-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = connector.glyph;
  el.appendChild(glyph);
  const label = document.createElement("span");
  label.className = "stacks-connector-label";
  label.textContent = `${connector.direction}: ${connector.label}` + (costLabel ? ` (${costLabel})` : "");
  el.appendChild(label);
  return el;
}

export function renderRoomTile(
  tile,
  {
    heroesById = {},
    isCurrentRoom = false,
    canMoveHere = false,
    moveEnergyCost = null,
    onRequestMove,
    isRoutePreview = false,
    legalBreachDirections = [],
    breachCostFor = () => null,
    onRequestBreach,
    legalObserveDirections = [],
    onObserve,
  } = {},
) {
  if (tile.kind === "fog") {
    const fog = document.createElement("div");
    fog.className = "stacks-tile stacks-tile--fog";
    fog.setAttribute("role", "img");
    fog.setAttribute("aria-label", "Fog of war: unexplored, not yet known to be a boundary");
    return fog;
  }

  const interactive = canMoveHere && typeof onRequestMove === "function" && !isCurrentRoom;
  const el = document.createElement(interactive ? "button" : "div");
  el.className =
    "stacks-tile stacks-tile--room" +
    (isCurrentRoom ? " is-current" : "") +
    (isRoutePreview ? " is-route-preview" : "") +
    (tile.required ? " is-required" : "") +
    (interactive ? " is-actionable" : "");
  el.dataset.roomId = tile.roomId;
  if (interactive) {
    el.type = "button";
    el.setAttribute("aria-label", `Move to ${tile.familyLabel} room (${moveEnergyCost} Energy)`);
    el.addEventListener("click", () => onRequestMove(tile.roomId));
  }

  const heading = document.createElement("div");
  heading.className = "stacks-tile-heading";
  heading.textContent = tile.familyLabel + (isCurrentRoom ? " (here)" : "");
  el.appendChild(heading);

  if (interactive) {
    const costBadge = document.createElement("span");
    costBadge.className = "stacks-tile-move-cost";
    costBadge.textContent = `Move: ${moveEnergyCost} Energy`;
    el.appendChild(costBadge);
  }

  if (tile.required) {
    const badge = document.createElement("span");
    badge.className = "stacks-tile-badge";
    badge.textContent = "Required";
    el.appendChild(badge);
  }

  if (tile.heroesHere.length) {
    const heroes = document.createElement("div");
    heroes.className = "stacks-tile-heroes";
    for (const heroId of tile.heroesHere) {
      const hero = heroesById[heroId];
      const chip = document.createElement("span");
      chip.className = "stacks-tile-hero-chip";
      if (hero && hero.token) chip.appendChild(renderToken(hero.token, { size: "sm" }));
      const name = document.createElement("span");
      name.className = "stacks-tile-hero-chip-name";
      name.textContent = hero ? `${hero.name} (${hero.danger.label}${hero.inCombat ? ", in combat" : ""})` : heroId;
      chip.appendChild(name);
      heroes.appendChild(chip);
    }
    el.appendChild(heroes);
  }

  const connectors = document.createElement("div");
  connectors.className = "stacks-tile-connectors";
  for (const connector of tile.connectors) {
    const canBreach = isCurrentRoom && connector.state === "undiscovered" && legalBreachDirections.includes(connector.direction);
    const canObserve = isCurrentRoom && connector.state === "open" && legalObserveDirections.includes(connector.direction);
    if (canBreach && typeof onRequestBreach === "function") {
      connectors.appendChild(renderConnector(connector, { interactive: true, onActivate: onRequestBreach, costLabel: `${breachCostFor(connector.direction)} Energy` }));
    } else if (canObserve && typeof onObserve === "function") {
      connectors.appendChild(renderConnector(connector, { interactive: true, onActivate: onObserve }));
    } else {
      connectors.appendChild(renderConnector(connector, { interactive: false }));
    }
  }
  el.appendChild(connectors);

  return el;
}
