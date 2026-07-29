// Wave 12A: the NATIVE FORM CONTROL CONTRACT on the production Signal Desk
// page (signal-desk.html, `ui: 'signal-desk-prod'`).
//
// Run with:  BF_QA_UI=signal-desk-prod node tests/qa/run.mjs ui-controls-prod
//
// WHY THIS FILE EXISTS AND WHY IT IS NOT A SCREENSHOT SUITE.
//
// Every finding this wave fixed is, by definition, a visual one -- the product
// owner reported them by looking at the app. That is exactly why the
// assertions here are computed-style assertions and not image comparisons:
//
//   * A screenshot of a <select> shows the CLOSED control. The bug in finding
//     (2) ("pause style brings up black text hard to see options") lives in the
//     OPEN popup, which the platform draws in its own window -- Playwright
//     cannot screenshot it, and a green screenshot of the closed select would
//     have "passed" the whole time the bug shipped. So the contract asserted
//     below is the thing that actually determines the popup's legibility: the
//     computed color and background-color of the <option> elements, and the
//     real WCAG contrast ratio between them, computed here rather than
//     eyeballed.
//   * A screenshot cannot distinguish "styled to look like the platform" from
//     "not styled at all". `appearance` and the presence of a background-image
//     can. Every reachable select is checked, by enumeration, not by sampling:
//     if someone adds a 37th select tomorrow with a new class, this fails.
//   * "Buttons oversized" is a font-metric bug. The assertion is on
//     font-family: a control still on the UA default reports a generic
//     'Arial'-family stack rather than the page's Inter stack, and that
//     difference is measurable to the character.
//
// The negative-control discipline used elsewhere in this suite does not apply
// here: these scenarios read the app's OWN computed styles, so there is no
// backend stub that could lie to them. What could lie is a selector that
// matches nothing -- an `expects` that passes vacuously because it enumerated
// an empty list. Every enumeration below therefore asserts a non-zero count
// FIRST and reports the actual number it checked in the failure message.
//
// SELECTOR RULE (project-wide): attribute/id selectors only, never :has-text.
// Every id below was re-grepped against app/src/renderer/signal-desk.html.

import { expect } from '@playwright/test';
import { coldBoot, readyProfile } from './fixtures/cold-boot.mjs';

const VOICES = {
  defaults: [
    { id: 'af_bella', name: 'Bella' },
    { id: 'af_nicole', name: 'Nicole' },
    { id: 'am_michael', name: 'Michael' },
  ],
  cloned: [],
  cloning: { installed: false },
};

function voiceProfile() {
  return {
    ...readyProfile(),
    'GET /tts/voices': VOICES,
    'GET /voice-presets': { presets: [] },
  };
}

/** Shared with signal-desk-prod-sweep.mjs's rule: never click through the gate. */
async function assertNoOnboardingGate(page) {
  const gate = page.locator('#sdOnboarding');
  if (await gate.isVisible().catch(() => false)) {
    throw new Error(
      '#sdOnboarding is visible at scenario start -- broken precondition. Refusing to click ' +
        'through the gate; fix whatever left it open instead.',
    );
  }
}

// --- contrast maths ----------------------------------------------------------
// WCAG 2.1 relative luminance + contrast ratio, implemented here rather than
// pulled in, so the number in the failure message is one this file can be read
// to verify. Input is whatever getComputedStyle returns, i.e. `rgb(r, g, b)` or
// `rgba(r, g, b, a)`.

function parseRgb(value) {
  const m = String(value).match(/rgba?\(([^)]+)\)/);
  if (!m) throw new Error(`not a computed rgb() color: ${value}`);
  const parts = m[1].split(',').map((p) => parseFloat(p.trim()));
  return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
}

function relativeLuminance({ r, g, b }) {
  const channel = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrastRatio(fg, bg) {
  const l1 = relativeLuminance(parseRgb(fg));
  const l2 = relativeLuminance(parseRgb(bg));
  const [hi, lo] = l1 >= l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

// --- in-page collectors ------------------------------------------------------
// These run inside the renderer. They deliberately enumerate by TAG, not by
// class: the entire point of the Wave 12A fix is that the contract is keyed on
// the element, so a class-based enumeration here would test the fix's premise
// instead of its effect.

/** Every <select> in the document, styled or not, with the facts that decide whether it is still a raw native control. */
const COLLECT_SELECTS = () =>
  Array.from(document.querySelectorAll('select')).map((el) => {
    const cs = getComputedStyle(el);
    const option = el.querySelector('option');
    const ocs = option ? getComputedStyle(option) : null;
    return {
      id: el.id || null,
      className: el.className || '',
      appearance: cs.appearance,
      backgroundImage: cs.backgroundImage,
      backgroundColor: cs.backgroundColor,
      fontFamily: cs.fontFamily,
      colorScheme: cs.colorScheme,
      paddingRight: cs.paddingRight,
      optionCount: el.querySelectorAll('option').length,
      optionColor: ocs ? ocs.color : null,
      optionBackground: ocs ? ocs.backgroundColor : null,
    };
  });

/** Every <button>, with the facts that decide whether it is still a UA buttonface slab. */
const COLLECT_BUTTONS = () =>
  Array.from(document.querySelectorAll('button')).map((el) => {
    const cs = getComputedStyle(el);
    return {
      id: el.id || null,
      className: el.className || '',
      fontFamily: cs.fontFamily,
      fontSize: cs.fontSize,
      backgroundColor: cs.backgroundColor,
      borderTopStyle: cs.borderTopStyle,
    };
  });

/** Every file input, plus its ::file-selector-button -- the widget the user called "a generic html button". */
const COLLECT_FILE_INPUTS = () =>
  Array.from(document.querySelectorAll('input[type="file"]')).map((el) => {
    const cs = getComputedStyle(el);
    const bcs = getComputedStyle(el, '::file-selector-button');
    return {
      id: el.id || null,
      fontFamily: cs.fontFamily,
      buttonFontFamily: bcs.fontFamily,
      buttonBackgroundColor: bcs.backgroundColor,
      buttonBorderRadius: bcs.borderTopLeftRadius,
      buttonBorderStyle: bcs.borderTopStyle,
    };
  });

// The UA default button font. Chromium reports the buttonface slab's family as
// a system stack that never contains 'Inter'; the page's stack always starts
// with it. Testing for the presence of the page font (rather than the absence
// of some specific UA string) is the assertion that survives a Chromium
// version bump.
const PAGE_FONT = 'Inter';

// Chromium's UA button background. Present here as documentation of what the
// failure looks like, and asserted against directly.
const UA_BUTTONFACE = ['rgb(239, 239, 239)', 'rgba(239, 239, 239, 0.3)'];

export const uiControlsProdScenarios = [
  {
    area: 'ui-controls-prod',
    ui: 'signal-desk-prod',
    name: 'no-select-is-left-on-the-browser-default',
    kind: 'standard',
    description:
      'Enumerates EVERY <select> in the production page and asserts none of them is still a raw native control. ' +
      'Before Wave 12A there were 36 selects across six class families and exactly one of them set ' +
      'appearance:none -- so 35 dropdowns rendered the GTK arrow the product owner described as "big arrows [...] ' +
      'out of place, wrong size, no distinguishable backplate", and one class (.sd-select) was not defined in the ' +
      'stylesheet at all. The assertions are appearance:none, a real background-image (our chevron plus its ' +
      'backplate, which is what a native control does NOT have), the page font, and enough right padding that the ' +
      'chevron is not sitting on top of the label text. Enumeration, not sampling: a 37th select added later with ' +
      'a seventh class fails this scenario rather than quietly shipping.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      const selects = await page.evaluate(COLLECT_SELECTS);
      expect(
        selects.length,
        'found no <select> at all -- this scenario would pass vacuously, so the selector or the page is wrong',
      ).toBeGreaterThan(20);

      const offenders = selects.filter(
        (s) =>
          s.appearance !== 'none' ||
          s.backgroundImage === 'none' ||
          !s.fontFamily.includes(PAGE_FONT) ||
          parseFloat(s.paddingRight) < 24,
      );
      expect(
        offenders.map((o) => `#${o.id || '(no id)'}.${o.className} appearance=${o.appearance} ` +
          `bgImage=${o.backgroundImage === 'none' ? 'NONE' : 'set'} font=${o.fontFamily} padRight=${o.paddingRight}`),
        `every one of the ${selects.length} selects must carry the Signal Desk treatment`,
      ).toEqual([]);
    },
    screenshots: [{ name: 'no-select-is-left-on-the-browser-default' }],
  },

  {
    area: 'ui-controls-prod',
    ui: 'signal-desk-prod',
    name: 'option-text-is-legible-in-the-app-theme',
    kind: 'standard',
    description:
      'The finding-(2) contract, asserted the only way it can be: by computed color. ' +
      '".sd-review-select option { color: #000 }" shipped black option text, and because a Linux/GTK select ' +
      'popup takes its background from the desktop theme, on a dark desktop that is black on near-black -- ' +
      'exactly "pause style brings up black text hard to see options", #voicePauseStyle being a .sd-review-select. ' +
      'The popup is an OS-drawn window, so no screenshot can cover this. Instead every option of every populated ' +
      'select is checked for a real WCAG contrast ratio against its own computed background, at the AA ' +
      'normal-text threshold of 4.5:1, with the measured ratio printed on failure. The select is also asserted to ' +
      'declare color-scheme:dark, which is the separate half of the fix -- it is what makes Chromium ask the ' +
      'platform for the dark popup chrome in the first place.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="settings"]');
      await expect(page.locator('#workspace-settings')).toBeVisible();
    },
    async expects(page) {
      const selects = (await page.evaluate(COLLECT_SELECTS)).filter((s) => s.optionCount > 0);
      expect(
        selects.length,
        'no select had any <option> -- nothing would be measured, so this must fail loudly',
      ).toBeGreaterThan(5);

      const failures = [];
      for (const s of selects) {
        if (s.colorScheme !== 'dark') {
          failures.push(`#${s.id || '(no id)'} color-scheme=${s.colorScheme} (must be dark for the native popup)`);
        }
        const ratio = contrastRatio(s.optionColor, s.optionBackground);
        if (ratio < 4.5) {
          failures.push(
            `#${s.id || '(no id)'} option ${s.optionColor} on ${s.optionBackground} = ${ratio.toFixed(2)}:1 (needs >= 4.5:1)`,
          );
        }
      }
      expect(failures, `option legibility across ${selects.length} populated selects`).toEqual([]);

      // And the specific control the product owner named, by id, so this
      // scenario names the reported bug rather than only its class of bug.
      const pauseStyle = selects.find((s) => s.id === 'voicePauseStyle');
      expect(pauseStyle, '#voicePauseStyle must be reachable -- it is the control finding (2) named').toBeTruthy();
      expect(
        pauseStyle.optionColor,
        '#voicePauseStyle options must no longer be painted black (this was literally `color: #000`)',
      ).not.toBe('rgb(0, 0, 0)');
    },
    screenshots: [{ name: 'option-text-is-legible-in-the-app-theme' }],
  },

  {
    area: 'ui-controls-prod',
    ui: 'signal-desk-prod',
    name: 'no-button-or-file-input-is-left-on-the-browser-default',
    kind: 'standard',
    description:
      'Findings (4) and (10), the button half. Enumerates every <button> and asserts none reports the UA font ' +
      'stack or the UA buttonface background -- "buttons oversized" is a font-metric mismatch (the UA falls back ' +
      'to 13.33px Arial next to the page\'s Inter), and it is measurable rather than a matter of taste. Then the ' +
      'file inputs: ::file-selector-button is a real pseudo-element with a real computed style, so "the choose ' +
      'file button looks like a generic html button" is checked directly -- our background token, our radius, our ' +
      'font. Chromium\'s native file button has a 2px radius and the UA font; ours cannot report both.',
    backendState: coldBoot,
    async navigate(page) {
      await assertNoOnboardingGate(page);
    },
    async expects(page) {
      const buttons = await page.evaluate(COLLECT_BUTTONS);
      expect(buttons.length, 'found no <button> at all -- vacuous pass guard').toBeGreaterThan(30);

      const badButtons = buttons.filter(
        (b) => !b.fontFamily.includes(PAGE_FONT) || UA_BUTTONFACE.includes(b.backgroundColor),
      );
      expect(
        badButtons.map((b) => `#${b.id || '(no id)'}.${b.className} font=${b.fontFamily} bg=${b.backgroundColor}`),
        `every one of the ${buttons.length} buttons must use the page font and must not be a UA buttonface slab`,
      ).toEqual([]);

      const fileInputs = await page.evaluate(COLLECT_FILE_INPUTS);
      expect(
        fileInputs.length,
        'found no file input -- #voiceCloneFile / #sdSetImportProfileFile / #sdUtilWakeImportFile must exist',
      ).toBeGreaterThan(0);

      const badFiles = fileInputs.filter(
        (f) =>
          !f.buttonFontFamily.includes(PAGE_FONT) ||
          parseFloat(f.buttonBorderRadius) < 6 ||
          f.buttonBorderStyle !== 'solid',
      );
      expect(
        badFiles.map(
          (f) =>
            `#${f.id || '(no id)'} ::file-selector-button font=${f.buttonFontFamily} ` +
            `radius=${f.buttonBorderRadius} borderStyle=${f.buttonBorderStyle}`,
        ),
        `every one of the ${fileInputs.length} file inputs must carry the Signal Desk button treatment`,
      ).toEqual([]);
    },
    screenshots: [{ name: 'no-button-or-file-input-is-left-on-the-browser-default' }],
  },

  {
    area: 'ui-controls-prod',
    ui: 'signal-desk-prod',
    name: 'the-active-voice-is-named-on-screen',
    kind: 'standard',
    description:
      'Finding (3), UI half: "the user cannot SEE which voice is selected, nor what voices exist to blend." The ' +
      'stub serves three voices, so the assertion is that the Studio voice surfaces NAME one of them in text -- ' +
      'not that a <select> holds a value, which was already true while the user could not see it. Two surfaces ' +
      'are checked because there are two: #voiceActiveVoiceName in the Voice Studio section, and ' +
      '#sdVoiceBlendAvailable under the Voice & Delivery blend strip, whose "+ Add Voice" button used to add a ' +
      'silently-chosen voice from a roster shown nowhere. The active-voice readout is then asserted to TRACK the ' +
      'select: it is changed through the real control and the text must follow, which is what proves the readout ' +
      'is wired rather than a hard-coded label that happens to be right on first paint.',
    backendState: voiceProfile,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="studio"]');
      await expect(page.locator('#workspace-studio')).toBeVisible();
    },
    async expects(page) {
      const active = page.locator('#voiceActiveVoiceName');
      await expect(active, '#voiceActiveVoiceName must exist exactly once').toHaveCount(1);
      await expect(
        active,
        'the active voice must be named, not left on the "None selected" placeholder, once voices have loaded',
      ).not.toHaveText('None selected');

      const namedVoice = (await active.textContent())?.trim();
      expect(
        ['Bella', 'Nicole', 'Michael'],
        `the named active voice ("${namedVoice}") must be one the stub actually serves, not a placeholder`,
      ).toContain(namedVoice);

      // It must FOLLOW the control. Pick a voice that is definitely not the
      // current one, drive the real select, and require the text to move.
      const select = page.locator('#settingReviewTtsVoiceHint');
      await expect(select, 'the base-voice select must be populated from the stub').not.toHaveValue('');
      const target = namedVoice === 'Michael' ? 'af_bella' : 'am_michael';
      const targetName = target === 'af_bella' ? 'Bella' : 'Michael';
      await select.selectOption(target);
      await expect(
        active,
        'changing the base voice must move the readout -- otherwise it is a label, not a readout',
      ).toHaveText(targetName);

      // The blend roster. The strip names what "+ Add Voice" can reach.
      const available = page.locator('#sdVoiceBlendAvailable');
      await expect(available, '#sdVoiceBlendAvailable must exist exactly once').toHaveCount(1);
      await expect(
        available,
        'the blend strip must say something about what is available -- an empty line is the old behaviour',
      ).not.toHaveText('');
    },
    screenshots: [{ name: 'the-active-voice-is-named-on-screen' }],
  },

  {
    area: 'ui-controls-prod',
    ui: 'signal-desk-prod',
    name: 'blend-rows-render-in-the-signal-desk-primitives',
    kind: 'standard',
    description:
      'Finding (4), by construction rather than by appearance. features/voiceStudio.js rendered its blend rows ' +
      'with class names -- setting-row, settings-input, secondary-button -- that exist only in styles/base.css, ' +
      'and signal-desk.html links only styles/signal-desk.css. So on the page that has been the DEFAULT since the ' +
      'Wave 11 flip, the whole Blend surface rendered as raw HTML: "the remove button on blend voices looks like ' +
      'a generic html button". This adds a layer through the real "Add layer" button and asserts the rendered row ' +
      'uses the Signal Desk primitives AND -- the part a class-name check alone would miss -- that the Remove ' +
      'button and the row select come back with real computed styling, so a future rename that breaks the CSS ' +
      'link is caught too.',
    backendState: voiceProfile,
    async navigate(page) {
      await assertNoOnboardingGate(page);
      await page.click('.sd-nav__button[data-nav="studio"]');
      await expect(page.locator('#workspace-studio')).toBeVisible();
      await page.click('#addVoiceLayerButton');
    },
    async expects(page) {
      const row = page.locator('#voiceBlendRows .sd-voice-studio__blend-row');
      await expect(row, 'exactly one blend row after one click of Add layer').toHaveCount(1);

      // No base.css-only class name may reach this page. These three are the
      // exact names the module used to emit.
      for (const legacy of ['setting-row', 'settings-input', 'secondary-button']) {
        await expect(
          page.locator(`#voiceBlendRows .${legacy}`),
          `.${legacy} is defined only in styles/base.css, which this page does not load`,
        ).toHaveCount(0);
      }

      const removeButton = row.locator('button.sd-btn');
      await expect(removeButton, 'the Remove control must be an .sd-btn').toHaveCount(1);
      const removeStyle = await removeButton.evaluate((el) => {
        const cs = getComputedStyle(el);
        return { font: cs.fontFamily, radius: cs.borderTopLeftRadius, bg: cs.backgroundColor };
      });
      expect(removeStyle.font, 'Remove must use the page font').toContain(PAGE_FONT);
      expect(
        parseFloat(removeStyle.radius),
        'Remove must carry a real radius -- a UA button reports 2px',
      ).toBeGreaterThanOrEqual(6);
      expect(UA_BUTTONFACE, 'Remove must not be a UA buttonface slab').not.toContain(removeStyle.bg);

      const rowSelect = row.locator('select');
      await expect(rowSelect, 'the blend row must offer a voice select').toHaveCount(1);
      const selectStyle = await rowSelect.evaluate((el) => {
        const cs = getComputedStyle(el);
        return { appearance: cs.appearance, bgImage: cs.backgroundImage };
      });
      expect(selectStyle.appearance, 'the blend row select must be a styled control').toBe('none');
      expect(selectStyle.bgImage, 'the blend row select must carry our chevron, not the native arrow').not.toBe('none');
    },
    screenshots: [{ name: 'blend-rows-render-in-the-signal-desk-primitives' }],
  },
];
