// Character-builder screen (infinite_stacks.md S11): four visible d4s from
// the server (S11.1/S24.2 -- the client never determines randomness, only
// ever displays attribute_dice_rolled's server-supplied values), a
// drag-free keyboard-navigable assignment UI (a <select> per attribute, kept
// as a valid bijection onto the four rolled dice by swapping rather than
// allowing a duplicate), background choice with its S11.3 ability text, a
// derived-stat preview, and a persona name field. Designed to take a
// first-timer under four minutes (S11): one screen, no required navigation.
// Receives state+handlers and only builds DOM; main.js is the sole place
// that wires network/store/timers together.

import { selectCharacterBuilderView, selectYouHero, computeDerivedStatsPreview } from "../core/selectors.js";
import { renderAttributeDie } from "../components/die.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderRollStage(handlers) {
  const panel = el("section", "stacks-builder-roll");
  panel.setAttribute("aria-label", "Roll your attribute dice");
  panel.appendChild(el("p", null, "Roll four dice, one for each attribute: Force, Finesse, Insight, Presence."));
  const button = el("button", "stacks-builder-roll-button", "Roll attribute dice");
  button.type = "button";
  button.addEventListener("click", () => handlers.onRollAttributeDice());
  panel.appendChild(button);
  return panel;
}

function renderDiceRow(pendingDice, reducedMotion) {
  const panel = el("section", "stacks-builder-dice");
  panel.setAttribute("aria-label", "Your rolled attribute dice");
  panel.appendChild(el("h2", "stacks-panel-heading", "Your dice"));
  const row = el("div", "stacks-builder-dice-row");
  pendingDice.forEach((value, index) => {
    row.appendChild(renderAttributeDie(value, { reducedMotion, label: `Die ${index + 1}` }));
  });
  panel.appendChild(row);
  return panel;
}

// One <select> per attribute, each offering the four rolled die indices.
// Picking a die index already held by another attribute swaps the two
// attributes' assignments instead of creating a duplicate -- the assignment
// is always a valid one-die-per-attribute bijection, with no error state to
// show or block submission on.
function renderAssignmentForm(builder, draft, handlers) {
  const panel = el("section", "stacks-builder-assignment");
  panel.setAttribute("aria-label", "Assign dice to attributes");
  panel.appendChild(el("h2", "stacks-panel-heading", "Assign your dice"));

  for (const attribute of builder.attributeNames) {
    const wrap = el("div", "stacks-builder-field");
    const id = `stacks-builder-attribute-${attribute}`;
    const label = document.createElement("label");
    label.setAttribute("for", id);
    label.textContent = builder.attributeLabels[attribute];
    wrap.appendChild(label);

    const select = document.createElement("select");
    select.id = id;
    builder.pendingDice.forEach((value, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `Die ${index + 1} (value ${value})`;
      select.appendChild(option);
    });
    select.value = String(draft.attributeAssignment[attribute] ?? 0);
    select.addEventListener("change", () => {
      const chosenIndex = Number(select.value);
      const nextAssignment = { ...draft.attributeAssignment };
      const swapAttribute = Object.keys(nextAssignment).find(
        (other) => other !== attribute && nextAssignment[other] === chosenIndex,
      );
      if (swapAttribute) nextAssignment[swapAttribute] = nextAssignment[attribute];
      nextAssignment[attribute] = chosenIndex;
      handlers.onUpdateCharacterDraft({ attributeAssignment: nextAssignment });
    });
    wrap.appendChild(select);
    panel.appendChild(wrap);
  }
  return panel;
}

function renderBackgroundChoice(builder, draft, handlers) {
  const panel = el("section", "stacks-builder-background");
  panel.setAttribute("aria-label", "Choose a background");
  panel.appendChild(el("h2", "stacks-panel-heading", "Background"));

  const id = "stacks-builder-background-select";
  const label = document.createElement("label");
  label.setAttribute("for", id);
  label.textContent = "Background";
  panel.appendChild(label);

  const select = document.createElement("select");
  select.id = id;
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a background...";
  select.appendChild(placeholder);
  for (const background of builder.backgrounds) {
    const option = document.createElement("option");
    option.value = background.id;
    option.textContent = background.name;
    select.appendChild(option);
  }
  select.value = draft.backgroundId || "";
  select.addEventListener("change", () => handlers.onUpdateCharacterDraft({ backgroundId: select.value || null }));
  panel.appendChild(select);

  const chosen = builder.backgrounds.find((b) => b.id === draft.backgroundId);
  if (chosen) {
    const details = el("div", "stacks-builder-background-details");
    details.appendChild(el("p", "stacks-builder-background-fallback", chosen.fallback));
    details.appendChild(
      el("p", "stacks-builder-background-bonus", `+1 ${builder.attributeLabels[chosen.attribute_bonus] || chosen.attribute_bonus}`),
    );
    const skills = Object.entries(chosen.skill_ranks)
      .map(([skill, rank]) => `${skill} +${rank}`)
      .join(", ");
    details.appendChild(el("p", "stacks-builder-background-skills", `Skills: ${skills}`));
    details.appendChild(
      el(
        "p",
        "stacks-builder-background-signature",
        `Signature ability (${chosen.signature_ability.frequency.replace(/_/g, " ")}): ${chosen.signature_ability.fallback}`,
      ),
    );
    panel.appendChild(details);
  }
  return panel;
}

// Exactly two general cards (infinite_stacks.md S13.2). Checkboxes disable
// once two are checked, so the player can't overshoot the count.
function renderGeneralCardChoice(builder, draft, handlers) {
  const panel = el("section", "stacks-builder-cards");
  panel.setAttribute("aria-label", "Choose two general cards");
  panel.appendChild(el("h2", "stacks-panel-heading", "General cards (choose 2)"));

  const list = el("div", "stacks-builder-card-list");
  for (const card of builder.generalCards) {
    const id = `stacks-builder-card-${card.id}`;
    const row = el("div", "stacks-builder-card-row");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.id = id;
    checkbox.checked = draft.generalCardIds.includes(card.id);
    checkbox.disabled = !checkbox.checked && draft.generalCardIds.length >= 2;
    checkbox.addEventListener("change", () => {
      const next = checkbox.checked
        ? [...draft.generalCardIds, card.id]
        : draft.generalCardIds.filter((id_) => id_ !== card.id);
      handlers.onUpdateCharacterDraft({ generalCardIds: next });
    });
    row.appendChild(checkbox);
    const label = document.createElement("label");
    label.setAttribute("for", id);
    label.textContent = `${card.name} -- ${card.fallback}`;
    row.appendChild(label);
    list.appendChild(row);
  }
  panel.appendChild(list);
  return panel;
}

function renderNameField(draft, handlers) {
  const panel = el("section", "stacks-builder-name");
  panel.setAttribute("aria-label", "Name your hero");
  const label = document.createElement("label");
  label.setAttribute("for", "stacks-builder-name-input");
  label.textContent = "Hero name";
  panel.appendChild(label);
  const input = document.createElement("input");
  input.id = "stacks-builder-name-input";
  input.type = "text";
  input.maxLength = 40;
  input.value = draft.name;
  input.addEventListener("input", () => handlers.onUpdateCharacterDraft({ name: input.value }));
  panel.appendChild(input);
  return panel;
}

// §11.1 derived-stat preview: max HP, Defense, Initiative modifier, and
// carry slots, computed from the current assignment + background bonus so
// the player can see the consequence of their choices before committing.
function renderDerivedPreview(builder, draft) {
  const attributes = { force: 0, finesse: 0, insight: 0, presence: 0 };
  builder.attributeNames.forEach((attribute) => {
    const dieIndex = draft.attributeAssignment[attribute];
    if (typeof dieIndex === "number" && builder.pendingDice[dieIndex] !== undefined) {
      attributes[attribute] = builder.pendingDice[dieIndex];
    }
  });
  const chosen = builder.backgrounds.find((b) => b.id === draft.backgroundId);
  if (chosen && attributes[chosen.attribute_bonus] !== undefined) {
    attributes[chosen.attribute_bonus] = Math.min(5, attributes[chosen.attribute_bonus] + 1);
  }
  const derived = computeDerivedStatsPreview(attributes);

  const panel = el("section", "stacks-builder-preview");
  panel.setAttribute("aria-label", "Derived stat preview");
  panel.appendChild(el("h2", "stacks-panel-heading", "Preview"));
  const facts = document.createElement("dl");
  facts.className = "stacks-builder-preview-facts";
  function addFact(term, value) {
    facts.appendChild(el("dt", null, term));
    facts.appendChild(el("dd", null, String(value)));
  }
  for (const attribute of builder.attributeNames) {
    addFact(builder.attributeLabels[attribute], attributes[attribute]);
  }
  addFact("Maximum HP", derived.maxHp);
  addFact("Defense", derived.defense);
  addFact("Initiative modifier", derived.initiativeModifier);
  addFact("Carry slots", derived.carrySlots);
  panel.appendChild(facts);
  return panel;
}

function assignmentIsValid(attributeNames, assignment, diceCount) {
  const values = attributeNames.map((name) => assignment[name]);
  if (values.some((v) => typeof v !== "number")) return false;
  const unique = new Set(values);
  return unique.size === attributeNames.length && values.every((v) => v >= 0 && v < diceCount);
}

function renderSubmit(builder, draft, handlers) {
  const panel = el("section", "stacks-builder-submit");
  const canSubmit =
    !!draft.name.trim() &&
    !!draft.backgroundId &&
    draft.generalCardIds.length === 2 &&
    !!builder.personaCard &&
    assignmentIsValid(builder.attributeNames, draft.attributeAssignment, builder.pendingDice.length);

  if (!canSubmit) {
    panel.appendChild(
      el("p", "stacks-builder-submit-hint", "Choose a background, exactly two general cards, and a name to continue."),
    );
  }

  const button = el("button", "stacks-builder-submit-button", "Create hero");
  button.type = "button";
  button.disabled = !canSubmit;
  button.addEventListener("click", () => {
    if (!canSubmit) return;
    handlers.onCreateHero({
      name: draft.name.trim(),
      backgroundId: draft.backgroundId,
      attributeAssignment: Object.fromEntries(
        builder.attributeNames.map((attribute) => [attribute, builder.pendingDice[draft.attributeAssignment[attribute]]]),
      ),
      generalCardIds: draft.generalCardIds,
      personaCardId: builder.personaCard.id,
    });
  });
  panel.appendChild(button);
  return panel;
}

export function renderCharacterBuilderScreen(container, state, handlers) {
  const you = selectYouHero(state);
  container.replaceChildren();
  if (!you) return;

  const heading = el("header", "stacks-builder-heading");
  heading.appendChild(el("h1", "stacks-builder-title", "Create your hero"));
  container.appendChild(heading);

  const builder = selectCharacterBuilderView(state);
  if (!builder.pendingDice) {
    container.appendChild(renderRollStage(handlers));
    return;
  }
  if (!builder.catalogLoaded) {
    container.appendChild(el("p", null, "Loading backgrounds and cards..."));
    return;
  }

  const draft = state.characterDraft;
  const layout = el("div", "stacks-builder-layout");
  layout.appendChild(renderDiceRow(builder.pendingDice, state.reducedMotion));
  layout.appendChild(renderAssignmentForm(builder, draft, handlers));
  layout.appendChild(renderBackgroundChoice(builder, draft, handlers));
  layout.appendChild(renderGeneralCardChoice(builder, draft, handlers));
  layout.appendChild(renderNameField(draft, handlers));
  layout.appendChild(renderDerivedPreview(builder, draft));
  layout.appendChild(renderSubmit(builder, draft, handlers));
  container.appendChild(layout);
}
