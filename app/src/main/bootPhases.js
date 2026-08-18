// OR-02: pure derivation of the startup-splash phase + services list from real
// signals only. No timer in this file ever produces 'failed' -- that value is
// supplied by the caller (main.js) exclusively from waitForHealthy() actually
// rejecting (see sidecar.js), never guessed here. See docs/release/SPLASH_SPEC.md.

const SLOW_THRESHOLD_MS = 7000;

// Copy verbatim from SPLASH_SPEC.md §3. 'slow' and 'failed' get their dynamic
// suffix (elapsed seconds / the real error message) appended by the caller.
const PHASE_COPY = {
  booting: 'Starting BetterFingers',
  'loading-services': 'Initializing local services',
  'preparing-voice': 'Preparing voice systems',
  'almost-ready': 'Almost ready',
  ready: 'Ready',
  slow: 'Still preparing local services',
  failed: 'BetterFingers could not finish starting',
};

// Doctor's runtime_status values that are real, named failures -- never a
// splash-side guess. Kept as a set literal rather than derived from server.py
// so this file has no import-time dependency on the Python backend.
const LLM_FAILURE_STATUSES = new Set([
  'missing_llama_server',
  'missing_model',
  'runtime_link_failure',
  'runtime_outdated',
  'startup_failure',
]);

// Only ever reads what /doctor actually reported; a subsystem doctor didn't
// mention gets no row at all (a row a timer invented is the same lie the
// operator's prototype shipped, just in smaller type).
function deriveServices(doctor) {
  if (!doctor) return [];
  const services = [];

  if (doctor.stt) {
    const stt = doctor.stt;
    let status = 'pending';
    if (stt.loaded) status = 'online';
    else if (stt.initialized) status = 'starting';
    services.push({
      key: 'stt',
      name: 'Speech recognition',
      status,
      message: stt.using_cpu_fallback ? 'Running on CPU (GPU unavailable for this model).' : '',
    });
  }

  if (doctor.llm && doctor.llm.enabled !== false) {
    const llm = doctor.llm;
    let status = 'pending';
    let message = '';
    if (llm.runtime_status === 'ready') {
      status = 'online';
    } else if (LLM_FAILURE_STATUSES.has(llm.runtime_status)) {
      status = 'failed';
      message = llm.runtime_message || llm.last_error || llm.runtime_status;
    } else if (llm.initialized) {
      status = 'starting';
    }
    services.push({ key: 'llm', name: 'Local language model', status, message });
  }

  if (doctor.tts) {
    const tts = doctor.tts;
    let status = 'pending';
    if (tts.loaded) status = 'online';
    else if (tts.initialized) status = 'starting';
    services.push({
      key: 'tts',
      name: 'Voice output',
      status,
      message: tts.fallback ? 'Using a fallback voice engine.' : '',
    });
  }

  if (doctor.hotkeys) {
    const hk = doctor.hotkeys;
    let status = 'pending';
    let message = '';
    if (hk.started && hk.active && hk.keyboard_hooks_ok) {
      status = 'online';
    } else if (hk.started && hk.active && !hk.keyboard_hooks_ok) {
      status = 'failed';
      message = (hk.keyboard_hook_errors || [])[0] || 'Keyboard hook failed.';
    } else if (hk.started) {
      status = 'starting';
    }
    services.push({ key: 'hotkeys', name: 'Global hotkeys', status, message });
  }

  if (doctor.models && (!doctor.llm || doctor.llm.enabled !== false)) {
    const m = doctor.models;
    let status;
    let message = '';
    // `models.default_model_exists` describes the catalog's legacy default,
    // not necessarily the model the user selected. A different selected
    // model can already be verified and serving requests while that default
    // file is absent. Treat the selected model evidence from /doctor.llm as
    // authoritative so the splash cannot wait forever on an unused file.
    const selectedModelExists = doctor.llm && doctor.llm.model_exists === true;
    if (!m.models_dir_exists) {
      status = 'failed';
      message = 'Models directory is missing.';
    } else if (selectedModelExists || m.default_model_exists) {
      status = 'online';
    } else {
      status = 'starting';
    }
    services.push({ key: 'models', name: 'Model files', status, message });
  }

  if (doctor.audio) {
    const a = doctor.audio;
    let status = 'online';
    let message = '';
    if (a.error) {
      status = 'failed';
      message = a.error;
    } else if (Array.isArray(a.devices) && a.devices.length === 0) {
      status = 'failed';
      message = 'No input audio devices detected.';
    }
    services.push({ key: 'audio', name: 'Microphone', status, message });
  }

  if (doctor.platform) {
    // get_capabilities() is a synchronous probe (no load phase of its own) --
    // once /doctor has answered at all, this is resolved.
    services.push({ key: 'platform', name: 'Platform integration', status: 'online', message: '' });
  }

  if (doctor.hardware_tier) {
    services.push({
      key: 'hardware',
      name: 'Hardware',
      status: 'online',
      message: describeHardware(doctor),
    });
  }

  return services;
}

// Tells the user about THEIR machine using the backend's own honest tier
// classification (hardware_report.classify_tier) -- never fabricates
// CUDA/discrete; a machine with only integrated graphics gets exactly that.
function describeHardware(doctor) {
  const tier = doctor && doctor.hardware_tier;
  if (!tier || !tier.label) {
    return 'Checking your hardware…';
  }
  return tier.guidance ? `${tier.label} — ${tier.guidance}` : tier.label;
}

function hasUnresolvedServices(services) {
  return services.some((s) => {
    // Global hotkeys are intentionally lazy: the backend does not start its
    // hook manager merely to answer /health or /doctor. Treating that honest
    // `started: false` report as a boot dependency leaves a healthy app on the
    // splash forever. The row may still describe the current state while the
    // backend is starting, but it must not veto the sidecar health gate.
    if (s.key === 'hotkeys') return false;
    return s.status === 'pending' || s.status === 'starting';
  });
}

// sidecarOutcome is supplied by the caller and must be one of:
//   'pending' -- sidecar.start() has not yet settled
//   'ready'   -- sidecar.start() resolved (waitForHealthy succeeded)
//   'failed'  -- sidecar.start() rejected (waitForHealthy gave up, or the
//                backend process exited before readiness)
// This is the one rule OR-02 exists to enforce: 'failed' here is a pass-through
// of that real outcome, never computed from elapsedMs or any local timer.
function derivePhase({ elapsedMs = 0, doctor = null, sidecarOutcome = 'pending' } = {}) {
  if (sidecarOutcome === 'failed') {
    return 'failed';
  }

  if (sidecarOutcome === 'ready') {
    const services = deriveServices(doctor);
    // waitForHealthy already succeeded; only keep showing progress if /doctor
    // enrichment is available AND says a subsystem is still mid-load. If
    // doctor didn't answer, trust the health check rather than stalling.
    if (!doctor || !hasUnresolvedServices(services)) {
      return 'ready';
    }
  }

  if (elapsedMs > SLOW_THRESHOLD_MS) {
    return 'slow';
  }

  if (!doctor) {
    return 'booting';
  }

  const services = deriveServices(doctor);
  const voicePending = services.some(
    (s) => (s.key === 'stt' || s.key === 'tts') && (s.status === 'pending' || s.status === 'starting'),
  );
  if (voicePending) {
    return 'preparing-voice';
  }

  if (hasUnresolvedServices(services)) {
    return 'loading-services';
  }

  return 'almost-ready';
}

module.exports = {
  SLOW_THRESHOLD_MS,
  PHASE_COPY,
  deriveServices,
  describeHardware,
  derivePhase,
};
