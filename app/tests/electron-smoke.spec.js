const { test, expect } = require('@playwright/test');
const { _electron: electron } = require('playwright');
const path = require('node:path');
const fs = require('node:fs');

test.describe('BetterFingers Electron App Tests', () => {
  let app;
  let window;

  test.beforeAll(async () => {
    // Launch Electron app
    app = await electron.launch({
      cwd: path.resolve(__dirname, '..'),
      args: ['.'],
      env: {
        ...process.env,
        BETTERFINGERS_PYTHON: 'python3', // Use system python3
      },
    });

    // Wait for the first window to open
    window = await app.firstWindow();
  });

  test.afterAll(async () => {
    // Close Electron app
    if (app) {
      await app.close();
    }
  });

  test('Launches and shows main dashboard header', async () => {
    await expect(window.locator('text=Backend Status Dashboard')).toBeVisible();
    await expect(window.locator('#backendStatus')).toBeVisible();
  });

  test('Backend transitions to active/ready state', async () => {
    // The backend should respond and transition to active
    const statusLocator = window.locator('#backendStatus');
    await expect(statusLocator).toHaveText(/ready|active|running/i, { timeout: 15000 });
  });

  test('Tab navigation switching works', async () => {
    // Check Dashboard content is visible initially
    await expect(window.locator('#tabDashboard')).toBeVisible();
    await expect(window.locator('#tabSettings')).not.toBeVisible();

    // Click Settings Tab
    await window.click('#tabButtonSettings');
    await expect(window.locator('#tabSettings')).toBeVisible();
    await expect(window.locator('#tabDashboard')).not.toBeVisible();

    // Click Models Tab
    await window.click('#tabButtonModels');
    await expect(window.locator('#tabModels')).toBeVisible();
    await expect(window.locator('#tabSettings')).not.toBeVisible();

    // Click Diagnostics Tab
    await window.click('#tabButtonDiagnostics');
    await expect(window.locator('#tabDiagnostics')).toBeVisible();
    await expect(window.locator('#tabModels')).not.toBeVisible();
  });

  test('Hotkey input records multiple keys together', async () => {
    // Navigate to settings tab
    await window.click('#tabButtonSettings');

    const hotkeyInput = window.locator('#settingHotkey');
    await hotkeyInput.focus();

    // Hold down F8, then 4, then t
    await window.keyboard.down('F8');
    await window.keyboard.down('4');
    await window.keyboard.down('t');

    // Input value should be F8+4+T
    await expect(hotkeyInput).toHaveValue('F8+4+T');

    // Release keys
    await window.keyboard.up('t');
    await window.keyboard.up('4');
    await window.keyboard.up('F8');

    // Unfocus to complete
    await hotkeyInput.blur();
  });

  test('Diagnostics & Doctor checkup displays subsystem health', async () => {
    // Switch to Diagnostics tab
    await window.click('#tabButtonDiagnostics');

    // Run Doctor Check
    await window.click('#refreshDoctorButton');

    // Wait for doctor cards to populate
    const cardsGrid = window.locator('#doctorCardsGrid');
    await expect(cardsGrid.locator('.doctor-card').first()).toBeVisible({ timeout: 10000 });

    // Verify critical cards are present (e.g. STT, LLM, TTS, Audio, Platform)
    const cardHeaders = await cardsGrid.locator('.doctor-card-header').allTextContents();
    console.log('Detected Doctor Subsystem headers:', cardHeaders);
    expect(cardHeaders.length).toBeGreaterThanOrEqual(4);

    // Verify sidecar console logs are rendered
    const logsTail = window.locator('#sidecarLogsTail');
    await expect(logsTail).not.toHaveText('Logs loading...');
    const logsText = await logsTail.textContent();
    expect(logsText).toContain('Checking backend port');
  });

  test('Capture screenshot of dashboard', async () => {
    // Go back to dashboard tab
    await window.click('#tabButtonDashboard');
    await window.screenshot({ path: 'artifacts/betterfingers-dashboard-verified.png' });
  });
});
