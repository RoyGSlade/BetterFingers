// Workflow builder (Wave 9, D-0011) — Utilities › Advanced › Launch Workflows.
//
// THE FLOW IS THE FEATURE, and it is enforced here as a state machine rather
// than as a suggestion:
//
//   describe -> compile restricted actions -> validate targets -> exact preview
//   -> explicit approval -> save disabled or enabled -> run only after approval
//
// Every button's enablement comes from `computeFlowState`, a pure function over
// that state, exported and unit-tested on its own. The alternative — enabling
// controls ad hoc as handlers fire — is how "Run" ends up live for one repaint
// after an edit, which is exactly the window in which a workflow runs steps
// nobody approved.
//
// WHAT THIS MODULE WILL NOT DO. It never composes a command line, never offers
// one as a workaround, and never renders a refusal as anything other than the
// backend's own sentence. A refusal is a product answer ("BetterFingers does
// not do this"), and rewriting it in the renderer is how it degrades into a
// hint about how to do it anyway.
//
// UNAVAILABLE IS A REAL STATE, NOT AN EMPTY LIST. Backend traffic reaches this
// feature through the main-process proxy's exact (method, route) allowlist. If
// the api adapter has no workflow methods, this section says so in one sentence
// instead of rendering an empty workflow list — an empty list and a
// disconnected feature look identical, and only one of them means "you have no
// workflows". Same contract as features/applicationProfiles.js.
//
// Every mapper below is pure and separately exported, so the display and
// gating rules are testable without a DOM or a backend.

export const WORKFLOW_ELEMENT_IDS = {
  section: 'sdUtilWorkflowGroup',
  unavailable: 'sdUtilWorkflowUnavailable',
  nameInput: 'sdUtilWorkflowName',
  triggersInput: 'sdUtilWorkflowTriggers',
  stepsInput: 'sdUtilWorkflowSteps',
  compileButton: 'sdUtilWorkflowCompileButton',
  preview: 'sdUtilWorkflowPreview',
  refusals: 'sdUtilWorkflowRefusals',
  approveButton: 'sdUtilWorkflowApproveButton',
  enabledToggle: 'sdUtilWorkflowEnabled',
  saveButton: 'sdUtilWorkflowSaveButton',
  runButton: 'sdUtilWorkflowRunButton',
  list: 'sdUtilWorkflowList',
  history: 'sdUtilWorkflowHistory',
  message: 'sdUtilWorkflowMessage',
};

const REQUIRED_API_METHODS = [
  'fetchWorkflows',
  'compileWorkflow',
  'saveWorkflow',
  'approveWorkflow',
  'runWorkflow',
];

/**
 * The closed vocabulary, mirrored from backend/domain/actions.py.
 *
 * Mirrored rather than fetched so the builder can render its step editor before
 * any backend call resolves — and asserted against the Python source in
 * `workflowBuilder.test.mjs`, so a verb added on one side and not the other is
 * a failing test rather than a step the user can type and never save.
 */
export const ACTION_PARAM = {
  launch_app: 'app_id',
  focus_app: 'app_id',
  open_uri: 'uri',
  open_folder: 'path',
  wait_for_process: 'app_id',
  activate_application_profile: 'profile_id',
  activate_persona: 'persona',
  activate_writing_preset: 'preset',
  show_notification: 'message',
  speak_confirmation: 'message',
};

export const ALLOWED_ACTIONS = Object.keys(ACTION_PARAM);

/**
 * One step per line, `verb: target`.
 *
 * An unrecognised verb is kept as-is rather than dropped or corrected: the
 * backend is the only thing allowed to decide a verb is not permitted, and it
 * answers with a reason. A renderer that filtered them out first would show the
 * user a workflow that silently lost the line they cared about.
 */
export function parseStepLines(text) {
  const steps = [];
  for (const rawLine of String(text ?? '').split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    const separator = line.indexOf(':');
    const action = (separator >= 0 ? line.slice(0, separator) : line).trim().toLowerCase();
    const value = separator >= 0 ? line.slice(separator + 1).trim() : '';
    if (!action) continue;
    const param = ACTION_PARAM[action];
    steps.push(param ? { action, [param]: value } : { action, value });
  }
  return steps;
}

/** Trigger phrases, one per line or comma-separated. */
export function parseTriggerPhrases(text) {
  return String(text ?? '')
    .split(/[\r\n,]+/)
    .map((phrase) => phrase.trim())
    .filter(Boolean);
}

/** The workflow document a compile/save call sends. */
export function buildWorkflowPayload({ name, triggers, steps } = {}) {
  return {
    name: String(name ?? '').trim(),
    trigger_phrases: parseTriggerPhrases(triggers),
    steps: parseStepLines(steps),
  };
}

/** Is the feature usable at all? Returns {available, reason}. */
export function computeAvailability(api) {
  const missing = REQUIRED_API_METHODS.filter((name) => typeof api?.[name] !== 'function');
  if (missing.length) {
    return {
      available: false,
      reason:
        'Launch workflows are not reachable in this build — the backend route is not '
        + 'connected yet. Nothing is saved and nothing can run.',
    };
  }
  return { available: true, reason: '' };
}

/**
 * Which controls are live, given where the user is in the flow.
 *
 * `previewMatchesApproval` is the one that is easy to leave out and expensive
 * to leave out: an approved workflow whose preview has changed must not be
 * runnable, and the backend refuses it anyway — but a Run button that looks
 * live and then reports a refusal teaches people to ignore refusals.
 */
export function computeFlowState({
  compiled = false,
  hasRefusals = false,
  saved = false,
  approved = false,
  enabled = false,
  previewMatchesApproval = true,
  dirty = false,
} = {}) {
  const compiledClean = Boolean(compiled) && !hasRefusals && !dirty;
  return {
    canCompile: true,
    canSave: compiledClean,
    canApprove: compiledClean && Boolean(saved),
    canRun: Boolean(saved) && Boolean(approved) && Boolean(enabled)
      && compiledClean && Boolean(previewMatchesApproval),
    // The single sentence under the buttons. Says the NEXT thing to do, so the
    // flow is discoverable without a tutorial.
    hint: nextStepHint({ compiled, hasRefusals, saved, approved, enabled, dirty, previewMatchesApproval }),
  };
}

function nextStepHint({ compiled, hasRefusals, saved, approved, enabled, dirty, previewMatchesApproval }) {
  if (dirty) return 'You changed the workflow. Build the preview again to see what it will do now.';
  if (!compiled) return 'Describe the steps, then build the preview.';
  if (hasRefusals) return 'BetterFingers will not perform some of these steps. Remove them to continue.';
  if (!saved) return 'Save the workflow, then approve the preview.';
  if (!approved) return 'Read the preview and approve it. Nothing can run before you do.';
  if (!previewMatchesApproval) return 'What this workflow would do has changed. Approve the new preview before it can run.';
  if (!enabled) return 'This workflow is saved and approved but turned off.';
  return 'This workflow is approved and can run.';
}

/** A stored workflow's one-line summary. */
export function describeWorkflow(workflow) {
  if (!workflow || typeof workflow !== 'object') return '';
  const steps = Array.isArray(workflow.steps) ? workflow.steps.length : 0;
  const parts = [`${steps} step${steps === 1 ? '' : 's'}`];
  parts.push(workflow.enabled ? 'On' : 'Off');
  parts.push(workflow.approved ? 'Approved' : 'Not approved');
  return parts.join(' · ');
}

/**
 * Why a stored workflow cannot run, in words — or '' when it can.
 *
 * Deliberately separate from `describeWorkflow`: "Off" and "not approved" are
 * both routine states, and only the second one means the user has an unfinished
 * decision waiting for them.
 */
export function describeBlockedReason(workflow) {
  if (!workflow) return '';
  if (!workflow.approved) return 'Not approved yet, so it cannot run.';
  if (!workflow.enabled) return 'Turned off.';
  return '';
}

/** A run summary in one sentence. Never "done" unless every step is done. */
export function describeRunSummary(summary) {
  if (!summary) return '';
  const completed = Number(summary.completed || 0);
  const total = Number(summary.total || 0);
  switch (summary.status) {
    case 'success':
      return `All ${total} steps finished.`;
    case 'blocked':
      return 'Nothing ran.';
    case 'failed':
      return `None of the ${total} steps finished.`;
    default:
      return `${completed} of ${total} steps finished; the rest did not.`;
  }
}

export function collectWorkflowElements(root = document) {
  const els = {};
  for (const [key, id] of Object.entries(WORKFLOW_ELEMENT_IDS)) {
    els[key] = root?.getElementById?.(id) ?? null;
  }
  return els;
}

/**
 * @param {object} opts
 * @param {object} opts.elements from collectWorkflowElements()
 * @param {object} opts.api      backend api module
 * @param {object} [opts.hooks]  { showToast, escapeHtml, getValidationContext }
 */
export function createWorkflowBuilderFeature({
  elements = {},
  api = null,
  hooks = {},
} = {}) {
  const escapeHtml =
    hooks.escapeHtml
    || ((value) =>
      String(value ?? '').replace(/[&<>"']/g, (ch) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])));

  const availability = computeAvailability(api);

  // The whole builder state, in one place, so computeFlowState has one input.
  let state = {
    compiled: false,
    hasRefusals: false,
    saved: false,
    approved: false,
    enabled: false,
    dirty: false,
    previewMatchesApproval: true,
  };
  let previewLines = [];
  let refusals = [];
  let workflowId = '';
  let workflows = [];
  let history = [];
  // The exact lines the user approved, kept so a recompile can tell whether
  // the approval still describes what would run.
  let approvedLines = [];

  /**
   * What the validator needs about THIS machine.
   *
   * Supplied by the host (signalDeskApp wires the confirmed registry and the
   * known profile/persona/preset lists). Absent lists mean "nothing is known",
   * and the backend fails closed on them — a step it cannot verify is refused,
   * not assumed valid.
   */
  function validationContext() {
    const context = hooks.getValidationContext?.() || {};
    return {
      registry: Array.isArray(context.registry) ? context.registry : [],
      profile_ids: Array.isArray(context.profile_ids) ? context.profile_ids : [],
      personas: Array.isArray(context.personas) ? context.personas : [],
      writing_presets: Array.isArray(context.writing_presets) ? context.writing_presets : [],
      folder_roots: Array.isArray(context.folder_roots) ? context.folder_roots : null,
    };
  }

  function setMessage(text = '', tone = '') {
    if (!elements.message) return;
    elements.message.textContent = text;
    if (tone) elements.message.dataset.tone = tone;
    else delete elements.message.dataset.tone;
  }

  function currentPayload() {
    return buildWorkflowPayload({
      name: elements.nameInput?.value,
      triggers: elements.triggersInput?.value,
      steps: elements.stepsInput?.value,
    });
  }

  function renderPreview() {
    if (elements.preview) {
      elements.preview.innerHTML = previewLines
        .map((line, index) =>
          `<li class="sd-workflow-preview__row" data-workflow-preview-step="${index + 1}">`
          + `${escapeHtml(line)}</li>`)
        .join('');
      elements.preview.dataset.stepCount = String(previewLines.length);
    }
    if (elements.refusals) {
      elements.refusals.innerHTML = refusals
        .map((refusal) =>
          `<li class="sd-workflow-refusal" data-workflow-refusal="${escapeHtml(refusal.code || '')}"`
          + ` data-workflow-refusal-action="${escapeHtml(refusal.action || '')}">`
          // The backend's own sentence, verbatim. Not paraphrased, and never
          // followed by a "you could instead…" that names a command.
          + `${escapeHtml(refusal.reason || '')}</li>`)
        .join('');
      elements.refusals.hidden = refusals.length === 0;
    }
  }

  function renderFlow() {
    const flow = computeFlowState(state);
    if (elements.saveButton) elements.saveButton.disabled = !flow.canSave;
    if (elements.approveButton) elements.approveButton.disabled = !flow.canApprove;
    if (elements.runButton) {
      elements.runButton.disabled = !flow.canRun;
      elements.runButton.dataset.approved = String(Boolean(state.approved));
    }
    if (elements.section) {
      elements.section.dataset.workflowApproved = String(Boolean(state.approved));
      elements.section.dataset.workflowSaved = String(Boolean(state.saved));
    }
    setMessage(flow.hint, refusals.length ? 'danger' : '');
    return flow;
  }

  function renderList() {
    if (!elements.list) return;
    elements.list.innerHTML = workflows
      .map((workflow) => {
        const blocked = describeBlockedReason(workflow);
        return (
          `<div class="sd-workflow-row" data-workflow="${escapeHtml(workflow.id)}"`
          + ` data-workflow-approved="${workflow.approved ? 'true' : 'false'}"`
          + ` data-workflow-enabled="${workflow.enabled ? 'true' : 'false'}">`
          + `<span class="sd-workflow-row__name">${escapeHtml(workflow.name || workflow.id)}</span>`
          + `<span class="sd-workflow-row__summary">${escapeHtml(describeWorkflow(workflow))}</span>`
          + (blocked
            ? `<span class="sd-workflow-row__blocked" data-workflow-blocked>${escapeHtml(blocked)}</span>`
            : '')
          + `<button type="button" class="sd-btn sd-workflow-row__load"`
          + ` data-workflow-load="${escapeHtml(workflow.id)}">Open</button>`
          + `</div>`
        );
      })
      .join('');
  }

  function renderHistory() {
    if (!elements.history) return;
    elements.history.innerHTML = history
      .map((run) =>
        `<li class="sd-workflow-run" data-workflow-run="${escapeHtml(run.workflow_id)}"`
        + ` data-workflow-run-status="${escapeHtml(run.status)}">`
        + `${escapeHtml(run.status)} · ${Number(run.completed || 0)} of ${Number(run.total || 0)} steps`
        + `</li>`)
      .join('');
  }

  function renderUnavailable() {
    if (elements.unavailable) {
      elements.unavailable.hidden = false;
      elements.unavailable.textContent = availability.reason;
    }
    for (const key of ['compileButton', 'saveButton', 'approveButton', 'runButton']) {
      if (elements[key]) elements[key].disabled = true;
    }
    if (elements.list) elements.list.innerHTML = '';
    if (elements.preview) elements.preview.innerHTML = '';
  }

  function markDirty() {
    if (!state.compiled) return;
    state = { ...state, dirty: true };
    renderFlow();
  }

  // --- actions --------------------------------------------------------------

  async function compile() {
    if (!availability.available) return null;
    const payload = currentPayload();
    try {
      const result = await api.compileWorkflow(payload, validationContext());
      previewLines = Array.isArray(result?.preview_lines) ? result.preview_lines : [];
      refusals = [
        ...(Array.isArray(result?.refusals) ? result.refusals : []),
        ...(Array.isArray(result?.validation_refusals) ? result.validation_refusals : []),
      ];
      state = {
        ...state,
        compiled: true,
        dirty: false,
        hasRefusals: refusals.length > 0,
        // A recompile after an edit invalidates the earlier approval for
        // display purposes; the backend re-checks it independently on run.
        previewMatchesApproval: !state.approved || sameLines(previewLines, approvedLines),
      };
      renderPreview();
      renderFlow();
      return result;
    } catch (error) {
      setMessage(`Could not build the preview: ${error.message}`, 'danger');
      return null;
    }
  }

  function sameLines(a, b) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length
      && a.every((line, index) => line === b[index]);
  }

  async function save() {
    if (!availability.available || !computeFlowState(state).canSave) return null;
    const enabled = Boolean(elements.enabledToggle?.checked);
    try {
      const result = await api.saveWorkflow(currentPayload(), enabled);
      workflowId = result?.workflow?.id || '';
      state = {
        ...state,
        saved: Boolean(workflowId),
        // Saving never approves. The backend enforces it; mirroring it here
        // keeps the button state honest without a round trip.
        approved: Boolean(result?.workflow?.approved),
        enabled: Boolean(result?.workflow?.enabled),
      };
      renderFlow();
      await refreshList();
      hooks.showToast?.(
        enabled ? 'Workflow saved and turned on. It still needs approval before it can run.'
          : 'Workflow saved, turned off.',
        'success',
      );
      return result;
    } catch (error) {
      setMessage(`Could not save the workflow: ${error.message}`, 'danger');
      return null;
    }
  }

  async function approve() {
    if (!availability.available || !computeFlowState(state).canApprove) return null;
    try {
      const result = await api.approveWorkflow(workflowId, previewLines);
      approvedLines = previewLines.slice();
      state = {
        ...state,
        approved: Boolean(result?.workflow?.approved),
        enabled: Boolean(result?.workflow?.enabled),
        previewMatchesApproval: true,
      };
      renderFlow();
      await refreshList();
      return result;
    } catch (error) {
      setMessage(`Could not approve the workflow: ${error.message}`, 'danger');
      return null;
    }
  }

  async function run() {
    if (!availability.available || !computeFlowState(state).canRun) return null;
    try {
      const result = await api.runWorkflow(workflowId, validationContext());
      if (!result?.ok) {
        // The backend refused at the gate. Show ITS reason: it knows things the
        // renderer does not, such as the registry having changed underneath an
        // approved workflow.
        setMessage(result?.reason || 'That workflow cannot run right now.', 'danger');
        if (Array.isArray(result?.refusals)) {
          refusals = result.refusals;
          renderPreview();
        }
        return result;
      }
      setMessage('Approved. Running the steps in the order shown above.', 'success');
      return result;
    } catch (error) {
      setMessage(`Could not run the workflow: ${error.message}`, 'danger');
      return null;
    }
  }

  async function refreshList() {
    if (!availability.available) return [];
    try {
      const payload = await api.fetchWorkflows();
      workflows = Array.isArray(payload?.workflows) ? payload.workflows : [];
    } catch (_error) {
      workflows = [];
    }
    renderList();
    return workflows;
  }

  async function refreshHistory() {
    if (!availability.available || typeof api.fetchWorkflowHistory !== 'function') return [];
    try {
      const payload = await api.fetchWorkflowHistory();
      history = Array.isArray(payload?.history) ? payload.history : [];
    } catch (_error) {
      history = [];
    }
    renderHistory();
    return history;
  }

  function load(id) {
    const workflow = workflows.find((item) => item.id === id);
    if (!workflow) return null;
    workflowId = workflow.id;
    if (elements.nameInput) elements.nameInput.value = workflow.name || '';
    if (elements.triggersInput) {
      elements.triggersInput.value = (workflow.trigger_phrases || []).join('\n');
    }
    if (elements.stepsInput) {
      elements.stepsInput.value = (workflow.steps || [])
        .map((step) => `${step.action}: ${step[ACTION_PARAM[step.action]] ?? ''}`)
        .join('\n');
    }
    if (elements.enabledToggle) elements.enabledToggle.checked = Boolean(workflow.enabled);
    approvedLines = Array.isArray(workflow.approved_preview) ? workflow.approved_preview.slice() : [];
    previewLines = [];
    refusals = [];
    state = {
      compiled: false,
      hasRefusals: false,
      saved: true,
      approved: Boolean(workflow.approved),
      enabled: Boolean(workflow.enabled),
      dirty: false,
      previewMatchesApproval: true,
    };
    renderPreview();
    renderFlow();
    return workflow;
  }

  function bind() {
    elements.compileButton?.addEventListener?.('click', () => compile());
    elements.saveButton?.addEventListener?.('click', () => save());
    elements.approveButton?.addEventListener?.('click', () => approve());
    elements.runButton?.addEventListener?.('click', () => run());
    for (const key of ['nameInput', 'triggersInput', 'stepsInput']) {
      elements[key]?.addEventListener?.('input', () => markDirty());
    }
    elements.list?.addEventListener?.('click', (event) => {
      const id = event.target?.dataset?.workflowLoad;
      if (id) load(id);
    });
  }

  function init() {
    if (!availability.available) {
      renderUnavailable();
      return { available: false };
    }
    if (elements.unavailable) elements.unavailable.hidden = true;
    bind();
    renderPreview();
    renderFlow();
    refreshList().then(() => refreshHistory());
    return { available: true };
  }

  return {
    init,
    compile,
    save,
    approve,
    run,
    load,
    refreshList,
    refreshHistory,
    getState: () => ({ ...state }),
    getPreviewLines: () => previewLines.slice(),
    getRefusals: () => refusals.slice(),
    getWorkflows: () => workflows.slice(),
    getWorkflowId: () => workflowId,
    isAvailable: () => availability.available,
  };
}
