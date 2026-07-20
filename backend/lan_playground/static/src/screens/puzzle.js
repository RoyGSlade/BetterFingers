// Mystery Chamber puzzle screen (infinite_stacks.md S10, S24.4): objects are
// selectable/inspectable rather than buried in prose; every private clue has
// its own deliberate Share control (never auto-shared); shared notes support
// text, simple ordering, linking, and marking contradictions; the hint route
// is visible; and an ordered-list submission control lets the party commit an
// answer. Receives state+handlers and only builds DOM -- main.js is the sole
// place that wires network/store/timers together.
//
// core/selectors.js's selectPuzzleView is the REAL wire shape
// (docs/INFINITE_STACKS_CONTRACTS.md S5.2): objects carry fallback/accessible
// prose that's always visible (never gated behind inspecting first), and a
// hero can hold MULTIPLE private clue fragments (yourPrivateClues), each
// shared independently. There is no forward-looking hint-tier/cost list on
// the wire (systems/puzzles.py's request_hint is Energy-free and doesn't
// preview upcoming hints) and no item-id catalog for the ordering puzzle's
// solution items either -- see the ordered-list submission note below.

import { selectPuzzleView } from "../core/selectors.js";

// The ordering_sequence template (the only puzzle template this wave,
// docs/INFINITE_STACKS_CONTRACTS.md S5.1) always authors exactly three hint
// steps (content/puzzles/ordering_sequence.py). The wire never sends a total
// hint count, so this is a documented assumption specific to that one
// template -- it will need to become server-authoritative if a second
// template with a different hint count ships.
const KNOWN_HINT_TOTAL = 3;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// Objects are individually selectable/inspectable buttons -- the four design
// roles (anchor/key/contradiction/red herring, S10.2) are never labeled to
// the player, only the object's own fallback/accessible prose is (already
// always visible on the wire; pressing Inspect is what claims a key-object
// clue fragment or logs a non-key object's clue text, not what reveals text).
function renderObjects(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-objects");
  panel.setAttribute("aria-label", "Puzzle objects");
  panel.appendChild(el("h2", "stacks-panel-heading", "Objects"));
  const list = el("div", "stacks-puzzle-objects-list");
  for (const object of puzzle.objects) {
    const button = el("button", "stacks-puzzle-object" + (object.inspected ? " is-inspected" : ""));
    button.type = "button";
    button.dataset.objectId = object.id;
    button.setAttribute("aria-label", object.inspected ? `${object.accessible} (already inspected)` : `Inspect: ${object.accessible}`);
    button.addEventListener("click", () => handlers.onInspectObject(object.id));
    const text = el("span", "stacks-puzzle-object-text", object.fallback);
    button.appendChild(text);
    if (object.inspected) button.appendChild(el("span", "stacks-puzzle-object-status", "Inspected"));
    list.appendChild(button);
  }
  panel.appendChild(list);
  return panel;
}

// One clue with its own deliberate Share control (S24.4 "private clues have
// a deliberate Share control" -- never auto-shared into shared notes).
function renderClueRow(clue, handlers) {
  const row = el("li", "stacks-puzzle-clue");
  row.appendChild(el("p", "stacks-puzzle-clue-text", clue.fallback));
  if (clue.shared) {
    row.appendChild(el("p", "stacks-puzzle-clue-status", "Shared with the party."));
  } else {
    const shareButton = el("button", "stacks-puzzle-share-clue-button", "Share with party");
    shareButton.type = "button";
    shareButton.setAttribute("aria-label", `Share "${clue.fallback}" with the party`);
    shareButton.addEventListener("click", () => handlers.onShareClue(clue.clueId));
    row.appendChild(shareButton);
  }
  return row;
}

// A hero can hold more than one private key-object clue fragment (S10.3 #8),
// plus any clue text learned by inspecting the anchor/contradiction/red
// herring objects (discoveredClues) -- both render as individually
// shareable rows, never merged into one blob.
function renderPrivateClues(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-private-clue");
  panel.setAttribute("aria-label", "Your private clues");
  panel.appendChild(el("h2", "stacks-panel-heading", "Your clues (only you can see these until shared)"));

  const clues = [...puzzle.yourPrivateClues, ...puzzle.discoveredClues];
  if (!clues.length) {
    panel.appendChild(el("p", null, "No clues found yet -- inspect an object."));
    return panel;
  }

  const list = el("ul", "stacks-puzzle-clue-list");
  for (const clue of clues) list.appendChild(renderClueRow(clue, handlers));
  panel.appendChild(list);
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

// The hint route is always visible, in order, before the player asks for
// one -- never a hidden menu revealed only after clicking (S24.4). There is
// no per-tier cost on the wire (request_hint is Energy-free); requesting a
// hint past the last one is how the party accepts the room's force-progress
// consequence (systems/puzzles.py) -- the same button drives both, per the
// domain vocabulary (only request_hint exists, no separate force_progress).
function renderHints(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-hints");
  panel.setAttribute("aria-label", "Hint route");
  panel.appendChild(el("h2", "stacks-panel-heading", "Hints"));

  const list = el("ol", "stacks-puzzle-hint-tiers");
  for (let level = 1; level <= KNOWN_HINT_TOTAL; level += 1) {
    const revealed = puzzle.hintsRevealed[level - 1];
    const item = el("li", "stacks-puzzle-hint-tier" + (revealed ? " is-used" : ""));
    item.appendChild(el("p", "stacks-puzzle-hint-tier-description", revealed ? revealed.fallback : `Hint ${level}: not yet requested.`));
    list.appendChild(item);
  }
  panel.appendChild(list);

  if (!puzzle.canRequestHint) {
    panel.appendChild(el("p", null, puzzle.solved ? "Puzzle solved -- no more hints needed." : "This room has already force-progressed."));
    return panel;
  }

  if (puzzle.hintsRevealed.length >= KNOWN_HINT_TOTAL) {
    panel.appendChild(el("p", "stacks-puzzle-force-progress-consequence", "All hints spent -- requesting again accepts the room's consequence and force-progresses."));
  }
  const requestButton = el(
    "button",
    "stacks-puzzle-request-hint-button",
    puzzle.hintsRevealed.length >= KNOWN_HINT_TOTAL ? "Request hint (force progress)" : "Request next hint",
  );
  requestButton.type = "button";
  requestButton.addEventListener("click", () => handlers.onRequestHint());
  panel.appendChild(requestButton);

  return panel;
}

// Submission is an ordered list the party builds by adding entries (in the
// order they believe is correct) with move-earlier/move-later controls and
// per-entry removal -- never an image-coordinate or color-only input
// (S24.4). The wire projection exposes the puzzle's orderable items as
// puzzles[room_id].items ({item_id, fallback, accessible}, lexicographic --
// order-independent of the solution), so entries are picked from real item
// buttons and submit_solution sends canonical item_ids. When a snapshot
// carries no items list (older servers), the panel falls back to freeform
// text the party transcribes from clue prose.
function renderSubmission(puzzle, handlers) {
  const panel = el("section", "stacks-puzzle-submission");
  panel.setAttribute("aria-label", "Submit solution");
  panel.appendChild(el("h2", "stacks-panel-heading", "Submit solution"));
  const hasWireItems = puzzle.items && puzzle.items.length > 0;
  panel.appendChild(el(
    "p",
    "stacks-puzzle-submission-hint",
    hasWireItems
      ? "Add items in the order you believe is correct."
      : "Add items in the order you believe is correct, using the names from your clues."
  ));

  let items = [];
  const list = el("ol", "stacks-puzzle-submission-list");
  const submitButton = el("button", "stacks-puzzle-submit-button", "Submit solution");

  // Each entry is {itemId, label}: itemId is the canonical wire id when the
  // entry came from the items picker, or null for freeform-fallback text.
  function renderList() {
    list.replaceChildren();
    items.forEach((item, index) => {
      const row = el("li", "stacks-puzzle-submission-item");
      row.appendChild(el("span", "stacks-puzzle-submission-item-text", item.label));
      const upButton = el("button", "stacks-puzzle-submission-item-up", "Move earlier");
      upButton.type = "button";
      upButton.disabled = index === 0;
      upButton.setAttribute("aria-label", `Move "${item.label}" earlier`);
      upButton.addEventListener("click", () => {
        [items[index - 1], items[index]] = [items[index], items[index - 1]];
        renderList();
      });
      row.appendChild(upButton);
      const downButton = el("button", "stacks-puzzle-submission-item-down", "Move later");
      downButton.type = "button";
      downButton.disabled = index === items.length - 1;
      downButton.setAttribute("aria-label", `Move "${item.label}" later`);
      downButton.addEventListener("click", () => {
        [items[index + 1], items[index]] = [items[index], items[index + 1]];
        renderList();
      });
      row.appendChild(downButton);
      const removeButton = el("button", "stacks-puzzle-submission-item-remove", "Remove");
      removeButton.type = "button";
      removeButton.setAttribute("aria-label", `Remove "${item.label}" from the order`);
      removeButton.addEventListener("click", () => {
        items = items.filter((_, i) => i !== index);
        renderList();
      });
      row.appendChild(removeButton);
      list.appendChild(row);
    });
    submitButton.disabled = !puzzle.canSubmit || items.length === 0;
    if (hasWireItems) renderPicker();
  }

  // Wire-items picker: one button per orderable item, disabled once placed.
  const picker = hasWireItems ? el("div", "stacks-puzzle-submission-picker") : null;
  function renderPicker() {
    picker.replaceChildren();
    const pickerLabel = el("p", "stacks-puzzle-submission-picker-label", "Add item to the order");
    picker.appendChild(pickerLabel);
    puzzle.items.forEach((wireItem) => {
      const used = items.some((entry) => entry.itemId === wireItem.itemId);
      const itemButton = el("button", "stacks-puzzle-submission-item-add", wireItem.fallback);
      itemButton.type = "button";
      itemButton.disabled = used || !puzzle.canSubmit;
      itemButton.setAttribute("aria-label", `Add "${wireItem.accessible || wireItem.fallback}" to the order`);
      itemButton.addEventListener("click", () => {
        items = [...items, { itemId: wireItem.itemId, label: wireItem.fallback }];
        renderList();
      });
      picker.appendChild(itemButton);
    });
  }

  renderList();
  panel.appendChild(list);

  if (hasWireItems) {
    panel.appendChild(picker);
  } else {
    const addForm = el("div", "stacks-puzzle-submission-add-form");
    const label = document.createElement("label");
    label.setAttribute("for", "stacks-puzzle-submission-add-input");
    label.textContent = "Add item to the order";
    addForm.appendChild(label);
    const input = document.createElement("input");
    input.id = "stacks-puzzle-submission-add-input";
    input.type = "text";
    input.className = "stacks-puzzle-submission-add-input";
    addForm.appendChild(input);
    const addButton = el("button", "stacks-puzzle-submission-add-button", "Add");
    addButton.type = "button";
    addButton.disabled = !puzzle.canSubmit;
    addButton.addEventListener("click", () => {
      if (!input.value.trim()) return;
      items = [...items, { itemId: null, label: input.value.trim() }];
      input.value = "";
      renderList();
    });
    addForm.appendChild(addButton);
    panel.appendChild(addForm);
  }

  submitButton.type = "button";
  submitButton.addEventListener("click", () => {
    if (!items.length) return;
    handlers.onSubmitSolution(items.map((entry) => entry.itemId !== null ? entry.itemId : entry.label));
  });
  panel.appendChild(submitButton);

  if (typeof puzzle.attemptLimit === "number") {
    panel.appendChild(el("p", "stacks-puzzle-attempts", `Attempts used: ${puzzle.attemptsUsed} of ${puzzle.attemptLimit}`));
  }

  return panel;
}

function renderHeading(puzzle) {
  const heading = el("header", "stacks-puzzle-heading");
  heading.appendChild(el("h1", "stacks-puzzle-title", puzzle.templateId));
  heading.appendChild(el("p", "stacks-puzzle-difficulty", `Difficulty ${puzzle.difficulty}`));
  if (puzzle.solved) heading.appendChild(el("p", "stacks-puzzle-status", "Solved."));
  else if (puzzle.forced) heading.appendChild(el("p", "stacks-puzzle-status", "Force-progressed."));
  return heading;
}

export function renderPuzzleScreen(container, state, handlers) {
  const puzzle = selectPuzzleView(state);
  container.replaceChildren();
  if (!puzzle) return;

  container.appendChild(renderHeading(puzzle));
  const layout = el("div", "stacks-puzzle-layout");
  layout.appendChild(renderObjects(puzzle, handlers));
  layout.appendChild(renderPrivateClues(puzzle, handlers));
  layout.appendChild(renderSharedNotes(puzzle, handlers));
  layout.appendChild(renderHints(puzzle, handlers));
  layout.appendChild(renderSubmission(puzzle, handlers));
  container.appendChild(layout);
}
