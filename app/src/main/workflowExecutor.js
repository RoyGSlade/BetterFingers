// The workflow run executor (D-0027) — main process.
//
// Wave 9 built the approval gate and deliberately stopped short of running
// anything: `POST /workflows/run` returns a validated plan and a verdict, and
// Python has no code path that starts a process. This module is the missing
// half. It is the ONLY caller of applicationLauncher.js, and the only way to
// reach it is one typed IPC channel that carries a workflow id and nothing else.
//
// WHY AN ID AND NOTHING ELSE. The renderer is the least trusted part of this
// process tree. If `workflows:execute` took a step list, a plan, or even a
// preview, a compromised renderer would be describing work to a component that
// can spawn processes, and every guarantee Wave 9 makes would rest on the
// renderer having been honest. So the channel takes an id; the main process
// re-fetches the workflow through the run gate, gets back the steps the BACKEND
// says are approved, and executes those. A renderer that lies about the id can
// only ask for a different workflow the user already approved.
//
// THE ORDER, and every line of it is load-bearing:
//
//   1. shape-check the id                (a path segment, not a path)
//   2. consume the run authorization      (single use; none, expired or another id: refuse)
//   3. build the context from the CONFIRMED registry, read here in main
//   4. POST /workflows/run                (re-validate, re-preview, can_run)
//   5. refuse unless ok AND the plan equals the confirmed one -- no step runs otherwise
//   6. perform each FROZEN step against its FROZEN target, in order, collecting a STATUS
//      CODE per step; a changed application stops the run
//   7. POST /workflows/run/record         (codes only; the history holds no paths)
//
// Step 3 is not a formality. A workflow can become unrunnable without anybody
// editing it -- the user removes the application it launches, or re-confirms it
// with a different launch method -- so the stored approval flag is not evidence
// that the preview still describes what would happen. Asking again on every run
// is the whole point of the gate.
//
// ONE RUN AT A TIME, PER WORKFLOW. A controller with a bouncy shoulder button
// or a Stream Deck key that repeats will ask twice. Debounce catches the
// millisecond case; this catches the "user pressed it again because nothing
// visible happened yet" case, which is a second or more later and would
// otherwise launch the game twice.
//
// EVERY RUN IS AUTHORIZED, AND THE TARGETS ARE FROZEN (round 3, items 1 and 2). `execute` takes
// the id and a run authorization minted by approvalBroker.confirmWorkflowRun after the person
// clicked in a native dialog (runAuthorization.js). Without one, nothing is asked of the backend
// and nothing runs. The authorization is consumed first; the gate's plan must equal the plan that
// was shown (preview digest and canonical steps); the steps that run are the FROZEN copies; every
// application step uses the registry entry frozen at confirm time and is refused, stopping the
// run, when the live registry entry no longer equals it. A target swapped during a wait never
// runs, and neither does the original once its entry has changed.
//
// WHAT IS NOT WIRED, honestly. `activate_persona` and `activate_writing_preset`
// have no activation route on the backend today -- selecting either is a
// settings write the dashboard performs, not an endpoint. They are dispatched
// through `applySetting`, which defaults to reporting `unavailable`, so a
// workflow containing one reports "did 2 of 3" rather than claiming success.
// The integration diff records this as the one open item.

const { linesDigest } = require('./approvalBroker');
const { canonicalJson } = require('./runAuthorization');

const DEFAULT_TIMEOUT_MS = 8000;

// Mirrors backend/services/action_validator.py STEP_STATUS_CODES and
// applicationLauncher.js. Codes only: a launcher error routinely quotes a path,
// and a path is personal, so it never reaches the run history.
const STATUS_OK = 'ok';
const STATUS_FAILED = 'failed';
const STATUS_NOT_FOUND = 'not_found';
const STATUS_TIMEOUT = 'timeout';
const STATUS_SKIPPED = 'skipped';
const STATUS_REFUSED = 'refused';
const STATUS_UNAVAILABLE = 'unavailable';

// A workflow id is a path segment the backend already normalised to
// ^[a-z0-9][a-z0-9_]{0,63}$. Re-checking here rather than trusting it is the
// cheap half of not letting a renderer put a slash in a URL we build.
const WORKFLOW_ID = /^[a-z0-9][a-z0-9_]{0,63}$/;

// wait_for_process is a bounded pause, not a process query: there is no portable
// way to ask "is this app up yet" without inspecting the process table, which is
// exactly the kind of desktop surveillance this project keeps out of Python and
// does not want in main either. So it waits, honestly, and says so in the
// preview the user approved.
const MAX_WAIT_MS = 30000;

function isPlainObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

/**
 * @param {object} deps
 * @param {object} deps.backendProxy            main/backendProxy.js
 * @param {object} deps.launcher                createApplicationLauncher(...) result
 * @param {function} [deps.listApplications]    () => confirmed registry entries
 * @param {function} [deps.notify]              (message) => void
 * @param {function} [deps.applySetting]        (action, value) => status code
 * @param {function} [deps.wait]                (ms) => Promise
 * @param {object} deps.authorizations          runAuthorization.createRunAuthorizations() result
 */
function createWorkflowExecutor({
  backendProxy,
  launcher,
  listApplications = () => [],
  notify = null,
  applySetting = null,
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  authorizations = null,
} = {}) {
  // workflow id -> the in-flight promise. Not a boolean: a second press should
  // receive the SAME answer the first one is waiting for, not a bare "busy"
  // that the caller has to interpret.
  const inFlight = new Map();

  function registryEntry(appId) {
    const entries = listApplications() || [];
    return entries.find((entry) => entry && entry.id === appId) || null;
  }

  async function post(path, body) {
    const response = await backendProxy.request({
      method: 'POST', path, body, timeoutMs: DEFAULT_TIMEOUT_MS,
    });
    if (!response || response.ok !== true) {
      return { ok: false, transportError: true, body: null };
    }
    return { ok: true, status: response.status, body: response.body };
  }

  // The frozen target of an application step, if the live registry still holds exactly it.
  // null means "changed or gone since the person confirmed": the step is refused and the run stops.
  function unchangedEntry(target, step) {
    if (!target || !target.entry || target.app_id !== String(step.app_id || '')) return null;
    const live = registryEntry(target.app_id);
    if (!live || canonicalJson(live) !== canonicalJson(target.entry)) return null;
    return target.entry;
  }

  /** One step -> one status code. Never a message, never a path. */
  async function performStep(step, target) {
    const action = String((step && step.action) || '');
    if (target && target.action !== action) return { status: STATUS_REFUSED, stop: true };
    switch (action) {
      case 'launch_app': {
        // The registry is the only thing a workflow may name; the entry used is the one FROZEN
        // when the person confirmed, and only while the live entry still equals it.
        const entry = unchangedEntry(target, step);
        if (!entry) return { status: STATUS_REFUSED, stop: true };
        return launcher.launch(entry).status;
      }
      case 'focus_app': {
        const entry = unchangedEntry(target, step);
        if (!entry) return { status: STATUS_REFUSED, stop: true };
        return launcher.focus(entry).status;
      }
      case 'open_uri':
      case 'open_folder': {
        const wanted = String((action === 'open_uri' ? step.uri : step.path) || '');
        if (!target || typeof target.target !== 'string' || target.target !== wanted) return { status: STATUS_REFUSED, stop: true };
        return launcher.open(target.target).status;
      }
      case 'wait_for_process': {
        const requested = Number(step.timeout_ms);
        const ms = Number.isFinite(requested) && requested > 0
          ? Math.min(requested, MAX_WAIT_MS)
          : 2000;
        await wait(ms);
        return STATUS_OK;
      }
      case 'activate_application_profile': {
        const result = await post('/app-context/override', { profile_id: String(step.profile_id || '') });
        return result.ok && result.status < 400 ? STATUS_OK : STATUS_FAILED;
      }
      case 'show_notification': {
        if (typeof notify !== 'function') return STATUS_UNAVAILABLE;
        try {
          notify(String(step.message || ''));
          return STATUS_OK;
        } catch {
          return STATUS_FAILED;
        }
      }
      case 'speak_confirmation': {
        const result = await post('/tts/speak', { text: String(step.message || '') });
        return result.ok && result.status < 400 ? STATUS_OK : STATUS_FAILED;
      }
      case 'activate_persona':
      case 'activate_writing_preset': {
        if (typeof applySetting !== 'function') return STATUS_UNAVAILABLE;
        const field = action === 'activate_persona' ? 'persona' : 'preset';
        try {
          const code = await applySetting(action, String(step[field] || ''));
          return typeof code === 'string' ? code : STATUS_OK;
        } catch {
          return STATUS_FAILED;
        }
      }
      default:
        // A verb the backend allowed but this executor does not implement. It
        // is REFUSED, not silently skipped: "the plan said do this and nothing
        // did it" must be visible in the run summary.
        return STATUS_REFUSED;
    }
  }

  async function runApproved(workflowId, grant) {
    const gate = await post('/workflows/run', {
      workflow_id: workflowId,
      context: { registry: listApplications() || [] },
    });

    if (!gate.ok) {
      return { ok: false, error: 'backend_unreachable',
        reason: 'BetterFingers could not reach its own backend to check that workflow.' };
    }
    if (gate.status >= 400 || !isPlainObject(gate.body)) {
      return { ok: false, error: 'not_found',
        reason: 'That workflow no longer exists.' };
    }
    if (gate.body.ok !== true) {
      // The gate's own refusal, passed through unchanged. It already reads as a
      // sentence and already names which steps stopped being possible;
      // rewriting it here would make the same refusal say two different things
      // depending on whether a button or the dashboard asked.
      return {
        ok: false,
        error: gate.body.error || 'refused',
        reason: gate.body.reason || 'BetterFingers will not run that workflow.',
        refusals: gate.body.refusals || [],
        preview_lines: gate.body.preview_lines || [],
      };
    }

    const workflow = isPlainObject(gate.body.workflow) ? gate.body.workflow : {};
    const gateLines = Array.isArray(gate.body.preview_lines) ? gate.body.preview_lines.map(String) : null;
    // The gate must describe exactly the plan the person confirmed. Anything else -- an edit, a
    // re-approval, a registry change that alters the preview -- is a different run, refused.
    if (!gateLines || linesDigest(gateLines) !== grant.previewSha256
        || !Array.isArray(workflow.steps) || canonicalJson(workflow.steps) !== grant.stepsCanonical) {
      return { ok: false, error: 'plan_changed',
        reason: 'That workflow changed after you confirmed it, so nothing ran. Run it again to see the new steps.' };
    }
    const steps = grant.steps;

    // Sequential, deliberately. These steps have an order the user read in the
    // preview -- "launch the game, then switch the profile" -- and running them
    // concurrently would make the preview a lie about what happens when.
    const results = [];
    let stopped = false;
    for (let index = 0; index < steps.length; index += 1) {
      let status;
      if (stopped) {
        status = STATUS_SKIPPED;
      } else {
        try {
          const outcome = await performStep(steps[index], grant.targets[index]);
          if (outcome && typeof outcome === 'object') {
            status = outcome.status;
            stopped = Boolean(outcome.stop);
          } else {
            status = outcome;
          }
        } catch {
          status = STATUS_FAILED;
        }
      }
      results.push({ index, action: String(steps[index].action || ''), status });
    }

    // Always record, including when everything failed. A run that produced only
    // failures is exactly the run somebody will ask about later.
    const record = await post('/workflows/run/record', {
      workflow_id: workflowId, results,
    });
    const summary = record.ok && isPlainObject(record.body) ? record.body.summary : null;

    return {
      ok: Boolean(summary && summary.ok) && !stopped,
      ...(stopped ? { error: 'target_changed', reason: 'An application changed after you confirmed this run, so BetterFingers stopped before starting it.' } : {}),
      workflow_id: workflowId,
      preview_lines: gate.body.preview_lines || [],
      results,
      summary,
    };
  }

  /**
   * The one entry point. Takes a workflow id and the run authorization main minted after the
   * person's click, and nothing else: the steps and targets come from the authorization.
   */
  async function execute(workflowId, { authorization } = {}) {
    const id = String(workflowId || '').trim();
    if (!WORKFLOW_ID.test(id)) {
      return { ok: false, error: 'invalid_id',
        reason: 'That is not a workflow BetterFingers knows about.' };
    }
    // Consumed before anything else, so a token is good for exactly one attempt.
    const grant = authorizations && typeof authorizations.consume === 'function'
      ? authorizations.consume(authorization, id)
      : null;
    if (!grant) {
      return { ok: false, error: 'not_confirmed',
        reason: 'That run was not confirmed in the BetterFingers window, so nothing ran.' };
    }

    const existing = inFlight.get(id);
    if (existing) return existing;

    const promise = runApproved(id, grant).finally(() => inFlight.delete(id));
    inFlight.set(id, promise);
    return promise;
  }

  return { execute, isRunning: (id) => inFlight.has(String(id || '')) };
}

module.exports = {
  createWorkflowExecutor,
  WORKFLOW_ID,
  MAX_WAIT_MS,
  STATUS_OK,
  STATUS_FAILED,
  STATUS_NOT_FOUND,
  STATUS_TIMEOUT,
  STATUS_SKIPPED,
  STATUS_REFUSED,
  STATUS_UNAVAILABLE,
};
