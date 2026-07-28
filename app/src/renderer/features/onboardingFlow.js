// First-run onboarding as a guided flow (stage 13 step 2).
//
// Content is unchanged from the shipping overlay (main.js:976): Welcome ->
// data-stays-here consent -> how it works -> speech models. What changes is
// that the stepping, progress, focus and Escape semantics come from
// features/guidedFlow.js instead of a second hand-rolled implementation, and
// the step bodies live in markup rather than in template strings.
//
// That last part matters beyond tidiness: the shipping version builds every
// step body with innerHTML and therefore needs escapeHtml() around each piece
// of backend-supplied text in the recommendation box. Markup + textContent has
// no such hazard to remember.
//
// This is the only flow with dismissible: false. The consent step is a legal
// gate, so Escape is swallowed and there is no close button in its markup.

import { createGuidedFlow } from './guidedFlow.js';

// ONBOARDING_FLAG / shouldShowOnboarding / markOnboardingComplete are the
// LEGACY renderer-local path (localStorage only -- it dies with the renderer
// profile and cannot record legal consent). The durable path lives in
// features/onboardingConsent.js against the main-process store; the legacy
// flag is now read only ONCE, by onboardingConsent's migration, to carry a
// returning user's prior completion into the durable store. Do not add new
// callers of this flag -- gate and complete through the `consent` seam below.
export const ONBOARDING_FLAG = 'bf_onboarding_complete';

/**
 * Whether onboarding should run. A storage that throws (private mode, wiped
 * profile) reads as "not yet completed": showing the gate twice is a small
 * annoyance, skipping it is a consent failure.
 */
export function shouldShowOnboarding(storage) {
  try {
    return storage?.getItem?.(ONBOARDING_FLAG) !== 'true';
  } catch (_e) {
    return true;
  }
}

export function markOnboardingComplete(storage) {
  try {
    storage?.setItem?.(ONBOARDING_FLAG, 'true');
    return true;
  } catch (_e) {
    // Non-fatal; onboarding may show again next launch.
    return false;
  }
}

/** 'present' | 'missing' — mirrors main.js's downloaded-or-installed test. */
export function speechModelState(payload) {
  const models = payload?.models;
  if (!Array.isArray(models)) return 'missing';
  return models.some((m) => m?.downloaded || m?.installed) ? 'present' : 'missing';
}

/**
 * Steps for the shell. Only consent gates; the rest are informational, and
 * per guidedFlow's contract a step with no `canAdvance` is advanceable.
 */
export function buildOnboardingSteps({ isConsented = () => false } = {}) {
  return [
    { id: 'welcome', title: 'Welcome to BetterFingers', primaryLabel: 'Get started' },
    {
      id: 'consent',
      title: 'Your data stays on this device',
      primaryLabel: 'Accept & continue',
      canAdvance: () => Boolean(isConsented()),
    },
    { id: 'how', title: 'How it works', primaryLabel: 'Next' },
    { id: 'models', title: 'Speech models', primaryLabel: 'Finish' },
  ];
}

/**
 * Render the hardware-aware model recommendation into `box`.
 * Built from DOM nodes rather than markup so backend strings are never parsed
 * as HTML. Returns false when there is nothing to show, leaving the box hidden.
 */
export function renderRecommendation(box, payload, doc = globalThis.document) {
  const rec = payload?.recommendation;
  if (!box || !rec) return false;

  const llm = rec.llm?.models?.find((m) => m.id === rec.llm?.recommended);
  const llmName = llm?.name ?? rec.llm?.recommended ?? '—';
  const llmNote = llm?.note ? ` — ${llm.note}` : '';

  const frag = doc.createDocumentFragment();

  const heading = doc.createElement('strong');
  heading.textContent = `Recommended for your hardware (${rec.tier_label ?? rec.tier ?? 'unknown'})`;
  frag.append(heading);

  if (rec.tier_guidance) {
    const note = doc.createElement('p');
    note.className = 'sd-onboard__note';
    note.textContent = rec.tier_guidance;
    frag.append(note);
  }

  const list = doc.createElement('ul');
  for (const [label, value] of [
    ['Language model:', `${llmName}${llmNote}`],
    ['Speech model:', rec.whisper?.recommended ?? '—'],
  ]) {
    const item = doc.createElement('li');
    const strong = doc.createElement('strong');
    strong.textContent = label;
    item.append(strong, ` ${value}`);
    list.append(item);
  }
  frag.append(list);

  box.textContent = '';
  box.append(frag);
  box.hidden = false;
  return true;
}

export function collectOnboardingElements(doc = globalThis.document) {
  const $ = (id) => doc.getElementById(id);
  return {
    root: $('sdOnboarding'),
    consent: $('sdOnboardConsent'),
    decline: $('sdOnboardDecline'),
    recommendation: $('sdOnboardRecommendation'),
    modelsPresent: $('sdOnboardModelsPresent'),
    modelsMissing: $('sdOnboardModelsMissing'),
  };
}

/**
 * @param {object} opts
 * @param {ReturnType<typeof collectOnboardingElements>} opts.elements
 * @param {Storage} [opts.storage] legacy path, used when `consent`/`isConsented`/`shouldShow` are absent
 * @param {object} [opts.hooks]
 *   quitApp()               — Decline & quit (legacy path, or when `consent` has no decline())
 *   fetchRecommendation()   — U4 hardware tier; failure leaves the box hidden
 *   fetchWhisperModels()    — decides which "speech models" paragraph shows
 *   onComplete()            — after completion is confirmed (durable accept ok, or legacy flag written)
 *   onConsentError(err)     — a durable consent accept() or decline() failed; the gate stays open / app does not quit
 * @param {() => boolean} [opts.isConsented]
 *   Durable-state seam: when supplied, gates the consent step instead of the
 *   checkbox alone (see features/onboardingConsent.js's needsConsent). Falls
 *   back to `elements.consent?.checked` when absent.
 * @param {{accept: () => Promise<{ok: boolean}>, decline?: () => Promise<{ok: boolean}>}} [opts.consent]
 *   Durable-state seam: when supplied, its accept() records completion in the
 *   durable store instead of the legacy localStorage flag, and the gate only
 *   closes once accept() confirms {ok: true} -- a failed or throwing write
 *   leaves the flow open and reports through onConsentError instead. When it
 *   also exposes decline(), the Decline button routes through it instead of
 *   calling hooks.quitApp() directly.
 * @param {() => boolean} [opts.shouldShow]
 *   Durable-state seam: when supplied, init() gates on this instead of the
 *   legacy localStorage flag (see features/onboardingConsent.js's
 *   resolveOnboardingGate). Defaults to `() => shouldShowOnboarding(storage)`,
 *   i.e. omitting it reproduces today's legacy behavior exactly.
 */
export function createOnboardingFlow({
  elements = {},
  storage = globalThis.localStorage,
  hooks = {},
  doc = globalThis.document,
  consent = null,
  isConsented,
  shouldShow = () => shouldShowOnboarding(storage),
} = {}) {
  const steps = buildOnboardingSteps({
    isConsented: isConsented ?? (() => Boolean(elements.consent?.checked)),
  });

  let flow = null;

  // The speech-models step reports live state, so it is re-checked on entry
  // rather than captured once at init: a user can install a model in another
  // window while onboarding sits open on step 1.
  async function enterModelsStep() {
    try {
      const state = speechModelState(await hooks.fetchWhisperModels?.());
      if (elements.modelsPresent) elements.modelsPresent.hidden = state !== 'present';
      if (elements.modelsMissing) elements.modelsMissing.hidden = state === 'present';
    } catch (_e) {
      // Unknown state reads as "missing": telling a user without a model that
      // they are ready to go is the worse of the two wrong answers.
      if (elements.modelsPresent) elements.modelsPresent.hidden = true;
      if (elements.modelsMissing) elements.modelsMissing.hidden = false;
    }

    try {
      const payload = await hooks.fetchRecommendation?.();
      // The user may have stepped back while the request was in flight --
      // don't populate a box that is no longer on screen.
      if (elements.recommendation?.isConnected === false) return;
      renderRecommendation(elements.recommendation, payload, doc);
    } catch (_e) {
      // Recommendation is a nice-to-have; leave the box hidden.
    }
  }

  // Legacy path branches early and returns before any `await`, so its side
  // effects (flag write, close, onComplete) still happen synchronously --
  // async only changes behavior for callers that supply `consent`.
  async function finish() {
    if (!consent) {
      markOnboardingComplete(storage);
      flow?.close();
      hooks.onComplete?.();
      return;
    }

    let result;
    try {
      result = await consent.accept();
    } catch (e) {
      hooks.onConsentError?.(e);
      return;
    }

    if (result?.ok === true) {
      flow?.close();
      hooks.onComplete?.();
    } else {
      hooks.onConsentError?.(new Error('durable consent write failed'));
    }
  }

  flow = createGuidedFlow({
    root: elements.root,
    steps,
    dismissible: false,
    doc,
    onFinish: finish,
    onStepShown: (step) => {
      if (step.id === 'models') enterModelsStep();
    },
  });

  // Bound at construction, not inside init(), and deliberately so: binding on
  // open would leave the dialog half-live for any caller that opens it by some
  // other route (QA, the debug handle, a future "review the policy again"
  // entry) -- the steps would advance but the consent checkbox would be inert,
  // which looks exactly like a gate that cannot be satisfied. createGuidedFlow
  // binds its own footer the same way.
  //
  // Re-evaluating on change is what makes the checkbox a live control rather
  // than one that only takes effect on the next re-render.
  elements.consent?.addEventListener?.('change', () => flow.refresh());
  elements.decline?.addEventListener?.('click', () => {
    if (typeof consent?.decline === 'function') {
      Promise.resolve(consent.decline())
        .then((result) => {
          if (!result?.ok) hooks.onConsentError?.(new Error('durable consent decline failed'));
        })
        .catch((e) => hooks.onConsentError?.(e));
    } else {
      hooks.quitApp?.();
    }
  });

  /** @returns {boolean} whether onboarding was shown. */
  function init() {
    if (!elements.root) return false;
    if (!shouldShow()) return false;
    flow.open();
    return true;
  }

  return { init, finish, flow, steps };
}
