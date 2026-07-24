// First-run "get set up" experience (W8).
//
// The problem: a fresh install needs multi-GB downloads (llama-server
// runtime, an LLM GGUF, a Whisper model) before BetterFingers can do
// anything useful. Today those live behind per-model panels on the Models
// tab with no cohesive guidance, so a brand-new user who lands on the
// Dashboard sees empty draft panes and disabled buttons and no obvious next
// step. This module renders a single "Get BetterFingers set up" panel at the
// top of the Dashboard tab that:
//   - detects what's missing (runtime / LLM / Whisper) from EXISTING backend
//     endpoints only (no new routes): /health, /runtime/status, /models/llm,
//     /models/whisper, plus the LLM download-state poller already used by
//     the Models tab;
//   - wires Download buttons straight to the existing download endpoints
//     (downloadLlmModel/downloadWhisperModel) with live progress;
//   - surfaces the exact backend message on failure -- including W3's hard
//     disk-space gate (InsufficientDiskSpaceError -> {ok:false, message:
//     "Not enough disk space..."}) -- instead of a generic "download
//     failed";
//   - lets the user Continue once ready, or dismiss ("I'll set this up
//     myself") to go straight to the normal UI / Models tab.
//
// Deliberately an in-page panel, not another full-screen overlay: the app
// already has a first-run onboarding modal (policy -> tour -> models,
// #onboardingOverlay, z-index 10000) and the Persona Foundry modal (z-index
// 9000). Stacking a third modal on top invites focus-trap and z-index bugs.
// Living inside #tabDashboard means it's simply hidden behind the onboarding
// backdrop while onboarding is active, and appears normally once the user is
// looking at the Dashboard -- no additional coordination needed.
//
// Pure helpers (no DOM) are exported for unit testing, matching this repo's
// convention (see lib/wipeSummary.mjs, features/voiceStudio.js).
import * as backendApi from '../api/backend.js';

const DISMISS_KEY = 'bf_first_run_dismissed';
const POLL_MS = 900;
// Statuses the LLM/Whisper download-state payloads use that are worth
// showing a progress row for (mirrors main.js's renderLlmDownloadProgress).
const VISIBLE_DOWNLOAD_STATUSES = new Set([
  'starting', 'downloading', 'complete', 'ready', 'already_installed', 'error',
]);

// --- Pure helpers (no DOM, no network) --------------------------------------

/** Bytes -> a short human string ("1.2 GB"), or '' for falsy/invalid input. */
export function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '';
  }
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

// GET /models/llm's payload -> the pieces the first-run checklist cares
// about. A model can be *installed* yet not *ready* (llama-server binary
// present but too old for the model) -- same distinction main.js's
// renderModelOverview already draws for the Models tab.
export function summarizeLlmState(llmModels) {
  const models = Array.isArray(llmModels?.models) ? llmModels.models : [];
  const selectedId = llmModels?.selected_model_id ?? null;
  const selected = models.find((model) => model.id === selectedId) || null;
  return {
    selectedId,
    name: selected?.name ?? selectedId ?? null,
    installed: Boolean(selected?.installed),
    ready: selected?.ready === true,
    sizeMb: Number(selected?.size_mb || 0),
    runtimeExists: Boolean(llmModels?.llama_server_exists),
  };
}

// GET /models/whisper's payload -> the pieces the checklist cares about.
// "Ready" only requires SOME installed Whisper model, not necessarily the
// currently-selected one -- the app can still transcribe with any installed
// model even if the selected one was since removed.
export function summarizeWhisperState(whisperModels) {
  const models = Array.isArray(whisperModels?.models) ? whisperModels.models : [];
  const selectedSize = whisperModels?.selected_model_size ?? null;
  const selected = models.find((model) => model.model_size === selectedSize) || null;
  const installedCount = models.filter((model) => model.installed).length;
  return {
    selectedSize,
    selectedInstalled: Boolean(selected?.installed),
    installedCount,
    anyInstalled: installedCount > 0,
  };
}

// The master "what's missing" computation, built only from already-fetched
// endpoint payloads (health/runtime/llmModels/whisperModels may each be null
// if their fetch failed -- every field access below is defensive).
export function computeFirstRunStatus({ health, runtime, llmModels, whisperModels } = {}) {
  const backendReachable = Boolean(health || runtime || llmModels || whisperModels);
  const llm = summarizeLlmState(llmModels);
  const whisper = summarizeWhisperState(whisperModels);

  const runtimeReady = llm.runtimeExists;
  const llmReady = llm.installed && (llm.ready || Boolean(runtime?.llm_ready));
  const whisperReady = whisper.selectedInstalled || whisper.anyInstalled;

  const missing = [];
  if (!backendReachable) {
    missing.push({ key: 'backend', label: 'Waiting for the local backend to respond.' });
  }
  if (!runtimeReady) {
    missing.push({
      key: 'runtime',
      label: 'The llama-server runtime is not installed yet (it installs automatically with the language model).',
    });
  }
  if (!llm.installed) {
    missing.push({ key: 'llm', label: 'No language model is installed.' });
  } else if (!llmReady) {
    missing.push({
      key: 'llm-not-ready',
      label: `${llm.name || 'The language model'} is installed but not ready to run yet.`,
    });
  }
  if (!whisperReady) {
    missing.push({ key: 'whisper', label: 'No speech-to-text (Whisper) model is installed.' });
  }

  const ready = backendReachable && runtimeReady && llmReady && whisperReady;

  return {
    ready,
    backendReachable,
    missing,
    llm: { ...llm, ready: llmReady },
    whisper: { ...whisper, ready: whisperReady },
    runtime: { exists: runtimeReady },
  };
}

// Prefer the backend's own message (e.g. W3's disk-space gate text) over a
// generic fallback -- callers must never overwrite a specific backend
// message with "download failed".
export function formatDownloadOutcomeMessage(result, fallback) {
  const message = result && typeof result === 'object' ? result.message : null;
  const trimmed = typeof message === 'string' ? message.trim() : '';
  return trimmed || fallback;
}

// Detects model_manager.py's InsufficientDiskSpaceError message shape
// ("Not enough disk space to download this file: need X GB free, only Y GB
// available at ...") so the UI can show a dedicated disk-space warning
// instead of treating it as just another failed-download toast.
export function isDiskSpaceMessage(message) {
  return typeof message === 'string' && /not enough disk space|disk space.*(free|available)/i.test(message);
}

// --- DOM-wiring feature ------------------------------------------------------

/**
 * @param {object} deps
 * @param {object} deps.elements DOM element references looked up by main.js (see index.html's
 *   #firstRunPanel block). Every access below is optional-chained so a missing element (or a
 *   stub in tests) never throws.
 * @param {object} deps.ui shared render helpers: setMessage(el, text, tone), showToast(text, tone, durationMs)
 * @param {object} deps.hooks cross-feature callbacks:
 *   - afterModelsChanged(): called after a successful download so the Models tab / dashboard
 *     badges (owned by main.js) refresh too. Optional.
 *   - goToModelsTab(): called when the user dismisses to configure manually. Optional.
 * @param {object} [deps.api] backend.js module (or a stub) -- override point for unit tests.
 * @param {object} [deps.storage] Web Storage-shaped object (getItem/setItem/removeItem) used to
 *   persist the dismiss flag. Defaults to the real `localStorage` when present. Injectable so
 *   tests don't have to fight over the real global (and so a build with no storage at all just
 *   degrades to "always show until ready", never throws).
 */
export function createFirstRunFeature({
  elements,
  ui = {},
  hooks = {},
  api = backendApi,
  storage = (typeof localStorage !== 'undefined' ? localStorage : null),
} = {}) {
  const els = elements || {};
  const { setMessage, showToast } = ui;
  const { afterModelsChanged, goToModelsTab } = hooks;

  let lastStatus = null;
  let initialized = false;

  function isDismissed() {
    try {
      return Boolean(storage && storage.getItem(DISMISS_KEY) === 'true');
    } catch (_error) {
      return false;
    }
  }

  function setDismissed(value) {
    try {
      if (!storage) return;
      if (value) {
        storage.setItem(DISMISS_KEY, 'true');
      } else {
        storage.removeItem(DISMISS_KEY);
      }
    } catch (_error) {
      // Non-fatal; the panel may just reappear next launch.
    }
  }

  function show() {
    if (els.panelEl) els.panelEl.hidden = false;
  }

  function hide() {
    if (els.panelEl) els.panelEl.hidden = true;
  }

  function setBadge(el, text, tone) {
    if (!el) return;
    el.textContent = text;
    el.dataset.tone = tone;
  }

  function showDiskWarning(message) {
    if (!els.diskWarningEl) return;
    els.diskWarningEl.hidden = false;
    if (els.diskWarningMessageEl) {
      els.diskWarningMessageEl.textContent = message;
    }
  }

  function hideDiskWarning() {
    if (els.diskWarningEl) els.diskWarningEl.hidden = true;
  }

  function renderProgress(progressEls, state) {
    if (!progressEls || !progressEls.container) return;
    const status = String(state?.status || '').toLowerCase();
    const shouldShow = VISIBLE_DOWNLOAD_STATUSES.has(status);
    progressEls.container.hidden = !shouldShow;
    if (!shouldShow) return;

    const percent = Math.max(0, Math.min(100, Number(state?.percent || 0)));
    const rounded = Math.round(percent);
    const message = state?.message || 'Download status';

    if (progressEls.label) progressEls.label.textContent = message;
    if (progressEls.percent) progressEls.percent.textContent = `${rounded}%`;
    if (progressEls.fill) {
      progressEls.fill.style.width = `${percent}%`;
      progressEls.fill.dataset.tone =
        status === 'error' ? 'danger' : (status === 'complete' || status === 'ready' || status === 'already_installed') ? 'success' : 'active';
    }
    if (progressEls.bytes) {
      const downloaded = formatBytes(state?.downloaded_bytes);
      const total = formatBytes(state?.total_bytes);
      progressEls.bytes.textContent = downloaded && total ? `${downloaded} of ${total}` : downloaded;
    }
  }

  function renderUnknown() {
    setBadge(els.runtimeBadgeEl, 'Unknown', 'warning');
    setBadge(els.llmBadgeEl, 'Unknown', 'warning');
    setBadge(els.whisperBadgeEl, 'Unknown', 'warning');
    setBadge(els.overallBadgeEl, 'Unavailable', 'warning');
    if (els.continueButton) els.continueButton.disabled = true;
  }

  function renderChecklist(status) {
    if (!status) {
      renderUnknown();
      return;
    }

    setBadge(els.runtimeBadgeEl, status.runtime.exists ? 'Found' : 'Missing', status.runtime.exists ? 'success' : 'danger');
    if (els.runtimeDetailEl) {
      els.runtimeDetailEl.textContent = status.runtime.exists
        ? 'llama-server binary is installed.'
        : 'Installs automatically with the language model.';
    }

    const llmTone = !status.llm.installed ? 'danger' : status.llm.ready ? 'success' : 'warning';
    setBadge(els.llmBadgeEl, !status.llm.installed ? 'Missing' : status.llm.ready ? 'Ready' : 'Not ready', llmTone);
    if (els.llmDetailEl) {
      els.llmDetailEl.textContent = status.llm.name || 'No model selected';
    }

    setBadge(els.whisperBadgeEl, status.whisper.ready ? 'Installed' : 'Missing', status.whisper.ready ? 'success' : 'danger');
    if (els.whisperDetailEl) {
      els.whisperDetailEl.textContent = status.whisper.installedCount
        ? `${status.whisper.installedCount} model(s) installed`
        : 'None installed';
    }

    setBadge(els.overallBadgeEl, status.ready ? 'Ready' : 'Setup needed', status.ready ? 'success' : 'warning');

    if (els.continueButton) {
      els.continueButton.disabled = !status.ready;
    }
    if (els.downloadLlmButton && els.downloadLlmButton.dataset.busy !== 'true') {
      els.downloadLlmButton.disabled = Boolean(status.llm.installed && status.llm.ready);
      els.downloadLlmButton.textContent = status.llm.installed && status.llm.ready ? 'Installed' : 'Download language model';
    }
    if (els.downloadWhisperButton && els.downloadWhisperButton.dataset.busy !== 'true') {
      els.downloadWhisperButton.disabled = status.whisper.ready;
      els.downloadWhisperButton.textContent = status.whisper.ready ? 'Installed' : 'Download speech model';
    }
  }

  // Re-fetches every endpoint the checklist depends on. Each call is
  // independently wrapped so one failing endpoint (e.g. the backend hasn't
  // finished starting yet) never blanks out data the others already have,
  // and a total failure still leaves the panel in a clear, non-blank state.
  async function refreshStatus() {
    const [health, runtime, llmModels, whisperModels] = await Promise.all([
      api.fetchHealth().catch(() => null),
      api.fetchRuntimeStatus().catch(() => null),
      api.fetchLlmModels().catch(() => null),
      api.fetchWhisperModels().catch(() => null),
    ]);

    if (!health && !runtime && !llmModels && !whisperModels) {
      lastStatus = null;
      renderUnknown();
      setMessage?.(
        els.messageEl,
        'Could not reach the local backend yet. It may still be starting -- try Check again in a moment.',
        'warning',
      );
      return null;
    }

    const status = computeFirstRunStatus({ health, runtime, llmModels, whisperModels });
    lastStatus = status;
    renderChecklist(status);
    if (status.ready) {
      setMessage?.(els.messageEl, "Everything's installed and ready to go.", 'success');
    }
    return status;
  }

  // Shared by both download buttons: manage the busy button label, poll for
  // progress, surface the exact backend outcome message (never a generic
  // "failed" when the backend gave a specific reason -- e.g. W3's disk-space
  // gate text), and refresh the checklist + rest of the app afterwards.
  async function runDownloadAction({ button, progressEls, pollState, download, successFallback, failureFallback }) {
    if (!button || button.dataset.busy === 'true') return;
    button.dataset.busy = 'true';
    const previousLabel = button.textContent;
    button.disabled = true;
    button.textContent = 'Downloading...';
    hideDiskWarning();
    renderProgress(progressEls, { status: 'starting', percent: 0, message: 'Starting download.' });

    let stopped = false;
    const timer = setInterval(async () => {
      if (stopped) return;
      try {
        const state = await pollState();
        renderProgress(progressEls, state);
      } catch (_error) {
        // Progress polling is best-effort; the download promise below is the
        // source of truth for success/failure.
      }
    }, POLL_MS);

    let ok = false;
    let message = failureFallback;
    try {
      const result = await download();
      ok = result?.ok !== false;
      message = formatDownloadOutcomeMessage(result, ok ? successFallback : failureFallback);
    } catch (error) {
      ok = false;
      message = error?.message || failureFallback;
    } finally {
      stopped = true;
      clearInterval(timer);
    }

    renderProgress(progressEls, { status: ok ? 'ready' : 'error', percent: ok ? 100 : 0, message });
    setMessage?.(els.messageEl, message, ok ? 'success' : 'danger');
    if (ok) {
      showToast?.(message, 'success');
    } else {
      // durationMs 0 keeps a disk-space (or other actionable) failure on
      // screen until the user dismisses it, rather than auto-vanishing.
      showToast?.(message, 'danger', 0);
      if (isDiskSpaceMessage(message)) {
        showDiskWarning(message);
      }
    }

    delete button.dataset.busy;
    button.disabled = false;
    button.textContent = previousLabel;

    await refreshStatus().catch(() => {});
    if (ok) {
      try {
        await afterModelsChanged?.();
      } catch (_error) {
        // Best-effort sync with the rest of the app; the download itself
        // already succeeded and this panel's own state is already correct.
      }
    }
  }

  function downloadLlm() {
    const modelId = lastStatus?.llm?.selectedId;
    if (!modelId) {
      setMessage?.(els.messageEl, 'No language model is selected yet -- open the Models tab to choose one.', 'danger');
      return;
    }
    runDownloadAction({
      button: els.downloadLlmButton,
      progressEls: els.llmProgress,
      pollState: () => api.fetchLlmDownloadState(modelId),
      download: () => api.downloadLlmModel(modelId),
      successFallback: 'Language model download complete.',
      failureFallback: 'Language model download failed.',
    }).catch(() => {});
  }

  function downloadWhisper() {
    const modelSize = lastStatus?.whisper?.selectedSize;
    if (!modelSize) {
      setMessage?.(els.messageEl, 'No speech model is selected yet -- open the Models tab to choose one.', 'danger');
      return;
    }
    runDownloadAction({
      button: els.downloadWhisperButton,
      progressEls: els.whisperProgress,
      // No dedicated GET /models/whisper/:size/download-state route exists
      // (only the LLM download has one) -- reuse the GET /models/whisper
      // list, which already carries a `download_state` field, the same one
      // the Models tab renders after a whisper download completes.
      pollState: async () => (await api.fetchWhisperModels().catch(() => null))?.download_state,
      download: () => api.downloadWhisperModel(modelSize),
      successFallback: 'Speech model download complete.',
      failureFallback: 'Speech model download failed.',
    }).catch(() => {});
  }

  function bindOnce() {
    if (initialized) return;
    initialized = true;
    els.refreshButton?.addEventListener('click', () => {
      refreshStatus().catch(() => {});
    });
    els.downloadLlmButton?.addEventListener('click', downloadLlm);
    els.downloadWhisperButton?.addEventListener('click', downloadWhisper);
    els.continueButton?.addEventListener('click', () => {
      hide();
    });
    els.dismissButton?.addEventListener('click', () => {
      setDismissed(true);
      hide();
      goToModelsTab?.();
    });
  }

  // Entry point: bind listeners once, fetch the current status, and show
  // the panel only if setup is incomplete and the user hasn't dismissed it
  // before. Never throws -- any unexpected failure still leaves the panel
  // in a visible, honest state rather than a blank Dashboard.
  async function init() {
    bindOnce();
    try {
      const status = await refreshStatus();
      if (status && status.ready) {
        hide();
        return status;
      }
      if (isDismissed()) {
        hide();
        return status;
      }
      show();
      return status;
    } catch (error) {
      show();
      setMessage?.(els.messageEl, `Could not determine setup status: ${error?.message || error}`, 'danger');
      return null;
    }
  }

  return { init, refreshStatus };
}
