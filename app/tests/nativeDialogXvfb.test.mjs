// Round 3, item 7: the native approval dialog, REALLY opened. Electron's dialog.showMessageBox (GTK
// on Linux) is driven through the production approval broker on a virtual X display (xvfb-run),
// at three common screen sizes, and the dialog window is measured with xdotool and photographed
// with ffmpeg (tests/electron/nativeDialogProbe.cjs). It proves, on the real toolkit:
//   * the largest content the budgets allow (plain text, the widest Latin capitals, CJK) fits on a
//     1920x1080, a 1366x768 and a 1280x720 screen with the buttons on screen;
//   * content over the budget gets the Close-only dialog and nothing is posted or signed;
//   * a real Escape key press is a "no".
// Skips (with the reason) where xvfb-run, xdotool, ffmpeg or the Electron binary is missing, or off
// Linux. Set BF_NATIVE_DIALOG_OUT=<dir> to keep the screenshots.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ELECTRON = path.join(HERE, '..', 'node_modules', 'electron', 'dist', 'electron');
const PROBE = path.join(HERE, 'electron', 'nativeDialogProbe.cjs');

function missing() {
  if (process.platform !== 'linux') return 'the GTK dialog probe runs on Linux only';
  if (!fs.existsSync(ELECTRON)) return 'the Electron binary is not installed';
  for (const tool of ['xvfb-run', 'xdotool', 'ffmpeg']) {
    try { execFileSync('which', [tool], { stdio: 'ignore' }); } catch { return `${tool} is not installed`; }
  }
  return '';
}

const reason = missing();
const SIZES = ['1920x1080', '1366x768', '1280x720'];

for (const size of SIZES) {
  test(`the real native dialog fits and fails closed on a ${size} screen`, { skip: reason || false, timeout: 180000 }, () => {
    const base = process.env.BF_NATIVE_DIALOG_OUT || fs.mkdtempSync(path.join(os.tmpdir(), 'bf-native-dialog-'));
    const out = path.join(base, `native-dialog-${size}`);
    fs.rmSync(out, { recursive: true, force: true });
    const run = spawnSync('xvfb-run', ['-a', '-s', `-screen 0 ${size}x24`, ELECTRON, '--no-sandbox', PROBE, out],
      { encoding: 'utf8', timeout: 170000 });
    const reportPath = path.join(out, 'report.json');
    assert.ok(fs.existsSync(reportPath), `the probe wrote no report (exit ${run.status}): ${String(run.stderr).slice(-600)}`);
    const report = JSON.parse(fs.readFileSync(reportPath, 'utf8'));
    assert.equal(report.error, undefined, report.error);
    const byName = Object.fromEntries(report.cases.map((c) => [c.name, c]));
    for (const name of ['at-budget', 'wide-latin', 'wide-cjk']) {
      const c = byName[name];
      assert.ok(c.geometry, `${name}: the dialog window was found`);
      assert.ok(c.geometry.y + c.geometry.height <= c.screen.height, `${name}: ${c.geometry.height}px tall on a ${c.screen.height}px screen`);
      assert.ok(c.geometry.x + c.geometry.width <= c.screen.width, `${name}: fits the width`);
      assert.match(String(c.result.error), /You cancelled/, `${name}: Escape is a no`);
      assert.equal(c.approvePosted, false, `${name}: nothing was approved`);
      assert.ok(fs.statSync(c.png).size > 1000, `${name}: screenshot taken`);
    }
    // Round 4, item 2: a name with 45 newlines never yields a dialog taller than the screen.
    const nl = byName['newline-name'];
    assert.ok(nl && nl.geometry, 'newline-name: a dialog was shown');
    assert.ok(nl.geometry.y + nl.geometry.height <= nl.screen.height, `newline-name: ${nl.geometry.height}px tall on a ${nl.screen.height}px screen`);
    assert.equal(nl.approvePosted, false, 'newline-name: nothing was approved');
    const nlShort = byName['newline-name-short'];
    assert.ok(nlShort && nlShort.geometry, 'newline-name-short: a dialog was shown');
    assert.ok(nlShort.geometry.y + nlShort.geometry.height <= nlShort.screen.height, `newline-name-short: ${nlShort.geometry.height}px tall`);
    assert.ok(nlShort.geometry.height < 500, 'newline-name-short: the 45 newlines did not become 45 lines');
    assert.match(String(nlShort.result.error), /You cancelled/, 'newline-name-short: an approving dialog, dismissed with Escape');
    assert.equal(nlShort.approvePosted, false);
    const over = byName['over-budget'];
    assert.ok(over.geometry, 'the too-long dialog was shown');
    assert.ok(over.geometry.height < 400, 'it is the short Close-only notice, not the content');
    assert.match(String(over.result.error), /too long to review/);
    assert.equal(over.approvePosted, false);
    // Round 5, item 3: the real 22 wipe labels fit an approving dialog; a learned list too long to
    // show gets the short Close-only notice and nothing is forwarded.
    const wipe = byName['wipe-personal-data'];
    assert.ok(wipe && wipe.geometry, 'wipe-personal-data: a dialog was shown');
    assert.ok(wipe.geometry.y + wipe.geometry.height <= wipe.screen.height, `wipe-personal-data: ${wipe.geometry.height}px tall on a ${wipe.screen.height}px screen`);
    assert.match(String(wipe.result.error), /You cancelled/, 'wipe-personal-data: an approving dialog, dismissed with Escape');
    assert.equal(wipe.approvePosted, false);
    const many = byName['learned-clear-too-many'];
    assert.ok(many && many.geometry, 'learned-clear-too-many: a dialog was shown');
    assert.ok(many.geometry.height < 400, 'learned-clear-too-many: the short Close-only notice');
    assert.match(String(many.result.error), /Too many to show here/);
    assert.equal(many.approvePosted, false);
    if (!process.env.BF_NATIVE_DIALOG_OUT) fs.rmSync(base, { recursive: true, force: true });
  });
}
