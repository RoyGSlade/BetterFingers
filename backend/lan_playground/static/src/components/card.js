// Card face (infinite_stacks.md S13.3): every card declares timing, an
// action/reaction cost, range and legal targets, required room state/tags/
// equipment, its exact base effect, a check/outcome table if uncertain,
// combination tags, discard/Exhaust behavior, generated-description
// fallback text, and an accessible text equivalent. This component renders
// all of those facts from plain wire data -- it never touches the network,
// the store, or a timer.

// `card` shape: { id, name, timing, cost, range, targets, effect,
//   requirements, checkTable, tags, exhaustOnPlay, accessibleText,
//   generatedDescription }
export function renderCard(card, { onPlay, playable = false } = {}) {
  const wrap = document.createElement(playable && typeof onPlay === "function" ? "button" : "div");
  wrap.className = "stacks-card" + (playable ? " is-playable" : "");
  wrap.dataset.cardId = card.id;

  if (playable && typeof onPlay === "function") {
    wrap.type = "button";
    wrap.addEventListener("click", () => onPlay(card.id));
  }

  // Accessible text equivalent is the primary label assistive tech reads --
  // it stands in for the whole card face, not just a supplemental caption.
  wrap.setAttribute("aria-label", card.accessibleText || card.name);

  const heading = document.createElement("div");
  heading.className = "stacks-card-heading";
  const name = document.createElement("span");
  name.className = "stacks-card-name";
  name.textContent = card.name;
  heading.appendChild(name);
  const timing = document.createElement("span");
  timing.className = "stacks-card-timing";
  timing.textContent = card.timing;
  heading.appendChild(timing);
  wrap.appendChild(heading);

  const facts = document.createElement("dl");
  facts.className = "stacks-card-facts";

  function addFact(term, value) {
    if (value === undefined || value === null || value === "") return;
    const dt = document.createElement("dt");
    dt.textContent = term;
    facts.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = value;
    facts.appendChild(dd);
  }

  addFact("Cost", card.cost);
  addFact("Range", card.range);
  addFact("Targets", Array.isArray(card.targets) ? card.targets.join(", ") : card.targets);
  addFact("Requires", card.requirements);
  wrap.appendChild(facts);

  const effect = document.createElement("p");
  effect.className = "stacks-card-effect";
  effect.textContent = card.effect;
  wrap.appendChild(effect);

  if (card.checkTable) {
    const checkTable = document.createElement("p");
    checkTable.className = "stacks-card-check-table";
    checkTable.textContent = `If uncertain: ${card.checkTable}`;
    wrap.appendChild(checkTable);
  }

  if (card.tags && card.tags.length) {
    const tags = document.createElement("ul");
    tags.className = "stacks-card-tags";
    tags.setAttribute("aria-label", "Combination tags");
    for (const tag of card.tags) {
      const item = document.createElement("li");
      item.className = "stacks-card-tag";
      item.textContent = tag;
      tags.appendChild(item);
    }
    wrap.appendChild(tags);
  }

  const disposal = document.createElement("p");
  disposal.className = "stacks-card-disposal";
  disposal.textContent = card.exhaustOnPlay ? "Exhausts on play" : "Discards on play";
  wrap.appendChild(disposal);

  if (card.generatedDescription) {
    const fallback = document.createElement("p");
    fallback.className = "stacks-card-generated-description";
    fallback.textContent = card.generatedDescription;
    wrap.appendChild(fallback);
  }

  return wrap;
}

export function renderCardList(cards, opts) {
  const list = document.createElement("div");
  list.className = "stacks-card-list";
  for (const card of cards || []) {
    list.appendChild(renderCard(card, opts));
  }
  return list;
}
