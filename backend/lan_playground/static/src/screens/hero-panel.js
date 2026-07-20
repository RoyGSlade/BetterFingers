// Hand/deck + inventory panel (infinite_stacks.md S13.2, S13.6, S21.3
// "their hero, Energy, hand, equipment"). Rendered inside the map screen's
// sidebar (main.js appends it after the You panel) rather than as a
// separate screen, since it is relevant on every non-combat, non-puzzle
// view. Receives state+handlers and only builds DOM -- main.js is the sole
// place that wires network/store/timers together.

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

// Cards targeting "self" (or only room-scoped) play immediately; cards that
// can target an ally or an enemy get an inline target picker first so
// play_card's target_hero_id/target_enemy_id is always a real id, never
// guessed. Enemy targets are only offered while the hero is in a live
// conflict encounter (state.conflicts[roomId]).
function renderHandCard(card, allies, enemies, handlers) {
  const needsTarget = card.targets.includes("ally") || card.targets.includes("enemy");
  if (!needsTarget) {
    return renderCard(card, { playable: true, onPlay: () => handlers.onPlayCard(card.id, {}) });
  }

  const wrap = el("div", "stacks-hand-card-with-target");
  wrap.appendChild(renderCard(card, { playable: false }));

  const canTargetAlly = card.targets.includes("ally") && allies.length > 0;
  const canTargetEnemy = card.targets.includes("enemy") && enemies.length > 0;
  let allyField = null;
  let enemyField = null;
  if (canTargetAlly) {
    allyField = buildTargetSelect(
      `stacks-hand-ally-target-${card.id}`,
      "Ally target",
      allies.map((h) => ({ value: h.hero_id, label: h.name })),
    );
    wrap.appendChild(allyField.wrap);
  }
  if (canTargetEnemy) {
    enemyField = buildTargetSelect(
      `stacks-hand-enemy-target-${card.id}`,
      "Enemy target",
      enemies.map((e) => ({ value: e.id, label: e.name })),
    );
    wrap.appendChild(enemyField.wrap);
  }

  const button = el("button", "stacks-hand-play-targeted-button", "Play");
  button.type = "button";
  button.disabled = !canTargetAlly && !canTargetEnemy;
  button.addEventListener("click", () => {
    handlers.onPlayCard(card.id, {
      targetHeroId: allyField ? allyField.select.value : null,
      targetEnemyId: enemyField ? enemyField.select.value : null,
    });
  });
  wrap.appendChild(button);
  return wrap;
}

function renderHandSection(state, handlers) {
  const hand = selectHandView(state);
  const panel = el("section", "stacks-hand-panel");
  panel.setAttribute("aria-label", "Hand and deck");
  panel.appendChild(el("h2", "stacks-panel-heading", "Hand"));
  if (!hand) {
    panel.appendChild(el("p", null, "No deck yet."));
    return panel;
  }

  const you = selectYouHero(state);
  const roomId = you ? you.room_id : null;
  const conflict = roomId ? state.conflicts[roomId] : null;
  const allies = Object.values(state.heroes).filter((h) => h.room_id === roomId && h.hero_id !== (you ? you.hero_id : null));
  const enemies = conflict
    ? Object.entries(conflict.enemies || {})
        .filter(([, e]) => e.alive)
        .map(([id, e]) => ({ id, name: e.name }))
    : [];

  if (hand.hand) {
    const list = el("div", "stacks-hand-card-list");
    for (const card of hand.hand) list.appendChild(renderHandCard(card, allies, enemies, handlers));
    panel.appendChild(list);
  } else {
    panel.appendChild(el("p", null, "Hand not loaded."));
  }

  const counts = el("dl", "stacks-hand-pile-counts");
  function addFact(term, value) {
    counts.appendChild(el("dt", null, term));
    counts.appendChild(el("dd", null, String(value)));
  }
  addFact("Deck", hand.deckCount);
  addFact("Discard", hand.discardCount);
  addFact("Exhausted", hand.exhaustedCount);
  panel.appendChild(counts);

  const drawButton = el("button", "stacks-hand-draw-button", "Draw a card");
  drawButton.type = "button";
  drawButton.disabled = hand.deckCount <= 0;
  drawButton.addEventListener("click", () => handlers.onDrawCards(1));
  panel.appendChild(drawButton);

  const restButton = el("button", "stacks-hand-safe-rest-button", "Safe rest");
  restButton.type = "button";
  restButton.addEventListener("click", () => handlers.onSafeRest());
  panel.appendChild(restButton);

  return panel;
}

function renderInventorySection(state, handlers) {
  const inventory = selectInventoryView(state);
  const panel = el("section", "stacks-inventory-panel");
  panel.setAttribute("aria-label", "Inventory");
  panel.appendChild(el("h2", "stacks-panel-heading", "Inventory"));
  if (!inventory) {
    panel.appendChild(el("p", null, "No inventory yet."));
    return panel;
  }

  panel.appendChild(el("p", "stacks-inventory-slots", `Slots used: ${inventory.usedSlots} / ${inventory.totalSlots}`));

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
  panel.appendChild(carriedList);

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
    panel.appendChild(groundPanel);
  }

  if (inventory.recoverableBodies.length) {
    const bodyPanel = el("div", "stacks-inventory-bodies");
    bodyPanel.appendChild(el("h3", "stacks-panel-heading", "Recoverable body loot"));
    for (const body of inventory.recoverableBodies) {
      const row = el("div", "stacks-inventory-body");
      const button = el(
        "button",
        "stacks-inventory-recover-button",
        `Recover ${body.itemIds.length} item(s) from ${body.deadHeroId}`,
      );
      button.type = "button";
      button.addEventListener("click", () => handlers.onRecoverBodyLoot(body.deadHeroId, body.itemIds));
      row.appendChild(button);
      bodyPanel.appendChild(row);
    }
    panel.appendChild(bodyPanel);
  }

  return panel;
}

export function renderHeroPanel(container, state, handlers) {
  container.appendChild(renderHandSection(state, handlers));
  container.appendChild(renderInventorySection(state, handlers));
}
