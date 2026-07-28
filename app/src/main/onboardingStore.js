// Durable onboarding/consent record for the main process.
//
// This lives under the unified user-data root (see userDataRoot.js), NOT
// under Electron's app.getPath('userData') — the Python privacy/factory-reset
// tooling reasons about the unified root, and onboarding consent must be
// visible to it.
//
// Wipe-mode note (see data_categories.py, owned by the supervisor): this is a
// 'configuration'-class record, cleared only by a FACTORY RESET
// (clearForFactoryReset). There is deliberately NO privacy-wipe clear
// function here — an ordinary privacy wipe must not erase the legal consent
// record, because the record is evidence that consent was given, not user
// content. Only clearForFactoryReset may delete it.
//
// No electron import: this module is required directly by unit tests without
// an Electron runtime, and the user-data root is injectable for the same
// reason.

const fs = require('node:fs');
const path = require('node:path');

const { resolveUserDataRoot } = require('./userDataRoot');

const SCHEMA_VERSION = 1;
// Bump this to force every existing user through consent again.
const CURRENT_CONSENT_VERSION = 1;

const FILE_NAME = 'onboarding.json';

function onboardingFilePath(root) {
  return path.join(root, FILE_NAME);
}

function defaultState() {
  return {
    schema_version: SCHEMA_VERSION,
    consent_version: CURRENT_CONSENT_VERSION,
    accepted: false,
    accepted_at: null,
    completed_steps: [],
  };
}

function dedupeStable(list) {
  const seen = new Set();
  const out = [];
  for (const item of list) {
    if (!seen.has(item)) {
      seen.add(item);
      out.push(item);
    }
  }
  return out;
}

// Normalizes whatever was parsed off disk into the current shape, dropping
// unknown/extra keys and filling defaults for anything missing or malformed.
//
// A schema_version greater than what this build understands is treated as
// UNREADABLE, not silently downgraded/reinterpreted — we report "no consent
// recorded" (needsConsent will be true) rather than guess at a newer format
// and risk mis-parsing a future field as an acceptance.
function normalize(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return defaultState();
  }
  if (raw.schema_version !== undefined) {
    if (typeof raw.schema_version !== 'number' || raw.schema_version > SCHEMA_VERSION) {
      return defaultState();
    }
  }

  const accepted = raw.accepted === true;
  // An accepted record with a missing/malformed consent_version is of
  // UNKNOWN provenance — normalizing it to CURRENT_CONSENT_VERSION would let
  // it silently satisfy a future consent-version bump (the exact fail-open
  // this store exists to prevent). Normalize to 0 instead, which never
  // satisfies needsConsent's `>= currentConsentVersion` check, so it always
  // re-prompts. The never-accepted default state is unaffected by this and
  // keeps CURRENT_CONSENT_VERSION (inert; needsConsent only looks at
  // consent_version when accepted === true), matching the documented
  // on-disk shape for a fresh install.
  const consentVersion = Number.isFinite(raw.consent_version)
    ? raw.consent_version
    : (accepted ? 0 : CURRENT_CONSENT_VERSION);
  const acceptedAt = accepted && typeof raw.accepted_at === 'string' ? raw.accepted_at : null;
  const completedSteps = Array.isArray(raw.completed_steps)
    ? dedupeStable(raw.completed_steps.filter((s) => typeof s === 'string'))
    : [];

  return {
    schema_version: SCHEMA_VERSION,
    consent_version: consentVersion,
    accepted,
    accepted_at: acceptedAt,
    completed_steps: completedSteps,
  };
}

// Atomically and durably writes `data` to <root>/onboarding.json: mkdir -p
// the root, write to a same-directory temp file, fsync, then rename over the
// target, so a crash mid-write never leaves a truncated file. Never throws;
// returns { ok, error } so a failed write can be logged/reported instead of
// crashing app startup, and is never mistaken for success by its caller.
function atomicWriteJSON(root, data) {
  let fd;
  const tmpFile = path.join(root, `.${FILE_NAME}.tmp-${process.pid}-${Date.now()}`);
  try {
    // mode only takes effect on directories this call actually creates — an
    // existing root's permissions are left alone rather than force-reset on
    // every write (which would also defeat deliberate permission testing).
    fs.mkdirSync(root, { recursive: true, mode: 0o700 });

    fd = fs.openSync(tmpFile, 'w', 0o600);
    fs.writeSync(fd, JSON.stringify(data, null, 2));
    fs.fsyncSync(fd);
    fs.closeSync(fd);
    fd = undefined;
    fs.renameSync(tmpFile, onboardingFilePath(root));

    // Best-effort: fsync the containing directory too, so the rename itself
    // (the directory entry, not just the file's bytes) survives a hard power
    // loss. Not supported on Windows — failures here are ignored.
    try {
      const dirFd = fs.openSync(root, 'r');
      try {
        fs.fsyncSync(dirFd);
      } finally {
        fs.closeSync(dirFd);
      }
    } catch {
      // Best effort.
    }

    try {
      fs.chmodSync(onboardingFilePath(root), 0o600);
    } catch {
      // Best effort.
    }
    return { ok: true };
  } catch (error) {
    if (fd !== undefined) {
      try {
        fs.closeSync(fd);
      } catch {
        // Already closed or invalid — nothing more to clean up.
      }
    }
    try {
      fs.unlinkSync(tmpFile);
    } catch {
      // Temp file was never created, or already gone.
    }
    console.error('onboardingStore: failed to persist onboarding.json:', error);
    return { ok: false, error };
  }
}

// Reads and normalizes the durable state. Tolerant of a missing, unreadable,
// or corrupt file — any of those read as "no consent recorded" (the default
// state), never as accepted.
function readState({ root = resolveUserDataRoot() } = {}) {
  let raw;
  try {
    const text = fs.readFileSync(onboardingFilePath(root), 'utf8');
    raw = JSON.parse(text);
  } catch {
    return defaultState();
  }
  return normalize(raw);
}

function needsConsent(state, currentConsentVersion = CURRENT_CONSENT_VERSION) {
  return !(state && state.accepted === true && state.consent_version >= currentConsentVersion);
}

// Returns { ok, state, error? }. `state` reflects the intended new record
// even when ok is false — but callers (the consent UI in particular) MUST
// gate on `ok`, not on the presence of `state`: a false `ok` means the write
// did not durably happen, and the caller must not let the user proceed as
// though they had consented.
function recordAcceptance({
  root = resolveUserDataRoot(),
  consentVersion = CURRENT_CONSENT_VERSION,
  now = () => new Date(),
} = {}) {
  const current = readState({ root });
  const state = {
    ...current,
    schema_version: SCHEMA_VERSION,
    accepted: true,
    consent_version: consentVersion,
    accepted_at: now().toISOString(),
  };
  const result = atomicWriteJSON(root, state);
  return result.ok ? { ok: true, state } : { ok: false, state, error: result.error };
}

// Returns { ok, state, error? }. ok is true (with no write performed) when
// the step was already recorded — idempotent, not a failure. Same gating
// rule as recordAcceptance: a false ok means the append did not persist.
function recordStepComplete(stepId, { root = resolveUserDataRoot() } = {}) {
  const current = readState({ root });
  if (current.completed_steps.includes(stepId)) {
    return { ok: true, state: current };
  }
  const state = {
    ...current,
    completed_steps: [...current.completed_steps, stepId],
  };
  const result = atomicWriteJSON(root, state);
  return result.ok ? { ok: true, state } : { ok: false, state, error: result.error };
}

// One-shot migration of the legacy renderer-local
// localStorage['bf_onboarding_complete'] === 'true' flag into the durable
// store. Idempotent by construction: once the durable file exists — even if
// it's corrupt/unreadable, which is treated the same as present — migration
// never runs again, so this is safe to call unconditionally on every
// startup. Consequence: a user whose file got corrupted keeps their legacy
// localStorage completion unmigrated and simply sees the consent screen
// again — fail-closed, and the correct outcome for a record of unknown
// state.
//
// Returns { migrated, reason?, ok, state?, error? }. migrated is true only
// once the record is durably on disk — a write failure must NOT report
// migrated:true (nothing was actually migrated in that case), even though
// `state` still carries the record that was attempted.
function migrateLegacyCompletion({ legacyComplete, root = resolveUserDataRoot(), now = () => new Date() } = {}) {
  if (fs.existsSync(onboardingFilePath(root))) {
    return { migrated: false, reason: 'already_present', ok: true };
  }
  if (!legacyComplete) {
    return { migrated: false, reason: 'no_legacy_value', ok: true };
  }
  const state = {
    schema_version: SCHEMA_VERSION,
    consent_version: 1,
    accepted: true,
    accepted_at: now().toISOString(),
    completed_steps: [],
  };
  const result = atomicWriteJSON(root, state);
  if (!result.ok) {
    return { migrated: false, ok: false, state, error: result.error };
  }
  return { migrated: true, ok: true, state };
}

// Deletes the durable record. This is FACTORY-RESET-ONLY — see the header
// comment: there is intentionally no privacy-wipe equivalent. A missing file
// is treated as success (the desired end state already holds).
function clearForFactoryReset({ root = resolveUserDataRoot() } = {}) {
  try {
    fs.rmSync(onboardingFilePath(root), { force: true });
    return { cleared: true };
  } catch (error) {
    console.error('onboardingStore: failed to clear onboarding.json:', error);
    return { cleared: false, error };
  }
}

module.exports = {
  SCHEMA_VERSION,
  CURRENT_CONSENT_VERSION,
  readState,
  needsConsent,
  recordAcceptance,
  recordStepComplete,
  migrateLegacyCompletion,
  clearForFactoryReset,
};
