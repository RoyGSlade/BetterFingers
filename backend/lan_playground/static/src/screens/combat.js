// Combat screen (infinite_stacks.md S14, S24.3): enemy intent is rendered
// before any action-selection controls; legal targets and expected base
// effects are visible; a called maneuver's -4 accuracy cost is shown before
// confirmation; initiative order and reaction availability stay visible;
// and the S12.5 factual check receipt is rendered before any narration text
// (this screen never renders narration itself -- callers append it only
// after the receipt). Receives state+handlers and only builds DOM; main.js
// is the sole place that wires network/store/timers together.

import { selectCombatView } from "../core/selectors.js";
import { renderStatusList } from "../components/status.js";
import { renderCheckReceipt } from "../components/check-receipt.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderInitiativeOrder(combat) {
  const panel = el("section", "stacks-combat-initiative");
  panel.setAttribute("aria-label", "Initiative order");
  panel.appendChild(el("h2", "stacks-panel-heading", `Round ${combat.round}`));
  const list = el("ol", "stacks-combat-initiative-list");
  for (const combatant of combat.initiativeOrder) {
    const item = el(
      "li",
      "stacks-combat-initiative-item" + (combatant.isCurrentTurn ? " is-current-turn" : ""),
    );
    item.appendChild(el("span", "stacks-combat-initiative-name", combatant.name + (combatant.isCurrentTurn ? " (acting)" : "")));
    item.appendChild(el("span", "stacks-combat-initiative-value", `Initiative ${combatant.initiative}`));
    item.appendChild(
      el(
        "span",
        "stacks-combat-initiative-reaction",
        combatant.hasReactionAvailable ? "Reaction available" : "Reaction used",
      ),
    );
    list.appendChild(item);
  }
  panel.appendChild(list);
  return panel;
}

// Enemy intent is the first thing this screen renders after initiative --
// it must appear before any action-selection control (S24.3).
function renderEnemyIntents(combat) {
  const panel = el("section", "stacks-combat-enemies");
  panel.setAttribute("aria-label", "Enemies and their telegraphed intent");
  panel.appendChild(el("h2", "stacks-panel-heading", "Enemies"));
  const list = el("div", "stacks-combat-enemy-list");
  for (const enemy of combat.enemies) {
    const card = el("div", "stacks-combat-enemy-card");
    card.dataset.enemyId = enemy.id;
    card.appendChild(el("h3", "stacks-combat-enemy-name", enemy.name));
    const hp = el("p", "stacks-combat-enemy-hp");
    hp.setAttribute("aria-label", `${enemy.name} HP ${enemy.hp} of ${enemy.maxHp}`);
    hp.textContent = `HP ${enemy.hp} / ${enemy.maxHp}`;
    card.appendChild(hp);

    const intent = el("p", "stacks-combat-enemy-intent");
    intent.setAttribute("role", "status");
    const glyph = el("span", "stacks-combat-enemy-intent-glyph", enemy.intent.glyph || "!");
    glyph.setAttribute("aria-hidden", "true");
    intent.appendChild(glyph);
    intent.appendChild(el("span", "stacks-combat-enemy-intent-label", ` Intent: ${enemy.intent.label} — ${enemy.intent.description}`));
    card.appendChild(intent);

    if (enemy.statuses && enemy.statuses.length) card.appendChild(renderStatusList(enemy.statuses));
    list.appendChild(card);
  }
  panel.appendChild(list);
  return panel;
}

function renderHeroes(combat) {
  const panel = el("section", "stacks-combat-heroes");
  panel.setAttribute("aria-label", "Party in combat");
  panel.appendChild(el("h2", "stacks-panel-heading", "Party"));
  const list = el("div", "stacks-combat-hero-list");
  for (const hero of combat.heroes) {
    const card = el("div", "stacks-combat-hero-card");
    card.dataset.heroId = hero.id;
    card.appendChild(el("h3", "stacks-combat-hero-name", hero.name));
    const hp = el("p", "stacks-combat-hero-hp");
    hp.setAttribute("aria-label", `${hero.name} HP ${hero.hp} of ${hero.maxHp}`);
    hp.textContent = `HP ${hero.hp} / ${hero.maxHp}`;
    card.appendChild(hp);
    card.appendChild(el("p", "stacks-combat-hero-reaction", hero.reactionAvailable ? "Reaction available" : "Reaction used"));
    if (hero.statuses && hero.statuses.length) card.appendChild(renderStatusList(hero.statuses));
    list.appendChild(card);
  }
  panel.appendChild(list);
  return panel;
}

// Legal targets and expected base effects are visible on every attack
// button before it is chosen (S24.3).
function renderAttacks(combat, handlers) {
  const panel = el("section", "stacks-combat-attacks");
  panel.setAttribute("aria-label", "Legal attacks");
  panel.appendChild(el("h2", "stacks-panel-heading", "Attack"));
  const list = el("div", "stacks-combat-attacks-list");
  for (const attack of combat.legalActions.attacks) {
    const button = el("button", "stacks-combat-attack-button");
    button.type = "button";
    const label = el("span", "stacks-combat-attack-label", `${attack.label} → ${attack.targetLabel}`);
    button.appendChild(label);
    const effect = el("span", "stacks-combat-attack-effect", attack.expectedEffect);
    button.appendChild(effect);
    button.addEventListener("click", () => handlers.onAttack(attack.id, attack.targetId));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

// A called maneuver's -4 accuracy is shown on the button itself, before
// confirmation (S14.4/S24.3 "called-maneuver accuracy cost is shown before
// confirmation").
function renderManeuvers(combat, handlers) {
  const panel = el("section", "stacks-combat-maneuvers");
  panel.setAttribute("aria-label", "Called maneuvers");
  panel.appendChild(el("h2", "stacks-panel-heading", "Called maneuver"));
  const list = el("div", "stacks-combat-maneuvers-list");
  for (const maneuver of combat.legalActions.maneuvers) {
    const button = el("button", "stacks-combat-maneuver-button");
    button.type = "button";
    const label = el(
      "span",
      "stacks-combat-maneuver-label",
      `${maneuver.label} → ${maneuver.targetLabel} (${maneuver.accuracyModifier} accuracy)`,
    );
    button.appendChild(label);
    const effect = el("span", "stacks-combat-maneuver-effect", maneuver.expectedEffect);
    button.appendChild(effect);
    button.setAttribute(
      "aria-label",
      `${maneuver.label} on ${maneuver.targetLabel}, ${maneuver.accuracyModifier} accuracy, ${maneuver.expectedEffect}. Requires confirmation.`,
    );
    button.addEventListener("click", () => handlers.onDeclareManeuver(maneuver.id, maneuver.targetId));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

function renderReactions(combat, handlers) {
  const panel = el("section", "stacks-combat-reactions");
  panel.setAttribute("aria-label", "Reactions");
  panel.appendChild(el("h2", "stacks-panel-heading", "Reaction"));
  const list = el("div", "stacks-combat-reactions-list");
  for (const reaction of combat.legalActions.reactions) {
    const button = el("button", "stacks-combat-reaction-button", reaction.label);
    button.type = "button";
    button.disabled = !reaction.available;
    button.setAttribute("aria-label", reaction.available ? `React with ${reaction.label}` : `${reaction.label} (already used this round)`);
    button.addEventListener("click", () => handlers.onReact(reaction.id));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

// The S12.5 factual check receipt always renders before any narration --
// this screen renders only the receipt, never narration text.
function renderLastCheckReceipt(combat) {
  if (!combat.lastCheckReceipt) return null;
  return renderCheckReceipt(combat.lastCheckReceipt);
}

export function renderCombatScreen(container, state, handlers) {
  const combat = selectCombatView(state);
  container.replaceChildren();
  if (!combat) return;

  container.appendChild(renderInitiativeOrder(combat));
  container.appendChild(renderEnemyIntents(combat));
  container.appendChild(renderHeroes(combat));

  const receipt = renderLastCheckReceipt(combat);
  if (receipt) container.appendChild(receipt);

  const actions = el("div", "stacks-combat-actions");
  actions.appendChild(renderAttacks(combat, handlers));
  actions.appendChild(renderManeuvers(combat, handlers));
  actions.appendChild(renderReactions(combat, handlers));
  container.appendChild(actions);
}
