// Runtime status + bootstrap helpers extracted from main.js (Phase 1, A1.7).
// main.js stays the composition root: it owns the DOM element lookups, wires
// the beforeunload cleanup and the single bootstrap() call at the bottom of
// the file in the same place/order as before, and supplies this module the
// other features' refresh/init functions as hooks so bootstrap can orchestrate
// the exact same startup sequence it always has.
import {
  fetchHealth,
  fetchRuntimeStatus,
  normalizeHealthPayload,
  connectVoiceStatus,
} from '../api/backend.js';

export function getTranscriberRuntimeState(runtime) {
  if (runtime?.transcriber_loaded === true) {
    return { text: 'loaded', tone: 'success' };
  }

  if (runtime?.transcriber_initialized === true) {
    return { text: 'initialized', tone: 'warning' };
  }

  if (!runtime || typeof runtime !== 'object') {
    return { text: 'checking…', tone: 'warning', detail: 'Runtime status is not available yet.' };
  }

  if (!Object.prototype.hasOwnProperty.call(runtime, 'transcriber_loaded')
    && !Object.prototype.hasOwnProperty.call(runtime, 'transcriber_initialized')) {
    return { text: 'checking…', tone: 'warning', detail: 'Waiting for transcriber status.' };
  }

  return { text: 'unloaded', tone: 'danger' };
}

const LLM_REASON_KEYS = [
  'llm_error',
  'llm_reason',
  'llm_runtime_message',
  'llm_last_error',
];

function firstRuntimeReason(runtime, keys) {
  for (const key of keys) {
    const value = runtime?.[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export function getLlmRuntimeState(runtime) {
  if (!runtime || typeof runtime !== 'object') {
    return { text: 'checking…', tone: 'warning', detail: 'Runtime status is not available yet.' };
  }

  // `llm_ready` is the runtime probe. Never infer readiness from the saved
  // residency setting, and never turn `llm_initialized` into "ready": an
  // initialized engine can still be loading or can have failed to start.
  if (runtime.llm_ready === true) {
    return { text: 'ready', tone: 'success' };
  }

  const reason = firstRuntimeReason(runtime, LLM_REASON_KEYS);
  if (runtime.llm_ready === false) {
    const fallbackReason = runtime.llm_initialized === true
      ? 'LLM runtime is initialized but not ready.'
      : 'LLM runtime is not initialized.';
    return {
      text: runtime.llm_initialized === true ? 'not ready' : 'unloaded',
      tone: runtime.llm_initialized === true ? 'warning' : 'danger',
      detail: reason || fallbackReason,
    };
  }

  if (runtime.llm_initialized === true) {
    return {
      text: 'initialized',
      tone: 'warning',
      detail: reason || 'LLM runtime is initialized; waiting for readiness.',
    };
  }

  if (!Object.prototype.hasOwnProperty.call(runtime, 'llm_ready')
    && !Object.prototype.hasOwnProperty.call(runtime, 'llm_initialized')) {
    return { text: 'checking…', tone: 'warning', detail: 'Waiting for LLM status.' };
  }

  return { text: 'unloaded', tone: 'danger' };
}

export function getHotkeyRuntimeState(runtime) {
  if (!runtime || typeof runtime !== 'object') {
    return { text: 'checking…', tone: 'warning', detail: 'Waiting for runtime status.' };
  }

  const errors = Array.isArray(runtime.hotkey_keyboard_hook_errors)
    ? runtime.hotkey_keyboard_hook_errors.filter((error) => typeof error === 'string' && error.trim())
    : [];
  if (runtime.hotkey_manager_started === false) {
    return { text: 'unavailable', tone: 'danger', detail: 'Global hotkey manager is not started.' };
  }
  if (runtime.hotkey_keyboard_hooks_ok === false || errors.length) {
    return {
      text: 'unavailable',
      tone: 'danger',
      detail: errors[0] || 'Global keyboard hooks failed to initialize.',
    };
  }
  if (runtime.hotkey_manager_started === true && runtime.hotkey_keyboard_hooks_ok === true) {
    return { text: 'ready', tone: 'success' };
  }

  // An empty-but-valid response is not a failure. It is simply not enough
  // evidence to claim that global hotkeys are ready yet.
  return { text: 'checking…', tone: 'warning', detail: 'Waiting for hotkey status.' };
}

// Banner states worth interrupting the user for, mapped to a short title.
const BACKEND_BANNER_TITLES = {
  version_mismatch: 'Backend version mismatch:',
  unhealthy: 'Backend not responding:',
  restarting: 'Restarting backend:',
  crashed: 'Backend stopped:',
};

/**
 * @param {object} deps
 * @param {object} deps.elements runtime/bootstrap-related DOM element references (looked up by main.js)
 * @param {object} deps.ui shared render helpers: setBadgeState, renderDetailList, showToast
 * @param {object} deps.hooks cross-feature callbacks used by loadInitialData/bootstrap (see below)
 */
export function createRuntimeFeature({ elements, ui, hooks }) {
  const els = elements;
  const { setBadgeState, renderDetailList, showToast, setMessage } = ui;
  const {
    refreshCapabilities, refreshDrafts, renderDraft, refreshOutputSettings, refreshProfiles,
    refreshModels, refreshDiagnostics, refreshDoctor, refreshSidecarLogs, refreshPttAvailability,
    onVoiceStatusMessage, initFeaturePanels,
  } = hooks;

  let healthRefreshTimer = null;
  let websocketHandle = null;
  // The renderer loads from Vite instantly, but the Python sidecar takes a couple
  // of seconds to come up — so the very first data load can race it and every
  // fetch fails with ERR_CONNECTION_REFUSED (leaving settings fields empty,
  // personas/voices unloaded). We track whether that load succeeded so it can be
  // retried once the backend is actually reachable (see the sidecar-status hook).
  let initialDataLoaded = false;
  let runtimeSnapshotLoaded = false;

  function clearRuntimeDetail() {
    if (els.llmStatusEl) {
      els.llmStatusEl.removeAttribute?.('title');
      els.llmStatusEl.removeAttribute?.('aria-label');
    }
  }

  function paintRuntimeDetail(element, state) {
    if (!element) return;
    if (state.detail) {
      element.title = state.detail;
      element.setAttribute?.('aria-label', `${state.text}: ${state.detail}`);
    } else {
      element.removeAttribute?.('title');
      element.removeAttribute?.('aria-label');
    }
  }

  function markRuntimePending() {
    // A delayed status probe is not proof that the backend or hotkeys are
    // offline. Preserve a known-good snapshot while a later poll is pending;
    // on first load, use an explicit checking state instead of a false error.
    if (!runtimeSnapshotLoaded) {
      setBadgeState(els.transcriberStatusEl, 'checking…', 'warning');
      setBadgeState(els.llmStatusEl, 'checking…', 'warning');
      clearRuntimeDetail();
    }
    if (els.recordingControlStatusEl && !runtimeSnapshotLoaded) {
      els.recordingControlStatusEl.textContent = 'Checking global hotkeys…';
    }
  }

  function updateRuntimeTopCards(runtime) {
    const transcriber = getTranscriberRuntimeState(runtime);
    const llm = getLlmRuntimeState(runtime);

    setBadgeState(els.transcriberStatusEl, transcriber.text, transcriber.tone);
    setBadgeState(els.llmStatusEl, llm.text, llm.tone);
    paintRuntimeDetail(els.llmStatusEl, llm);

    const recording = Boolean(runtime?.recording_active);
    if (els.toggleRecordingButton) {
      els.toggleRecordingButton.textContent = recording ? 'Stop Recording' : 'Start Recording';
      els.toggleRecordingButton.dataset.recording = recording ? 'true' : 'false';
    }
    if (els.recordingControlStatusEl) {
      const hotkeys = getHotkeyRuntimeState(runtime);
      if (recording) {
        els.recordingControlStatusEl.textContent = 'Recording now. Press Stop Recording when finished.';
      } else if (hotkeys.text === 'unavailable') {
        els.recordingControlStatusEl.textContent = `Global hotkeys unavailable: ${hotkeys.detail}`;
      } else if (hotkeys.text === 'checking…') {
        els.recordingControlStatusEl.textContent = 'Checking global hotkeys…';
      } else {
        els.recordingControlStatusEl.textContent = 'Ready. Hotkeys or the dashboard button can start recording.';
      }
    }
  }

  async function refreshHealth() {
    try {
      const payload = await fetchHealth();
      const health = normalizeHealthPayload(payload);

      setBadgeState(els.backendStatusEl, health.backendStatus, health.backendStatus === 'active' ? 'success' : 'warning');
      if (els.backendDetailEl) {
        els.backendDetailEl.textContent = 'FastAPI /health responded successfully';
      }
      return true;
    } catch (error) {
      // The Electron shell spawns the sidecar, so a failed /health poll almost
      // always means "still starting" — show a calm amber state rather than three
      // alarming red "offline" cards at every normal boot.
      setBadgeState(els.backendStatusEl, 'starting…', 'warning');
      if (els.backendDetailEl) {
        els.backendDetailEl.textContent = 'Waiting for the Python backend to start';
      }
      setBadgeState(els.transcriberStatusEl, 'starting…', 'warning');
      setBadgeState(els.llmStatusEl, 'starting…', 'warning');
      return false;
    }
  }

  async function refreshRuntime() {
    const runtime = await fetchRuntimeStatus();
    runtimeSnapshotLoaded = true;
    updateRuntimeTopCards(runtime);
    renderDetailList(els.runtimeStatusListEl, runtime, [
      'transcriber_initialized',
      'transcriber_loaded',
      'llm_initialized',
      'llm_ready',
      'llm_error',
      'llm_reason',
      'llm_runtime_message',
      'llm_last_error',
      'hotkey_manager_started',
      'hotkey_keyboard_hooks_ok',
      'recording_active',
    ]);
    return runtime;
  }

  function updateBackendBanner(status) {
    if (!els.versionMismatchBanner) {
      return;
    }
    const title = BACKEND_BANNER_TITLES[status?.state];
    if (title) {
      if (els.backendBannerTitleEl) {
        els.backendBannerTitleEl.textContent = title;
      }
      if (els.backendBannerMessageEl) {
        els.backendBannerMessageEl.textContent =
          status.message || 'Some features may behave unexpectedly.';
      }
      els.versionMismatchBanner.dataset.tone = status.state === 'crashed' ? 'danger' : 'warning';
      els.versionMismatchBanner.classList.remove('hidden');
    } else {
      els.versionMismatchBanner.classList.add('hidden');
    }
  }

  async function refreshSidecarStatus() {
    if (!els.sidecarStatusEl) {
      return null;
    }

    const status = await window.betterFingers?.getSidecarStatus?.();
    if (!status) {
      els.sidecarStatusEl.textContent = 'Sidecar status is unavailable.';
      els.sidecarStatusEl.dataset.tone = 'warning';
      return null;
    }

    els.sidecarStatusEl.textContent = [
      `state: ${status.state ?? 'unknown'}`,
      `owns process: ${status.ownsProcess ? 'yes' : 'no'}`,
      `pid: ${status.pid ?? 'none'}`,
      status.message ?? '',
    ].filter(Boolean).join('\n');

    const dangerStates = new Set(['error', 'crashed']);
    if (dangerStates.has(status.state)) {
      els.sidecarStatusEl.dataset.tone = 'danger';
    } else if (status.state === 'ready') {
      els.sidecarStatusEl.dataset.tone = 'success';
    } else {
      els.sidecarStatusEl.dataset.tone = 'warning';
    }

    updateBackendBanner(status);

    if (dangerStates.has(status.state) || status.state === 'stopped') {
      refreshSidecarLogs().catch(() => {});
    }

    return status;
  }

  function updateConnectionPill(state, detail) {
    if (els.wsConnectionEl) {
      els.wsConnectionEl.textContent = detail ? `${state} · ${detail}` : state;
      els.wsConnectionEl.dataset.state = state;
    }
  }

  // Every panel the initial load fans out to, by name. `pendingInitialLoaders`
  // holds the names that have not succeeded yet: the health poll retries
  // exactly those, so a panel that lost the startup race (models, doctor,
  // drafts…) heals on a later poll instead of staying empty until the user
  // manually refreshes it — previously only a profiles failure ever triggered
  // a retry, and it re-ran the whole load.
  const initialLoaders = [
    {
      name: 'runtime',
      run: () => refreshRuntime(),
      onError: () => {
        markRuntimePending();
        if (!runtimeSnapshotLoaded) {
          renderDetailList(els.runtimeStatusListEl, {});
        }
      },
    },
    {
      name: 'capabilities',
      run: () => refreshCapabilities(),
      onError: () => {
        renderDetailList(els.capabilitiesListEl, {});
      },
    },
    {
      name: 'drafts',
      run: () => refreshDrafts(),
      onError: () => {
        renderDraft(null);
      },
    },
    {
      name: 'output-settings',
      run: () => refreshOutputSettings(),
      onError: () => {
        if (els.outputSettingsSummaryEl) {
          els.outputSettingsSummaryEl.textContent = 'Output settings unavailable.';
        }
      },
    },
    {
      name: 'profiles',
      run: () => refreshProfiles(),
      onError: (error) => {
        setMessage(els.profileMessageEl, `Profiles unavailable: ${error.message}`, 'danger');
      },
    },
    {
      name: 'models',
      run: () => refreshModels(),
      onError: (error) => {
        setMessage(els.modelMessageEl, `Models unavailable: ${error.message}`, 'danger');
      },
    },
    { name: 'diagnostics', run: () => refreshDiagnostics() },
    { name: 'doctor', run: () => refreshDoctor() },
    { name: 'sidecar-logs', run: () => refreshSidecarLogs() },
    { name: 'ptt-availability', run: () => refreshPttAvailability() },
  ];
  const pendingInitialLoaders = new Set(initialLoaders.map((loader) => loader.name));
  let initialLoadInFlight = false;

  async function loadInitialData({ onlyPending = false } = {}) {
    // A pass can outlive the 3s poll interval (chained request timeouts), so
    // overlapping passes would stampede the same endpoints. Skip instead.
    if (initialLoadInFlight) {
      return initialDataLoaded;
    }
    if (!onlyPending) {
      for (const loader of initialLoaders) {
        pendingInitialLoaders.add(loader.name);
      }
    }
    const toRun = initialLoaders.filter((loader) => pendingInitialLoaders.has(loader.name));
    if (!toRun.length) {
      return initialDataLoaded;
    }
    initialLoadInFlight = true;
    try {
      await Promise.allSettled(toRun.map((loader) =>
        loader.run()
          .then(() => {
            pendingInitialLoaders.delete(loader.name);
          })
          .catch((error) => {
            loader.onError?.(error);
          }),
      ));
    } finally {
      initialLoadInFlight = false;
    }
    // Consider the load a success only if the profile settings actually loaded —
    // that's what backs the settings form (and its save-blocking validation).
    initialDataLoaded = !pendingInitialLoaders.has('profiles');
    return initialDataLoaded;
  }

  async function bootstrap() {
    await refreshHealth();
    await loadInitialData();

    const pollHealth = () => {
      refreshHealth();
      refreshSidecarStatus().catch(() => {});
      refreshRuntime().catch(() => {
        markRuntimePending();
      });
      // Fallback: if the startup race left any panel un-loaded and we never
      // caught the sidecar 'ready' push, retry exactly those panels each poll.
      if (pendingInitialLoaders.size) {
        loadInitialData({ onlyPending: true }).catch(() => {});
      }
    };

    healthRefreshTimer = setInterval(() => {
      // Skip while the window is hidden/minimized — no point polling a UI
      // nobody can see.
      if (document.hidden) return;
      pollHealth();
    }, 3000);

    // Catch up immediately when the window becomes visible again instead of
    // waiting up to 3s for the next tick.
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        pollHealth();
      }
    });

    // React to sidecar lifecycle pushes (crash / restart / recovery) immediately
    // instead of waiting for the next poll tick.
    let lastSidecarState = null;
    window.betterFingers?.onSidecarStatus?.((status) => {
      if (!status) return;
      updateBackendBanner(status);
      refreshSidecarStatus().catch(() => {});
      // When the backend first becomes reachable (or recovers after a restart),
      // (re)load the data that failed during the startup race so the settings
      // form, personas and voices actually populate.
      const becameReady = status.state === 'ready' && lastSidecarState !== 'ready';
      lastSidecarState = status.state;
      if (becameReady) {
        loadInitialData().catch(() => {});
      }
      // These pushes are transition-based, so toasting here won't spam.
      if (status.state === 'crashed') {
        showToast(status.message || 'The backend stopped and could not recover.', 'danger', 0);
      } else if (status.state === 'unhealthy') {
        showToast(status.message || 'The backend stopped responding; recovering…', 'warning');
      }
    });

    websocketHandle = connectVoiceStatus({
      onConnectionChange: updateConnectionPill,
      onMessage: onVoiceStatusMessage,
      onError: (error) => {
        updateConnectionPill('error', error.message);
      },
    });

    initFeaturePanels();
  }

  function teardown() {
    if (healthRefreshTimer) {
      clearInterval(healthRefreshTimer);
    }

    if (websocketHandle) {
      websocketHandle.close();
    }
  }

  return {
    refreshHealth,
    refreshRuntime,
    refreshSidecarStatus,
    updateBackendBanner,
    updateConnectionPill,
    loadInitialData,
    bootstrap,
    teardown,
  };
}
