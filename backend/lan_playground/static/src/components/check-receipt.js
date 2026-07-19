// The §12.5 resolution receipt: the UI must show the chosen action, target,
// attribute, and skill; the die result; every bonus/penalty/Advantage/
// Disadvantage source; the target number or opposing roll; and the factual
// outcome -- generated narration is only allowed after these facts are
// committed (infinite_stacks.md S12.5, S24.3 "the factual check receipt
// precedes comic narration"). Pure DOM construction from plain wire data;
// no network, no store access, no timers, and it never renders narration
// text itself -- callers append narration only after this receipt.

// `receipt` shape: { action, target, attribute, skill, dieResult,
//   modifiers: [{ source, value }], targetNumber, outcome }
// `outcome` is a plain string per S12.3 ("Strong success"/"Clean success"/
// "Progress with cost"/"Meaningful setback") -- never color-only.
export function renderCheckReceipt(receipt) {
  const wrap = document.createElement("section");
  wrap.className = "stacks-check-receipt";
  wrap.setAttribute("role", "group");
  wrap.setAttribute("aria-label", "Check resolution receipt");

  const heading = document.createElement("h3");
  heading.className = "stacks-panel-heading";
  heading.textContent = `${receipt.action} — ${receipt.target}`;
  wrap.appendChild(heading);

  const facts = document.createElement("dl");
  facts.className = "stacks-check-receipt-facts";

  function addFact(term, value) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    facts.appendChild(dt);
    const dd = document.createElement("dd");
    dd.textContent = value;
    facts.appendChild(dd);
  }

  addFact("Attribute", receipt.attribute);
  addFact("Skill", receipt.skill);
  addFact("Die result", String(receipt.dieResult));

  wrap.appendChild(facts);

  const modifiers = document.createElement("ul");
  modifiers.className = "stacks-check-receipt-modifiers";
  modifiers.setAttribute("aria-label", "Every bonus, penalty, advantage, and disadvantage source");
  for (const modifier of receipt.modifiers || []) {
    const item = document.createElement("li");
    const sign = modifier.value >= 0 ? "+" : "";
    item.textContent = `${modifier.source}: ${sign}${modifier.value}`;
    modifiers.appendChild(item);
  }
  wrap.appendChild(modifiers);

  const target = document.createElement("p");
  target.className = "stacks-check-receipt-target";
  target.textContent = `Target number: ${receipt.targetNumber}`;
  wrap.appendChild(target);

  const outcome = document.createElement("p");
  outcome.className = `stacks-check-receipt-outcome stacks-check-receipt-outcome--${outcomeTier(receipt.outcome)}`;
  outcome.setAttribute("role", "status");
  outcome.textContent = `Outcome: ${receipt.outcome}`;
  wrap.appendChild(outcome);

  return wrap;
}

// Outcome text always ships with the receipt (never color-only); this tier
// only selects a reinforcing CSS class, not the label itself.
function outcomeTier(outcome) {
  const text = (outcome || "").toLowerCase();
  if (text.includes("strong")) return "strong";
  if (text.includes("clean")) return "clean";
  if (text.includes("setback")) return "setback";
  if (text.includes("cost") || text.includes("exposure")) return "cost";
  return "neutral";
}
