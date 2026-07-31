// OR-02 startup screen controller. Vanilla JS by design -- see splash.html's
// header comment and SPLASH_SPEC.md §2 (no React/Tailwind/framer-motion in
// this codebase, and this is one screen, not a reason to add them).
//
// This module never decides 'failed' on its own: every boot-state object it
// renders (phase, services, error) comes verbatim from main over the
// 'splash:boot' channel (see main.js's pushBootSnapshot()), which in turn only
// sets 'failed' when sidecar.start() actually rejects. This file is a pure
// renderer of whatever main last said.

// Copy verbatim from SPLASH_SPEC.md §3. Duplicated (not required() from
// bootPhases.js) because this is a browser context on the far side of the
// contextIsolation boundary -- main.js's bootPhases.js is CommonJS run only in
// the main process. Keep both copies in sync if the copy ever changes.
const PHASE_COPY = {
  booting: 'Starting BetterFingers',
  'loading-services': 'Initializing local services',
  'preparing-voice': 'Preparing voice systems',
  'almost-ready': 'Almost ready',
  ready: 'Ready',
  slow: 'Still preparing local services',
  failed: 'BetterFingers could not finish starting',
};

function byId(id) {
  return document.getElementById(id);
}

const els = {
  splash: byId('splash'),
  statusText: byId('splashStatusText'),
  activityDots: byId('splashActivityDots'),
  elapsed: byId('splashElapsed'),
  services: byId('splashServices'),
  recovery: byId('splashRecovery'),
  errorMessage: byId('splashErrorMessage'),
  detailsToggle: byId('splashDetailsToggle'),
  detailsChevron: byId('splashDetailsChevron'),
  details: byId('splashErrorDetails'),
  errorCode: byId('splashErrorCode'),
  errorTimestamp: byId('splashErrorTimestamp'),
  errorFullDetails: byId('splashErrorFullDetails'),
  recoveryServices: byId('splashRecoveryServices'),
  retryButton: byId('splashRetryButton'),
  glowPath: byId('horizonGlowPath'),
  mainPath: byId('horizonMainPath'),
  highlightPath: byId('horizonHighlightPath'),
  glowSpot: byId('horizonGlowSpot'),
};

const SERVICE_LABELS = {
  stt: 'Speech recognition',
  llm: 'Local language model',
  tts: 'Voice output',
  hotkeys: 'Global hotkeys',
  models: 'Model files',
  audio: 'Microphone',
  platform: 'Platform integration',
  hardware: 'Hardware',
};

function renderServiceChips(container, services) {
  container.innerHTML = '';
  for (const service of services) {
    const li = document.createElement('li');
    li.className = 'splash__service';
    li.dataset.status = service.status;
    const dot = document.createElement('span');
    dot.className = 'splash__service-dot';
    const label = document.createElement('span');
    label.textContent = SERVICE_LABELS[service.key] || service.name || service.key;
    li.appendChild(dot);
    li.appendChild(label);
    if (service.message) {
      li.title = service.message;
    }
    container.appendChild(li);
  }
}

function renderRecoveryDiagnostics(container, services) {
  container.innerHTML = '';
  for (const service of services) {
    const li = document.createElement('li');
    li.dataset.status = service.status;
    const name = document.createElement('span');
    name.textContent = SERVICE_LABELS[service.key] || service.name || service.key;
    const status = document.createElement('span');
    status.className = 'splash__recovery-diagnostics-status';
    status.textContent = service.status;
    li.appendChild(name);
    li.appendChild(status);
    container.appendChild(li);
  }
}

let detailsOpen = false;

function setDetailsOpen(open) {
  detailsOpen = open;
  els.details.hidden = !open;
  els.detailsToggle.setAttribute('aria-expanded', String(open));
  els.detailsChevron.textContent = open ? '▴' : '▾';
}

els.detailsToggle.addEventListener('click', () => setDetailsOpen(!detailsOpen));

let retryInFlight = false;
els.retryButton.addEventListener('click', async () => {
  if (retryInFlight) return;
  retryInFlight = true;
  els.retryButton.disabled = true;
  try {
    await window.betterFingersSplash?.retry?.();
  } finally {
    retryInFlight = false;
    els.retryButton.disabled = false;
  }
});

let lastServices = [];

function render(snapshot) {
  if (!snapshot) return;
  const phase = snapshot.phase || 'booting';
  els.splash.dataset.phase = phase;

  const statusText = phase === 'slow' ? PHASE_COPY.slow : (PHASE_COPY[phase] || phase);
  els.statusText.textContent = statusText;

  if (phase === 'slow') {
    els.elapsed.hidden = false;
    els.elapsed.textContent = `Taking longer than expected (${Math.round((snapshot.elapsedMs || 0) / 1000)}s elapsed)...`;
  } else {
    els.elapsed.hidden = true;
  }

  lastServices = Array.isArray(snapshot.services) ? snapshot.services : [];
  renderServiceChips(els.services, lastServices);

  const isFailed = phase === 'failed';
  els.recovery.hidden = !isFailed;
  if (isFailed) {
    const error = snapshot.error || {};
    els.errorMessage.textContent = error.message
      || 'A required local system background service failed to initialize.';
    els.errorCode.textContent = `Error: ${error.code || 'ERR_BACKEND_START_FAILED'}`;
    els.errorTimestamp.textContent = `Timestamp: ${error.timestamp || new Date().toISOString()}`;
    els.errorFullDetails.textContent = error.details || '';
    els.errorFullDetails.style.display = error.details ? '' : 'none';
    renderRecoveryDiagnostics(els.recoveryServices, lastServices);
  }
}

// --- Boot-state channel ------------------------------------------------------

if (window.betterFingersSplash) {
  window.betterFingersSplash.onBootEvent((snapshot) => render(snapshot));
  // A first paint from the pull path, in case boot already started before this
  // listener attached (main starts pushing immediately on cold boot).
  window.betterFingersSplash.getState().then((snapshot) => {
    if (snapshot) render(snapshot);
  }).catch(() => {});
} else {
  // Loaded outside Electron (e.g. a bare file:// open during manual QA) --
  // render a static booting frame rather than throwing.
  render({ phase: 'booting', elapsedMs: 0, services: [], error: null });
}

// --- Horizon pulse animation (ported from HorizonPulseSvg.tsx) -------------
//
// Geometry, timings and colour intent kept close to the original: a 1.2s
// heartbeat curve fired every 3s, computed per-frame exactly as the source
// did (bell-curve amplitude, travelling ripple past progress 0.4). Reduced
// motion renders the flat calm horizon the original also falls back to.

const PULSE_INTERVAL_MS = 3000;
const PULSE_DURATION_MS = 1200;
const VIEW_WIDTH = 1200;
const BASELINE_Y = 80;
const CENTER_X = 600;

function prefersReducedMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function flatPath() {
  return `M 0 ${BASELINE_Y} L ${VIEW_WIDTH} ${BASELINE_Y}`;
}

function horizonPath(progress, intensity) {
  if (prefersReducedMotion() || progress <= 0.05 || progress >= 0.95) {
    return flatPath();
  }

  let pulseAmp = 0;
  let travelOffset = 0;

  if (progress > 0.05 && progress <= 0.4) {
    const norm = (progress - 0.05) / 0.35;
    pulseAmp = Math.sin(norm * Math.PI) * 42 * intensity;
  } else if (progress > 0.4 && progress < 0.95) {
    const norm = (progress - 0.4) / 0.55;
    pulseAmp = Math.sin((1 - norm) * Math.PI) * 28 * intensity;
    travelOffset = norm * 120;
  }

  const x1 = CENTER_X - 90 - travelOffset * 0.3;
  const x2 = CENTER_X - 50 - travelOffset * 0.2;
  const x3 = CENTER_X - 20 - travelOffset * 0.1;
  const xPeak = CENTER_X;
  const x4 = CENTER_X + 20 + travelOffset * 0.1;
  const x5 = CENTER_X + 50 + travelOffset * 0.2;
  const x6 = CENTER_X + 90 + travelOffset * 0.3;

  const yPeak = BASELINE_Y - pulseAmp;
  const yDip1 = BASELINE_Y + pulseAmp * 0.25;
  const yDip2 = BASELINE_Y + pulseAmp * 0.45;
  const yRec = BASELINE_Y - pulseAmp * 0.2;

  return [
    `M 0 ${BASELINE_Y}`,
    `L ${x1} ${BASELINE_Y}`,
    `C ${x1 + 15} ${BASELINE_Y}, ${x2 - 10} ${yDip1}, ${x2} ${yDip1}`,
    `C ${x2 + 10} ${yDip1}, ${x3 - 5} ${yPeak}, ${xPeak} ${yPeak}`,
    `C ${xPeak + 5} ${yPeak}, ${x4 - 10} ${yDip2}, ${x4} ${yDip2}`,
    `C ${x4 + 10} ${yDip2}, ${x5 - 15} ${yRec}, ${x5} ${yRec}`,
    `C ${x5 + 15} ${yRec}, ${x6 - 15} ${BASELINE_Y}, ${x6} ${BASELINE_Y}`,
    `L ${VIEW_WIDTH} ${BASELINE_Y}`,
  ].join(' ');
}

let pulseFrame = null;
let pulseTimer = null;

function paintPulse(progress) {
  const reduced = prefersReducedMotion();
  const d = horizonPath(progress, 1.0);
  els.glowPath.setAttribute('d', d);
  els.mainPath.setAttribute('d', d);
  els.highlightPath.setAttribute('d', d);

  if (reduced) {
    els.highlightPath.style.strokeOpacity = '0';
    els.glowSpot.setAttribute('r', '180');
    els.glowSpot.style.opacity = '0.35';
    return;
  }

  const highlightVisible = progress > 0.1 && progress < 0.85;
  els.highlightPath.style.strokeOpacity = highlightVisible
    ? String(Math.max(0, 0.85 * (1 - Math.abs(progress - 0.35) * 2)))
    : '0';

  const glowOpacity = 0.25 + Math.sin(progress * Math.PI) * 0.5;
  const glowRadius = 160 + Math.sin(progress * Math.PI) * 80;
  els.glowSpot.setAttribute('r', String(glowRadius));
  els.glowSpot.style.opacity = String(glowOpacity);
}

function runHeartbeat() {
  if (els.splash.dataset.phase === 'failed') return;

  if (prefersReducedMotion()) {
    paintPulse(0);
    return;
  }

  const start = performance.now();
  const step = (now) => {
    const elapsed = now - start;
    const progress = Math.min(elapsed / PULSE_DURATION_MS, 1.0);
    paintPulse(progress);
    if (progress < 1.0) {
      pulseFrame = requestAnimationFrame(step);
    } else {
      paintPulse(0);
    }
  };
  pulseFrame = requestAnimationFrame(step);
}

function startPulseLoop() {
  stopPulseLoop();
  runHeartbeat();
  pulseTimer = setInterval(runHeartbeat, PULSE_INTERVAL_MS);
}

function stopPulseLoop() {
  if (pulseFrame) cancelAnimationFrame(pulseFrame);
  if (pulseTimer) clearInterval(pulseTimer);
  pulseFrame = null;
  pulseTimer = null;
}

if (prefersReducedMotion()) {
  paintPulse(0);
} else {
  startPulseLoop();
}

if (window.matchMedia) {
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change', (event) => {
    if (event.matches) {
      stopPulseLoop();
      paintPulse(0);
    } else {
      startPulseLoop();
    }
  });
}
