const STORAGE_KEY = 'bf_quick_setup_v1_seen';

export const QUICK_SETUP_STEPS = [
  { id: 'talk', title: 'Talk', body: 'Record hands-free, then press ? in the focused window for the local shortcut sheet.', target: '[data-tour-target="talk"]' },
  { id: 'speech', title: 'Speech Input', body: 'Configure recording, push-to-talk, emergency stop, primary action, review TTS, and privacy hotkeys.', target: '[data-tour-target="speech"]' },
  { id: 'models', title: 'Models', body: 'Download and select speech or local language models; dictation remains useful without a local LLM.', target: '[data-tour-target="models"]' },
  { id: 'recording', title: 'Recording', body: 'Choose how recording starts, stops, and handles silence in Settings.', target: '[data-tour-target="recording"]' },
  { id: 'review', title: 'Review & Drafts', body: 'Review drafts before sending, use Review TTS, and keep Selection Rewrite review-only.', target: '[data-tour-target="review"]' },
  { id: 'cleanup', title: 'AI Cleanup', body: 'Turn optional cleanup on when you want a local LLM to polish text without replacing or sending it automatically.', target: '[data-tour-target="cleanup"]' },
  { id: 'privacy', title: 'Privacy', body: 'Review local storage and network controls; replay this tour any time from Settings > Profile.', target: '[data-tour-target="privacy"]' },
];

export function hasSeenQuickSetup(storage = globalThis.localStorage) { return storage?.getItem(STORAGE_KEY) === '1'; }
export function markQuickSetupSeen(storage = globalThis.localStorage) { storage?.setItem(STORAGE_KEY, '1'); }

export function createQuickSetupTour({ doc = document, navigate, storage = globalThis.localStorage } = {}) {
  let index = 0;
  let previousFocus = null;
  let highlightedTarget = null;

  const root = doc.createElement('aside');
  root.className = 'bf-quick-setup';
  root.hidden = true;
  root.setAttribute('aria-live', 'polite');
  root.setAttribute('aria-label', 'Quick Setup');

  const card = doc.createElement('div');
  card.className = 'bf-quick-setup__card';
  card.setAttribute('role', 'region');
  card.setAttribute('aria-labelledby', 'bfQuickSetupTitle');

  const progress = doc.createElement('p');
  progress.className = 'bf-quick-setup__progress';
  const title = doc.createElement('h2');
  title.id = 'bfQuickSetupTitle';
  const body = doc.createElement('p');
  body.className = 'bf-quick-setup__body';
  const actions = doc.createElement('div');
  actions.className = 'bf-quick-setup__actions';

  const backButton = doc.createElement('button');
  backButton.type = 'button';
  backButton.className = 'sd-btn';
  backButton.dataset.action = 'back';
  backButton.textContent = 'Back';
  const skipButton = doc.createElement('button');
  skipButton.type = 'button';
  skipButton.className = 'sd-btn';
  skipButton.dataset.action = 'skip';
  skipButton.textContent = 'Skip';
  const nextButton = doc.createElement('button');
  nextButton.type = 'button';
  nextButton.className = 'sd-btn sd-btn--primary';
  nextButton.dataset.action = 'next';
  nextButton.textContent = 'Next';

  actions.append(backButton, skipButton, nextButton);
  card.append(progress, title, body, actions);
  root.append(card);
  (doc.body || doc.documentElement).append(root);

  const target = () => doc.querySelector(QUICK_SETUP_STEPS[index].target);

  function render() {
    highlightedTarget?.classList.remove('bf-quick-setup-target');
    const step = QUICK_SETUP_STEPS[index];
    progress.textContent = 'Quick Setup: ' + (index + 1) + ' of ' + QUICK_SETUP_STEPS.length;
    title.textContent = step.title;
    body.textContent = step.body;
    backButton.disabled = index === 0;
    nextButton.textContent = index === QUICK_SETUP_STEPS.length - 1 ? 'Done' : 'Next';
    const reducedMotion = doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches;
    highlightedTarget = target();
    highlightedTarget?.classList.add('bf-quick-setup-target');
    highlightedTarget?.scrollIntoView?.({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' });
    nextButton.focus?.({ preventScroll: true });
  }

  function close() {
    markQuickSetupSeen(storage);
    highlightedTarget?.classList.remove('bf-quick-setup-target');
    highlightedTarget = null;
    root.hidden = true;
    const priorCanReceiveFocus = previousFocus
      && previousFocus !== doc.body
      && previousFocus !== doc.documentElement
      && previousFocus.isConnected !== false
      && typeof previousFocus.focus === 'function';
    const focusTarget = priorCanReceiveFocus
      ? previousFocus
      : doc.querySelector('[data-tour-target="talk"]');
    focusTarget?.focus?.();
  }

  function open() {
    previousFocus = doc.activeElement;
    index = 0;
    root.hidden = false;
    navigate?.(QUICK_SETUP_STEPS[index].id);
    render();
  }

  backButton.addEventListener('click', () => {
    if (!index) return;
    index -= 1;
    navigate?.(QUICK_SETUP_STEPS[index].id);
    render();
  });
  skipButton.addEventListener('click', close);
  nextButton.addEventListener('click', () => {
    if (index === QUICK_SETUP_STEPS.length - 1) {
      close();
      return;
    }
    index += 1;
    navigate?.(QUICK_SETUP_STEPS[index].id);
    render();
  });

  const onDocumentKeydown = (event) => { if (!root.hidden && event.key === 'Escape') { event.preventDefault(); close(); } };
  doc.addEventListener('keydown', onDocumentKeydown);
  const destroy = () => {
    doc.removeEventListener?.('keydown', onDocumentKeydown);
    highlightedTarget?.classList.remove('bf-quick-setup-target');
    root.remove?.();
  };

  return {
    open,
    close,
    destroy,
    isOpen: () => !root.hidden,
    shouldAutoRun: () => !hasSeenQuickSetup(storage),
    replay: open,
    root,
  };
}

export { STORAGE_KEY as QUICK_SETUP_STORAGE_KEY };
