'use strict';

// Run authorizations (round 3, items 1 and 2) — main process only.
//
// A workflow APPROVAL says "these steps are fine". A RUN is a separate act, and since round 3 every
// run is confirmed in a native dialog first (approvalBroker.confirmWorkflowRun). What that click
// produces is not a boolean the caller passes along: it is a fresh, single-use authorization that
//
//   * names exactly one workflow,
//   * is bound to the exact plan that was shown (the digest of the preview lines and the canonical
//     form of the step list), and
//   * carries the RESOLVED launch targets, frozen at confirm time: for an application step the
//     confirmed registry entry and the command and argument list it resolves to; for a link or a
//     folder the exact string.
//
// The executor (workflowExecutor.js) consumes the authorization before it does anything, refuses
// when the backend's run gate describes a different plan, executes only the frozen steps against
// only the frozen targets, and refuses (stopping the run) when a registry entry no longer equals
// the frozen copy. A token is a random string held in this process; it is never sent to a renderer
// or the backend, it expires quickly, and consuming it deletes it.

const crypto = require('node:crypto');

const RUN_AUTHORIZATION_TTL_MS = 60 * 1000;
const MAX_LIVE = 32;

// JSON with object keys sorted, so two structurally equal values compare equal as strings.
function canonicalJson(value) {
  if (value === undefined || typeof value === 'function') return 'null';
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  const keys = Object.keys(value).filter((key) => value[key] !== undefined).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.freeze(value);
    for (const key of Object.keys(value)) deepFreeze(value[key]);
  }
  return value;
}

function frozenCopy(value) {
  return deepFreeze(JSON.parse(JSON.stringify(value === undefined ? null : value)));
}

const APP_ACTIONS = new Set(['launch_app', 'focus_app']);

/**
 * Resolve every outward target of `steps` against ONE registry snapshot.
 *
 * @param {Array} steps            the workflow's steps, as the backend previewed them
 * @param {Array} registry         the confirmed registry snapshot the preview was computed from
 * @param {object} deps
 * @param {function} deps.planLaunch  entry => { ok, command, args } (applicationLauncher.planFor)
 * @returns {{ok: true, targets: Array, lines: string[]} | {ok: false, reason: string}}
 */
function freezeRunTargets(steps, registry, { planLaunch } = {}) {
  if (!Array.isArray(steps) || steps.length === 0) return { ok: false, reason: 'The workflow has no steps.' };
  if (typeof planLaunch !== 'function') return { ok: false, reason: 'BetterFingers cannot resolve launch targets.' };
  const confirmed = new Map();
  for (const entry of Array.isArray(registry) ? registry : []) {
    if (entry && typeof entry === 'object' && entry.confirmed === true && typeof entry.id === 'string') {
      confirmed.set(entry.id, entry);
    }
  }
  const targets = [];
  const lines = [];
  for (let index = 0; index < steps.length; index += 1) {
    const step = steps[index] && typeof steps[index] === 'object' ? steps[index] : {};
    const action = String(step.action || '');
    const number = index + 1;
    if (APP_ACTIONS.has(action)) {
      const entry = confirmed.get(String(step.app_id || ''));
      if (!entry) return { ok: false, reason: `Step ${number} names an application that is not confirmed.` };
      if (action === 'launch_app') {
        const plan = planLaunch(entry);
        if (!plan || plan.ok !== true || typeof plan.command !== 'string' || !Array.isArray(plan.args)) {
          return { ok: false, reason: `Step ${number}: BetterFingers does not know how to start that application.` };
        }
        targets.push({ index, action, app_id: entry.id, entry, plan: { command: plan.command, args: plan.args.map(String) } });
        lines.push(`${number}. Starts the program ${plan.command}${plan.args.length ? ` with arguments ${JSON.stringify(plan.args.map(String))}` : ' with no arguments'}`);
      } else {
        targets.push({ index, action, app_id: entry.id, entry, plan: null });
        lines.push(`${number}. Brings the window of ${entry.executable || entry.id} to the front`);
      }
    } else if (action === 'open_uri') {
      const target = String(step.uri || '');
      if (!target) return { ok: false, reason: `Step ${number} has no link.` };
      targets.push({ index, action, target });
      lines.push(`${number}. Opens the link ${target}`);
    } else if (action === 'open_folder') {
      const target = String(step.path || '');
      if (!target) return { ok: false, reason: `Step ${number} has no folder.` };
      targets.push({ index, action, target });
      lines.push(`${number}. Opens the folder ${target}`);
    } else {
      targets.push({ index, action });
    }
  }
  return { ok: true, targets: frozenCopy(targets), lines };
}

function createRunAuthorizations({
  now = () => Date.now(),
  ttlMs = RUN_AUTHORIZATION_TTL_MS,
  randomBytes = crypto.randomBytes,
} = {}) {
  const live = new Map();

  function prune() {
    const t = now();
    for (const [token, grant] of live) if (grant.expiresAt <= t) live.delete(token);
    while (live.size >= MAX_LIVE) live.delete(live.keys().next().value);
  }

  /** Only approvalBroker.confirmWorkflowRun calls this, and only after the person clicked. */
  function issue({ workflowId, previewSha256, steps, targets }) {
    if (typeof workflowId !== 'string' || !workflowId) throw new Error('run authorization needs a workflow');
    if (typeof previewSha256 !== 'string' || !/^[0-9a-f]{64}$/.test(previewSha256)) throw new Error('run authorization needs a preview digest');
    if (!Array.isArray(steps) || !Array.isArray(targets) || targets.length !== steps.length) {
      throw new Error('run authorization needs one frozen target per step');
    }
    prune();
    const token = randomBytes(24).toString('hex');
    live.set(token, deepFreeze({
      workflowId,
      previewSha256,
      steps: frozenCopy(steps),
      stepsCanonical: canonicalJson(steps),
      targets: frozenCopy(targets),
      expiresAt: now() + ttlMs,
    }));
    return token;
  }

  /** Single use: the grant is deleted whether or not it is still valid. */
  function consume(token, workflowId) {
    if (typeof token !== 'string' || !live.has(token)) return null;
    const grant = live.get(token);
    live.delete(token);
    if (grant.expiresAt <= now()) return null;
    if (grant.workflowId !== workflowId) return null;
    return grant;
  }

  return { issue, consume, size: () => live.size };
}

module.exports = {
  canonicalJson,
  deepFreeze,
  frozenCopy,
  freezeRunTargets,
  createRunAuthorizations,
  RUN_AUTHORIZATION_TTL_MS,
};
