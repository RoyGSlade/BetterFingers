// Mystery Chamber puzzle screen (infinite_stacks.md S10, S24.4): objects are
// selectable/inspectable rather than buried in prose; the private-clue panel
// has a deliberate Share control (never auto-shared); shared notes support
// text, simple ordering, linking, and marking contradictions; the hint route
// and its S10.4 cost are visible; and a submission control lets the party
// commit an answer. Receives state+handlers and only builds DOM -- main.js
// is the sole place that wires network/store/timers together.

import { selectPuzzleView } from "../core/selectors.js";

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Objects are individually selectable/inspectable buttons -- the four design
// roles (anchor/key/contradiction/red herring, S10.2) are never labeled to
// the player, only the object's own name/description is shown.
function renderObjects(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-objects");
  panel.setAttribute("aria-label", "Puzzle objects");
  panel.appendChild(el("h2", "stacks-panel-heading", "Objects"));
  const list = el("div", "stacks-puzzle-objects-list");
  for (const object of puzzle.objects) {
    const button = el("button", "stacks-puzzle-object" + (object.inspected ? " is-inspected" : ""), object.label);
    button.type = "button";
    button.dataset.objectId = object.id;
    button.setAttribute("aria-label", object.inspected ? `${object.label} (already inspected)` : `Inspect ${object.label}`);
    button.addEventListener("click", () => handlers.onInspectObject(object.id));
    list.appendChild(button);
    if (object.inspected && object.description) {
      list.appendChild(el("p", "stacks-puzzle-object-description", object.description));
    }
  }
  panel.appendChild(list);
  return panel;
}

// The private-clue panel never auto-shares -- Share is a deliberate,
// separate control the clue-holder must press (S24.4 "private clues have a
// deliberate Share control").
function renderPrivateClue(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-private-clue");
  panel.setAttribute("aria-label", "Your private clue");
  panel.appendChild(el("h2", "stacks-panel-heading", "Private clue (only you can see this)"));

  if (!puzzle.privateClue) {
    panel.appendChild(el("p", null, "No private clue assigned."));
    return panel;
  }

  panel.appendChild(el("p", "stacks-puzzle-private-clue-text", puzzle.privateClue.text));

  if (puzzle.privateClue.shared) {
    panel.appendChild(el("p", "stacks-puzzle-private-clue-status", "Shared with the party."));
  } else {
    const shareButton = el("button", "stacks-puzzle-share-clue-button", "Share with party");
    shareButton.type = "button";
    shareButton.addEventListener("click", () => handlers.onShareClue());
    panel.appendChild(shareButton);
  }
  return panel;
}

// Shared notes support plain text, simple ordering (order number + move
// up/down), linking two notes into one evidence set, and marking a note as
// contradicted -- each control is a labeled button/input, never a
// color-only or image-coordinate-only affordance (S24.4).
function renderSharedNotes(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-shared-notes");
  panel.setAttribute("aria-label", "Shared notes");
  panel.appendChild(el("h2", "stacks-panel-heading", "Shared notes"));

  const list = el("ol", "stacks-puzzle-notes-list");
  const notes = puzzle.sharedNotes || [];
  notes.forEach((note, index) => {
    const item = el("li", "stacks-puzzle-note" + (note.contradiction ? " is-contradiction" : ""));

    const text = el("p", "stacks-puzzle-note-text", note.text);
    item.appendChild(text);

    const meta = el("p", "stacks-puzzle-note-meta", `By ${note.authorName}`);
    item.appendChild(meta);

    const order = el("div", "stacks-puzzle-note-order");
    const upButton = el("button", "stacks-puzzle-note-order-up", "Move earlier");
    upButton.type = "button";
    upButton.disabled = index === 0;
    upButton.setAttribute("aria-label", `Move note "${note.text}" earlier`);
    upButton.addEventListener("click", () => handlers.onReorderNote(note.id, "up"));
    order.appendChild(upButton);
    const downButton = el("button", "stacks-puzzle-note-order-down", "Move later");
    downButton.type = "button";
    downButton.disabled = index === notes.length - 1;
    downButton.setAttribute("aria-label", `Move note "${note.text}" later`);
    downButton.addEventListener("click", () => handlers.onReorderNote(note.id, "down"));
    order.appendChild(downButton);
    item.appendChild(order);

    if (note.linkedNoteIds && note.linkedNoteIds.length) {
      const linked = el(
        "p",
        "stacks-puzzle-note-links",
        `Linked with: ${note.linkedNoteIds.map((id) => notes.find((n) => n.id === id)?.text || id).join(", ")}`,
      );
      item.appendChild(linked);
    }

    const otherNotes = notes.filter((n) => n.id !== note.id);
    if (otherNotes.length) {
      const linkForm = el("div", "stacks-puzzle-note-link-form");
      const select = document.createElement("select");
      select.className = "stacks-puzzle-note-link-select";
      select.setAttribute("aria-label", `Link "${note.text}" with another note`);
      for (const other of otherNotes) {
        const option = document.createElement("option");
        option.value = other.id;
        option.textContent = other.text;
        select.appendChild(option);
      }
      linkForm.appendChild(select);
      const linkButton = el("button", "stacks-puzzle-note-link-button", "Link notes");
      linkButton.type = "button";
      linkButton.addEventListener("click", () => handlers.onLinkNotes(note.id, select.value));
      linkForm.appendChild(linkButton);
      item.appendChild(linkForm);
    }

    const contradictionButton = el(
      "button",
      "stacks-puzzle-note-contradiction-button",
      note.contradiction ? "Contradiction marked" : "Mark contradiction",
    );
    contradictionButton.type = "button";
    contradictionButton.setAttribute("aria-pressed", String(!!note.contradiction));
    contradictionButton.addEventListener("click", () => handlers.onToggleContradiction(note.id));
    item.appendChild(contradictionButton);

    list.appendChild(item);
  });
  panel.appendChild(list);

  const addForm = el("div", "stacks-puzzle-add-note-form");
  const label = document.createElement("label");
  label.setAttribute("for", "stacks-puzzle-add-note-input");
  label.textContent = "Add a shared note";
  addForm.appendChild(label);
  const input = document.createElement("textarea");
  input.id = "stacks-puzzle-add-note-input";
  input.className = "stacks-puzzle-add-note-input";
  addForm.appendChild(input);
  const addButton = el("button", "stacks-puzzle-add-note-button", "Add note");
  addButton.type = "button";
  addButton.addEventListener("click", () => {
    if (!input.value.trim()) return;
    handlers.onAddNote(input.value.trim());
    input.value = "";
  });
  addForm.appendChild(addButton);
  panel.appendChild(addForm);

  return panel;
}

// The hint route and its S10.4 cost are always visible, in order, before the
// player asks for one -- never a hidden menu revealed only after clicking.
function renderHints(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-hints");
  panel.setAttribute("aria-label", "Hint route");
  panel.appendChild(el("h2", "stacks-panel-heading", "Hints"));

  const list = el("ol", "stacks-puzzle-hint-tiers");
  for (const tier of puzzle.hints.tiers) {
    const item = el("li", "stacks-puzzle-hint-tier" + (tier.level <= puzzle.hints.used ? " is-used" : ""));
    item.appendChild(el("p", "stacks-puzzle-hint-tier-description", tier.description));
    item.appendChild(el("p", "stacks-puzzle-hint-tier-cost", `Cost: ${tier.cost}`));
    list.appendChild(item);
  }
  panel.appendChild(list);

  if (puzzle.hints.nextHintCost) {
    const requestButton = el("button", "stacks-puzzle-request-hint-button", `Request next hint (${puzzle.hints.nextHintCost})`);
    requestButton.type = "button";
    requestButton.addEventListener("click", () => handlers.onRequestHint());
    panel.appendChild(requestButton);
  } else if (puzzle.hints.forceProgressAvailable) {
    const consequence = el("p", "stacks-puzzle-force-progress-consequence", `Force progress: ${puzzle.hints.forceProgressConsequence}`);
    panel.appendChild(consequence);
    const forceButton = el("button", "stacks-puzzle-force-progress-button", "Force progress");
    forceButton.type = "button";
    forceButton.addEventListener("click", () => handlers.onForceProgress());
    panel.appendChild(forceButton);
  } else {
    panel.appendChild(el("p", null, "No hints remain."));
  }

  return panel;
}

// Submission is a set of labeled, accessible answer slots (dropdowns over
// puzzle objects) -- never an image-coordinate or color-only input (S24.4).
function renderSubmission(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-submission");
  panel.setAttribute("aria-label", "Submit solution");
  panel.appendChild(el("h2", "stacks-panel-heading", "Submit solution"));

  const form = el("div", "stacks-puzzle-submission-form");
  const selects = [];
  for (const slot of puzzle.submission.slots) {
    const row = el("div", "stacks-puzzle-submission-slot");
    const label = document.createElement("label");
    const selectId = `stacks-puzzle-slot-${slot.id}`;
    label.setAttribute("for", selectId);
    label.textContent = slot.label;
    row.appendChild(label);

    const select = document.createElement("select");
    select.id = selectId;
    select.className = "stacks-puzzle-submission-select";
    select.dataset.slotId = slot.id;
    for (const option of slot.options) {
      const optionEl = document.createElement("option");
      optionEl.value = option.id;
      optionEl.textContent = option.label;
      if (option.id === slot.selectedId) optionEl.selected = true;
      select.appendChild(optionEl);
    }
    row.appendChild(select);
    form.appendChild(row);
    selects.push({ slotId: slot.id, select });
  }
  panel.appendChild(form);

  const submitButton = el("button", "stacks-puzzle-submit-button", "Submit solution");
  submitButton.type = "button";
  submitButton.disabled = !puzzle.submission.legal;
  submitButton.addEventListener("click", () => {
    const answer = {};
    for (const { slotId, select } of selects) answer[slotId] = select.value;
    handlers.onSubmitSolution(answer);
  });
  panel.appendChild(submitButton);

  return panel;
}

function renderHeading(puzzle) {
  const heading = el("header", "stacks-puzzle-heading");
  heading.appendChild(el("h1", "stacks-puzzle-title", puzzle.templateLabel));
  heading.appendChild(el("p", "stacks-puzzle-difficulty", `Difficulty ${puzzle.difficulty}`));
  return heading;
}

export function renderPuzzleScreen(container, state, handlers) {
  const puzzle = selectPuzzleView(state);
  container.replaceChildren();
  if (!puzzle) return;

  container.appendChild(renderHeading(puzzle));
  const layout = el("div", "stacks-puzzle-layout");
  layout.appendChild(renderObjects(puzzle, handlers));
  layout.appendChild(renderPrivateClue(puzzle, handlers));
  layout.appendChild(renderSharedNotes(puzzle, handlers));
  layout.appendChild(renderHints(puzzle, handlers));
  layout.appendChild(renderSubmission(puzzle, handlers));
  container.appendChild(layout);
}
