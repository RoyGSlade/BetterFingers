// Card face (infinite_stacks.md S13.3 + playtest A1-A5): real card anatomy,
// top-down -- title, art slot, keywords, description, effect -- inside a
// frame + backing, with a visible playable-now/inert affordance. Clicking
// the card body only ever inspects/expands it (A4: "click must
// select/inspect"); playing is a separate, explicit control that appears
// once expanded and always requires main.js to stage a confirm step before
// any command is sent -- this component never calls a "play" handler
// directly, only onInspect. Pure DOM construction from plain wire data, no
// network/store/timers.

// `card` shape: { id, name, timing, cost, range, targets, effect,
//   requirements, checkTable, tags, exhaustOnPlay, accessibleText,
//   generatedDescription, frameKind, playableNow }
export function renderCard(card, { onInspect, inspected = false, expandedContent = null, playable = false } = {}) {
  const wrap = document.createElement("div");
  const playableNow = playable && card.playableNow !== false;
  wrap.className =
    "stacks-card" +
    ` stacks-card--${card.frameKind || "scheme"}` +
    (playableNow ? " is-playable" : " is-inert") +
    (inspected ? " is-inspected" : "");
  wrap.dataset.cardId = card.id;

  const trigger = document.createElement(typeof onInspect === "function" ? "button" : "div");
  trigger.className = "stacks-card-inspect-trigger";
  if (typeof onInspect === "function") {
    trigger.type = "button";
    trigger.setAttribute("aria-expanded", String(inspected));
    trigger.addEventListener("click", () => onInspect(card.id));
  }
  // Accessible text equivalent is the primary label assistive tech reads --
  // it stands in for the whole card face, not just a supplemental caption.
  trigger.setAttribute("aria-label", card.accessibleText || card.name);

  const frame = document.createElement("div");
  frame.className = "stacks-card-frame";

  // 1. Title
  const title = document.createElement("div");
  title.className = "stacks-card-title";
  title.textContent = card.name;
  frame.appendChild(title);

  // 2. Art slot (background-image via a frame-kind CSS class, never an
  // inline style -- see stacks.css .stacks-card-art--charm/scheme/bonk).
  const art = document.createElement("div");
  art.className = `stacks-card-art stacks-card-art--${card.frameKind || "scheme"}`;
  art.setAttribute("aria-hidden", "true");
  frame.appendChild(art);

  // 3. Keywords: cost/timing, range, targets, requirements, combination tags
  // -- compact facts rather than prose, ahead of the description/effect.
  const keywords = document.createElement("dl");
  keywords.className = "stacks-card-keywords";
  function addKeyword(term, value) {
    if (value === undefined || value === null || value === "") return;
    const dt = document.createElement("dt");
    dt.textContent = term;
    keywords.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = value;
    keywords.appendChild(dd);
  }
  addKeyword("Cost", card.cost);
  addKeyword("Range", card.range);
  addKeyword("Targets", Array.isArray(card.targets) ? card.targets.join(", ") : card.targets);
  addKeyword("Requires", card.requirements);
  frame.appendChild(keywords);

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
    frame.appendChild(tags);
  }

  // 4. Description (flavor / generated fallback prose)
  if (card.generatedDescription) {
    const description = document.createElement("p");
    description.className = "stacks-card-description";
    description.textContent = card.generatedDescription;
    frame.appendChild(description);
  }

  // 5. Effect (the exact mechanical text)
  const effect = document.createElement("p");
  effect.className = "stacks-card-effect";
  effect.textContent = card.effect;
  frame.appendChild(effect);

  if (card.checkTable) {
    const checkTable = document.createElement("p");
    checkTable.className = "stacks-card-check-table";
    checkTable.textContent = `If uncertain: ${card.checkTable}`;
    frame.appendChild(checkTable);
  }

  const disposal = document.createElement("p");
  disposal.className = "stacks-card-disposal";
  disposal.textContent = card.exhaustOnPlay ? "Exhausts on play" : "Discards on play";
  frame.appendChild(disposal);

  // A3: playable-now vs inert affordance -- text label, never color-only.
  const affordance = document.createElement("p");
  affordance.className = "stacks-card-affordance";
  affordance.textContent = playableNow ? "Playable now" : "Not playable right now";
  frame.appendChild(affordance);

  trigger.appendChild(frame);
  wrap.appendChild(trigger);

  if (inspected && expandedContent) {
    wrap.appendChild(expandedContent);
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
