// Onboarding chrome (playtest B1/B2): a first-run rules overlay covering
// move/breach/Energy/cards/combat/reactions in plain words, a persistent
// contextual hint line, and an always-available help control that reopens
// the overlay. Rendered on every screen by main.js's renderChrome -- pure
// DOM construction from plain data/handlers, same discipline as every other
// component here.

const RULES_SECTIONS = [
  {
    heading: "Moving and breaching",
    text: "Click an adjacent discovered room to move there for 1 Energy. Click a fogged edge next to your room to breach into the unknown for 3 Energy. Both show the cost and ask you to confirm before anything is spent.",
  },
  {
    heading: "Energy",
    text: "Every hero has 5 Energy per world round. The round only advances once every living, conscious hero has acted, so there is no rush -- but Energy will not refill until then.",
  },
  {
    heading: "Cards",
    text: "Cards in your hand light up when they can be played right now; dim cards are inert. Click a card to inspect it -- clicking never plays it. Playing a card means choosing a target (if it needs one) and pressing Confirm.",
  },
  {
    heading: "Combat",
    text: "When a fight starts, pick a target and an attack or a called maneuver. Enemies telegraph what they're about to do before they act, so you can plan around it.",
  },
  {
    heading: "Reactions",
    text: "When an enemy attacks you or an ally you're protecting, you may get a reaction prompt: Dodge, Block, Protect, or Counter. Answer before the timer runs out, or it resolves to a safe default automatically.",
  },
];

export function renderRulesOverlay(open, { onClose } = {}) {
  if (!open) return null;
  const overlay = document.createElement("div");
  overlay.className = "stacks-rules-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "stacks-rules-heading");

  const panel = document.createElement("div");
  panel.className = "stacks-rules-panel";

  const heading = document.createElement("h2");
  heading.id = "stacks-rules-heading";
  heading.textContent = "How to play The Lost Meaning";
  panel.appendChild(heading);

  for (const section of RULES_SECTIONS) {
    const sectionHeading = document.createElement("h3");
    sectionHeading.textContent = section.heading;
    panel.appendChild(sectionHeading);
    const sectionText = document.createElement("p");
    sectionText.textContent = section.text;
    panel.appendChild(sectionText);
  }

  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "stacks-rules-close-button";
  closeButton.textContent = "Got it, close";
  closeButton.addEventListener("click", () => onClose());
  panel.appendChild(closeButton);

  overlay.appendChild(panel);
  return overlay;
}

export function renderHelpButton({ onOpen } = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "stacks-help-button";
  button.setAttribute("aria-label", "Open the rules overlay");
  button.textContent = "? Help";
  button.addEventListener("click", () => onOpen());
  return button;
}

export function renderHintBar(hintText) {
  const bar = document.createElement("p");
  bar.className = "stacks-hint-bar";
  bar.setAttribute("role", "status");
  bar.setAttribute("aria-live", "polite");
  bar.textContent = hintText;
  return bar;
}
