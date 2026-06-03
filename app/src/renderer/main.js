import {
  acceptDraft,
  activateProfile,
  connectVoiceStatus,
  createProfile,
  deleteProfile,
  deleteLlmModel,
  deleteWhisperModel,
  declineDraft,
  downloadLlmModel,
  downloadWhisperModel,
  editDraft,
  emergencyStop,
  fetchCapabilities,
  fetchDiagnosticsLogs,
  fetchDiagnosticsPaths,
  fetchDrafts,
  fetchHealth,
  fetchLatestDraft,
  fetchLlmModels,
  fetchOutputSettings,
  fetchProfile,
  fetchProfiles,
  fetchRuntimeErrors,
  fetchRuntimeStatus,
  fetchWhisperModels,
  normalizeHealthPayload,
  retryDraft,
  rewriteDraft,
  runPrimaryAction,
  saveProfile,
  sendDraft,
  selectLlmModel,
  speakDraft,
  testWhisperModel,
  unloadModel,
  warmupRuntime,
  fetchDoctor,
  refreshAudioDevices,
  fetchVersion,
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
const primaryActionButton = document.getElementById('primaryActionButton');
const emergencyStopButton = document.getElementById('emergencyStopButton');
const runtimeStatusListEl = document.getElementById('runtimeStatusList');
const warmupMessageEl = document.getElementById('warmupMessage');
const outputSettingsSummaryEl = document.getElementById('outputSettingsSummary');
const capabilitiesListEl = document.getElementById('capabilitiesList');
const capabilitiesSummaryEl = document.getElementById('capabilitiesSummary');
const draftStatusEl = document.getElementById('draftStatus');
const draftRawTextEl = document.getElementById('draftRawText');
const draftFinalTextEl = document.getElementById('draftFinalText');
const draftTokenSummaryEl = document.getElementById('draftTokenSummary');
const saveDraftEditButton = document.getElementById('saveDraftEditButton');
const rewriteShorterButton = document.getElementById('rewriteShorterButton');
const rewriteClearerButton = document.getElementById('rewriteClearerButton');
const rewriteToneButton = document.getElementById('rewriteToneButton');
const customRewriteInstructionEl = document.getElementById('customRewriteInstruction');
const rewriteCustomButton = document.getElementById('rewriteCustomButton');
const readSelectionButton = document.getElementById('readSelectionButton');
const readFullDraftButton = document.getElementById('readFullDraftButton');
const copyDraftButton = document.getElementById('copyDraftButton');
const acceptDraftButton = document.getElementById('acceptDraftButton');
const declineDraftButton = document.getElementById('declineDraftButton');
const retryDraftButton = document.getElementById('retryDraftButton');
const sendDraftButton = document.getElementById('sendDraftButton');
const draftMessageEl = document.getElementById('draftMessage');
const draftMetadataEl = document.getElementById('draftMetadata');
const draftHistoryListEl = document.getElementById('draftHistoryList');
const refreshDiagnosticsButton = document.getElementById('refreshDiagnosticsButton');
const sidecarStatusEl = document.getElementById('sidecarStatus');
const diagnosticsPathsListEl = document.getElementById('diagnosticsPathsList');
const runtimeErrorsListEl = document.getElementById('runtimeErrorsList');
const debugLogTailEl = document.getElementById('debugLogTail');
const refreshProfilesButton = document.getElementById('refreshProfilesButton');
const profileSelectEl = document.getElementById('profileSelect');
const newProfileNameEl = document.getElementById('newProfileName');
const activateProfileButton = document.getElementById('activateProfileButton');
const saveProfileButton = document.getElementById('saveProfileButton');
const discardProfileChangesButton = document.getElementById('discardProfileChangesButton');
const createProfileButton = document.getElementById('createProfileButton');
const deleteProfileButton = document.getElementById('deleteProfileButton');
const profileMessageEl = document.getElementById('profileMessage');
const refreshModelsButton = document.getElementById('refreshModelsButton');
const llmModelSelectEl = document.getElementById('llmModelSelect');
const whisperModelSelectEl = document.getElementById('whisperModelSelect');
const modelStatusSummaryEl = document.getElementById('modelStatusSummary');
const modelMessageEl = document.getElementById('modelMessage');
const selectLlmModelButton = document.getElementById('selectLlmModelButton');
const downloadLlmModelButton = document.getElementById('downloadLlmModelButton');
const deleteLlmModelButton = document.getElementById('deleteLlmModelButton');
const downloadWhisperButton = document.getElementById('downloadWhisperButton');
const testWhisperButton = document.getElementById('testWhisperButton');
const deleteWhisperButton = document.getElementById('deleteWhisperButton');
const unloadSttButton = document.getElementById('unloadSttButton');
const unloadLlmButton = document.getElementById('unloadLlmButton');
const unloadTtsButton = document.getElementById('unloadTtsButton');

const versionMismatchBanner = document.getElementById('versionMismatchBanner');
const refreshDoctorButton = document.getElementById('refreshDoctorButton');
const doctorCardsGrid = document.getElementById('doctorCardsGrid');
const doctorRecoveryPanel = document.getElementById('doctorRecoveryPanel');
const doctorRecoveryList = document.getElementById('doctorRecoveryList');
const clearSidecarLogsButton = document.getElementById('clearSidecarLogsButton');
const sidecarLogsTail = document.getElementById('sidecarLogsTail');

let healthRefreshTimer = null;
let websocketHandle = null;
let latestDraft = null;
let draftHistory = [];
let outputSettings = null;
let activeProfileSettings = null;
let profileDirty = false;
let llmModelsPayload = null;
let whisperModelsPayload = null;

const settingEls = {
  hotkey: document.getElementById('settingHotkey'),
  recording_mode: document.getElementById('settingRecordingMode'),
  force_stop_key: document.getElementById('settingForceStopKey'),
  manual_send_hotkey: document.getElementById('settingManualSendHotkey'),
  review_tts_hotkey: document.getElementById('settingReviewTtsHotkey'),
  chat_open_key: document.getElementById('settingChatOpenKey'),
  voice_mute_key: document.getElementById('settingVoiceMuteKey'),
  send_mode: document.getElementById('settingSendMode'),
  current_preset: document.getElementById('settingCurrentPreset'),
  output_token_limit: document.getElementById('settingOutputTokenLimit'),
  no_audio_min_duration_sec: document.getElementById('settingNoAudioDuration'),
  no_audio_min_rms: document.getElementById('settingNoAudioRms'),
  no_audio_min_peak: document.getElementById('settingNoAudioPeak'),
  auto_submit: document.getElementById('settingAutoSubmit'),
  instant_typing: document.getElementById('settingInstantTyping'),
  audio_ducking: document.getElementById('settingAudioDucking'),
  status_indicator_enabled: document.getElementById('settingStatusIndicator'),
  notification_overlay_enabled: document.getElementById('settingNotificationOverlay'),
  preview_overlay_enabled: document.getElementById('settingPreviewOverlay'),
  model_keep_llm_loaded: document.getElementById('settingKeepLlm'),
  model_keep_stt_loaded: document.getElementById('settingKeepStt'),
  model_keep_tts_loaded: document.getElementById('settingKeepTts'),
};

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

function getDraftEditorText() {
  if (!draftFinalTextEl) {
    return latestDraft?.final_text ?? '';
  }

  return draftFinalTextEl.value ?? latestDraft?.final_text ?? '';
}

function getSelectedDraftText() {
  if (!draftFinalTextEl) {
    return getDraftEditorText();
  }

  const start = Number(draftFinalTextEl.selectionStart ?? 0);
  const end = Number(draftFinalTextEl.selectionEnd ?? 0);
  const value = getDraftEditorText();
  if (end > start) {
    return value.slice(start, end);
  }
  return value;
}

function renderTokenSummary(draft) {
  if (!draftTokenSummaryEl) {
    return;
  }

  if (!draft) {
    draftTokenSummaryEl.textContent = '0 tokens';
    delete draftTokenSummaryEl.dataset.state;
    return;
  }

  const tokenCount = Number(draft.token_count ?? 0);
  const tokenLimit = Number(draft.token_limit ?? 0);
  const longText = Boolean(draft.long_text || (tokenLimit && tokenCount > tokenLimit));
  draftTokenSummaryEl.textContent = tokenLimit
    ? `${tokenCount} / ${tokenLimit} tokens${longText ? ' · long text' : ''}`
    : `${tokenCount} tokens`;
  if (longText) {
    draftTokenSummaryEl.dataset.state = 'warning';
  } else {
    delete draftTokenSummaryEl.dataset.state;
  }
}

function setDraftControlsEnabled(enabled) {
  const status = latestDraft?.status ?? '';
  const hasDraft = enabled && Boolean(latestDraft?.id);
  const hasFinalText = hasDraft && Boolean(getDraftEditorText().trim());
  const canReview = hasDraft && status === 'pending';
  const canRetry = hasDraft && ['blocked', 'error'].includes(status);
  const canEdit = hasDraft;

  if (draftFinalTextEl) {
    draftFinalTextEl.disabled = !canEdit;
  }
  if (saveDraftEditButton) {
    saveDraftEditButton.disabled = !canEdit;
  }
  for (const button of [rewriteShorterButton, rewriteClearerButton, rewriteToneButton, rewriteCustomButton]) {
    if (button) {
      button.disabled = !canEdit || !hasFinalText;
    }
  }
  if (customRewriteInstructionEl) {
    customRewriteInstructionEl.disabled = !canEdit;
  }
  if (readSelectionButton) {
    readSelectionButton.disabled = !canEdit || !hasFinalText;
  }
  if (readFullDraftButton) {
    readFullDraftButton.disabled = !canEdit || !hasFinalText;
  }

  if (copyDraftButton) {
    copyDraftButton.disabled = !hasFinalText;
  }
  if (acceptDraftButton) {
    acceptDraftButton.disabled = !canReview;
  }
  if (declineDraftButton) {
    declineDraftButton.disabled = !enabled;
  }
  if (retryDraftButton) {
    retryDraftButton.disabled = !canRetry;
  }
  if (sendDraftButton) {
    sendDraftButton.disabled = !hasFinalText;
  }
}

function formatDraftMetadata(draft) {
  const metadata = draft?.metadata ?? {};
  if (!Object.keys(metadata).length) {
    return 'No recording metadata available.';
  }

  const duration = Number(metadata.duration_seconds || 0).toFixed(2);
  const rms = Number(metadata.rms_amplitude || 0).toFixed(5);
  const peak = Number(metadata.max_amplitude || 0).toFixed(5);
  const samples = metadata.sample_count ?? 0;
  const stopReason = metadata.stop_reason || 'unknown';
  return `duration ${duration}s · samples ${samples} · peak ${peak} · rms ${rms} · stop ${stopReason}`;
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
      draftFinalTextEl.value = 'Nothing to preview yet.';
      draftFinalTextEl.disabled = true;
    }
    renderTokenSummary(null);
    if (draftMetadataEl) {
      draftMetadataEl.textContent = 'No recording metadata yet.';
    }
    setMessage(draftMessageEl, '');
    setDraftControlsEnabled(false);
    return;
  }

  if (draftStatusEl) {
    draftStatusEl.textContent = latestDraft.status ?? 'pending';
    draftStatusEl.dataset.state = ['blocked', 'error'].includes(latestDraft.status) ? 'error' : latestDraft.status === 'pending' ? 'connecting' : 'connected';
  }
  if (draftRawTextEl) {
    draftRawTextEl.textContent = latestDraft.raw_text || '(empty transcript)';
  }
  if (draftFinalTextEl) {
    draftFinalTextEl.value = latestDraft.final_text || '';
  }
  renderTokenSummary(latestDraft);
  if (draftMetadataEl) {
    draftMetadataEl.textContent = formatDraftMetadata(latestDraft);
  }

  if (latestDraft.error) {
    const reasons = Array.isArray(latestDraft.gate_reasons) && latestDraft.gate_reasons.length
      ? ` (${latestDraft.gate_reasons.join(', ')})`
      : '';
    setMessage(draftMessageEl, `${latestDraft.error}${reasons}`, 'danger');
  } else {
    const tokenLimit = Number(latestDraft.token_limit ?? 0);
    const tokenCount = Number(latestDraft.token_count ?? 0);
    if (latestDraft.long_text || (tokenLimit && tokenCount > tokenLimit)) {
      setMessage(draftMessageEl, 'Long text warning: this draft may need shortening before send.', 'warning');
    } else {
      setMessage(draftMessageEl, '');
    }
  }

  setDraftControlsEnabled(true);
}

function renderDraftHistory(drafts) {
  if (!draftHistoryListEl) {
    return;
  }

  draftHistory = Array.isArray(drafts) ? drafts : [];
  draftHistoryListEl.innerHTML = '';

  if (!draftHistory.length) {
    draftHistoryListEl.innerHTML = '<span class="empty-state">No draft history yet.</span>';
    return;
  }

  for (const draft of draftHistory.slice().reverse()) {
    const item = document.createElement('button');
    item.className = 'draft-history-item';
    item.type = 'button';
    item.dataset.status = draft.status ?? 'pending';

    const title = document.createElement('strong');
    title.textContent = `#${draft.id} · ${draft.status ?? 'pending'}`;

    const detail = document.createElement('small');
    const text = draft.final_text || draft.raw_text || draft.error || 'No text';
    detail.textContent = text.length > 140 ? `${text.slice(0, 140)}...` : text;

    item.append(title, detail);
    item.addEventListener('click', () => {
      renderDraft(draft);
    });
    draftHistoryListEl.append(item);
  }
}

async function refreshLatestDraft() {
  const payload = await fetchLatestDraft();
  renderDraft(payload?.draft ?? null);
  return payload?.draft ?? null;
}

async function refreshDrafts() {
  const payload = await fetchDrafts();
  renderDraftHistory(payload?.drafts ?? []);
  if (payload?.drafts?.length) {
    renderDraft(payload.drafts[payload.drafts.length - 1]);
  } else {
    renderDraft(null);
  }
  return payload?.drafts ?? [];
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

async function refreshOutputSettings() {
  outputSettings = await fetchOutputSettings();
  if (outputSettingsSummaryEl) {
    const supportsInput = outputSettings?.capabilities?.supports_input_injection ? 'input injection available' : 'copy fallback';
    const pendingCount = Array.isArray(outputSettings?.pending_manual_send_ids) ? outputSettings.pending_manual_send_ids.length : 0;
    outputSettingsSummaryEl.textContent = `send mode ${outputSettings?.send_mode ?? 'unknown'} · auto-submit ${formatValue(outputSettings?.auto_submit)} · ${supportsInput} · pending sends ${pendingCount}`;
  }
  return outputSettings;
}

function fillSelect(selectEl, options, selectedValue, labelFor = (item) => item) {
  if (!selectEl) {
    return;
  }

  selectEl.innerHTML = '';
  for (const item of options) {
    const value = typeof item === 'string' ? item : item.value;
    const option = document.createElement('option');
    option.value = value;
    option.textContent = labelFor(item);
    option.selected = value === selectedValue;
    selectEl.append(option);
  }
}

function renderProfileSettings(settings) {
  activeProfileSettings = { ...(settings ?? {}) };
  profileDirty = false;
for (const [key, el] of Object.entries(settingEls)) {
    if (!el) {
      continue;
    }
    if (el.type === 'checkbox') {
      el.checked = Boolean(activeProfileSettings[key]);
    } else {
      el.value = activeProfileSettings[key] ?? '';
    }
  }
}

function markProfileDirty() {
  profileDirty = true;
  setMessage(profileMessageEl, 'Unsaved profile changes.', 'warning');
}

function collectProfileSettings() {
  const next = { ...(activeProfileSettings ?? {}) };
  for (const [key, el] of Object.entries(settingEls)) {
    if (!el) {
      continue;
    }
    if (el.type === 'checkbox') {
      next[key] = Boolean(el.checked);
    } else if (el.type === 'number') {
      next[key] = Number(el.value);
    } else {
      next[key] = el.value;
    }
  }
  return next;
}

async function refreshProfiles() {
  const payload = await fetchProfiles();
  fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
  renderProfileSettings(payload.settings ?? {});
  setMessage(profileMessageEl, `Active profile: ${payload.active_profile}`, 'success');
  return payload;
}

async function refreshModels() {
  const [llmPayload, whisperPayload] = await Promise.all([
    fetchLlmModels(),
    fetchWhisperModels(),
  ]);
  llmModelsPayload = llmPayload;
  whisperModelsPayload = whisperPayload;

  fillSelect(
    llmModelSelectEl,
    (llmPayload.models ?? []).map((model) => ({ value: model.id, label: `${model.name} ${model.installed ? '(installed)' : ''}` })),
    llmPayload.selected_model_id,
    (item) => item.label,
  );
  fillSelect(whisperModelSelectEl, whisperPayload.supported ?? [], whisperPayload.selected_model_size);

  if (modelStatusSummaryEl) {
    const llmSelected = (llmPayload.models ?? []).find((model) => model.id === llmPayload.selected_model_id);
    const installedWhisper = (whisperPayload.models ?? []).filter((model) => model.installed).map((model) => model.model_size);
    const estimateMb = Number(llmSelected?.size_mb || 0);
    modelStatusSummaryEl.textContent = [
      `LLM: ${llmSelected?.name ?? llmPayload.selected_model_id ?? 'unknown'} (${llmSelected?.installed ? 'installed' : 'missing'})`,
      `approx model size: ${estimateMb ? `${estimateMb} MB` : 'unknown'}`,
      `llama-server: ${llmPayload.llama_server_exists ? 'found' : 'missing'}`,
      `Whisper installed: ${installedWhisper.length ? installedWhisper.join(', ') : 'none'}`,
    ].join(' · ');
  }
  return { llmPayload, whisperPayload };
}

async function runModelAction(button, label, action) {
  if (!button) {
    return;
  }
  const previous = button.textContent;
  button.disabled = true;
  button.textContent = 'Working...';
  try {
    const result = await action();
    setMessage(modelMessageEl, result?.message || `${label} completed.`, result?.ok === false ? 'danger' : 'success');
    await Promise.all([refreshModels(), refreshRuntime()]);
  } catch (error) {
    setMessage(modelMessageEl, `${label} failed: ${error.message}`, 'danger');
  } finally {
    button.textContent = previous;
    button.disabled = false;
  }
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

function renderRuntimeErrors(payload) {
  if (!runtimeErrorsListEl) {
    return;
  }

  const errors = Array.isArray(payload?.errors) ? payload.errors : [];
  runtimeErrorsListEl.innerHTML = '';

  if (!errors.length) {
    runtimeErrorsListEl.innerHTML = '<span class="empty-state">No runtime errors recorded.</span>';
    return;
  }

  for (const error of errors.slice(-8).reverse()) {
    const row = document.createElement('div');
    row.className = 'diagnostics-error';
    row.dataset.severity = error.severity ?? 'recoverable';

    const title = document.createElement('strong');
    title.textContent = `${error.component ?? 'runtime'}: ${error.message ?? 'Unknown error'}`;

    const severityPill = document.createElement('span');
    severityPill.className = 'doctor-card-status';
    severityPill.style.display = 'inline-block';
    severityPill.style.marginLeft = '10px';
    severityPill.style.fontSize = '0.75rem';
    severityPill.style.padding = '2px 6px';
    severityPill.textContent = error.severity ?? 'recoverable';
    
    if (error.severity === 'fatal') {
      severityPill.dataset.tone = 'danger';
    } else if (error.severity === 'warning') {
      severityPill.dataset.tone = 'warning';
    } else if (error.severity === 'info') {
      severityPill.dataset.tone = 'success';
    } else {
      severityPill.dataset.tone = 'danger';
    }

    title.append(severityPill);

    const meta = document.createElement('small');
    meta.textContent = error.created_at ?? '';

    row.append(title, meta);
    runtimeErrorsListEl.append(row);
  }
}

async function refreshSidecarStatus() {
  if (!sidecarStatusEl) {
    return null;
  }

  const status = await window.betterFingers?.getSidecarStatus?.();
  if (!status) {
    sidecarStatusEl.textContent = 'Sidecar status is unavailable.';
    sidecarStatusEl.dataset.tone = 'warning';
    return null;
  }

  sidecarStatusEl.textContent = [
    `state: ${status.state ?? 'unknown'}`,
    `owns process: ${status.ownsProcess ? 'yes' : 'no'}`,
    `pid: ${status.pid ?? 'none'}`,
    status.message ?? '',
  ].filter(Boolean).join('\n');
  
  if (status.state === 'error') {
    sidecarStatusEl.dataset.tone = 'danger';
  } else if (status.state === 'ready') {
    sidecarStatusEl.dataset.tone = 'success';
  } else if (status.state === 'version_mismatch') {
    sidecarStatusEl.dataset.tone = 'warning';
  } else {
    sidecarStatusEl.dataset.tone = 'warning';
  }

  if (versionMismatchBanner) {
    if (status.state === 'version_mismatch') {
      versionMismatchBanner.classList.remove('hidden');
    } else {
      versionMismatchBanner.classList.add('hidden');
    }
  }

  if (status.state === 'error' || status.state === 'stopped') {
    refreshSidecarLogs().catch(() => {});
  }

  return status;
}

async function refreshDiagnostics() {
  await Promise.all([
    refreshSidecarStatus().catch((error) => {
      if (sidecarStatusEl) {
        sidecarStatusEl.textContent = `Sidecar status failed: ${error.message}`;
        sidecarStatusEl.dataset.tone = 'danger';
      }
    }),
    fetchDiagnosticsPaths().then((paths) => {
      renderDetailList(diagnosticsPathsListEl, paths, [
        'debug_log_path',
        'models_dir',
        'default_model_path',
        'default_model_exists',
        'llama_server_path',
        'llama_server_exists',
        'repo_local_llama_server_path',
        'repo_local_llama_server_exists',
        'BETTERFINGERS_LLAMA_SERVER',
        'BETTERFINGERS_MODEL_PATH',
      ]);
    }).catch(() => {
      renderDetailList(diagnosticsPathsListEl, {});
    }),
    fetchRuntimeErrors().then(renderRuntimeErrors).catch(() => {
      renderRuntimeErrors({ errors: [{ component: 'diagnostics', message: 'Failed loading runtime errors.' }] });
    }),
    fetchDiagnosticsLogs(80).then((logs) => {
      if (debugLogTailEl) {
        const lines = Array.isArray(logs?.lines) ? logs.lines : [];
        debugLogTailEl.textContent = lines.length ? lines.join('\n') : `No log lines found at ${logs?.path ?? 'debug.log'}.`;
      }
    }).catch((error) => {
      if (debugLogTailEl) {
        debugLogTailEl.textContent = `Failed loading log tail: ${error.message}`;
      }
    }),
  ]);
}

function summarizeWarmupResult(result, requestedPayload) {
  const labels = {
    stt: 'STT',
    llm: 'LLM',
    hotkeys: 'Hotkeys',
};

for (const el of Object.values(settingEls)) {
  el?.addEventListener('input', markProfileDirty);
  el?.addEventListener('change', markProfileDirty);
}
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
    await refreshOutputSettings().catch(() => {});
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

  if (['preview_ready', 'draft_blocked', 'draft_error'].includes(message.status)) {
    renderDraft({
      id: message.draft_id,
      raw_text: message.raw_text,
      final_text: message.final_text,
      status: message.status === 'draft_blocked' ? 'blocked' : message.status === 'draft_error' ? 'error' : 'pending',
      error: message.error ?? '',
      gate_reasons: message.gate_reasons ?? [],
      token_count: message.token_count,
      token_limit: message.token_limit,
      long_text: message.long_text,
    });
    setMessage(
      draftMessageEl,
      message.status === 'preview_ready' ? 'New draft ready for review.' : message.error || 'Draft needs attention.',
      message.status === 'preview_ready' ? 'success' : 'danger',
    );
    refreshDrafts().catch(() => {});
  }

  if (['draft_accepted', 'draft_declined'].includes(message.status)) {
    refreshDrafts().catch(() => {});
    refreshOutputSettings().catch(() => {});
  }

  if (['draft_updated', 'draft_rewriting', 'draft_rewritten', 'draft_rewrite_error', 'draft_tts_requested'].includes(message.status)) {
    if (message.status === 'draft_rewriting') {
      setMessage(draftMessageEl, `Rewriting draft with ${message.action || 'selected'} action...`, 'warning');
    } else if (message.status === 'draft_rewrite_error') {
      setMessage(draftMessageEl, `Rewrite failed: ${message.error}`, 'danger');
    } else if (message.status === 'draft_tts_requested') {
      setMessage(draftMessageEl, 'Draft read-aloud request sent.', 'success');
    } else {
      setMessage(draftMessageEl, message.status === 'draft_rewritten' ? 'Rewrite complete.' : 'Draft edit saved.', 'success');
    }
    refreshDrafts().catch(() => {});
  }

  if (['draft_sent', 'draft_send_error', 'selection_captured', 'selection_capture_failed', 'emergency_stop'].includes(message.status)) {
    setMessage(draftMessageEl, message.message || message.send_result?.message || statusText, message.status.endsWith('error') || message.status.endsWith('failed') ? 'danger' : 'success');
    refreshDrafts().catch(() => {});
    refreshOutputSettings().catch(() => {});
  }
}

async function saveCurrentDraftEdit({ silent = false } = {}) {
  if (!latestDraft?.id) {
    return null;
  }

  const finalText = getDraftEditorText();
  if (finalText === (latestDraft.final_text ?? '')) {
    return latestDraft;
  }

  const draft = await editDraft(latestDraft.id, finalText);
  renderDraft(draft);
  await refreshDrafts();
  if (!silent) {
    setMessage(draftMessageEl, 'Draft edit saved.', 'success');
  }
  return draft;
}

async function runRewriteAction(button, action, customInstruction = '') {
  if (!latestDraft?.id) {
    return;
  }

  const originalText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = 'Rewriting...';
  }

  try {
    await saveCurrentDraftEdit({ silent: true });
    const result = await rewriteDraft(latestDraft.id, { action, customInstruction });
    if (result?.ok === false) {
      if (result.draft?.id) {
        renderDraft(result.draft);
      }
      setMessage(draftMessageEl, `Rewrite failed: ${result.error || 'Unknown error'}`, 'danger');
      return;
    }
    renderDraft(result);
    await refreshDrafts();
    setMessage(draftMessageEl, `${action === 'custom' ? 'Custom' : action} rewrite complete.`, 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Rewrite failed: ${error.message}`, 'danger');
  } finally {
    if (button) {
      button.textContent = originalText;
    }
    setDraftControlsEnabled(Boolean(latestDraft));
  }
}

async function runDraftTts(selectedOnly = false) {
  if (!latestDraft?.id) {
    return;
  }

  const text = selectedOnly ? getSelectedDraftText() : getDraftEditorText();
  if (!text.trim()) {
    setMessage(draftMessageEl, 'No draft text is available to read.', 'warning');
    return;
  }

  try {
    await saveCurrentDraftEdit({ silent: true });
    const result = await speakDraft(latestDraft.id, { text });
    setMessage(draftMessageEl, result?.message || 'Draft read-aloud request sent.', result?.ok === false ? 'warning' : 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Read aloud failed: ${error.message}`, 'danger');
  }
}

async function copyCurrentDraftText() {
  if (!latestDraft?.id) {
    return;
  }

  const text = getDraftEditorText();
  if (!text.trim()) {
    setMessage(draftMessageEl, 'No cleaned output is available to copy.', 'warning');
    return;
  }

  await window.betterFingers?.writeClipboardText?.(text);
  setMessage(draftMessageEl, 'Cleaned output copied to clipboard.', 'success');
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
    refreshDrafts().catch(() => {
      renderDraft(null);
    }),
    refreshOutputSettings().catch(() => {
      if (outputSettingsSummaryEl) {
        outputSettingsSummaryEl.textContent = 'Output settings unavailable.';
      }
    }),
    refreshProfiles().catch((error) => {
      setMessage(profileMessageEl, `Profiles unavailable: ${error.message}`, 'danger');
    }),
    refreshModels().catch((error) => {
      setMessage(modelMessageEl, `Models unavailable: ${error.message}`, 'danger');
    }),
    refreshDiagnostics().catch(() => {}),
    refreshDoctor().catch(() => {}),
    refreshSidecarLogs().catch(() => {}),
  ]);

  healthRefreshTimer = setInterval(() => {
    refreshHealth();
    refreshSidecarStatus().catch(() => {});
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

primaryActionButton?.addEventListener('click', async () => {
  primaryActionButton.disabled = true;
  primaryActionButton.textContent = 'Working...';
  try {
    const result = await runPrimaryAction();
    if (result?.send_result) {
      renderDraft(result);
      setMessage(draftMessageEl, result.send_result.message || 'Primary action sent pending draft.', result.send_result.ok ? 'success' : 'danger');
    } else {
      setMessage(draftMessageEl, result?.message || 'Primary action completed.', result?.ok ? 'success' : 'warning');
    }
    await Promise.all([refreshDrafts(), refreshOutputSettings()]);
  } catch (error) {
    setMessage(draftMessageEl, `Primary action failed: ${error.message}`, 'danger');
  } finally {
    primaryActionButton.textContent = 'Primary Action';
    primaryActionButton.disabled = false;
  }
});

emergencyStopButton?.addEventListener('click', async () => {
  emergencyStopButton.disabled = true;
  emergencyStopButton.textContent = 'Stopping...';
  try {
    const result = await emergencyStop();
    setWarmupMessage(result?.message || 'Emergency stop completed.', result?.ok ? 'success' : 'warning');
    await Promise.all([refreshRuntime(), refreshOutputSettings()]);
  } catch (error) {
    setWarmupMessage(`Emergency stop failed: ${error.message}`, 'danger');
  } finally {
    emergencyStopButton.textContent = 'Emergency Stop';
    emergencyStopButton.disabled = false;
  }
});

refreshDiagnosticsButton?.addEventListener('click', () => {
  refreshDiagnostics();
});

refreshProfilesButton?.addEventListener('click', () => {
  refreshProfiles().catch((error) => setMessage(profileMessageEl, `Refresh failed: ${error.message}`, 'danger'));
});

profileSelectEl?.addEventListener('change', async () => {
  try {
    const payload = await fetchProfile(profileSelectEl.value);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `${payload.profile} loaded for editing.`, payload.active ? 'success' : 'warning');
  } catch (error) {
    setMessage(profileMessageEl, `Profile load failed: ${error.message}`, 'danger');
  }
});

activateProfileButton?.addEventListener('click', async () => {
  const name = profileSelectEl?.value;
  if (!name) {
    return;
  }
  try {
    const payload = await activateProfile(name);
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
    renderProfileSettings(payload.settings ?? {});
    await Promise.all([refreshRuntime(), refreshOutputSettings()]);
    setMessage(profileMessageEl, `Activated ${payload.active_profile}.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Activate failed: ${error.message}`, 'danger');
  }
});

saveProfileButton?.addEventListener('click', async () => {
  const name = profileSelectEl?.value;
  if (!name) {
    return;
  }
  try {
    const payload = await saveProfile(name, collectProfileSettings());
    renderProfileSettings(payload.settings ?? {});
    await Promise.all([refreshRuntime(), refreshOutputSettings(), refreshModels()]);
    setMessage(profileMessageEl, `Saved ${payload.profile}.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Save failed: ${error.message}`, 'danger');
  }
});

createProfileButton?.addEventListener('click', async () => {
  const name = newProfileNameEl?.value?.trim();
  if (!name) {
    setMessage(profileMessageEl, 'Enter a profile name first.', 'warning');
    return;
  }
  try {
    const payload = await createProfile(name, collectProfileSettings());
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.profile);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `Created ${payload.profile}. Activate it when ready.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Create failed: ${error.message}`, 'danger');
  }
});

discardProfileChangesButton?.addEventListener('click', async () => {
  const name = profileSelectEl?.value;
  if (!name) {
    return;
  }
  try {
    const payload = await fetchProfile(name);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `Discarded changes for ${payload.profile}.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Discard failed: ${error.message}`, 'danger');
  }
});

deleteProfileButton?.addEventListener('click', async () => {
  const name = profileSelectEl?.value;
  if (!name || name === 'Default') {
    setMessage(profileMessageEl, 'Default profile cannot be deleted.', 'warning');
    return;
  }
  try {
    const payload = await deleteProfile(name);
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
    renderProfileSettings(payload.settings ?? {});
    await Promise.all([refreshRuntime(), refreshOutputSettings()]);
    setMessage(profileMessageEl, `Deleted ${name}.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Delete failed: ${error.message}`, 'danger');
  }
});

refreshModelsButton?.addEventListener('click', () => {
  refreshModels().catch((error) => setMessage(modelMessageEl, `Refresh failed: ${error.message}`, 'danger'));
});

selectLlmModelButton?.addEventListener('click', () => {
  const modelId = llmModelSelectEl?.value;
  runModelAction(selectLlmModelButton, 'Select LLM', () => selectLlmModel(modelId));
});

downloadLlmModelButton?.addEventListener('click', () => {
  const modelId = llmModelSelectEl?.value;
  runModelAction(downloadLlmModelButton, 'Download LLM', () => downloadLlmModel(modelId));
});

deleteLlmModelButton?.addEventListener('click', () => {
  const modelId = llmModelSelectEl?.value;
  runModelAction(deleteLlmModelButton, 'Delete LLM', () => deleteLlmModel(modelId));
});

downloadWhisperButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  runModelAction(downloadWhisperButton, 'Download Whisper', () => downloadWhisperModel(modelSize));
});

testWhisperButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  runModelAction(testWhisperButton, 'Test Whisper', () => testWhisperModel(modelSize));
});

deleteWhisperButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  runModelAction(deleteWhisperButton, 'Delete Whisper', () => deleteWhisperModel(modelSize));
});

unloadSttButton?.addEventListener('click', () => {
  runModelAction(unloadSttButton, 'Unload STT', () => unloadModel('stt'));
});

unloadLlmButton?.addEventListener('click', () => {
  runModelAction(unloadLlmButton, 'Unload LLM', () => unloadModel('llm'));
});

unloadTtsButton?.addEventListener('click', () => {
  runModelAction(unloadTtsButton, 'Unload TTS', () => unloadModel('tts'));
});

saveDraftEditButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  saveDraftEditButton.disabled = true;
  saveDraftEditButton.textContent = 'Saving...';
  try {
    await saveCurrentDraftEdit();
  } catch (error) {
    setMessage(draftMessageEl, `Save failed: ${error.message}`, 'danger');
  } finally {
    saveDraftEditButton.textContent = 'Save Edit';
    setDraftControlsEnabled(Boolean(latestDraft));
  }
});

rewriteShorterButton?.addEventListener('click', () => {
  runRewriteAction(rewriteShorterButton, 'shorter');
});

rewriteClearerButton?.addEventListener('click', () => {
  runRewriteAction(rewriteClearerButton, 'clearer');
});

rewriteToneButton?.addEventListener('click', () => {
  runRewriteAction(rewriteToneButton, 'tone');
});

rewriteCustomButton?.addEventListener('click', () => {
  const instruction = customRewriteInstructionEl?.value?.trim() ?? '';
  if (!instruction) {
    setMessage(draftMessageEl, 'Add a custom rewrite instruction first.', 'warning');
    return;
  }
  runRewriteAction(rewriteCustomButton, 'custom', instruction);
});

readSelectionButton?.addEventListener('click', () => {
  runDraftTts(true);
});

readFullDraftButton?.addEventListener('click', () => {
  runDraftTts(false);
});

draftFinalTextEl?.addEventListener('input', () => {
  const words = getDraftEditorText().trim().split(/\s+/).filter(Boolean).length;
  const tokenLimit = Number(latestDraft?.token_limit ?? 0);
  renderTokenSummary({
    token_count: words,
    token_limit: tokenLimit,
    long_text: Boolean(tokenLimit && words > tokenLimit),
  });
  setDraftControlsEnabled(Boolean(latestDraft));
});

copyDraftButton?.addEventListener('click', async () => {
  try {
    await copyCurrentDraftText();
  } catch (error) {
    setMessage(draftMessageEl, `Copy failed: ${error.message}`, 'danger');
  }
});

acceptDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  try {
    await saveCurrentDraftEdit({ silent: true });
    const draft = await acceptDraft(latestDraft.id);
    renderDraft(draft);
    await refreshOutputSettings();
    setMessage(draftMessageEl, 'Draft accepted and queued for primary action send.', 'success');
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
    await refreshOutputSettings();
    setMessage(draftMessageEl, 'Draft declined.', 'success');
  } catch (error) {
    setMessage(draftMessageEl, `Decline failed: ${error.message}`, 'danger');
  }
});

retryDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  retryDraftButton.disabled = true;
  retryDraftButton.textContent = 'Retrying...';
  try {
    const draft = await retryDraft(latestDraft.id);
    renderDraft(draft);
    await refreshDrafts();
    setMessage(draftMessageEl, draft.status === 'pending' ? 'Retry created a new draft.' : 'Retry completed with a draft state update.', draft.status === 'pending' ? 'success' : 'warning');
  } catch (error) {
    setMessage(draftMessageEl, `Retry failed: ${error.message}`, 'danger');
  } finally {
    retryDraftButton.textContent = 'Retry';
    setDraftControlsEnabled(Boolean(latestDraft));
  }
});

sendDraftButton?.addEventListener('click', async () => {
  if (!latestDraft?.id) {
    return;
  }

  sendDraftButton.disabled = true;
  sendDraftButton.textContent = 'Sending...';
  try {
    await saveCurrentDraftEdit({ silent: true });
    const action = outputSettings?.capabilities?.supports_input_injection ? 'paste' : 'copy_only';
    const draft = await sendDraft(latestDraft.id, { action });
    renderDraft(draft);
    await Promise.all([refreshDrafts(), refreshOutputSettings()]);
    setMessage(draftMessageEl, draft.send_result?.message || 'Draft send completed.', draft.send_result?.ok ? 'success' : 'danger');
  } catch (error) {
    setMessage(draftMessageEl, `Send failed: ${error.message}`, 'danger');
  } finally {
    sendDraftButton.textContent = 'Send / Copy';
    setDraftControlsEnabled(Boolean(latestDraft));
  }
});

document.addEventListener('keydown', async (event) => {
  const modifier = event.ctrlKey || event.metaKey;
  if (!modifier || !latestDraft?.id) {
    return;
  }

  const key = event.key.toLowerCase();
  try {
    if (event.shiftKey && key === 'enter') {
      event.preventDefault();
      sendDraftButton?.click();
    } else if (key === 'enter') {
      event.preventDefault();
      acceptDraftButton?.click();
    } else if (event.shiftKey && key === 'c') {
      event.preventDefault();
      await copyCurrentDraftText();
    } else if (key === 's') {
      event.preventDefault();
      await saveCurrentDraftEdit();
    } else if (key === 'd') {
      event.preventDefault();
      declineDraftButton?.click();
    }
  } catch (error) {
    setMessage(draftMessageEl, `Shortcut failed: ${error.message}`, 'danger');
  }
});

// Tab switching logic
const tabButtons = document.querySelectorAll('.tab-button');
const tabContents = document.querySelectorAll('.tab-content');

tabButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const targetTab = button.dataset.tab;

    tabButtons.forEach((btn) => btn.classList.remove('active'));
    button.classList.add('active');

    tabContents.forEach((content) => {
      if (content.id === `tab${targetTab.charAt(0).toUpperCase() + targetTab.slice(1)}`) {
        content.classList.add('active');
      } else {
        content.classList.remove('active');
      }
    });

    if (targetTab === 'diagnostics') {
      refreshDiagnostics().catch(() => {});
      refreshDoctor().catch(() => {});
    }
  });
});

// Sidecar Startup Logs
async function refreshSidecarLogs() {
  if (!sidecarLogsTail) {
    return;
  }
  try {
    const logs = await window.betterFingers?.getSidecarLogs?.();
    if (Array.isArray(logs)) {
      sidecarLogsTail.textContent = logs.length ? logs.join('\n') : 'No captured logs from sidecar process yet.';
    } else {
      sidecarLogsTail.textContent = 'Sidecar logs are not available.';
    }
  } catch (error) {
    sidecarLogsTail.textContent = `Failed to retrieve sidecar logs: ${error.message}`;
  }
}

clearSidecarLogsButton?.addEventListener('click', () => {
  if (sidecarLogsTail) {
    sidecarLogsTail.textContent = '';
  }
});

// Doctor Health Checkup
async function refreshDoctor(refreshAudio = false) {
  if (!doctorCardsGrid) {
    return;
  }
  
  if (refreshDoctorButton) {
    refreshDoctorButton.disabled = true;
    refreshDoctorButton.textContent = 'Running check...';
  }

  try {
    const doctor = await fetchDoctor(refreshAudio);
    
    doctorCardsGrid.innerHTML = '';
    
    const subsystems = [
      { id: 'stt', name: 'STT (Transcriber)', data: doctor.stt },
      { id: 'llm', name: 'LLM Engine', data: doctor.llm },
      { id: 'tts', name: 'TTS (Read-Aloud)', data: doctor.tts },
      { id: 'hotkeys', name: 'Hotkey Manager', data: doctor.hotkeys },
      { id: 'models', name: 'Model Paths', data: doctor.models },
      { id: 'audio', name: 'Audio System', data: doctor.audio },
      { id: 'platform', name: 'Platform Capabilities', data: doctor.platform }
    ];

    let recoveryTriggers = [];

    for (const sub of subsystems) {
      const card = document.createElement('div');
      card.className = 'doctor-card';

      const header = document.createElement('div');
      header.className = 'doctor-card-header';
      
      const title = document.createElement('span');
      title.textContent = sub.name;

      const badge = document.createElement('span');
      badge.className = 'doctor-card-status';

      let detailsText = '';
      
      if (sub.id === 'stt') {
        const isLoaded = sub.data.loaded;
        const isInit = sub.data.initialized;
        badge.textContent = isLoaded ? 'Loaded' : isInit ? 'Initialized' : 'Offline';
        badge.dataset.tone = isLoaded ? 'success' : isInit ? 'warning' : 'danger';
        detailsText = `Initialized: ${isInit ? 'Yes' : 'No'}\nLoaded: ${isLoaded ? 'Yes' : 'No'}\nModel Size: ${sub.data.model_size ?? 'None'}\nDevice: ${sub.data.device ?? 'None'}`;
        if (!isInit) {
          recoveryTriggers.push('missing_model');
        }
      } else if (sub.id === 'llm') {
        const isReady = sub.data.ready;
        const isInit = sub.data.initialized;
        badge.textContent = isReady ? 'Ready' : isInit ? 'Warming Up' : 'Offline';
        badge.dataset.tone = isReady ? 'success' : isInit ? 'warning' : 'danger';
        detailsText = `Initialized: ${isInit ? 'Yes' : 'No'}\nReady: ${isReady ? 'Yes' : 'No'}\nSelected Model: ${sub.data.model_id ?? 'None'}\nllama-server: ${sub.data.llama_server_exists ? 'Found' : 'Missing'}`;
        if (!sub.data.llama_server_exists) {
          recoveryTriggers.push('missing_llama_server');
        }
        if (!isInit && sub.data.llama_server_exists) {
          recoveryTriggers.push('missing_model');
        }
      } else if (sub.id === 'tts') {
        const isLoaded = sub.data.loaded;
        const isInit = sub.data.initialized;
        badge.textContent = isLoaded ? 'Active' : isInit ? 'Offline' : 'Error';
        badge.dataset.tone = isLoaded ? 'success' : isInit ? 'warning' : 'danger';
        detailsText = `Provider: ${sub.data.backend}\nLoaded: ${isLoaded ? 'Yes' : 'No'}\nStatus: ${sub.data.status_message}\nFallback Active: ${sub.data.fallback ? 'Yes' : 'No'}`;
        if (sub.data.backend === 'none') {
          recoveryTriggers.push('failed_tts_dependency');
        }
      } else if (sub.id === 'hotkeys') {
        const isStarted = sub.data.started;
        const isActive = sub.data.active;
        badge.textContent = isActive ? 'Listening' : isStarted ? 'Started' : 'Stopped';
        badge.dataset.tone = isActive ? 'success' : isStarted ? 'warning' : 'danger';
        detailsText = `Manager Started: ${isStarted ? 'Yes' : 'No'}\nHotkey Thread Active: ${isActive ? 'Yes' : 'No'}`;
      } else if (sub.id === 'models') {
        const defaultExists = sub.data.default_model_exists;
        badge.textContent = defaultExists ? 'Verified' : 'Missing Default';
        badge.dataset.tone = defaultExists ? 'success' : 'danger';
        detailsText = `Models Folder: ${sub.data.models_dir}\nDefault Model (Gemma): ${defaultExists ? 'Found' : 'Missing'}`;
        if (!defaultExists) {
          recoveryTriggers.push('missing_model');
        }
      } else if (sub.id === 'audio') {
        const hasDevices = Array.isArray(sub.data.devices) && sub.data.devices.length > 0;
        badge.textContent = hasDevices ? 'Available' : 'No Mics';
        badge.dataset.tone = hasDevices ? 'success' : 'danger';
        
        let micNames = 'No devices detected.';
        if (hasDevices) {
          const defaultInIdx = sub.data.default_input_device;
          const defaultMic = sub.data.devices.find(d => d.index === defaultInIdx);
          micNames = `Default Mic: ${defaultMic ? defaultMic.name : 'System Default'}\nTotal Devices: ${sub.data.devices.length}`;
        }
        detailsText = `${micNames}\nSounddevice Error: ${sub.data.error ?? 'None'}`;
        if (!hasDevices || sub.data.error) {
          recoveryTriggers.push('microphone_unavailable');
        }
      } else if (sub.id === 'platform') {
        const injection = sub.data.supports_input_injection;
        badge.textContent = injection ? 'Fully Supported' : 'Limited';
        badge.dataset.tone = injection ? 'success' : 'warning';
        detailsText = `Platform: ${sub.data.platform}\nSession: ${sub.data.session_type}\nInput Injection: ${injection ? 'Yes' : 'No'}\nGlobal Hotkeys: ${sub.data.supports_global_hotkeys ? 'Yes' : 'No'}`;
        if (sub.data.is_wayland && !injection) {
          recoveryTriggers.push('unsupported_wayland_injection');
        }
      }

      header.append(title, badge);
      
      const detail = document.createElement('pre');
      detail.className = 'doctor-card-detail';
      detail.textContent = detailsText;

      card.append(header, detail);
      doctorCardsGrid.append(card);
    }

    if (doctorRecoveryPanel && doctorRecoveryList) {
      doctorRecoveryList.innerHTML = '';
      const uniqueTriggers = [...new Set(recoveryTriggers)];
      
      if (uniqueTriggers.length > 0) {
        doctorRecoveryPanel.classList.remove('hidden');
        for (const trigger of uniqueTriggers) {
          const recommendation = doctor.recovery[trigger];
          if (recommendation) {
            const item = document.createElement('div');
            item.className = 'recovery-item';
            
            const labelMap = {
              missing_model: 'Model Download Needed',
              missing_llama_server: 'llama-server Required',
              port_conflict: 'Port Conflict',
              microphone_unavailable: 'Microphone Not Found',
              unsupported_wayland_injection: 'Wayland Restriction',
              failed_clipboard: 'Clipboard Failure',
              failed_tts_dependency: 'TTS Missing'
            };

            const title = document.createElement('strong');
            title.textContent = `[${labelMap[trigger] ?? trigger}] `;

            const text = document.createTextNode(recommendation);
            item.append(title, text);
            doctorRecoveryList.append(item);
          }
        }
      } else {
        doctorRecoveryPanel.classList.add('hidden');
      }
    }

  } catch (error) {
    if (doctorCardsGrid) {
      doctorCardsGrid.innerHTML = `<span class="empty-state" data-tone="danger">Doctor check failed: ${error.message}. Is the backend running?</span>`;
    }
    doctorRecoveryPanel?.classList.add('hidden');
  } finally {
    if (refreshDoctorButton) {
      refreshDoctorButton.disabled = false;
      refreshDoctorButton.textContent = 'Run Doctor Check';
    }
  }
}

refreshDoctorButton?.addEventListener('click', () => {
  refreshDoctor(true).catch(() => {});
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
