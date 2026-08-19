// Unit tests for the Settings workspace wiring adapter's PURE helpers
// (docs/ui/SIGNAL_DESK_SPEC.md section 8, CURRENT_UI_INVENTORY.md section 7).
// Mirrors studioWorkspace.test.mjs/utilitiesWorkspace.test.mjs's approach:
// only DOM-free "data -> view model" logic and the section router are
// exercised here -- createSettingsWorkspaceFeature()'s DOM wiring itself
// needs a real document and is exercised manually via
// signal-desk-preview.html per the phase brief.
//
// Also includes the director's "no-orphan gate" completeness check (every
// inventory item the work packet calls out by name for Settings must have a
// home in INVENTORY_PLACEMENT_MAP), plus explicit regression tests for the
// two bugs the work packet named:
//   - BUG #1 (rename/duplicate/export profile buttons never bound) --
//     covered structurally: SETTINGS_ELEMENT_IDS/collectSettingsElements
//     include real ids for all three, unlike main.js's bare identifiers.
//   - draft_history_limit not collected/restored -- covered by the
//     collect/restore round-trip test asserting it survives the cycle.
//
// Run with: node --test app/tests/settingsWorkspace.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_SECTIONS,
  SETTINGS_SECTION_META,
  isValidSettingsSection,
  computeNextSettingsSection,
  INVENTORY_PLACEMENT_MAP,
  VALID_THEMES,
  VALID_ACCENTS,
  VALID_DENSITIES,
  VALID_FONT_SIZES,
  normalizeAppearancePrefs,
  computeAppearanceClasses,
  formatPercentFromFraction,
  validateProfileName,
  SETTINGS_VALIDATION_RULES,
  validateFieldValue,
  runSettingsValidation,
  SETTINGS_FIELD_KEYS,
  SETTINGS_FIELD_TYPES,
  SETTINGS_DEFAULT_ON_KEYS,
  collectPatchFromFieldStates,
  restoreFieldStatesFromSettings,
  mergeProfilePatch,
  buildLegacyProfileImportPayload,
  rowMatchesQuery,
  SETTINGS_ELEMENT_IDS,
  collectSettingsElements,
  createSettingsWorkspaceFeature,
  DISCLOSED_TOGGLES,
  disclosedToggleFor,
  disclosureRowsFor,
  toggleIsInteractive,
  toggleStateFrom,
  normalizeUpdateState,
  buildUpdateViewModel,
} from '../src/renderer/features/settingsWorkspace.js';

// --- section routing (pure reducer, same contract as signalDeskShell.js / utilitiesWorkspace.js) ---

test('SETTINGS_SECTIONS: exactly the 7 sections named in the work packet', () => {
  assert.deepEqual(SETTINGS_SECTIONS, ['profile', 'recording', 'review', 'aicleanup', 'notifications', 'appearance', 'privacy']);
});

test('SETTINGS_SECTION_META: every section has a label and description', () => {
  for (const id of SETTINGS_SECTIONS) {
    assert.ok(SETTINGS_SECTION_META[id]?.label, `${id} missing a label`);
    assert.ok(SETTINGS_SECTION_META[id]?.description, `${id} missing a description`);
  }
});

test('isValidSettingsSection: only the 7 known ids are valid', () => {
  for (const id of SETTINGS_SECTIONS) assert.equal(isValidSettingsSection(id), true);
  assert.equal(isValidSettingsSection('utilities'), false);
  assert.equal(isValidSettingsSection('bogus'), false);
  assert.equal(isValidSettingsSection(undefined), false);
});

test('computeNextSettingsSection: switches to a valid requested section', () => {
  const next = computeNextSettingsSection({ active: 'profile' }, 'privacy');
  assert.deepEqual(next, { active: 'privacy' });
});

test('computeNextSettingsSection: an unknown id is a no-op (stays on current)', () => {
  const next = computeNextSettingsSection({ active: 'review' }, 'bogus');
  assert.deepEqual(next, { active: 'review' });
});

test('computeNextSettingsSection: a missing/invalid current state falls back to the first section', () => {
  const next = computeNextSettingsSection(undefined, 'appearance');
  assert.deepEqual(next, { active: 'appearance' });
  const next2 = computeNextSettingsSection({ active: 'not-a-section' }, 'bogus');
  assert.deepEqual(next2, { active: 'profile' });
});

// --- appearance: normalize + class mapping ----------------------------------

test('normalizeAppearancePrefs: valid values pass through unchanged', () => {
  const result = normalizeAppearancePrefs({ theme: 'dark', accent: 'purple', density: 'compact', fontSize: 'large', highContrast: true });
  assert.deepEqual(result, { theme: 'dark', accent: 'purple', density: 'compact', fontSize: 'large', highContrast: true });
});

test('normalizeAppearancePrefs: invalid/missing values fall back to documented defaults', () => {
  const result = normalizeAppearancePrefs({ theme: 'neon', accent: 'chartreuse', density: 'roomy', fontSize: 'gigantic' });
  assert.deepEqual(result, { theme: 'system', accent: 'teal', density: 'comfortable', fontSize: 'medium', highContrast: false });
});

test('normalizeAppearancePrefs: highContrast accepts boolean true or the string "true" only', () => {
  assert.equal(normalizeAppearancePrefs({ highContrast: true }).highContrast, true);
  assert.equal(normalizeAppearancePrefs({ highContrast: 'true' }).highContrast, true);
  assert.equal(normalizeAppearancePrefs({ highContrast: 'false' }).highContrast, false);
  assert.equal(normalizeAppearancePrefs({ highContrast: false }).highContrast, false);
  assert.equal(normalizeAppearancePrefs({}).highContrast, false);
});

test('VALID_* enums match main.js exactly (theme/accent/density/fontSize)', () => {
  assert.deepEqual(VALID_THEMES, ['system', 'dark', 'light']);
  assert.deepEqual(VALID_ACCENTS, ['teal', 'purple', 'blue', 'gold']);
  assert.deepEqual(VALID_DENSITIES, ['comfortable', 'compact']);
  assert.deepEqual(VALID_FONT_SIZES, ['small', 'medium', 'large', 'huge']);
});

test('computeAppearanceClasses: explicit dark theme resolves to theme-dark regardless of prefersDark', () => {
  const plan = computeAppearanceClasses({ theme: 'dark', accent: 'blue', density: 'compact', fontSize: 'huge', highContrast: true, prefersDark: false });
  assert.equal(plan.resolvedThemeClass, 'theme-dark');
  assert.deepEqual(plan.bodyAdd, ['theme-dark', 'accent-blue', 'density-compact', 'high-contrast']);
  assert.equal(plan.htmlClass, 'font-huge');
});

test('computeAppearanceClasses: explicit light theme resolves to theme-light regardless of prefersDark', () => {
  const plan = computeAppearanceClasses({ theme: 'light', prefersDark: true });
  assert.equal(plan.resolvedThemeClass, 'theme-light');
});

test('computeAppearanceClasses: theme="system" resolves from prefersDark', () => {
  assert.equal(computeAppearanceClasses({ theme: 'system', prefersDark: true }).resolvedThemeClass, 'theme-dark');
  assert.equal(computeAppearanceClasses({ theme: 'system', prefersDark: false }).resolvedThemeClass, 'theme-light');
});

test('computeAppearanceClasses: highContrast=false omits the high-contrast class from bodyAdd', () => {
  const plan = computeAppearanceClasses({ theme: 'dark', highContrast: false });
  assert.equal(plan.bodyAdd.includes('high-contrast'), false);
});

test('computeAppearanceClasses: bodyRemove always lists every possible theme/accent/density/high-contrast class (so stale classes never linger)', () => {
  const plan = computeAppearanceClasses({});
  for (const cls of ['theme-light', 'theme-dark', 'accent-teal', 'accent-purple', 'accent-blue', 'accent-gold', 'density-compact', 'density-comfortable', 'high-contrast']) {
    assert.ok(plan.bodyRemove.includes(cls), `bodyRemove missing ${cls}`);
  }
});

test('formatPercentFromFraction: rounds 0..1 fractions to whole percents', () => {
  assert.equal(formatPercentFromFraction(1), '100%');
  assert.equal(formatPercentFromFraction(0.5), '50%');
  assert.equal(formatPercentFromFraction(0.156), '16%');
  assert.equal(formatPercentFromFraction('0.3'), '30%');
});

test('formatPercentFromFraction: non-numeric input is treated as 0', () => {
  assert.equal(formatPercentFromFraction('not-a-number'), '0%');
  assert.equal(formatPercentFromFraction(undefined), '0%');
});

// --- profile name validation (mirrors main.js's validateProfileName) --------

test('validateProfileName: rejects empty/whitespace-only names', () => {
  assert.match(validateProfileName(''), /cannot be empty/);
  assert.match(validateProfileName('   '), /cannot be empty/);
  assert.match(validateProfileName(undefined), /cannot be empty/);
});

test('validateProfileName: rejects names with disallowed characters', () => {
  assert.match(validateProfileName('my profile!'), /letters, numbers, underscores, and hyphens/);
  assert.match(validateProfileName('a/b'), /letters, numbers, underscores, and hyphens/);
});

test('validateProfileName: rejects reserved names case-insensitively', () => {
  assert.match(validateProfileName('Default'), /reserved profile name/);
  assert.match(validateProfileName('IMPORT'), /reserved profile name/);
});

test('validateProfileName: accepts a well-formed, non-reserved name', () => {
  assert.equal(validateProfileName('Work-Profile_2'), null);
});

// --- range validation --------------------------------------------------------

test('SETTINGS_VALIDATION_RULES: includes draft_history_limit at 10-500 (the wiring-fix field)', () => {
  assert.deepEqual(SETTINGS_VALIDATION_RULES.draft_history_limit, { min: 10, max: 500, parse: 'int', message: SETTINGS_VALIDATION_RULES.draft_history_limit.message });
});

test('validateFieldValue: max_completion_tokens rejects out-of-range and accepts in-range', () => {
  assert.match(validateFieldValue('max_completion_tokens', '100'), /512 and 4096/);
  assert.match(validateFieldValue('max_completion_tokens', '5000'), /512 and 4096/);
  assert.equal(validateFieldValue('max_completion_tokens', '2048'), null);
  assert.equal(validateFieldValue('max_completion_tokens', '512'), null);
  assert.equal(validateFieldValue('max_completion_tokens', '4096'), null);
});

test('validateFieldValue: non-numeric input is an error', () => {
  assert.match(validateFieldValue('max_completion_tokens', 'abc'), /512 and 4096/);
});

test('validateFieldValue: fields with no rule always return null', () => {
  assert.equal(validateFieldValue('recording_mode', 'toggle'), null);
  assert.equal(validateFieldValue('not_a_real_field', '123'), null);
});

test('validateFieldValue: float-parsed fields accept boundary values (confidence thresholds 0.0-1.0)', () => {
  assert.equal(validateFieldValue('confidence_force_review_below', '0'), null);
  assert.equal(validateFieldValue('confidence_force_review_below', '1'), null);
  assert.equal(validateFieldValue('confidence_force_review_below', '0.6'), null);
  assert.match(validateFieldValue('confidence_force_review_below', '1.1'), /0\.0 and 1\.0/);
  assert.match(validateFieldValue('confidence_force_review_below', '-0.1'), /0\.0 and 1\.0/);
});

test('runSettingsValidation: only checks keys present in the input map', () => {
  const { errors, hasErrors } = runSettingsValidation({ max_completion_tokens: '99999' });
  assert.deepEqual(Object.keys(errors), ['max_completion_tokens']);
  assert.equal(hasErrors, true);
});

test('runSettingsValidation: all-valid input produces no errors', () => {
  const values = {
    max_completion_tokens: '1024',
    long_draft_warning_words: '1200',
    llm_chunk_size: '800',
    whisper_chunk_size: '800',
    confidence_force_review_below: '0.6',
    confidence_auto_send_above: '0.9',
    auto_stop_silence_ms: '1200',
    auto_stop_min_recording_ms: '500',
    no_audio_min_duration_sec: '0.3',
    no_audio_min_rms: '0.01',
    no_audio_min_peak: '0.05',
    draft_history_limit: '100',
  };
  const { errors, hasErrors } = runSettingsValidation(values);
  assert.deepEqual(errors, {});
  assert.equal(hasErrors, false);
});

test('runSettingsValidation: multiple simultaneous errors are all reported', () => {
  const { errors, hasErrors } = runSettingsValidation({ draft_history_limit: '5', llm_chunk_size: '1' });
  assert.equal(hasErrors, true);
  assert.match(errors.draft_history_limit, /10 and 500/);
  assert.match(errors.llm_chunk_size, /50 and 5000/);
});

// --- profile field collect/restore round-trip --------------------------------

test('SETTINGS_FIELD_KEYS and SETTINGS_FIELD_TYPES stay in sync (every key has a type, no extras)', () => {
  assert.deepEqual([...SETTINGS_FIELD_KEYS].sort(), Object.keys(SETTINGS_FIELD_TYPES).sort());
});

test('SETTINGS_FIELD_KEYS: includes draft_history_limit (the wiring-fix field) exactly once', () => {
  const occurrences = SETTINGS_FIELD_KEYS.filter((k) => k === 'draft_history_limit');
  assert.equal(occurrences.length, 1);
});

test('AI cleanup is a Settings-owned opt-in checkbox', () => {
  assert.equal(SETTINGS_FIELD_KEYS.filter((key) => key === 'llm_enabled').length, 1);
  assert.equal(SETTINGS_FIELD_TYPES.llm_enabled, 'checkbox');
  assert.equal(SETTINGS_ELEMENT_IDS.fields.llm_enabled, 'sdSetLlmEnabled');
  assert.equal(restoreFieldStatesFromSettings({}).llm_enabled.checked, false);
  assert.equal(collectPatchFromFieldStates({ llm_enabled: { checked: true, disabled: false } }).llm_enabled, true);
});

test('SETTINGS_FIELD_KEYS: does NOT include fields owned by Utilities/Studio (no duplication)', () => {
  const forbidden = ['hotkey', 'force_stop_key', 'manual_send_hotkey', 'review_tts_hotkey', 'selection_rewrite_hotkey', 'chat_open_key', 'voice_mute_key', 'input_device_index', 'audio_ducking', 'wake_word_model', 'wake_word_sensitivity', 'wake_word_cooldown_s', 'wake_word_max_recording_s', 'macros_enabled', 'model_keep_llm_loaded', 'model_keep_stt_loaded', 'model_keep_tts_loaded', 'review_tts_voice_hint', 'review_tts_speed'];
  for (const key of forbidden) {
    assert.equal(SETTINGS_FIELD_KEYS.includes(key), false, `${key} should not be Settings-owned`);
  }
});

test('SETTINGS_DEFAULT_ON_KEYS: exactly the 3 fields that default ON, matching main.js filtered to Settings-owned fields', () => {
  assert.deepEqual([...SETTINGS_DEFAULT_ON_KEYS].sort(), ['confidence_force_review_enabled', 'restore_clipboard_after_paste', 'voice_commands_enabled'].sort());
});

test('collectPatchFromFieldStates: coerces checkbox/number/text per SETTINGS_FIELD_TYPES', () => {
  const patch = collectPatchFromFieldStates({
    recording_mode: { value: 'ptt' },
    auto_stop_after_silence_enabled: { checked: true, disabled: false },
    auto_stop_silence_ms: { value: '900' },
    voice_commands_enabled: { checked: false, disabled: false },
  });
  assert.equal(patch.recording_mode, 'ptt');
  assert.equal(patch.auto_stop_after_silence_enabled, true);
  assert.equal(patch.auto_stop_silence_ms, 900);
  assert.equal(typeof patch.auto_stop_silence_ms, 'number');
  assert.equal(patch.voice_commands_enabled, false);
});

test('collectPatchFromFieldStates: a disabled checkbox always collects as false, even if checked=true', () => {
  const patch = collectPatchFromFieldStates({ auto_submit: { checked: true, disabled: true } });
  assert.equal(patch.auto_submit, false);
});

test('collectPatchFromFieldStates: fields absent from fieldStates are omitted from the patch', () => {
  const patch = collectPatchFromFieldStates({ recording_mode: { value: 'toggle' } });
  assert.deepEqual(Object.keys(patch), ['recording_mode']);
});

test('restoreFieldStatesFromSettings: default-on checkbox fields resolve to true when unset in the profile', () => {
  const states = restoreFieldStatesFromSettings({});
  assert.equal(states.voice_commands_enabled.checked, true);
  assert.equal(states.confidence_force_review_enabled.checked, true);
  assert.equal(states.restore_clipboard_after_paste.checked, true);
  // Non-default-on checkbox fields resolve to false when unset.
  assert.equal(states.auto_submit.checked, false);
  assert.equal(states.long_recording_stitch_pass_enabled.checked, false);
});

test('restoreFieldStatesFromSettings: an explicit stored value always wins over the default-on fallback', () => {
  const states = restoreFieldStatesFromSettings({ voice_commands_enabled: false });
  assert.equal(states.voice_commands_enabled.checked, false);
});

test('restoreFieldStatesFromSettings: non-checkbox fields fall back to empty string when unset', () => {
  const states = restoreFieldStatesFromSettings({});
  assert.equal(states.draft_history_limit.value, '');
  assert.equal(states.max_completion_tokens.value, '');
});

test('restoreFieldStatesFromSettings: draft_history_limit round-trips a real stored value (the wiring-fix field)', () => {
  const states = restoreFieldStatesFromSettings({ draft_history_limit: 250 });
  assert.equal(states.draft_history_limit.value, 250);
});

test('collect/restore ROUND TRIP: a full settings object survives restore -> (simulated DOM) -> collect unchanged', () => {
  const original = {
    llm_enabled: true,
    recording_mode: 'ptt',
    auto_stop_after_silence_enabled: true,
    auto_stop_silence_ms: 900,
    auto_stop_min_recording_ms: 400,
    voice_commands_enabled: false,
    no_audio_min_duration_sec: 0.4,
    no_audio_min_rms: 0.02,
    no_audio_min_peak: 0.08,
    send_mode: 'auto_send',
    confidence_force_review_enabled: false,
    confidence_force_review_below: 0.55,
    confidence_auto_send_above: 0.85,
    auto_submit: true,
    instant_typing: true,
    restore_clipboard_after_paste: false,
    draft_history_limit: 250,
    current_preset: 'Direct',
    max_completion_tokens: 2048,
    long_draft_warning_words: 900,
    llm_chunk_size: 700,
    whisper_chunk_size: 600,
    long_recording_stitch_pass_enabled: true,
    status_indicator_enabled: false,
    notification_overlay_enabled: false,
    preview_overlay_enabled: false,
    // D-0005 disclosed toggle. Included with a non-default value on purpose:
    // a user who turns delivery signals on must find them still on after a
    // profile round trip, or the control is decorative.
    use_delivery_signals: true,
  };

  // "Restore" -> simulated DOM element states (value/checked as strings, the
  // way real <input>/<select> elements store them).
  const restored = restoreFieldStatesFromSettings(original);
  const simulatedDom = {};
  for (const [key, type] of Object.entries(SETTINGS_FIELD_TYPES)) {
    simulatedDom[key] = type === 'checkbox'
      ? { checked: restored[key].checked, disabled: false }
      : { value: String(restored[key].value) };
  }

  // "Collect" back from the simulated DOM.
  const collected = collectPatchFromFieldStates(simulatedDom);
  assert.deepEqual(collected, original);
});

test('collect/restore ROUND TRIP: an empty profile restores documented defaults, and those defaults collect back consistently', () => {
  const restored = restoreFieldStatesFromSettings({});
  const simulatedDom = {};
  for (const [key, type] of Object.entries(SETTINGS_FIELD_TYPES)) {
    simulatedDom[key] = type === 'checkbox'
      ? { checked: restored[key].checked, disabled: false }
      : { value: String(restored[key].value ?? '') };
  }
  const collected = collectPatchFromFieldStates(simulatedDom);
  assert.equal(collected.voice_commands_enabled, true);
  assert.equal(collected.confidence_force_review_enabled, true);
  assert.equal(collected.restore_clipboard_after_paste, true);
  assert.equal(collected.auto_submit, false);
  // Empty numeric fields collect as NaN (Number('')===0 actually -- verify
  // the real coercion behavior explicitly rather than assume).
  assert.equal(collected.draft_history_limit, 0);
});

test('mergeProfilePatch: patch keys win over base, base keys not in patch are preserved', () => {
  const merged = mergeProfilePatch({ a: 1, b: 2 }, { b: 3, c: 4 });
  assert.deepEqual(merged, { a: 1, b: 3, c: 4 });
});

test('mergeProfilePatch: handles missing base/patch gracefully', () => {
  assert.deepEqual(mergeProfilePatch(undefined, { a: 1 }), { a: 1 });
  assert.deepEqual(mergeProfilePatch({ a: 1 }, undefined), { a: 1 });
  assert.deepEqual(mergeProfilePatch(undefined, undefined), {});
});

// --- legacy profile import upgrade ------------------------------------------

test('buildLegacyProfileImportPayload: passes through an already-versioned profile untouched', () => {
  const input = { kind: 'betterfingers_profile', schema_version: 1, name: 'Work', settings: { a: 1 } };
  assert.deepEqual(buildLegacyProfileImportPayload(input, 'fallback'), input);
});

test('buildLegacyProfileImportPayload: upgrades a bare settings object using the filename fallback', () => {
  const result = buildLegacyProfileImportPayload({ recording_mode: 'ptt' }, 'MyProfile');
  assert.deepEqual(result, { kind: 'betterfingers_profile', schema_version: 1, name: 'MyProfile', settings: { recording_mode: 'ptt' } });
});

test('buildLegacyProfileImportPayload: upgrades a { name, settings } shape, preferring its own name over the fallback', () => {
  const result = buildLegacyProfileImportPayload({ name: 'Exported', settings: { recording_mode: 'toggle' } }, 'fallback');
  assert.equal(result.name, 'Exported');
  assert.equal(result.schema_version, 1);
  assert.deepEqual(result.settings, { recording_mode: 'toggle' });
});

// --- search matching ----------------------------------------------------

test('rowMatchesQuery: empty query always matches', () => {
  assert.equal(rowMatchesQuery('anything at all', ''), true);
  assert.equal(rowMatchesQuery('anything at all', '   '), true);
});

test('rowMatchesQuery: case-insensitive substring match', () => {
  assert.equal(rowMatchesQuery('Draft History Limit', 'draft history'), true);
  assert.equal(rowMatchesQuery('Draft History Limit', 'HISTORY'), true);
  assert.equal(rowMatchesQuery('Draft History Limit', 'macros'), false);
});

// --- element ids -------------------------------------------------------

test('SETTINGS_ELEMENT_IDS.fields: every SETTINGS_FIELD_KEYS entry has an element id', () => {
  for (const key of SETTINGS_FIELD_KEYS) {
    assert.ok(SETTINGS_ELEMENT_IDS.fields[key], `${key} missing an element id`);
  }
});

test('SETTINGS_ELEMENT_IDS: BUG #1 fix -- rename/duplicate/export all have real ids (unlike main.js\'s unbound identifiers)', () => {
  assert.equal(SETTINGS_ELEMENT_IDS.renameButton, 'sdSetRenameProfileButton');
  assert.equal(SETTINGS_ELEMENT_IDS.duplicateButton, 'sdSetDuplicateProfileButton');
  assert.equal(SETTINGS_ELEMENT_IDS.exportButton, 'sdSetExportProfileButton');
});

test('collectSettingsElements: missing ids resolve to null, never throw (no real document)', () => {
  const fakeDoc = { getElementById: () => null };
  const els = collectSettingsElements(fakeDoc);
  assert.equal(els.profileSelect, null);
  assert.equal(els.fields.draft_history_limit, null);
  assert.equal(els.fieldErrors.max_completion_tokens, null);
});

test('collectSettingsElements: resolves elements the stub document has', () => {
  const found = { id: 'sdSetProfileSelect' };
  const fakeDoc = { getElementById: (id) => (id === 'sdSetProfileSelect' ? found : null) };
  const els = collectSettingsElements(fakeDoc);
  assert.equal(els.profileSelect, found);
});

// --- createSettingsWorkspaceFeature: lightweight DOM-stub smoke tests -------
// (Full DOM wiring is exercised manually via signal-desk-preview.html per
// the phase brief -- these are narrow stub-based checks that the factory
// never throws when given a sparse `elements`/`hooks` object, the same
// "safe no-op" contract every other workspace module documents.)

test('createSettingsWorkspaceFeature: init()/goToSection() work with an empty elements object', () => {
  const feature = createSettingsWorkspaceFeature({ elements: {}, hooks: {} });
  const state = feature.init();
  assert.deepEqual(state, { active: 'profile' });
  assert.deepEqual(feature.goToSection('privacy'), { active: 'privacy' });
  assert.deepEqual(feature.getSectionState(), { active: 'privacy' });
});

test('createSettingsWorkspaceFeature: renderSettings()/collectSettings() round-trip against stub field elements', () => {
  function makeInput(type) {
    return { type, value: '', checked: false, disabled: false, classList: { add() {}, remove() {} }, addEventListener() {} };
  }
  const fields = {};
  for (const [key, type] of Object.entries(SETTINGS_FIELD_TYPES)) {
    fields[key] = makeInput(type === 'checkbox' ? 'checkbox' : type === 'number' ? 'number' : 'text');
  }
  const feature = createSettingsWorkspaceFeature({ elements: { fields }, hooks: {} });
  feature.init();
  feature.renderSettings({ draft_history_limit: 150, max_completion_tokens: 2048, voice_commands_enabled: false });
  assert.equal(fields.draft_history_limit.value, 150);
  assert.equal(fields.max_completion_tokens.value, 2048);
  assert.equal(fields.voice_commands_enabled.checked, false);
  // restore_clipboard_after_paste wasn't in the input -> default-on fallback applies.
  assert.equal(fields.restore_clipboard_after_paste.checked, true);

  const collected = feature.collectSettings();
  assert.equal(collected.draft_history_limit, 150);
  assert.equal(collected.max_completion_tokens, 2048);
  assert.equal(collected.voice_commands_enabled, false);
  assert.equal(collected.restore_clipboard_after_paste, true);
});

test('createSettingsWorkspaceFeature: runValidation() sets/clears field errors against stub elements', () => {
  function makeErrorTextEl() {
    return { textContent: '' };
  }
  function makeNumberInput(value) {
    return { type: 'number', value, classList: { add() {}, remove() {} }, addEventListener() {} };
  }
  const fields = { max_completion_tokens: makeNumberInput('99999') };
  const fieldErrors = { max_completion_tokens: makeErrorTextEl() };
  const saveButton = { disabled: false, title: '' };
  const feature = createSettingsWorkspaceFeature({ elements: { fields, fieldErrors, saveButton }, hooks: {} });
  feature.init();

  const errors = feature.runValidation();
  assert.match(errors.max_completion_tokens, /512 and 4096/);
  assert.match(fieldErrors.max_completion_tokens.textContent, /512 and 4096/);
  assert.equal(saveButton.disabled, true);
  assert.deepEqual(feature.getValidationErrors(), { max_completion_tokens: errors.max_completion_tokens });

  fields.max_completion_tokens.value = '2048';
  const errors2 = feature.runValidation();
  assert.deepEqual(errors2, {});
  assert.equal(fieldErrors.max_completion_tokens.textContent, '');
  assert.equal(saveButton.disabled, false);
  assert.deepEqual(feature.getValidationErrors(), {});
});

// --- Auto Submit safety: acknowledgement gate + warning banner (OR-01) ------
// The operator's highest-severity finding: Auto Submit pastes/types then
// presses Enter into whatever window has OS focus, with no review step.
// These tests pin the SAFETY PROPERTIES, not the copy: the checkbox cannot
// reach "checked" without going through an explicit confirmFn(), the warning
// banner tracks the checked state, and turning it off and back on demands the
// acknowledgement again rather than remembering an earlier "yes".

function autoSubmitInputStub(initialChecked = false) {
  const listeners = {};
  return {
    checked: initialChecked,
    disabled: false,
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    fire: (evt) => listeners[evt]?.(),
  };
}

function autoSubmitHarness(hooks = {}) {
  const input = autoSubmitInputStub();
  const warning = { hidden: true };
  const feature = createSettingsWorkspaceFeature({
    elements: { fields: { auto_submit: input }, fieldErrors: {}, autoSubmitWarning: warning },
    hooks,
  });
  feature.init();
  return { feature, input, warning };
}

test('auto submit warning starts hidden when the control is off', () => {
  const { warning } = autoSubmitHarness();
  assert.equal(warning.hidden, true);
});

test('checking auto submit asks for an explicit confirmation naming the real risk', () => {
  const calls = [];
  const { input } = autoSubmitHarness({ confirmFn: (msg) => { calls.push(msg); return true; } });
  input.checked = true;
  input.fire('change');
  assert.equal(calls.length, 1, 'checking the box must go through confirmFn');
  // Pin the safety property (the confirmation names the real mechanism), not the exact wording.
  assert.match(calls[0], /Enter/);
  assert.match(calls[0], /focus/i);
});

test('declining the confirmation reverts the checkbox and keeps the warning hidden', () => {
  const { input, warning } = autoSubmitHarness({ confirmFn: () => false });
  input.checked = true;
  input.fire('change');
  assert.equal(input.checked, false, 'declining must not leave auto submit enabled');
  assert.equal(warning.hidden, true);
});

test('confirming the acknowledgement leaves auto submit checked and reveals the warning', () => {
  const { input, warning } = autoSubmitHarness({ confirmFn: () => true });
  input.checked = true;
  input.fire('change');
  assert.equal(input.checked, true);
  assert.equal(warning.hidden, false);
});

test('turning auto submit off and back on demands the acknowledgement again', () => {
  let calls = 0;
  const { input, warning } = autoSubmitHarness({ confirmFn: () => { calls += 1; return true; } });

  input.checked = true;
  input.fire('change');
  assert.equal(calls, 1);
  assert.equal(input.checked, true);

  input.checked = false;
  input.fire('change');
  assert.equal(warning.hidden, true, 'turning it off hides the warning immediately');

  input.checked = true;
  input.fire('change');
  assert.equal(calls, 2, 're-enabling must re-run the acknowledgement, not remember the earlier "yes"');
  assert.equal(input.checked, true);
});

test('declining the re-enable confirmation reverts it again, even though it was on before', () => {
  let calls = 0;
  const confirmFn = () => { calls += 1; return calls === 1; }; // yes the first time, no the second
  const { input, warning } = autoSubmitHarness({ confirmFn });

  input.checked = true;
  input.fire('change');
  assert.equal(input.checked, true);

  input.checked = false;
  input.fire('change');

  input.checked = true;
  input.fire('change');
  assert.equal(calls, 2);
  assert.equal(input.checked, false, 'a decline must win even on a re-enable of a previously-accepted toggle');
  assert.equal(warning.hidden, true);
});

test('renderSettings() reflects a persisted auto_submit=true without re-prompting', () => {
  const calls = [];
  const { feature, input, warning } = autoSubmitHarness({ confirmFn: (msg) => { calls.push(msg); return true; } });
  feature.renderSettings({ auto_submit: true });
  assert.equal(input.checked, true, 'loading a profile that already has it on must restore the checked state');
  assert.equal(warning.hidden, false, 'the warning must render whenever the control does, on load as well as on toggle');
  assert.equal(calls.length, 0, 'restoring saved state is not "turning it on" -- it must not re-run the confirmation');
});

// --- completeness gate: every required inventory item has a placement -------

// Exactly the inventory areas the work packet calls out by name for
// Settings: sticky Save/Discard bar + profile management (including the
// BUG #1 buttons), Recording, Review & Drafts (including draft_history_limit),
// AI Cleanup numeric knobs, Notifications, Appearance (incl. Floating
// Overlay), and Privacy (incl. the wipe flow).
const REQUIRED_INVENTORY_KEYS = [
  // Profile (§7.0 save bar + §7.1 profile mgmt)
  'profile.select',
  'profile.newName',
  'profile.activate',
  'profile.create',
  'profile.rename',
  'profile.duplicate',
  'profile.export',
  'profile.import',
  'profile.delete',
  'profile.saveBar',
  'profile.validation',
  // Recording (§7.2)
  'recording.mode',
  'recording.autoStopSilence',
  'recording.voiceCommands',
  'recording.noAudioGate',
  // Review & Drafts (§7.4)
  'review.sendMode',
  'review.confidenceGate',
  'review.autoSubmit',
  'review.instantTyping',
  'review.restoreClipboard',
  'review.draftHistoryLimit',
  // AI Cleanup (§7.5 numeric knobs)
  'aicleanup.currentPreset',
  'aicleanup.maxCompletionTokens',
  'aicleanup.longDraftWarningWords',
  'aicleanup.llmChunkSize',
  'aicleanup.whisperChunkSize',
  'aicleanup.stitchPass',
  // Notifications & Status (§7.10)
  'notifications.statusIndicator',
  'notifications.notificationOverlay',
  'notifications.previewOverlay',
  // Appearance (§7.11)
  'appearance.themeGroup',
  'appearance.overlayGroup',
  // Privacy (§7.14)
  'privacy.networkList',
  'privacy.dataList',
  'privacy.wakeListenerStatus',
  'privacy.wipe',
];

test('COMPLETENESS: every required inventory key has an entry in INVENTORY_PLACEMENT_MAP', () => {
  const missing = REQUIRED_INVENTORY_KEYS.filter((key) => !INVENTORY_PLACEMENT_MAP[key]);
  assert.deepEqual(missing, [], `missing placement map entries: ${missing.join(', ')}`);
});

test('COMPLETENESS: every placement map entry names a valid Settings section', () => {
  for (const [key, entry] of Object.entries(INVENTORY_PLACEMENT_MAP)) {
    assert.ok(isValidSettingsSection(entry.section), `${key} names an invalid section: ${entry.section}`);
  }
});

test('COMPLETENESS: an unwired Settings control must explain itself', () => {
  // This used to assert that NOTHING in Settings was unwired. Wave 5 added a
  // control that is deliberately built-but-not-live -- the audience toggle,
  // which D-0005 reserves for a director ruling -- so the rule becomes the one
  // the other workspaces already use: unwired is allowed, undeclared is not.
  for (const [key, entry] of Object.entries(INVENTORY_PLACEMENT_MAP)) {
    if (entry.wired === true) continue;
    assert.equal(entry.wired, false, `${key}.wired must be a boolean`);
    assert.ok(
      typeof entry.note === 'string' && entry.note.length > 0,
      `${key} is unwired with no note -- an undeclared gap is how features get lost`,
    );
  }
});

// --- D-0005 disclosed toggles ------------------------------------------------
//
// Both keys changed model behaviour with no way for a user to see them. The
// tests below pin the two things that makes acceptable: the disclosure is
// complete, and the ungated one cannot be turned on by any path Settings owns.

test('both disclosed toggles exist, with the release wording', () => {
  assert.equal(DISCLOSED_TOGGLES.length, 2);
  assert.deepEqual(
    DISCLOSED_TOGGLES.map((t) => t.label),
    ['Use speech delivery signals', 'Use selected contact/audience context'],
  );
});

test('every toggle discloses all six required pieces', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    const rows = disclosureRowsFor(toggle);
    assert.deepEqual(
      rows.map((r) => r.field),
      ['dataUsed', 'mayChange', 'mustPreserve', 'default', 'inspect', 'gate'],
      `${toggle.key} must disclose data used, what it may change, what it must preserve, its default, an inspect path, and its gate status`,
    );
    for (const row of rows) {
      assert.ok(row.text && row.text.length > 0, `${toggle.key}.${row.field} is empty`);
    }
  }
});

test('every toggle ships OFF', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    assert.equal(toggle.defaultOn, false, `${toggle.key} must default off`);
    // And the rendered "Default" row must say so, not just the descriptor.
    const defaultRow = disclosureRowsFor(toggle).find((r) => r.field === 'default');
    assert.equal(defaultRow.text, 'Off');
  }
});

test('a profile that has never stored the key reports the default, not a guess', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    assert.equal(toggleStateFrom({}, toggle).checked, false);
    assert.equal(toggleStateFrom(undefined, toggle).checked, false);
  }
});

test('every toggle names a preservation gate status and its decision', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    assert.ok(toggle.gate.status, `${toggle.key} has no gate status`);
    assert.equal(toggle.gate.decision, 'D-0005');
  }
});

test('every toggle promises meaning is preserved, in its own words', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    assert.match(toggle.mustPreserve, /meaning/i,
      `${toggle.key} must state that meaning survives -- that is the promise the whole product rests on`);
  }
});

test('the audience toggle cannot be enabled from Settings', () => {
  const audience = disclosedToggleFor('use_audience_context');
  assert.equal(audience.userEnablable, false);
  assert.equal(toggleIsInteractive(audience), false);
  assert.equal(toggleStateFrom({}, audience).disabled, true);
  assert.match(audience.gate.text, /cannot be switched on yet/);
});

test('use_audience_context is not collectable into a profile patch at all', () => {
  // The strongest guarantee available: the key is absent from the field maps,
  // so no save path -- including one written later by someone who has not read
  // D-0005 -- can carry it.
  assert.equal(SETTINGS_FIELD_KEYS.includes('use_audience_context'), false);
  assert.equal('use_audience_context' in SETTINGS_FIELD_TYPES, false);

  const patch = collectPatchFromFieldStates({
    use_audience_context: { checked: true, disabled: false },
    use_delivery_signals: { checked: true, disabled: false },
  });
  assert.equal('use_audience_context' in patch, false, 'the audience key must never reach a patch');
  assert.equal(patch.use_delivery_signals, true);
});

test('a profile that already has audience context on still reports it honestly', () => {
  // Settings does not write the key, but it must not lie about it either: a
  // user who set it by hand is shown the truth, still with no way to flip it
  // here.
  const audience = disclosedToggleFor('use_audience_context');
  const state = toggleStateFrom({ use_audience_context: true }, audience);
  assert.equal(state.checked, true);
  assert.equal(state.disabled, true);
});

test('the delivery-signals toggle is a real control that defaults off', () => {
  const delivery = disclosedToggleFor('use_delivery_signals');
  assert.equal(delivery.userEnablable, true);
  assert.equal(toggleIsInteractive(delivery), true);
  assert.equal(toggleStateFrom({}, delivery).disabled, false);

  assert.equal(SETTINGS_FIELD_KEYS.includes('use_delivery_signals'), true);
  assert.equal(SETTINGS_FIELD_TYPES.use_delivery_signals, 'checkbox');
  // Not in the default-ON set: it must survive a restore as off.
  assert.equal(SETTINGS_DEFAULT_ON_KEYS.has('use_delivery_signals'), false);
  assert.equal(restoreFieldStatesFromSettings({}).use_delivery_signals.checked, false);
});

test('delivery signals survive a collect/restore round trip once turned on', () => {
  const patch = collectPatchFromFieldStates({ use_delivery_signals: { checked: true, disabled: false } });
  assert.equal(patch.use_delivery_signals, true);
  assert.equal(restoreFieldStatesFromSettings(patch).use_delivery_signals.checked, true);
});

test('every disclosed toggle has a full set of element ids', () => {
  for (const toggle of DISCLOSED_TOGGLES) {
    const ids = SETTINGS_ELEMENT_IDS.disclosedToggles[toggle.key];
    assert.ok(ids, `${toggle.key} has no element ids`);
    assert.deepEqual(
      Object.keys(ids).sort(),
      ['dataUsed', 'default', 'gate', 'input', 'inspect', 'mayChange', 'mustPreserve'],
      `${toggle.key} is missing an element for one of its disclosure rows`,
    );
  }
});

test('collectSettingsElements resolves the disclosure groups', () => {
  const seen = [];
  const doc = { getElementById: (id) => { seen.push(id); return { id }; } };
  const els = collectSettingsElements(doc);

  for (const toggle of DISCLOSED_TOGGLES) {
    const group = els.disclosedToggles[toggle.key];
    assert.ok(group, `${toggle.key} group missing`);
    assert.equal(group.input.id, SETTINGS_ELEMENT_IDS.disclosedToggles[toggle.key].input);
    assert.equal(group.mustPreserve.id, SETTINGS_ELEMENT_IDS.disclosedToggles[toggle.key].mustPreserve);
  }
});

// --- disclosed toggles: DOM behaviour ---------------------------------------

function toggleGroupStub() {
  const listeners = {};
  const mk = () => ({ textContent: '' });
  const input = {
    checked: false,
    disabled: false,
    title: '',
    attrs: {},
    setAttribute(name, value) { this.attrs[name] = value; },
    addEventListener: (evt, fn) => { listeners[evt] = fn; },
    fire: (evt) => listeners[evt]?.(),
  };
  return {
    input,
    dataUsed: mk(),
    mayChange: mk(),
    mustPreserve: mk(),
    default: mk(),
    inspect: { addEventListener: (evt, fn) => { listeners[`inspect:${evt}`] = fn; }, click: () => listeners['inspect:click']?.({ preventDefault() {} }) },
    gate: mk(),
    fireInputChange: () => listeners.change?.(),
  };
}

function settingsHarness(hooks = {}) {
  const groups = {
    use_delivery_signals: toggleGroupStub(),
    use_audience_context: toggleGroupStub(),
  };
  const feature = createSettingsWorkspaceFeature({
    elements: { disclosedToggles: groups, fields: {}, fieldErrors: {} },
    hooks,
  });
  return { feature, groups };
}

test('rendering writes every disclosure row into its element', () => {
  const { feature, groups } = settingsHarness();
  feature.renderSettings({});

  for (const toggle of DISCLOSED_TOGGLES) {
    const group = groups[toggle.key];
    assert.equal(group.dataUsed.textContent, toggle.dataUsed);
    assert.equal(group.mayChange.textContent, toggle.mayChange);
    assert.equal(group.mustPreserve.textContent, toggle.mustPreserve);
    assert.equal(group.default.textContent, 'Off');
    assert.equal(group.gate.textContent, toggle.gate.text);
  }
});

test('rendering leaves both controls off and the audience one disabled', () => {
  const { feature, groups } = settingsHarness();
  feature.renderSettings({});

  assert.equal(groups.use_delivery_signals.input.checked, false);
  assert.equal(groups.use_delivery_signals.input.disabled, false);

  assert.equal(groups.use_audience_context.input.checked, false);
  assert.equal(groups.use_audience_context.input.disabled, true);
  assert.equal(groups.use_audience_context.input.attrs['aria-disabled'], 'true');
  assert.match(groups.use_audience_context.input.title, /cannot be switched on yet/);
});

test('forcing the audience checkbox on flips it straight back and says why', () => {
  const { feature, groups } = settingsHarness();
  feature.init();
  feature.renderSettings({});
  // Stand in for anything that sets .checked directly -- a stray script, an
  // autofill, a future bug. D-0005 is about the stored value, not the widget.
  groups.use_audience_context.input.checked = true;
  groups.use_audience_context.fireInputChange();

  assert.equal(groups.use_audience_context.input.checked, false);
  // And it can never reach a patch regardless.
  assert.equal('use_audience_context' in feature.collectSettings(), false);
});

test('the delivery-signals control is not force-reset', () => {
  const { feature, groups } = settingsHarness();
  feature.init();
  feature.renderSettings({});
  groups.use_delivery_signals.input.checked = true;
  groups.use_delivery_signals.fireInputChange();
  assert.equal(groups.use_delivery_signals.input.checked, true, 'this one the user is allowed to turn on');
});

test('the inspect link routes to the data rather than explaining it away', () => {
  const inspected = [];
  const { feature, groups } = settingsHarness({
    onInspectToggleData: (key, target) => inspected.push([key, target]),
  });
  feature.init();

  groups.use_audience_context.inspect.click();
  assert.deepEqual(inspected, [['use_audience_context', 'contacts']]);

  groups.use_delivery_signals.inspect.click();
  assert.deepEqual(inspected[1], ['use_delivery_signals', 'speech_signals']);
});

test('with no inspect hook the link still goes somewhere real', () => {
  const { feature, groups } = settingsHarness();
  feature.init();
  groups.use_delivery_signals.inspect.click();
  assert.equal(feature.getSectionState().active, 'privacy');
});

// --- persistent BetterFingers Update card ---------------------------------

test('update view models cover every updater state with honest actions', () => {
  const cases = [
    ['unsupported', null, '', true],
    ['idle', 'check', 'Check again', false],
    ['checking', 'check', 'Checking…', false],
    ['up_to_date', 'check', 'Check again', false],
    ['available', 'download', 'Download update', false],
    ['downloading', null, '', false],
    ['ready', 'install', 'Restart and install', false],
    ['installing', 'install', 'Installing…', false],
    ['error', 'check', 'Try again', true],
  ];
  for (const [status, action, label, manual] of cases) {
    const view = buildUpdateViewModel({
      status,
      currentVersion: '1.1.0-alpha.3',
      availableVersion: '1.1.0-alpha.4',
      channel: 'alpha',
      percent: 42,
    });
    assert.equal(view.primaryAction, action, `${status} action`);
    assert.equal(view.primaryLabel, label, `${status} label`);
    assert.equal(view.showManual, manual, `${status} manual link`);
    assert.equal(view.channelLabel, 'Public alpha');
  }
});

test('update view model separates download from restart and exposes real progress', () => {
  const available = buildUpdateViewModel({
    status: 'available', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4',
    channel: 'alpha', releaseDate: '2026-08-19T00:00:00Z', releaseNotes: 'Safer update',
    bytesTotal: 12 * 1024 * 1024,
  });
  assert.equal(available.primaryAction, 'download');
  assert.equal(available.showLater, true);
  assert.match(available.releaseMeta, /2026-08-19/);
  assert.match(available.releaseMeta, /12 MB/);

  const downloading = buildUpdateViewModel({
    status: 'downloading', currentVersion: '1.1.0-alpha.3',
    availableVersion: '1.1.0-alpha.4', channel: 'alpha', percent: 48.6,
  });
  assert.equal(downloading.showProgress, true);
  assert.match(downloading.detail, /49%/);
  assert.equal(downloading.primaryAction, null, 'there is no fake cancel action');

  const ready = buildUpdateViewModel({
    status: 'ready', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4', channel: 'alpha',
  });
  assert.equal(ready.primaryAction, 'install');
  assert.match(ready.detail, /stop its active services/);
});

test('active dictation disables restart and Later remains reversible', () => {
  const blocked = buildUpdateViewModel({
    status: 'ready', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4',
    channel: 'alpha', errorCode: 'ACTIVE_DICTATION',
  });
  assert.equal(blocked.primaryDisabled, true);
  assert.match(blocked.detail, /recording or processing/);

  const deferred = buildUpdateViewModel({
    status: 'available', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4', channel: 'alpha',
  }, { deferred: true });
  assert.equal(deferred.showResume, true);
  assert.equal(deferred.primaryAction, null);
  assert.match(deferred.detail, /Nothing was changed/);
});

test('unavailable runtime verification is honest, fail-closed, and retryable', () => {
  const unavailable = buildUpdateViewModel({
    status: 'ready', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4',
    channel: 'alpha', errorCode: 'RUNTIME_STATUS_UNAVAILABLE',
  });
  assert.match(unavailable.headline, /verify a safe restart/);
  assert.match(unavailable.detail, /Nothing was changed/);
  assert.match(unavailable.detail, /still running/);
  assert.equal(unavailable.primaryAction, 'install');
  assert.equal(unavailable.primaryLabel, 'Try restart and install again');
  assert.equal(unavailable.primaryDisabled, false);
});

function updateElement() {
  const listeners = {};
  return {
    textContent: '', hidden: false, disabled: false, value: 0, max: 0,
    dataset: {}, attrs: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute(name, value) { this.attrs[name] = value; },
    addEventListener(name, listener) { listeners[name] = listener; },
    fire(name) { return listeners[name]?.({ preventDefault() {} }); },
  };
}

function updateCardHarness(initialState) {
  const elements = { fields: {}, fieldErrors: {}, disclosedToggles: {} };
  for (const key of [
    'updateCard', 'updateCurrentVersion', 'updateChannel', 'updateStatus', 'updateDetail',
    'updateRelease', 'updateReleaseMeta', 'updateReleaseNotes', 'updateProgress',
    'updateProgressText', 'updatePrimaryButton', 'updateLaterButton', 'updateResumeButton',
    'updateManualLink',
  ]) elements[key] = updateElement();
  const calls = [];
  let pushed = null;
  let unsubscribed = false;
  const updatesApi = {
    getState: async () => initialState,
    check: async () => { calls.push('check'); return { ...initialState, status: 'checking' }; },
    download: async () => { calls.push('download'); return { ...initialState, status: 'downloading' }; },
    install: async () => { calls.push('install'); return { ...initialState, status: 'installing' }; },
    onState(callback) { pushed = callback; return () => { unsubscribed = true; }; },
  };
  const feature = createSettingsWorkspaceFeature({ elements, hooks: { updatesApi } });
  feature.init();
  return { calls, elements, feature, push: (state) => pushed?.(state), wasUnsubscribed: () => unsubscribed };
}

test('update card renders text-only state, semantic progress, actions, and listener cleanup', async () => {
  const initial = {
    status: 'available', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4',
    channel: 'alpha', releaseNotes: '<b>already sanitized by main</b>', bytesTotal: 1024,
  };
  const h = updateCardHarness(initial);
  await h.feature.refreshUpdateState();
  assert.equal(h.elements.updateCurrentVersion.textContent, 'Version 1.1.0-alpha.3');
  assert.equal(h.elements.updateChannel.textContent, 'Public alpha');
  assert.equal(h.elements.updateReleaseNotes.textContent, '<b>already sanitized by main</b>', 'textContent never interprets notes as markup');
  assert.equal(h.elements.updatePrimaryButton.textContent, 'Download update');
  await h.feature.runUpdateAction('download');
  assert.deepEqual(h.calls, ['download']);
  assert.equal(h.elements.updateProgress.hidden, false);

  h.push({ ...initial, status: 'downloading', percent: 63 });
  assert.equal(h.elements.updateProgress.value, 63);
  assert.equal(h.elements.updateProgress.max, 100);
  assert.equal(h.elements.updateProgress.attrs['aria-valuetext'], '63% downloaded');
  h.feature.destroy();
  assert.equal(h.wasUnsubscribed(), true);
  h.push({ ...initial, status: 'ready' });
  assert.equal(h.elements.updateStatus.textContent, 'Downloading BetterFingers 1.1.0-alpha.4…');
});

test('Later hides update actions without invoking main and Show options restores them', async () => {
  const h = updateCardHarness({
    status: 'ready', currentVersion: '1.1.0-alpha.3', availableVersion: '1.1.0-alpha.4', channel: 'alpha',
  });
  await h.feature.refreshUpdateState();
  h.elements.updateLaterButton.fire('click');
  assert.equal(h.elements.updateResumeButton.hidden, false);
  assert.equal(h.elements.updatePrimaryButton.hidden, true);
  assert.deepEqual(h.calls, []);
  h.elements.updateResumeButton.fire('click');
  assert.equal(h.elements.updatePrimaryButton.hidden, false);
  assert.equal(h.elements.updatePrimaryButton.textContent, 'Restart and install');
});

test('malformed update payloads normalize to unsupported finite state', () => {
  const state = normalizeUpdateState({ status: 'made-up', percent: Infinity, bytesTotal: -5 });
  assert.equal(state.status, 'unsupported');
  assert.equal(state.percent, 0);
  assert.equal(state.bytesTotal, 0);
});
