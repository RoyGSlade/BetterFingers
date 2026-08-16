// Minimal application-level operation center. Long-running features publish
// stable operation IDs; updates replace in place rather than spawning toasts.

export const TERMINAL_NOTIFICATION_STATES = new Set(['completed', 'cancelled', 'error']);

export function createNotificationState() {
  return { operations: new Map() };
}

export function upsertOperation(state, operation) {
  const id = String(operation?.id || '').trim();
  if (!id) return state;
  const prior = state.operations.get(id) || {};
  const next = {
    id,
    title: String(operation.title || prior.title || 'Operation'),
    state: String(operation.state || prior.state || 'preparing'),
    detail: String(operation.detail ?? prior.detail ?? ''),
    current: Number.isFinite(Number(operation.current)) ? Number(operation.current) : (prior.current || 0),
    total: Number.isFinite(Number(operation.total)) ? Number(operation.total) : (prior.total || 0),
    workspace: String(operation.workspace || prior.workspace || ''),
    updatedAt: Date.now(),
  };
  const operations = new Map(state.operations);
  operations.set(id, next);
  return { operations };
}

export function dismissOperation(state, id) {
  const operations = new Map(state.operations);
  const item = operations.get(id);
  if (!item || !TERMINAL_NOTIFICATION_STATES.has(item.state)) return state;
  operations.delete(id);
  return { operations };
}

export function createAppNotificationCenter({ root, onOpenWorkspace } = {}) {
  let state = createNotificationState();
  const container = root?.getElementById?.('sdOperationCenter');

  function render() {
    if (!container) return;
    container.replaceChildren();
    const operations = [...state.operations.values()].sort((a, b) => b.updatedAt - a.updatedAt);
    container.hidden = operations.length === 0;
    for (const operation of operations) {
      const row = root.createElement('section');
      row.className = 'sd-operation';
      row.dataset.state = operation.state;
      const heading = root.createElement('strong');
      heading.textContent = operation.title;
      const detail = root.createElement('span');
      const progress = operation.total > 0 ? ` · ${operation.current} / ${operation.total}` : '';
      detail.textContent = `${operation.detail}${progress}`;
      row.append(heading, detail);
      if (operation.workspace) {
        const open = root.createElement('button');
        open.type = 'button';
        open.className = 'sd-link-btn';
        open.textContent = 'Open';
        open.addEventListener('click', () => onOpenWorkspace?.(operation.workspace));
        row.append(open);
      }
      if (TERMINAL_NOTIFICATION_STATES.has(operation.state)) {
        const dismiss = root.createElement('button');
        dismiss.type = 'button';
        dismiss.className = 'sd-icon-btn';
        dismiss.setAttribute('aria-label', `Dismiss ${operation.title}`);
        dismiss.textContent = '×';
        dismiss.addEventListener('click', () => {
          state = dismissOperation(state, operation.id);
          render();
        });
        row.append(dismiss);
      }
      container.append(row);
    }
  }

  return {
    update(operation) {
      state = upsertOperation(state, operation);
      render();
    },
    dismiss(id) {
      state = dismissOperation(state, id);
      render();
    },
    getState: () => state,
  };
}
