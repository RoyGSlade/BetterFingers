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

function getTranscriberRuntimeState(runtime) {
  if (runtime?.transcriber_loaded) {
    return { text: 'loaded', tone: 'success' };
  }

  if (runtime?.transcriber_initialized) {
    return { text: 'initialized', tone: 'warning' };
  }

  return { text: 'unloaded', tone: 'danger' };
}

function getLlmRuntimeState(runtime) {
  if (runtime?.llm_ready) {
    return { text: 'ready', tone: 'success' };
  }

  if (runtime?.llm_initialized) {
    return { text: 'initialized', tone: 'warning' };
  }

  return { text: 'unloaded', tone: 'danger' };
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

  function updateRuntimeTopCards(runtime) {
    const transcriber = getTranscriberRuntimeState(runtime);
    const llm = getLlmRuntimeState(runtime);

    setBadgeState(els.transcriberStatusEl, transcriber.text, transcriber.tone);
    setBadgeState(els.llmStatusEl, llm.text, llm.tone);

    const recording = Boolean(runtime?.recording_active);
    if (els.toggleRecordingButton) {
      els.toggleRecordingButton.textContent = recording ? 'Stop Recording' : 'Start Recording';
      els.toggleRecordingButton.dataset.recording = recording ? 'true' : 'false';
    }
    if (els.recordingControlStatusEl) {
      const hookErrors = Array.isArray(runtime?.hotkey_keyboard_hook_errors) ? runtime.hotkey_keyboard_hook_errors : [];
      if (recording) {
        els.recordingControlStatusEl.textContent = 'Recording now. Press Stop Recording when finished.';
      } else if (hookErrors.length) {
        els.recordingControlStatusEl.textContent = `Global hotkeys unavailable: ${hookErrors[0]}`;
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
    updateRuntimeTopCards(runtime);
    renderDetailList(els.runtimeStatusListEl, runtime, [
      'transcriber_initialized',
      'transcriber_loaded',
      'llm_initialized',
      'llm_ready',
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

  async function loadInitialData() {
    const results = await Promise.allSettled([
      refreshRuntime().catch(() => {
        setBadgeState(els.transcriberStatusEl, 'offline', 'danger');
        setBadgeState(els.llmStatusEl, 'offline', 'danger');
        renderDetailList(els.runtimeStatusListEl, {});
        throw new Error('runtime');
      }),
      refreshCapabilities().catch(() => {
        renderDetailList(els.capabilitiesListEl, {});
        throw new Error('capabilities');
      }),
      refreshDrafts().catch(() => {
        renderDraft(null);
        throw new Error('drafts');
      }),
      refreshOutputSettings().catch(() => {
        if (els.outputSettingsSummaryEl) {
          els.outputSettingsSummaryEl.textContent = 'Output settings unavailable.';
        }
        throw new Error('output-settings');
      }),
      refreshProfiles().catch((error) => {
        setMessage(els.profileMessageEl, `Profiles unavailable: ${error.message}`, 'danger');
        throw error;
      }),
      refreshModels().catch((error) => {
        setMessage(els.modelMessageEl, `Models unavailable: ${error.message}`, 'danger');
        throw error;
      }),
      refreshDiagnostics().catch(() => {
        throw new Error('diagnostics');
      }),
      refreshDoctor().catch(() => {
        throw new Error('doctor');
      }),
      refreshSidecarLogs().catch(() => {
        throw new Error('sidecar-logs');
      }),
      refreshPttAvailability().catch(() => {
        throw new Error('ptt-availability');
      }),
    ]);
    // Consider the load a success only if the profile settings actually loaded —
    // that's what backs the settings form (and its save-blocking validation).
    const profilesResult = results[4];
    initialDataLoaded = profilesResult.status === 'fulfilled';
    return initialDataLoaded;
  }

  async function bootstrap() {
    await refreshHealth();
    await loadInitialData();

    const pollHealth = () => {
      refreshHealth();
      refreshSidecarStatus().catch(() => {});
      refreshRuntime().catch(() => {
        setBadgeState(els.transcriberStatusEl, 'offline', 'danger');
        setBadgeState(els.llmStatusEl, 'offline', 'danger');
      });
      // Fallback: if the startup race left us un-loaded and we never caught the
      // sidecar 'ready' push, retry the load as soon as a poll succeeds.
      if (!initialDataLoaded) {
        loadInitialData().catch(() => {});
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
