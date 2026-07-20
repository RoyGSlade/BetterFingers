// The shared map screen (infinite_stacks.md S21.3/S24.1): full discovered
// map with fog of war, hero locations and danger, connector states, and a
// route preview to a selected ally. This function receives state and a
// small handlers object and only ever builds/replaces DOM -- it never calls
// fetch/WebSocket, never mutates the store, and never starts a timer.
// main.js owns the network/store glue and passes handlers in.

import {
  selectTiles,
  selectHeroCards,
  selectYouHero,
  selectDieDisplay,
  selectRoutePreview,
  selectLegalActionsSummary,
  selectLastError,
  energyPips,
} from "../core/selectors.js";
import { renderHeroCard } from "../components/hero.js";
import { renderDie } from "../components/die.js";
import { renderRoomTile } from "../components/room-tile.js";
import { renderHeroPanel } from "./hero-panel.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderStatusBar(state) {
  const bar = el("div", "stacks-status-bar");
  bar.appendChild(el("span", "stacks-status-connection stacks-status-connection--" + state.connection, `Connection: ${state.connection}`));
  bar.appendChild(el("span", "stacks-status-round", `World round ${state.worldRound}`));
  bar.appendChild(el("span", "stacks-status-rooms", `Rooms: ${Object.keys(state.rooms).length} discovered (need ${state.requiredRooms}, max ${state.maximumRooms})`));
  return bar;
}

function renderRoster(state, handlers) {
  const heroCards = selectHeroCards(state);
  const panel = el("section", "stacks-roster");
  panel.setAttribute("aria-label", "Party roster");
  panel.appendChild(el("h2", "stacks-panel-heading", "Party"));
  const list = el("div", "stacks-roster-list");
  for (const heroCard of heroCards) {
    list.appendChild(
      renderHeroCard(heroCard, {
        onSelect: heroCard.isYou ? undefined : handlers.onSelectAlly,
        selected: heroCard.heroId === state.selectedAllyId,
      }),
    );
  }
  panel.appendChild(list);

  if (state.selectedAllyId && state.selectedAllyId !== state.you.heroId) {
    const you = selectYouHero(state);
    const ally = state.heroes[state.selectedAllyId];
    if (you && ally) {
      const route = selectRoutePreview(state, you.room_id, ally.room_id);
      const preview = el("p", "stacks-route-preview");
      preview.setAttribute("role", "status");
      preview.textContent = route
        ? `Route to ${ally.name}: ${route.roomIds.length} room(s), arriving in ${route.arrivalRounds} move(s).`
        : `No currently-discovered open route to ${ally.name} yet.`;
      panel.appendChild(preview);
    }
  }
  return panel;
}

// Grid placement uses pre-generated `stacks-col-N`/`stacks-row-N` utility
// classes (stacks.css) rather than inline `style.gridColumn`/`gridRow`
// assignment, so the map keeps working under a strict `style-src 'self'`
// CSP (no 'unsafe-inline') -- the same policy stacks_api.py's
// _PolicyMiddleware applies to every response. MAX_GRID_SPAN comfortably
// covers the wave-1 room cap (maximum_rooms <= 15, infinite_stacks.md S7.3).
const MAX_GRID_SPAN = 24;

function clampSpan(n) {
  return Math.max(1, Math.min(MAX_GRID_SPAN, n));
}

function renderMapGrid(state, handlers) {
  const tiles = selectTiles(state);
  const you = selectYouHero(state);
  const legalActions = selectLegalActionsSummary(state) || {};
  const heroCards = selectHeroCards(state);
  const heroesById = Object.fromEntries(heroCards.map((h) => [h.heroId, h]));

  const ally = state.selectedAllyId ? state.heroes[state.selectedAllyId] : null;
  const route = you && ally ? selectRoutePreview(state, you.room_id, ally.room_id) : null;
  const routeRoomIds = new Set(route ? route.roomIds : []);

  const minX = Math.min(0, ...tiles.map((t) => t.x));
  const maxX = Math.max(0, ...tiles.map((t) => t.x));
  const minY = Math.min(0, ...tiles.map((t) => t.y));
  const maxY = Math.max(0, ...tiles.map((t) => t.y));

  const grid = el("div", "stacks-map-grid");
  grid.setAttribute("role", "grid");
  grid.setAttribute("aria-label", "Discovered map, fog of war hides unexplored rooms");
  grid.classList.add(`stacks-cols-${clampSpan(maxX - minX + 1)}`);
  grid.classList.add(`stacks-rows-${clampSpan(maxY - minY + 1)}`);

  for (const tile of tiles) {
    const node = renderRoomTile(tile, {
      heroesById,
      isCurrentRoom: !!you && tile.roomId === you.room_id,
      canMoveHere: (legalActions.can_move_to || []).includes(tile.roomId),
      onMove: handlers.onMove,
      isRoutePreview: routeRoomIds.has(tile.roomId),
      legalBreachDirections: legalActions.can_breach_directions || [],
      onBreach: handlers.onBreach,
      legalObserveDirections: legalActions.can_observe_directions || [],
      onObserve: handlers.onObserve,
    });
    node.classList.add(`stacks-col-${clampSpan(tile.x - minX + 1)}`);
    node.classList.add(`stacks-row-${clampSpan(maxY - tile.y + 1)}`);
    grid.appendChild(node);
  }
  return grid;
}

function renderYouPanel(state, handlers) {
  const you = selectYouHero(state);
  const panel = el("section", "stacks-you-panel");
  panel.setAttribute("aria-label", "Your hero");
  panel.appendChild(el("h2", "stacks-panel-heading", "You"));
  if (!you) {
    panel.appendChild(el("p", null, "Not yet joined."));
    return panel;
  }

  const energy = el("div", "stacks-hero-card-energy");
  energy.setAttribute("role", "img");
  const pips = energyPips(you);
  const filled = pips.filter(Boolean).length;
  energy.setAttribute("aria-label", `Energy ${filled} of ${pips.length}`);
  for (const isFilled of pips) {
    const pip = el("span", "stacks-energy-pip" + (isFilled ? " is-filled" : ""), isFilled ? "●" : "○");
    pip.setAttribute("aria-hidden", "true");
    energy.appendChild(pip);
  }
  panel.appendChild(energy);

  const legalActions = selectLegalActionsSummary(state) || {};
  const actions = el("div", "stacks-you-actions");
  const inspectBtn = el("button", "stacks-action-button", "Inspect");
  inspectBtn.type = "button";
  inspectBtn.disabled = !legalActions.can_inspect;
  inspectBtn.addEventListener("click", () => handlers.onInspect());
  actions.appendChild(inspectBtn);

  const passBtn = el("button", "stacks-action-button", "Pass");
  passBtn.type = "button";
  passBtn.disabled = !legalActions.can_pass;
  passBtn.addEventListener("click", () => handlers.onPass());
  actions.appendChild(passBtn);
  panel.appendChild(actions);

  if (state.privateClue) {
    const clue = el("div", "stacks-private-clue");
    clue.setAttribute("role", "note");
    clue.appendChild(el("h3", "stacks-panel-heading", "Private clue (only you can see this)"));
    clue.appendChild(el("p", null, state.privateClue));
    panel.appendChild(clue);
  }

  return panel;
}

function renderDiePanel(state) {
  const panel = el("section", "stacks-die-panel");
  panel.setAttribute("aria-label", "Last die roll");
  panel.appendChild(renderDie(selectDieDisplay(state), { reducedMotion: state.reducedMotion }));
  return panel;
}

function renderErrorPanel(state) {
  const error = selectLastError(state);
  if (!error) return null;
  const panel = el("div", "stacks-error-panel");
  panel.setAttribute("role", "alert");
  panel.appendChild(el("p", null, `Action not applied: ${error.code}${error.message ? " - " + error.message : ""}`));
  return panel;
}

function renderLog(state) {
  const panel = el("section", "stacks-log-panel");
  panel.setAttribute("aria-label", "Recent events");
  panel.appendChild(el("h2", "stacks-panel-heading", "Recent events"));
  const list = el("ul", "stacks-log-list");
  list.setAttribute("role", "log");
  list.setAttribute("aria-live", "polite");
  for (const entry of state.log.slice(-10)) {
    list.appendChild(el("li", null, `[round ${entry.worldRound}] ${entry.type}${entry.actorHeroId ? " (" + entry.actorHeroId + ")" : ""}`));
  }
  panel.appendChild(list);
  return panel;
}

// Rebuilds the whole screen from scratch on every call. Simple and correct
// for the golden-floor slice's data size; main.js calls this once per store
// change via store.subscribe.
export function renderMapScreen(container, state, handlers) {
  container.replaceChildren();
  container.appendChild(renderStatusBar(state));
  const errorPanel = renderErrorPanel(state);
  if (errorPanel) container.appendChild(errorPanel);

  const layout = el("div", "stacks-map-layout");
  layout.appendChild(renderRoster(state, handlers));
  layout.appendChild(renderMapGrid(state, handlers));

  const sidebar = el("div", "stacks-map-sidebar");
  sidebar.appendChild(renderYouPanel(state, handlers));
  renderHeroPanel(sidebar, state, handlers);
  sidebar.appendChild(renderDiePanel(state));
  sidebar.appendChild(renderLog(state));
  layout.appendChild(sidebar);

  container.appendChild(layout);
}
