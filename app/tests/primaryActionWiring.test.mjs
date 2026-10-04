import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import { test } from 'node:test';

const require = createRequire(import.meta.url);

function fakeWindows() {
  class FakeWindow extends EventEmitter {
    constructor() {
      super();
      this.visible = false;
      this.destroyed = false;
      this.webContents = new EventEmitter();
      this.webContents.mainFrame = {};
      this.webContents.setWindowOpenHandler = () => {};
      this.webContents.isLoading = () => false;
      this.webContents.send = (_channel, draft) => { this.lastDraft = draft; };
    }
    setPosition() {}
    isDestroyed() { return this.destroyed; }
    isVisible() { return this.visible; }
    showInactive() { this.visible = true; }
    hide() { this.visible = false; this.emit('hide'); }
    loadFile() { return Promise.resolve(); }
    loadURL() { return Promise.resolve(); }
  }
  const Module = require('node:module');
  const originalLoad = Module._load;
  Module._load = function(name, ...args) {
    if (name === 'electron') return { BrowserWindow: FakeWindow, screen: { getPrimaryDisplay: () => ({ workAreaSize: { width: 1920, height: 1080 } }) } };
    return originalLoad.call(this, name, ...args);
  };
  try {
    const path = require.resolve('../src/main/windows.js');
    delete require.cache[path];
    return { windows: require(path), restore() { Module._load = originalLoad; } };
  } catch (error) { Module._load = originalLoad; throw error; }
}

function acknowledge(windows, window, overrides = {}) {
  return windows.acknowledgeReviewDraft(window.webContents, {
    id: window.lastDraft.id,
    presentation: window.lastDraft.reviewPresentation,
    finalText: window.lastDraft.final_text,
    ...overrides,
  });
}

test('only acknowledged visible review presentation can authorize F9; new arrivals and closed/crashed windows invalidate it', () => {
  const context = fakeWindows();
  const { windows } = context;
  try {
  const window = windows.showReviewWindow({ id: 7, final_text: 'shown' });
  assert.equal(windows.getDisplayedReviewDraft(), null);
  assert.equal(windows.acknowledgeReviewDraft({}, { id: 7 }), false);
  assert.equal(acknowledge(windows, window), true);
  assert.deepEqual(windows.getDisplayedReviewDraft(), { displayed_draft_id: 7, displayed_final_text: 'shown' });
  assert.equal(acknowledge(windows, window, { id: 999 }), false);
  assert.equal(windows.getDisplayedReviewDraft(), null);
  acknowledge(windows, window);
  const oldPresentation = window.lastDraft.reviewPresentation;
  windows.showReviewWindow({ id: 8, final_text: 'newer' });
  assert.equal(windows.getDisplayedReviewDraft(), null);
  assert.equal(acknowledge(windows, window, { id: 7, presentation: oldPresentation }), false);
  acknowledge(windows, window);
  windows.hideReviewWindow();
  assert.equal(windows.getDisplayedReviewDraft(), null);
  windows.showReviewWindow({ id: 8, final_text: 'newer' });
  acknowledge(windows, window);
  window.webContents.emit('render-process-gone');
  assert.equal(windows.getDisplayedReviewDraft(), null);
  window.emit('closed');
  assert.equal(windows.getDisplayedReviewDraft(), null);
  } finally { context.restore(); }
});

test('overlay reports the actual visible text after paint and unsaved edits; API responses retain presentation identity', () => {
  const html = readFileSync(new URL('../src/renderer/review-overlay.html', import.meta.url), 'utf8');
  const script = html.slice(html.indexOf('      function renderDraft(draft)'), html.indexOf('      async function saveEdit()'));
  const reports = [], frames = [], events = {};
  const textarea = { value: '', addEventListener: (name, callback) => { events[name] = callback; } };
  const context = vm.createContext({
    currentDraft: null, currentReviewPresentation: null,
    statusEl: {}, rawTextEl: {}, finalTextEl: textarea,
    window: { betterFingersReview: { displayed: payload => reports.push(payload) } },
    requestAnimationFrame: callback => frames.push(callback),
    updateDraftSummary() {}, renderMetaStrip() {}, setOverlayState() {}, setMessage() {},
    mapDraftStatusToOverlayState: status => status,
  });
  vm.runInContext(script, context);
  context.renderDraft({ id: 7, final_text: 'shown', reviewPresentation: 3 });
  assert.equal(reports.length, 0);
  frames.shift()(); frames.shift()();
  assert.deepEqual(JSON.parse(JSON.stringify(reports.pop())), { id: 7, presentation: 3, finalText: 'shown' });
  textarea.value = 'unsaved edit'; events.input();
  assert.equal(reports.pop().finalText, 'unsaved edit');
  context.renderDraft({ id: 7, final_text: 'saved edit' });
  frames.shift()(); frames.shift()();
  assert.equal(reports.pop().presentation, 3);
});

test('display acknowledgment IPC rejects subframes and forwards identity; preload exposes only the typed acknowledgment', () => {
  const ipc = readFileSync(new URL('../src/main/ipc.js', import.meta.url), 'utf8');
  const start = ipc.indexOf("  onTrusted('review:displayed'");
  const end = ipc.indexOf('\n  });', start) + '\n  });'.length;
  let callback;
  const calls = [];
  vm.runInNewContext(ipc.slice(start, end), {
    onTrusted: (_name, handler) => { callback = handler; },
    require: () => ({ acknowledgeReviewDraft: (...args) => calls.push(args) }),
  });
  const sender = { mainFrame: {} };
  callback({ sender, senderFrame: {} }, { id: 7 });
  assert.equal(calls.length, 0);
  callback({ sender, senderFrame: sender.mainFrame }, { id: 7 });
  assert.equal(calls[0][0], sender);
  const preload = readFileSync(new URL('../src/preload/preload.js', import.meta.url), 'utf8');
  assert.match(preload, /displayed: \(payload\) => ipcRenderer\.send\('review:displayed', payload\)/);
});
