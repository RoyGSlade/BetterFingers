// Wave 9 QA: the restricted action engine on the production composition root.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs wave9-actions
//
// PREREQUISITE (stated because it is the difference between these scenarios
// proving something and passing vacuously): renderer backend traffic reaches
// the stub through the MAIN-PROCESS proxy, whose ROUTE_ALLOWLIST in
// app/src/main/backendProxy.js is an exact (method, route) table -- the stub is
// BEHIND the proxy, so the allowlist gates QA exactly as it gates production.
// Wave 9 needs the /workflows/* entries and the api/backend.js helpers; both
// are integration-owned and written out as D-1..D-3 in
// docs/release/WAVE9_INTEGRATION_DIFFS.md. Until they land,
// features/workflowBuilder.js correctly reports itself UNAVAILABLE and only the
// first scenario below can pass -- which is itself the assertion that the
// degraded state is honest rather than an empty form.
//
// REQUEST CAPTURE (D-0021). Every capture lives in the STUB HANDLER, never on
// `page.on('request')`: the renderer never issues the HTTP request itself, so a
// page-level listener counts zero forever -- passing every "performed no calls"
// assertion vacuously and failing every "performed exactly one".
//
// STATEFUL STUBS. Several scenarios below need the backend to CHANGE as the
// user works (save creates a record; approve flips its flag; a second run sees
// a registry that moved underneath it). Those stubs hold per-scenario state and
// are reset in `navigate`, because a stub that answers identically to the first
// and second call cannot distinguish "the approval was recorded" from "the
// button repainted".
//
// SELECTORS (D-0023). Attribute selectors throughout, never `:has-text`. The
// workflow rows carry data-workflow / data-workflow-approved /
// data-workflow-enabled and the preview rows carry data-workflow-preview-step
// precisely so a row can be addressed by identity rather than by the words
// inside it.
//
// WHAT THESE SCENARIOS ARE REALLY FOR. Gate 9 is "unsupported actions and
// unknown commands cannot execute; partial failure is visible". None of those
// failures crash. A workflow that quietly drops its shell step looks like a
// workflow that saved. A Run button that is live one repaint too early looks
// like a responsive UI. A run that launched two of three applications and said
// "Done" looks like a success. So the assertions are on refusal text, on button
// state at each step of the flow, and on the exact words a partial run reports.

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';

const REGISTRY = [{
  id: 'obsidian',
  display_name: 'Obsidian',
  launch_method: 'flatpak',
  flatpak_id: 'md.obsidian.Obsidian',
  confirmed: true,
}];

const PREVIEW_LINE = '1. Launch Obsidian (flatpak run md.obsidian.Obsidian)';

const SHELL_REFUSAL = {
  step_index: 1,
  action: 'shell',
  code: 'prohibited_action',
  reason:
    'BetterFingers never runs shell commands. Workflows are a fixed list of '
    + 'approved actions, not a script, so there is no command line for a '
    + 'transcript to end up on.',
};

const UNKNOWN_APP_REFUSAL = {
  step_index: 0,
  action: 'launch_app',
  code: 'unknown_application',
  reason:
    '“blender” is not one of the applications you confirmed, so this workflow '
    + 'cannot open it. Add it in the application list first.',
};

// --- captures ----------------------------------------------------------------

let compileCalls = [];
let saveCalls = [];
let approveCalls = [];
let runCalls = [];

/**
 * A stateful workflow backend.
 *
 * `saved` and `approved` move exactly as the real store does: saving never
 * approves, approval records the preview lines, and run consults both. A
 * stateless stub would let a broken renderer pass by answering "approved" to
 * a request that never happened.
 */
function workflowBackend({ compile = null, run = null, extra = {} } = {}) {
  return () => {
    let record = null;
    return {
      ...readyProfile(),
      'GET /workflows': () => ({ ok: true, workflows: record ? [record] : [] }),
      'GET /workflows/history': { ok: true, history: [] },
      'POST /workflows/compile': (_req, { body }) => {
        compileCalls.push(body);
        if (compile) return compile(body);
        return {
          ok: true,
          workflow: body && body.workflow,
          refusals: [],
          validation_refusals: [],
          preview: [{ position: 0, step_number: 1, action: 'launch_app', target: 'obsidian', summary: 'Launch Obsidian (flatpak run md.obsidian.Obsidian)' }],
          preview_lines: [PREVIEW_LINE],
        };
      },
      'POST /workflows/save': (_req, { body }) => {
        saveCalls.push(body);
        record = {
          id: 'studio_setup',
          name: (body && body.workflow && body.workflow.name) || 'Studio setup',
          trigger_phrases: (body && body.workflow && body.workflow.trigger_phrases) || [],
          steps: (body && body.workflow && body.workflow.steps) || [],
          enabled: Boolean(body && body.enabled),
          // THE RULE: saving never approves.
          approved: false,
          approved_preview: [],
        };
        return { ok: true, workflow: record };
      },
      'POST /workflows/approve': (_req, { body }) => {
        approveCalls.push(body);
        if (!record) return { ok: false, error: 'not_found' };
        record = { ...record, approved: true, approved_preview: (body && body.preview) || [] };
        return { ok: true, workflow: record };
      },
      'POST /workflows/run': (_req, { body }) => {
        runCalls.push(body);
        if (run) return run(body, record);
        if (!record || !record.approved) {
          return { ok: false, error: 'not_approved',
            reason: 'That workflow has not been approved yet, so it cannot run.' };
        }
        return { ok: true, workflow: record, preview_lines: [PREVIEW_LINE] };
      },
      ...extra,
    };
  };
}

function resetCaptures() {
  compileCalls = [];
  saveCalls = [];
  approveCalls = [];
  runCalls = [];
}

async function openWorkflows(page) {
  await page.click('.sd-nav__button[data-nav="utilities"]');
  await expect(page.locator('#workspace-utilities')).toBeVisible();
  await page.click('#sdUtilNavAdvanced');
  await expect(page.locator('#sdUtilWorkflowGroup')).toBeVisible();
}

async function describeWorkflow(page, { steps = 'launch_app: obsidian', enabled = true } = {}) {
  await page.fill('#sdUtilWorkflowName', 'Studio setup');
  await page.fill('#sdUtilWorkflowTriggers', 'open my studio');
  await page.fill('#sdUtilWorkflowSteps', steps);
  if (enabled) await page.check('#sdUtilWorkflowEnabled');
}

export const wave9ActionScenarios = [
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'the-builder-states-what-a-workflow-can-never-do',
    kind: 'standard',
    description:
      'Before anything is typed, the group states the boundary in plain words: a workflow opens applications, '
      + 'folders and links or switches a BetterFingers setting, and never runs shell commands, deletes or moves '
      + 'files, closes programs, or types credentials. Stating it up front is the difference between a user who '
      + 'understands why their request was refused and one who concludes the feature is broken. Run is dead on '
      + 'arrival — there is nothing approved to run.',
    backendState: workflowBackend(),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
    },
    async expects(page) {
      const group = page.locator('#sdUtilWorkflowGroup');
      await expect(group).toContainText('never a script');
      await expect(group).toContainText('does not run shell commands');
      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeDisabled();
      await expect(page.locator('#sdUtilWorkflowApproveButton')).toBeDisabled();
      await expect(page.locator('#sdUtilWorkflowSaveButton')).toBeDisabled();
    },
    screenshots: [{ name: 'the-builder-states-what-a-workflow-can-never-do' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'the-preview-is-exact-and-ordered',
    kind: 'standard',
    description:
      'Building the preview issues exactly one compile call and renders the resolved launch target — '
      + '"flatpak run md.obsidian.Obsidian", not "launch Obsidian". A paraphrase cannot be checked by the person '
      + 'approving it, and approval of an unverifiable summary is not approval. Each row is addressable by its '
      + 'step number so ordering is asserted by identity rather than by reading the text back.',
    backendState: workflowBackend(),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page);
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowCompileButton');
      await expect.poll(() => compileCalls.length, {
        message: 'building the preview must reach the backend exactly once',
      }).toBe(1);
      await expect(page.locator('[data-workflow-preview-step="1"]')).toContainText(
        'flatpak run md.obsidian.Obsidian',
      );
      await expect(page.locator('#sdUtilWorkflowPreview')).toHaveAttribute('data-step-count', '1');
    },
    screenshots: [{ name: 'the-preview-is-exact-and-ordered' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'a-prohibited-step-is-refused-with-a-reason-and-nothing-saves',
    kind: 'standard',
    description:
      'THE Wave 9 rule, asserted end to end: a shell step is refused with the sentence that explains why, and Save '
      + 'stays dead. The failure this prevents is not a crash — it is a workflow that saves happily having quietly '
      + 'dropped the step, then does less than the user described every time it runs. The stub-side capture proves '
      + 'no save call was made, which is the part a screenshot cannot show.',
    backendState: workflowBackend({
      compile: () => ({
        ok: false,
        refusals: [SHELL_REFUSAL],
        validation_refusals: [],
        preview: [],
        preview_lines: [],
      }),
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page, { steps: 'launch_app: obsidian\nshell: rm -rf ~' });
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowCompileButton');
      const refusal = page.locator('[data-workflow-refusal="prohibited_action"]');
      await expect(refusal).toHaveCount(1);
      await expect(refusal).toContainText('never runs shell commands');
      await expect(page.locator('#sdUtilWorkflowSaveButton')).toBeDisabled();
      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeDisabled();
      expect(saveCalls.length, 'a refused workflow must not reach the store').toBe(0);
    },
    screenshots: [{ name: 'a-prohibited-step-is-refused-with-a-reason-and-nothing-saves' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'no-refusal-ever-offers-a-command-line-as-a-workaround',
    kind: 'standard',
    description:
      'A refusal is a product answer, not a hint. Nothing in the group may contain shell syntax, a terminal '
      + 'suggestion, or a copy-pasteable command — offering one would move the exact risk the refusal exists to '
      + 'prevent somewhere with no preview and no approval, while looking like helpfulness. Asserted against the '
      + 'whole group, not just the refusal row, because a "you could instead…" note would live beside it.',
    backendState: workflowBackend({
      compile: () => ({
        ok: false, refusals: [SHELL_REFUSAL], validation_refusals: [], preview: [], preview_lines: [],
      }),
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page, { steps: 'shell: rm -rf ~' });
      await page.click('#sdUtilWorkflowCompileButton');
      await expect(page.locator('[data-workflow-refusal]')).toHaveCount(1);
    },
    async expects(page) {
      const text = (await page.locator('#sdUtilWorkflowGroup').innerText()).toLowerCase();
      for (const token of ['sudo', 'bash -c', 'powershell -', 'cmd.exe', '&&', '$(', 'open a terminal']) {
        expect(text.includes(token), `the UI must never show "${token}"`).toBe(false);
      }
    },
    screenshots: [{ name: 'no-refusal-ever-offers-a-command-line-as-a-workaround' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'a-step-outside-the-application-registry-is-refused',
    kind: 'standard',
    description:
      'A workflow cannot escape the confirmed application registry. A launch step naming an application the user '
      + 'never confirmed is refused with a reason that says what to do about it, and Save stays dead. This is the '
      + 'second half of the boundary: the schema stops verbs that do not exist, and the registry stops targets '
      + 'nobody approved.',
    backendState: workflowBackend({
      compile: () => ({
        ok: false, refusals: [], validation_refusals: [UNKNOWN_APP_REFUSAL],
        preview: [], preview_lines: [],
      }),
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page, { steps: 'launch_app: blender' });
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowCompileButton');
      const refusal = page.locator('[data-workflow-refusal="unknown_application"]');
      await expect(refusal).toHaveCount(1);
      await expect(refusal).toContainText('not one of the applications you confirmed');
      await expect(page.locator('#sdUtilWorkflowSaveButton')).toBeDisabled();
      expect(saveCalls.length).toBe(0);
    },
    screenshots: [{ name: 'a-step-outside-the-application-registry-is-refused' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'saving-is-not-approving-and-run-stays-dead',
    kind: 'standard',
    description:
      'Saving a workflow — even with "turn on when saved" checked — leaves it unapproved and unrunnable. These are '
      + 'two separate decisions and collapsing them would make "keep this for later" and "let a spoken phrase '
      + 'launch this" the same click. The stateful stub returns approved:false from save, and the assertion is on '
      + 'the Run button plus the saved-row attribute, neither of which a hopeful repaint can fake.',
    backendState: workflowBackend(),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page);
      await page.click('#sdUtilWorkflowCompileButton');
      await expect.poll(() => compileCalls.length).toBe(1);
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowSaveButton');
      await expect.poll(() => saveCalls.length).toBe(1);
      expect(saveCalls[0].enabled, 'the enabled choice is sent, not inferred').toBe(true);

      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeDisabled();
      await expect(page.locator('#sdUtilWorkflowApproveButton')).toBeEnabled();
      await expect(
        page.locator('[data-workflow="studio_setup"][data-workflow-approved="false"]'),
      ).toHaveCount(1);
      await expect(page.locator('[data-workflow-blocked]')).toContainText('cannot run');
    },
    screenshots: [{ name: 'saving-is-not-approving-and-run-stays-dead' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'approval-sends-the-exact-preview-the-user-read',
    kind: 'standard',
    description:
      'Approving posts the exact preview LINES, not just an id. That is what lets the backend refuse later when the '
      + 'workflow is untouched but the application behind it was re-confirmed with a different launch method — the '
      + 'approved words and the real behaviour having quietly diverged is precisely the case an approval flag alone '
      + 'cannot catch. Only after this does Run come alive.',
    backendState: workflowBackend(),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page);
      await page.click('#sdUtilWorkflowCompileButton');
      await expect.poll(() => compileCalls.length).toBe(1);
      await page.click('#sdUtilWorkflowSaveButton');
      await expect.poll(() => saveCalls.length).toBe(1);
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowApproveButton');
      await expect.poll(() => approveCalls.length, {
        message: 'approval must reach the backend, not just repaint',
      }).toBe(1);
      expect(approveCalls[0].preview).toEqual([PREVIEW_LINE]);
      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeEnabled();
      await expect(page.locator('#sdUtilWorkflowRunButton')).toHaveAttribute('data-approved', 'true');
    },
    screenshots: [{ name: 'approval-sends-the-exact-preview-the-user-read' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'editing-after-approval-takes-run-away-again',
    kind: 'standard',
    description:
      'Changing a step after approval immediately disables Run and says the preview must be rebuilt. The window '
      + 'this closes is small and total: a Run button that stays live for one repaint after an edit runs steps '
      + 'nobody approved, and nothing on screen would look wrong while it happened.',
    backendState: workflowBackend(),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page);
      await page.click('#sdUtilWorkflowCompileButton');
      await expect.poll(() => compileCalls.length).toBe(1);
      await page.click('#sdUtilWorkflowSaveButton');
      await expect.poll(() => saveCalls.length).toBe(1);
      await page.click('#sdUtilWorkflowApproveButton');
      await expect.poll(() => approveCalls.length).toBe(1);
      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeEnabled();
    },
    async expects(page) {
      await page.fill('#sdUtilWorkflowSteps', 'launch_app: obsidian\nopen_folder: /etc');
      await expect(page.locator('#sdUtilWorkflowRunButton')).toBeDisabled();
      await expect(page.locator('#sdUtilWorkflowMessage')).toContainText('Build the preview again');
      expect(runCalls.length, 'nothing may run during the edit').toBe(0);
    },
    screenshots: [{ name: 'editing-after-approval-takes-run-away-again' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'a-registry-change-after-approval-blocks-the-run',
    kind: 'standard',
    description:
      'Nobody edited the workflow; the application behind it now launches a different way, so the approved preview '
      + 'no longer describes what would happen. The backend refuses at the gate and the UI shows ITS reason rather '
      + 'than claiming the run started. This is the case that makes approval mean something beyond a stored '
      + 'boolean.',
    backendState: workflowBackend({
      run: () => ({
        ok: false,
        error: 'preview_changed',
        reason: 'What this workflow would do has changed since you approved it. Review the new steps and approve '
          + 'them before it runs.',
        preview_lines: ['1. Launch Obsidian (program /usr/bin/obsidian)'],
      }),
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
      await describeWorkflow(page);
      await page.click('#sdUtilWorkflowCompileButton');
      await expect.poll(() => compileCalls.length).toBe(1);
      await page.click('#sdUtilWorkflowSaveButton');
      await expect.poll(() => saveCalls.length).toBe(1);
      await page.click('#sdUtilWorkflowApproveButton');
      await expect.poll(() => approveCalls.length).toBe(1);
    },
    async expects(page) {
      await page.click('#sdUtilWorkflowRunButton');
      await expect.poll(() => runCalls.length).toBe(1);
      await expect(page.locator('#sdUtilWorkflowMessage')).toContainText('has changed since you approved');
      await expect(page.locator('#sdUtilWorkflowMessage')).toHaveAttribute('data-tone', 'danger');
    },
    screenshots: [{ name: 'a-registry-change-after-approval-blocks-the-run' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'a-partial-run-is-reported-as-partial',
    kind: 'standard',
    description:
      'Two of three launched is not success. The run history row reports the status code and the exact count, so a '
      + 'workflow that half-worked cannot read as one that finished. A run summary that said "Done" because it '
      + 'started is the failure Gate 9 names outright — it looks like success and leaves the user to discover the '
      + 'missing application themselves.',
    backendState: workflowBackend({
      extra: {
        'GET /workflows/history': {
          ok: true,
          history: [{
            workflow_id: 'studio_setup',
            at: 0,
            status: 'partial',
            completed: 2,
            total: 3,
            steps: [
              { step_number: 1, action: 'launch_app', status: 'ok' },
              { step_number: 2, action: 'launch_app', status: 'ok' },
              { step_number: 3, action: 'open_folder', status: 'not_found' },
            ],
          }],
        },
      },
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
    },
    async expects(page) {
      const run = page.locator('[data-workflow-run="studio_setup"][data-workflow-run-status="partial"]');
      await expect(run).toHaveCount(1);
      await expect(run).toContainText('2 of 3 steps');
      // And the word that must not appear for a partial run.
      await expect(page.locator('#sdUtilWorkflowHistory')).not.toContainText('success');
    },
    screenshots: [{ name: 'a-partial-run-is-reported-as-partial' }],
  },
  {
    area: 'wave9-actions',
    ui: 'signal-desk-prod',
    name: 'run-history-shows-status-codes-and-no-speech',
    kind: 'standard',
    description:
      'History is a record of what the machine did, not of what was said to it. Asserted against a stub that '
      + 'deliberately returns a transcript and a folder path alongside the codes: neither may reach the screen. One '
      + 'free-text field in a run log is all it takes to turn it into a transcript nobody consented to keeping, and '
      + 'it would look like helpful detail.',
    backendState: workflowBackend({
      extra: {
        'GET /workflows/history': {
          ok: true,
          history: [{
            workflow_id: 'studio_setup',
            at: 0,
            status: 'partial',
            completed: 1,
            total: 2,
            transcript: 'betterfingers open my studio please',
            steps: [
              { step_number: 1, action: 'launch_app', status: 'ok', target: '/home/someone/Private Notes' },
              { step_number: 2, action: 'open_folder', status: 'not_found', error_message: 'no such folder /home/someone/Private Notes' },
            ],
          }],
        },
      },
    }),
    async navigate(page) {
      resetCaptures();
      await openWorkflows(page);
    },
    async expects(page) {
      const history = page.locator('#sdUtilWorkflowHistory');
      await expect(history).toContainText('partial');
      for (const leak of ['open my studio please', 'Private Notes', 'no such folder']) {
        await expect(history, `"${leak}" must never appear in run history`).not.toContainText(leak);
      }
    },
    screenshots: [{ name: 'run-history-shows-status-codes-and-no-speech' }],
  },
];
