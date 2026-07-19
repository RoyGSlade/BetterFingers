// Shared visible d8 display (infinite_stacks.md S24.2). The server supplies
// the result (docs/INFINITE_STACKS_CONTRACTS.md S9: "handle() is the only
// place allowed to draw from rng") -- this component only ever displays a
// value it was given, it never generates one. Reduced-motion mode skips the
// CSS rolling animation and shows the readable result immediately; the
// animation itself is CSS-only (no JS timer in this function).

export function renderDie(dieDisplay, { reducedMotion = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = "stacks-die" + (reducedMotion ? " stacks-die--instant" : "");

  if (!dieDisplay) {
    wrap.setAttribute("role", "img");
    wrap.setAttribute("aria-label", "No die rolled yet");
    const idle = document.createElement("div");
    idle.className = "stacks-die-face stacks-die-face--idle";
    idle.textContent = "–";
    wrap.appendChild(idle);
    return wrap;
  }

  wrap.setAttribute("role", "img");
  wrap.setAttribute(
    "aria-label",
    `d8 rolled ${dieDisplay.value}: ${dieDisplay.familyLabel}, world round ${dieDisplay.worldRound}`,
  );

  const face = document.createElement("div");
  face.className = "stacks-die-face" + (reducedMotion ? "" : " stacks-die-face--rolling");
  face.textContent = String(dieDisplay.value);
  face.setAttribute("aria-hidden", "true");
  wrap.appendChild(face);

  const label = document.createElement("div");
  label.className = "stacks-die-label";
  label.textContent = dieDisplay.familyLabel;
  label.setAttribute("aria-hidden", "true");
  wrap.appendChild(label);

  return wrap;
}
