import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  buildPersonaTestMaterial,
  buildPersonaTestPrompt,
  cleanPersonaTestOutput,
  describePersonaTestSettings,
} from '../src/renderer/features/studioWorkspace.js';

test('persona test material keeps the visible sample distinct from rewrite instructions', () => {
  assert.equal(
    buildPersonaTestMaterial('Could you send this tomorrow?'),
    '[PERSONA TEST MATERIAL]\nCould you send this tomorrow?\n[END PERSONA TEST MATERIAL]',
  );
});

test('persona test prompt explicitly demonstrates rewriting instead of answering', () => {
  const prompt = buildPersonaTestPrompt('Be warm and concise.');
  assert.match(prompt, /Be warm and concise\./);
  assert.match(prompt, /rewriting the supplied PERSONA TEST MATERIAL/);
  assert.match(prompt, /not as a request for you to answer/);
  assert.match(prompt, /Return only the rewritten text/);
});

test('persona test output never exposes echoed internal material markers', () => {
  assert.equal(
    cleanPersonaTestOutput('Cleaned: [PERSONA TEST MATERIAL]\nhello there\n[END PERSONA TEST MATERIAL]'),
    'Cleaned: hello there',
  );
});

test('persona test settings summary reports defaults and persona overrides truthfully', () => {
  assert.match(describePersonaTestSettings({}), /temperature 0\.3 default/);
  assert.match(describePersonaTestSettings({}), /policy preserve/);
  assert.match(describePersonaTestSettings({}), /safety strict/);
  assert.match(describePersonaTestSettings({}), /max tokens profile default/);

  const summary = describePersonaTestSettings({
    temperature: 0.8,
    output_policy: 'tighten',
    safety_mode: 'light',
    max_completion_tokens: 900,
  });
  assert.match(summary, /temperature 0\.8/);
  assert.match(summary, /policy tighten/);
  assert.match(summary, /safety light/);
  assert.match(summary, /max tokens 900/);
});
