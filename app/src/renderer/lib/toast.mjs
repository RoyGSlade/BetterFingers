// Transient toast notifications — the app-wide way to surface events/errors
// that would otherwise only reach the console.
//
// Extracted from main.js so BOTH dashboards can use one implementation. Every
// Signal Desk workspace module already calls `hooks.showToast(...)`, but that
// page had no #toastContainer and no toast function, so all of them were
// reporting success and failure into the void — a user could click Save,
// Delete, or Publish and get no feedback either way.
//
// main.js keeps its `showToast` name by re-exporting this (a rule-7
// compatibility wrapper), so the ~40 existing call sites there are unchanged.
//
// Container-less by contract: if the host page has no mount point the call is
// a silent no-op rather than a throw, matching the original behaviour — a
// missing toast must never break the flow that was trying to report.

export const TOAST_CONTAINER_ID = 'toastContainer';

/**
 * Show a transient message.
 *
 * @param {string} message   text to display; falsy is ignored
 * @param {'info'|'success'|'warning'|'error'} [tone]
 * @param {number} [durationMs] auto-dismiss delay; <=0 means stay until closed
 * @param {Document} [doc] injectable for tests
 * @returns {HTMLElement|undefined} the toast element, if one was created
 */
export function showToast(message, tone = 'info', durationMs = 5000, doc = globalThis.document) {
  const container = doc?.getElementById?.(TOAST_CONTAINER_ID);
  if (!container || !message) {
    return;
  }

  const toast = doc.createElement('div');
  toast.className = 'toast';
  toast.dataset.tone = tone;

  const text = doc.createElement('div');
  text.className = 'toast-message';
  text.textContent = String(message);

  const close = doc.createElement('button');
  close.className = 'toast-close';
  close.type = 'button';
  close.setAttribute('aria-label', 'Dismiss notification');
  close.textContent = '×';

  let removeTimer = null;
  const dismiss = () => {
    if (removeTimer) {
      clearTimeout(removeTimer);
      removeTimer = null;
    }
    toast.classList.add('leaving');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
    // Fallback in case the animation doesn't fire.
    setTimeout(() => toast.remove(), 250);
  };

  close.addEventListener('click', dismiss);
  toast.append(text, close);
  container.append(toast);

  if (durationMs > 0) {
    removeTimer = setTimeout(dismiss, durationMs);
  }
  return toast;
}
