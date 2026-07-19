// Hero roster card (infinite_stacks.md S21.3/S24.1): portrait-equivalent,
// danger tier, 5-pip Energy display. Takes the plain data selectors.js
// already computed and returns a DOM node -- never touches the network, the
// store, or a timer. Other heroes' cards are buttons (route-preview target
// select, S24.1 "selecting a distant ally previews route length"); your own
// hero card is a non-interactive status display.

export function renderHeroCard(heroCard, { onSelect, selected = false } = {}) {
  const interactive = !heroCard.isYou && typeof onSelect === "function";
  const el = document.createElement(interactive ? "button" : "div");
  el.className = "stacks-hero-card" + (heroCard.isYou ? " stacks-hero-card--you" : "") + (selected ? " is-selected" : "");
  el.dataset.heroId = heroCard.heroId;

  if (interactive) {
    el.type = "button";
    el.setAttribute("aria-pressed", String(selected));
    el.addEventListener("click", () => onSelect(heroCard.heroId));
  }

  const name = document.createElement("div");
  name.className = "stacks-hero-card-name";
  name.textContent = heroCard.name + (heroCard.isYou ? " (you)" : "");
  el.appendChild(name);

  // Danger tier: text label always present, never color-only (S24.1/S25).
  const danger = document.createElement("div");
  danger.className = `stacks-hero-card-danger stacks-hero-card-danger--${heroCard.danger.tier}`;
  danger.textContent = heroCard.danger.label;
  el.appendChild(danger);

  const energy = document.createElement("div");
  energy.className = "stacks-hero-card-energy";
  energy.setAttribute("role", "img");
  const filled = heroCard.energyPips.filter(Boolean).length;
  energy.setAttribute("aria-label", `Energy ${filled} of ${heroCard.energyPips.length}`);
  for (const isFilled of heroCard.energyPips) {
    const pip = document.createElement("span");
    pip.className = "stacks-energy-pip" + (isFilled ? " is-filled" : "");
    pip.setAttribute("aria-hidden", "true");
    pip.textContent = isFilled ? "●" : "○"; // filled/empty circle -- shape-coded, not color-only
    energy.appendChild(pip);
  }
  el.appendChild(energy);

  const presence = document.createElement("div");
  presence.className = "stacks-hero-card-presence";
  presence.textContent = [heroCard.connected ? "Connected" : "Disconnected", heroCard.ready ? "Ready" : null]
    .filter(Boolean)
    .join(" · ");
  el.appendChild(presence);

  return el;
}
