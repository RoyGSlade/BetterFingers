// Shared explicit-confirm step (playtest A4: "playing requires an explicit
// target + confirm step" / C1: "Energy cost shown at the point of click and
// a confirm"). Renders core/store.js's pendingAction as an inline bar with
// its own Confirm/Cancel controls -- nothing that stages a pendingAction
// (room-tile clicks, hand-card play) ever calls sendCommand directly; only
// this bar's Confirm button does, via the handler passed in.

export function renderConfirmBar(pendingAction, { onConfirm, onCancel } = {}) {
  if (!pendingAction) return null;
  const bar = document.createElement("div");
  bar.className = "stacks-confirm-bar";
  bar.setAttribute("role", "alertdialog");
  bar.setAttribute("aria-label", "Confirm action");

  const text = document.createElement("p");
  text.className = "stacks-confirm-text";
  text.textContent = pendingAction.label;
  bar.appendChild(text);

  const actions = document.createElement("div");
  actions.className = "stacks-confirm-actions";

  const confirmButton = document.createElement("button");
  confirmButton.type = "button";
  confirmButton.className = "stacks-confirm-button";
  confirmButton.textContent = pendingAction.confirmLabel || "Confirm";
  confirmButton.addEventListener("click", () => onConfirm(pendingAction));
  actions.appendChild(confirmButton);

  const cancelButton = document.createElement("button");
  cancelButton.type = "button";
  cancelButton.className = "stacks-confirm-cancel-button";
  cancelButton.textContent = "Cancel";
  cancelButton.addEventListener("click", () => onCancel());
  actions.appendChild(cancelButton);

  bar.appendChild(actions);
  return bar;
}
