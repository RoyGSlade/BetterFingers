const { test, expect } = require('@playwright/test');
const { _electron: electron } = require('playwright');
const path = require('node:path');

test.describe('BetterFingers Electron App Tests', () => {
  let app;
  let window;

  test.beforeAll(async () => {
    // Inherit the parent env but strip the vars that make Electron start as a
    // plain Node process (ELECTRON_RUN_AS_NODE) instead of opening a window.
    // A shell that has one exported — common under some test runners/CI — would
    // otherwise silently break the launch with no window ever appearing.
    const launchEnv = { ...process.env };
    delete launchEnv.ELECTRON_RUN_AS_NODE;
    delete launchEnv.ELECTRON_NO_ATTACH_CONSOLE;
    launchEnv.BETTERFINGERS_PYTHON = launchEnv.BETTERFINGERS_PYTHON || 'python3'; // Use system python3

    // Launch Electron app
    app = await electron.launch({
      cwd: path.resolve(__dirname, '..'),
      args: ['.'],
      env: launchEnv,
    });

    // Wait for the main window (index.html) to open and load
    const windows = app.windows();
    window = windows.find(w => w.url().includes('index.html'));
    if (!window) {
      window = await app.waitForEvent('window', {
        predicate: (w) => w.url().includes('index.html'),
        timeout: 20000,
      });
    }

    await window.waitForLoadState('domcontentloaded');
    await window.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });

    // On a clean profile the first-run onboarding overlay is modal and blocks
    // the tab/settings clicks these tests perform. Mark onboarding complete and
    // reload so every test below runs against the dismissed dashboard.
    await window.addInitScript(() => {
      try { localStorage.setItem('bf_onboarding_complete', 'true'); } catch (_e) {}
    });
    await window.reload();
    await window.waitForLoadState('domcontentloaded');
    await window.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });
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
    const statusLocator = window.locator('#backendStatus');
    await expect(statusLocator).toHaveText(/ready|active|running|external/i, { timeout: 15000 });
  });

  test('Tab navigation switching works', async () => {
    await expect(window.locator('#tabDashboard')).toBeVisible();
    await expect(window.locator('#tabSettings')).not.toBeVisible();

    await window.click('#tabButtonSettings');
    await expect(window.locator('#tabSettings')).toBeVisible();
    await expect(window.locator('#tabDashboard')).not.toBeVisible();

    await window.click('#tabButtonModels');
    await expect(window.locator('#tabModels')).toBeVisible();
    await expect(window.locator('#tabSettings')).not.toBeVisible();

    await window.click('#tabButtonDiagnostics');
    await expect(window.locator('#tabDiagnostics')).toBeVisible();
    await expect(window.locator('#tabModels')).not.toBeVisible();
  });

  test('Settings page renders and category switching works', async () => {
    await window.click('#tabButtonSettings');

    // Verify a couple of nav buttons are visible
    const generalNavBtn = window.locator('.settings-nav-button[data-section="general"]');
    const recordingNavBtn = window.locator('.settings-nav-button[data-section="recording"]');
    await expect(generalNavBtn).toBeVisible();
    await expect(recordingNavBtn).toBeVisible();

    // General section is active by default
    await expect(window.locator('.settings-section[data-section="general"]')).toHaveClass(/active/);
    await expect(window.locator('.settings-section[data-section="recording"]')).toHaveClass(/hidden/);

    // Switch to Recording section
    await recordingNavBtn.click();
    await expect(window.locator('.settings-section[data-section="recording"]')).toHaveClass(/active/);
    await expect(window.locator('.settings-section[data-section="general"]')).toHaveClass(/hidden/);
  });

  test('Search filters rows', async () => {
    await window.click('#tabButtonSettings');
    const searchInput = window.locator('#settingsSearchInput');
    await expect(searchInput).toBeVisible();

    // Query a specific settings row
    await searchInput.fill('instant typing');
    
    // Search Results header should appear
    await expect(window.locator('#settingsSearchHeader')).toBeVisible();

    // Instant Typing row should be visible
    const instantTypingRow = window.locator('.setting-row:has-text("Instant Typing")');
    await expect(instantTypingRow).toBeVisible();

    // Non-matching row should be hidden
    const whisperChunkRow = window.locator('.setting-row:has-text("Whisper Chunk Size")');
    await expect(whisperChunkRow).not.toBeVisible();

    // Clear search
    await searchInput.fill('');
    await expect(window.locator('#settingsSearchHeader')).toHaveClass(/hidden/);
  });

  test('Invalid token limit blocks save', async () => {
    await window.click('#tabButtonSettings');
    
    // Go to AI Cleanup section where Output Token Limit is located
    await window.click('.settings-nav-button[data-section="ai-cleanup"]');
    
    const tokenLimitInput = window.locator('#settingOutputTokenLimit');
    await expect(tokenLimitInput).toBeVisible();

    // Fill with invalid value (allowed range: 900 - 1200)
    await tokenLimitInput.fill('800');
    
    // Check that Save button is disabled
    const saveButton = window.locator('#saveProfileButton');
    await expect(saveButton).toBeDisabled();

    // Restore to a valid value
    await tokenLimitInput.fill('1000');
  });

  test('Duplicate hotkey blocks save', async () => {
    await window.click('#tabButtonSettings');
    await window.click('.settings-nav-button[data-section="hotkeys"]');

    const hotkeyInput = window.locator('#settingHotkey');
    const forceStopInput = window.locator('#settingForceStopKey');
    
    // Clear and set both to the same key combination
    await hotkeyInput.click();
    await hotkeyInput.focus();
    await window.keyboard.press('Control+Shift+H');
    await hotkeyInput.blur();

    await forceStopInput.click();
    await forceStopInput.focus();
    await window.keyboard.press('Control+Shift+H');
    await forceStopInput.blur();

    // Save button should be disabled due to collision validation error
    const saveButton = window.locator('#saveProfileButton');
    await expect(saveButton).toBeDisabled();

    // Restore different values using clear button
    await window.click('.setting-row:has(#settingForceStopKey) .clear-hotkey-btn');
  });

  test('Dirty-state appears and discard hides dirty state', async () => {
    await window.click('#tabButtonSettings');
    await window.click('.settings-nav-button[data-section="ai-cleanup"]');

    const tokenLimitInput = window.locator('#settingOutputTokenLimit');
    
    // Make a change
    await tokenLimitInput.fill('1050');

    // Unsaved changes bar (settingsSaveBar) should become visible
    const saveBar = window.locator('#settingsSaveBar');
    await expect(saveBar).toHaveClass(/visible/);

    // Click Discard
    await window.click('#discardProfileChangesButton');
    
    // Save bar should be hidden again
    await expect(saveBar).toHaveClass(/hidden/);
  });

  test('Appearance controls persist', async () => {
    await window.click('#tabButtonSettings');
    await window.click('.settings-nav-button[data-section="appearance"]');

    const themeSelect = window.locator('#settingTheme');
    const accentSelect = window.locator('#settingAccentColor');
    const densitySelect = window.locator('#settingDensity');
    const fontSizeSelect = window.locator('#settingFontSize');
    const highContrastCheckbox = window.locator('#settingHighContrast');

    // Change value states
    await themeSelect.selectOption('dark');
    await accentSelect.selectOption('purple');
    await densitySelect.selectOption('compact');
    await fontSizeSelect.selectOption('large');
    
    const isChecked = await highContrastCheckbox.isChecked();
    await window.click('.setting-row:has(#settingHighContrast) .custom-switch-slider');

    // Reload page to verify persistence via localStorage
    await window.reload();
    await window.waitForLoadState('domcontentloaded');
    await window.waitForSelector('#backendStatus', { state: 'attached', timeout: 15000 });

    await window.click('#tabButtonSettings');
    await window.click('.settings-nav-button[data-section="appearance"]');

    // Verify after reload that they are set
    await expect(themeSelect).toHaveValue('dark');
    await expect(accentSelect).toHaveValue('purple');
    await expect(densitySelect).toHaveValue('compact');
    await expect(fontSizeSelect).toHaveValue('large');
    await expect(highContrastCheckbox).toBeChecked({ checked: !isChecked });
  });

  test('Diagnostics & Doctor checkup displays subsystem health', async () => {
    await window.click('#tabButtonDiagnostics');
    await window.click('#refreshDoctorButton');

    // Wait for doctor cards to populate
    const cardsGrid = window.locator('#doctorCardsGrid');
    await expect(cardsGrid.locator('.doctor-card').first()).toBeVisible({ timeout: 15000 });

    const cardHeaders = await cardsGrid.locator('.doctor-card-header').allTextContents();
    expect(cardHeaders.length).toBeGreaterThanOrEqual(4);

    // Verify sidecar console logs are rendered
    const logsTail = window.locator('#sidecarLogsTail');
    await expect(logsTail).not.toHaveText('Logs loading...');
    const logsText = await logsTail.textContent();
    expect(logsText).toContain('Checking backend port');
  });

  test('Hotkey input records multiple keys together', async () => {
    await window.click('#tabButtonSettings');
    await window.click('.settings-nav-button[data-section="hotkeys"]');

    const hotkeyInput = window.locator('#settingHotkey');
    await hotkeyInput.click();
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

    await hotkeyInput.blur();
  });

  test('Capture screenshot of dashboard', async () => {
    await window.click('#tabButtonDashboard');
    await window.screenshot({ path: 'artifacts/betterfingers-dashboard-verified.png' });
  });
});
