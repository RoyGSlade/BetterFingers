// Persistent character panel (playtest D1/D2): "No character sheet ... HP
// must be shown as numbers (and bar), plus attributes, skills, Energy,
// statuses, and abilities, in a persistent panel" / "Inventory ... belongs
// inside the character panel as a visual slot grid." Mounted by main.js into
// the always-visible #character-panel element on every screen once the
// hero has a sheet -- nothing here is ever pushed below the fold. Pure DOM
// construction from plain state, same discipline as every screen module.

import { selectCharacterPanelView } from "../core/selectors.js";
import { renderToken } from "../components/token.js";
import { renderStatusBadge } from "../components/status.js";
import { renderInventoryPanel } from "./hero-panel.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderHpBar(hp, maxHp, danger) {
  const wrap = el("div", "stacks-character-hp");
  const numbers = el("p", "stacks-character-hp-numbers", `HP ${hp} / ${maxHp}`);
  wrap.appendChild(numbers);
  const bar = el("div", "stacks-character-hp-bar");
  bar.setAttribute("role", "img");
  bar.setAttribute("aria-label", `HP ${hp} of ${maxHp}, ${danger.label}`);
  const fillPercent = maxHp > 0 ? Math.max(0, Math.min(100, Math.round((hp / maxHp) * 100))) : 0;
  const fill = el("div", `stacks-character-hp-fill stacks-character-hp-fill--${danger.tier} stacks-fill-${Math.round(fillPercent / 5) * 5}`);
  bar.appendChild(fill);
  wrap.appendChild(bar);
  const dangerLine = el("p", `stacks-character-danger stacks-hero-card-danger--${danger.tier}`);
  const glyph = el("span", null, danger.glyph || "");
  glyph.setAttribute("aria-hidden", "true");
  dangerLine.appendChild(glyph);
  dangerLine.appendChild(document.createTextNode(` ${danger.label}`));
  wrap.appendChild(dangerLine);
  return wrap;
}

function renderEnergyPips(pips) {
  const wrap = el("div", "stacks-character-energy");
  wrap.setAttribute("role", "img");
  const filled = pips.filter(Boolean).length;
  wrap.setAttribute("aria-label", `Energy ${filled} of ${pips.length}`);
  for (const isFilled of pips) {
    const pip = el("span", "stacks-energy-pip" + (isFilled ? " is-filled" : ""), isFilled ? "●" : "○");
    pip.setAttribute("aria-hidden", "true");
    wrap.appendChild(pip);
  }
  return wrap;
}

function renderFactGrid(className, entries) {
  const grid = el("dl", className);
  for (const [label, value] of entries) {
    grid.appendChild(el("dt", null, label));
    grid.appendChild(el("dd", null, String(value)));
  }
  return grid;
}

function renderAbilities(abilities, handlers) {
  const section = el("section", "stacks-character-abilities");
  section.setAttribute("aria-label", "Abilities");
  section.appendChild(el("h3", "stacks-panel-heading", "Abilities"));
  if (!abilities.length) {
    section.appendChild(el("p", "stacks-character-empty", "No abilities yet."));
    return section;
  }
  const list = el("ul", "stacks-ability-list");
  for (const ability of abilities) {
    const item = el("li", "stacks-ability-item" + (ability.available ? " is-available" : " is-unavailable"));
    const name = el("span", "stacks-ability-name", ability.name);
    item.appendChild(name);
    const frequency = el("span", "stacks-ability-frequency", ability.frequency ? ` (${ability.frequency.replace(/_/g, " ")})` : "");
    item.appendChild(frequency);
    const availability = el("span", "stacks-ability-availability", ability.available ? " -- available" : " -- used");
    item.appendChild(availability);
    // Director's ruling 04:39: content authors fallback as one flavor line
    // and accessible as the FULL rules text (trigger, exact check/DC, why
    // it's good) -- both must render visibly for sighted players, not just
    // land in an aria attribute, or the "what benefit do I get" complaint
    // comes right back.
    item.appendChild(el("p", "stacks-ability-flavor", ability.fallback));
    item.appendChild(el("p", "stacks-ability-effect", ability.accessible));
    if (typeof handlers.onUseAbility === "function" && ability.available) {
      const useButton = el("button", "stacks-ability-use-button", "Use");
      useButton.type = "button";
      useButton.addEventListener("click", () => handlers.onUseAbility(ability.id));
      item.appendChild(useButton);
    }
    list.appendChild(item);
  }
  section.appendChild(list);
  return section;
}

// A5: active-effects tray. Reuses status.js's badge for real combat statuses
// (hero.statuses) and renders a matching badge shape for forward-compatible
// hero.active_effects (card/ability durations, fixture-first per this wave's
// room-chat contract with stacks-abilities).
function renderActiveEffectsTray(activeEffects) {
  const section = el("section", "stacks-character-active-effects");
  section.setAttribute("aria-label", "Active effects");
  section.appendChild(el("h3", "stacks-panel-heading", "Active effects"));
  if (!activeEffects.length) {
    section.appendChild(el("p", "stacks-character-empty", "No active effects."));
    return section;
  }
  const list = el("div", "stacks-status-list");
  for (const effect of activeEffects) {
    if (effect.kind === "status") {
      list.appendChild(renderStatusBadge({ id: effect.id, roundsRemaining: effect.roundsRemaining }));
      continue;
    }
    const badge = el("span", "stacks-status-badge");
    const duration = typeof effect.roundsRemaining === "number" ? ` (${effect.roundsRemaining} round${effect.roundsRemaining === 1 ? "" : "s"})` : " (until fight ends)";
    const label = el("span", "stacks-status-label", `${effect.name}${duration}`);
    badge.appendChild(label);
    badge.title = effect.fallback || "";
    badge.setAttribute("aria-label", effect.accessible || `${effect.name}${duration}`);
    list.appendChild(badge);
  }
  section.appendChild(list);
  return section;
}

export function renderCharacterPanel(container, state, handlers) {
  const view = selectCharacterPanelView(state);
  if (!view) {
    container.hidden = true;
    container.replaceChildren();
    return;
  }
  container.hidden = false;
  container.replaceChildren();

  const heading = el("div", "stacks-character-heading");
  if (view.token) heading.appendChild(renderToken(view.token, { size: "lg" }));
  heading.appendChild(el("h2", "stacks-character-name", view.name));
  container.appendChild(heading);

  container.appendChild(renderHpBar(view.hp, view.maxHp, view.danger));
  container.appendChild(renderEnergyPips(view.energyPips));

  if (view.attributes) {
    const attrSection = el("section", "stacks-character-attributes");
    attrSection.setAttribute("aria-label", "Attributes");
    attrSection.appendChild(el("h3", "stacks-panel-heading", "Attributes"));
    attrSection.appendChild(renderFactGrid("stacks-character-fact-grid", Object.entries(view.attributes)));
    container.appendChild(attrSection);
  }

  if (view.skills) {
    const skillSection = el("section", "stacks-character-skills");
    skillSection.setAttribute("aria-label", "Skills");
    skillSection.appendChild(el("h3", "stacks-panel-heading", "Skills"));
    const entries = Object.entries(view.skills);
    if (entries.length) {
      skillSection.appendChild(renderFactGrid("stacks-character-fact-grid", entries));
    } else {
      skillSection.appendChild(el("p", "stacks-character-empty", "No trained skills yet."));
    }
    container.appendChild(skillSection);
  }

  container.appendChild(renderActiveEffectsTray(view.activeEffects));
  container.appendChild(renderAbilities(view.abilities, handlers));

  const inventorySection = el("section", "stacks-character-inventory");
  inventorySection.setAttribute("aria-label", "Inventory");
  inventorySection.appendChild(el("h3", "stacks-panel-heading", "Inventory"));
  renderInventoryPanel(inventorySection, state, handlers);
  container.appendChild(inventorySection);
}
