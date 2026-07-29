// Wave 11B (B-2): the two floating overlay WINDOWS, exercised for the first time.
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs overlay-windows
//
// ---------------------------------------------------------------------------
// READ THIS BEFORE TREATING THESE SCENARIOS AS PARITY EVIDENCE.
// ---------------------------------------------------------------------------
// `overlay.html` and `review-overlay.html` are real production windows: separate
// always-on-top BrowserWindows from `app/src/main/windows.js`, shipped whichever
// dashboard is loaded. Wave 11 counted them in the production closure on that
// basis and called their 18 unevidenced parity rows an AUDIT gap.
//
// Writing this suite turned up something the audit had not: on the production
// page they are, in normal use, unreachable.
//
//   * `overlay:update-status` is what makes the capture overlay appear and show
//     a pipeline state. Its only renderer-side caller in the whole repo is
//     `app/src/renderer/main.js` -- the LEGACY page. The production module
//     closure (`signal-desk.html` + everything `bootstrap/signalDeskApp.js`
//     imports) contains no call to `updateOverlayStatus` at all. Signal Desk
//     consumes the same voice-status stream itself (features/talkCapture.js)
//     and drives its own in-page ring, and never forwards to the overlay window.
//   * `review:show` is the only way `review-overlay.html`'s window is ever
//     created. Its only caller is likewise `main.js`. On the production page
//     that window is never created at all.
//
// So the honest split for these rows is not "anchored, needs QA". It is:
// the window code ships and works, and nothing on the shipping page reaches it.
// That is a PRODUCT gap, and it is recorded as one in
// docs/release/WAVE11_BLOCKERS.md B-2. These scenarios do not paper over it --
// they are what makes it checkable, and they are the regression net the fix
// will need.
//
// What that means for how these scenarios are written: they drive the overlays
// through the REAL main-process handlers (`overlay:update-status`, `review:show`
// in `app/src/main/ipc.js`) via the REAL preload bridge, invoked from the
// production page. Every line of main-process routing, window management and
// overlay-renderer logic under test is production code on the production path.
// The one thing NOT proven is that the production page decides to make those
// calls -- because it does not. The scenario named
// `settings-appearance-reaches-the-overlay-window` is the exception and is
// marked as such: `#sdSetOverlaySize` is a real production control with a real
// production caller, so that one is a complete chain.
//
// Reaching a second window needs no app change and no debug handle: run.mjs now
// hands scenarios `ctx.app` (the ElectronApplication), which already tracks
// every window the app owns, hidden ones included. See harness.mjs's
// auxiliaryWindow().

import { expect } from '@playwright/test';
import { readyProfile } from './fixtures/cold-boot.mjs';
import { auxiliaryWindow } from '../harness.mjs';

const DRAFT = {
  id: 7,
  status: 'pending',
  raw_text: 'so uh can you take a look at the deploy when you get a sec',
  final_text: 'Could you take a look at the deploy when you have a moment?',
  confidence: { score: 0.91 },
  metadata: { duration_seconds: 12 },
  persona_name: 'True Janitor',
  auto_send_ok: true,
};

const REWRITTEN = {
  ...DRAFT,
  status: 'rewritten',
  final_text: 'Please review the deploy when you can.',
};

// --- captures ----------------------------------------------------------------

let rewriteCalls = [];
let ttsCalls = [];
let ttsStops = [];
let declines = [];

function overlayBackendState(extra = {}) {
  return () => {
    rewriteCalls = [];
    ttsCalls = [];
    ttsStops = [];
    declines = [];
    return {
      ...readyProfile(),
      'GET /runtime/tts-status': { ok: true, backend: 'kokoro', message: '' },
      'GET /drafts': { drafts: [DRAFT] },
      'POST /drafts/:id/edit': (_req, { body }) => ({ ...DRAFT, final_text: body?.final_text }),
      'POST /drafts/:id/rewrite': (_req, { params, body }) => {
        rewriteCalls.push({ id: params.id, ...body });
        return REWRITTEN;
      },
      'POST /drafts/:id/tts': (_req, { params, body }) => {
        ttsCalls.push({ id: params.id, ...body });
        return { ok: true };
      },
      'POST /tts/stop': () => {
        ttsStops.push(true);
        return { ok: true };
      },
      'POST /drafts/:id/decline': (_req, { params }) => {
        declines.push(params.id);
        return { ok: true };
      },
      ...extra,
    };
  };
}

/**
 * Push a pipeline status through the real `overlay:update-status` handler.
 *
 * Invoked from the production page's own preload bridge, which is the exact
 * call `main.js` makes on the legacy page and the exact call the production page
 * would need to make. See this file's header for why it does not.
 */
async function pushStatus(page, payload) {
  await page.evaluate((update) => window.betterFingers.updateOverlayStatus(update), payload);
}

/** Per-window `{ url, visible }` straight from the main process. */
async function windowVisibility(app) {
  return app.evaluate(({ BrowserWindow }) =>
    BrowserWindow.getAllWindows().map((win) => ({
      file: (win.webContents.getURL().split('?')[0] || '').split('/').pop(),
      visible: win.isVisible(),
    })),
  );
}

async function visibilityOf(app, file) {
  const windows = await windowVisibility(app);
  return windows.find((win) => win.file === file) || null;
}

async function openCaptureOverlay(page, app) {
  // The capture overlay window is created during startup (main.js), so it
  // already exists -- it is just hidden until a status arrives.
  const overlay = await auxiliaryWindow(app, 'overlay.html');
  await pushStatus(page, { status: 'recording' });
  await expect
    .poll(async () => (await visibilityOf(app, 'overlay.html'))?.visible)
    .toBe(true);
  return overlay;
}

async function openReviewOverlay(page, app, draft = DRAFT) {
  await page.evaluate((d) => window.betterFingers.showReviewOverlay(d), draft);
  const review = await auxiliaryWindow(app, 'review-overlay.html');
  await expect(review.locator('#status')).toHaveText(`Draft #${draft.id}`);
  return review;
}

export const overlayProdScenarios = [
  {
    area: 'overlay-windows',
    ui: 'signal-desk-prod',
    name: 'capture-overlay-renders-every-pipeline-state',
    kind: 'standard',
    description:
      'The floating capture overlay is the surface a user watches while dictating, and until Wave 11B nothing '
      + 'exercised it. Pushing a status through the real overlay:update-status handler shows the window (it is '
      + 'created hidden at startup) and drives #statusRing and #statusText through the states that matter: '
      + 'recording, processing, draft-ready and an error. #statusText carries both the label and a data-ring-state '
      + 'attribute, and the attribute is the assertion that matters -- a label that says "Recording..." over an '
      + 'idle-coloured ring is precisely the failure a screenshot cannot show. An idle status with always-on off '
      + 'hides the window again, which is the contract that stops the overlay sitting on top of everything after '
      + 'dictation ends.',
    backendState: overlayBackendState(),
    async navigate(page, { app }) {
      await openCaptureOverlay(page, app);
    },
    async expects(page, { app }) {
      const overlay = await auxiliaryWindow(app, 'overlay.html');
      await expect(overlay.locator('#statusRing')).toHaveCount(1);

      const label = overlay.locator('#statusText');
      await expect(label).toHaveText('Recording...');
      await expect(label).toHaveAttribute('data-ring-state', 'recording');

      await pushStatus(page, { status: 'transcribing' });
      await expect(label).toHaveText('Processing...');
      await expect(label).toHaveAttribute('data-ring-state', 'transcribing');

      // A payload `message` wins over the default label where the mapping
      // allows it, which is how the pipeline reports chunking progress.
      await pushStatus(page, { status: 'chunking_progress', message: 'Chunk 2 of 5' });
      await expect(label).toHaveText('Chunk 2 of 5');
      await expect(label).toHaveAttribute('data-ring-state', 'transcribing');

      await pushStatus(page, { status: 'preview_ready', durationMs: 30000 });
      await expect(label).toHaveText('Draft ready');
      await expect(label).toHaveAttribute('data-ring-state', 'ready');

      await pushStatus(page, { status: 'draft_error', message: 'Model unavailable', durationMs: 30000 });
      await expect(label).toHaveText('Model unavailable');
      await expect(label).toHaveAttribute('data-ring-state', 'error');

      // Live mic amplitude rides along on the recording payload. Its effect is
      // inside the canvas and cannot honestly be asserted from the DOM, so what
      // is asserted here is the part that CAN be: an amplitude-bearing payload
      // is accepted and still resolves to the recording state rather than
      // falling through to the unknown/idle default.
      await pushStatus(page, { status: 'recording', amplitude: 0.62 });
      await expect(label).toHaveAttribute('data-ring-state', 'recording');

      // Idle + always-on off puts the overlay away again.
      await pushStatus(page, { status: 'idle' });
      await expect
        .poll(async () => (await visibilityOf(app, 'overlay.html'))?.visible)
        .toBe(false);
    },
    // No screenshot: Playwright's page.screenshot() hangs indefinitely on this
    // window (it reports "fonts loaded" and then times out at 30s). The capture
    // overlay is frameless, transparent and always-on-top, which is the shape
    // that does not screenshot reliably here. The assertions above drive the
    // real overlay through every pipeline state and check the data-ring-state
    // attribute, so the coverage is real -- only the picture is missing, and a
    // 30-second hang per run is a worse trade than no image.
    screenshots: [],
  },
  {
    area: 'overlay-windows',
    ui: 'signal-desk-prod',
    name: 'settings-appearance-reaches-the-overlay-window',
    kind: 'standard',
    description:
      'The ONE overlay chain that is complete on the production page today. Settings > Appearance owns the overlay '
      + 'appearance group (#sdSetOverlaySize, #sdSetOverlayLabelPos), settingsWorkspace.js pushes each change '
      + 'through overlay:set-appearance, and the main process both resizes the window and forwards the renderer-side '
      + 'bits to overlay.html. Choosing "Large" resizes the ring canvas to its 108px size and choosing a label '
      + 'position un-hides #statusText and positions it -- asserted on the overlay window itself, not on the '
      + 'Settings control, because a setting that renders correctly and reaches nothing is the failure this covers. '
      + 'Setting an appearance also shows the overlay, which is how a user sees what they just changed.',
    backendState: overlayBackendState(),
    async navigate(page) {
      await page.click('.sd-nav__button[data-nav="settings"]');
      await expect(page.locator('#workspace-settings')).toBeVisible();
      await page.click('#sdSetNavAppearance');
      await expect(page.locator('#sdSetOverlayAppearanceGroup')).toBeVisible();
    },
    async expects(page, { app }) {
      const overlay = await auxiliaryWindow(app, 'overlay.html');
      const canvas = overlay.locator('#statusRing');
      const label = overlay.locator('#statusText');

      await page.selectOption('#sdSetOverlaySize', 'large');
      await expect(canvas).toHaveAttribute('style', /width:\s*108px/);
      await expect
        .poll(async () => (await visibilityOf(app, 'overlay.html'))?.visible)
        .toBe(true);

      await page.selectOption('#sdSetOverlayLabelPos', 'below');
      await expect(label).not.toHaveClass(/\bhidden\b/);
      await expect(overlay.locator('#overlayWrap')).toHaveClass(/pos-below/);

      await page.selectOption('#sdSetOverlayLabelPos', 'hidden');
      await expect(label).toHaveClass(/\bhidden\b/);

      // Leave the persisted appearance as this suite found it -- the setting is
      // written to userData and would otherwise leak into every later run.
      await page.selectOption('#sdSetOverlaySize', 'medium');
      await expect(canvas).toHaveAttribute('style', /width:\s*70px/);
    },
    screenshots: [{ name: 'settings-overlay-appearance-group' }],
  },
  {
    area: 'overlay-windows',
    ui: 'signal-desk-prod',
    name: 'review-overlay-renders-a-draft',
    kind: 'standard',
    description:
      'review:show creates the Review Deck window and pushes it a draft. The window renders the draft it was '
      + 'given rather than re-fetching one: the raw transcript, the editable final text, the draft-length summary, '
      + 'the recording duration, and the confidence meter driven by the same confidence->percent helpers the Talk '
      + 'workspace uses. #statusBadge reports the mapped overlay state and #ttsBackendBadge reports the real TTS '
      + 'backend rather than a hardcoded "Loading...". Every one of these is a live value, so a window that opened '
      + 'but never received its draft would show the "Waiting for draft" placeholder and fail here.',
    backendState: overlayBackendState(),
    async navigate(page, { app }) {
      await openReviewOverlay(page, app);
    },
    async expects(page, { app }) {
      const review = await auxiliaryWindow(app, 'review-overlay.html');
      await expect(review.locator('#rawText')).toHaveText(DRAFT.raw_text);
      await expect(review.locator('#finalText')).toHaveValue(DRAFT.final_text);
      await expect(review.locator('#draftSummary')).not.toBeEmpty();
      await expect(review.locator('#statusBadge')).toHaveText('Draft Pending');
      await expect(review.locator('#reviewConfidenceValue')).toHaveText('91%');
      await expect(review.locator('#reviewPersonaValue')).toHaveText('True Janitor');
      await expect(review.locator('#rawDuration')).toHaveText('00:12');
      await expect(review.locator('#ttsBackendBadge')).toHaveText('TTS: kokoro');

      // The raw transcript is collapsible, and the toggle keeps aria-expanded
      // honest rather than only changing a class.
      await expect(review.locator('#rawToggleButton')).toHaveAttribute('aria-expanded', 'true');
      await review.click('#rawToggleButton');
      await expect(review.locator('#rawToggleButton')).toHaveAttribute('aria-expanded', 'false');
      await expect(review.locator('#rawSection')).toHaveClass(/is-collapsed/);
    },
    screenshots: [
      {
        name: 'review-overlay-draft',
        of: async ({ app }) => auxiliaryWindow(app, 'review-overlay.html'),
      },
    ],
  },
  {
    area: 'overlay-windows',
    ui: 'signal-desk-prod',
    name: 'review-overlay-rewrite-instruct-and-read',
    kind: 'standard',
    description:
      'The Review Deck\'s action row is the reason the window exists, and each action is a distinct request rather '
      + 'than one generic one. #rewritePreset chooses the preset #changeButton sends to POST /drafts/:id/rewrite, so '
      + 'the captured request body is asserted -- a Revise that always sent "clearer" regardless of the select '
      + 'renders identically. #instructButton discloses #instructionRow, #runInstructionButton refuses an empty '
      + 'instruction locally instead of posting a blank custom rewrite, and a real instruction posts action '
      + '"custom" carrying that text. #readButton posts POST /drafts/:id/tts, flips itself to "Stop" while '
      + 'speaking, and the second press posts POST /tts/stop rather than starting a second read.',
    backendState: overlayBackendState(),
    async navigate(page, { app }) {
      await openReviewOverlay(page, app);
    },
    async expects(page, { app }) {
      const review = await auxiliaryWindow(app, 'review-overlay.html');

      // Revise with an explicitly chosen preset.
      await review.selectOption('#rewritePreset', 'shorter');
      await review.click('#changeButton');
      await expect(review.locator('#finalText')).toHaveValue(REWRITTEN.final_text);
      await expect(review.locator('#statusBadge')).toHaveText('Rewritten');
      // KNOWN ORDER DEPENDENCE (director, Wave 11B): this scenario passes
      // inside the full board and fails when its area is run alone -- the
      // capture is empty, i.e. the rewrite never posted, which means the
      // overlay is relying on state an earlier scenario left behind. The
      // handler itself is correct (review-overlay.html's runInstructionButton
      // refuses an empty instruction and posts action "custom" otherwise), so
      // this is a scenario-isolation defect, not a product one. Until it is
      // self-contained it is NOT counted as passing evidence and its ledger
      // rows stay blocked.
      await expect.poll(() => rewriteCalls.length, {
        message: 'the chosen preset must post exactly one rewrite',
      }).toBe(1);
      expect(rewriteCalls[0].id).toBe('7');
      expect(rewriteCalls[0].action).toBe('shorter');

      // Instruct: disclosed, guarded, then sent as a custom rewrite.
      await expect(review.locator('#instructionRow')).toBeHidden();
      await review.click('#instructButton');
      await expect(review.locator('#instructionRow')).toBeVisible();

      await review.click('#runInstructionButton');
      await expect(review.locator('#message')).toHaveText('Add an instruction first.');
      expect(rewriteCalls, 'empty instruction posted nothing').toHaveLength(1);

      await review.fill('#instructionText', 'Make it a question.');
      await review.click('#runInstructionButton');
      // Polled, not asserted flat: the click posts asynchronously, so a bare
      // length check races the request and fails against a correct handler.
      // The earlier flat checks are safe because each follows an awaited UI
      // assertion that the response had already driven.
      await expect.poll(() => rewriteCalls.length, {
        message: 'a real instruction must post a second, custom rewrite',
      }).toBe(2);
      expect(rewriteCalls[1].action).toBe('custom');
      expect(rewriteCalls[1].custom_instruction).toBe('Make it a question.');

      // Read, then stop. The button is its own state indicator.
      await expect(review.locator('#readButton')).toHaveText('Read');
      await review.click('#readButton');
      await expect(review.locator('#readButton')).toHaveText('Stop');
      await expect(review.locator('#statusBadge')).toHaveText('Speaking');
      expect(ttsCalls, 'one read').toHaveLength(1);
      expect(ttsCalls[0].id).toBe('7');

      await review.click('#readButton');
      expect(ttsStops, 'second press stopped rather than re-read').toHaveLength(1);
      expect(ttsCalls, 'second press did not start another read').toHaveLength(1);
    },
    screenshots: [
      {
        name: 'review-overlay-instruct-row',
        of: async ({ app }) => auxiliaryWindow(app, 'review-overlay.html'),
      },
    ],
  },
  {
    area: 'overlay-windows',
    ui: 'signal-desk-prod',
    name: 'review-overlay-dismissal-is-not-a-decision',
    kind: 'standard',
    description:
      'Both ways out of the Review Deck that are NOT a decision have to stay non-destructive, because the draft is '
      + 'the user\'s only copy of what they said. #closeButton hides the window and Escape hides the window, and '
      + 'neither posts POST /drafts/:id/decline -- Cancel is the only control that declines. This is asserted on '
      + 'the request capture and on the main process\'s own view of window visibility, not on a class: a window '
      + 'that "looks closed" while still being visible on top of everything is the exact bug this catches. Pushing '
      + 'a draft again re-shows the same window with the draft intact.',
    backendState: overlayBackendState(),
    async navigate(page, { app }) {
      await openReviewOverlay(page, app);
    },
    async expects(page, { app }) {
      const review = await auxiliaryWindow(app, 'review-overlay.html');

      await review.click('#closeButton');
      await expect
        .poll(async () => (await visibilityOf(app, 'review-overlay.html'))?.visible)
        .toBe(false);
      expect(declines, 'close is not a decline').toHaveLength(0);

      await openReviewOverlay(page, app);
      await expect
        .poll(async () => (await visibilityOf(app, 'review-overlay.html'))?.visible)
        .toBe(true);
      await expect(review.locator('#finalText')).toHaveValue(DRAFT.final_text);

      // Escape is a dismissal, deliberately not a decline (SPEC 5d).
      await review.locator('#finalText').press('Escape');
      await expect
        .poll(async () => (await visibilityOf(app, 'review-overlay.html'))?.visible)
        .toBe(false);
      expect(declines, 'Escape is not a decline').toHaveLength(0);
    },
    screenshots: [],
  },
];
