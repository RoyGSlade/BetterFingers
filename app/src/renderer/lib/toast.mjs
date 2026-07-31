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

// Wave 12: coalescing and a hard cap.
//
// Found by eye in the QA walkbook, not by any assertion — the board was 97/97
// while a screenshot showed SEVEN stacked toasts covering the right half of the
// app, two of them the same message verbatim:
//
//   Could not refresh application profiles: no stub for GET /app-context/profiles
//   Could not refresh Studio personas. Showing the last known data.
//   Could not load the persona list; the preset dropdown may be empty.
//   Could not refresh your contacts. Showing the last known list.
//   Could not refresh Studio personas. Showing the last known data.   <-- again
//   ...
//
// That is this wave's own doing. Making every fetched list report failure
// honestly instead of blanking was right; letting each of those reports become
// its own permanent-until-dismissed toast turned "never a silent blank" into a
// wall the user has to clear before they can see the app. A cold start fires
// every loader at once and the /health re-populate fires them all again, so the
// pile-up is the NORMAL case, not an edge case.
//
// Two rules, both about the same thing — a toast is meant to be glanceable:
//   * identical message+tone coalesces into the live toast and shows a count,
//     rather than repeating itself down the screen;
//   * at most MAX_VISIBLE_TOASTS are on screen; the oldest is retired to make
//     room, because the newest message is the one describing what just
//     happened.
//
// The deeper fix belongs in the callers: a BACKGROUND refresh failing is not a
// user action and should generally paint in-panel state rather than toast at
// all. That is noted in the handoff as follow-up; this keeps the shared surface
// survivable in the meantime and is not a substitute for it.
export const MAX_VISIBLE_TOASTS = 4;

/**
 * Show a transient message.
 *
 * @param {string} message   text to display; falsy is ignored
 * @param {'info'|'success'|'warning'|'error'} [tone]
 * @param {number} [durationMs] auto-dismiss delay; <=0 means stay until closed
 * @param {Document} [doc] injectable for tests
 * @param {{onClick?: Function, actionLabel?: string}} [options] optional
 *   click-through action, rendered as a second button alongside dismiss.
 *   Activating it both runs `onClick` and dismisses the toast -- an
 *   informational-only toast (no onClick) renders exactly as before.
 * @returns {HTMLElement|undefined} the toast element, if one was created
 */
export function showToast(message, tone = 'info', durationMs = 5000, doc = globalThis.document, options = {}) {
  const container = doc?.getElementById?.(TOAST_CONTAINER_ID);
  if (!container || !message) {
    return;
  }

  const text_ = String(message);
  const { onClick, actionLabel } = options || {};

  // Coalesce: an identical message already on screen gets its timer restarted
  // and a count, instead of a second copy of itself. Matched on message AND
  // tone so the same wording at a different severity still stands out.
  const live = Array.from(container.children || []);
  const twin = live.find(
    (el) => el?.dataset?.tone === tone && el?.dataset?.toastMessage === text_,
  );
  if (twin) {
    const count = Number(twin.dataset.toastCount || '1') + 1;
    twin.dataset.toastCount = String(count);
    const label = twin.querySelector?.('.toast-message');
    if (label) label.textContent = `${text_} (${count}×)`;
    twin.__bfRestartTimer?.();
    return twin;
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

  // The click-through: a second button, not a click handler on the whole
  // toast -- keyboard/screen-reader reachable, and it can never be confused
  // with dismissing the message it sits next to.
  let action = null;
  if (typeof onClick === 'function') {
    action = doc.createElement('button');
    action.className = 'toast-action';
    action.type = 'button';
    action.textContent = actionLabel || 'Fix this';
    action.addEventListener('click', () => {
      onClick();
      dismiss();
    });
  }

  toast.append(text, ...(action ? [action] : []), close);
  toast.dataset.toastMessage = text_;
  toast.dataset.toastCount = '1';
  container.append(toast);

  // Cap the stack. The OLDEST goes: the newest message describes what just
  // happened, and on a cold start the early ones are the generic
  // "backend isn't up yet" reports the later, more specific ones supersede.
  const overflow = Array.from(container.children || []).length - MAX_VISIBLE_TOASTS;
  for (let i = 0; i < overflow; i += 1) {
    const oldest = container.children[i];
    if (oldest && oldest !== toast) oldest.remove();
  }

  const startTimer = () => {
    if (removeTimer) clearTimeout(removeTimer);
    removeTimer = durationMs > 0 ? setTimeout(dismiss, durationMs) : null;
  };
  // Exposed so a coalesced repeat can restart the countdown: a message that is
  // still happening should stay up, not vanish on the first one's schedule.
  toast.__bfRestartTimer = startTimer;
  startTimer();
  return toast;
}
