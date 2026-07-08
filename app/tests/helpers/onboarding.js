const { expect } = require('@playwright/test');

// First-run onboarding shows on any fresh user-data-dir profile (see
// ONBOARDING_FLAG in src/renderer/main.js) and blocks all pointer events
// until dismissed. Step through it so specs can interact with the app.
async function dismissOnboardingIfPresent(window) {
  const overlay = window.locator('#onboardingOverlay');
  if (!(await overlay.isVisible().catch(() => false))) return;

  const consent = window.locator('#onboardingConsent');
  const nextButton = window.locator('#onboardingNextButton');

  for (let i = 0; i < 6; i += 1) {
    if (!(await overlay.isVisible().catch(() => false))) return;
    if (await consent.isVisible().catch(() => false)) {
      await consent.check();
    }
    await nextButton.click();
  }

  await expect(overlay).toBeHidden({ timeout: 5000 });
}

module.exports = { dismissOnboardingIfPresent };
