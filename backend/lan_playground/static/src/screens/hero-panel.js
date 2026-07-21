// Hand + inventory (infinite_stacks.md S13.2, S13.6; playtest A1/A2/A3/A4/D2).
// Two independently-mounted pieces, each receiving state+handlers and only
// building DOM (main.js wires network/store/timers):
//   renderHandDock   -- the center-bottom hand dock (A1). Cards are inspect-
//     first (A4): clicking a card only expands it; a separate "Play card"
//     button inside the expansion stages a pendingAction via
//     handlers.onRequestPlayCard, never sends a command directly.
//   renderInventoryPanel -- a visual slot grid (D2) followed by the existing
//     functional drop/trade/pickup/recover controls, mounted inside the
//     persistent character panel (screens/character-panel.js).

import { selectHandView, selectInventoryView, selectYouHero } from "../core/selectors.js";
import { renderCard } from "../components/card.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function buildTargetSelect(id, labelText, options) {
  const wrap = el("div", "stacks-hand-target-field");
  const label = document.createElement("label");
  label.setAttribute("for", id);
  label.textContent = labelText;
  wrap.appendChild(label);
  const select = document.createElement("select");
  select.id = id;
  for (const option of options) {
    const optionEl = document.createElement("option");
    optionEl.value = option.value;
    optionEl.textContent = option.label;
    select.appendChild(optionEl);
  }
  wrap.appendChild(select);
  return { wrap, select };
}

// A4: shown only while a card is inspected/expanded. Builds whatever target
// picker(s) the card actually needs, and the one "Play card" button that
// stages the pendingAction the confirm bar (components/confirm-dialog.js)
// commits -- this function itself never calls sendCommand.
function renderExpandedPlayControls(card, allies, enemies, handlers) {
  const wrap = el("div", "stacks-hand-card-play-controls");

  const needsAllyTarget = card.targets.includes("ally") && !card.targets.includes("self");
  const needsEnemyTarget = card.targets.includes("enemy");
  let allyField = null;
  let enemyField = null;
  if (needsAllyTarget && allies.length) {
    allyField = buildTargetSelect(
      `stacks-hand-ally-target-${card.id}`,
      "Ally target",
      allies.map((h) => ({ value: h.hero_id, label: h.name })),
    );
    wrap.appendChild(allyField.wrap);
  }
  if (needsEnemyTarget && enemies.length) {
    enemyField = buildTargetSelect(
      `stacks-hand-enemy-target-${card.id}`,
      "Enemy target",
      enemies.map((e) => ({ value: e.id, label: e.name })),
    );
    wrap.appendChild(enemyField.wrap);
  }

  const missingRequiredTarget = (needsAllyTarget && allies.length === 0) || (needsEnemyTarget && enemies.length === 0);
  const playButton = el("button", "stacks-hand-play-button", "Play card");
  playButton.type = "button";
  playButton.disabled = card.playableNow === false || missingRequiredTarget;
  playButton.addEventListener("click", () => {
    handlers.onRequestPlayCard(card, {
      targetHeroId: allyField ? allyField.select.value : null,
      targetEnemyId: enemyField ? enemyField.select.value : null,
    });
  });
  wrap.appendChild(playButton);
  return wrap;
}

// A1: rendered into the persistent #hand-dock element (center-bottom of the
// viewport, stacks.css), mounted by main.js on every screen where the hero
// has a hand -- the standard card-game hand position the playtest asked for,
// replacing the old sidebar placement.
export function renderHandDock(container, state, handlers) {
  container.replaceChildren();
  const hand = selectHandView(state);
  if (!hand) {
    container.hidden = true;
    return;
  }
  container.hidden = false;

  const heading = el("h2", "sr-only", "Your hand");
  container.appendChild(heading);

  const you = selectYouHero(state);
  const roomId = you ? you.room_id : null;
  const conflict = roomId ? state.conflicts[roomId] : null;
  const allies = Object.values(state.heroes).filter((h) => h.room_id === roomId && h.hero_id !== (you ? you.hero_id : null));
  const enemies = conflict
    ? Object.entries(conflict.enemies || {})
        .filter(([, e]) => e.alive)
        .map(([id, e]) => ({ id, name: e.name }))
    : [];

  const list = el("div", "stacks-hand-dock-list");
  if (hand.hand) {
    for (const card of hand.hand) {
      const inspected = state.inspectedCardId === card.id;
      const expandedContent = inspected ? renderExpandedPlayControls(card, allies, enemies, handlers) : null;
      list.appendChild(
        renderCard(card, {
          onInspect: handlers.onInspectCard,
          inspected,
          expandedContent,
          playable: true,
        }),
      );
    }
  } else {
    list.appendChild(el("p", null, "Hand not loaded."));
  }
  container.appendChild(list);

  const counts = el("dl", "stacks-hand-pile-counts");
  function addFact(term, value) {
    counts.appendChild(el("dt", null, term));
    counts.appendChild(el("dd", null, String(value)));
  }
  addFact("Deck", hand.deckCount);
  addFact("Discard", hand.discardCount);
  addFact("Exhausted", hand.exhaustedCount);
  container.appendChild(counts);

  const drawButton = el("button", "stacks-hand-draw-button", "Draw a card");
  drawButton.type = "button";
  drawButton.disabled = hand.deckCount <= 0;
  drawButton.addEventListener("click", () => handlers.onDrawCards(1));
  container.appendChild(drawButton);

  const restButton = el("button", "stacks-hand-safe-rest-button", "Safe rest");
  restButton.type = "button";
  restButton.addEventListener("click", () => handlers.onSafeRest());
  container.appendChild(restButton);
}

// D2: a visual slot grid (one cell per carry slot, using the existing
// stacks-col-N utility classes so it stays CSP-safe) ahead of the same
// functional drop/trade/pickup/recover controls the sidebar used to render.
function renderInventoryGrid(inventory) {
  const totalSlots = Math.max(1, Math.min(24, inventory.totalSlots || 1));
  const grid = el("div", `stacks-inventory-grid stacks-cols-${totalSlots}`);
  grid.setAttribute("role", "list");
  grid.setAttribute("aria-label", "Inventory slots");

  let used = 0;
  for (const item of inventory.carried) {
    const cell = el("span", "stacks-inventory-slot stacks-inventory-slot--filled", item.name);
    cell.setAttribute("role", "listitem");
    cell.setAttribute("aria-label", `${item.name}, ${item.slotCost} slot${item.slotCost === 1 ? "" : "s"}`);
    grid.appendChild(cell);
    used += 1;
    for (let i = 1; i < item.slotCost; i += 1) {
      const continuation = el("span", "stacks-inventory-slot stacks-inventory-slot--continuation");
      continuation.setAttribute("aria-hidden", "true");
      grid.appendChild(continuation);
      used += 1;
    }
  }
  for (let i = used; i < inventory.totalSlots; i += 1) {
    const empty = el("span", "stacks-inventory-slot stacks-inventory-slot--empty");
    empty.setAttribute("role", "listitem");
    empty.setAttribute("aria-label", "Empty slot");
    grid.appendChild(empty);
  }
  return grid;
}

export function renderInventoryPanel(container, state, handlers) {
  container.replaceChildren();
  const inventory = selectInventoryView(state);
  if (!inventory) {
    container.appendChild(el("p", null, "No inventory yet."));
    return;
  }

  container.appendChild(el("p", "stacks-inventory-slots", `Slots used: ${inventory.usedSlots} / ${inventory.totalSlots}`));
  container.appendChild(renderInventoryGrid(inventory));

  const carriedList = el("ul", "stacks-inventory-carried-list");
  for (const item of inventory.carried) {
    const row = el("li", "stacks-inventory-carried-item");
    row.appendChild(el("span", "stacks-inventory-item-name", `${item.name} (${item.slotCost} slot${item.slotCost === 1 ? "" : "s"})`));
    const dropButton = el("button", "stacks-inventory-drop-button", "Drop");
    dropButton.type = "button";
    dropButton.addEventListener("click", () => handlers.onDropItem(item.itemId));
    row.appendChild(dropButton);
    if (inventory.otherHeroesHere.length) {
      const tradeSelect = buildTargetSelect(
        `stacks-inventory-trade-target-${item.itemId}`,
        "Trade with",
        inventory.otherHeroesHere.map((h) => ({ value: h.hero_id, label: h.name })),
      );
      row.appendChild(tradeSelect.wrap);
      const tradeButton = el("button", "stacks-inventory-trade-button", "Trade");
      tradeButton.type = "button";
      tradeButton.addEventListener("click", () => handlers.onTradeItem(tradeSelect.select.value, item.itemId));
      row.appendChild(tradeButton);
    }
    carriedList.appendChild(row);
  }
  container.appendChild(carriedList);

  if (inventory.groundItems.length) {
    const groundPanel = el("div", "stacks-inventory-ground");
    groundPanel.appendChild(el("h3", "stacks-panel-heading", "On the ground"));
    for (const item of inventory.groundItems) {
      const row = el("div", "stacks-inventory-ground-item");
      const claimed = item.claimedByHeroId ? ` (claimed)` : "";
      const button = el("button", "stacks-inventory-pickup-button", `Pick up ${item.name}${claimed}`);
      button.type = "button";
      button.addEventListener("click", () => handlers.onPickupItem(item.instanceId));
      row.appendChild(button);
      groundPanel.appendChild(row);
    }
    container.appendChild(groundPanel);
  }

  if (inventory.recoverableBodies.length) {
    const bodyPanel = el("div", "stacks-inventory-bodies");
    bodyPanel.appendChild(el("h3", "stacks-panel-heading", "Recoverable body loot"));
    for (const body of inventory.recoverableBodies) {
      const row = el("div", "stacks-inventory-body");
      const button = el("button", "stacks-inventory-recover-button", `Recover ${body.itemIds.length} item(s) from ${body.deadHeroId}`);
      button.type = "button";
      button.addEventListener("click", () => handlers.onRecoverBodyLoot(body.deadHeroId, body.itemIds));
      row.appendChild(button);
      bodyPanel.appendChild(row);
    }
    container.appendChild(bodyPanel);
  }
}
