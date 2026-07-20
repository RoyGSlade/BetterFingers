// Combat screen (infinite_stacks.md S14, S24.3): enemy intent is rendered
// before any action-selection controls; a called maneuver's -4 accuracy cost
// is shown before confirmation; initiative order and reaction availability
// stay visible; and the S12.5 factual check receipt is rendered before any
// narration text (this screen never renders narration itself -- callers
// append it only after the receipt). Receives state+handlers and only builds
// DOM; main.js is the sole place that wires network/store/timers together.
//
// core/selectors.js's selectCombatView is the wire shape stacks-conflict
// posted 17:15 (EARLY DRAFT, board task #9): the "conflict" projection has
// no legal-attacks/legal-maneuvers catalog (unlike the wave-2 fixture's
// guess) because per-hero weapon/skill data isn't wired into domain until
// wave 4's heroes lane lands -- so attacks/maneuvers/reactions here are a
// generic form (target + attribute + skill/maneuver/reaction choice) built
// against the CONFIRMED command payload shapes (combat_attack {target_id,
// attribute, skill}, combat_maneuver {maneuver, target_id, attribute,
// skill}, combat_reaction {reaction}), not a per-target enumerated button
// list. The four attributes (force/finesse/insight/presence) are confirmed
// in two independent places this session (heroes.creation.HeroSheet and the
// combat/models ATTRIBUTE_NAMES it copies); skill is freeform since no
// skill-name catalog has shipped anywhere yet.

import { selectCombatView } from "../core/selectors.js";
import { renderCheckReceipt } from "../components/check-receipt.js";

// infinite_stacks.md S14.4 / docs/INFINITE_STACKS_COMBAT.md: called
// maneuvers always cost exactly -4 accuracy -- a fixed rule, not per-target
// wire data (there is no accuracy_modifier field on the wire this wave).
const CALLED_MANEUVER_ACCURACY = -4;
const ATTRIBUTES = ["force", "finesse", "insight", "presence"];
const MANEUVERS = ["disarm", "trip", "drive_back", "break", "crushing_blow", "rattle"];
const REACTIONS = ["dodge", "block", "protect", "counter", "escape"];

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
    if (combatant.hasReactionAvailable !== null) {
      item.appendChild(
        el(
          "span",
          "stacks-combat-initiative-reaction",
          combatant.hasReactionAvailable ? "Reaction available" : "Reaction used",
        ),
      );
    }
    list.appendChild(item);
  }
  panel.appendChild(list);
  return panel;
}

// Enemy intent is the first thing this screen renders after initiative --
// it must appear before any action-selection control (S24.3). Intent text
// is folded client-side from intent_telegraphed combat events (core/store.js)
// and is only present once telegraphed this round.
function renderEnemyIntents(combat) {
  const panel = el("section", "stacks-combat-enemies");
  panel.setAttribute("aria-label", "Enemies and their telegraphed intent");
  panel.appendChild(el("h2", "stacks-panel-heading", "Enemies"));
  const list = el("div", "stacks-combat-enemy-list");
  for (const enemy of combat.enemies) {
    const card = el("div", "stacks-combat-enemy-card" + (enemy.alive ? "" : " is-defeated"));
    card.dataset.enemyId = enemy.id;
    card.appendChild(el("h3", "stacks-combat-enemy-name", enemy.name));
    const hp = el("p", "stacks-combat-enemy-hp");
    hp.setAttribute("aria-label", `${enemy.name} HP ${enemy.hp} of ${enemy.maxHp}`);
    hp.textContent = enemy.alive ? `HP ${enemy.hp} / ${enemy.maxHp}` : "Defeated";
    card.appendChild(hp);

    const intent = el("p", "stacks-combat-enemy-intent");
    intent.setAttribute("role", "status");
    if (enemy.intent) {
      const glyph = el("span", "stacks-combat-enemy-intent-glyph", "!");
      glyph.setAttribute("aria-hidden", "true");
      intent.appendChild(glyph);
      intent.appendChild(el("span", "stacks-combat-enemy-intent-label", ` Intent: ${enemy.intent.telegraphText}`));
      if (enemy.intent.counterplay) {
        card.appendChild(el("p", "stacks-combat-enemy-counterplay", `Counterplay: ${enemy.intent.counterplay}`));
      }
    } else {
      intent.appendChild(el("span", "stacks-combat-enemy-intent-label", "No intent telegraphed yet this round."));
    }
    card.appendChild(intent);

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
    const danger = el("p", `stacks-combat-hero-danger stacks-combat-hero-danger--${hero.danger.tier}`);
    const dangerGlyph = el("span", null, hero.danger.glyph || "");
    dangerGlyph.setAttribute("aria-hidden", "true");
    danger.appendChild(dangerGlyph);
    danger.appendChild(document.createTextNode(` ${hero.danger.label}`));
    card.appendChild(danger);
    card.appendChild(el("p", "stacks-combat-hero-reaction", hero.reactionAvailable ? "Reaction available" : "Reaction used"));
    list.appendChild(card);
  }
  panel.appendChild(list);
  return panel;
}

function buildSelect(id, labelText, options) {
  const wrap = el("div", "stacks-combat-form-field");
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

// Legal targets are visible (only living enemies); the -4 accuracy cost on a
// called maneuver is shown on its own control before confirmation (S14.4/
// S24.3), matching maneuver.accuracyModifier so it stays a labeled fact, not
// a hidden number.
function renderAttacks(combat, handlers) {
  const panel = el("section", "stacks-combat-attacks");
  panel.setAttribute("aria-label", "Attack");
  panel.appendChild(el("h2", "stacks-panel-heading", "Attack"));

  const targets = combat.enemies.filter((e) => e.alive);
  if (!targets.length) {
    panel.appendChild(el("p", null, "No living targets."));
    return panel;
  }
  if (!combat.isYourTurn) {
    panel.appendChild(el("p", null, "Not your turn."));
    return panel;
  }

  const targetField = buildSelect(
    "stacks-combat-attack-target",
    "Target",
    targets.map((e) => ({ value: e.id, label: e.name })),
  );
  const attributeField = buildSelect(
    "stacks-combat-attack-attribute",
    "Attribute",
    ATTRIBUTES.map((a) => ({ value: a, label: a })),
  );
  panel.appendChild(targetField.wrap);
  panel.appendChild(attributeField.wrap);

  const skillLabel = document.createElement("label");
  skillLabel.setAttribute("for", "stacks-combat-attack-skill");
  skillLabel.textContent = "Skill";
  panel.appendChild(skillLabel);
  const skillInput = document.createElement("input");
  skillInput.id = "stacks-combat-attack-skill";
  skillInput.type = "text";
  panel.appendChild(skillInput);

  const button = el("button", "stacks-combat-attack-button", "Attack");
  button.type = "button";
  button.addEventListener("click", () => {
    handlers.onAttack(targetField.select.value, attributeField.select.value, skillInput.value.trim());
  });
  panel.appendChild(button);
  return panel;
}

function renderManeuvers(combat, handlers) {
  const panel = el("section", "stacks-combat-maneuvers");
  panel.setAttribute("aria-label", "Called maneuvers");
  panel.appendChild(el("h2", "stacks-panel-heading", "Called maneuver"));

  const maneuverOptions = MANEUVERS.map((m) => ({ id: m, accuracyModifier: CALLED_MANEUVER_ACCURACY }));
  const targets = combat.enemies.filter((e) => e.alive);
  if (!targets.length || !combat.isYourTurn) {
    panel.appendChild(el("p", null, combat.isYourTurn ? "No living targets." : "Not your turn."));
    return panel;
  }

  const maneuverField = buildSelect(
    "stacks-combat-maneuver-select",
    `Maneuver (${CALLED_MANEUVER_ACCURACY} accuracy)`,
    maneuverOptions.map((maneuver) => ({ value: maneuver.id, label: `${maneuver.id} (${maneuver.accuracyModifier} accuracy)` })),
  );
  const targetField = buildSelect(
    "stacks-combat-maneuver-target",
    "Target",
    targets.map((e) => ({ value: e.id, label: e.name })),
  );
  const attributeField = buildSelect(
    "stacks-combat-maneuver-attribute",
    "Attribute",
    ATTRIBUTES.map((a) => ({ value: a, label: a })),
  );
  panel.appendChild(maneuverField.wrap);
  panel.appendChild(targetField.wrap);
  panel.appendChild(attributeField.wrap);

  const skillLabel = document.createElement("label");
  skillLabel.setAttribute("for", "stacks-combat-maneuver-skill");
  skillLabel.textContent = "Skill";
  panel.appendChild(skillLabel);
  const skillInput = document.createElement("input");
  skillInput.id = "stacks-combat-maneuver-skill";
  skillInput.type = "text";
  panel.appendChild(skillInput);

  const button = el("button", "stacks-combat-maneuver-button", `Declare maneuver (${CALLED_MANEUVER_ACCURACY} accuracy)`);
  button.type = "button";
  button.setAttribute(
    "aria-label",
    `Declare a called maneuver at ${CALLED_MANEUVER_ACCURACY} accuracy. Requires confirmation.`,
  );
  button.addEventListener("click", () => {
    handlers.onDeclareManeuver(maneuverField.select.value, targetField.select.value, attributeField.select.value, skillInput.value.trim());
  });
  panel.appendChild(button);
  return panel;
}

function renderReactions(combat, handlers) {
  const panel = el("section", "stacks-combat-reactions");
  panel.setAttribute("aria-label", "Reactions");
  panel.appendChild(el("h2", "stacks-panel-heading", "Reaction"));
  const list = el("div", "stacks-combat-reactions-list");
  for (const reaction of REACTIONS) {
    const button = el("button", "stacks-combat-reaction-button", reaction);
    button.type = "button";
    button.setAttribute("aria-label", `React with ${reaction}`);
    button.addEventListener("click", () => handlers.onReact(reaction));
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
