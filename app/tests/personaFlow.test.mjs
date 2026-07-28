// Persona creation on the guided-flow shell (features/personaFlow.js).
//
// The interesting property here is that personaFlow does NOT own stepping --
// the wizard and the Foundry each drive their own, and the dialog chrome
// follows via observers. These tests pin that the following is faithful in both
// directions, because the failure mode is a dialog whose header says one thing
// while its body shows another.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  FOUNDRY_STEPS,
  WIZARD_ELEMENT_IDS,
  WIZARD_STEPS,
  collectPersonaWizardElements,
  createPersonaFlow,
  foundryStepIdFor,
  wizardStepIdFor,
} from '../src/renderer/features/personaFlow.js';

// --- pure mapping ------------------------------------------------------------

test('both paths are four steps ending in Review & save', () => {
  assert.equal(WIZARD_STEPS.length, 4);
  assert.equal(FOUNDRY_STEPS.length, 4);
  assert.equal(WIZARD_STEPS.at(-1).title, 'Review & save');
  assert.equal(FOUNDRY_STEPS.at(-1).title, 'Review & save');
});

test('the two paths address different markup sections', () => {
  // If they overlapped, one path's Back would land in the other's screens.
  const wizardIds = new Set(WIZARD_STEPS.map((s) => s.id));
  const overlap = FOUNDRY_STEPS.filter((s) => wizardIds.has(s.id));
  assert.deepEqual(overlap, []);
});

test('wizard step numbers map to step ids, 1-indexed', () => {
  assert.equal(wizardStepIdFor(1), 'wizard1');
  assert.equal(wizardStepIdFor(4), 'wizard4');
  assert.equal(wizardStepIdFor(0), null);
  assert.equal(wizardStepIdFor(5), null);
});

test('unknown Foundry screens map to nothing rather than to step 1', () => {
  assert.equal(foundryStepIdFor('collection'), 'collection');
  assert.equal(foundryStepIdFor('closed'), null);
  assert.equal(foundryStepIdFor('somethingNew'), null);
});

// --- element collection ------------------------------------------------------

test('every wizard element key equals its DOM id', () => {
  // createPersonasFeature destructures by these names; a mismatch would leave a
  // control silently unbound rather than throw.
  const doc = { getElementById: (id) => ({ id }) };
  const els = collectPersonaWizardElements(doc);
  for (const key of WIZARD_ELEMENT_IDS) {
    assert.equal(els[key]?.id, key, `${key} did not resolve to its own id`);
  }
});

test('the collected set covers the wizard controls the inventory lists', () => {
  // Spot-checks across every group, so a truncated port fails here rather than
  // at runtime on a control nobody clicked during QA.
  for (const id of [
    'wizardRole', 'wizardCustomRole', 'wizardTone', 'wizardCustomTone',
    'wizardRuleLength', 'wizardRuleCommands', 'wizardRuleNoPreamble', 'wizardRuleSanitize',
    'wizardPersonaName', 'wizardPromptPreview', 'wizardRegeneratePromptButton',
    'wizardRefinePromptButton', 'wizardApplyRefinedButton', 'wizardDismissRefinedButton',
    'wizardDescribeInput', 'wizardDescribeButton',
    'wizardTemperature', 'wizardModelHint', 'wizardFormatCaps', 'wizardFormatPunctuation',
    'wizardFormatSignoff', 'wizardOutputPolicy', 'wizardSafetyMode',
    'wizardMaxCompletionTokens', 'wizardChunkSize',
    'wizardFewShotList', 'wizardAddFewShotButton',
    'wizardLintButton', 'wizardTestSample', 'wizardTestButton',
    'wizardPrevButton', 'wizardNextButton', 'wizardDeleteButton', 'wizardMessage',
  ]) {
    assert.ok(WIZARD_ELEMENT_IDS.includes(id), `${id} missing from the element map`);
  }
});

// --- wiring ------------------------------------------------------------------

const ALL_STEP_IDS = [...WIZARD_STEPS, ...FOUNDRY_STEPS].map((s) => s.id);

function makeEl(extra = {}) {
  const listeners = {};
  return {
    hidden: false,
    disabled: false,
    textContent: '',
    dataset: {},
    classes: new Set(),
    offsetParent: {},
    classList: {
      add(c) { this.owner.classes.add(c); },
      remove(c) { this.owner.classes.delete(c); },
    },
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    removeEventListener: (evt) => { delete listeners[evt]; },
    focus() { this.focused = true; },
    click() { this.clicked = (this.clicked || 0) + 1; },
    fire: (evt) => listeners[evt]?.(),
    ...extra,
  };
}

function harness() {
  // Captured rather than registered globally: personas.js keeps its observers in
  // module state, so two flows in one test file would fight over them.
  const registered = {};
  const title = makeEl();
  const progress = makeEl({ setAttribute(name, value) { this.dataset[name] = value; } });
  const stepEls = ALL_STEP_IDS.map((id) => makeEl({ dataset: { flowStep: id } }));
  const footer = makeEl();
  const trigger = makeEl();
  const nameInput = makeEl();

  const classes = new Set(['hidden']);
  const root = {
    hidden: true,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
    querySelector: (sel) => ({ '[data-flow-title]': title, '[data-flow-progress]': progress }[sel] ?? null),
    querySelectorAll: (sel) => (sel === '[data-flow-step]' ? stepEls : []),
  };

  const doc = {
    activeElement: null,
    addEventListener() {},
    removeEventListener() {},
    getElementById: (id) => (id === 'wizardPersonaName' ? nameInput : null),
  };

  const flow = createPersonaFlow({
    root,
    footer,
    foundryTrigger: trigger,
    doc,
    observeWizardStep: (fn) => { registered.wizardStep = fn; },
    observeFoundryScreen: (fn) => { registered.foundryScreen = fn; },
  });
  const visible = () => ALL_STEP_IDS.filter((_id, i) => !stepEls[i].hidden);
  return { flow, root, classes, footer, trigger, title, visible, nameInput, registered };
}

test('the manual entry opens on Goal & role with the wizard footer', () => {
  const h = harness();
  h.flow.openWizard();
  assert.equal(h.flow.getActivePath(), 'wizard');
  assert.deepEqual(h.visible(), ['wizard1']);
  assert.equal(h.title.textContent, 'Goal & role');
  assert.equal(h.footer.hidden, false);
  assert.equal(h.root.hidden, false);
  assert.equal(h.classes.has('hidden'), false, 'the .hidden class must be cleared too');
});

test('the AI entry opens on Interview and starts the interview', () => {
  const h = harness();
  h.flow.openFoundry();
  assert.equal(h.flow.getActivePath(), 'foundry');
  assert.deepEqual(h.visible(), ['interview']);
  assert.equal(h.title.textContent, 'Interview');
  assert.equal(h.trigger.clicked, 1, 'personas.js owns starting the interview');
});

test('the Foundry path hides the wizard footer', () => {
  // Every Foundry advance is a Continue button inside the screen that produced
  // the thing being continued from; a footer Next would have nothing to do.
  const h = harness();
  h.flow.openFoundry();
  assert.equal(h.footer.hidden, true);
});

test('the chrome follows the wizard rather than driving it', () => {
  // personas.js calls this from showStep(), including its jump straight to
  // step 4 when the model drafts a persona from a description.
  const h = harness();
  h.flow.openWizard();

  h.registered.wizardStep(3);
  assert.deepEqual(h.visible(), ['wizard3']);
  assert.equal(h.title.textContent, 'Rules');

  h.registered.wizardStep(4);
  assert.deepEqual(h.visible(), ['wizard4']);
  assert.equal(h.title.textContent, 'Review & save');
});

test('the chrome follows the Foundry through its screens', () => {
  const h = harness();
  h.flow.openFoundry();

  for (const [screen, title] of [
    ['collection', 'Examples'],
    ['stressTest', 'Stress test'],
    ['review', 'Review & save'],
  ]) {
    h.registered.foundryScreen(screen);
    assert.deepEqual(h.visible(), [screen]);
    assert.equal(h.title.textContent, title);
  }
});

test('observers are ignored for the path that is not open', () => {
  // Both builders stay alive between openings, so a stray showStep() from the
  // wizard must not drag a running interview onto a wizard screen.
  const h = harness();
  h.flow.openFoundry();
  h.registered.wizardStep(2);
  assert.deepEqual(h.visible(), ['interview'], 'the wizard moved a Foundry dialog');
});

test('a Foundry close closes the dialog from either path', () => {
  // personas.js binds the dialog's x to foundryClose(), so this is the close
  // button as well as the post-save close.
  const h = harness();
  h.flow.openWizard();
  h.registered.foundryScreen('closed');
  assert.equal(h.root.hidden, true);
  assert.equal(h.classes.has('hidden'), true);
  assert.equal(h.flow.getActivePath(), null);
});

test('closing clears both flows and both hiding mechanisms', () => {
  // The two share a root, so leaving the other flow open would keep its Escape
  // handler bound after the dialog is gone.
  const h = harness();
  h.flow.openWizard();
  h.flow.close();
  assert.equal(h.root.hidden, true);
  assert.equal(h.classes.has('hidden'), true);
  assert.equal(h.flow.getActivePath(), null);
});

test('reopening after a close works from either entry', () => {
  const h = harness();
  h.flow.openWizard();
  h.flow.close();
  h.flow.openFoundry();
  assert.equal(h.root.hidden, false);
  assert.equal(h.classes.has('hidden'), false);
  assert.deepEqual(h.visible(), ['interview']);
});

// --- trait sliders (Stage 10) -------------------------------------------------

test('the wizard element map carries all five trait sliders and their bands', () => {
  // A slider the composition root never looks up is a control the user can drag
  // that changes nothing on save.
  for (const key of ['Warmth', 'Directness', 'Detail', 'Formality', 'Confidence']) {
    assert.ok(WIZARD_ELEMENT_IDS.includes(`wizardTrait${key}`), `wizardTrait${key} missing`);
    assert.ok(WIZARD_ELEMENT_IDS.includes(`wizardTrait${key}Band`), `wizardTrait${key}Band missing`);
  }
});
