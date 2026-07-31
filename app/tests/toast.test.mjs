// Unit tests for the extracted shared toast (lib/toast.mjs).
//
// Extracted from main.js so both dashboards share one implementation. The
// container-less no-op is the important contract: it is why every Signal Desk
// workspace could call hooks.showToast for months and produce nothing.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { showToast, TOAST_CONTAINER_ID, MAX_VISIBLE_TOASTS } from '../src/renderer/lib/toast.mjs';

/** Minimal DOM double — enough for the element-building path, no jsdom needed. */
function makeDoc({ withContainer = true } = {}) {
  const makeEl = () => {
    const el = {
      className: '',
      type: '',
      textContent: '',
      dataset: {},
      children: [],
      attrs: {},
      classList: { added: [], add(c) { this.added.push(c); } },
      listeners: {},
      setAttribute(k, v) { this.attrs[k] = v; },
      addEventListener(evt, fn) { (this.listeners[evt] ||= []).push(fn); },
      // append/remove keep the parent link honest. The original double recorded
      // `removed = true` without detaching, which made it impossible to test
      // anything about how many toasts are actually ON SCREEN -- and the stack
      // cap is precisely a statement about that count.
      append(...kids) {
        for (const kid of kids) {
          kid.parent = this;
          this.children.push(kid);
        }
      },
      remove() {
        this.removed = true;
        const siblings = this.parent?.children;
        if (siblings) {
          const at = siblings.indexOf(this);
          if (at !== -1) siblings.splice(at, 1);
        }
      },
      querySelector(selector) {
        const wanted = selector.replace(/^\./, '');
        return this.children.find((kid) => kid.className === wanted) || null;
      },
    };
    return el;
  };
  const container = makeEl();
  return {
    container,
    createElement: () => makeEl(),
    getElementById: (id) => (withContainer && id === TOAST_CONTAINER_ID ? container : null),
  };
}

test('renders a toast into the container', () => {
  const doc = makeDoc();
  const toast = showToast('Saved.', 'success', 0, doc);

  assert.ok(toast, 'expected a toast element');
  assert.equal(doc.container.children.length, 1);
  assert.equal(toast.dataset.tone, 'success');

  const [message, close] = toast.children;
  assert.equal(message.textContent, 'Saved.');
  assert.equal(close.attrs['aria-label'], 'Dismiss notification');
});

test('is a silent no-op when the host page has no container', () => {
  // This is exactly the Signal Desk situation before the container was added:
  // the call must not throw, but it also must not pretend to have worked.
  const doc = makeDoc({ withContainer: false });
  assert.equal(showToast('Saved.', 'info', 0, doc), undefined);
});

test('ignores empty messages rather than rendering a blank toast', () => {
  const doc = makeDoc();
  assert.equal(showToast('', 'info', 0, doc), undefined);
  assert.equal(showToast(null, 'info', 0, doc), undefined);
  assert.equal(doc.container.children.length, 0);
});

test('defaults to the info tone', () => {
  const doc = makeDoc();
  assert.equal(showToast('Note.', undefined, 0, doc).dataset.tone, 'info');
});

test('coerces non-string messages instead of dropping them', () => {
  const doc = makeDoc();
  assert.equal(showToast(42, 'info', 0, doc).children[0].textContent, '42');
});

test('dismiss marks the toast leaving', () => {
  const doc = makeDoc();
  const toast = showToast('Bye.', 'info', 0, doc);
  const close = toast.children[1];

  close.listeners.click[0]();
  assert.ok(toast.classList.added.includes('leaving'));
});

test('does not throw when the document itself is unusable', () => {
  // Guards the optional-chaining in the container lookup.
  assert.equal(showToast('x', 'info', 0, undefined), undefined);
  assert.equal(showToast('x', 'info', 0, {}), undefined);
});

// --- Wave 12: coalescing and the stack cap -----------------------------------
//
// Caught by LOOKING at the QA walkbook rather than by any assertion: the board
// was 97/97 while a screenshot showed seven stacked toasts covering the right
// half of the app, two of them the same message verbatim. Making every fetched
// list report its failure honestly was right; letting each report become its
// own toast turned "never a silent blank" into a wall the user must clear
// before they can see the app. A cold start fires every loader at once and the
// /health re-populate fires them all again, so the pile-up is the normal case.

test('an identical message coalesces into the live toast with a count', () => {
  const doc = makeDoc();
  const first = showToast('Could not refresh Studio personas.', 'warning', 0, doc);
  const again = showToast('Could not refresh Studio personas.', 'warning', 0, doc);

  assert.equal(again, first, 'the repeat must reuse the live toast, not make a second one');
  assert.equal(doc.container.children.length, 1, 'the same message must not stack');
  assert.equal(first.children[0].textContent, 'Could not refresh Studio personas. (2×)');

  showToast('Could not refresh Studio personas.', 'warning', 0, doc);
  assert.equal(first.children[0].textContent, 'Could not refresh Studio personas. (3×)');
});

test('the same wording at a different tone is NOT coalesced', () => {
  // A warning becoming an error is a change the user needs to see, not a
  // silent increment on the thing they already read past.
  const doc = makeDoc();
  showToast('Backend unreachable.', 'warning', 0, doc);
  showToast('Backend unreachable.', 'error', 0, doc);
  assert.equal(doc.container.children.length, 2);
});

test('the visible stack is capped, retiring the oldest', () => {
  const doc = makeDoc();
  const messages = ['one', 'two', 'three', 'four', 'five', 'six', 'seven'];
  for (const message of messages) showToast(message, 'warning', 0, doc);

  assert.equal(doc.container.children.length, MAX_VISIBLE_TOASTS);
  const shown = doc.container.children.map((el) => el.children[0].textContent);
  assert.deepEqual(shown, ['four', 'five', 'six', 'seven'],
    'the newest messages survive; the oldest are retired');
});

test('the cap never retires the toast it was just asked to show', () => {
  // The guard against an off-by-one that would drop the newest message on the
  // floor -- the one describing what just happened.
  const doc = makeDoc();
  for (const message of ['a', 'b', 'c', 'd', 'e']) showToast(message, 'info', 0, doc);
  const newest = doc.container.children[doc.container.children.length - 1];
  assert.equal(newest.children[0].textContent, 'e');
  assert.ok(!newest.removed);
});

test('a coalesced repeat restarts the auto-dismiss countdown', async () => {
  // A condition that is STILL happening must keep its toast up rather than
  // disappear on the first occurrence's schedule.
  const doc = makeDoc();
  const toast = showToast('Still failing.', 'warning', 40, doc);
  await new Promise((resolve) => setTimeout(resolve, 25));
  showToast('Still failing.', 'warning', 40, doc);   // restarts the 40ms clock
  await new Promise((resolve) => setTimeout(resolve, 25));
  assert.ok(!toast.classList.added.includes('leaving'), 'must not have dismissed on the original timer');
});

// --- click-through action (OR-06: the no-input-signal toast) ----------------

test('with no options argument, a toast renders exactly message + dismiss, unchanged from before', () => {
  const doc = makeDoc();
  const toast = showToast('Saved.', 'success', 0, doc);
  assert.equal(toast.children.length, 2);
  assert.equal(toast.children[1].className, 'toast-close');
});

test('an onClick option renders a third, clickable action button between the message and dismiss', () => {
  const doc = makeDoc();
  const toast = showToast("I can't hear you.", 'warning', 0, doc, {
    onClick: () => {},
    actionLabel: 'Open Sound Settings',
  });
  assert.equal(toast.children.length, 3);
  const [message, action, close] = toast.children;
  assert.equal(message.textContent, "I can't hear you.");
  assert.equal(action.className, 'toast-action');
  assert.equal(action.textContent, 'Open Sound Settings');
  assert.equal(close.className, 'toast-close');
});

test('an onClick option with no actionLabel falls back to a generic label', () => {
  const doc = makeDoc();
  const toast = showToast('Needs attention.', 'warning', 0, doc, { onClick: () => {} });
  assert.equal(toast.children[1].textContent, 'Fix this');
});

test('activating the action button runs onClick AND dismisses the toast', () => {
  const doc = makeDoc();
  let clicked = 0;
  const toast = showToast("I can't hear you.", 'warning', 0, doc, {
    onClick: () => { clicked += 1; },
    actionLabel: 'Open Sound Settings',
  });
  const action = toast.children[1];
  action.listeners.click[0]();
  assert.equal(clicked, 1, 'onClick must have run');
  assert.ok(toast.classList.added.includes('leaving'), 'the toast must also dismiss itself');
});

test('clicking dismiss (not the action button) does not run onClick', () => {
  const doc = makeDoc();
  let clicked = 0;
  const toast = showToast("I can't hear you.", 'warning', 0, doc, { onClick: () => { clicked += 1; } });
  const close = toast.children[2];
  close.listeners.click[0]();
  assert.equal(clicked, 0, 'dismissing the toast must not trigger the click-through action');
  assert.ok(toast.classList.added.includes('leaving'));
});
