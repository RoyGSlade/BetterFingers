// Inline status-message helper, shared.
//
// Extracted from main.js:947 for the same reason showToast was: feature modules
// take `setMessage` as a ui hook, and every page that mounts one has to supply
// it. The Signal Desk preview had grown its own copy which looked equivalent
// but was not -- it set `data-tone` and never removed it, so an element that
// once showed an error kept its red styling under every later success message.
//
// One implementation, so there is nothing to diverge.

/**
 * Write `message` into `el` and set/clear its tone.
 *
 * @param {HTMLElement|null|undefined} el
 * @param {string} [message] text content; '' clears it
 * @param {string} [tone] 'success' | 'warning' | 'danger' | ''; falsy REMOVES
 *   the attribute rather than leaving the previous one in place
 */
export function setMessage(el, message = '', tone = '') {
  if (!el) {
    return;
  }

  el.textContent = message;
  if (tone) {
    el.dataset.tone = tone;
  } else {
    delete el.dataset.tone;
  }
}
