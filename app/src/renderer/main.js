import {
  acceptDraft,
  connectVoiceStatus,
  declineDraft,
  fetchCapabilities,
  fetchHealth,
  fetchLatestDraft,
  fetchRuntimeStatus,
  normalizeHealthPayload,
  warmupRuntime,
} from './api/backend.js';

const backendStatusEl = document.getElementById('backendStatus');
const backendDetailEl = document.getElementById('backendDetail');
const transcriberStatusEl = document.getElementById('transcriberStatus');
const llmStatusEl = document.getElementById('llmStatus');
const wsConnectionEl = document.getElementById('wsConnection');
const voiceStatusEl = document.getElementById('voiceStatus');
const voiceStatusDetailEl = document.getElementById('voiceStatusDetail');
const quitButton = document.getElementById('quitButton');
const refreshRuntimeButton = document.getElementById('refreshRuntimeButton');
const warmupSttButton = document.getElementById('warmupSttButton');
const warmupLlmButton = document.getElementById('warmupLlmButton');
const startHotkeysButton = document.getElementById('startHotkeysButton');
const runtimeStatusListEl = document.getElementById('runtimeStatusList');
const warmupMessageEl = document.getElementById('warmupMessage');
const capabilitiesListEl = document.getElementById('capabilitiesList');
const capabilitiesSummaryEl = document.getElementById('capabilitiesSummary');
const draftStatusEl = document.getElementById('draftStatus');
const draftRawTextEl = document.getElementById('draftRawText');
const draftFinalTextEl = document.getElementById('draftFinalText');
const copyDraftButton = document.getElementById('copyDraftButton');
const acceptDraftButton = document.getElementById('acceptDraftButton');
const declineDraftButton = document.getElementById('declineDraftButton');
const draftMessageEl = document.getElementById('draftMessage');

let healthRefreshTimer = null;
let websocketHandle = null;
let latestDraft = null;

function setBadgeState(el, text, tone) {
  if (!el) {
    return;
  }

  el.textContent = text;
  el.dataset.tone = tone;
}

function formatValue(value) {
  if (typeof value === 'boolean') {
    return value ? 'yes' : 'no';
  }

  if (value === null || value === undefined || value === '') {
    return 'unknown';
  }

  return String(value);
}

function renderDetailList(container, values, preferredKeys = []) {
  if (!container) {
    return;
  }

  const keys = preferredKeys.length ? preferredKeys : Object.keys(values ?? {});
  container.innerHTML = '';

  for (const key of keys) {
    if (!Object.prototype.hasOwnProperty.call(values ?? {}, key)) {
      continue;
    }

    const row = document.createElement('div');
    row.className = 'detail-row';

    const label = document.createElement('span');
    label.className = 'detail-label';
    label.textContent = key.replaceAll('_', ' ');

    const value = document.createElement('strong');
    value.className = 'detail-value';
    value.textContent = formatValue(values[key]);
    if (typeof values[key] === 'boolean') {
      value.dataset.tone = values[key] ? 'success' : 'warning';
    }

    row.append(label, value);
    container.append(row);
  }

  if (!container.children.length) {
    container.innerHTML = '<span class="empty-state">No data available</span>';
  }
}

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

function updateRuntimeTopCards(runtime) {
  const transcriber = getTranscriberRuntimeState(runtime);
  const llm = getLlmRuntimeState(runtime);

  setBadgeState(transcriberStatusEl, transcriber.text, transcriber.tone);
  setBadgeState(llmStatusEl, llm.text, llm.tone);
}

function setWarmupMessage(message = '', tone = '') {
  if (!warmupMessageEl) {
    return;
  }

  warmupMessageEl.textContent = message;
  if (tone) {
    warmupMessageEl.dataset.tone = tone;
  } else {
    delete warmupMessageEl.dataset.tone;
  }
}

function setMessage(el, message = '', tone = '') {
  if (!el) {
    return;
  }

  el.textContent = message;
  if (tone) {
    el.dataset.tone = tone;
  } else {
    delete el.dataset.tone;
  }
}

function setDraftControlsEnabled(enabled) {
  if (copyDraftButton) {
    copyDraftButton.disabled = !enabled;
  }
  if (acceptDraftButton) {
    acceptDraftButton.disabled = !enabled;
  }
  if (declineDraftButton) {
    declineDraftButton.disabled = !enabled;
  }
}

function renderDraft(draft) {
  latestDraft = draft ?? null;

  if (!latestDraft) {
    if (draftStatusEl) {
      draftStatusEl.textContent = 'No draft yet';
      delete draftStatusEl.dataset.state;
    }
    if (draftRawTextEl) {
      draftRawTextEl.textContent = 'Waiting for a recording...';
    }
    if (draftFinalTextEl) {
      draftFinalTextEl.textContent = 'Nothing to preview yet.';
    }
    setDraftControlsEnabled(false);
    return;
  }

  if (draftStatusEl) {
    draftStatusEl.textContent = latestDraft.status ?? 'pending';
    draftStatusEl.dataset.state = latestDraft.status === 'pending' ? 'connecting' : 'connected';
  }
  if (draftRawTextEl) {
    draftRawTextEl.textContent = latestDraft.raw_text || '(empty transcript)';
  }
  if (draftFinalTextEl) {
    draftFinalTextEl.textContent = latestDraft.final_text || '(empty cleaned output)';
  }

  setDraftControlsEnabled(true);
}

async function refreshLatestDraft() {
  const payload = await fetchLatestDraft();
  renderDraft(payload?.draft ?? null);
  return payload?.draft ?? null;
}

async function refreshHealth() {
  try {
    const payload = await fetchHealth();
    const health = normalizeHealthPayload(payload);

    setBadgeState(backendStatusEl, health.backendStatus, health.backendStatus === 'active' ? 'success' : 'warning');
    if (backendDetailEl) {
      backendDetailEl.textContent = 'FastAPI /health responded successfully';
    }
  } catch (error) {
    setBadgeState(backendStatusEl, 'offline', 'danger');
    if (backendDetailEl) {
      backendDetailEl.textContent = 'Waiting for the Python backend to start';
    }
    setBadgeState(transcriberStatusEl, 'offline', 'danger');
    setBadgeState(llmStatusEl, 'offline', 'danger');
  }
}

async function refreshRuntime() {
  const runtime = await fetchRuntimeStatus();
  updateRuntimeTopCards(runtime);
  renderDetailList(runtimeStatusListEl, runtime, [
    'transcriber_initialized',
    'transcriber_loaded',
    'llm_initialized',
    'llm_ready',
    'hotkey_manager_started',
  ]);
  return runtime;
}

async function refreshCapabilities() {
  const capabilities = await fetchCapabilities();
  if (capabilitiesSummaryEl) {
    const platform = capabilities.platform ?? 'unknown';
    const session = capabilities.session_type ?? 'unknown';
    capabilitiesSummaryEl.textContent = `${platform} · ${session}`;
  }
  renderDetailList(capabilitiesListEl, capabilities, [
    'platform',
    'session_type',
    'is_linux',
    'is_wayland',
    'is_x11',
    'supports_basic_clipboard',
    'supports_rich_clipboard_restore',
    'supports_input_injection',
    'supports_global_hotkeys',
    'supports_audio_ducking',
    'supports_stt',
    'supports_llm',
    'supports_tts',
  ]);
  return capabilities;
}

function summarizeWarmupResult(result, requestedPayload) {
  const labels = {
    stt: 'STT',
    llm: 'LLM',
    hotkeys: 'Hotkeys',
  };
  const errors = [];
  const successes = [];

  for (const key of Object.keys(labels)) {
    if (!requestedPayload[key]) {
      continue;
    }

    const row = result?.[key];
    if (!row) {
      errors.push(`${labels[key]} returned no result data.`);
      continue;
    }

    if (row.ok === false) {
      errors.push(`${labels[key]} failed: ${row.error || 'Unknown error'}`);
    } else {
      successes.push(`${labels[key]} ok`);
    }
  }

  return { errors, successes };
}

async function runWarmup(button, payload) {
  if (!button) {
    return;
  }

  const previousText = button.textContent;
  button.disabled = true;
  button.textContent = 'Working...';
  setWarmupMessage('');

  try {
    const result = await warmupRuntime(payload);
    await Promise.all([refreshHealth(), refreshRuntime()]);
    const summary = summarizeWarmupResult(result, payload);
    if (summary.errors.length) {
      setWarmupMessage(summary.errors.join('\n'), 'danger');
      button.textContent = previousText;
      button.disabled = false;
      return;
    }
    setWarmupMessage(summary.successes.length ? summary.successes.join(' · ') : 'Warmup request completed.', 'success');
  } catch (error) {
    setWarmupMessage(`Warmup failed: ${error.message}`, 'danger');
    button.textContent = previousText;
    button.disabled = false;
    return;
  }

  button.textContent = previousText;
  button.disabled = false;
}

function updateConnectionPill(state, detail) {
  if (wsConnectionEl) {
    wsConnectionEl.textContent = detail ? `${state} · ${detail}` : state;
    wsConnectionEl.dataset.state = state;
  }
}

function updateVoiceStatus(message) {
  if (!message) {
    return;
  }

  const statusText = typeof message === 'string' ? message : String(message.status ?? message.type ?? 'unknown');
  voiceStatusEl.textContent = statusText;
  voiceStatusDetailEl.textContent = JSON.stringify(message, null, 2);

  if (message.status === 'preview_ready') {
    renderDraft({
      id: message.draft_id,
      raw_text: message.raw_text,
      final_text: message.final_text,
      status: 'pending',
    });
    setMessage(draftMessageEl, 'New draft ready for review.', 'success');
  }
}

async function bootstrap() {
  await refreshHealth();
  await Promise.all([
    refreshRuntime().catch(() => {
      setBadgeState(transcriberStatusEl, 'offline', 'danger');
      setBadgeState(llmStatusEl, 'offline', 'danger');
      renderDetailList(runtimeStatusListEl, {});
    }),
    refreshCapabilities().catch(() => {
      if (capabilitiesSummaryEl) {
        capabilitiesSummaryEl.textContent = 'Unavailable';
      }
      renderDetailList(capabilitiesListEl, {});
    }),
    refreshLatestDraft().catch(() => {
      renderDraft(null);
    }),
  ]);

  healthRefreshTimer = setInterval(() => {
    refreshHealth();
    refreshRuntime().catch(() => {
      setBadgeState(transcriberStatusEl, 'offline', 'danger');
      setBadgeState(llmStatusEl, 'offline', 'danger');
    });
  }, 3000);

  websocketHandle = connectVoiceStatus({
    onConnectionChange: updateConnectionPill,
    onMessage: updateVoiceStatus,
    onError: (error) => {
      updateConnectionPill('error', error.message);
    },
  });
}

quitButton?.addEventListener('click', () => {
  window.betterFingers?.quitApp?.();
});

refreshRuntimeButton?.addEventListener('click', () => {
  Promise.all([
    refreshHealth(),
    refreshRuntime().catch(() => {
      setBadgeState(transcriberStatusEl, 'offline', 'danger');
      setBadgeState(llmStatusEl, 'offline', 'danger');
      renderDetailList(runtimeStatusListEl, {});
    }),
  ]);
});

warmupSttButton?.addEventListener('click', () => {
  runWarmup(warmupSttButton, { stt: true });
});

warmupLlmButton?.addEventListener('click', () => {
  runWarmup(warmupLlmButton, { llm: true });
});

startHotkeysButton?.addEventListener('click', () => {
  runWarmup(startHotkeysButton, { hotkeys: true });
});

copyDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.final_text) {
    return;
  }

  try {
    await window.betterFingers?.writeClipboardText?.(latestDraft.final_text);
    setMessage(draftMessageEl, 'Cleaned output copied to clipboard.', 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Copy failed: ${error.message}`, 'danger');
  }
});

acceptDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  try {
    const draft = await acceptDraft(latestDraft.id);
    renderDraft(draft);
    setMessage(draftMessageEl, 'Draft accepted.', 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Accept failed: ${error.message}`, 'danger');
  }
});

declineDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  try {
    const draft = await declineDraft(latestDraft.id);
    renderDraft(draft);
    setMessage(draftMessageEl, 'Draft declined.', 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Decline failed: ${error.message}`, 'danger');
  }
});

window.addEventListener('beforeunload', () => {
  if (healthRefreshTimer) {
    clearInterval(healthRefreshTimer);
  }

  if (websocketHandle) {
    websocketHandle.close();
  }
});

bootstrap().catch((error) => {
  setBadgeState(backendStatusEl, 'offline', 'danger');
  if (backendDetailEl) {
    backendDetailEl.textContent = error.message;
  }
  setBadgeState(transcriberStatusEl, 'offline', 'danger');
  setBadgeState(llmStatusEl, 'offline', 'danger');
});
