// Settings workspace -- profile management + the sticky Save/Discard bar,
// driven through the REAL DOM wiring against the production element ids.
//
// CURRENT_UI_INVENTORY.md section 7.0/7.1 (parity rows UI-07-003, -004, -005,
// -009, -010, -015, -016, -018). settingsWorkspace.test.mjs already covers the
// pure helpers; what was never executed by a test is the wiring itself --
// which id becomes which control, which listener a button really gets, and
// which backend route a click actually reaches. That is the leg the Wave 11
// ledger reports as missing, and asserting it needs a document.
//
// Two rules this file follows deliberately:
//   * the production ids are written out as LITERAL strings and pinned against
//     SETTINGS_ELEMENT_IDS. A test that derived the ids from the module could
//     not notice the module renaming a control, which is the one thing an
//     id-level test exists to catch.
//   * the backend is stubbed at window.betterFingers.backendRequest -- the
//     single preload bridge api/backend.js funnels every route through -- so
//     the real URL building, the real error unwrapping and the real (method,
//     path, body) triple are exercised, not mocked away.
//
// Run with: node --test app/tests/settingsProfileOps.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  SETTINGS_ELEMENT_IDS,
  collectSettingsElements,
  createSettingsWorkspaceFeature,
} from '../src/renderer/features/settingsWorkspace.js';
import { makeDocument, makeBackendBridge, installDomGlobals } from './helpers/rendererDom.mjs';

// --- the production ids under test ------------------------------------------
//
// Written out rather than read from the module on purpose (see the header).

const CHROME_IDS = {
  saveBar: 'sdSetSaveBar',
  discardButton: 'sdSetDiscardButton',
  saveButton: 'sdSetSaveButton',
  profileMessage: 'sdSetProfileMessage',
  searchInput: 'sdSetSearchInput',
  emptyState: 'sdSetEmptyState',
  searchHeader: 'sdSetSearchHeader',
};

const PROFILE_IDS = {
  profileSelect: 'sdSetProfileSelect',
  newProfileName: 'sdSetNewProfileName',
  activateButton: 'sdSetActivateProfileButton',
  createButton: 'sdSetCreateProfileButton',
  renameButton: 'sdSetRenameProfileButton',
  duplicateButton: 'sdSetDuplicateProfileButton',
  exportButton: 'sdSetExportProfileButton',
  importFile: 'sdSetImportProfileFile',
  deleteButton: 'sdSetDeleteProfileButton',
  pttAvailabilityNote: 'sdSetPttAvailabilityNote',
};

const FIELD_IDS = {
  recording_mode: 'sdSetRecordingMode',
  draft_history_limit: 'sdSetDraftHistoryLimit',
  max_completion_tokens: 'sdSetMaxCompletionTokens',
  // The Long Recording Stitch Pass toggle (inventory §15 orphan UI-15-023): a
  // quiet cleanup-quality switch that is easy to lose as "just another
  // checkbox", so it is driven explicitly rather than in bulk.
  long_recording_stitch_pass_enabled: 'sdSetStitchPass',
};

const FIELD_ERROR_IDS = {
  draft_history_limit: 'sdSetDraftHistoryLimitError',
  max_completion_tokens: 'sdSetMaxCompletionTokensError',
};

test('the ids this file drives are the ids the Settings module ships', () => {
  for (const [key, id] of Object.entries({ ...CHROME_IDS, ...PROFILE_IDS })) {
    assert.equal(SETTINGS_ELEMENT_IDS[key], id, `${key} is not ${id} any more`);
  }
  for (const [key, id] of Object.entries(FIELD_IDS)) {
    assert.equal(SETTINGS_ELEMENT_IDS.fields[key], id, `field ${key} is not ${id} any more`);
  }
  for (const [key, id] of Object.entries(FIELD_ERROR_IDS)) {
    assert.equal(SETTINGS_ELEMENT_IDS.fieldErrors[key], id, `field error ${key} is not ${id} any more`);
  }
});

// --- harness -----------------------------------------------------------------

// Every numeric field this file registers carries a rule, and an EMPTY numeric
// field is genuinely invalid -- so a test that renders `{}` starts with the
// save button correctly disabled. Tests that are not about validation render
// this stored profile instead, which is valid.
const STORED_SETTINGS = { recording_mode: 'toggle', draft_history_limit: 100, max_completion_tokens: 2048 };

const PROFILES_PAYLOAD = {
  profiles: ['Default', 'Work'],
  active_profile: 'Work',
  settings: STORED_SETTINGS,
};

function defaultRoutes(extra = {}) {
  return {
    'GET /settings/profiles': PROFILES_PAYLOAD,
    'GET /settings/profiles/Work': { profile: 'Work', settings: { recording_mode: 'ptt', draft_history_limit: 100, max_completion_tokens: 2048 } },
    'GET /personas': { Direct: {}, Warm: {} },
    'GET /privacy': { network_touchpoints: [], data_locations: [], stores: [] },
    ...extra,
  };
}

/**
 * A Settings workspace wired to a document that carries the real ids.
 *
 * `collectSettingsElements(doc)` is the same call signalDeskApp.js makes, so
 * the element map under test is built by production code, not by the test.
 */
function mount({ routes = defaultRoutes(), hotkeyCapabilities, confirmFn } = {}) {
  const ids = [
    ...Object.values(CHROME_IDS),
    ...Object.values(PROFILE_IDS),
    ...Object.values(FIELD_IDS),
    ...Object.values(FIELD_ERROR_IDS),
  ];
  const doc = makeDocument(ids, {
    sdSetProfileSelect: { tagName: 'select' },
    sdSetNewProfileName: { tagName: 'input', type: 'text' },
    sdSetImportProfileFile: { tagName: 'input', type: 'file' },
    sdSetRecordingMode: { tagName: 'select', value: 'toggle' },
    sdSetDraftHistoryLimit: { tagName: 'input', type: 'number', value: '100' },
    sdSetMaxCompletionTokens: { tagName: 'input', type: 'number', value: '2048' },
    sdSetStitchPass: { tagName: 'input', type: 'checkbox' },
  });
  const bridge = makeBackendBridge(routes);
  const betterFingers = {
    backendRequest: bridge.request,
    getHotkeyCapabilities: hotkeyCapabilities ? async () => hotkeyCapabilities : undefined,
  };
  const restore = installDomGlobals({ document: doc, betterFingers });
  const feature = createSettingsWorkspaceFeature({
    elements: collectSettingsElements(doc),
    hooks: confirmFn ? { confirmFn } : {},
  });
  return { doc, bridge, feature, restore, el: (id) => doc.getElementById(id) };
}

// --- UI-07-003: the sticky save bar ------------------------------------------

test('#sdSetSaveBar is hidden after a profile render and appears the moment a field is touched', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings({ recording_mode: 'toggle' });

  const saveBar = ctx.el('sdSetSaveBar');
  assert.equal(saveBar.classList.contains('hidden'), true, 'a freshly rendered profile has nothing to save');
  assert.equal(saveBar.classList.contains('visible'), false);

  // The real listener, bound by init() -> bindFieldDirtyTracking().
  const recordingMode = ctx.el('sdSetRecordingMode');
  assert.ok(recordingMode.listenerCount('change') > 0, 'the recording-mode field was never bound');
  recordingMode.value = 'ptt';
  recordingMode.emit('change');

  assert.equal(saveBar.classList.contains('visible'), true, 'touching a control must raise the save bar');
  assert.equal(saveBar.classList.contains('hidden'), false);
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Unsaved profile changes.');
  assert.equal(ctx.feature.isDirty(), true);
});

test('#sdSetSaveButton is disabled while a field is invalid and re-enabled when it is fixed', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings(STORED_SETTINGS);

  const tokens = ctx.el('sdSetMaxCompletionTokens');
  tokens.value = '99999';
  tokens.emit('input');

  const saveButton = ctx.el('sdSetSaveButton');
  assert.equal(saveButton.disabled, true);
  assert.match(saveButton.title, /fix validation errors/);
  assert.match(ctx.el('sdSetMaxCompletionTokensError').textContent, /512 and 4096/);

  tokens.value = '2048';
  tokens.emit('input');
  assert.equal(saveButton.disabled, false);
  assert.equal(ctx.el('sdSetMaxCompletionTokensError').textContent, '');
});

// --- UI-07-005: Save -> POST /settings/profiles/:name -------------------------

test('#sdSetSaveButton POSTs the collected profile to the active profile route', async (t) => {
  const saved = [];
  const ctx = mount({
    routes: defaultRoutes({
      'POST /settings/profiles/Work': ({ body }) => {
        saved.push(body);
        return { profile: 'Work', settings: body.settings };
      },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings(STORED_SETTINGS);
  ctx.el('sdSetProfileSelect').value = 'Work';
  ctx.el('sdSetRecordingMode').value = 'ptt';

  await ctx.feature.handleSave();

  assert.deepEqual(ctx.bridge.signatures(), ['POST /settings/profiles/Work']);
  assert.equal(saved.length, 1);
  assert.equal(saved[0].settings.recording_mode, 'ptt', 'the DOM value must be what gets saved');
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Saved Work.');
  assert.equal(ctx.el('sdSetSaveBar').classList.contains('hidden'), true, 'a successful save clears the bar');
});

test('#sdSetSaveButton refuses to save while a validation error stands, and says so', async (t) => {
  const ctx = mount({ routes: defaultRoutes({ 'POST /settings/profiles/Work': { profile: 'Work', settings: {} } }) });
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings({});
  ctx.el('sdSetProfileSelect').value = 'Work';
  ctx.el('sdSetDraftHistoryLimit').value = '2';

  await ctx.feature.handleSave();

  assert.deepEqual(ctx.bridge.signatures(), [], 'nothing may reach the backend while a field is invalid');
  assert.match(ctx.el('sdSetProfileMessage').textContent, /fix validation errors/);
});

test('a failed save reports the backend message instead of claiming success', async (t) => {
  const ctx = mount({
    routes: defaultRoutes({ 'POST /settings/profiles/Work': { ok: false, status: 500, body: { detail: 'disk is full' } } }),
  });
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings(STORED_SETTINGS);
  ctx.el('sdSetProfileSelect').value = 'Work';

  await ctx.feature.handleSave();
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Save failed: disk is full');
});

// --- UI-07-004: Discard -------------------------------------------------------

test('#sdSetDiscardButton re-fetches the stored profile and drops the local edits', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings({ recording_mode: 'toggle' });
  ctx.el('sdSetProfileSelect').value = 'Work';

  const recordingMode = ctx.el('sdSetRecordingMode');
  recordingMode.value = 'ptt';
  recordingMode.emit('change');
  assert.equal(ctx.feature.isDirty(), true);

  const discard = ctx.el('sdSetDiscardButton');
  assert.ok(discard.listenerCount('click') > 0, 'Discard was never bound');
  discard.click();
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.signatures(), ['GET /settings/profiles/Work']);
  assert.equal(recordingMode.value, 'ptt', 'the stored profile in this fixture is ptt, so that is what comes back');
  assert.equal(ctx.feature.isDirty(), false);
  assert.equal(ctx.el('sdSetSaveBar').classList.contains('hidden'), true);
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Discarded changes for Work.');
});

// --- UI-07-009 / UI-07-010: the shared name input + Activate ------------------

test('#sdSetActivateProfileButton POSTs the selected profile to the activate route and refreshes the list', async (t) => {
  const changed = [];
  const ctx = mount({
    routes: defaultRoutes({
      'POST /settings/profiles/Work/activate': { profiles: ['Default', 'Work'], active_profile: 'Work', settings: { recording_mode: 'ptt' } },
    }),
  });
  t.after(ctx.restore);
  const feature = createSettingsWorkspaceFeature({
    elements: collectSettingsElements(ctx.doc),
    hooks: { onProfileChanged: (payload) => changed.push(payload) },
  });
  feature.init();
  ctx.el('sdSetProfileSelect').value = 'Work';

  const activate = ctx.el('sdSetActivateProfileButton');
  assert.ok(activate.listenerCount('click') > 0, 'Activate was never bound');
  await feature.handleActivate();

  assert.deepEqual(ctx.bridge.signatures(), ['POST /settings/profiles/Work/activate']);
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Activated Work.');
  assert.deepEqual(ctx.el('sdSetProfileSelect').children.map((o) => o.value), ['Default', 'Work']);
  assert.equal(changed.length, 1);
});

test('#sdSetNewProfileName is the name every create/rename/duplicate reads, and it is cleared on success', async (t) => {
  const ctx = mount({
    routes: defaultRoutes({
      'POST /settings/profiles': { profile: 'Travel', profiles: ['Default', 'Work', 'Travel'], settings: {} },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings({});

  const nameInput = ctx.el('sdSetNewProfileName');
  nameInput.value = '  Travel  ';
  await ctx.feature.handleCreate();

  const call = ctx.bridge.find('POST', '/settings/profiles');
  assert.ok(call, 'Create must POST to the profiles collection');
  assert.equal(call.body.name, 'Travel', 'the name is trimmed before it is sent');
  assert.equal(nameInput.value, '', 'a successful create empties the shared name field');
});

test('#sdSetNewProfileName rejects a reserved or malformed name before any request goes out', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings({});

  ctx.el('sdSetNewProfileName').value = 'Default';
  await ctx.feature.handleCreate();
  assert.match(ctx.el('sdSetProfileMessage').textContent, /reserved profile name/);

  ctx.el('sdSetNewProfileName').value = 'has spaces!';
  await ctx.feature.handleCreate();
  assert.match(ctx.el('sdSetProfileMessage').textContent, /letters, numbers, underscores, and hyphens/);

  assert.deepEqual(ctx.bridge.signatures(), [], 'a bad name must never reach the backend');
});

// --- UI-07-016: Delete --------------------------------------------------------

test('#sdSetDeleteProfileButton DELETEs the selected profile', async (t) => {
  const ctx = mount({
    routes: defaultRoutes({
      'DELETE /settings/profiles/Work': { profiles: ['Default'], active_profile: 'Default', settings: {} },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.el('sdSetProfileSelect').value = 'Work';

  const deleteButton = ctx.el('sdSetDeleteProfileButton');
  assert.ok(deleteButton.listenerCount('click') > 0, 'Delete was never bound');
  await ctx.feature.handleDelete();

  assert.deepEqual(ctx.bridge.signatures(), ['DELETE /settings/profiles/Work']);
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Deleted Work.');
});

test('#sdSetDeleteProfileButton refuses to delete the Default profile', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.el('sdSetProfileSelect').value = 'Default';

  await ctx.feature.handleDelete();
  assert.deepEqual(ctx.bridge.signatures(), []);
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Default profile cannot be deleted.');
});

// --- UI-07-015: Import --------------------------------------------------------

function installFileReader(pending) {
  const previous = globalThis.FileReader;
  globalThis.FileReader = class {
    readAsText(file) {
      pending.push(Promise.resolve().then(() => this.onload({ target: { result: file.contents } })));
    }
  };
  return () => { globalThis.FileReader = previous; };
}

test('#sdSetImportProfileFile upgrades a legacy unversioned export and POSTs it to the import route', async (t) => {
  const pending = [];
  const restoreReader = installFileReader(pending);
  t.after(restoreReader);
  const ctx = mount({
    routes: defaultRoutes({
      'POST /settings/profiles/import': { profiles: ['Default', 'Legacy'], active_profile: 'Legacy', settings: { recording_mode: 'ptt' } },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();

  const importFile = ctx.el('sdSetImportProfileFile');
  assert.ok(importFile.listenerCount('change') > 0, 'the import file input was never bound');
  // A bare settings object with no schema_version -- the legacy shape the
  // upgrade path exists for.
  importFile.emit('change', {
    target: { files: [{ name: 'Legacy_profile.json', contents: JSON.stringify({ recording_mode: 'ptt' }) }] },
  });
  await Promise.all(pending);
  await new Promise((resolve) => setImmediate(resolve));

  const call = ctx.bridge.find('POST', '/settings/profiles/import');
  assert.ok(call, 'the import never reached the backend');
  assert.equal(call.body.schema_version, 1, 'the legacy payload must be upgraded before it is sent');
  assert.equal(call.body.name, 'Legacy', 'the filename supplies the name a legacy export lacks');
  assert.deepEqual(call.body.settings, { recording_mode: 'ptt' });
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Imported profile Legacy successfully.');
  assert.equal(importFile.value, '', 'the file input is cleared so the same file can be picked twice');
});

test('#sdSetImportProfileFile refuses a future schema version rather than importing it partially', async (t) => {
  const pending = [];
  t.after(installFileReader(pending));
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.el('sdSetImportProfileFile').emit('change', {
    target: {
      files: [{
        name: 'Future_profile.json',
        contents: JSON.stringify({ kind: 'betterfingers_profile', schema_version: 99, name: 'Future', settings: {} }),
      }],
    },
  });
  await Promise.all(pending);
  await new Promise((resolve) => setImmediate(resolve));

  assert.deepEqual(ctx.bridge.signatures(), []);
  assert.match(ctx.el('sdSetProfileMessage').textContent, /Unsupported profile schema version: 99/);
});

// --- UI-15-023: the Long Recording Stitch Pass toggle ------------------------

test('#sdSetStitchPass round-trips through render and save like any other profile field', async (t) => {
  const saved = [];
  const ctx = mount({
    routes: defaultRoutes({
      'POST /settings/profiles/Work': ({ body }) => { saved.push(body); return { profile: 'Work', settings: body.settings }; },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();

  ctx.feature.renderSettings({ ...STORED_SETTINGS, long_recording_stitch_pass_enabled: true });
  const stitchPass = ctx.el('sdSetStitchPass');
  assert.equal(stitchPass.checked, true, 'a stored value must come back checked');

  stitchPass.checked = false;
  stitchPass.emit('change');
  assert.equal(ctx.el('sdSetSaveBar').classList.contains('visible'), true, 'this toggle is a real profile edit, not a client-local one');

  ctx.el('sdSetProfileSelect').value = 'Work';
  await ctx.feature.handleSave();
  assert.equal(saved[0].settings.long_recording_stitch_pass_enabled, false);
});

// --- Task B: refreshAll() must not destroy in-progress user input -----------
//
// refreshAll() is called on the cold-start race AND on every mid-session
// backend-restart re-populate (bootstrap/signalDeskApp.js's 3s /health
// poll). renderSettings() clears dirty state and overwrites every field, so
// it must not fire while the user is mid-edit or has navigated the dropdown
// to a profile they have not yet activated.

test('refreshAll() does not clobber a field the user is mid-edit on', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();
  ctx.feature.renderSettings(STORED_SETTINGS);
  ctx.el('sdSetProfileSelect').value = 'Work';

  const recordingMode = ctx.el('sdSetRecordingMode');
  recordingMode.value = 'ptt';
  recordingMode.emit('change');
  assert.equal(ctx.feature.isDirty(), true);

  await ctx.feature.refreshAll();
  assert.equal(recordingMode.value, 'ptt', 'a background repopulate must not discard an unsaved edit');
  assert.equal(ctx.feature.isDirty(), true, 'the dirty flag (and the visible "Unsaved changes" bar) must survive the repopulate too');
});

test('refreshAll() keeps the dropdown on a profile the user is viewing but has not activated', async (t) => {
  const ctx = mount({
    routes: defaultRoutes({
      // active_profile stays 'Work' throughout -- the user merely selected a
      // different, not-yet-activated profile in the dropdown.
      'GET /settings/profiles': { profiles: ['Default', 'Work'], active_profile: 'Work', settings: STORED_SETTINGS },
    }),
  });
  t.after(ctx.restore);
  ctx.feature.init();
  await ctx.feature.refreshAll();
  ctx.el('sdSetProfileSelect').value = 'Default';

  await ctx.feature.refreshAll();
  assert.equal(ctx.el('sdSetProfileSelect').value, 'Default', 'a background repopulate must not snap the dropdown back to the real active profile out from under the user');
});

test('refreshAll() still resyncs normally once the user is neither dirty nor viewing a different profile', async (t) => {
  const ctx = mount();
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  const workOption = ctx.el('sdSetProfileSelect').children.find((o) => o.value === 'Work');
  assert.equal(workOption.selected, true, 'the ordinary cold-start/health-recovery resync must still select the active profile');
  assert.equal(ctx.el('sdSetProfileMessage').textContent, 'Active profile: Work');
});

// --- UI-07-018: the PTT availability note ------------------------------------

test('#sdSetPttAvailabilityNote states the limitation when the session cannot do push-to-talk', async (t) => {
  const ctx = mount({ hotkeyCapabilities: { supports_ptt: false } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  assert.equal(ctx.el('sdSetPttAvailabilityNote').textContent, 'Push-to-talk is not supported in this session.');
});

test('#sdSetPttAvailabilityNote stays empty when push-to-talk is available', async (t) => {
  const ctx = mount({ hotkeyCapabilities: { supports_ptt: true } });
  t.after(ctx.restore);
  ctx.feature.init();

  await ctx.feature.refreshAll();
  assert.equal(ctx.el('sdSetPttAvailabilityNote').textContent, '');
  // refreshAll is the real startup path: it must reach the profile, persona
  // and privacy routes, not just the one under test.
  assert.deepEqual(ctx.bridge.signatures(), ['GET /settings/profiles', 'GET /personas', 'GET /privacy']);
});
