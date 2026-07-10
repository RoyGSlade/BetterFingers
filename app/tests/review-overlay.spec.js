const { test, expect } = require('@playwright/test');
const { _electron: electron } = require('playwright');
const path = require('node:path');
const { dismissOnboardingIfPresent } = require('./helpers/onboarding');

// The overlay opens from a mock draft (POST /drafts/test-mock) which needs no
// model, so structure/summary/cancel assertions run anywhere — including CI. The
// Read (TTS), Change and Instruct (LLM rewrite) tests need a live llama-server +
// TTS model on disk, which CI does not provision. Gate those behind an opt-in env
// flag so the model-free subset is CI-wireable; set BETTERFINGERS_E2E_MODEL=1 to
// run the full flow on a machine that has the model + sidecar. See DESIGN §10 (U1).
const MODEL_E2E = process.env.BETTERFINGERS_E2E_MODEL === '1';

test.describe('BetterFingers Review Overlay Tests', () => {
  let app;
  let mainWindow;
  let reviewWindow;

  test.beforeAll(async () => {
    // Launch Electron app
    app = await electron.launch({
      cwd: path.resolve(__dirname, '..'),
      args: ['.'],
      env: {
        ...process.env,
        BETTERFINGERS_PYTHON: process.env.BETTERFINGERS_PYTHON || 'python3',
      },
    });

    // Wait for the main window (index.html) to open and load
    const windows = app.windows();
    mainWindow = windows.find(w => w.url().includes('index.html'));
    if (!mainWindow) {
      mainWindow = await app.waitForEvent('window', {
        predicate: (w) => w.url().includes('index.html'),
        timeout: 20000,
      });
    }

    await mainWindow.waitForLoadState('domcontentloaded');
    await mainWindow.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
    await dismissOnboardingIfPresent(mainWindow);
    const statusLocator = mainWindow.locator('#backendStatus');
    await expect(statusLocator).toHaveText(/ready|active|running|external/i, { timeout: 15000 });

    // Wait for WebSocket stream connection to be fully connected
    const wsConnection = mainWindow.locator('#wsConnection');
    await expect(wsConnection).toHaveText(/connected/i, { timeout: 15000 });
  });

  test.afterAll(async () => {
    // Close Electron app
    if (app) {
      await app.close();
    }
  });

  test('Review overlay opens and displays correct elements when mock draft is triggered', async () => {
    // Trigger a mock draft via FastAPI endpoint
    const token = await mainWindow.evaluate(() => window.betterFingers.authToken);
    const response = await fetch('http://127.0.0.1:8000/drafts/test-mock', { 
      method: 'POST',
      headers: { 'Authorization': `Bearer ${token}` }
    });
    expect(response.ok).toBe(true);

    // Wait for review window to open
    reviewWindow = await app.waitForEvent('window', {
      predicate: (w) => w.url().includes('review-overlay.html'),
      timeout: 10000,
    });

    await reviewWindow.waitForLoadState('domcontentloaded');

    // Confirm state badge exists and shows 'Draft Pending'
    const statusBadge = reviewWindow.locator('#statusBadge');
    await expect(statusBadge).toBeVisible();
    await expect(statusBadge).toHaveText(/Draft Pending/i);

    // Confirm TTS backend badge exists
    const ttsBadge = reviewWindow.locator('#ttsBackendBadge');
    await expect(ttsBadge).toBeVisible();
    await expect(ttsBadge).toHaveText(/TTS:/i);

    // Confirm essential buttons exist
    await expect(reviewWindow.locator('#acceptButton')).toBeVisible();
    await expect(reviewWindow.locator('#changeButton')).toBeVisible();
    await expect(reviewWindow.locator('#instructButton')).toBeVisible();
    await expect(reviewWindow.locator('#readButton')).toBeVisible();
    await expect(reviewWindow.locator('#cancelButton')).toBeVisible();

    // Baseline screenshot of the review overlay for visual QA.
    await reviewWindow.screenshot({ path: 'artifacts/betterfingers-review-overlay.png' });
  });

  test('Draft summary shows the word count and updates live on edit', async () => {
    const summary = reviewWindow.locator('#draftSummary');
    await expect(summary).toBeVisible();
    // Mock draft final text is "Mock cleaned and polished output." -> 5 words.
    await expect(summary).toHaveText(/^5 words$/);

    // Editing the final text recomputes the count live...
    const finalText = reviewWindow.locator('#finalText');
    await finalText.fill('one two three');
    await expect(summary).toHaveText(/^3 words$/);

    // ...then restore the original so later tests see the unedited draft.
    await finalText.fill('Mock cleaned and polished output.');
    await expect(summary).toHaveText(/^5 words$/);
  });

  test('Read button calls TTS path and enters speaking state, then stop halts it', async () => {
    test.skip(!MODEL_E2E, 'Needs a live TTS model; set BETTERFINGERS_E2E_MODEL=1 to run.');
    const readButton = reviewWindow.locator('#readButton');
    const statusBadge = reviewWindow.locator('#statusBadge');

    // Click Read button
    await readButton.click();

    // The status badge should visibly change to 'Speaking'
    await expect(statusBadge).toHaveText(/Speaking/i);
    // The button text should change to 'Stop'
    await expect(readButton).toHaveText(/Stop/i);

    // Clicking Stop should halt TTS and return to pending/normal state
    await readButton.click();
    await expect(statusBadge).toHaveText(/Draft Pending/i);
    await expect(readButton).toHaveText(/Read/i);
  });

  test('Change button triggers rewrite and enters rewriting state', async () => {
    test.skip(!MODEL_E2E, 'Needs a live llama-server; set BETTERFINGERS_E2E_MODEL=1 to run.');
    const changeButton = reviewWindow.locator('#changeButton');
    const statusBadge = reviewWindow.locator('#statusBadge');

    // Click Change button
    await changeButton.click();

    // It should transiently enter 'Rewriting' or quickly complete to 'Rewritten'
    await expect(statusBadge).toHaveText(/Rewriting|Rewritten/i);
  });

  test('Instruct button toggles custom instruction row and typing run rewrite works', async () => {
    test.skip(!MODEL_E2E, 'Needs a live llama-server; set BETTERFINGERS_E2E_MODEL=1 to run.');
    const instructButton = reviewWindow.locator('#instructButton');
    const instructionRow = reviewWindow.locator('#instructionRow');
    const instructionText = reviewWindow.locator('#instructionText');
    const runInstructionButton = reviewWindow.locator('#runInstructionButton');
    const statusBadge = reviewWindow.locator('#statusBadge');

    // Verify initially hidden
    await expect(instructionRow).toHaveClass(/hidden/);

    // Click Instruct button to reveal it
    await instructButton.click();
    await expect(instructionRow).not.toHaveClass(/hidden/);

    // Type custom instruction
    await instructionText.fill('make it professional');

    // Click Rewrite
    await runInstructionButton.click();

    // Verify it moves to rewriting or rewritten state
    await expect(statusBadge).toHaveText(/Rewriting|Rewritten/i);
  });

  test('Cancel button hides overlay', async () => {
    const cancelButton = reviewWindow.locator('#cancelButton');
    
    // Click Cancel
    await cancelButton.click();

    // Verify Electron window is hidden
    let isVisible = true;
    for (let i = 0; i < 10; i++) {
      isVisible = await app.evaluate(({ BrowserWindow }) => {
        const win = BrowserWindow.getAllWindows().find(w => w.getTitle() === 'BetterFingers Review');
        return win ? win.isVisible() : false;
      });
      if (!isVisible) break;
      await new Promise(resolve => setTimeout(resolve, 300));
    }
    expect(isVisible).toBe(false);
  });

  test('Dashboard still functions normally after overlay closes', async () => {
    // Verify dashboard is still visible and responsive
    await expect(mainWindow.locator('.hero h1')).toHaveText('BetterFingers');
    
    // Check that we can navigate
    await mainWindow.click('#tabButtonSettings');
    await expect(mainWindow.locator('#tabSettings')).toBeVisible();
  });
});
