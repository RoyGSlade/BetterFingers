'use strict';

// Round 3, item 7: open the REAL native approval dialogs (Electron's dialog.showMessageBox, GTK on
// Linux) through the PRODUCTION approval broker, on a virtual X display, and record what a person
// would see: a screenshot of the whole screen and the dialog window's geometry, for
//   1. the largest preview the budget allows (exactly at the line budget), and
//   2. a preview over the budget, which must get the Close-only dialog.
// Each dialog is dismissed with a real Escape key press (xdotool), so the "a dismissal is a no"
// path is exercised against the real toolkit too.
//
// Run by app/tests/nativeDialogXvfb.test.mjs under xvfb-run; it is not a unit test. Usage:
//   electron nativeDialogProbe.cjs <outDir>
// Writes <outDir>/report.json and one PNG per case.

const path = require('node:path');
const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const { app, dialog } = require('electron');

const MAIN = path.resolve(__dirname, '..', '..', 'src', 'main');
const { createApprovalBroker, linesDigest, displayLines, MAX_DISPLAY_LINES, WRAP_WIDTH } = require(path.join(MAIN, 'approvalBroker.js'));

// As many copies of `make(i)` as fit the line budget once wrapped (header, blank and note: 5 lines).
function fillBudget(make) {
  const lines = [];
  let used = 0;
  for (let i = 0; ; i += 1) {
    const next = displayLines(make(i)).length;
    if (used + next > MAX_DISPLAY_LINES - 5) return lines;
    lines.push(make(i));
    used += next;
  }
}

const outDir = path.resolve(process.argv[process.argv.length - 1]);
fs.mkdirSync(outDir, { recursive: true });
const display = process.env.DISPLAY;

function sleep(ms) { return new Promise((resolve) => setTimeout(resolve, ms)); }

function screenSize() {
  const text = execFileSync('xdotool', ['getdisplaygeometry'], { encoding: 'utf8' }).trim();
  const [width, height] = text.split(/\s+/).map(Number);
  return { width, height };
}

function windowGeometry(title) {
  let ids = [];
  try {
    ids = execFileSync('xdotool', ['search', '--name', title], { encoding: 'utf8' }).trim().split(/\s+/).filter(Boolean);
  } catch { return null; }
  for (const id of ids.reverse()) {
    try {
      const text = execFileSync('xdotool', ['getwindowgeometry', '--shell', id], { encoding: 'utf8' });
      const geo = Object.fromEntries(text.trim().split('\n').map((line) => line.split('=')));
      const shape = { id, x: Number(geo.X), y: Number(geo.Y), width: Number(geo.WIDTH), height: Number(geo.HEIGHT) };
      if (shape.width > 50 && shape.height > 50) return shape;
    } catch { /* try the next */ }
  }
  return null;
}

function screenshot(file) {
  const { width, height } = screenSize();
  execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'x11grab', '-video_size', `${width}x${height}`,
    '-i', display, '-frames:v', '1', file]);
}

function fakeBackend(lines) {
  return {
    async send(method, route) {
      if (route === '/workflows/preview') {
        return { ok: true, status: 200, body: {
          ok: true, workflow_id: 'probe', name: 'Native dialog probe', preview_lines: lines,
          preview_sha256: linesDigest(lines), steps_sha256: 'a'.repeat(64), refusals: [],
        } };
      }
      return { ok: true, status: 200, body: { posted: route } };
    },
  };
}

async function runCase(name, lines, expectTitle) {
  const backend = fakeBackend(lines);
  const posted = [];
  const wrapped = { send: async (...args) => { posted.push(args[1]); return backend.send(...args); } };
  const broker = createApprovalBroker({ secret: Buffer.alloc(32, 7), dialog, backend: wrapped });
  const pending = broker.approveWorkflow('probe');
  let geometry = null;
  for (let i = 0; i < 40 && !geometry; i += 1) { await sleep(150); geometry = windowGeometry(expectTitle); }
  await sleep(600); // let GTK finish painting
  const png = path.join(outDir, `${name}.png`);
  screenshot(png);
  // A real key press, as a person would dismiss it.
  if (geometry) execFileSync('xdotool', ['windowfocus', '--sync', geometry.id]); // no window manager under Xvfb
  execFileSync('xdotool', ['key', 'Escape']);
  const result = await Promise.race([pending, sleep(8000).then(() => ({ timedOut: true }))]);
  return { name, lines: lines.length, geometry, screen: screenSize(), png, result, approvePosted: posted.includes('/workflows/approve') };
}

app.whenReady().then(async () => {
  const report = { electron: process.versions.electron, cases: [] };
  try {
    // The worst case the budget allows: every line at the full wrap width, and exactly the line
    // budget once the header, the blank lines and the (wrapped) note are counted.
    const atBudget = fillBudget((i) => `${i + 1}. Open the folder /home/someone/Projects/client-${String(i).padStart(2, '0')}/notes`);
    report.cases.push(await runCase('at-budget', atBudget, 'Approve workflow'));
    await sleep(700);
    // Wide glyphs: every line as wide as the budget allows, in the widest Latin capital and in
    // CJK (two columns each). These must not make the toolkit wrap a line a second time.
    // The broker wraps by estimated rendered width, so these long lines become several pieces;
    // the number of lines is chosen so the wrapped result is exactly at the line budget.
    const capitals = fillBudget((i) => `${i + 1}. ${'W'.repeat(100)}`);
    report.cases.push(await runCase('wide-latin', capitals, 'Approve workflow'));
    await sleep(700);
    const cjk = fillBudget((i) => `${i + 1}. ${'\u6f22'.repeat(80)}`);
    report.cases.push(await runCase('wide-cjk', cjk, 'Approve workflow'));
    await sleep(700);
    const overBudget = Array.from({ length: MAX_DISPLAY_LINES + 10 }, (_, i) => `${i + 1}. step`);
    report.cases.push(await runCase('over-budget', overBudget, 'Approve workflow'));
  } catch (error) {
    report.error = String(error && error.stack || error);
  }
  fs.writeFileSync(path.join(outDir, 'report.json'), JSON.stringify(report, null, 2));
  app.exit(0);
});
