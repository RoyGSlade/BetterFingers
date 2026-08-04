const { test, expect } = require('@playwright/test');
const { _electron: electron } = require('playwright');
const path = require('node:path');

const SHIPPING_ROUTE = 'signal-desk.html';

test.describe('BetterFingers Electron production smoke', () => {
  let app;
  let window;

  test.beforeAll(async () => {
    // Keep Electron from inheriting shell flags that turn it into a plain Node
    // process instead of opening the application window.
    const launchEnv = { ...process.env };
    delete launchEnv.ELECTRON_RUN_AS_NODE;
    delete launchEnv.ELECTRON_NO_ATTACH_CONSOLE;
    launchEnv.BETTERFINGERS_PYTHON = launchEnv.BETTERFINGERS_PYTHON || 'python3';

    app = await electron.launch({
      cwd: path.resolve(__dirname, '..'),
      args: ['.'],
      env: launchEnv,
    });

    const shippingWindow = (candidate) => candidate.url().includes(SHIPPING_ROUTE);
    window = app.windows().find(shippingWindow);
    if (!window) {
      window = await app.waitForEvent('window', {
        predicate: shippingWindow,
        timeout: 20000,
      });
    }

    await window.waitForLoadState('domcontentloaded');
    await expect(window).toHaveURL(new RegExp(`${SHIPPING_ROUTE}$`));

    // The production onboarding flow is covered by its own scenarios. Seed
    // the documented completion flag here so this smoke remains model-free and
    // can exercise the production shell without a first-run modal blocking it.
    await window.addInitScript(() => {
      try { localStorage.setItem('bf_onboarding_complete', 'true'); } catch (_error) {}
    });
    await window.reload();
    await window.waitForLoadState('domcontentloaded');
    await expect(window.locator('#sdShell')).toBeVisible();
    await expect(window.locator('#sdOnboarding')).toBeHidden();
  });

  test.afterAll(async () => {
    if (app) await app.close();
  });

  test('opens the shipping Signal Desk route with production status surfaces', async () => {
    await expect(window).toHaveURL(new RegExp(`${SHIPPING_ROUTE}$`));
    await expect(window.locator('#sdHeaderTitle')).toHaveText('TALK');
    await expect(window.locator('#sdStatusBackendValue')).toBeVisible();
    await expect(window.locator('#sdStatusStreamValue')).toBeVisible();
    await expect(window.locator('#sdCaptureStartButton')).toBeVisible();
  });

  test('switches between stable production workspace selectors', async () => {
    const settingsNav = window.locator('.sd-nav__button[data-nav="settings"]');
    const talkNav = window.locator('.sd-nav__button[data-nav="talk"]');

    await expect(talkNav).toHaveAttribute('aria-current', 'page');
    await expect(window.locator('#workspace-talk')).toBeVisible();

    await settingsNav.click();
    await expect(settingsNav).toHaveAttribute('aria-current', 'page');
    await expect(window.locator('#workspace-settings')).toBeVisible();
    await expect(window.locator('#workspace-talk')).toBeHidden();

    await talkNav.click();
    await expect(talkNav).toHaveAttribute('aria-current', 'page');
    await expect(window.locator('#workspace-talk')).toBeVisible();
  });
});
