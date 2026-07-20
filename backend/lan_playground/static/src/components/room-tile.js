// One map tile (infinite_stacks.md S24.1): fog of war without a false
// boundary, connector states (open/locked/undiscovered/none/unstable/
// secret-discovered/one-way) with a text label alongside the glyph so
// nothing is color-only, and hero portraits showing danger state. Pure DOM
// construction from the plain data selectors.selectTiles() already computed
// -- no network, no store access, no timers.

function renderConnector(connector, { interactive, onActivate } = {}) {
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
  label.textContent = `${connector.direction}: ${connector.label}`;
  el.appendChild(label);
  return el;
}

export function renderRoomTile(
  tile,
  {
    heroesById = {},
    isCurrentRoom = false,
    canMoveHere = false,
    onMove,
    isRoutePreview = false,
    legalBreachDirections = [],
    onBreach,
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

  const interactive = canMoveHere && typeof onMove === "function" && !isCurrentRoom;
  const el = document.createElement(interactive ? "button" : "div");
  el.className =
    "stacks-tile stacks-tile--room" +
    (isCurrentRoom ? " is-current" : "") +
    (isRoutePreview ? " is-route-preview" : "") +
    (tile.required ? " is-required" : "");
  el.dataset.roomId = tile.roomId;
  if (interactive) {
    el.type = "button";
    el.setAttribute("aria-label", `Move to ${tile.familyLabel} room`);
    el.addEventListener("click", () => onMove(tile.roomId));
  }

  const heading = document.createElement("div");
  heading.className = "stacks-tile-heading";
  heading.textContent = tile.familyLabel + (isCurrentRoom ? " (here)" : "");
  el.appendChild(heading);

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
      chip.textContent = hero ? `${hero.name} (${hero.danger.label}${hero.inCombat ? ", in combat" : ""})` : heroId;
      heroes.appendChild(chip);
    }
    el.appendChild(heroes);
  }

  const connectors = document.createElement("div");
  connectors.className = "stacks-tile-connectors";
  for (const connector of tile.connectors) {
    const canBreach = isCurrentRoom && connector.state === "undiscovered" && legalBreachDirections.includes(connector.direction);
    const canObserve = isCurrentRoom && connector.state === "open" && legalObserveDirections.includes(connector.direction);
    if (canBreach && typeof onBreach === "function") {
      connectors.appendChild(renderConnector(connector, { interactive: true, onActivate: onBreach }));
    } else if (canObserve && typeof onObserve === "function") {
      connectors.appendChild(renderConnector(connector, { interactive: true, onActivate: onObserve }));
    } else {
      connectors.appendChild(renderConnector(connector, { interactive: false }));
    }
  }
  el.appendChild(connectors);

  return el;
}
