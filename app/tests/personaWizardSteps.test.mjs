// The manual Persona Wizard's four steps, the describe-it-in-words path and
// the prompt-refinement panel, driven through the real DOM wiring.
//
// CURRENT_UI_INVENTORY.md section 7.5.1 (parity rows UI-07-052, -058, -072,
// -074). The wizard is the surface where a user hands a description to their
// local model and gets a persona back; the two lines that carry that
// conversation -- #wizardDescribeStatus and #wizardRefineStatus -- are the
// difference between "the model is working" and "the model refused", and
// nothing exercised either.
//
// features/personaFlow.js already exports the id list and a collector, so the
// element map here is built by production code: WIZARD_ELEMENT_IDS is the
// contract createPersonasFeature() expects and every entry equals its DOM id.
//
// Run with: node --test app/tests/personaWizardSteps.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { WIZARD_ELEMENT_IDS, collectPersonaWizardElements } from '../src/renderer/features/personaFlow.js';
import { createPersonasFeature } from '../src/renderer/features/personas.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

test('the wizard element contract names the ids the parity inventory tracks', () => {
  for (const id of ['wizardStepProgress', 'wizardDescribeStatus', 'wizardDescribeInput', 'wizardDescribeButton',
    'wizardRefineStatus', 'wizardRefinePanel', 'wizardRefineUnderstood', 'wizardRefineAmbiguities',
    'wizardRefinedPrompt', 'wizardAdvanced']) {
    assert.ok(WIZARD_ELEMENT_IDS.includes(id), `${id} is no longer part of the wizard element contract`);
  }
});

const STEP_IDS = ['wizardStep1', 'wizardStep2', 'wizardStep3', 'wizardStep4'];

function mount({ routes = {} } = {}) {
  const doc = makeDocument([...WIZARD_ELEMENT_IDS, ...STEP_IDS], {
    wizardRole: { tagName: 'select', value: 'assistant' },
    wizardCustomRole: { tagName: 'input', type: 'text' },
    wizardTone: { tagName: 'select', value: 'neutral' },
    wizardCustomTone: { tagName: 'input', type: 'text' },
    wizardPersonaName: { tagName: 'input', type: 'text' },
    wizardPromptPreview: { tagName: 'textarea', value: '' },
    wizardRefinedPrompt: { tagName: 'textarea', value: '' },
    wizardDescribeInput: { tagName: 'textarea', value: '' },
    wizardTemperature: { tagName: 'input', type: 'number', value: '' },
    wizardModelHint: { tagName: 'input', type: 'text' },
    wizardFormatCaps: { tagName: 'select', value: 'none' },
    wizardFormatPunctuation: { tagName: 'input', type: 'checkbox' },
    wizardFormatSignoff: { tagName: 'input', type: 'text' },
    wizardOutputPolicy: { tagName: 'select', value: 'preserve' },
    wizardSafetyMode: { tagName: 'select', value: 'standard' },
    wizardMaxCompletionTokens: { tagName: 'input', type: 'number' },
    wizardChunkSize: { tagName: 'input', type: 'number' },
    wizardTestSample: { tagName: 'textarea', value: '' },
    wizardRuleLength: { tagName: 'input', type: 'checkbox' },
    wizardRuleCommands: { tagName: 'input', type: 'checkbox' },
    wizardRuleNoPreamble: { tagName: 'input', type: 'checkbox' },
    wizardRuleSanitize: { tagName: 'input', type: 'checkbox' },
    wizardAdvanced: { tagName: 'details', open: false },
  });
  const bridge = makeBackendBridge({ 'GET /personas-builtins': { builtins: ['True Janitor', 'Formal'] }, ...routes });
  const toasts = [];
  const restore = installDomGlobals({ document: doc, betterFingers: { backendRequest: bridge.request } });
  const feature = createPersonasFeature({
    elements: collectPersonaWizardElements(doc),
    ui: { setMessage: () => {}, showToast: (message, tone) => toasts.push({ message, tone }) },
    hooks: { getLoadedPersonas: () => ({}), refreshPersonasAndVoices: async () => {}, markProfileDirty: () => {} },
    doc,
  });
  feature.initWizard();
  return { doc, feature, bridge, toasts, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-07-052: the "Step N of 4" progress label ------------------------------

test('#wizardStepProgress names the step number AND what that step is for', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);

  const progress = ctx.el('wizardStepProgress');
  const next = ctx.el('wizardNextButton');
  assert.ok(next.listenerCount('click') > 0, 'the wizard Next button was never bound');

  // Step 1 is painted as soon as the wizard is stepped, and each Next both
  // advances the label and swaps which step section is visible.
  next.click();
  assert.equal(progress.textContent, 'Step 2 of 4: Configure Tone & Voice Style');
  assert.equal(ctx.el('wizardStep2').classList.contains('hidden'), false);
  assert.equal(ctx.el('wizardStep1').classList.contains('hidden'), true);

  next.click();
  assert.equal(progress.textContent, 'Step 3 of 4: Define Strict Rules');

  next.click();
  assert.equal(progress.textContent, 'Step 4 of 4: Save & Preview');
  assert.equal(ctx.el('wizardStep4').classList.contains('hidden'), false);
});

test('#wizardStepProgress goes back as well as forward, and never past either end', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  const progress = ctx.el('wizardStepProgress');

  for (let i = 0; i < 6; i += 1) ctx.el('wizardNextButton').click();
  assert.equal(progress.textContent, 'Step 4 of 4: Save & Preview', 'Next must stop at the last step');

  for (let i = 0; i < 6; i += 1) ctx.el('wizardPrevButton').click();
  assert.equal(progress.textContent, 'Step 1 of 4: Select Goal & Role', 'Back must stop at the first step');
  assert.equal(ctx.el('wizardStep1').classList.contains('hidden'), false);
});

// --- UI-07-058: the describe-it-in-words status line --------------------------

const DRAFTED_PERSONA = {
  name: 'True Janitor',
  prompt: 'Clean the text without changing what it means.',
  temperature: 0.05,
  output_policy: 'preserve',
  safety_mode: 'standard',
  understood: ['Keep the meaning exactly.'],
  ambiguities: [],
  few_shot: [{ raw: 'gonna ship it', out: 'Going to ship it.' }],
};

test('#wizardDescribeStatus refuses an empty description before any model call', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/draft': DRAFTED_PERSONA } });
  t.after(ctx.restore);

  ctx.el('wizardDescribeInput').value = '   ';
  ctx.el('wizardDescribeButton').click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('wizardDescribeStatus').textContent, 'Describe the persona first — a couple of sentences is plenty.');
  assert.equal(ctx.bridge.find('POST', '/personas/draft'), null, 'nothing may reach the model without a description');
});

test('#wizardDescribeStatus clears once the model answers, and the result lands on step 4', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/draft': DRAFTED_PERSONA } });
  t.after(ctx.restore);

  ctx.el('wizardDescribeInput').value = 'someone who tidies my speech without editorialising';
  ctx.el('wizardDescribeButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.find('POST', '/personas/draft').body, {
    description: 'someone who tidies my speech without editorialising',
  });
  assert.equal(ctx.el('wizardDescribeStatus').textContent, '', 'a finished run must not leave "designing…" on screen');
  assert.equal(ctx.el('wizardStepProgress').textContent, 'Step 4 of 4: Save & Preview');
  assert.equal(ctx.el('wizardPromptPreview').value, DRAFTED_PERSONA.prompt);
  assert.equal(ctx.el('wizardDescribeButton').disabled, false, 'the button must be usable again');
});

test('a drafted name that collides with a built-in persona is renamed rather than shadowing it', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/draft': DRAFTED_PERSONA } });
  t.after(ctx.restore);
  // Let the built-in list load first -- that is what the collision check reads.
  await new Promise((resolve) => setImmediate(resolve));

  ctx.el('wizardDescribeInput').value = 'a tidy-up persona';
  ctx.el('wizardDescribeButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(ctx.el('wizardPersonaName').value, 'True Janitor (mine)');
});

test('#wizardAdvanced is opened when the model attached few-shot examples, so they are reviewed not smuggled', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/draft': DRAFTED_PERSONA } });
  t.after(ctx.restore);

  const advanced = ctx.el('wizardAdvanced');
  assert.equal(advanced.open, false);

  ctx.el('wizardDescribeInput').value = 'a tidy-up persona';
  ctx.el('wizardDescribeButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(advanced.open, true, 'generated examples live in Advanced and must be visible for review');
});

test('#wizardDescribeStatus reports a model failure instead of a silent no-op', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/draft': { ok: false, status: 503, body: { detail: 'the LLM is not loaded' } } } });
  t.after(ctx.restore);

  ctx.el('wizardDescribeInput').value = 'a tidy-up persona';
  ctx.el('wizardDescribeButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(ctx.el('wizardDescribeStatus').textContent, /the LLM is not loaded/);
  assert.equal(ctx.el('wizardDescribeButton').disabled, false);
});

// --- UI-07-072: the refinement panel ------------------------------------------

const REFINED = {
  refined_prompt: 'Rewrite the transcript cleanly. Never add information.',
  understood: ['Tone should stay neutral.'],
  ambiguities: ['How formal is "neutral"?'],
  lint_warnings: [],
};

test('#wizardRefinePanel stays hidden until the model has actually answered', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/refine': REFINED } });
  t.after(ctx.restore);

  const panel = ctx.el('wizardRefinePanel');
  ctx.el('wizardPromptPreview').value = 'be neutral and brief';
  ctx.el('wizardRefinePromptButton').click();
  assert.equal(ctx.el('wizardRefineStatus').textContent, 'Asking your local model… (this uses the LLM you have downloaded)');
  assert.equal(panel.classList.contains('hidden'), true, 'the panel must not show a stale reading while a new one is running');

  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(panel.classList.contains('hidden'), false);
});

test('#wizardRefineUnderstood and #wizardRefineAmbiguities carry the two halves of the model reading', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/refine': REFINED } });
  t.after(ctx.restore);

  ctx.el('wizardPromptPreview').value = 'be neutral and brief';
  ctx.el('wizardRuleSanitize').checked = true;
  ctx.el('wizardRefinePromptButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  const sent = ctx.bridge.find('POST', '/personas/refine').body;
  assert.equal(sent.prompt, 'be neutral and brief');
  assert.deepEqual(sent.rules, ['sanitize profanity/hostile language'], 'the ticked rules must travel with the draft');

  assert.match(ctx.el('wizardRefineUnderstood').textContent, /Tone should stay neutral\./);
  assert.match(ctx.el('wizardRefineAmbiguities').textContent, /How formal is "neutral"\?/);
  assert.equal(ctx.el('wizardRefinedPrompt').value, REFINED.refined_prompt);
  assert.match(ctx.el('wizardRefineStatus').textContent, /Review the model's reading below/);
});

test('#wizardRefineAmbiguities says "nothing" rather than going blank when the model found none', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/refine': { ...REFINED, ambiguities: [] } } });
  t.after(ctx.restore);

  ctx.el('wizardPromptPreview').value = 'be neutral and brief';
  ctx.el('wizardRefinePromptButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(ctx.el('wizardRefineAmbiguities').textContent, /Nothing — it found your description clear\./);
});

test('#wizardRefineStatus surfaces lint warnings alongside the reading', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/refine': { ...REFINED, lint_warnings: ['Prompt is very long.'] } } });
  t.after(ctx.restore);

  ctx.el('wizardPromptPreview').value = 'be neutral and brief';
  ctx.el('wizardRefinePromptButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(ctx.el('wizardRefineStatus').textContent, /Lint: Prompt is very long\./);
});

test('#wizardRefineStatus refuses an empty draft and reports a failed refine', async (t) => {
  const ctx = mount({ routes: { 'POST /personas/refine': { ok: false, status: 500, body: { detail: 'refine crashed' } } } });
  t.after(ctx.restore);

  ctx.el('wizardPromptPreview').value = '';
  ctx.el('wizardRefinePromptButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('wizardRefineStatus').textContent, 'Write or generate a draft prompt first.');
  assert.deepEqual(ctx.bridge.signatures().filter((s) => s.includes('refine')), []);

  ctx.el('wizardPromptPreview').value = 'be neutral and brief';
  ctx.el('wizardRefinePromptButton').click();
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(ctx.el('wizardRefineStatus').textContent, 'Persona helper failed: refine crashed');
  assert.equal(ctx.el('wizardRefinePromptButton').disabled, false);
});
