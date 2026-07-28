// Guided-flow shell (SPEC stage 13, docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md).
//
// Onboarding, the Persona Foundry, the persona wizard and the contact wizard
// are the same shape: ordered steps, forward/back, a gate somewhere, ending in
// a saved thing. Two of them build the SAME object by different routes. They
// were separate because they were written at different times, not because a
// user thinks of them as different.
//
// So this owns stepping, progress, focus, escape semantics and the footer once,
// and a flow supplies only its steps and a completion action.
//
// The step model is pure and exported separately: "can I advance from here" and
// "what does the primary button say" are the rules most likely to be got wrong,
// and they should be testable without a DOM or a backend.

export const FIRST_STEP = 0;

/**
 * @typedef {object} FlowStep
 * @property {string} id
 * @property {string} title            heading, and the focus target on entry
 * @property {string} [primaryLabel]   footer button text for this step
 * @property {() => boolean} [canAdvance]  gate; absent means always advanceable
 */

// --- Pure step model ---------------------------------------------------------

export function isFirstStep(index) {
  return index <= FIRST_STEP;
}

export function isLastStep(index, steps) {
  return index >= (steps?.length ?? 0) - 1;
}

/**
 * Whether the primary button should be enabled.
 *
 * A step with no `canAdvance` is always advanceable; a step that supplies one
 * is gated by it. Onboarding's consent step is the only current gate, and it is
 * a legal one -- so the default is deliberately permissive and gating is opt-in
 * rather than something every step has to remember to allow.
 */
export function canAdvanceFrom(index, steps) {
  const step = steps?.[index];
  if (!step) return false;
  if (typeof step.canAdvance !== 'function') return true;
  try {
    return Boolean(step.canAdvance());
  } catch (_e) {
    // A throwing gate must not strand the user mid-flow with a dead button.
    return false;
  }
}

/** Label for the primary action; per-step, falling back to Next/Finish. */
export function primaryLabelFor(index, steps) {
  const step = steps?.[index];
  if (step?.primaryLabel) return step.primaryLabel;
  return isLastStep(index, steps) ? 'Finish' : 'Next';
}

/** Next index, clamped. Never advances past a failing gate. */
export function nextIndex(index, steps) {
  if (!canAdvanceFrom(index, steps)) return index;
  return Math.min(index + 1, (steps?.length ?? 1) - 1);
}

export function prevIndex(index) {
  return Math.max(FIRST_STEP, index - 1);
}

/** Progress-dot state per step: 'done' | 'current' | 'upcoming'. */
export function progressStates(index, steps) {
  return (steps || []).map((_step, i) => {
    if (i < index) return 'done';
    if (i === index) return 'current';
    return 'upcoming';
  });
}

// --- DOM wiring --------------------------------------------------------------

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * @param {object} opts
 * @param {HTMLElement} opts.root        the .sd-flow dialog
 * @param {FlowStep[]} opts.steps
 * @param {boolean} [opts.dismissible]   false = Escape is swallowed (a gate)
 * @param {() => void} [opts.onFinish]
 * @param {(step: FlowStep, index: number) => void} [opts.onStepShown]
 */
export function createGuidedFlow({
  root,
  steps = [],
  dismissible = true,
  onFinish,
  onStepShown,
  doc = globalThis.document,
} = {}) {
  let index = FIRST_STEP;
  let opener = null;
  let keydownHandler = null;

  const q = (sel) => root?.querySelector?.(sel) ?? null;

  function render() {
    const step = steps[index];
    if (!step) return;

    // Step elements are addressed by id when the markup supplies one
    // (data-flow-step="interview"), falling back to position otherwise.
    //
    // Position alone is not enough for the persona flow: its two entry paths
    // are different four-step subsets of the same eight-section markup, so
    // "step 2" means a different element depending on how the dialog was
    // opened. Onboarding's markup uses bare data-flow-step and keeps the
    // index behaviour unchanged.
    const stepEls = [...(root?.querySelectorAll?.('[data-flow-step]') || [])];
    const byId = stepEls.some((el) => el.dataset?.flowStep);
    for (const [i, el] of stepEls.entries()) {
      el.hidden = byId ? el.dataset.flowStep !== step.id : i !== index;
    }

    const heading = q('[data-flow-title]');
    if (heading) heading.textContent = step.title || '';

    const dots = [...(root?.querySelectorAll?.('[data-flow-dot]') || [])];
    progressStates(index, steps).forEach((state, i) => {
      if (dots[i]) dots[i].dataset.state = state;
    });

    // The dots are shape, not text, so position has to be stated for anyone who
    // cannot see them. The container carries role="img" and this label rather
    // than each dot announcing itself, which would read as four blank items.
    q('[data-flow-progress]')?.setAttribute?.(
      'aria-label',
      `Step ${index + 1} of ${steps.length}`,
    );

    const back = q('[data-flow-back]');
    if (back) back.hidden = isFirstStep(index);

    const primary = q('[data-flow-primary]');
    if (primary) {
      primary.textContent = primaryLabelFor(index, steps);
      primary.disabled = !canAdvanceFrom(index, steps);
    }

    onStepShown?.(step, index);

    // Focus the heading rather than the first control: it tells a screen-reader
    // user what step they are on before what they can type into.
    heading?.focus?.();
  }

  /** Re-evaluate gates without moving. Call after a gating input changes. */
  function refresh() {
    const primary = q('[data-flow-primary]');
    if (primary) primary.disabled = !canAdvanceFrom(index, steps);
  }

  function goNext() {
    if (!canAdvanceFrom(index, steps)) return;
    if (isLastStep(index, steps)) {
      onFinish?.();
      return;
    }
    index = nextIndex(index, steps);
    render();
  }

  function goBack() {
    index = prevIndex(index);
    render();
  }

  /**
   * Move to a step by id or index, bypassing gates.
   *
   * For flows whose stepping is driven by something other than the footer --
   * the persona wizard and the Persona Foundry both advance on backend results
   * and their own in-body buttons. Gates guard the user's Next button; they are
   * not a lock against the owner that already decided where the user is. An
   * unknown id is a no-op rather than a jump to step 1, because silently
   * rewinding a half-finished interview is worse than not moving.
   */
  function goTo(target) {
    const next = typeof target === 'number'
      ? Math.min(Math.max(FIRST_STEP, target), Math.max(0, steps.length - 1))
      : steps.findIndex((s) => s.id === target);
    if (next < 0) return false;
    index = next;
    render();
    return true;
  }

  function trapTab(event) {
    const focusable = [...(root?.querySelectorAll?.(FOCUSABLE) || [])].filter(
      (el) => el.offsetParent !== null || el === doc.activeElement,
    );
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && doc.activeElement === first) {
      event.preventDefault();
      last.focus?.();
    } else if (!event.shiftKey && doc.activeElement === last) {
      event.preventDefault();
      first.focus?.();
    }
  }

  function onKeydown(event) {
    if (event.key === 'Escape') {
      // A gating flow swallows Escape. Onboarding's consent is a legal gate,
      // not a preference, so there is no back door out of it.
      event.preventDefault();
      if (dismissible) close();
      return;
    }
    if (event.key === 'Tab') trapTab(event);
  }

  /**
   * @param {number|string} [start] step index, or a step id.
   *
   * Accepts an id as well as an index because goTo does, and a caller that
   * learned one form will reach for it here. Passing an id to an index-only
   * version was silent rather than loud -- Math.max(0, 'contactIntro') is NaN,
   * steps[NaN] is undefined, and render() returned early leaving whatever the
   * dialog last showed. An unknown id falls back to the first step: unlike
   * goTo, which must not rewind a flow in progress, opening has nothing to
   * preserve.
   */
  function open(start = FIRST_STEP) {
    opener = doc.activeElement;
    const resolved = typeof start === 'string'
      ? steps.findIndex((s) => s.id === start)
      : start;
    const startIndex = Number.isInteger(resolved) && resolved >= 0 ? resolved : FIRST_STEP;
    index = Math.min(Math.max(FIRST_STEP, startIndex), Math.max(0, steps.length - 1));
    if (root) root.hidden = false;
    keydownHandler = onKeydown;
    doc?.addEventListener?.('keydown', keydownHandler, true);
    render();
  }

  function close() {
    if (root) root.hidden = true;
    if (keydownHandler) doc?.removeEventListener?.('keydown', keydownHandler, true);
    keydownHandler = null;
    // Returning focus to the trigger is what stops a keyboard user being
    // dumped at the top of the document every time they close a dialog.
    opener?.focus?.();
    opener = null;
  }

  function bind() {
    q('[data-flow-primary]')?.addEventListener?.('click', goNext);
    q('[data-flow-back]')?.addEventListener?.('click', goBack);
    q('[data-flow-close]')?.addEventListener?.('click', () => {
      if (dismissible) close();
    });
  }

  bind();

  return {
    open,
    close,
    goNext,
    goBack,
    goTo,
    refresh,
    getIndex: () => index,
    getStep: () => steps[index] ?? null,
  };
}
