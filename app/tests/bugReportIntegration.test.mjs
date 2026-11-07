import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';

const appRoot = path.resolve(import.meta.dirname, '..');
const repoRoot = path.resolve(appRoot, '..');
const readApp = (...parts) => fs.readFileSync(path.join(appRoot, ...parts), 'utf8');
const readRepo = (...parts) => fs.readFileSync(path.join(repoRoot, ...parts), 'utf8');

const ipc = readApp('src', 'main', 'ipc.js');
const preload = readApp('src', 'preload', 'preload.js');
const bootstrap = readApp('src', 'renderer', 'bootstrap', 'signalDeskApp.js');
const html = readApp('src', 'renderer', 'signal-desk.html');
const renderer = readApp('src', 'renderer', 'features', 'bugReport.js');
const vite = readApp('electron.vite.config.js');
const security = readRepo('SECURITY.md');
const docs = readRepo('docs', 'BUG_REPORTING.md');
const relay = readRepo('services', 'bug-report-relay', 'src', 'index.js');
const relayPackage = JSON.parse(readRepo('services', 'bug-report-relay', 'package.json'));

const requiredIds = [
  'sdBugReportOpen', 'sdBugReportDialog', 'sdBugReportTitle', 'sdBugReportClose',
  'sdBugReportSummary', 'sdBugReportSteps', 'sdBugReportExpected', 'sdBugReportActual',
  'sdBugReportContact', 'sdBugReportPreview', 'sdBugReportPreviewButton',
  'sdBugReportConsent', 'sdBugReportDestination', 'sdBugReportSubmit', 'sdBugReportStatus',
];

test('bug-report IPC is trusted, fixed-shape, and keeps diagnostics in main', () => {
  for (const channel of ['bug-report:get-config', 'bug-report:prepare', 'bug-report:submit']) {
    assert.match(ipc, new RegExp(`handleTrusted\\('${channel.replaceAll(':', '\\:')}'`));
    assert.doesNotMatch(ipc, new RegExp(`ipcMain\\.(?:handle|on)\\('${channel.replaceAll(':', '\\:')}'`));
  }
  assert.match(ipc, /createBugReportController\(\{[\s\S]*backendProxy,[\s\S]*dialog,[\s\S]*shell,[\s\S]*clipboard/);
  const prepareHandler = ipc.match(/handleTrusted\('bug-report:prepare',[\s\S]*?\n\s*\}\);/)?.[0] || '';
  assert.match(prepareHandler, /\{ summary, steps, expected, actual, contact \}/);
  assert.doesNotMatch(prepareHandler, /diagnostics|logs|endpoint|token|secret/i);
  const submitHandler = ipc.match(/handleTrusted\('bug-report:submit',[\s\S]*?\n\s*\}\);/)?.[0] || '';
  assert.match(submitHandler, /\{ previewId, destination \}/);
  assert.doesNotMatch(submitHandler, /\b(?:diagnostics|logs|endpoint|token|secret)\b/i);
});

test('preload exposes only the fixed form, preview id, and destination contract', () => {
  assert.match(preload, /getBugReportConfig: \(\) => ipcRenderer\.invoke\('bug-report:get-config'\)/);
  assert.match(preload, /prepareBugReport: \(\{ summary, steps, expected, actual, contact \} = \{\}\)/);
  assert.match(preload, /submitBugReport: \(\{ previewId, destination \} = \{\}\)/);
  const bugBridge = preload.match(/getBugReportConfig:[\s\S]*?submitBugReport:[\s\S]*?\n\s*voiceStatus:/)?.[0] || '';
  assert.doesNotMatch(bugBridge, /diagnostics|logs|endpoint|webhook|token|secret/i);
});

test('the controller is bundled and the shipping Signal Desk initializes and destroys the feature', () => {
  assert.match(vite, /bugReportController:\s*resolve\(__dirname, 'src\/main\/bugReportController\.js'\)/);
  assert.match(bootstrap, /createBugReportFeature, collectBugReportElements/);
  assert.match(bootstrap, /createBugReportFeature\(\{[\s\S]*collectBugReportElements\(doc\)[\s\S]*doc\.defaultView\?\.betterFingers/);
  assert.match(bootstrap, /bugReport\.destroy\?\.\(\)/);
});

test('Signal Desk contains one accessible reviewed-report surface with bounded fields', () => {
  for (const id of requiredIds) {
    const matches = html.match(new RegExp(`id="${id}"`, 'g')) || [];
    assert.equal(matches.length, 1, `${id} must exist exactly once`);
  }
  assert.match(html, /id="sdBugReportDialog"[^>]*role="dialog"[^>]*aria-modal="true"/);
  assert.match(html, /id="sdBugReportSummary"[^>]*maxlength="160"[^>]*required/);
  assert.match(html, /id="sdBugReportActual"[^>]*maxlength="4000"[^>]*required/);
  assert.match(html, /id="sdBugReportConsent"/);
  assert.match(html, /You see the exact report before anything leaves this computer/);
  assert.match(html, /That is a handoff, not a completed submission/);
  assert.doesNotMatch(renderer, /\.innerHTML\b/);
});

test('security and operator docs state the outbound exception, disabled-by-default relay, and secret boundary', () => {
  assert.match(security, /bug report the user explicitly prepares, reviews, consents/);
  assert.match(docs, /No relay endpoint is deployed or configured by this repository change/);
  assert.match(docs, /allowed_mentions: \{ "parse": \[\] \}/);
  assert.match(docs, /Do not put a Discord webhook, bot token, SMTP password/);
  assert.match(docs, /opening an app is reported as[\s\S]*never as a completed submission/i);
});

test('the deployable relay keeps provider secrets server-side and fails closed on abuse controls', () => {
  assert.equal(relayPackage.private, true);
  assert.match(relay, /BUG_REPORT_RATE_LIMITER\.limit/);
  assert.match(relay, /BUG_REPORT_DEDUPE\.(?:get|put)/);
  assert.match(relay, /browser_origin_refused/);
  assert.match(relay, /allowed_mentions:\s*\{\s*parse:\s*\[\]\s*\}/);
  assert.match(relay, /authorization:\s*`Bearer \$\{env\.RESEND_API_KEY\}`/);
  assert.doesNotMatch(preload, /DISCORD_WEBHOOK_URL|RESEND_API_KEY|BUG_REPORT_EMAIL_TO/);
  assert.match(docs, /No relay endpoint is deployed or configured by this repository change/);
});
