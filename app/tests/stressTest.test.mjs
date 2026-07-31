import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  STRESS_TEST_DISABLED_MESSAGE,
  STRESS_TEST_SAMPLES,
  createStudioWorkspaceFeature,
} from '../src/renderer/features/studioWorkspace.js';

function makeButton() {
  const listeners = {};
  return {
    disabled: false,
    title: '',
    attributes: {},
    addEventListener(type, handler) {
      listeners[type] = handler;
    },
    setAttribute(name, value) {
      this.attributes[name] = value;
    },
    listeners,
  };
}

test('Persona Studio no longer carries a prompt-injection probe', () => {
  assert.ok(STRESS_TEST_SAMPLES.length > 0);
  assert.equal(
    STRESS_TEST_SAMPLES.some(({ category }) => category.toLowerCase().includes('injection')),
    false,
  );
  assert.equal(STRESS_TEST_SAMPLES.some(({ sample }) => /previous/i.test(sample)), false);
});

test('Persona Studio Stress Test control is disabled and points to Diagnostics', () => {
  const button = makeButton();
  const feature = createStudioWorkspaceFeature({ elements: { stressButton: button } });

  feature.init();

  assert.equal(button.disabled, true);
  assert.equal(button.title, 'Moved to Pipeline Latency / Diagnostics.');
  assert.equal(
    button.attributes['aria-label'],
    'Stress Test unavailable in Persona Studio; use Pipeline Latency / Diagnostics',
  );
});

test('direct Stress Test handler reports unavailable without running a backend probe', async () => {
  const messages = [];
  const feature = createStudioWorkspaceFeature({
    elements: {},
    hooks: { showToast: (message, tone) => messages.push({ message, tone }) },
  });

  feature.setPersonas({ Natural: { prompt: 'persona prompt' } });
  await feature.handleStressTestClick();

  assert.deepEqual(messages, [{ message: STRESS_TEST_DISABLED_MESSAGE, tone: 'warning' }]);
});
