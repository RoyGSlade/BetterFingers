// Game setup wizard (Wave 10, deliverable 3) — Utilities › Advanced › Game Setup.
//
// Seven steps, in this order, because the order is the safety property:
//
//   detect -> dictation binding -> command binding -> game chat key
//   -> delivery choice -> anti-cheat warning -> rehearsal -> save
//
// THE REHEARSAL CAN NEVER SEND. That is the requirement, and it is enforced
// three ways rather than one, because "we remembered not to" is not an
// enforcement:
//
//   1. The rehearsal posts to /input/dispatch with `rehearsal: true`, and the
//      backend answers it with `input_dispatch.rehearsal_dispatcher()` — an
//      object constructed with an EMPTY handler table. There is no callable to
//      reach, so there is nothing to disable and nothing a later edit could
//      re-enable by flipping a flag.
//   2. This module has no send/inject method and never imports one. `REHEARSAL_
//      FORBIDDEN_ACTIONS` names the ids it will not even transmit, and a test
//      walks every id in the vocabulary against it.
//   3. The state machine cannot reach `saved` from `rehearsal` without the user
//      pressing Save, and cannot reach `rehearsal` at all until the warning has
//      been acknowledged.
//
// WHY A CHAT KEY IS RECORDED AND NOT DETECTED. Every game opens its chat with a
// different key and no game tells anybody which. Asking the user is the only
// honest way to know, and it is also the only way that does not involve reading
// the focused window's contents.
//
// THE ANTI-CHEAT WARNING IS NOT DISMISSIBLE BY DEFAULT. Anti-cheat systems
// classify synthetic keystrokes as input automation; some ban for it. The
// warning is a required acknowledgement, and the wizard's own recommendation is
// the delivery mode that never synthesises input at all. That recommendation is
// a pure function so it cannot drift from what the text says.

export const WIZARD_ELEMENT_IDS = {
  section: 'sdUtilGameSetupGroup',
  unavailable: 'sdUtilGameSetupUnavailable',
  stepLabel: 'sdUtilGameSetupStep',
  deviceList: 'sdUtilGameSetupDevices',
  detectButton: 'sdUtilGameSetupDetectButton',
  recordDictationButton: 'sdUtilGameSetupRecordDictation',
  recordCommandButton: 'sdUtilGameSetupRecordCommand',
  dictationValue: 'sdUtilGameSetupDictationValue',
  commandValue: 'sdUtilGameSetupCommandValue',
  chatKeyInput: 'sdUtilGameSetupChatKey',
  deliverySelect: 'sdUtilGameSetupDelivery',
  warning: 'sdUtilGameSetupWarning',
  acknowledge: 'sdUtilGameSetupAcknowledge',
  rehearseButton: 'sdUtilGameSetupRehearseButton',
  rehearsalLog: 'sdUtilGameSetupRehearsalLog',
  profileNameInput: 'sdUtilGameSetupProfileName',
  saveButton: 'sdUtilGameSetupSaveButton',
  message: 'sdUtilGameSetupMessage',
};

const REQUIRED_API_METHODS = [
  'fetchInputVocabulary',
  'fetchInputBindings',
  'setInputBinding',
  'dispatchInputAction',
  'saveAppProfile',
];

/** The seven steps, in order. Exported so the UI cannot invent an eighth. */
export const STEPS = [
  'detect',
  'dictation',
  'command',
  'chat_key',
  'delivery',
  'warning',
  'rehearsal',
  'saved',
];

/**
 * Delivery modes, mirrored from backend/stores/app_profiles.py INJECTION_POLICIES.
 *
 * Only the three that make sense in a game are offered. `auto` and `paste` are
 * deliberately absent: "let BetterFingers decide" is not an answer a user can
 * weigh against an anti-cheat risk, and paste is a synthesised keystroke with
 * extra steps.
 */
export const DELIVERY_MODES = {
  review_only: {
    id: 'review_only',
    label: 'Review first (safest)',
    synthesises_input: false,
    note: 'Nothing reaches the game on its own. You read the draft and send it yourself.',
  },
  clipboard_only: {
    id: 'clipboard_only',
    label: 'Copy to clipboard',
    synthesises_input: false,
    note: 'BetterFingers copies the text. You paste it into the game with your own keyboard.',
  },
  type: {
    id: 'type',
    label: 'Type it into the game',
    synthesises_input: true,
    note: 'BetterFingers types the text for you. Some anti-cheat systems treat this as input '
      + 'automation, and a few ban accounts for it.',
  },
};

export const DEFAULT_DELIVERY = 'review_only';

/**
 * Ids the rehearsal will not transmit under any circumstances.
 *
 * `latest.inject` is the obvious one — it delivers text to whatever has focus,
 * which during a rehearsal is a game. `emergency.stop` is the less obvious one
 * and matters just as much: a rehearsal must not stop a recording the user never
 * started, so even the panic button is inert here. That is why the rehearsal
 * uses an empty handler table rather than the ordinary `suspend`, which has an
 * exception for exactly that id.
 */
export const REHEARSAL_FORBIDDEN_ACTIONS = ['latest.inject', 'emergency.stop'];

export const ANTI_CHEAT_WARNING =
  'Some games ban accounts for input automation. BetterFingers typing into a game is '
  + 'input automation, however it is meant. Review first and Copy to clipboard never '
  + 'synthesise a keystroke, so neither can be detected as one — they are what '
  + 'BetterFingers recommends for any game with anti-cheat.';

/** True when the chosen mode is the one that can get somebody banned. */
export function deliveryNeedsWarning(mode) {
  return Boolean(DELIVERY_MODES[mode] && DELIVERY_MODES[mode].synthesises_input);
}

/** The recommendation, as a function, so it cannot drift from the warning text. */
export function recommendedDelivery() {
  return DEFAULT_DELIVERY;
}

export function computeAvailability(api) {
  const missing = REQUIRED_API_METHODS.filter((name) => typeof api?.[name] !== 'function');
  if (missing.length === 0) return { available: true, reason: '' };
  return {
    available: false,
    reason: 'Game setup is not reachable in this build, so no controller binding can be '
      + 'recorded or saved here.',
  };
}

/**
 * What the wizard may do next, as a pure function over its state.
 *
 * Enabling controls ad hoc as handlers fire is how "Save" ends up live for one
 * repaint before the warning was acknowledged. Everything gates on this.
 */
export function computeWizardState(state = {}) {
  const hasDevice = Boolean(state.deviceKey);
  const hasDictation = Boolean(state.dictationBinding);
  const hasCommand = Boolean(state.commandBinding);
  const hasChatKey = Boolean(String(state.chatKey || '').trim());
  const mode = state.delivery || DEFAULT_DELIVERY;
  const known = Boolean(DELIVERY_MODES[mode]);
  // The acknowledgement is only REQUIRED for the risky mode, but it is always
  // OFFERED — a user who reads the warning and picks the safe option should not
  // have to click a checkbox to be told they are safe.
  const warningSatisfied = !deliveryNeedsWarning(mode) || Boolean(state.acknowledged);

  let step = 'detect';
  if (state.saved) step = 'saved';
  else if (hasDevice && hasDictation && hasCommand && hasChatKey && known && warningSatisfied) {
    step = 'rehearsal';
  } else if (hasDevice && hasDictation && hasCommand && hasChatKey && known) step = 'warning';
  else if (hasDevice && hasDictation && hasCommand && hasChatKey) step = 'delivery';
  else if (hasDevice && hasDictation && hasCommand) step = 'chat_key';
  else if (hasDevice && hasDictation) step = 'command';
  else if (hasDevice) step = 'dictation';

  return {
    step,
    canRecordDictation: hasDevice,
    // Recording the command binding is unlocked by the dictation one, which is
    // how the "separate bindings at minimum" rule shows up in the UI: you cannot
    // finish the wizard having bound only one, and you cannot bind them to the
    // same thing without the second recording overwriting the first visibly.
    canRecordCommand: hasDevice && hasDictation,
    canChooseDelivery: hasDevice && hasDictation && hasCommand && hasChatKey,
    needsWarning: deliveryNeedsWarning(mode),
    warningSatisfied,
    canRehearse: step === 'rehearsal' || step === 'saved',
    canSave: (step === 'rehearsal' || step === 'saved') && Boolean(state.rehearsed),
    bindingsAreDistinct: bindingsAreDistinct(state.dictationBinding, state.commandBinding),
  };
}

/** Two bindings that fire on the same tokens are one binding wearing two hats. */
export function bindingsAreDistinct(a, b) {
  if (!a || !b) return true;
  const key = (binding) => JSON.stringify([
    binding?.input?.style || 'single',
    [...(binding?.input?.events || [])].sort(),
  ]);
  return key(a) !== key(b);
}

/**
 * The profile this wizard saves.
 *
 * Note what it does NOT carry: no game name typed by the user reaches a match
 * rule, no window title is stored, and the bindings go in the slot Wave 7
 * reserved rather than into a second table. The wizard is a shortcut through the
 * existing profile schema, not a parallel one.
 */
export function buildProfile(state = {}) {
  const bindings = {};
  if (state.dictationBinding) bindings['dictation.begin'] = state.dictationBinding;
  if (state.commandBinding) bindings['command.begin'] = state.commandBinding;
  return {
    id: state.profileId || 'game',
    injection_policy: DELIVERY_MODES[state.delivery] ? state.delivery : DEFAULT_DELIVERY,
    match: { process_names: state.processNames || [], window_patterns: [] },
    bindings,
  };
}

/** One line per rehearsal press, for the log the user reads. */
export function describeRehearsal(row) {
  const action = String(row?.action_id || 'that button');
  if (row?.ok) {
    // Should be unreachable: the rehearsal dispatcher has no handlers. Said
    // plainly rather than silently, because if it ever happens it is a bug in
    // the one guarantee this step exists to make.
    return `${action}: something ran, which it should not have. Do not use this build in a game.`;
  }
  switch (row?.status) {
    case 'unavailable':
      return `${action}: BetterFingers saw your button. Nothing was sent — this is a rehearsal.`;
    case 'needs_param':
      return `${action}: BetterFingers saw your button, but that action still needs a choice.`;
    case 'unknown_action':
      return 'BetterFingers did not recognise that button.';
    default:
      return `${action}: BetterFingers saw your button. Nothing was sent.`;
  }
}

export function collectGameSetupElements(root = document) {
  const els = {};
  for (const [key, id] of Object.entries(WIZARD_ELEMENT_IDS)) {
    els[key] = root?.getElementById?.(id) ?? null;
  }
  return els;
}

export function createGameSetupWizardFeature({ elements = {}, api = {}, onMessage = null } = {}) {
  const availability = computeAvailability(api);
  const state = {
    deviceKey: '',
    devices: [],
    dictationBinding: null,
    commandBinding: null,
    chatKey: '',
    delivery: DEFAULT_DELIVERY,
    acknowledged: false,
    rehearsed: false,
    saved: false,
    profileId: '',
    processNames: [],
  };
  let rehearsalLog = [];

  function setMessage(text, tone = 'info') {
    if (elements.message) {
      elements.message.textContent = text;
      elements.message.dataset.tone = tone;
    }
    if (typeof onMessage === 'function') onMessage(text, tone);
  }

  function renderUnavailable() {
    if (elements.unavailable) {
      elements.unavailable.hidden = false;
      elements.unavailable.textContent = availability.reason;
    }
    for (const key of ['detectButton', 'recordDictationButton', 'recordCommandButton',
      'rehearseButton', 'saveButton']) {
      if (elements[key]) elements[key].disabled = true;
    }
  }

  function render() {
    const flow = computeWizardState(state);
    if (elements.section) {
      elements.section.dataset.wizardStep = flow.step;
      elements.section.dataset.wizardRehearsed = String(Boolean(state.rehearsed));
      elements.section.dataset.wizardSaved = String(Boolean(state.saved));
    }
    if (elements.stepLabel) elements.stepLabel.textContent = flow.step;
    if (elements.recordDictationButton) {
      elements.recordDictationButton.disabled = !flow.canRecordDictation;
    }
    if (elements.recordCommandButton) {
      elements.recordCommandButton.disabled = !flow.canRecordCommand;
    }
    if (elements.deliverySelect) elements.deliverySelect.disabled = !flow.canChooseDelivery;
    if (elements.rehearseButton) elements.rehearseButton.disabled = !flow.canRehearse;
    if (elements.saveButton) elements.saveButton.disabled = !flow.canSave;

    if (elements.warning) {
      elements.warning.hidden = false;
      elements.warning.textContent = ANTI_CHEAT_WARNING;
      elements.warning.dataset.required = String(flow.needsWarning);
      elements.warning.dataset.satisfied = String(flow.warningSatisfied);
    }
    if (elements.dictationValue) {
      elements.dictationValue.textContent = describeBinding(state.dictationBinding);
    }
    if (elements.commandValue) {
      elements.commandValue.textContent = describeBinding(state.commandBinding);
    }
    if (elements.rehearsalLog) {
      elements.rehearsalLog.textContent = rehearsalLog.join('\n');
      elements.rehearsalLog.dataset.pressCount = String(rehearsalLog.length);
    }
    if (!flow.bindingsAreDistinct) {
      setMessage('Dictation and commands are on the same button. Record one of them again — '
        + 'a button that means both can issue a command you were only trying to say.', 'danger');
    }
  }

  function describeBinding(binding) {
    if (!binding) return 'not set';
    const events = binding?.input?.events || [];
    const style = binding?.input?.style || 'single';
    const joiner = style === 'sequence' ? ' then ' : ' + ';
    return events.join(joiner) || 'not set';
  }

  async function detect() {
    if (!availability.available) return [];
    try {
      const payload = await api.fetchInputBindings();
      state.devices = Array.isArray(payload?.devices) ? payload.devices : [];
      state.deviceKey = state.devices[0] || '';
      if (elements.deviceList) {
        elements.deviceList.textContent = state.devices.join(', ');
        elements.deviceList.dataset.deviceCount = String(state.devices.length);
      }
      setMessage(state.deviceKey
        ? `Found ${state.devices.length} controller(s). Using ${state.deviceKey}.`
        : 'No controller found. Plug one in, press a button on it, and detect again.',
      state.deviceKey ? 'success' : 'warn');
      render();
      return state.devices;
    } catch (error) {
      setMessage(`Could not look for controllers: ${error.message}`, 'danger');
      return [];
    }
  }

  /**
   * Poll the backend until the user has finished pressing something.
   *
   * The engine does the listening — it is the thing with the events — and this
   * asks it for the answer. `binding` stays null until every token is back up,
   * so a two-button chord is recorded as a chord rather than as whichever half
   * landed first.
   */
  async function captureFromController({ attempts = 60, delayMs = 100 } = {}) {
    if (typeof api.startInputCapture !== 'function') return null;
    await api.startInputCapture();
    for (let i = 0; i < attempts; i += 1) {
      const payload = await api.readInputCapture();
      if (payload && payload.binding) return payload.binding;
      await new Promise((resolve) => setTimeout(resolve, delayMs));
    }
    await api.cancelInputCapture?.();
    return null;
  }

  /**
   * Record one binding.
   *
   * `capture` is injected and defaults to the controller poll above: the actual
   * "press a button now" listen is the controller engine's job, and the wizard's
   * job is to know what to do with the answer. That split is why this is
   * testable on a machine with no controller — which is every machine this
   * project has.
   */
  async function record(actionId, capture = captureFromController) {
    const binding = await capture();
    if (!binding) {
      setMessage('BetterFingers did not see a button. Try again.', 'warn');
      return null;
    }
    const row = { mode: 'hold', param: '', input: binding };
    if (actionId === 'dictation.begin') state.dictationBinding = row;
    if (actionId === 'command.begin') state.commandBinding = row;
    render();
    return row;
  }

  function setChatKey(value) {
    state.chatKey = String(value || '').trim();
    render();
  }

  function setDelivery(mode) {
    state.delivery = DELIVERY_MODES[mode] ? mode : DEFAULT_DELIVERY;
    // Changing the mode retracts the acknowledgement. A tick made against
    // "Review first" is not consent to type into a game.
    state.acknowledged = false;
    if (elements.acknowledge) elements.acknowledge.checked = false;
    render();
  }

  function acknowledge(value) {
    state.acknowledged = Boolean(value);
    render();
  }

  /**
   * The test step. Sends presses that CANNOT do anything.
   *
   * Every action id it transmits is refused by the backend's rehearsal
   * dispatcher, and the two ids it will not even transmit are the two whose
   * refusal would be the only thing standing between a rehearsal and a real
   * consequence.
   */
  async function rehearse(actionIds = ['dictation.begin', 'command.begin']) {
    if (!computeWizardState(state).canRehearse) return [];
    const rows = [];
    for (const actionId of actionIds) {
      if (REHEARSAL_FORBIDDEN_ACTIONS.includes(actionId)) continue;
      try {
        const result = await api.dispatchInputAction({
          action_id: actionId,
          source: 'controller',
          device_key: state.deviceKey,
          rehearsal: true,
        });
        rows.push(result || { action_id: actionId, ok: false, status: 'unavailable' });
      } catch (error) {
        rows.push({ action_id: actionId, ok: false, status: 'failed' });
      }
    }
    rehearsalLog = rows.map(describeRehearsal);
    state.rehearsed = true;
    render();
    setMessage('Nothing was sent. That is what a rehearsal is.', 'success');
    return rows;
  }

  async function save(profileId) {
    state.profileId = String(profileId || state.profileId || 'game').trim() || 'game';
    if (!computeWizardState(state).canSave) {
      setMessage('Run the test first, so you can see the buttons arrive before you save.', 'warn');
      return null;
    }
    try {
      // The device-level bindings are what survive switching profile, so they
      // are written to the device layer as well as into the profile. A user who
      // set up their pad in this wizard should not lose it by playing a
      // different game.
      await api.setInputBinding('dictation.begin', state.dictationBinding, state.deviceKey);
      await api.setInputBinding('command.begin', state.commandBinding, state.deviceKey);
      const result = await api.saveAppProfile(buildProfile(state));
      if (!result?.ok) {
        setMessage(result?.reason || 'That profile could not be saved.', 'danger');
        return result;
      }
      state.saved = true;
      render();
      setMessage(`Saved. Your controller is set up for ${state.profileId}.`, 'success');
      return result;
    } catch (error) {
      setMessage(`Could not save the profile: ${error.message}`, 'danger');
      return null;
    }
  }

  function bind() {
    elements.detectButton?.addEventListener?.('click', () => detect());
    elements.recordDictationButton?.addEventListener?.('click', () => record('dictation.begin'));
    elements.recordCommandButton?.addEventListener?.('click', () => record('command.begin'));
    elements.chatKeyInput?.addEventListener?.('change', (event) =>
      setChatKey(event?.target?.value ?? elements.chatKeyInput.value));
    elements.deliverySelect?.addEventListener?.('change', (event) =>
      setDelivery(event?.target?.value ?? elements.deliverySelect.value));
    elements.acknowledge?.addEventListener?.('change', (event) =>
      acknowledge(event?.target?.checked ?? elements.acknowledge.checked));
    elements.rehearseButton?.addEventListener?.('click', () => rehearse());
    elements.saveButton?.addEventListener?.('click', () =>
      save(elements.profileNameInput?.value));
  }

  function init() {
    if (!availability.available) {
      renderUnavailable();
      return { available: false };
    }
    if (elements.unavailable) elements.unavailable.hidden = true;
    bind();
    render();
    return { available: true };
  }

  return {
    init,
    detect,
    record,
    setChatKey,
    setDelivery,
    acknowledge,
    rehearse,
    save,
    getState: () => ({ ...state }),
    getFlow: () => computeWizardState(state),
    getRehearsalLog: () => rehearsalLog.slice(),
    isAvailable: () => availability.available,
  };
}
