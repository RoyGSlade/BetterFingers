// Consent flow against durable onboarding state (Wave 1 Objective B, part 2).
//
// The consequential rules:
//   - Consent is fail-closed. Any uncertainty -- a missing bridge, a throwing
//     bridge.getState(), a malformed durable state -- shows the gate. It is
//     never acceptable to read an error or an unrecognized shape as "already
//     consented".
//   - Acceptance is only ever recorded once the durable write (bridge.accept)
//     confirms success. A failed or throwing write must not let the caller
//     believe the user is consented -- accept() reports {ok:false} and the
//     gate stays up.
//   - Declining always quits the app. There is no "dismiss" for a legal gate:
//     a user who does not consent does not get to sit in the running app.
//
// The durable store itself lives in the main process (src/main/onboardingStore.js,
// owned by a sibling worker) and is reached only through the injected `bridge`
// -- this module never imports it directly, so it stays testable with a fake
// bridge, and the real preload/ipc wiring can be added later without touching
// this file.

const CURRENT_CONSENT_VERSION = 1;
const LEGACY_FLAG = 'bf_onboarding_complete';

/**
 * True unless durable state records acceptance at >= consentVersion. A
 * missing/null/malformed state (or one whose consent_version doesn't parse
 * to a number) reads as needing consent -- NaN comparisons are false, so a
 * garbage version falls through to "needs consent" on its own.
 */
export function needsConsent(state, consentVersion = CURRENT_CONSENT_VERSION) {
  return !(state?.accepted === true && Number(state.consent_version) >= consentVersion);
}

/**
 * The first-launch gate decision. Reads durable state, and -- only when that
 * state has never recorded acceptance -- makes a single attempt at migrating
 * the legacy renderer-local flag so a returning user isn't re-prompted just
 * because the durable store is new. Never throws: every failure mode (no
 * bridge, a throwing bridge, a throwing storage) resolves to show:true.
 *
 * @returns {Promise<{show: boolean, state: object|null, migrated: boolean, reason: string}>}
 *   reason is one of 'no_state' | 'accepted' | 'consent_version_bumped' |
 *   'migrated' | 'bridge_unavailable'.
 */
export async function resolveOnboardingGate({ bridge, storage, consentVersion = CURRENT_CONSENT_VERSION } = {}) {
  if (!bridge) {
    return { show: true, state: null, migrated: false, reason: 'bridge_unavailable' };
  }

  let state = null;
  try {
    state = await bridge.getState();
  } catch (_e) {
    state = null;
  }

  const wasAccepted = state?.accepted === true;

  if (wasAccepted && !needsConsent(state, consentVersion)) {
    return { show: false, state, migrated: false, reason: 'accepted' };
  }

  // Only ever migrate a durable state that has never recorded consent -- a
  // version bump on an already-accepted state is a re-prompt, not a first
  // run, and must not be satisfied by replaying the old legacy flag.
  if (!wasAccepted) {
    let legacyComplete = false;
    try {
      legacyComplete = storage?.getItem?.(LEGACY_FLAG) === 'true';
    } catch (_e) {
      legacyComplete = false;
    }

    try {
      const result = await bridge.migrateLegacy?.({ legacyComplete });
      if (result?.migrated) {
        const migratedState = result.state ?? null;
        return {
          show: needsConsent(migratedState, consentVersion),
          state: migratedState,
          migrated: true,
          reason: 'migrated',
        };
      }
    } catch (_e) {
      // Migration is best-effort; fall through to showing the gate on
      // whatever durable state (or lack of it) was already read above.
    }
  }

  return {
    show: true,
    state,
    migrated: false,
    reason: wasAccepted ? 'consent_version_bumped' : 'no_state',
  };
}

/**
 * @param {object} opts
 * @param {object} [opts.bridge] see the bridge contract in this module's header
 * @param {number} [opts.consentVersion]
 * @param {(err: Error) => void} [opts.onError] called on any accept/decline failure
 */
export function createConsentController({ bridge, consentVersion = CURRENT_CONSENT_VERSION, onError } = {}) {
  async function accept() {
    try {
      const result = await bridge?.accept?.({ consentVersion });
      if (result?.ok) return { ok: true };
      onError?.(new Error('durable consent write failed'));
      return { ok: false };
    } catch (e) {
      onError?.(e);
      return { ok: false };
    }
  }

  // Declining is not a soft dismissal: it always quits, and a failure to
  // quit is surfaced rather than swallowed as if the decline had never
  // happened -- an app that fails to quit un-consented must not look idle.
  async function decline() {
    try {
      await bridge?.quit?.();
      return { ok: true };
    } catch (e) {
      onError?.(e);
      return { ok: false };
    }
  }

  // Informational step progress -- unlike accept, a failure here does not
  // block or misrepresent consent, so it is reported but non-fatal.
  async function completeStep(id) {
    try {
      const result = await bridge?.completeStep?.(id);
      return { ok: Boolean(result?.ok) };
    } catch (e) {
      onError?.(e);
      return { ok: false };
    }
  }

  return { accept, decline, completeStep };
}
