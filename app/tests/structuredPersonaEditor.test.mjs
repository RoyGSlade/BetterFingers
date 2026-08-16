import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  appendPersonaAttempt,
  buildStructuredPersonaDraft,
  comparableAttempts,
} from '../src/renderer/features/structuredPersonaEditor.js';

test('structured editor draft preserves separate concerns and locked meaning fields', () => {
  const draft = buildStructuredPersonaDraft({}, {
    displayName: 'Readable Pirate', description: 'Light pirate flavor', kind: 'character_filter', language: 'en-US',
    cleanup: '3', strength: '1', retention: '4', targetLength: 'similar',
    formality: '1', directness: '3', warmth: '2', humor: '1', vocabulary: '2', sentenceLength: 'short_to_medium',
    coreImpression: 'Experienced\nDirect', speakingHabits: 'Occasional nautical metaphor', forbidden: 'No caricature\nNo jokes in serious content',
  });
  assert.equal(draft.metadata.display_name, 'Readable Pirate');
  assert.equal(draft.transformation.persona_strength, 1);
  assert.deepEqual(draft.characterization.core_impression, ['Experienced', 'Direct']);
  assert.equal(draft.meaning_lock.preserve.negation, true);
  assert.equal(draft.meaning_lock.preserve.questions, true);
  assert.equal(draft.output_contract.output_only_rewritten_text, true);
});

test('attempt history retains snapshots and compares current with previous only', () => {
  let attempts = [];
  for (let index = 1; index <= 3; index += 1) {
    attempts = appendPersonaAttempt(attempts, {
      attempt_id: String(index), persona_draft_version: index,
      source_text: `in ${index}`, generated_text: `out ${index}`,
      model_id: 'gemma', settings_snapshot: { version: index },
    });
  }
  assert.equal(attempts.length, 3);
  assert.deepEqual(comparableAttempts(attempts).map((item) => item.attempt_id), ['2', '3']);
  attempts[2].settings_snapshot.version = 99;
  assert.equal(attempts[1].settings_snapshot.version, 2);
});
