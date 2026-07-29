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
  // Wave 11B. The legacy dashboard carried a three-card backend status grid and
  // a WebSocket connection pill; Signal Desk shipped neither, so two states a
  // user needs -- "is the backend answering at all" and "is the live voice
  // stream still attached" -- had no production surface. See mapBackend() and
  // mapStream() for why each is a rail cell rather than a card.
  backendValue: 'sdStatusBackendValue',
  backendDot: 'sdStatusBackendDot',
  streamValue: 'sdStatusStreamValue',
  streamDot: 'sdStatusStreamDot',
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
  // Wave 7. Same absent-rather-than-unknown rule as the contact cell above,
  // for the same reason -- see mapAppProfile().
  appProfileCell: 'sdStatusAppProfileCell',
  appProfileValue: 'sdStatusAppProfileValue',
};

export const UNKNOWN = '—';

/** Tone vocabulary shared with the rest of the Signal Desk surface. */
const OK = 'success';
const WARN = 'warning';
const IDLE = 'muted';

// --- Pure mappers -------------------------------------------------------------

/**
 * Backend reachability — the cell that replaces the legacy dashboard's Backend
 * card (`backendStatus`/`backendDetail` — deliberately written WITHOUT the
 * selector `#`: tools/parity_evidence.py treats a quoted or `#`-prefixed id
 * appearing anywhere in reachable source as a production anchor, and a COMMENT
 * naming a legacy id must never be the thing that makes an inventory row
 * resolve. The real anchor is the element this function paints; the mapping is
 * declared, and checked, in tools/parity_anchors.py).
 *
 * Reachability and payload are separate arguments on purpose. `health` alone
 * cannot distinguish "the fetch failed" from "we have not fetched yet", and
 * those must not read the same: a rail that shows `—` while the backend is
 * down is silently wrong about the one thing that explains why nothing else
 * works. So `reachable === false` reports Unreachable, `null` (never asked)
 * reports unknown, and only a real payload is trusted for the rest.
 *
 * `detail` rides along for the element title so a degraded state can say what
 * it is without widening the rail.
 */
export function mapBackend(health, reachable) {
  if (reachable === false) {
    return { text: 'Unreachable', tone: WARN, detail: 'The backend did not answer GET /health.' };
  }
  const status = typeof health?.status === 'string' ? health.status.trim() : '';
  if (!status) return { text: UNKNOWN, tone: IDLE };
  if (status !== 'active') return { text: status, tone: WARN };
  const jobs = Number(health?.active_job_count);
  return Number.isFinite(jobs) && jobs > 0
    ? { text: 'Active', tone: OK, detail: `${jobs} job${jobs === 1 ? '' : 's'} in progress.` }
    : { text: 'Active', tone: OK, detail: 'GET /health responded.' };
}

/**
 * Live voice-status stream — the cell that replaces the legacy `wsConnection`
 * pill (again no selector `#`, for the reason mapBackend() gives above).
 *
 * The socket itself lives in the Electron main process (it holds the token);
 * the renderer only receives forwarded state. Before Wave 11B the production
 * bootstrap subscribed with empty `onConnectionChange`/`onError` handlers, so a
 * dropped stream was invisible: the Signal Core simply stopped moving and the
 * user had no way to tell a quiet mic from a severed connection.
 *
 * `reconnecting` is deliberately a warning rather than a neutral state. It is
 * recoverable, but while it lasts the meter and the capture controls are
 * reporting stale truth, and that is worth showing.
 */
const STREAM_STATES = {
  connecting: { text: 'Connecting', tone: IDLE },
  connected: { text: 'Connected', tone: OK },
  reconnecting: { text: 'Reconnecting', tone: WARN },
  closed: { text: 'Closed', tone: WARN },
  error: { text: 'Error', tone: WARN },
};

export function mapStream(state, detail) {
  const key = typeof state === 'string' ? state.trim().toLowerCase() : '';
  if (!key) return { text: UNKNOWN, tone: IDLE };
  const known = STREAM_STATES[key];
  const cell = known || { text: key, tone: WARN };
  const note = typeof detail === 'string' ? detail.trim() : '';
  return note ? { ...cell, detail: note } : { ...cell };
}

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

/**
 * Human labels for the built-in application profiles.
 *
 * A map rather than a title-caser because "World Of Warcraft" is not what the
 * game is called, and a status rail that misspells the thing it is reporting on
 * reads as a rail that is guessing. Ids this build has never seen (a profile a
 * user created) fall back to word-casing, which is the honest best effort for a
 * string only the user chose.
 */
export const APP_PROFILE_LABELS = {
  default: 'Default',
  discord: 'Discord',
  email: 'Email',
  game_generic: 'Game',
  rocket_league: 'Rocket League',
  world_of_warcraft: 'World of Warcraft',
  writing_app: 'Writing',
};

export function appProfileLabel(profileId) {
  const id = typeof profileId === 'string' ? profileId.trim() : '';
  if (!id) return '';
  if (APP_PROFILE_LABELS[id]) return APP_PROFILE_LABELS[id];
  return id
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Active application profile — the second cell that can be ABSENT.
 *
 * Hidden for Default, and Default is also what an unidentified application
 * resolves to (Wayland has no portable focused-window query, so the backend
 * honestly reports nothing rather than guessing). Both of those states mean
 * "the app is behaving normally", and a permanent rail cell announcing
 * "Profile: Default" would be a claim of activity where there is none — the
 * same mistake the mockup's hard-coded "Destination: Discord" made, and the
 * same rule the Wave 5 contact cell established.
 *
 * A cell appears only when a real, non-default profile is in effect. The
 * `source` rides along as a tone so a TEMPORARY override reads differently
 * from an automatic match: an override the user forgot they set is exactly the
 * thing they need the rail to remind them about.
 */
export function mapAppProfile(context) {
  const id = typeof context?.profile_id === 'string' ? context.profile_id.trim() : '';
  if (!id || id === 'default') return null;
  const label = appProfileLabel(id);
  if (!label) return null;
  return {
    text: context?.override_active ? `${label} (held)` : label,
    tone: context?.override_active ? WARN : IDLE,
  };
}

/** Maps a whole backend snapshot to the full set of cell values. */
export function computeStatusBar({
  health, healthReachable, stream, runtime, profile, metrics, targetApp, contact, appContext,
} = {}) {
  return {
    backend: mapBackend(health, healthReachable),
    stream: mapStream(stream?.state, stream?.detail),
    mic: mapMic(runtime),
    stt: mapStt(health, runtime),
    llm: mapLlm(health, runtime),
    persona: mapPersona(profile),
    targetApp: mapTargetApp(targetApp),
    latency: formatLatency(metrics),
    contact: mapContact(contact),
    appProfile: mapAppProfile(appContext),
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
    // The rail is too narrow for a reason string, but a cell that says
    // "Unreachable" and cannot say why is a dead end. Hover/AT get the detail;
    // a cell with none clears any stale title rather than keeping the last one.
    if (cell.detail) el.title = cell.detail;
    else el.removeAttribute?.('title');
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
  // Same reason as appliedContact: the application context is pushed in by the
  // applicationProfiles feature (it owns the /app-context poll), so without
  // holding it here the next health poll would silently clear the cell.
  let appContext = null;
  // Wave 11B. Same hold-across-renders reason as appliedContact/appContext: the
  // voice-status stream state is PUSHED in by the main-process bridge, never
  // fetched by the poll below, so without holding it here every health tick
  // would reset a live "Reconnecting" back to unknown.
  let streamState = null;

  function paintContact(cell) {
    if (elements.contactCell) elements.contactCell.hidden = !cell;
    if (!cell) {
      if (elements.contactValue) elements.contactValue.textContent = '';
      return;
    }
    paint(elements.contactValue, null, cell);
  }

  function paintAppProfile(cell) {
    if (elements.appProfileCell) elements.appProfileCell.hidden = !cell;
    if (!cell) {
      if (elements.appProfileValue) elements.appProfileValue.textContent = '';
      return;
    }
    paint(elements.appProfileValue, null, cell);
  }

  function render(snapshot) {
    const source = snapshot || {};
    const values = computeStatusBar({
      ...source,
      contact: 'contact' in source ? source.contact : appliedContact,
      appContext: 'appContext' in source ? source.appContext : appContext,
      stream: 'stream' in source ? source.stream : streamState,
    });
    latest = values;
    paint(elements.backendValue, elements.backendDot, values.backend);
    paint(elements.streamValue, elements.streamDot, values.stream);
    paint(elements.micValue, null, values.mic);
    paint(elements.sttValue, elements.sttDot, values.stt);
    paint(elements.llmValue, elements.llmDot, values.llm);
    paint(elements.personaValue, null, values.persona);
    paint(elements.targetAppValue, null, values.targetApp);
    paint(elements.latencyValue, null, values.latency);
    paintContact(values.contact);
    paintAppProfile(values.appProfile);
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

  /**
   * The production bootstrap calls this from connectVoiceStatus()'s
   * onConnectionChange/onError. Those two closures were empty before Wave 11B,
   * which is why a severed stream was invisible: the Signal Core just stopped
   * moving. Repaints at once rather than waiting for the next 3s poll — a
   * connection the user is watching drop should be reported when it drops.
   */
  function setStreamState(state, detail) {
    streamState = state ? { state, detail: detail || '' } : null;
    const cell = mapStream(streamState?.state, streamState?.detail);
    paint(elements.streamValue, elements.streamDot, cell);
    if (latest) latest.stream = cell;
    return streamState;
  }

  // Each call is independently guarded: one dead endpoint must degrade its own
  // cell to `—` rather than blanking cells whose data arrived fine.
  async function refresh() {
    if (!api) return render(null);
    // /health is fetched apart from the others because its FAILURE is itself the
    // value the Backend cell reports. Folding it into the same catch-to-null as
    // the rest would erase the difference between "down" and "not asked yet",
    // which is the whole point of the cell -- see mapBackend().
    let health = null;
    let healthReachable = null;
    if (api.fetchHealth) {
      try {
        health = (await api.fetchHealth()) ?? null;
        healthReachable = true;
      } catch (_e) {
        health = null;
        healthReachable = false;
      }
    }
    const [runtime, metrics] = await Promise.all([
      api.fetchRuntimeStatus?.().catch(() => null) ?? null,
      api.fetchMetrics?.().catch(() => null) ?? null,
    ]);
    let profile = null;
    try {
      profile = (await api.fetchProfile?.('Default')) ?? null;
    } catch (_e) {
      profile = null;
    }
    return render({ health, healthReachable, runtime, profile, metrics });
  }

  /**
   * The applicationProfiles feature calls this when the active profile
   * changes, including with null. Repaints immediately rather than waiting for
   * the next poll -- a profile switch the user just caused should be visible
   * when they look, not up to three seconds later.
   */
  function setAppContext(context) {
    appContext = context || null;
    paintAppProfile(mapAppProfile(appContext));
    if (latest) latest.appProfile = mapAppProfile(appContext);
    return appContext;
  }

  return {
    render,
    refresh,
    setContact,
    getContact: () => appliedContact,
    setAppContext,
    getAppContext: () => appContext,
    setStreamState,
    getStreamState: () => streamState,
    getState: () => latest,
  };
}
