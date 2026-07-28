// workflowBuilder.js — the approval flow, as a state machine.
//
// The tests that matter here are the gating ones: Run must be unreachable
// until a preview has been built, saved and approved, and it must go
// unreachable again the moment the user edits anything. Those are exactly the
// transitions that look fine in a manual click-through because a human does
// them in the "right" order.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  ACTION_PARAM,
  ALLOWED_ACTIONS,
  buildWorkflowPayload,
  computeAvailability,
  computeFlowState,
  createWorkflowBuilderFeature,
  describeBlockedReason,
  describeRunSummary,
  describeWorkflow,
  parseStepLines,
  parseTriggerPhrases,
} from '../src/renderer/features/workflowBuilder.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');

// --- vocabulary parity --------------------------------------------------------

test('the renderer vocabulary matches backend/domain/actions.py exactly', () => {
  const source = fs.readFileSync(path.join(REPO, 'backend', 'domain', 'actions.py'), 'utf8');
  const block = source.slice(source.indexOf('ACTION_PARAM = {'), source.indexOf('}', source.indexOf('ACTION_PARAM = {')));
  const pairs = [...block.matchAll(/ACTION_([A-Z_]+):\s*"([a-z_]+)"/g)];
  assert.ok(pairs.length >= 10, 'the Python ACTION_PARAM table was found');
  // Every renderer verb exists in the Python allowed tuple, and vice versa.
  for (const action of ALLOWED_ACTIONS) {
    assert.ok(source.includes(`"${action}"`), `${action} must exist in the schema`);
  }
  const pythonParams = new Set(pairs.map(([, , param]) => param));
  for (const param of new Set(Object.values(ACTION_PARAM))) {
    assert.ok(pythonParams.has(param), `parameter ${param} must exist in the schema`);
  }
  assert.equal(ALLOWED_ACTIONS.length, pairs.length);
});

// --- pure parsing -------------------------------------------------------------

test('step lines parse into the schema parameter for each verb', () => {
  const steps = parseStepLines([
    'launch_app: obsidian',
    '  open_uri:  https://example.com  ',
    'speak_confirmation: Studio ready',
    '',
  ].join('\n'));
  assert.deepEqual(steps, [
    { action: 'launch_app', app_id: 'obsidian' },
    { action: 'open_uri', uri: 'https://example.com' },
    { action: 'speak_confirmation', message: 'Studio ready' },
  ]);
});

test('an unrecognised verb is passed through for the backend to refuse, not dropped', () => {
  // Dropping it in the renderer would show the user a workflow that silently
  // lost the line they cared about, with no reason given anywhere.
  const steps = parseStepLines('shell: rm -rf ~\nlaunch_app: obsidian');
  assert.equal(steps.length, 2);
  assert.equal(steps[0].action, 'shell');
  assert.equal(steps[0].value, 'rm -rf ~');
});

test('trigger phrases split on newlines and commas', () => {
  assert.deepEqual(parseTriggerPhrases('open my studio\nstudio time, start studio'),
    ['open my studio', 'studio time', 'start studio']);
});

test('buildWorkflowPayload sends only the schema fields', () => {
  const payload = buildWorkflowPayload({
    name: '  Studio setup ', triggers: 'open my studio', steps: 'launch_app: obsidian',
  });
  assert.deepEqual(Object.keys(payload).sort(), ['name', 'steps', 'trigger_phrases']);
  assert.equal(payload.name, 'Studio setup');
});

// --- availability -------------------------------------------------------------

test('the feature reports itself unavailable when the api has no workflow methods', () => {
  const { available, reason } = computeAvailability({});
  assert.equal(available, false);
  assert.match(reason, /not reachable in this build/);
  assert.match(reason, /nothing can run/);
});

test('the feature is available when every required method exists', () => {
  const api = {
    fetchWorkflows() {}, compileWorkflow() {}, saveWorkflow() {},
    approveWorkflow() {}, runWorkflow() {},
  };
  assert.equal(computeAvailability(api).available, true);
});

// --- the flow -----------------------------------------------------------------

test('nothing is runnable before a preview has been built', () => {
  const flow = computeFlowState({});
  assert.equal(flow.canSave, false);
  assert.equal(flow.canApprove, false);
  assert.equal(flow.canRun, false);
  assert.match(flow.hint, /build the preview/i);
});

test('a refused step blocks save, approve and run', () => {
  const flow = computeFlowState({ compiled: true, hasRefusals: true });
  assert.equal(flow.canSave, false);
  assert.equal(flow.canApprove, false);
  assert.equal(flow.canRun, false);
  assert.match(flow.hint, /will not perform/i);
});

test('approve is only reachable after saving', () => {
  assert.equal(computeFlowState({ compiled: true }).canApprove, false);
  assert.equal(computeFlowState({ compiled: true, saved: true }).canApprove, true);
});

test('run needs saved AND approved AND enabled — every one of them', () => {
  const base = { compiled: true, saved: true, approved: true, enabled: true };
  assert.equal(computeFlowState(base).canRun, true);
  assert.equal(computeFlowState({ ...base, approved: false }).canRun, false);
  assert.equal(computeFlowState({ ...base, enabled: false }).canRun, false);
  assert.equal(computeFlowState({ ...base, saved: false }).canRun, false);
});

test('editing after approval makes it unrunnable until it is rebuilt', () => {
  const flow = computeFlowState({
    compiled: true, saved: true, approved: true, enabled: true, dirty: true,
  });
  assert.equal(flow.canRun, false);
  assert.equal(flow.canSave, false);
  assert.match(flow.hint, /Build the preview again/);
});

test('an approval that no longer matches the preview does not enable run', () => {
  const flow = computeFlowState({
    compiled: true, saved: true, approved: true, enabled: true, previewMatchesApproval: false,
  });
  assert.equal(flow.canRun, false);
  assert.match(flow.hint, /Approve the new preview/);
});

test('a saved, approved but disabled workflow says so rather than looking broken', () => {
  const flow = computeFlowState({ compiled: true, saved: true, approved: true, enabled: false });
  assert.match(flow.hint, /turned off/);
});

// --- display ------------------------------------------------------------------

test('a workflow summary states approval and on/off in words, not colour', () => {
  assert.equal(
    describeWorkflow({ steps: [1, 2], enabled: true, approved: false }),
    '2 steps · On · Not approved',
  );
  assert.equal(describeWorkflow({ steps: [1], enabled: false, approved: true }),
    '1 step · Off · Approved');
});

test('an unapproved workflow explains that it cannot run', () => {
  assert.match(describeBlockedReason({ approved: false, enabled: true }), /cannot run/);
  assert.equal(describeBlockedReason({ approved: true, enabled: false }), 'Turned off.');
  assert.equal(describeBlockedReason({ approved: true, enabled: true }), '');
});

test('a partial run is never described as finished', () => {
  assert.equal(
    describeRunSummary({ status: 'partial', completed: 2, total: 3 }),
    '2 of 3 steps finished; the rest did not.',
  );
  assert.equal(describeRunSummary({ status: 'success', total: 3 }), 'All 3 steps finished.');
  assert.equal(describeRunSummary({ status: 'blocked' }), 'Nothing ran.');
});

// --- feature behaviour with a fake DOM ---------------------------------------

function fakeElement(extra = {}) {
  const listeners = {};
  return {
    value: '',
    checked: false,
    disabled: false,
    hidden: false,
    textContent: '',
    innerHTML: '',
    dataset: {},
    addEventListener(type, handler) { listeners[type] = handler; },
    fire(type, event = {}) { listeners[type]?.(event); },
    ...extra,
  };
}

function fakeElements() {
  return {
    section: fakeElement(),
    unavailable: fakeElement(),
    nameInput: fakeElement(),
    triggersInput: fakeElement(),
    stepsInput: fakeElement(),
    compileButton: fakeElement(),
    preview: fakeElement(),
    refusals: fakeElement(),
    approveButton: fakeElement(),
    enabledToggle: fakeElement(),
    saveButton: fakeElement(),
    runButton: fakeElement(),
    list: fakeElement(),
    history: fakeElement(),
    message: fakeElement(),
  };
}

function fakeApi(overrides = {}) {
  return {
    async fetchWorkflows() { return { workflows: [] }; },
    async compileWorkflow() {
      return { ok: true, preview_lines: ['1. Launch Obsidian (flatpak run md.obsidian.Obsidian)'], refusals: [], validation_refusals: [] };
    },
    async saveWorkflow(_payload, enabled) {
      return { ok: true, workflow: { id: 'studio_setup', approved: false, enabled } };
    },
    async approveWorkflow() {
      return { ok: true, workflow: { id: 'studio_setup', approved: true, enabled: true } };
    },
    async runWorkflow() { return { ok: true }; },
    async fetchWorkflowHistory() { return { history: [] }; },
    ...overrides,
  };
}

test('an unreachable feature paints one sentence and disables every button', () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({ elements, api: {} });
  assert.equal(feature.init().available, false);
  assert.equal(elements.unavailable.hidden, false);
  assert.match(elements.unavailable.textContent, /not reachable/);
  for (const key of ['compileButton', 'saveButton', 'approveButton', 'runButton']) {
    assert.equal(elements[key].disabled, true, key);
  }
});

test('the full flow: compile, save, approve — and Run is dead until the end', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({ elements, api: fakeApi() });
  feature.init();
  elements.nameInput.value = 'Studio setup';
  elements.stepsInput.value = 'launch_app: obsidian';
  elements.enabledToggle.checked = true;

  assert.equal(elements.runButton.disabled, true, 'run is dead before anything');

  await feature.compile();
  assert.equal(elements.saveButton.disabled, false);
  assert.equal(elements.approveButton.disabled, true, 'approve needs a save first');
  assert.equal(elements.runButton.disabled, true);

  await feature.save();
  assert.equal(elements.approveButton.disabled, false);
  assert.equal(elements.runButton.disabled, true, 'saving is not approving');

  await feature.approve();
  assert.equal(elements.runButton.disabled, false);
  assert.equal(elements.runButton.dataset.approved, 'true');
});

test('a refusal is rendered as the backend wrote it, and blocks the flow', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({
    elements,
    api: fakeApi({
      async compileWorkflow() {
        return {
          ok: false,
          preview_lines: [],
          refusals: [{
            code: 'prohibited_action', action: 'shell',
            reason: 'BetterFingers never runs shell commands. Workflows are a fixed list of approved actions.',
          }],
          validation_refusals: [],
        };
      },
    }),
  });
  feature.init();
  await feature.compile();

  assert.equal(elements.refusals.hidden, false);
  assert.match(elements.refusals.innerHTML, /never runs shell commands/);
  assert.equal(elements.saveButton.disabled, true);
  assert.equal(elements.runButton.disabled, true);
});

test('no rendered refusal or hint ever contains a command line', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({
    elements,
    api: fakeApi({
      async compileWorkflow() {
        return {
          ok: false, preview_lines: [],
          refusals: [{ code: 'prohibited_action', action: 'shell', reason: 'BetterFingers never runs shell commands.' }],
          validation_refusals: [],
        };
      },
    }),
  });
  feature.init();
  await feature.compile();
  const rendered = `${elements.refusals.innerHTML} ${elements.message.textContent}`.toLowerCase();
  for (const token of ['sudo ', 'bash -', 'powershell -', 'cmd.exe', '&&', '$(', 'rm -rf']) {
    assert.ok(!rendered.includes(token), token);
  }
});

test('editing after approval disables Run again', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({ elements, api: fakeApi() });
  feature.init();
  elements.nameInput.value = 'Studio setup';
  elements.stepsInput.value = 'launch_app: obsidian';
  elements.enabledToggle.checked = true;
  await feature.compile();
  await feature.save();
  await feature.approve();
  assert.equal(elements.runButton.disabled, false);

  elements.stepsInput.value = 'launch_app: obsidian\nopen_folder: /etc';
  elements.stepsInput.fire('input');
  assert.equal(elements.runButton.disabled, true, 'an edit revokes runnability until rebuilt');
});

test('a run the backend refuses shows the backend reason rather than claiming success', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({
    elements,
    api: fakeApi({
      async runWorkflow() {
        return { ok: false, error: 'preview_changed', reason: 'What this workflow would do has changed since you approved it.' };
      },
    }),
  });
  feature.init();
  elements.nameInput.value = 'Studio setup';
  elements.stepsInput.value = 'launch_app: obsidian';
  elements.enabledToggle.checked = true;
  await feature.compile();
  await feature.save();
  await feature.approve();
  await feature.run();
  assert.match(elements.message.textContent, /has changed since you approved/);
  assert.equal(elements.message.dataset.tone, 'danger');
});

test('the saved list marks approval state by attribute, not by its label text', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({
    elements,
    api: fakeApi({
      async fetchWorkflows() {
        return { workflows: [
          { id: 'studio_setup', name: 'Studio setup', steps: [1], enabled: true, approved: false },
          { id: 'stream', name: 'Stream', steps: [1, 2], enabled: true, approved: true },
        ] };
      },
    }),
  });
  feature.init();
  await feature.refreshList();
  assert.match(elements.list.innerHTML, /data-workflow="studio_setup"[^>]*data-workflow-approved="false"/);
  assert.match(elements.list.innerHTML, /data-workflow="stream"[^>]*data-workflow-approved="true"/);
  assert.match(elements.list.innerHTML, /data-workflow-blocked/);
});

// --- the markup actually carries the ids the feature collects -----------------

test('every element id the feature collects exists in signal-desk.html', async () => {
  const { WORKFLOW_ELEMENT_IDS } = await import('../src/renderer/features/workflowBuilder.js');
  const markup = fs.readFileSync(
    path.join(HERE, '..', 'src', 'renderer', 'signal-desk.html'), 'utf8',
  );
  const missing = Object.values(WORKFLOW_ELEMENT_IDS).filter((id) => !markup.includes(`id="${id}"`));
  assert.deepEqual(
    missing, [],
    'a collected id that is not in the page makes the feature bind to nothing and '
    + 'fail silently — it looks exactly like a feature nobody has used yet',
  );
});

test('the builder markup states the boundary the QA scenario asserts', () => {
  const markup = fs.readFileSync(
    path.join(HERE, '..', 'src', 'renderer', 'signal-desk.html'), 'utf8',
  );
  // Whitespace-normalised, the way Playwright's toContainText compares: the
  // sentence is wrapped across source lines and the QA scenario asserts the
  // rendered text, not the source formatting.
  const group = markup.slice(markup.indexOf('id="sdUtilWorkflowGroup"')).replace(/\s+/g, ' ');
  assert.ok(group.includes('never a script'));
  assert.ok(group.includes('does not run shell commands'));
});

// --- the QA scenarios are registered and well-formed --------------------------
//
// Not a substitute for running them (that needs Electron and a display); this
// is the cheap check that catches the failure mode where a scenario file exists,
// is syntactically fine, and is simply never reached because nobody added it to
// the registry — which looks exactly like a green QA run.

test('the Wave 9 scenarios are registered on the production UI target', async () => {
  const { scenarios } = await import('./qa/scenarios/index.mjs');
  const wave9 = scenarios.filter((scenario) => scenario.area === 'wave9-actions');
  assert.ok(wave9.length >= 10, `expected the Wave 9 scenarios to be registered, got ${wave9.length}`);
  for (const scenario of wave9) {
    assert.equal(scenario.ui, 'signal-desk-prod', scenario.name);
    assert.equal(typeof scenario.navigate, 'function', scenario.name);
    assert.equal(typeof scenario.expects, 'function', scenario.name);
    assert.ok(scenario.description.length > 120, `${scenario.name} needs a real description`);
    assert.ok(Array.isArray(scenario.screenshots) && scenario.screenshots.length, scenario.name);
  }
  const names = wave9.map((scenario) => scenario.name);
  assert.equal(new Set(names).size, names.length, 'scenario names must be unique');
});

test('every Wave 9 scenario uses attribute selectors, never :has-text (D-0023)', async () => {
  // Comment lines are excluded: the file's own header explains why :has-text is
  // banned, and a check that could not mention its own rule would be a poor one.
  const code = fs.readFileSync(path.join(HERE, 'qa', 'scenarios', 'wave9-actions.mjs'), 'utf8')
    .split(/\r?\n/)
    .filter((line) => !line.trim().startsWith('//'))
    .join('\n');
  assert.ok(!code.includes(':has-text'), 'text selectors silently pick a different row when a label changes');
});

test('loading a saved workflow resets the flow so its preview must be rebuilt', async () => {
  const elements = fakeElements();
  const feature = createWorkflowBuilderFeature({
    elements,
    api: fakeApi({
      async fetchWorkflows() {
        return { workflows: [{
          id: 'studio_setup', name: 'Studio setup', enabled: true, approved: true,
          approved_preview: ['1. Launch Obsidian (flatpak run md.obsidian.Obsidian)'],
          trigger_phrases: ['open my studio'],
          steps: [{ action: 'launch_app', app_id: 'obsidian' }],
        }] };
      },
    }),
  });
  feature.init();
  await feature.refreshList();
  feature.load('studio_setup');
  assert.equal(elements.stepsInput.value, 'launch_app: obsidian');
  assert.equal(elements.triggersInput.value, 'open my studio');
  // Approved on disk, but this session has not built a preview yet, so Run
  // stays dead until the user sees what it would do now.
  assert.equal(elements.runButton.disabled, true);
});
