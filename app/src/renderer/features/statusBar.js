// Signal Desk status bar (SPEC 3d) — the persistent bottom rail.
//
// DESIGN.md §11 calls for "every piece of hidden state permanently
// glanceable". The rail existed as markup only: no element had an `id`, and it
// hard-coded "Live / Ready / Local / Natural / Discord / 1.2 sec" regardless of
// what the app was actually doing. A rail that asserts a mic is Live while it
// is idle, or 1.2 sec latency before a single dictation has run, is worse than
// no rail — it is confidently wrong about exactly the state the user came here
// to check.
//
// The rule this module follows: never invent a value. Anything not known reads
// `—`, the same convention main.js already uses for absent metrics.
//
// Every mapper below is pure and separately exported so the display rules are
// testable without a DOM or a backend.

export const STATUS_BAR_ELEMENT_IDS = {
  micValue: 'sdStatusMicValue',
  sttValue: 'sdStatusSttValue',
  sttDot: 'sdStatusSttDot',
  llmValue: 'sdStatusLlmValue',
  llmDot: 'sdStatusLlmDot',
  personaValue: 'sdStatusPersonaValue',
  targetAppValue: 'sdStatusTargetAppValue',
  latencyValue: 'sdStatusLatencyValue',
  // Wave 5. Unlike every other cell this one HIDES when there is nothing to
  // say, so it needs its container as well as its value element.
  contactCell: 'sdStatusContactCell',
  contactValue: 'sdStatusContactValue',
};

export const UNKNOWN = '—';

/** Tone vocabulary shared with the rest of the Signal Desk surface. */
const OK = 'success';
const WARN = 'warning';
const IDLE = 'muted';

// --- Pure mappers -------------------------------------------------------------

/**
 * Mic cell. Deliberately "Idle" rather than the mockup's "Live": the mic is not
 * being streamed when nothing is recording, and saying otherwise misrepresents
 * whether the app is listening — the single most privacy-sensitive claim in the
 * whole UI.
 */
export function mapMic(runtime) {
  if (!runtime) return { text: UNKNOWN, tone: IDLE };
  return runtime.recording_active
    ? { text: 'Recording', tone: OK }
    : { text: 'Idle', tone: IDLE };
}

/** Speech-to-text readiness, preferring the runtime probe over /health. */
export function mapStt(health, runtime) {
  const loaded = runtime?.transcriber_loaded ?? runtime?.transcriber_initialized ?? health?.transcriber;
  if (loaded === undefined || loaded === null) return { text: UNKNOWN, tone: IDLE };
  return loaded ? { text: 'Loaded', tone: OK } : { text: 'Not loaded', tone: WARN };
}

/**
 * LLM readiness. The mockup's "Local" described WHERE the model runs, which is
 * invariant (everything is local) and therefore tells the user nothing. Report
 * readiness instead, which actually changes.
 */
export function mapLlm(health, runtime) {
  const ready = runtime?.llm_ready ?? runtime?.llm_initialized ?? health?.llm_engine;
  if (ready === undefined || ready === null) return { text: UNKNOWN, tone: IDLE };
  return ready ? { text: 'Ready', tone: OK } : { text: 'Not ready', tone: WARN };
}

/** Active persona, from the profile's current_preset. */
export function mapPersona(profile) {
  const name = typeof profile?.current_preset === 'string' ? profile.current_preset.trim() : '';
  return name ? { text: name, tone: IDLE } : { text: UNKNOWN, tone: IDLE };
}

/**
 * Latency: the last end-to-end dictation time.
 *
 * `null` before any dictation has run, which is the common case on a fresh
 * launch — hence `—` rather than a plausible-looking number.
 */
export function formatLatency(metrics) {
  const ms = metrics?.total?.last_ms;
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return { text: UNKNOWN, tone: IDLE };
  if (ms < 1000) return { text: `${Math.round(ms)} ms`, tone: IDLE };
  return { text: `${(ms / 1000).toFixed(1)} sec`, tone: IDLE };
}

/**
 * Target app — what the mockup labelled "Destination: Discord".
 *
 * That was fiction twice over: drafts carry no destination field at all
 * (backend/stores/drafts.py), and the only real per-app signal in the codebase
 * is injection_pacing.py's detect_active_app_key(), which identifies the
 * focused APPLICATION (not a person or channel), is used solely to choose
 * keystroke pacing, never reaches the renderer, and returns "" on Wayland.
 *
 * So this reports the app when something supplies one and `—` otherwise. It
 * does not guess, and it is never a person: naming a recipient here would be
 * inventing exactly the concept the product does not yet have.
 */
export function mapTargetApp(targetApp) {
  const name = typeof targetApp === 'string' ? targetApp.trim() : '';
  return name ? { text: name, tone: IDLE } : { text: UNKNOWN, tone: IDLE };
}

/**
 * Applied contact — the "Writing to" selection, made glanceable.
 *
 * This is the one cell that can be ABSENT rather than unknown, and the
 * distinction matters. Every other cell describes something that always has a
 * state, so `—` is the honest reading when we cannot see it. "No one in
 * particular" is not an unknown audience, it is a real and default choice, and
 * a permanent rail cell reading `—` next to "Writing to" would turn that
 * default into a gap the user feels invited to fill.
 *
 * So: a contact returns a cell, no contact returns null, and the caller hides
 * the element. Reuses statusLabelFor()'s rule via the same null contract, and
 * takes the resolved contact rather than an id -- an id whose contact was
 * deleted must show nothing, not a dangling identifier.
 */
export function mapContact(contact) {
  const name = typeof contact?.name === 'string' ? contact.name.trim() : '';
  if (!contact?.id || !name) return null;
  return { text: name, tone: IDLE };
}

/** Maps a whole backend snapshot to the full set of cell values. */
export function computeStatusBar({ health, runtime, profile, metrics, targetApp, contact } = {}) {
  return {
    mic: mapMic(runtime),
    stt: mapStt(health, runtime),
    llm: mapLlm(health, runtime),
    persona: mapPersona(profile),
    targetApp: mapTargetApp(targetApp),
    latency: formatLatency(metrics),
    contact: mapContact(contact),
  };
}

// --- DOM wiring ---------------------------------------------------------------

export function collectStatusBarElements(root = document) {
  const els = {};
  for (const [key, id] of Object.entries(STATUS_BAR_ELEMENT_IDS)) {
    els[key] = root?.getElementById?.(id) ?? null;
  }
  return els;
}

function paint(el, dotEl, cell) {
  if (el) {
    el.textContent = cell.text;
    el.dataset.tone = cell.tone;
  }
  if (dotEl) dotEl.dataset.tone = cell.tone;
}

/**
 * @param {object} opts
 * @param {object} opts.elements  from collectStatusBarElements()
 * @param {object} [opts.api]     backend api module; when absent, render() must
 *                                be handed a snapshot explicitly
 */
export function createStatusBarFeature({ elements = {}, api = null } = {}) {
  let latest = null;
  // Held across renders because it does not come from the backend snapshot the
  // poll below fetches -- the applied contact is pushed in by the contacts
  // feature when the user changes it. Without this, the next health poll would
  // silently clear the cell.
  let appliedContact = null;

  function paintContact(cell) {
    if (elements.contactCell) elements.contactCell.hidden = !cell;
    if (!cell) {
      if (elements.contactValue) elements.contactValue.textContent = '';
      return;
    }
    paint(elements.contactValue, null, cell);
  }

  function render(snapshot) {
    const source = snapshot || {};
    const values = computeStatusBar({
      ...source,
      contact: 'contact' in source ? source.contact : appliedContact,
    });
    latest = values;
    paint(elements.micValue, null, values.mic);
    paint(elements.sttValue, elements.sttDot, values.stt);
    paint(elements.llmValue, elements.llmDot, values.llm);
    paint(elements.personaValue, null, values.persona);
    paint(elements.targetAppValue, null, values.targetApp);
    paint(elements.latencyValue, null, values.latency);
    paintContact(values.contact);
    return values;
  }

  /**
   * The contacts feature calls this when the applied contact changes, including
   * with null when it is cleared. Repaints immediately rather than waiting for
   * the next poll: clearing an audience is the kind of thing a user wants to
   * see take effect at once.
   */
  function setContact(contact) {
    appliedContact = contact || null;
    paintContact(mapContact(appliedContact));
    if (latest) latest.contact = mapContact(appliedContact);
    return appliedContact;
  }

  // Each call is independently guarded: one dead endpoint must degrade its own
  // cell to `—` rather than blanking cells whose data arrived fine.
  async function refresh() {
    if (!api) return render(null);
    const [health, runtime, metrics] = await Promise.all([
      api.fetchHealth?.().catch(() => null) ?? null,
      api.fetchRuntimeStatus?.().catch(() => null) ?? null,
      api.fetchMetrics?.().catch(() => null) ?? null,
    ]);
    let profile = null;
    try {
      profile = (await api.fetchProfile?.('Default')) ?? null;
    } catch (_e) {
      profile = null;
    }
    return render({ health, runtime, profile, metrics });
  }

  return { render, refresh, setContact, getContact: () => appliedContact, getState: () => latest };
}
