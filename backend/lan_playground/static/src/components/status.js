// The nine light statuses (infinite_stacks.md S16.4). Each has one primary
// effect, a visible duration, and a treatment rule -- every badge shows a
// text label alongside a decorative glyph so nothing is color-only
// (S24.1/S25). Pure DOM construction: no network, no store access, no timers.

export const STATUS_DISPLAY = Object.freeze({
  bleeding: {
    label: "Bleeding",
    glyph: "◆", // filled diamond
    primaryEffect: "Lose 1 HP after strenuous action",
    removal: "Bandage, medicine, safe rest",
  },
  burning: {
    label: "Burning",
    glyph: "▲", // filled triangle
    primaryEffect: "Take damage at round end",
    removal: "Water, roll, extinguish action",
  },
  frightened: {
    label: "Frightened",
    glyph: "!",
    primaryEffect: "Cannot willingly approach the source",
    removal: "Rally, distance, source removed",
  },
  confused: {
    label: "Confused",
    glyph: "?",
    primaryEffect: "First targeted action shows two possible targets",
    removal: "Read/Wordcraft aid, room end",
  },
  silenced: {
    label: "Silenced",
    glyph: "✕", // multiplication x
    primaryEffect: "Cannot use speech-tagged cards",
    removal: "Break source, writing tool, room end",
  },
  sickened: {
    label: "Sickened",
    glyph: "◐", // half-filled circle
    primaryEffect: "Disadvantage on Force recovery checks",
    removal: "Antidote, diagnosis and treatment",
  },
  exhausted: {
    label: "Exhausted",
    glyph: "▽", // hollow down triangle
    primaryEffect: "Begin next world round with 3 Energy",
    removal: "Full safe rest",
  },
  marked: {
    label: "Marked",
    glyph: "✦", // four-pointed star
    primaryEffect: "Named enemy gains an effect against the hero",
    removal: "Hide, cleanse, defeat marker",
  },
  prone: {
    label: "Prone",
    glyph: "⊘", // circled division slash
    primaryEffect: "Movement required before normal repositioning",
    removal: "Stand or allied assist",
  },
});

export const STATUS_IDS = Object.freeze(Object.keys(STATUS_DISPLAY));

// `status` is plain wire data: { id, roundsRemaining? }. Duration is shown
// whenever the caller knows it; an unknown/indefinite duration omits the
// count rather than showing a misleading number.
export function renderStatusBadge(status) {
  const display = STATUS_DISPLAY[status.id] || { label: status.id, glyph: "•", primaryEffect: "", removal: "" };

  const badge = document.createElement("span");
  badge.className = "stacks-status-badge";
  badge.dataset.statusId = status.id;

  const glyph = document.createElement("span");
  glyph.className = "stacks-status-glyph";
  glyph.setAttribute("aria-hidden", "true");
  glyph.textContent = display.glyph;
  badge.appendChild(glyph);

  const text = document.createElement("span");
  text.className = "stacks-status-label";
  const duration = typeof status.roundsRemaining === "number" ? ` (${status.roundsRemaining} round${status.roundsRemaining === 1 ? "" : "s"})` : "";
  text.textContent = display.label + duration;
  badge.appendChild(text);

  badge.title = `${display.primaryEffect}. Removed by: ${display.removal}.`;
  badge.setAttribute("aria-label", `${display.label}${duration}: ${display.primaryEffect}. Removed by ${display.removal}.`);

  return badge;
}

// `statuses` is an array of the same plain wire data renderStatusBadge takes.
export function renderStatusList(statuses) {
  const list = document.createElement("div");
  list.className = "stacks-status-list";
  if (!statuses || !statuses.length) {
    list.appendChild(document.createTextNode(""));
    return list;
  }
  for (const status of statuses) {
    list.appendChild(renderStatusBadge(status));
  }
  return list;
}
