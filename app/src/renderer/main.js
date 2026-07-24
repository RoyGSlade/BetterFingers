import {
  activateProfile,
  createProfile,
  deleteProfile,
  deleteLlmModel,
  deleteWhisperModel,
  downloadLlmModel,
  downloadWhisperModel,
  emergencyStop,
  fetchCapabilities,
  fetchDiagnosticsLogs,
  fetchDiagnosticsPaths,
  fetchSupportReport,
  fetchMetrics,
  fetchPrivacy,
  wipeData,
  fetchRecordings,
  retranscribeRecording,
  deleteRecording,
  fetchJobs,
  cancelJob,
  clearRecordings,
  fetchDictionary,
  addDictionaryTerm,
  deleteDictionaryTerm,
  suggestDictionaryTerms,
  fetchLlmDownloadState,
  fetchLlmModels,
  fetchOutputSettings,
  fetchProfile,
  fetchProfiles,
  fetchRuntimeErrors,
  fetchWhisperModels,
  runPrimaryAction,
  saveProfile,
  selectLlmModel,
  selectWhisperModel,
  toggleRecording,
  unloadModel,
  warmupRuntime,
  fetchDoctor,
  fetchPersonas,
  provisionVoiceCloning,
  renameProfile,
  duplicateProfile,
  exportProfile,
  importProfile,
  fetchModelRecommendation,
  fetchMacros,
  addMacro,
  deleteMacro,
  fetchWakeStatus,
  fetchWakeModels,
  enableWake,
  disableWake,
  downloadWakeModel,
  fetchWakeModelDownloadState,
  testWake,
  trainWakePhrase,
  fetchWakeTrainStatus,
  importWakeModel,
} from './api/backend.js';
import { summarizeWipeFailure } from './lib/wipeSummary.mjs';
import { createDraftsFeature } from './features/drafts.js';
import { createPersonasFeature } from './features/personas.js';
import { createRuntimeFeature } from './features/runtime.js';
import { createVoiceStudioFeature } from './features/voiceStudio.js';
import { initMessageRescueDraft } from './features/messageRescueDraft.js';

// --- Composition root ---
// main.js owns every DOM element lookup and wires them, in file order, to the
// three extracted feature modules plus the profile/model/settings/diagnostics/
// privacy/dictionary/macros/wake-word/voice-studio/onboarding logic that stays
// here. Nothing below constructs its own document.getElementById calls for
// elements another module already owns — dependencies flow one way, in via
// `elements`/`ui`/`hooks`, state and DOM access back out via the feature's
// returned API.
//
// Initialization order (top of file to bottom):
//   1. DOM element consts (this section) — every element any feature or local
//      handler needs is looked up exactly once, here.
//   2. `drafts` = createDraftsFeature(...) — owns latestDraft/draftHistory
//      state. Its `ui` hooks (setMessage/showToast/escapeHtml/renderSendResult)
//      are plain `function` declarations defined further down this file; that
//      only works because function declarations are hoisted — if any of those
//      were converted to `const fn = () => {}`, this call would throw (TDZ)
//      since it runs before that line is reached.
//   3. `settingEls` — the settings-panel element map, needed by both the
//      personas feature (current_preset select) and initSettingsPanel() below.
//   4. `personas` = createPersonasFeature(...) — owns the wizard/Foundry
//      state; reads the live persona list via hooks.getLoadedPersonas()
//      rather than a snapshot, since `loadedPersonas` is refreshed later by
//      refreshPersonasAndVoices().
//   5. `runtime` = createRuntimeFeature(...) — owns health/runtime polling and
//      bootstrap(). Its hooks list every refresh*/render* function the other
//      two features and this file expose, because bootstrap()'s
//      loadInitialData() fans out to all of them. `initFeaturePanels` (one of
//      those hooks) is what actually calls personas.initWizard(),
//      personas.initFoundry(), initSettingsPanel(), and initOnboarding() —
//      deferred until bootstrap() runs so those panels initialize only after
//      the first profile/settings load, in the same relative order they
//      always have.
//   6. Local helpers, event listener registrations, and one-off panels
//      (profiles, models, diagnostics, privacy, dictionary, macros, wake word,
//      voice studio, doctor, appearance) — order among these doesn't matter,
//      none of them run until a user interaction or bootstrap() triggers them.
//   7. `bootstrap().catch(...)` at the bottom of the file is the single entry
//      point that starts everything async: health check -> initial data load
//      (runtime/capabilities/drafts/output-settings/profiles/models/
//      diagnostics/doctor/sidecar-logs/ptt) -> health polling + websocket ->
//      initFeaturePanels(). `initOverlayAppearanceControls()` runs
//      independently right after, since it talks to the Electron bridge
//      directly and has no backend dependency.

const backendStatusEl = document.getElementById('backendStatus');
const backendDetailEl = document.getElementById('backendDetail');
const transcriberStatusEl = document.getElementById('transcriberStatus');
const llmStatusEl = document.getElementById('llmStatus');
const wsConnectionEl = document.getElementById('wsConnection');
const voiceStatusEl = document.getElementById('voiceStatus');
const voiceStatusDetailEl = document.getElementById('voiceStatusDetail');
const quitButton = document.getElementById('quitButton');
const warmupSttButton = document.getElementById('warmupSttButton');
const warmupLlmButton = document.getElementById('warmupLlmButton');
const startHotkeysButton = document.getElementById('startHotkeysButton');
const primaryActionButton = document.getElementById('primaryActionButton');
const emergencyStopButton = document.getElementById('emergencyStopButton');
const runtimeStatusListEl = document.getElementById('runtimeStatusList');
const warmupMessageEl = document.getElementById('warmupMessage');
const outputSettingsSummaryEl = document.getElementById('outputSettingsSummary');
const capabilitiesListEl = document.getElementById('capabilitiesList');
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
const sendActionSelectEl = document.getElementById('sendActionSelect');
const sendDraftButton = document.getElementById('sendDraftButton');
const draftMessageEl = document.getElementById('draftMessage');
const toggleRecordingButton = document.getElementById('toggleRecordingButton');
const dashboardEmergencyStopButton = document.getElementById('dashboardEmergencyStopButton');
const recordingControlStatusEl = document.getElementById('recordingControlStatus');
const sendResultPanelEl = document.getElementById('sendResultPanel');
const draftMetadataEl = document.getElementById('draftMetadata');
const draftHistoryListEl = document.getElementById('draftHistoryList');
const clearDraftHistoryButton = document.getElementById('clearDraftHistoryButton');
const refreshDiagnosticsButton = document.getElementById('refreshDiagnosticsButton');
const copySupportReportButton = document.getElementById('copySupportReportButton');
const sidecarStatusEl = document.getElementById('sidecarStatus');
const diagnosticsPathsListEl = document.getElementById('diagnosticsPathsList');
const runtimeErrorsListEl = document.getElementById('runtimeErrorsList');
const debugLogTailEl = document.getElementById('debugLogTail');
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
const llmModelBadgeEl = document.getElementById('llmModelBadge');
const whisperModelBadgeEl = document.getElementById('whisperModelBadge');
const llmModelDetailsEl = document.getElementById('llmModelDetails');
const whisperModelDetailsEl = document.getElementById('whisperModelDetails');
const llmDownloadProgressEl = document.getElementById('llmDownloadProgress');
const llmDownloadProgressLabelEl = document.getElementById('llmDownloadProgressLabel');
const llmDownloadProgressPercentEl = document.getElementById('llmDownloadProgressPercent');
const llmDownloadProgressFillEl = document.getElementById('llmDownloadProgressFill');
const llmDownloadProgressBytesEl = document.getElementById('llmDownloadProgressBytes');
const selectLlmModelButton = document.getElementById('selectLlmModelButton');
const downloadLlmModelButton = document.getElementById('downloadLlmModelButton');
const deleteLlmModelButton = document.getElementById('deleteLlmModelButton');
const selectWhisperModelButton = document.getElementById('selectWhisperModelButton');
const downloadWhisperButton = document.getElementById('downloadWhisperButton');
const deleteWhisperButton = document.getElementById('deleteWhisperButton');
const unloadSttButton = document.getElementById('unloadSttButton');
const unloadLlmButton = document.getElementById('unloadLlmButton');
const unloadTtsButton = document.getElementById('unloadTtsButton');
const voiceCloningBadgeEl = document.getElementById('voiceCloningBadge');
const voiceCloningStatusEl = document.getElementById('voiceCloningStatus');
const voiceCloningHintEl = document.getElementById('voiceCloningHint');
const provisionVoiceCloningButton = document.getElementById('provisionVoiceCloningButton');

const wizardStepProgress = document.getElementById('wizardStepProgress');
const wizardPrevButton = document.getElementById('wizardPrevButton');
const wizardNextButton = document.getElementById('wizardNextButton');
const wizardDeleteButton = document.getElementById('wizardDeleteButton');
const wizardMessage = document.getElementById('wizardMessage');
const wizardRole = document.getElementById('wizardRole');
const wizardCustomRole = document.getElementById('wizardCustomRole');
const wizardCustomRoleLabel = document.getElementById('wizardCustomRoleLabel');
const wizardTone = document.getElementById('wizardTone');
const wizardCustomTone = document.getElementById('wizardCustomTone');
const wizardCustomToneLabel = document.getElementById('wizardCustomToneLabel');
const wizardRuleLength = document.getElementById('wizardRuleLength');
const wizardRuleCommands = document.getElementById('wizardRuleCommands');
const wizardRuleNoPreamble = document.getElementById('wizardRuleNoPreamble');
const wizardRuleSanitize = document.getElementById('wizardRuleSanitize');
const wizardPersonaName = document.getElementById('wizardPersonaName');
const wizardPromptPreview = document.getElementById('wizardPromptPreview');
const wizardRegeneratePromptButton = document.getElementById('wizardRegeneratePromptButton');
const wizardTemperature = document.getElementById('wizardTemperature');
const wizardModelHint = document.getElementById('wizardModelHint');
const wizardFormatCaps = document.getElementById('wizardFormatCaps');
const wizardFormatPunctuation = document.getElementById('wizardFormatPunctuation');
const wizardFormatSignoff = document.getElementById('wizardFormatSignoff');
const wizardOutputPolicy = document.getElementById('wizardOutputPolicy');
const wizardSafetyMode = document.getElementById('wizardSafetyMode');
const wizardMaxCompletionTokens = document.getElementById('wizardMaxCompletionTokens');
const wizardChunkSize = document.getElementById('wizardChunkSize');
const wizardFewShotList = document.getElementById('wizardFewShotList');
const wizardAddFewShotButton = document.getElementById('wizardAddFewShotButton');
const wizardLintButton = document.getElementById('wizardLintButton');
const wizardLintWarnings = document.getElementById('wizardLintWarnings');
const wizardTestSample = document.getElementById('wizardTestSample');
const wizardTestButton = document.getElementById('wizardTestButton');
const wizardTestResult = document.getElementById('wizardTestResult');
const wizardRefinePromptButton = document.getElementById('wizardRefinePromptButton');
const wizardRefineStatus = document.getElementById('wizardRefineStatus');
const wizardRefinePanel = document.getElementById('wizardRefinePanel');
const wizardRefineUnderstood = document.getElementById('wizardRefineUnderstood');
const wizardRefineAmbiguities = document.getElementById('wizardRefineAmbiguities');
const wizardRefinedPrompt = document.getElementById('wizardRefinedPrompt');
const wizardApplyRefinedButton = document.getElementById('wizardApplyRefinedButton');
const wizardDismissRefinedButton = document.getElementById('wizardDismissRefinedButton');
const wizardRefinePromptBlock = document.getElementById('wizardRefinePromptBlock');
const wizardRefineActions = document.getElementById('wizardRefineActions');
const wizardDescribeInput = document.getElementById('wizardDescribeInput');
const wizardDescribeButton = document.getElementById('wizardDescribeButton');
const wizardDescribeStatus = document.getElementById('wizardDescribeStatus');
const wizardAdvanced = document.getElementById('wizardAdvanced');

let loadedPersonas = {};

const versionMismatchBanner = document.getElementById('versionMismatchBanner');
const backendBannerTitleEl = document.getElementById('backendBannerTitle');
const backendBannerMessageEl = document.getElementById('backendBannerMessage');
const refreshDoctorButton = document.getElementById('refreshDoctorButton');
const doctorCardsGrid = document.getElementById('doctorCardsGrid');
const doctorRecoveryPanel = document.getElementById('doctorRecoveryPanel');
const doctorRecoveryList = document.getElementById('doctorRecoveryList');
const clearSidecarLogsButton = document.getElementById('clearSidecarLogsButton');
const sidecarLogsTail = document.getElementById('sidecarLogsTail');

let outputSettings = null;
let activeProfileSettings = null;
let profileDirty = false;
let llmModelsPayload = null;
let whisperModelsPayload = null;

// Step 2 of the composition order (see the header comment above the imports):
// ui hooks below resolve via hoisted `function` declarations further down.
const drafts = createDraftsFeature({
  elements: {
    draftStatusEl, draftRawTextEl, draftFinalTextEl, draftTokenSummaryEl,
    saveDraftEditButton, rewriteShorterButton, rewriteClearerButton, rewriteToneButton,
    customRewriteInstructionEl, rewriteCustomButton, readSelectionButton, readFullDraftButton,
    copyDraftButton, acceptDraftButton, declineDraftButton, retryDraftButton, sendDraftButton,
    draftMessageEl, draftMetadataEl, draftHistoryListEl,
  },
  ui: { setMessage, showToast, escapeHtml, renderSendResult },
  hooks: {
    getSelectedSendAction,
    gatherVoiceStudioSettings,
    onDraftEdited: maybeLearnFromEdit,
    refreshOutputSettings,
  },
});
const {
  renderDraft, handleHistorySearch, refreshLatestDraft, refreshDrafts,
  runRewriteAction, runDraftTts,
} = drafts;

// I3.5-I3.7: Message Rescue live-bound to the Review Draft panel. Behind the
// same default-off pref_message_rescue_enabled flag as F2.8's static preview
// panel; a no-op (returns null) when the flag is off or the markup is
// missing. `applyToEditor` is the one piece of state this module doesn't own
// itself -- it writes a selected variant into the existing final-text editor
// and replays the same handler main.js already wires to that textarea's own
// `input` event (line ~3695), so token-summary/control-enablement stay in
// sync exactly as if the user had typed the replacement themselves. Raw
// transcript (draftRawTextEl) is never touched.
const messageRescueDraft = initMessageRescueDraft({
  hooks: {
    applyToEditor(text) {
      if (!draftFinalTextEl) return;
      draftFinalTextEl.value = text;
      drafts.handleDraftTextInput();
    },
  },
});

const settingEls = {
  hotkey: document.getElementById('settingHotkey'),
  recording_mode: document.getElementById('settingRecordingMode'),
  force_stop_key: document.getElementById('settingForceStopKey'),
  manual_send_hotkey: document.getElementById('settingManualSendHotkey'),
  review_tts_hotkey: document.getElementById('settingReviewTtsHotkey'),
  chat_open_key: document.getElementById('settingChatOpenKey'),
  voice_mute_key: document.getElementById('settingVoiceMuteKey'),
  send_mode: document.getElementById('settingSendMode'),
  confidence_force_review_enabled: document.getElementById('settingConfidenceForceReview'),
  confidence_force_review_below: document.getElementById('settingConfidenceForceReviewBelow'),
  confidence_auto_send_above: document.getElementById('settingConfidenceAutoSendAbove'),
  auto_stop_after_silence_enabled: document.getElementById('settingAutoStopSilence'),
  auto_stop_silence_ms: document.getElementById('settingAutoStopSilenceMs'),
  auto_stop_min_recording_ms: document.getElementById('settingAutoStopMinMs'),
  current_preset: document.getElementById('settingCurrentPreset'),
  max_completion_tokens: document.getElementById('settingMaxCompletionTokens'),
  long_draft_warning_words: document.getElementById('settingLongDraftWarningWords'),
  long_recording_stitch_pass_enabled: document.getElementById('settingStitchPass'),
  llm_chunk_size: document.getElementById('settingLlmChunkSize'),
  whisper_chunk_size: document.getElementById('settingWhisperChunkSize'),
  review_tts_voice_hint: document.getElementById('settingReviewTtsVoiceHint'),
  review_tts_speed: document.getElementById('settingReviewTtsSpeed'),
  no_audio_min_duration_sec: document.getElementById('settingNoAudioDuration'),
  no_audio_min_rms: document.getElementById('settingNoAudioRms'),
  no_audio_min_peak: document.getElementById('settingNoAudioPeak'),
  auto_submit: document.getElementById('settingAutoSubmit'),
  instant_typing: document.getElementById('settingInstantTyping'),
  restore_clipboard_after_paste: document.getElementById('settingRestoreClipboard'),
  voice_commands_enabled: document.getElementById('settingVoiceCommands'),
  macros_enabled: document.getElementById('settingMacrosEnabled'),
  input_device_index: document.getElementById('settingInputDevice'),
  audio_ducking: document.getElementById('settingAudioDucking'),
  status_indicator_enabled: document.getElementById('settingStatusIndicator'),
  notification_overlay_enabled: document.getElementById('settingNotificationOverlay'),
  preview_overlay_enabled: document.getElementById('settingPreviewOverlay'),
  model_keep_llm_loaded: document.getElementById('settingKeepLlm'),
  model_keep_stt_loaded: document.getElementById('settingKeepStt'),
  model_keep_tts_loaded: document.getElementById('settingKeepTts'),
  wake_word_model: document.getElementById('settingWakeWordModel'),
  wake_word_sensitivity: document.getElementById('settingWakeWordSensitivity'),
  wake_word_cooldown_s: document.getElementById('settingWakeWordCooldown'),
  wake_word_max_recording_s: document.getElementById('settingWakeWordMaxRecording'),
};

// Step 4: getLoadedPersonas reads live state (loadedPersonas is populated
// later by refreshPersonasAndVoices), not a snapshot taken at this line.
const personas = createPersonasFeature({
  elements: {
    wizardStepProgress, wizardPrevButton, wizardNextButton, wizardDeleteButton, wizardMessage,
    wizardRole, wizardCustomRole, wizardCustomRoleLabel, wizardTone, wizardCustomTone, wizardCustomToneLabel,
    wizardRuleLength, wizardRuleCommands, wizardRuleNoPreamble, wizardRuleSanitize,
    wizardPersonaName, wizardPromptPreview, wizardRegeneratePromptButton,
    wizardTemperature, wizardModelHint, wizardFormatCaps, wizardFormatPunctuation, wizardFormatSignoff,
    wizardOutputPolicy, wizardSafetyMode, wizardMaxCompletionTokens, wizardChunkSize,
    wizardFewShotList, wizardAddFewShotButton, wizardLintButton, wizardLintWarnings,
    wizardTestSample, wizardTestButton, wizardTestResult,
    // AI helper (refine + from-scratch draft) panel elements
    wizardRefinePromptButton, wizardRefineStatus, wizardRefinePanel,
    wizardRefineUnderstood, wizardRefineAmbiguities, wizardRefinedPrompt,
    wizardApplyRefinedButton, wizardDismissRefinedButton,
    wizardRefinePromptBlock, wizardRefineActions,
    wizardDescribeInput, wizardDescribeButton, wizardDescribeStatus, wizardAdvanced,
    currentPresetSelect: settingEls.current_preset,
  },
  ui: { setMessage, showToast },
  hooks: {
    getLoadedPersonas: () => loadedPersonas,
    refreshPersonasAndVoices,
    markProfileDirty,
  },
});

// voiceStudio owns base voice + blend + modulation (Settings > TTS/Read-Aloud
// > Voice Studio). `voiceStudio` is a `const` declared here, but nothing
// below calls into it until bootstrap() actually runs (well after this line
// executes) — same hoisting-safe pattern as the ui hooks above.
const voiceStudio = createVoiceStudioFeature({
  ui: { setMessage, showToast },
  hooks: {
    markProfileDirty,
    renderVoiceCloningPanel,
  },
});

// Kept as a bare function (not `voiceStudio.gatherVoiceStudioSettings`) so it
// can be referenced by name in the drafts feature's hooks below via plain
// hoisting, the same as every other cross-feature hook in this file.
function gatherVoiceStudioSettings() {
  return voiceStudio.gatherVoiceStudioSettings();
}

// Step 5: hooks below are every refresh*/render* function bootstrap()'s
// loadInitialData() fans out to (see runtime.js), most defined further down
// this file (hoisted, like the drafts feature's ui hooks above).
const runtime = createRuntimeFeature({
  elements: {
    backendStatusEl, backendDetailEl, transcriberStatusEl, llmStatusEl, runtimeStatusListEl,
    toggleRecordingButton, recordingControlStatusEl, sidecarStatusEl,
    versionMismatchBanner, backendBannerTitleEl, backendBannerMessageEl, wsConnectionEl,
    capabilitiesListEl, outputSettingsSummaryEl, profileMessageEl, modelMessageEl,
  },
  ui: { setBadgeState, renderDetailList, showToast, setMessage },
  hooks: {
    refreshCapabilities,
    refreshDrafts,
    renderDraft,
    refreshOutputSettings,
    refreshProfiles,
    refreshModels,
    refreshDiagnostics,
    refreshDoctor,
    refreshSidecarLogs,
    refreshPttAvailability,
    onVoiceStatusMessage: updateVoiceStatus,
    // Deferred until bootstrap() actually runs (not called at composition
    // time above) so these panels initialize only after the first
    // profile/settings load, preserving the original startup order.
    initFeaturePanels: () => {
      personas.initWizard();
      personas.initFoundry();
      initSettingsPanel();
      initOnboarding();
    },
  },
});
const { refreshHealth, refreshRuntime, refreshSidecarStatus, bootstrap } = runtime;

function setupHotkeyRecording(inputEl) {
  if (!inputEl) return;

  let activeKeys = new Set();
  let accumulatedKeys = [];
  let isRecording = false;

  function getStandardKeyName(event) {
    const key = event.key;
    const specialKeys = {
      ' ': 'space',
      'Control': 'ctrl',
      'Shift': 'shift',
      'Alt': 'alt',
      'Meta': 'meta',
      'Escape': 'escape',
      'ArrowUp': 'up',
      'ArrowDown': 'down',
      'ArrowLeft': 'left',
      'ArrowRight': 'right',
      'CapsLock': 'capslock',
      'PageUp': 'pageup',
      'PageDown': 'pagedown',
      'Delete': 'delete',
      'Insert': 'insert',
      'Home': 'home',
      'End': 'end',
      'Backspace': 'backspace',
      'Tab': 'tab',
      'Enter': 'enter'
    };

    if (specialKeys[key]) {
      return specialKeys[key];
    }
    if (/^f[0-9]+$/i.test(key)) {
      return key.toUpperCase();
    }
    if (key.length === 1) {
      return key.toUpperCase();
    }
    return key.toLowerCase();
  }

  inputEl.addEventListener('keydown', (e) => {
    e.preventDefault();
    e.stopPropagation();

    const standardName = getStandardKeyName(e);
    if (!standardName) return;

    if (!isRecording) {
      isRecording = true;
      activeKeys.clear();
      accumulatedKeys = [];
    }

    if (!activeKeys.has(standardName)) {
      activeKeys.add(standardName);
      if (!accumulatedKeys.includes(standardName)) {
        accumulatedKeys.push(standardName);
      }
      
      inputEl.value = accumulatedKeys.join('+');
      
      // Mark profile dirty
      inputEl.dispatchEvent(new Event('input', { bubbles: true }));
    }
  });

  inputEl.addEventListener('keyup', (e) => {
    e.preventDefault();
    e.stopPropagation();

    const standardName = getStandardKeyName(e);
    if (standardName) {
      activeKeys.delete(standardName);
    }

    if (activeKeys.size === 0) {
      isRecording = false;
    }
  });

  inputEl.addEventListener('blur', () => {
    activeKeys.clear();
    isRecording = false;
  });
}

const HOTKEY_FIELDS = new Set([
  'hotkey',
  'force_stop_key',
  'manual_send_hotkey',
  'review_tts_hotkey',
  'chat_open_key',
  'voice_mute_key'
]);

for (const [key, el] of Object.entries(settingEls)) {
  if (el && HOTKEY_FIELDS.has(key)) {
    setupHotkeyRecording(el);
  }
}


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

function formatBytes(value) {
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

function renderLlmDownloadProgress(state = null, model = null) {
  if (!llmDownloadProgressEl) {
    return;
  }

  const status = String(state?.status || '').toLowerCase();
  const show = ['starting', 'downloading', 'complete', 'ready', 'already_installed', 'error'].includes(status);
  llmDownloadProgressEl.hidden = !show;
  // Drives the error styling (hides the meaningless 0% track for runtime errors).
  llmDownloadProgressEl.dataset.state = show ? status : '';
  if (!show) {
    return;
  }

  const percent = Math.max(0, Math.min(100, Number(state?.percent || 0)));
  const rounded = Math.round(percent);
  const message = state?.message || (model?.name ? `${model.name} download status` : 'Download status');
  const downloaded = formatBytes(state?.downloaded_bytes);
  const total = formatBytes(state?.total_bytes);

  if (llmDownloadProgressLabelEl) {
    llmDownloadProgressLabelEl.textContent = message;
  }
  if (llmDownloadProgressPercentEl) {
    llmDownloadProgressPercentEl.textContent = `${rounded}%`;
  }
  if (llmDownloadProgressFillEl) {
    llmDownloadProgressFillEl.style.width = `${percent}%`;
    llmDownloadProgressFillEl.dataset.tone = status === 'error' ? 'danger' : status === 'complete' || status === 'ready' || status === 'already_installed' ? 'success' : 'active';
  }
  if (llmDownloadProgressBytesEl) {
    llmDownloadProgressBytesEl.textContent = downloaded && total ? `${downloaded} of ${total}` : downloaded;
  }
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

function setModelBadge(el, installed, selected = false) {
  if (!el) {
    return;
  }
  if (installed) {
    el.textContent = selected ? 'Selected + installed' : 'Installed';
    el.dataset.tone = 'success';
    return;
  }
  el.textContent = selected ? 'Selected but missing' : 'Missing';
  el.dataset.tone = selected ? 'danger' : 'warning';
}

function renderModelDetailGrid(container, rows) {
  if (!container) {
    return;
  }
  container.innerHTML = '';
  for (const row of rows) {
    const item = document.createElement('div');
    item.className = 'model-detail';

    const label = document.createElement('span');
    label.textContent = row.label;

    const value = document.createElement('strong');
    value.textContent = formatValue(row.value);
    if (row.tone) {
      value.dataset.tone = row.tone;
    }

    item.append(label, value);
    container.append(item);
  }
}

function renderModelOverview(llmPayload, whisperPayload, selectedLlm, installedWhisper) {
  if (!modelStatusSummaryEl) {
    return;
  }
  modelStatusSummaryEl.innerHTML = '';

  // Honest LLM readiness: a model can be installed yet unable to run — most
  // commonly because the llama-server binary is present but too old for the
  // model (installed + binary present + not ready). Don't claim "Ready" then.
  const llmInstalled = Boolean(selectedLlm?.installed);
  const llmReady = selectedLlm?.ready === true;
  const runtimeExists = Boolean(llmPayload.llama_server_exists);
  const runtimeIncompatible = runtimeExists && llmInstalled && selectedLlm?.ready === false;

  let llmState;
  if (!llmInstalled) {
    llmState = { value: 'Needs download', tone: 'danger' };
  } else if (llmReady) {
    llmState = { value: 'Ready', tone: 'success' };
  } else if (runtimeIncompatible) {
    llmState = { value: 'Runtime outdated', tone: 'warning' };
  } else {
    llmState = { value: 'Not ready', tone: 'warning' };
  }

  let runtimeState;
  if (!runtimeExists) {
    runtimeState = { value: 'llama-server missing', tone: 'danger' };
  } else if (runtimeIncompatible) {
    runtimeState = { value: 'Update required', tone: 'warning' };
  } else {
    runtimeState = { value: 'llama-server found', tone: 'success' };
  }

  const stats = [
    {
      label: 'LLM',
      value: llmState.value,
      detail: selectedLlm?.name ?? llmPayload.selected_model_id ?? 'Unknown model',
      tone: llmState.tone,
    },
    {
      label: 'Whisper',
      value: installedWhisper.length ? `${installedWhisper.length} installed` : 'None installed',
      detail: `Selected: ${whisperPayload.selected_model_size ?? 'unknown'}`,
      tone: installedWhisper.length ? 'success' : 'warning',
    },
    {
      label: 'Runtime',
      value: runtimeState.value,
      detail: llmPayload.llama_server_path ?? 'No runtime path reported',
      tone: runtimeState.tone,
    },
  ];

  for (const stat of stats) {
    const card = document.createElement('div');
    card.className = 'model-stat';

    const label = document.createElement('span');
    label.textContent = stat.label;

    const value = document.createElement('strong');
    value.textContent = stat.value;
    value.dataset.tone = stat.tone;

    const detail = document.createElement('small');
    detail.textContent = stat.detail;

    card.append(label, value, detail);
    modelStatusSummaryEl.append(card);
  }
}

// Renders the models-page "Voice Cloning" card from the /tts/voices `cloning`
// availability payload ({ available, reason, setup_hint, mechanism }). This
// replaces surfacing the raw "run tools/setup_voice_cloning.py" hint to end
// users — that CLI can't work in a packaged app. When unavailable, the Install
// button triggers in-app provisioning (POST /tts/clone/provision), which
// reports honestly (incl. "not published yet") rather than failing silently.
function renderVoiceCloningPanel(cloning) {
  if (!voiceCloningBadgeEl || !provisionVoiceCloningButton) return;
  const info = cloning && typeof cloning === 'object' ? cloning : {};
  if (info.available) {
    voiceCloningBadgeEl.textContent = 'Installed';
    voiceCloningBadgeEl.className = 'model-badge model-badge-ready';
    if (voiceCloningStatusEl) {
      voiceCloningStatusEl.textContent =
        'Voice cloning is ready. Upload a short sample in TTS / Read-Aloud to clone a voice.';
    }
    provisionVoiceCloningButton.hidden = true;
    if (voiceCloningHintEl) voiceCloningHintEl.hidden = true;
  } else {
    voiceCloningBadgeEl.textContent = 'Not installed';
    voiceCloningBadgeEl.className = 'model-badge';
    if (voiceCloningStatusEl) {
      voiceCloningStatusEl.textContent =
        'Optional add-on. Clone your own voice from a short sample (~1.5 GB download).';
    }
    provisionVoiceCloningButton.hidden = false;
    // Show the backend's actionable reason as a small hint, but never the raw
    // "run <script>" CLI instruction — the Install button is the user path.
    if (voiceCloningHintEl) {
      // Only surface an UNUSUAL reason. The normal not-installed states
      // ("dependencies not installed…", the "run <script>" CLI hint) are jargon
      // already covered by the friendly status text above — hide them.
      const reason = String(info.reason || '').trim();
      const isRoutine = !reason || /setup_voice_cloning|dependencies not installed/i.test(reason);
      voiceCloningHintEl.textContent = isRoutine ? '' : reason;
      voiceCloningHintEl.hidden = isRoutine;
    }
  }
}

// The one and only provisioning path (POST /tts/clone/provision) — both the
// Models tab's "Install voice cloning" button and the TTS/Read-Aloud
// section's clone-status affordance call this instead of each doing their
// own POST, so there is never a second implementation to keep in sync.
async function installVoiceCloning() {
  return runModelAction(provisionVoiceCloningButton, 'Install voice cloning', async () => {
    const result = await provisionVoiceCloning();
    renderVoiceCloningPanel(result?.cloning);
    return result;
  });
}

function renderModelPanels() {
  const llmPayload = llmModelsPayload;
  const whisperPayload = whisperModelsPayload;
  if (!llmPayload || !whisperPayload) {
    return;
  }

  const llmSelected = (llmPayload.models ?? []).find((model) => model.id === llmPayload.selected_model_id);
  const llmVisible = (llmPayload.models ?? []).find((model) => model.id === llmModelSelectEl?.value) || llmSelected;
  const installedWhisper = (whisperPayload.models ?? []).filter((model) => model.installed).map((model) => model.model_size);
  const visibleWhisperSize = whisperModelSelectEl?.value || whisperPayload.selected_model_size;
  const visibleWhisper = (whisperPayload.models ?? []).find((model) => model.model_size === visibleWhisperSize);
  const estimateMb = Number(llmVisible?.size_mb || 0);

  setModelBadge(llmModelBadgeEl, Boolean(llmVisible?.installed), llmVisible?.id === llmPayload.selected_model_id);
  setModelBadge(whisperModelBadgeEl, Boolean(visibleWhisper?.installed), visibleWhisperSize === whisperPayload.selected_model_size);
  renderModelOverview(llmPayload, whisperPayload, llmSelected, installedWhisper);
  renderModelDetailGrid(llmModelDetailsEl, [
    { label: 'Selected model', value: llmPayload.selected_model_id },
    { label: 'Viewing', value: llmVisible?.name ?? llmVisible?.id ?? 'unknown' },
    { label: 'Install state', value: llmVisible?.installed ? 'installed' : 'missing', tone: llmVisible?.installed ? 'success' : 'danger' },
    { label: 'Approx size', value: estimateMb ? `${estimateMb.toLocaleString()} MB` : 'unknown' },
    { label: 'Runtime', value: llmPayload.llama_server_exists ? 'found' : 'missing', tone: llmPayload.llama_server_exists ? 'success' : 'danger' },
  ]);
  renderLlmDownloadProgress(llmPayload.download_state, llmVisible);
  renderModelDetailGrid(whisperModelDetailsEl, [
    { label: 'Selected model', value: whisperPayload.selected_model_size },
    { label: 'Viewing', value: visibleWhisperSize },
    { label: 'Install state', value: visibleWhisper?.installed ? 'installed' : 'missing', tone: visibleWhisper?.installed ? 'success' : 'warning' },
    { label: 'Installed models', value: installedWhisper.length ? installedWhisper.join(', ') : 'none' },
    { label: 'Download state', value: whisperPayload.download_state?.status ?? 'unknown' },
  ]);
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

// Transient toast notifications — the app-wide way to surface events/errors that
// would otherwise only reach the console.
function showToast(message, tone = 'info', durationMs = 5000) {
  const container = document.getElementById('toastContainer');
  if (!container || !message) {
    return;
  }

  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.dataset.tone = tone;

  const text = document.createElement('div');
  text.className = 'toast-message';
  text.textContent = String(message);

  const close = document.createElement('button');
  close.className = 'toast-close';
  close.type = 'button';
  close.setAttribute('aria-label', 'Dismiss notification');
  close.textContent = '×';

  let removeTimer = null;
  const dismiss = () => {
    if (removeTimer) {
      clearTimeout(removeTimer);
      removeTimer = null;
    }
    toast.classList.add('leaving');
    toast.addEventListener('animationend', () => toast.remove(), { once: true });
    // Fallback in case the animation doesn't fire.
    setTimeout(() => toast.remove(), 250);
  };

  close.addEventListener('click', dismiss);
  toast.append(text, close);
  container.append(toast);

  if (durationMs > 0) {
    removeTimer = setTimeout(dismiss, durationMs);
  }
  return toast;
}

// --- First-run onboarding (policy -> tour -> models) ---

const ONBOARDING_FLAG = 'bf_onboarding_complete';

const onboardingSteps = [
  {
    title: 'Welcome to BetterFingers',
    body: () => `
      <p>BetterFingers turns your voice into text anywhere on your system — fully
      local, no cloud. This quick setup takes about a minute.</p>
      <h3>What you'll do</h3>
      <ul>
        <li>Review how BetterFingers uses your data</li>
        <li>Learn the record → review → send flow</li>
        <li>Make sure a speech model is installed</li>
      </ul>`,
    nextLabel: 'Get started',
  },
  {
    title: 'Your data stays on this device',
    body: () => `
      <div class="policy-box">
        <p>BetterFingers runs a local speech-to-text, rewrite, and text-to-speech
        pipeline on your own machine. Audio you record is transcribed locally and is
        not sent to any external server.</p>
        <p>The only network activity is downloading the AI models you choose to
        install. You can delete recordings, drafts, and models at any time from the
        app.</p>
        <p>By continuing you confirm you will use BetterFingers lawfully and only to
        capture speech you are authorized to capture.</p>
      </div>
      <label class="consent">
        <input type="checkbox" id="onboardingConsent" />
        <span>I understand and accept how BetterFingers handles my data.</span>
      </label>`,
    nextLabel: 'Accept & continue',
    onEnter: () => {
      const consent = document.getElementById('onboardingConsent');
      consent?.addEventListener('change', updateOnboardingNextState);
    },
    canProceed: () => Boolean(document.getElementById('onboardingConsent')?.checked),
  },
  {
    title: 'How it works',
    body: () => `
      <ul>
        <li><strong>Record</strong> — press your record hotkey (or use the tray) and speak.
        Hold-to-talk and press-to-toggle are both supported.</li>
        <li><strong>Review</strong> — a draft appears with the cleaned-up text. Rewrite it
        (Clearer / Shorter / Tone), edit inline, or have it read back to you.</li>
        <li><strong>Send</strong> — accept to type or paste it into whatever app you're in.</li>
      </ul>
      <p>You can change hotkeys, injection behavior, and more under <strong>Settings</strong>.</p>`,
    nextLabel: 'Next',
  },
  {
    title: 'Speech models',
    body: () => {
      const hasWhisper = Array.isArray(whisperModelsPayload?.models)
        && whisperModelsPayload.models.some((m) => m.downloaded || m.installed);
      const intro = hasWhisper
        ? `<p>A speech model is installed — you're ready to go. You can manage or add
          models any time from the <strong>Models</strong> tab.</p>`
        : `<p>No speech model is installed yet. Open the <strong>Models</strong> tab to
          download the recommended set for your hardware (a small Whisper model for
          transcription, plus an optional local LLM for cleanup).</p>
          <p>You can finish setup now and download models whenever you're ready.</p>`;
      // Filled in asynchronously by onEnter with the hardware-aware recommendation.
      return `${intro}<div id="onboardingRecommendation" class="policy-box" hidden></div>`;
    },
    onEnter: () => { populateOnboardingRecommendation(); },
    nextLabel: 'Finish',
  },
];

// Surface the U4 hardware-aware recommendation (tier + recommended LLM/Whisper)
// inside the onboarding "Speech models" step. Non-fatal on any failure.
async function populateOnboardingRecommendation() {
  const box = document.getElementById('onboardingRecommendation');
  if (!box) return;
  try {
    const payload = await fetchModelRecommendation();
    // The user may have left this onboarding step (or the app) while the
    // request was in flight — don't populate a box that's no longer shown.
    if (!box.isConnected) return;
    const rec = payload?.recommendation;
    if (!rec) return;
    const llm = rec.llm?.models?.find((m) => m.id === rec.llm.recommended);
    const whisper = rec.whisper?.recommended;
    const llmNote = llm?.note ? ` — ${escapeHtml(llm.note)}` : '';
    box.innerHTML =
      `<strong>Recommended for your hardware (${escapeHtml(rec.tier_label ?? rec.tier)})</strong>` +
      (rec.tier_guidance ? `<p class="section-desc">${escapeHtml(rec.tier_guidance)}</p>` : '') +
      `<ul><li><strong>Language model:</strong> ${escapeHtml(llm?.name ?? rec.llm?.recommended ?? '—')}${llmNote}</li>` +
      `<li><strong>Speech model:</strong> ${escapeHtml(whisper ?? '—')}</li></ul>`;
    box.hidden = false;
  } catch (error) {
    // Recommendation is a nice-to-have; leave the box hidden if it can't load.
  }
}

let onboardingIndex = 0;

function updateOnboardingNextState() {
  const nextButton = document.getElementById('onboardingNextButton');
  if (!nextButton) return;
  const step = onboardingSteps[onboardingIndex];
  nextButton.disabled = typeof step.canProceed === 'function' ? !step.canProceed() : false;
}

function renderOnboardingStep() {
  const overlay = document.getElementById('onboardingOverlay');
  const titleEl = document.getElementById('onboardingTitle');
  const bodyEl = document.getElementById('onboardingBody');
  const progressEl = document.getElementById('onboardingProgress');
  const backButton = document.getElementById('onboardingBackButton');
  const nextButton = document.getElementById('onboardingNextButton');
  if (!overlay || !titleEl || !bodyEl) return;

  const step = onboardingSteps[onboardingIndex];
  titleEl.textContent = step.title;
  bodyEl.innerHTML = typeof step.body === 'function' ? step.body() : String(step.body || '');

  if (progressEl) {
    progressEl.innerHTML = '';
    onboardingSteps.forEach((_, i) => {
      const dot = document.createElement('div');
      dot.className = 'step-dot' + (i === onboardingIndex ? ' active' : i < onboardingIndex ? ' done' : '');
      progressEl.append(dot);
    });
  }

  if (backButton) backButton.style.visibility = onboardingIndex === 0 ? 'hidden' : 'visible';
  if (nextButton) nextButton.textContent = step.nextLabel || 'Next';

  if (typeof step.onEnter === 'function') step.onEnter();
  updateOnboardingNextState();
  nextButton?.focus();
}

function finishOnboarding() {
  try {
    localStorage.setItem(ONBOARDING_FLAG, 'true');
  } catch (error) {
    // Non-fatal; onboarding may show again next launch.
  }
  const overlay = document.getElementById('onboardingOverlay');
  overlay?.classList.add('hidden');
  document.removeEventListener('keydown', onboardingKeydownTrap, true);
}

function onboardingKeydownTrap(event) {
  const overlay = document.getElementById('onboardingOverlay');
  if (!overlay || overlay.classList.contains('hidden')) return;
  // Block Escape (this is a required first-run gate) and keep Tab focus inside.
  if (event.key === 'Escape') {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  if (event.key !== 'Tab') return;
  const focusable = overlay.querySelectorAll('button:not([disabled]), input, a[href]');
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function initOnboarding() {
  let complete = false;
  try {
    complete = localStorage.getItem(ONBOARDING_FLAG) === 'true';
  } catch (error) {
    complete = false;
  }
  const overlay = document.getElementById('onboardingOverlay');
  if (!overlay || complete) return;

  const backButton = document.getElementById('onboardingBackButton');
  const nextButton = document.getElementById('onboardingNextButton');
  const declineButton = document.getElementById('onboardingDeclineButton');

  nextButton?.addEventListener('click', () => {
    const step = onboardingSteps[onboardingIndex];
    if (typeof step.canProceed === 'function' && !step.canProceed()) return;
    if (onboardingIndex >= onboardingSteps.length - 1) {
      finishOnboarding();
      return;
    }
    onboardingIndex += 1;
    renderOnboardingStep();
  });

  backButton?.addEventListener('click', () => {
    if (onboardingIndex > 0) {
      onboardingIndex -= 1;
      renderOnboardingStep();
    }
  });

  declineButton?.addEventListener('click', () => {
    window.betterFingers?.quitApp?.();
  });

  document.addEventListener('keydown', onboardingKeydownTrap, true);
  overlay.classList.remove('hidden');
  onboardingIndex = 0;
  renderOnboardingStep();
}

function formatSendActionLabel(action = '') {
  const labels = {
    profile_default: 'Profile default',
    copy_only: 'Copy only',
    paste: 'Paste',
    type: 'Type',
    open_chat_then_send: 'Open chat then send',
  };
  return labels[action] || String(action || 'unknown').replaceAll('_', ' ');
}

function selectDefaultSendAction() {
  if (!outputSettings) {
    return 'copy_only';
  }

  if (!outputSettings?.capabilities?.supports_input_injection) {
    return 'copy_only';
  }

  return outputSettings.send_mode === 'auto_send' ? 'open_chat_then_send' : 'paste';
}

function getSelectedSendAction() {
  const selected = sendActionSelectEl?.value || 'profile_default';
  if (selected === 'profile_default') {
    return selectDefaultSendAction();
  }
  return selected;
}

function renderSendResult(sendResult) {
  if (!sendResultPanelEl) {
    return;
  }

  if (!sendResult) {
    sendResultPanelEl.classList.add('hidden');
    sendResultPanelEl.innerHTML = '';
    return;
  }

  const requested = sendResult.requested_action || sendResult.action || 'unknown';
  const actual = sendResult.actual_action || sendResult.action || 'unknown';
  const fallback = Boolean(sendResult.fallback);
  const rows = [
    ['Requested', formatSendActionLabel(requested)],
    ['Used', formatSendActionLabel(actual)],
    ['Fallback', fallback ? (sendResult.fallback_reason || 'yes') : 'no'],
    ['Platform', [sendResult.platform, sendResult.session_type].filter(Boolean).join(' · ') || 'unknown'],
  ];

  sendResultPanelEl.classList.remove('hidden');
  sendResultPanelEl.dataset.tone = sendResult.ok ? (fallback ? 'warning' : 'success') : 'danger';
  sendResultPanelEl.innerHTML = '';

  const title = document.createElement('strong');
  title.textContent = sendResult.message || 'Send result';
  sendResultPanelEl.append(title);

  const grid = document.createElement('div');
  grid.className = 'send-result-grid';
  for (const [labelText, valueText] of rows) {
    const label = document.createElement('span');
    label.textContent = labelText;
    const value = document.createElement('b');
    value.textContent = valueText;
    grid.append(label, value);
  }
  sendResultPanelEl.append(grid);
}

function sendOverlayUpdate(message) {
  if (!window.betterFingers?.updateOverlayStatus) {
    return;
  }

  if (typeof message === 'string') {
    window.betterFingers.updateOverlayStatus(message);
    return;
  }

  const status = message?.status || 'unknown';
  const sendResult = message?.send_result;
  const overlayPayload = {
    status,
    message: message?.message || sendResult?.message || message?.error || '',
    fallback: Boolean(sendResult?.fallback),
  };

  if (status === 'preview_ready') {
    overlayPayload.message = 'Draft ready';
  } else if (status === 'draft_sent' && sendResult?.fallback) {
    overlayPayload.message = 'Copied as fallback';
  } else if (status === 'draft_sent') {
    overlayPayload.message = 'Sent';
  } else if (status === 'draft_send_error') {
    overlayPayload.message = sendResult?.message || 'Send failed';
  } else if (status === 'draft_blocked') {
    overlayPayload.message = message?.error || 'No usable audio';
  } else if (status === 'draft_error') {
    overlayPayload.message = message?.error || 'Draft failed';
  } else if (status === 'long_recording_detected') {
    overlayPayload.message = 'Long recording…';
  } else if (status === 'chunking_started') {
    overlayPayload.message = message?.chunk_count ? `Processing ${message.chunk_count} chunks` : 'Processing…';
  } else if (status === 'chunking_progress') {
    overlayPayload.message = `Chunk ${message?.chunk_index} of ${message?.chunk_count}`;
  } else if (status === 'chunking_stitching') {
    overlayPayload.message = 'Smoothing…';
  } else if (status === 'selection_capture_failed') {
    overlayPayload.message = message?.message || 'Selection unavailable';
  } else if (status === 'emergency_stop') {
    overlayPayload.message = message?.message || 'Stopped';
  }

  window.betterFingers.updateOverlayStatus(overlayPayload);
}

function showReviewOverlayDraft(draft) {
  if (!draft?.id || !window.betterFingers?.showReviewOverlay) {
    return;
  }
  window.betterFingers.showReviewOverlay(draft);
}

function hideReviewOverlay() {
  window.betterFingers?.hideReviewOverlay?.();
}

async function refreshOutputSettings() {
  outputSettings = await fetchOutputSettings();
  if (outputSettingsSummaryEl) {
    const supportsInput = outputSettings?.capabilities?.supports_input_injection ? 'input injection available' : 'copy fallback';
    const pendingCount = Array.isArray(outputSettings?.pending_manual_send_ids) ? outputSettings.pending_manual_send_ids.length : 0;
    outputSettingsSummaryEl.textContent = `send mode ${outputSettings?.send_mode ?? 'unknown'} · auto-submit ${formatValue(outputSettings?.auto_submit)} · ${supportsInput} · pending sends ${pendingCount}`;
  }
  if (sendActionSelectEl && sendActionSelectEl.value === 'profile_default') {
    sendActionSelectEl.title = `Profile default currently resolves to ${formatSendActionLabel(selectDefaultSendAction())}.`;
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

  // Clear all validation errors
  for (const key of Object.keys(settingEls)) {
    clearValidationError(key);
  }

  for (const [key, el] of Object.entries(settingEls)) {
    if (!el) {
      continue;
    }
    if (el.type === 'checkbox') {
      // Some toggles default ON when the profile hasn't stored them yet.
      const defaultOnKeys = new Set(['voice_commands_enabled', 'macros_enabled', 'confidence_force_review_enabled', 'restore_clipboard_after_paste']);
      const stored = activeProfileSettings[key];
      const value = stored === undefined && defaultOnKeys.has(key) ? true : Boolean(stored);
      el.checked = el.disabled ? false : value;
    } else {
      el.value = activeProfileSettings[key] ?? '';
    }
  }

  // Blend/modulation aren't in settingEls (they're a dynamic list + sliders
  // owned by voiceStudio), so they need their own restore pass — see the
  // module header comment for why this closes the "resets on reload" bug.
  voiceStudio.restoreFromProfile(activeProfileSettings, document);

  // Hide the save bar
  const saveBar = document.getElementById('settingsSaveBar');
  if (saveBar) {
    saveBar.classList.remove('visible');
    setTimeout(() => {
      if (!profileDirty) saveBar.classList.add('hidden');
    }, 300);
  }
}

function markProfileDirty() {
  profileDirty = true;
  setMessage(profileMessageEl, 'Unsaved profile changes.', 'warning');
  
  const saveBar = document.getElementById('settingsSaveBar');
  if (saveBar) {
    saveBar.classList.remove('hidden');
    requestAnimationFrame(() => {
      saveBar.classList.add('visible');
    });
  }
}

function collectProfileSettings() {
  const next = { ...(activeProfileSettings ?? {}) };
  for (const [key, el] of Object.entries(settingEls)) {
    if (!el) {
      continue;
    }
    if (el.type === 'checkbox') {
      next[key] = el.disabled ? false : Boolean(el.checked);
    } else if (el.type === 'number') {
      next[key] = Number(el.value);
    } else {
      next[key] = el.value;
    }
  }
  // Blend/modulation: same profile boundary as everything above, just not
  // owned by a single settingEls input (see voiceStudio.js header comment).
  Object.assign(next, voiceStudio.getPersistableState(document));
  return next;
}

async function refreshAudioInputDevices() {
  const select = settingEls.input_device_index;
  if (!select) return;
  let info;
  try {
    info = await fetchJson('/runtime/audio-devices');
  } catch (error) {
    console.error('Failed to load audio input devices:', error);
    return;
  }
  const devices = info && Array.isArray(info.devices) ? info.devices : [];
  select.innerHTML = '';
  const defaultOption = document.createElement('option');
  defaultOption.value = '-1';
  defaultOption.textContent = 'System default';
  select.appendChild(defaultOption);
  for (const dev of devices) {
    if (!dev || Number(dev.max_input_channels) <= 0) continue; // input-capable only
    const option = document.createElement('option');
    option.value = String(dev.index);
    option.textContent = dev.name || `Device ${dev.index}`;
    select.appendChild(option);
  }
  // Reflect the stored selection; fall back to System default if that device is
  // no longer present. Setting .value programmatically does not fire change, so
  // this never marks the profile dirty.
  const stored = activeProfileSettings && activeProfileSettings.input_device_index != null
    ? String(activeProfileSettings.input_device_index)
    : '-1';
  select.value = select.querySelector(`option[value="${CSS.escape(stored)}"]`) ? stored : '-1';
}

async function refreshPersonasAndVoices() {
  try {
    const personas = await fetchPersonas();
    loadedPersonas = personas ?? {};
    const presetSelect = settingEls.current_preset;
    if (presetSelect) {
      const currentSelected = presetSelect.value;
      presetSelect.innerHTML = '';
      for (const name of Object.keys(loadedPersonas)) {
        const option = document.createElement('option');
        option.value = name;
        option.textContent = name;
        presetSelect.appendChild(option);
      }
      if (currentSelected && loadedPersonas[currentSelected]) {
        presetSelect.value = currentSelected;
      }
    }
  } catch (error) {
    console.error('Failed to load personas:', error);
  }

  await voiceStudio.refreshVoices(document).catch((error) => console.error('Failed to load TTS voices/presets:', error));
}

async function refreshProfiles() {
  await refreshPersonasAndVoices().catch(() => {});
  const payload = await fetchProfiles();
  fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
  renderProfileSettings(payload.settings ?? {});
  await refreshAudioInputDevices().catch(() => {});
  setMessage(profileMessageEl, `Active profile: ${payload.active_profile}`, 'success');
  if (payload.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
    window.betterFingers.updateHotkeys(payload.settings);
  }
  return payload;
}

async function renderModelRecommendation() {
  const el = document.getElementById('modelRecommendation');
  if (!el) return;
  try {
    const payload = await fetchModelRecommendation();
    const rec = payload?.recommendation;
    if (!rec) {
      el.classList.add('hidden');
      return;
    }
    const llm = rec.llm?.models?.find((m) => m.id === rec.llm.recommended);
    const whisper = rec.whisper?.recommended;
    const llmNote = llm?.note ? ` — ${escapeHtml(llm.note)}` : '';
    el.innerHTML =
      `<strong>Recommended for your hardware (${escapeHtml(rec.tier_label ?? rec.tier)})</strong>` +
      (rec.tier_guidance ? `<p class="section-desc">${escapeHtml(rec.tier_guidance)}</p>` : '') +
      `<ul><li><strong>Language model:</strong> ${escapeHtml(llm?.name ?? rec.llm?.recommended ?? '—')}${llmNote}</li>` +
      `<li><strong>Speech model:</strong> ${escapeHtml(whisper ?? '—')}</li></ul>`;
    el.classList.remove('hidden');
  } catch (error) {
    el.classList.add('hidden');
  }
}

async function refreshModels() {
  const [llmPayload, whisperPayload] = await Promise.all([
    fetchLlmModels(),
    fetchWhisperModels(),
  ]);
  llmModelsPayload = llmPayload;
  whisperModelsPayload = whisperPayload;
  renderModelRecommendation().catch(() => {});

  fillSelect(
    llmModelSelectEl,
    (llmPayload.models ?? []).map((model) => ({ value: model.id, label: `${model.name} ${model.installed ? '(installed)' : ''}` })),
    llmPayload.selected_model_id,
    (item) => item.label,
  );
  fillSelect(whisperModelSelectEl, whisperPayload.supported ?? [], whisperPayload.selected_model_size);

  renderModelPanels();
  // Wake engine backbones live in this tab too now — keep them in sync with
  // every Models refresh (non-blocking; its own error handling renders inline).
  refreshWakeModels().catch(() => {});
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

async function runLlmDownloadAction() {
  const modelId = llmModelSelectEl?.value;
  if (!modelId || !downloadLlmModelButton) {
    return;
  }

  const previous = downloadLlmModelButton.textContent;
  const visibleModel = (llmModelsPayload?.models ?? []).find((model) => model.id === modelId);
  let stopped = false;
  downloadLlmModelButton.disabled = true;
  downloadLlmModelButton.textContent = 'Downloading...';
  renderLlmDownloadProgress({ status: 'starting', percent: 0, message: `Starting ${visibleModel?.name ?? modelId} download.` }, visibleModel);

  const poll = async () => {
    if (stopped) {
      return;
    }
    try {
      const state = await fetchLlmDownloadState(modelId);
      renderLlmDownloadProgress(state, visibleModel);
    } catch (_error) {
      // The main download request is the source of truth; progress polling is best-effort.
    }
  };

  const pollTimer = window.setInterval(poll, 900);
  try {
    await poll();
    const result = await downloadLlmModel(modelId);
    stopped = true;
    window.clearInterval(pollTimer);
    renderLlmDownloadProgress({ status: result?.ok === false ? 'error' : 'ready', percent: result?.ok === false ? 0 : 100, message: result?.message || 'Download complete.' }, visibleModel);
    setMessage(modelMessageEl, result?.message || 'LLM download completed.', result?.ok === false ? 'danger' : 'success');
    await Promise.all([refreshModels(), refreshRuntime()]);
  } catch (error) {
    stopped = true;
    window.clearInterval(pollTimer);
    renderLlmDownloadProgress({ status: 'error', percent: 0, message: `Download failed: ${error.message}` }, visibleModel);
    setMessage(modelMessageEl, `Download LLM failed: ${error.message}`, 'danger');
  } finally {
    stopped = true;
    window.clearInterval(pollTimer);
    downloadLlmModelButton.textContent = previous;
    downloadLlmModelButton.disabled = false;
  }
}

async function refreshCapabilities() {
  const capabilities = await fetchCapabilities();

  // Update Hotkeys session indicator element
  const hotkeySessionIndicator = document.getElementById('hotkeySessionIndicator');
  if (hotkeySessionIndicator) {
    const platform = capabilities.platform ?? 'unknown';
    const session = capabilities.session_type ?? 'unknown';
    hotkeySessionIndicator.textContent = `${platform} (${session})`;
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
    'injection_method',
    'supports_typing',
    'supports_global_hotkeys',
    'supports_audio_ducking',
    'supports_stt',
    'supports_llm',
    'supports_tts',
  ]);
  updatePlatformWarnings(capabilities);
  return capabilities;
}

// Reflect whether push-to-talk is actually available on this platform/session,
// based on the Electron hotkey backend (uiohook vs globalShortcut fallback).
async function refreshPttAvailability() {
  const note = document.getElementById('pttAvailabilityNote');
  if (!note || !window.betterFingers?.getHotkeyCapabilities) {
    return;
  }
  try {
    const caps = await window.betterFingers.getHotkeyCapabilities();
    if (caps?.pttSupported) {
      note.textContent = 'Push-to-talk is available on this system.';
      note.dataset.tone = 'success';
    } else {
      note.textContent =
        'Push-to-talk needs a global key hook that is unavailable here (e.g. Wayland); it will fall back to toggle.';
      note.dataset.tone = 'warning';
    }
  } catch (error) {
    note.textContent = '';
  }
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

function renderMetricsHud(summary) {
  const el = document.getElementById('metricsHud');
  if (!el) return;
  if (!summary || !summary.count) {
    el.innerHTML = '<p class="empty-state">No utterances measured yet.</p>';
    return;
  }
  const fmt = (v) => (v === null || v === undefined ? '—' : `${v} ms`);
  const row = (label, stage) =>
    `<tr><th scope="row">${label}</th><td>${fmt(stage?.last_ms)}</td><td>${fmt(stage?.avg_ms)}</td>` +
    `<td>${fmt(stage?.p50_ms)}</td><td>${fmt(stage?.p95_ms)}</td></tr>`;
  el.innerHTML =
    `<table class="metrics-table"><thead><tr><th scope="col">Stage</th><th scope="col">Last</th>` +
    `<th scope="col">Avg</th><th scope="col">p50</th><th scope="col">p95</th></tr></thead><tbody>` +
    row('Transcribe', summary.stt) +
    row('Dictionary/commands/macros', summary.post) +
    row('LLM cleanup', summary.llm) +
    row('Total', summary.total) +
    `</tbody></table><p class="section-desc">Over the last ${summary.count} utterance(s).</p>`;
}

async function refreshPrivacy() {
  const netEl = document.getElementById('privacyNetworkList');
  const dataEl = document.getElementById('privacyDataList');
  if (!netEl && !dataEl) return;
  try {
    const report = await fetchPrivacy();
    if (netEl) {
      netEl.innerHTML = (report.network_touchpoints || [])
        .map((t) => {
          const tag = t.direction === 'outbound' ? 'outbound' : 'on-device';
          const hosts = (t.hosts || []).length ? ` (${t.hosts.join(', ')})` : '';
          return `<div class="detail-row"><span class="detail-key">${t.name} — ${tag}${hosts}</span>` +
            `<span class="detail-value">${t.purpose}</span></div>`;
        })
        .join('') || '<span class="empty-state">No network activity.</span>';
    }
    if (dataEl) {
      dataEl.innerHTML = (report.data_locations || [])
        .map((d) => `<div class="detail-row"><span class="detail-key">${d.name}</span>` +
          `<span class="detail-value">${formatBytes(d.bytes)} · ${d.path}</span></div>`)
        .join('');
    }
    const wakeEl = document.getElementById('privacyWakeListenerStatus');
    if (wakeEl) {
      const wake = report.wake_listener;
      if (wake) {
        const state = wake.active ? 'Active — listening for the wake phrase.' : 'Not active.';
        wakeEl.textContent = `${state} ${wake.note || ''}`.trim();
      } else {
        wakeEl.textContent = 'Not reported by the backend.';
      }
    }
  } catch (error) {
    if (netEl) netEl.innerHTML = `<span class="empty-state">Privacy report unavailable: ${escapeHtml(error.message)}</span>`;
  }
}

async function handleWipeData() {
  const button = document.getElementById('privacyWipeButton');
  const wipeVoices = document.getElementById('privacyWipeVoices')?.checked || false;
  const confirmed = window.confirm(
    'Permanently delete your drafts, transcription history, and in-memory recordings' +
      (wipeVoices ? ', plus your cloned voices' : '') +
      '? This cannot be undone.',
  );
  if (!confirmed) return;
  const messageEl = document.getElementById('privacyMessage');
  if (button) button.disabled = true;
  try {
    const result = await wipeData(wipeVoices, undefined, { confirmed: true });
    // Phase 1.2: defense in depth. Even on HTTP 200, never claim success
    // unless the backend proved every postcondition held. A failed wipe now
    // returns a non-2xx status (see server.py _wipe_status_code) and lands in
    // the catch below, but a 200-with-ok:false must never slip through here.
    if (!result?.ok) {
      const summary = summarizeWipeFailure(result);
      throw new Error(
        `${result?.message || 'The privacy wipe did not complete.'} ${summary}`.trim(),
      );
    }
    const cleared = result.cleared || {};
    showToast(`Data wiped (${cleared.drafts ?? 0} drafts cleared).`, 'success');
    setMessage(messageEl, 'Your data was wiped.', 'success');
    await refreshPrivacy();
    await refreshDrafts().catch(() => {});
  } catch (error) {
    // Failure arrives either as a thrown non-2xx (error.body carries the wipe
    // payload) or the defensive throw above (message already summarized).
    // Surface the truthful detail: what remained and whether retry is safe.
    const payload = error?.body;
    const base = error?.message || 'The privacy wipe did not complete.';
    const detail = payload ? summarizeWipeFailure(payload) : '';
    showToast(`Wipe failed: ${base}`, 'danger');
    setMessage(messageEl, detail ? `${base} ${detail}` : base, 'danger');
    await refreshPrivacy().catch(() => {});
  } finally {
    if (button) button.disabled = false;
  }
}

// --- Personal dictionary (C1) ---

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]),
  );
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function renderDictionaryTerms(terms) {
  const el = document.getElementById('dictionaryList');
  if (!el) return;
  if (!terms || !terms.length) {
    el.innerHTML = '<span class="empty-state">No terms yet.</span>';
    return;
  }
  el.innerHTML = terms
    .map(
      (t) =>
        `<span class="dictionary-chip">${escapeHtml(t)}` +
        `<button class="dictionary-chip-remove" type="button" data-term="${escapeAttr(t)}" aria-label="Remove ${escapeAttr(t)}">×</button></span>`,
    )
    .join('');
}

// --- Voice macros (C11) ---

function renderMacros(macrosList) {
  const el = document.getElementById('macrosList');
  if (!el) return;
  if (!macrosList || !macrosList.length) {
    el.innerHTML = '<span class="empty-state">No macros yet.</span>';
    return;
  }
  el.innerHTML = macrosList
    .map(
      (m) =>
        `<div class="macro-row"><span class="macro-pair"><strong>${escapeHtml(m.trigger)}</strong> → ${escapeHtml(m.expansion)}</span>` +
        `<button class="dictionary-chip-remove macro-remove" type="button" data-trigger="${escapeAttr(m.trigger)}" aria-label="Remove ${escapeAttr(m.trigger)}">×</button></div>`,
    )
    .join('');
}

async function refreshMacros() {
  const el = document.getElementById('macrosList');
  if (!el) return;
  try {
    const payload = await fetchMacros();
    renderMacros(payload?.macros || []);
  } catch (error) {
    el.innerHTML = `<span class="empty-state">Macros unavailable: ${escapeHtml(error.message)}</span>`;
  }
}

async function handleAddMacro() {
  const trigger = document.getElementById('macroTrigger')?.value?.trim();
  const expansion = document.getElementById('macroExpansion')?.value?.trim();
  if (!trigger || !expansion) {
    showToast('A macro needs both a trigger and an expansion.', 'warning');
    return;
  }
  try {
    const payload = await addMacro(trigger, expansion);
    renderMacros(payload?.macros || []);
    document.getElementById('macroTrigger').value = '';
    document.getElementById('macroExpansion').value = '';
  } catch (error) {
    showToast(`Could not add macro: ${error.message}`, 'danger');
  }
}

async function handleRemoveMacro(trigger) {
  try {
    const payload = await deleteMacro(trigger);
    renderMacros(payload?.macros || []);
  } catch (error) {
    showToast(`Could not remove macro: ${error.message}`, 'danger');
  }
}

async function refreshDictionary() {
  const el = document.getElementById('dictionaryList');
  if (!el) return;
  try {
    const payload = await fetchDictionary();
    renderDictionaryTerms(payload?.terms || []);
  } catch (error) {
    el.innerHTML = `<span class="empty-state">Dictionary unavailable: ${escapeHtml(error.message)}</span>`;
  }
}

async function handleAddDictionaryTerm(term) {
  const value = String(term || '').trim();
  if (!value) return;
  try {
    const payload = await addDictionaryTerm(value);
    renderDictionaryTerms(payload?.terms || []);
    const input = document.getElementById('dictionaryInput');
    if (input) input.value = '';
    // Drop it from the suggestions row if it was there.
    document.querySelector(`#dictionarySuggestions [data-term="${CSS.escape(value)}"]`)?.closest('.dictionary-chip')?.remove();
  } catch (error) {
    showToast(`Could not add term: ${error.message}`, 'danger');
  }
}

async function handleRemoveDictionaryTerm(term) {
  try {
    const payload = await deleteDictionaryTerm(term);
    renderDictionaryTerms(payload?.terms || []);
  } catch (error) {
    showToast(`Could not remove term: ${error.message}`, 'danger');
  }
}

function renderDictionarySuggestions(suggestions) {
  const group = document.getElementById('dictionarySuggestGroup');
  const el = document.getElementById('dictionarySuggestions');
  if (!group || !el) return;
  if (!suggestions || !suggestions.length) {
    group.hidden = true;
    el.innerHTML = '';
    return;
  }
  group.hidden = false;
  el.innerHTML = suggestions
    .map(
      (t) =>
        `<button class="dictionary-chip dictionary-chip-add" type="button" data-term="${escapeAttr(t)}">+ ${escapeHtml(t)}</button>`,
    )
    .join('');
}

// After a draft edit, quietly learn candidate terms from what the user changed.
async function maybeLearnFromEdit(rawText, editedText) {
  if (!rawText || !editedText) return;
  try {
    const payload = await suggestDictionaryTerms(rawText, editedText);
    const suggestions = payload?.suggestions || [];
    if (suggestions.length) {
      renderDictionarySuggestions(suggestions);
      showToast(
        `Dictionary suggestion${suggestions.length > 1 ? 's' : ''}: ${suggestions.slice(0, 3).join(', ')} — add in Settings → Dictionary.`,
        'info',
      );
    }
  } catch (error) {
    // Non-fatal: auto-learn is best-effort.
  }
}

async function refreshRecordings() {
  const el = document.getElementById('recordingsList');
  if (!el) return;
  try {
    const payload = await fetchRecordings();
    const items = payload?.recordings || [];
    if (!items.length) {
      el.innerHTML = '<p class="empty-state">No saved recordings.</p>';
      return;
    }
    el.innerHTML = items
      .map((r) => {
        const when = r.created_at ? new Date(r.created_at * 1000).toLocaleString() : '';
        const dur = r.duration_seconds ? `${r.duration_seconds}s` : '';
        const reason = r.stop_reason ? ` · ${r.stop_reason}` : '';
        return `<div class="recording-row" data-rec-id="${r.id}">` +
          `<span class="recording-meta">${when} · ${dur}${reason}</span>` +
          `<span class="recording-actions">` +
          `<button class="secondary-button recording-retry" type="button" data-rec-id="${r.id}">Re-transcribe</button>` +
          `<button class="secondary-button recording-discard" type="button" data-rec-id="${r.id}">Discard</button>` +
          `</span></div>`;
      })
      .join('');
  } catch (error) {
    el.innerHTML = `<p class="empty-state">Recordings unavailable: ${error.message}</p>`;
  }
}

const JOB_STATE_LABELS = {
  queued: 'Queued',
  loading: 'Loading',
  capturing: 'Capturing',
  transcribing: 'Transcribing',
  refining: 'Refining',
  stitching: 'Stitching',
  review_ready: 'Ready for review',
  injecting: 'Injecting',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
};

// Show only work that is still running; finished jobs are just noise here.
async function refreshJobs() {
  const el = document.getElementById('jobsList');
  if (!el) return;
  try {
    const payload = await fetchJobs(true);
    const items = payload?.jobs || [];
    if (!items.length) {
      el.innerHTML = '<p class="empty-state">No active jobs.</p>';
      return;
    }
    el.innerHTML = items
      .map((job) => {
        const stateLabel = JOB_STATE_LABELS[job.state] || job.state;
        const pct = typeof job.progress === 'number' ? ` · ${Math.round(job.progress * 100)}%` : '';
        const cancelling = job.cancel_requested ? ' · cancelling…' : '';
        return `<div class="job-row" data-job-id="${escapeHtml(job.id)}">` +
          `<span class="job-meta">${escapeHtml(job.label || job.kind)} — ${escapeHtml(stateLabel)}${pct}${cancelling}</span>` +
          `<button class="secondary-button job-cancel" type="button" data-job-id="${escapeHtml(job.id)}"${job.cancel_requested ? ' disabled' : ''}>Cancel</button>` +
          `</div>`;
      })
      .join('');
  } catch (error) {
    el.innerHTML = `<p class="empty-state">Jobs unavailable: ${escapeHtml(error.message)}</p>`;
  }
}

async function handleCancelJob(jobId) {
  try {
    await cancelJob(jobId);
    await refreshJobs();
  } catch (error) {
    showToast(`Cancel failed: ${error.message}`, 'danger');
  }
}

async function handleRetranscribeRecording(recId) {
  showToast('Re-transcribing…', 'info', 2500);
  try {
    await retranscribeRecording(recId);
    showToast('Re-transcribed — check the dashboard for the new draft.', 'success');
    await refreshDrafts().catch(() => {});
  } catch (error) {
    showToast(`Re-transcribe failed: ${error.message}`, 'danger');
  }
}

async function handleDiscardRecording(recId) {
  try {
    await deleteRecording(recId);
    await refreshRecordings();
  } catch (error) {
    showToast(`Discard failed: ${error.message}`, 'danger');
  }
}

async function refreshDiagnostics() {
  await Promise.all([
    refreshSidecarStatus().catch((error) => {
      if (sidecarStatusEl) {
        sidecarStatusEl.textContent = `Sidecar status failed: ${error.message}`;
        sidecarStatusEl.dataset.tone = 'danger';
      }
    }),
    fetchMetrics().then(renderMetricsHud).catch(() => {}),
    refreshRecordings().catch(() => {}),
    refreshJobs().catch(() => {}),
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

/* ==========================================
   Validation, Search, Warnings & Appearance
   ========================================== */

let validationErrors = new Map();

function validateProfileName(name) {
  const trimmed = name?.trim();
  if (!trimmed) {
    return 'Profile name cannot be empty.';
  }
  if (!/^[a-zA-Z0-9_\-]+$/.test(trimmed)) {
    return 'Profile name can only contain letters, numbers, underscores, and hyphens.';
  }
  const lower = trimmed.toLowerCase();
  if (lower === 'default' || lower === 'import') {
    return `"${trimmed}" is a reserved profile name.`;
  }
  return null;
}

function setValidationError(fieldKey, message) {
  const el = settingEls[fieldKey];
  if (!el) return;

  el.classList.add('input-error');
  validationErrors.set(fieldKey, message);

  const row = el.closest('.setting-row');
  if (row) {
    let msgEl = row.querySelector('.validation-error-text');
    if (!msgEl) {
      msgEl = document.createElement('div');
      msgEl.className = 'validation-error-text';
      const info = row.querySelector('.setting-info');
      if (info) {
        info.appendChild(msgEl);
      } else {
        row.appendChild(msgEl);
      }
    }
    msgEl.textContent = message;
    msgEl.classList.remove('hidden');
  }

  updateSaveButtonState();
}

function clearValidationError(fieldKey) {
  const el = settingEls[fieldKey];
  if (!el) return;

  el.classList.remove('input-error');
  validationErrors.delete(fieldKey);

  const row = el.closest('.setting-row');
  if (row) {
    const msgEl = row.querySelector('.validation-error-text');
    if (msgEl) {
      msgEl.textContent = '';
      msgEl.classList.add('hidden');
    }
  }

  updateSaveButtonState();
}

function updateSaveButtonState() {
  if (saveProfileButton) {
    if (validationErrors.size > 0) {
      saveProfileButton.disabled = true;
      saveProfileButton.title = "Please fix validation errors before saving.";
      saveProfileButton.style.opacity = '0.5';
      saveProfileButton.style.cursor = 'not-allowed';
    } else {
      saveProfileButton.disabled = false;
      saveProfileButton.title = "";
      saveProfileButton.style.opacity = '';
      saveProfileButton.style.cursor = '';
    }
  }
}

function runValidation() {
  // 1a. Max Completion Tokens (512 - 4096)
  const maxCompletionEl = settingEls.max_completion_tokens;
  if (maxCompletionEl) {
    const val = parseInt(maxCompletionEl.value, 10);
    if (isNaN(val) || val < 512 || val > 4096) {
      setValidationError('max_completion_tokens', 'Max completion tokens must be between 512 and 4096.');
    } else {
      clearValidationError('max_completion_tokens');
    }
  }

  // 1b. Long Draft Warning (words) (300 - 10000)
  const longWarnEl = settingEls.long_draft_warning_words;
  if (longWarnEl) {
    const val = parseInt(longWarnEl.value, 10);
    if (isNaN(val) || val < 300 || val > 10000) {
      setValidationError('long_draft_warning_words', 'Long draft warning must be between 300 and 10000 words.');
    } else {
      clearValidationError('long_draft_warning_words');
    }
  }

  // 2. LLM Chunk Size (50 - 5000)
  const llmChunkEl = settingEls.llm_chunk_size;
  if (llmChunkEl) {
    const val = parseInt(llmChunkEl.value, 10);
    if (isNaN(val) || val < 50 || val > 5000) {
      setValidationError('llm_chunk_size', 'LLM chunk size must be between 50 and 5000.');
    } else {
      clearValidationError('llm_chunk_size');
    }
  }

  // 3. Whisper Chunk Size (50 - 5000)
  const whisperChunkEl = settingEls.whisper_chunk_size;
  if (whisperChunkEl) {
    const val = parseInt(whisperChunkEl.value, 10);
    if (isNaN(val) || val < 50 || val > 5000) {
      setValidationError('whisper_chunk_size', 'Whisper chunk size must be between 50 and 5000.');
    } else {
      clearValidationError('whisper_chunk_size');
    }
  }

  // 4. TTS Speed (0.5 - 3.0)
  const ttsSpeedEl = settingEls.review_tts_speed;
  if (ttsSpeedEl) {
    const val = parseFloat(ttsSpeedEl.value);
    if (isNaN(val) || val < 0.5 || val > 3.0) {
      setValidationError('review_tts_speed', 'TTS speed must be between 0.5 and 3.0.');
    } else {
      clearValidationError('review_tts_speed');
    }
  }

  // 5. Min Duration (0.0 - 30.0)
  const durationEl = settingEls.no_audio_min_duration_sec;
  if (durationEl) {
    const val = parseFloat(durationEl.value);
    if (isNaN(val) || val < 0.0 || val > 30.0) {
      setValidationError('no_audio_min_duration_sec', 'Min duration must be between 0.0 and 30.0s.');
    } else {
      clearValidationError('no_audio_min_duration_sec');
    }
  }

  // 6. Min RMS (0.0 - 1.0)
  const rmsEl = settingEls.no_audio_min_rms;
  if (rmsEl) {
    const val = parseFloat(rmsEl.value);
    if (isNaN(val) || val < 0.0 || val > 1.0) {
      setValidationError('no_audio_min_rms', 'Min RMS must be between 0.0 and 1.0.');
    } else {
      clearValidationError('no_audio_min_rms');
    }
  }

  // 7. Min Peak (0.0 - 1.0)
  const peakEl = settingEls.no_audio_min_peak;
  if (peakEl) {
    const val = parseFloat(peakEl.value);
    if (isNaN(val) || val < 0.0 || val > 1.0) {
      setValidationError('no_audio_min_peak', 'Min Peak must be between 0.0 and 1.0.');
    } else {
      clearValidationError('no_audio_min_peak');
    }
  }

  // 7b. Confidence-gated send thresholds (0.0 - 1.0)
  for (const key of ['confidence_force_review_below', 'confidence_auto_send_above']) {
    const el = settingEls[key];
    if (el) {
      const val = parseFloat(el.value);
      if (isNaN(val) || val < 0.0 || val > 1.0) {
        setValidationError(key, 'Confidence thresholds must be between 0.0 and 1.0.');
      } else {
        clearValidationError(key);
      }
    }
  }

  // 7c. Auto-stop after silence (ms ranges)
  const autoStopSilenceEl = settingEls.auto_stop_silence_ms;
  if (autoStopSilenceEl) {
    const val = parseInt(autoStopSilenceEl.value, 10);
    if (isNaN(val) || val < 250 || val > 5000) {
      setValidationError('auto_stop_silence_ms', 'Auto-stop silence must be between 250 and 5000 ms.');
    } else {
      clearValidationError('auto_stop_silence_ms');
    }
  }
  const autoStopMinEl = settingEls.auto_stop_min_recording_ms;
  if (autoStopMinEl) {
    const val = parseInt(autoStopMinEl.value, 10);
    if (isNaN(val) || val < 0 || val > 10000) {
      setValidationError('auto_stop_min_recording_ms', 'Auto-stop minimum recording must be between 0 and 10000 ms.');
    } else {
      clearValidationError('auto_stop_min_recording_ms');
    }
  }

  // 8. Hotkeys Collision Detection
  const hotkeyFields = [
    'hotkey',
    'force_stop_key',
    'manual_send_hotkey',
    'review_tts_hotkey',
    'chat_open_key',
    'voice_mute_key'
  ];

  const keysMap = new Map();
  hotkeyFields.forEach(field => {
    const el = settingEls[field];
    if (el) {
      const val = el.value.trim().toLowerCase();
      if (val) {
        if (!keysMap.has(val)) {
          keysMap.set(val, []);
        }
        keysMap.get(val).push(field);
      }
    }
  });

  hotkeyFields.forEach(field => {
    if (validationErrors.has(field) && validationErrors.get(field).includes('collision')) {
      clearValidationError(field);
    }
  });

  for (const [key, fields] of keysMap.entries()) {
    if (fields.length > 1) {
      fields.forEach(field => {
        const otherLabels = fields.filter(f => f !== field).map(f => {
          const labelEl = document.querySelector(`label[for="${settingEls[f].id}"]`);
          return labelEl ? labelEl.textContent.trim() : f;
        }).join(', ');
        setValidationError(field, `Hotkey collision: '${key}' is also used by ${otherLabels}.`);
      });
    }
  }
}

function filterSettings(query) {
  const q = query.trim().toLowerCase();
  const searchHeader = document.getElementById('settingsSearchHeader');
  const emptyState = document.getElementById('settingsEmptyState');
  const sidebarNavButtons = document.querySelectorAll('.settings-nav-button');
  const sections = document.querySelectorAll('.settings-section');

  if (!q) {
    if (searchHeader) searchHeader.classList.add('hidden');
    if (emptyState) emptyState.classList.add('hidden');

    let activeSectionName = 'general';
    sidebarNavButtons.forEach(btn => {
      btn.disabled = false;
      if (btn.classList.contains('active')) {
        activeSectionName = btn.dataset.section;
      }
    });

    sections.forEach(section => {
      if (section.dataset.section === activeSectionName) {
        section.classList.remove('hidden');
        section.classList.add('active');
      } else {
        section.classList.add('hidden');
        section.classList.remove('active');
      }
      section.querySelectorAll('.setting-group').forEach(group => group.classList.remove('hidden'));
      section.querySelectorAll('.setting-row').forEach(row => row.classList.remove('hidden'));
    });
    return;
  }

  if (searchHeader) searchHeader.classList.remove('hidden');

  let totalMatches = 0;

  sections.forEach(section => {
    let sectionMatches = 0;

    section.querySelectorAll('.setting-group').forEach(group => {
      let groupMatches = 0;

      group.querySelectorAll('.setting-row').forEach(row => {
        const text = row.textContent.toLowerCase();
        const inputs = Array.from(row.querySelectorAll('input, select, textarea')).map(input => {
          return (input.id || '') + ' ' + (input.name || '') + ' ' + (input.placeholder || '');
        }).join(' ').toLowerCase();

        const isMatch = text.includes(q) || inputs.includes(q);

        if (isMatch) {
          row.classList.remove('hidden');
          groupMatches++;
          sectionMatches++;
          totalMatches++;
        } else {
          row.classList.add('hidden');
        }
      });

      if (groupMatches > 0) {
        group.classList.remove('hidden');
      } else {
        group.classList.add('hidden');
      }
    });

    if (sectionMatches > 0) {
      section.classList.remove('hidden');
      section.classList.add('active');
    } else {
      section.classList.add('hidden');
      section.classList.remove('active');
    }
  });

  if (totalMatches === 0) {
    if (emptyState) emptyState.classList.remove('hidden');
  } else {
    if (emptyState) emptyState.classList.add('hidden');
  }
}

function updatePlatformWarnings(capabilities) {
  const isWayland = capabilities.is_wayland;
  const isLinux = capabilities.is_linux;
  const isWindows = capabilities.is_windows;

  const waylandHotkeyWarning = document.getElementById('waylandHotkeyWarning');
  if (waylandHotkeyWarning) {
    if (isLinux && isWayland) {
      waylandHotkeyWarning.classList.remove('hidden');
    } else {
      waylandHotkeyWarning.classList.add('hidden');
    }
  }

  const waylandInjectionWarning = document.getElementById('waylandInjectionWarning');
  if (waylandInjectionWarning) {
    if (isLinux && isWayland) {
      waylandInjectionWarning.classList.remove('hidden');
    } else {
      waylandInjectionWarning.classList.add('hidden');
    }
  }

  // Injection genuinely unavailable (e.g. Linux without xclip/xsel/wl-clipboard):
  // surface the backend's actionable hint instead of silently failing at send time.
  const injectionUnavailableWarning = document.getElementById('injectionUnavailableWarning');
  if (injectionUnavailableWarning) {
    const hint = capabilities.injection_hint;
    if (capabilities.supports_input_injection === false && hint) {
      injectionUnavailableWarning.innerHTML = `<strong>Text injection unavailable:</strong> ${escapeHtml(hint)}`;
      injectionUnavailableWarning.classList.remove('hidden');
    } else {
      injectionUnavailableWarning.classList.add('hidden');
    }
  }

  // Audio ducking is available on Windows and on Linux with pactl/PipeWire;
  // trust the backend capability rather than assuming Windows-only.
  const supportsAudioDucking = Boolean(capabilities.supports_audio_ducking);

  const audioDuckingWarning = document.getElementById('audioDuckingWarning');
  if (audioDuckingWarning) {
    if (supportsAudioDucking) {
      audioDuckingWarning.classList.add('hidden');
    } else {
      audioDuckingWarning.classList.remove('hidden');
      audioDuckingWarning.innerHTML = '<strong>Audio Ducking Warning:</strong> Dynamic volume ducking isn\'t available on this system (needs Windows, or Linux with <code>pactl</code>/PipeWire). Please manually pause background media players during speech capture.';
    }
  }

  // Enforce disabling of platform-unsupported controls dynamically
  const audioDuckingInput = settingEls.audio_ducking;
  if (audioDuckingInput) {
    if (!supportsAudioDucking) {
      audioDuckingInput.checked = false;
      audioDuckingInput.disabled = true;
      audioDuckingInput.title = "Audio ducking needs Windows, or Linux with pactl/PipeWire.";
    } else {
      audioDuckingInput.disabled = false;
      audioDuckingInput.title = "";
    }
  }

  const instantTypingInput = settingEls.instant_typing;
  if (instantTypingInput) {
    if (isLinux && isWayland) {
      instantTypingInput.checked = false;
      instantTypingInput.disabled = true;
      instantTypingInput.title = "Instant typing is not supported on Linux Wayland. BetterFingers will fall back to clipboard copy-only mode.";
    } else {
      instantTypingInput.disabled = false;
      instantTypingInput.title = "";
    }
  }

  addPlatformBadge('settingAudioDucking', supportsAudioDucking ? 'Supported' : 'Unsupported', supportsAudioDucking ? 'success' : 'danger');
  addPlatformBadge('settingInstantTyping', (isLinux && isWayland) ? 'Wayland Limitation' : '', 'danger');
  addPlatformBadge('settingHotkey', (isLinux && isWayland) ? 'Global shortcut depends on Wayland compositor' : '', 'danger');
}

function addPlatformBadge(settingId, text, tone) {
  const input = document.getElementById(settingId);
  if (!input) return;

  const row = input.closest('.setting-row');
  if (!row) return;

  const info = row.querySelector('.setting-info');
  if (!info) return;

  const label = info.querySelector('.status-label');
  if (!label) return;

  let badge = label.querySelector('.warning-badge');
  if (badge) {
    badge.remove();
  }

  if (text) {
    badge = document.createElement('span');
    badge.className = 'warning-badge';
    badge.dataset.tone = tone;
    badge.textContent = text;
    label.appendChild(badge);
  }
}

// Appearance preferences
const themeSelect = document.getElementById('settingTheme');
const accentSelect = document.getElementById('settingAccentColor');
const densitySelect = document.getElementById('settingDensity');
const fontSizeSelect = document.getElementById('settingFontSize');
const highContrastCheck = document.getElementById('settingHighContrast');

const VALID_THEMES = ['system', 'dark', 'light'];
const VALID_ACCENTS = ['teal', 'purple', 'blue', 'gold'];
const VALID_DENSITIES = ['comfortable', 'compact'];
const VALID_FONT_SIZES = ['small', 'medium', 'large', 'huge'];

function applyAppearance() {
  let theme = localStorage.getItem('pref_theme') || 'system';
  if (!VALID_THEMES.includes(theme)) {
    theme = 'system';
    localStorage.setItem('pref_theme', theme);
  }

  let accent = localStorage.getItem('pref_accent') || 'teal';
  if (!VALID_ACCENTS.includes(accent)) {
    accent = 'teal';
    localStorage.setItem('pref_accent', accent);
  }

  let density = localStorage.getItem('pref_density') || 'comfortable';
  if (!VALID_DENSITIES.includes(density)) {
    density = 'comfortable';
    localStorage.setItem('pref_density', density);
  }

  let fontSize = localStorage.getItem('pref_font_size') || 'medium';
  if (!VALID_FONT_SIZES.includes(fontSize)) {
    fontSize = 'medium';
    localStorage.setItem('pref_font_size', fontSize);
  }

  const highContrast = localStorage.getItem('pref_high_contrast') === 'true';

  document.body.classList.remove('theme-light', 'theme-dark');
  if (theme === 'light') {
    document.body.classList.add('theme-light');
  } else if (theme === 'dark') {
    document.body.classList.add('theme-dark');
  } else {
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    document.body.classList.add(prefersDark ? 'theme-dark' : 'theme-light');
  }

  document.body.classList.remove('accent-teal', 'accent-purple', 'accent-blue', 'accent-gold');
  document.body.classList.add(`accent-${accent}`);

  document.body.classList.remove('density-compact', 'density-comfortable');
  document.body.classList.add(`density-${density}`);

  document.documentElement.className = '';
  document.documentElement.classList.add(`font-${fontSize}`);

  if (highContrast) {
    document.body.classList.add('high-contrast');
  } else {
    document.body.classList.remove('high-contrast');
  }

  if (themeSelect) themeSelect.value = theme;
  if (accentSelect) accentSelect.value = accent;
  if (densitySelect) densitySelect.value = density;
  if (fontSizeSelect) fontSizeSelect.value = fontSize;
  if (highContrastCheck) highContrastCheck.checked = highContrast;
}

// Microphone live level test
const micMeterBar = document.getElementById('micMeterBar');
const micMeterFill = document.getElementById('micMeterFill');
let micStream = null;
let audioContext = null;
let analyser = null;
let micInterval = null;

function stopMicTest() {
  if (micInterval) {
    cancelAnimationFrame(micInterval);
    micInterval = null;
  }
  if (micStream) {
    micStream.getTracks().forEach(track => track.stop());
    micStream = null;
  }
  if (audioContext) {
    audioContext.close();
    audioContext = null;
  }
  const testMicButton = document.getElementById('testMicButton');
  if (testMicButton) {
    testMicButton.textContent = 'Test Browser Microphone Access';
    testMicButton.classList.remove('danger-button');
  }
  if (micMeterBar) {
    micMeterBar.classList.add('hidden');
  }
  if (micMeterFill) {
    micMeterFill.style.width = '0%';
  }
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

function updateVoiceStatus(message) {
  if (!message) {
    return;
  }

  const statusText = typeof message === 'string' ? message : String(message.status ?? message.type ?? 'unknown');
  voiceStatusEl.textContent = statusText;
  voiceStatusDetailEl.textContent = JSON.stringify(message, null, 2);
  sendOverlayUpdate(message);

  if (['preview_ready', 'draft_blocked', 'draft_error'].includes(message.status)) {
    const draft = {
      id: message.draft_id,
      raw_text: message.raw_text,
      final_text: message.final_text,
      status: message.status === 'draft_blocked' ? 'blocked' : message.status === 'draft_error' ? 'error' : 'pending',
      error: message.error ?? '',
      gate_reasons: message.gate_reasons ?? [],
      token_count: message.token_count,
      token_limit: message.token_limit,
      long_text: message.long_text,
      confidence: message.confidence,
      auto_send_ok: message.auto_send_ok,
      force_review: message.force_review,
      force_review_reason: message.force_review_reason,
    };
    renderDraft(draft);
    if (message.status === 'preview_ready') {
      showReviewOverlayDraft(draft);
    }
    setMessage(
      draftMessageEl,
      message.status === 'preview_ready' ? 'New draft ready for review.' : message.error || 'Draft needs attention.',
      message.status === 'preview_ready' ? 'success' : 'danger',
    );
    refreshDrafts().catch(() => {});
  }

  // Long-recording progress: keep the review overlay closed (it only opens on
  // preview_ready above) and surface chunk-by-chunk progress in the status rail.
  if (['long_recording_detected', 'chunking_started', 'chunking_progress', 'chunking_stitching'].includes(message.status)) {
    let progressText;
    if (message.status === 'long_recording_detected') {
      progressText = 'Long recording detected. Processing…';
    } else if (message.status === 'chunking_started') {
      const n = message.chunk_count;
      progressText = n ? `Long recording detected. Processing ${n} chunk${n === 1 ? '' : 's'}…` : 'Processing long recording…';
    } else if (message.status === 'chunking_progress') {
      progressText = `Processing chunk ${message.chunk_index} of ${message.chunk_count}…`;
    } else {
      progressText = 'Smoothing chunk transitions…';
    }
    setMessage(draftMessageEl, progressText, 'warning');
  }

  // Missed-release watchdog (Phase 11): a stranded recording was force-stopped
  // after max_recording_seconds. Surface it as a warning so it doesn't look like
  // a silent glitch.
  if (message.status === 'watchdog_timeout_warning') {
    showToast(message.message || 'Recording stopped after max duration.', 'warning');
    setMessage(draftMessageEl, message.message || 'Recording stopped after max duration.', 'warning');
  }

  if (['draft_accepted', 'draft_declined'].includes(message.status)) {
    refreshDrafts().catch(() => {});
    refreshOutputSettings().catch(() => {});
  }

  if (message.status === 'draft_history_cleared') {
    renderDraft(null);
    refreshDrafts().catch(() => {});
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
    if (message.status === 'draft_rewritten' || message.status === 'draft_updated') {
      refreshLatestDraft().then(showReviewOverlayDraft).catch(() => {});
    }
    refreshDrafts().catch(() => {});
  }

  if (['draft_sent', 'draft_send_error', 'selection_captured', 'selection_capture_failed', 'emergency_stop'].includes(message.status)) {
    setMessage(draftMessageEl, message.message || message.send_result?.message || statusText, message.status.endsWith('error') || message.status.endsWith('failed') ? 'danger' : 'success');
    if (message.send_result) {
      renderSendResult(message.send_result);
    }
    if (message.status === 'draft_sent' || message.status === 'emergency_stop') {
      hideReviewOverlay();
    }
    refreshDrafts().catch(() => {});
    refreshOutputSettings().catch(() => {});
  }
}

function renderWakeStatus(status) {
  const enabledEl = document.getElementById('settingWakeWordEnabled');
  const detailEl = document.getElementById('wakeStatusDetail');
  const listening = Boolean(status && status.listening);
  if (enabledEl && document.activeElement !== enabledEl) {
    enabledEl.checked = listening;
  }
  if (detailEl) {
    if (listening) {
      detailEl.textContent = `Listening (threshold ${status.threshold ?? '?'}, cooldown ${status.cooldown_ms ?? '?'}ms).`;
    } else if (status && status.enabled) {
      detailEl.textContent = `Enabled but not listening: ${status.reason || 'unknown'}`;
    } else {
      const reason = status && status.reason && status.reason !== 'disabled' ? status.reason : '';
      detailEl.textContent = reason ? `Disabled (${reason}).` : 'Disabled.';
    }
  }
}

async function refreshWakeStatus() {
  try {
    const status = await fetchWakeStatus();
    renderWakeStatus(status);
  } catch (error) {
    const detailEl = document.getElementById('wakeStatusDetail');
    if (detailEl) detailEl.textContent = `Status unavailable: ${error.message}`;
  }
}

function renderWakeBackboneList(models) {
  const el = document.getElementById('wakeBackboneList');
  if (!el) return;
  const backbones = (models || []).filter((m) => m.kind === 'backbone');
  const badge = document.getElementById('wakeEngineBadge');
  if (!backbones.length) {
    el.innerHTML = '<span class="empty-state">No wake engine components listed.</span>';
    if (badge) badge.textContent = '—';
    return;
  }
  if (badge) {
    const ready = backbones.filter((m) => m.downloaded).length;
    badge.textContent = ready === backbones.length ? 'Installed' : `${ready}/${backbones.length} installed`;
  }
  el.innerHTML = backbones
    .map(
      (m) => `
      <div class="setting-row">
        <div class="setting-info">
          <span class="status-label">${escapeHtml(m.name)}</span>
          <span class="setting-desc">${escapeHtml(m.license)} — ${m.downloaded ? 'downloaded' : 'not downloaded'}</span>
        </div>
        <div class="setting-control">
          <button class="secondary-button settings-btn" type="button" data-wake-download="${escapeHtml(m.id)}" ${m.downloaded ? 'disabled' : ''}>
            ${m.downloaded ? 'Downloaded' : 'Download'}
          </button>
        </div>
      </div>`
    )
    .join('');
  el.querySelectorAll('[data-wake-download]').forEach((btn) => {
    btn.addEventListener('click', () => handleWakeDownload(btn.dataset.wakeDownload, btn));
  });
}

function renderWakeModelSelect(models) {
  const select = settingEls.wake_word_model;
  if (!select) return;
  const classifiers = (models || []).filter((m) => m.kind === 'classifier');
  const current = select.value;
  select.innerHTML = '<option value="">None imported</option>';
  classifiers.forEach((m) => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = `${m.name} (${m.license})`;
    select.appendChild(opt);
  });
  if (classifiers.some((m) => m.id === current)) {
    select.value = current;
  }
}

async function refreshWakeModels() {
  try {
    const payload = await fetchWakeModels();
    const models = payload?.models || [];
    renderWakeBackboneList(models);
    renderWakeModelSelect(models);
  } catch (error) {
    const el = document.getElementById('wakeBackboneList');
    if (el) el.innerHTML = `<span class="empty-state">Wake models unavailable: ${escapeHtml(error.message)}</span>`;
  }
}

async function handleWakeDownload(modelId, buttonEl) {
  if (!modelId) return;
  if (buttonEl) {
    buttonEl.disabled = true;
    buttonEl.textContent = 'Downloading…';
  }
  try {
    await downloadWakeModel(modelId);
    const poll = async () => {
      const state = await fetchWakeModelDownloadState(modelId);
      if (state.active) {
        setTimeout(poll, 1000);
        return;
      }
      await refreshWakeModels();
    };
    setTimeout(poll, 1000);
  } catch (error) {
    showToast(`Wake model download failed: ${error.message}`, 'danger');
    if (buttonEl) {
      buttonEl.disabled = false;
      buttonEl.textContent = 'Download';
    }
  }
}

async function handleWakeImport(file) {
  const statusEl = document.getElementById('importWakeModelStatus');
  if (!file) return;
  const name = file.name.replace(/\.onnx$/i, '') || 'Imported model';
  if (statusEl) statusEl.textContent = `Importing ${file.name}…`;
  try {
    await importWakeModel(file, name);
    if (statusEl) statusEl.textContent = `Imported ${file.name}. Its licensing is your responsibility.`;
    await refreshWakeModels();
  } catch (error) {
    if (statusEl) statusEl.textContent = `Import failed: ${error.message}`;
    showToast(`Wake model import failed: ${error.message}`, 'danger');
  }
}

// Truthful backbone readiness (loadable, not just present) for the two wake
// engine models. Returns the list of backbones that still need installing.
async function getMissingWakeBackbones() {
  const payload = await fetchWakeModels();
  const backbones = (payload?.models || []).filter((m) => m.kind === 'backbone');
  const checked = await Promise.all(
    backbones.map(async (m) => {
      try {
        const state = await fetchWakeModelDownloadState(m.id);
        return { ...m, ready: !!state.downloaded };
      } catch {
        return { ...m, ready: false };
      }
    }),
  );
  return checked.filter((m) => !m.ready);
}

// Enabling wake word requires the engine backbones. If they're missing, offer
// to jump to the Models tab (same install flow as every other model) instead
// of failing with an opaque "unavailable".
async function ensureWakeBackbonesOrPromptModels() {
  let missing;
  try {
    missing = await getMissingWakeBackbones();
  } catch {
    return true; // don't block enable on a readiness-probe hiccup
  }
  if (!missing.length) return true;
  const names = missing.map((m) => m.name).join(', ');
  const goToModels = window.confirm(
    `Wake word needs these engine models installed first:\n\n${names}\n\n`
      + 'Click OK to open the Models tab and install them, or Cancel to stay here.',
  );
  if (goToModels) {
    const modelsTabButton = document.getElementById('tabButtonModels');
    if (modelsTabButton) activateTab(modelsTabButton, { focus: true });
    refreshModels().catch(() => {});
  }
  return false;
}

async function handleWakeToggle(checked) {
  const enabledEl = document.getElementById('settingWakeWordEnabled');
  if (enabledEl) enabledEl.disabled = true;
  try {
    if (checked) {
      // Gate on the engine backbones first: prompt to install via the Models
      // tab rather than letting enable fail with a cryptic reason.
      const ready = await ensureWakeBackbonesOrPromptModels();
      if (!ready) {
        if (enabledEl) enabledEl.checked = false;
        return;
      }
      const sensitivityEl = settingEls.wake_word_sensitivity;
      const cooldownEl = settingEls.wake_word_cooldown_s;
      const modelEl = settingEls.wake_word_model;
      const result = await enableWake({
        classifier_id: modelEl?.value || null,
        classifier_origin: 'user-imported',
        threshold: sensitivityEl?.value ? parseFloat(sensitivityEl.value) : undefined,
        cooldown_ms: cooldownEl?.value ? Math.round(parseFloat(cooldownEl.value) * 1000) : undefined,
      });
      if (!result || result.ok === false) {
        showToast(result?.reason || 'Wake word is unavailable.', 'warning');
        if (enabledEl) enabledEl.checked = false;
      }
      renderWakeStatus(result);
    } else {
      const result = await disableWake();
      renderWakeStatus(result);
    }
  } catch (error) {
    showToast(`Wake word toggle failed: ${error.message}`, 'danger');
    if (enabledEl) enabledEl.checked = !checked;
  } finally {
    if (enabledEl) enabledEl.disabled = false;
  }
}

async function handleWakeTest() {
  const button = document.getElementById('testWakeButton');
  const bar = document.getElementById('wakeScoreBar');
  const fill = document.getElementById('wakeScoreFill');
  const resultEl = document.getElementById('wakeTestResult');
  if (button) {
    button.disabled = true;
    button.textContent = 'Listening… (10s)';
  }
  bar?.classList.remove('hidden');
  if (fill) fill.style.width = '0%';
  if (resultEl) resultEl.textContent = '';
  try {
    const result = await testWake(10.0);
    if (!result || result.ok === false) {
      if (resultEl) resultEl.textContent = result?.reason || 'Wake test unavailable.';
    } else {
      const peakPercent = Math.max(0, Math.min(100, Math.round((result.peak_score || 0) * 100)));
      if (fill) fill.style.width = `${peakPercent}%`;
      if (resultEl) {
        resultEl.textContent = `Peak score: ${(result.peak_score || 0).toFixed(2)} over ${result.sample_count || 0} samples.`;
      }
    }
  } catch (error) {
    if (resultEl) resultEl.textContent = `Test failed: ${error.message}`;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = 'Test Wake Detection (10s)';
    }
  }
}

const _WAKE_VERDICT_COPY = {
  reliable: { text: 'Reliable — clean separation. Select it in the model picker above to use it.', tone: 'success' },
  noisy: { text: 'Usable but noisy — try more/clearer samples or a more distinct phrase. Selectable above.', tone: 'warn' },
  unusable: { text: 'Not separable — pick a more distinctive phrase (more syllables) and retrain.', tone: 'danger' },
};

async function handleWakeTrain() {
  const button = document.getElementById('wakeTrainButton');
  const phraseEl = document.getElementById('wakeTrainPhrase');
  const progress = document.getElementById('wakeTrainProgress');
  const label = document.getElementById('wakeTrainProgressLabel');
  const percentEl = document.getElementById('wakeTrainProgressPercent');
  const fill = document.getElementById('wakeTrainProgressFill');
  const resultEl = document.getElementById('wakeTrainResult');

  const phrase = (phraseEl?.value || '').trim();
  if (!phrase) {
    if (resultEl) resultEl.textContent = 'Enter a wake phrase to train.';
    return;
  }

  const setProgress = (pct, msg) => {
    if (fill) fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
    if (percentEl) percentEl.textContent = `${Math.round(pct)}%`;
    if (label) label.textContent = msg || '';
  };

  if (button) button.disabled = true;
  if (resultEl) { resultEl.textContent = ''; resultEl.className = 'setting-desc'; }
  progress?.removeAttribute('hidden');
  setProgress(0, 'Starting…');

  try {
    const start = await trainWakePhrase(phrase);
    if (start && start.ok === false && start.already_running) {
      if (resultEl) resultEl.textContent = 'A training run is already in progress.';
      if (button) button.disabled = false;
      return;
    }
    // Poll until the background run finishes. Training is model-free but the
    // Kokoro synthesis of the phrase + decoys can take up to ~a minute.
    const deadline = Date.now() + 180000;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 700));
      let status;
      try {
        status = await fetchWakeTrainStatus();
      } catch {
        continue;
      }
      setProgress(status.percent || 0, status.message || '');
      if (status.status === 'done') {
        const result = status.result || {};
        if (!result.ok) {
          if (resultEl) { resultEl.textContent = result.message || 'Training failed.'; resultEl.className = 'setting-desc danger'; }
        } else {
          const copy = _WAKE_VERDICT_COPY[result.verdict] || { text: `Trained (${result.verdict}).`, tone: '' };
          if (resultEl) {
            resultEl.textContent = `Trained "${phrase}" — ${copy.text} `
              + `(false-accept ${Math.round((result.fa_rate || 0) * 100)}%, false-reject ${Math.round((result.fr_rate || 0) * 100)}%)`;
            resultEl.className = `setting-desc ${copy.tone}`;
          }
          // The new trained classifier now appears in the model picker.
          refreshWakeModels().catch(() => {});
        }
        return;
      }
    }
    if (resultEl) resultEl.textContent = 'Training is taking longer than expected — check back shortly.';
  } catch (error) {
    if (resultEl) resultEl.textContent = `Training failed: ${error.message}`;
  } finally {
    if (button) button.disabled = false;
    progress?.setAttribute('hidden', '');
  }
}

function initSettingsPanel() {
  for (const el of Object.values(settingEls)) {
    if (!el) continue;
    el.addEventListener('input', () => {
      markProfileDirty();
      runValidation();
    });
    el.addEventListener('change', () => {
      markProfileDirty();
      runValidation();
    });
  }

  document.querySelectorAll('.setting-row').forEach((row) => {
    const input = row.querySelector('.hotkey-input');
    const clearBtn = row.querySelector('.clear-hotkey-btn');
    if (input && clearBtn) {
      clearBtn.addEventListener('click', () => {
        input.value = '';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
    }
  });

  const categoryButtons = document.querySelectorAll('.settings-nav-button');
  const settingsSections = document.querySelectorAll('.settings-section');
  const settingsSearchInput = document.getElementById('settingsSearchInput');

  categoryButtons.forEach((btn) => {
    btn.addEventListener('click', () => {
      const sectionName = btn.dataset.section;

      if (settingsSearchInput) {
        settingsSearchInput.value = '';
      }

      categoryButtons.forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');

      if (sectionName === 'privacy') {
        refreshPrivacy().catch(() => {});
      } else if (sectionName === 'dictionary') {
        refreshDictionary().catch(() => {});
      } else if (sectionName === 'macros') {
        refreshMacros().catch(() => {});
      } else if (sectionName === 'voice-control') {
        refreshWakeStatus().catch(() => {});
        refreshWakeModels().catch(() => {});
      } else if (sectionName === 'tts-readaloud') {
        refreshVoiceBlendCapabilityNote().catch(() => {});
        refreshCloneStatusNote().catch(() => {});
      }

      settingsSections.forEach((section) => {
        if (section.dataset.section === sectionName) {
          section.classList.remove('hidden');
          section.classList.add('active');
        } else {
          section.classList.add('hidden');
          section.classList.remove('active');
        }
        section.querySelectorAll('.setting-group').forEach(group => group.classList.remove('hidden'));
        section.querySelectorAll('.setting-row').forEach(row => row.classList.remove('hidden'));
      });

      const searchHeader = document.getElementById('settingsSearchHeader');
      const emptyState = document.getElementById('settingsEmptyState');
      if (searchHeader) searchHeader.classList.add('hidden');
      if (emptyState) emptyState.classList.add('hidden');
    });
  });

  settingsSearchInput?.addEventListener('input', (e) => {
    filterSettings(e.target.value);
  });

  document.getElementById('settingWakeWordEnabled')?.addEventListener('change', (event) => {
    handleWakeToggle(event.target.checked);
  });

  const importWakeModelButton = document.getElementById('importWakeModelButton');
  const importWakeModelFile = document.getElementById('importWakeModelFile');
  importWakeModelButton?.addEventListener('click', () => importWakeModelFile?.click());
  importWakeModelFile?.addEventListener('change', (event) => {
    const file = event.target.files && event.target.files[0];
    handleWakeImport(file);
    event.target.value = '';
  });

  document.getElementById('testWakeButton')?.addEventListener('click', () => {
    handleWakeTest();
  });

  document.getElementById('wakeTrainButton')?.addEventListener('click', () => {
    handleWakeTrain();
  });

  const testMicButton = document.getElementById('testMicButton');
  testMicButton?.addEventListener('click', async () => {
    if (micStream) {
      stopMicTest();
      return;
    }

    testMicButton.textContent = 'Stop Mic Test';
    testMicButton.classList.add('danger-button');
    micMeterBar?.classList.remove('hidden');

    try {
      micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      const source = audioContext.createMediaStreamSource(micStream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      function updateMeter() {
        if (!micStream || !analyser) return;
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        const percentage = Math.min(100, Math.round((average / 128) * 100));
        if (micMeterFill) {
          micMeterFill.style.width = `${percentage}%`;
        }
        micInterval = requestAnimationFrame(updateMeter);
      }
      updateMeter();
    } catch (error) {
      setMessage(profileMessageEl, `Microphone test failed: ${error.message}. Please check permissions.`, 'danger');
      stopMicTest();
    }
  });

  voiceStudio.init({ doc: document });

  const testPasteCopyButton = document.getElementById('testPasteCopyButton');
  testPasteCopyButton?.addEventListener('click', async () => {
    const testText = "BetterFingers Paste Test Success!";
    try {
      await window.betterFingers?.writeClipboardText?.(testText);
      setMessage(profileMessageEl, 'Test text copied to clipboard! Try pasting it in any text field.', 'success');
    } catch (error) {
      setMessage(profileMessageEl, `Paste/Copy test failed: ${error.message}`, 'danger');
    }
  });

  const testModelLoadButton = document.getElementById('testModelLoadButton');
  testModelLoadButton?.addEventListener('click', async () => {
    testModelLoadButton.disabled = true;
    testModelLoadButton.textContent = 'Loading...';
    try {
      const res = await warmupRuntime({ llm: true });
      if (res?.llm?.ok === false) {
        setMessage(profileMessageEl, `Model load failed: ${res.llm.error || 'Unknown error'}`, 'danger');
      } else {
        setMessage(profileMessageEl, 'Model loaded successfully!', 'success');
      }
    } catch (error) {
      setMessage(profileMessageEl, `Model load test failed: ${error.message}`, 'danger');
    } finally {
      testModelLoadButton.disabled = false;
      testModelLoadButton.textContent = 'Test Model Load';
    }
  });

  themeSelect?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (VALID_THEMES.includes(val)) {
      localStorage.setItem('pref_theme', val);
    } else {
      localStorage.setItem('pref_theme', 'system');
    }
    applyAppearance();
  });
  accentSelect?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (VALID_ACCENTS.includes(val)) {
      localStorage.setItem('pref_accent', val);
    } else {
      localStorage.setItem('pref_accent', 'teal');
    }
    applyAppearance();
  });
  densitySelect?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (VALID_DENSITIES.includes(val)) {
      localStorage.setItem('pref_density', val);
    } else {
      localStorage.setItem('pref_density', 'comfortable');
    }
    applyAppearance();
  });
  fontSizeSelect?.addEventListener('change', (e) => {
    const val = e.target.value;
    if (VALID_FONT_SIZES.includes(val)) {
      localStorage.setItem('pref_font_size', val);
    } else {
      localStorage.setItem('pref_font_size', 'medium');
    }
    applyAppearance();
  });
  highContrastCheck?.addEventListener('change', (e) => {
    localStorage.setItem('pref_high_contrast', e.target.checked === true);
    applyAppearance();
  });

  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    if ((localStorage.getItem('pref_theme') || 'system') === 'system') {
      applyAppearance();
    }
  });

  applyAppearance();
}

quitButton?.addEventListener('click', () => {
  window.betterFingers?.quitApp?.();
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

toggleRecordingButton?.addEventListener('click', async () => {
  toggleRecordingButton.disabled = true;
  const previousText = toggleRecordingButton.textContent;
  toggleRecordingButton.textContent = 'Working...';
  try {
    const result = await toggleRecording();
    setMessage(draftMessageEl, result?.message || 'Recording toggled.', result?.ok ? 'success' : 'warning');
    await Promise.all([refreshRuntime(), refreshDrafts()]);
  } catch (error) {
    setMessage(draftMessageEl, `Recording failed: ${error.message}`, 'danger');
  } finally {
    toggleRecordingButton.disabled = false;
    if (toggleRecordingButton.textContent === 'Working...') {
      toggleRecordingButton.textContent = previousText;
    }
  }
});

dashboardEmergencyStopButton?.addEventListener('click', async () => {
  dashboardEmergencyStopButton.disabled = true;
  dashboardEmergencyStopButton.textContent = 'Stopping...';
  try {
    const result = await emergencyStop();
    setMessage(draftMessageEl, result?.message || 'Emergency stop completed.', result?.ok ? 'success' : 'warning');
    await Promise.all([refreshRuntime(), refreshOutputSettings()]);
  } catch (error) {
    setMessage(draftMessageEl, `Emergency stop failed: ${error.message}`, 'danger');
  } finally {
    dashboardEmergencyStopButton.textContent = 'Emergency Stop';
    dashboardEmergencyStopButton.disabled = false;
  }
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

async function handleCopySupportReport() {
  const button = copySupportReportButton;
  const original = button ? button.textContent : '';
  if (button) {
    button.disabled = true;
    button.textContent = 'Building report…';
  }
  try {
    const payload = await fetchSupportReport();
    const markdown = payload?.markdown;
    if (!markdown) {
      throw new Error('empty report');
    }
    await window.betterFingers?.writeClipboardText?.(markdown);
    showToast('Support report copied to clipboard.', 'success', 2500);
  } catch (error) {
    showToast(`Could not build support report: ${error.message}`, 'danger');
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = original || 'Copy Support Report';
    }
  }
}

copySupportReportButton?.addEventListener('click', handleCopySupportReport);

document.getElementById('privacyWipeButton')?.addEventListener('click', handleWipeData);

document.getElementById('dictionaryAddButton')?.addEventListener('click', () => {
  handleAddDictionaryTerm(document.getElementById('dictionaryInput')?.value);
});
document.getElementById('macroAddButton')?.addEventListener('click', handleAddMacro);
document.getElementById('macroExpansion')?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    handleAddMacro();
  }
});
document.getElementById('macrosList')?.addEventListener('click', (event) => {
  const remove = event.target.closest('.macro-remove');
  if (remove?.dataset.trigger) {
    handleRemoveMacro(remove.dataset.trigger);
  }
});
document.getElementById('dictionaryInput')?.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') {
    event.preventDefault();
    handleAddDictionaryTerm(event.target.value);
  }
});
document.getElementById('dictionaryList')?.addEventListener('click', (event) => {
  const remove = event.target.closest('.dictionary-chip-remove');
  if (remove?.dataset.term) {
    handleRemoveDictionaryTerm(remove.dataset.term);
  }
});
document.getElementById('dictionarySuggestions')?.addEventListener('click', (event) => {
  const add = event.target.closest('.dictionary-chip-add');
  if (add?.dataset.term) {
    handleAddDictionaryTerm(add.dataset.term);
  }
});

document.getElementById('recordingsList')?.addEventListener('click', (event) => {
  const retry = event.target.closest('.recording-retry');
  if (retry?.dataset.recId) {
    handleRetranscribeRecording(retry.dataset.recId);
    return;
  }
  const discard = event.target.closest('.recording-discard');
  if (discard?.dataset.recId) {
    handleDiscardRecording(discard.dataset.recId);
  }
});

document.getElementById('jobsList')?.addEventListener('click', (event) => {
  const cancel = event.target.closest('.job-cancel');
  if (cancel?.dataset.jobId) {
    handleCancelJob(cancel.dataset.jobId);
  }
});

document.getElementById('clearRecordingsButton')?.addEventListener('click', async () => {
  if (!window.confirm('Delete all saved recordings? This cannot be undone.')) return;
  try {
    await clearRecordings();
    await refreshRecordings();
    showToast('All recordings cleared.', 'success');
  } catch (error) {
    showToast(`Clear failed: ${error.message}`, 'danger');
  }
});

profileSelectEl?.addEventListener('change', async () => {
  try {
    const payload = await fetchProfile(profileSelectEl.value);
    renderProfileSettings(payload.settings ?? {});
    await refreshAudioInputDevices().catch(() => {});
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
    if (payload.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
      window.betterFingers.updateHotkeys(payload.settings);
    }
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

  if (validationErrors.size > 0) {
    setMessage(profileMessageEl, 'Cannot save settings: please fix validation errors first.', 'danger');
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
  const nameError = validateProfileName(name);
  if (nameError) {
    setMessage(profileMessageEl, nameError, 'danger');
    return;
  }

  if (validationErrors.size > 0) {
    setMessage(profileMessageEl, 'Cannot create profile: please fix validation errors first.', 'danger');
    return;
  }

  try {
    const payload = await createProfile(name, collectProfileSettings());
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.profile);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `Created ${payload.profile}. Activate it when ready.`, 'success');
    newProfileNameEl.value = '';
  } catch (error) {
    setMessage(profileMessageEl, `Create failed: ${error.message}`, 'danger');
  }
});

renameProfileButton?.addEventListener('click', async () => {
  const oldName = profileSelectEl?.value;
  const newName = newProfileNameEl?.value?.trim();
  if (!oldName) {
    setMessage(profileMessageEl, 'Select a profile first.', 'warning');
    return;
  }
  if (oldName === 'Default') {
    setMessage(profileMessageEl, 'Default profile cannot be renamed.', 'warning');
    return;
  }
  const nameError = validateProfileName(newName);
  if (nameError) {
    setMessage(profileMessageEl, nameError, 'danger');
    return;
  }
  try {
    const payload = await renameProfile(oldName, newName);
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `Renamed profile to ${payload.active_profile}.`, 'success');
    newProfileNameEl.value = '';
  } catch (error) {
    setMessage(profileMessageEl, `Rename failed: ${error.message}`, 'danger');
  }
});

duplicateProfileButton?.addEventListener('click', async () => {
  const oldName = profileSelectEl?.value;
  const newName = newProfileNameEl?.value?.trim();
  if (!oldName) {
    setMessage(profileMessageEl, 'Select a profile first.', 'warning');
    return;
  }
  const nameError = validateProfileName(newName);
  if (nameError) {
    setMessage(profileMessageEl, nameError, 'danger');
    return;
  }
  try {
    const payload = await duplicateProfile(oldName, newName);
    fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
    renderProfileSettings(payload.settings ?? {});
    setMessage(profileMessageEl, `Duplicated profile as ${payload.active_profile}.`, 'success');
    newProfileNameEl.value = '';
  } catch (error) {
    setMessage(profileMessageEl, `Duplicate failed: ${error.message}`, 'danger');
  }
});

exportProfileButton?.addEventListener('click', async () => {
  const name = profileSelectEl?.value;
  if (!name) return;
  try {
    const data = await exportProfile(name);
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${name}_profile.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    setMessage(profileMessageEl, `Exported profile ${name} successfully.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Export failed: ${error.message}`, 'danger');
  }
});

const importProfileFileEl = document.getElementById('importProfileFile');
importProfileFileEl?.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;

  const reader = new FileReader();
  reader.onload = async (event) => {
    try {
      let parsed = JSON.parse(event.target.result);
      
      // Gracefully upgrade legacy flat or un-versioned profile structures
      if (!parsed || parsed.kind !== 'betterfingers_profile') {
        const settings = parsed.settings || parsed;
        const profileName = parsed.name || file.name.replace('_profile.json', '').replace('.json', '');
        parsed = {
          kind: 'betterfingers_profile',
          schema_version: 1,
          name: profileName,
          settings: settings
        };
      }

      if (parsed.schema_version !== 1) {
        throw new Error(`Unsupported profile schema version: ${parsed.schema_version}`);
      }

      const nameError = validateProfileName(parsed.name);
      if (nameError) {
        throw new Error(`Invalid imported profile name: ${nameError}`);
      }

      const payload = await importProfile(parsed);
      fillSelect(profileSelectEl, payload.profiles ?? [], payload.active_profile);
      renderProfileSettings(payload.settings ?? {});
      if (payload.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
        window.betterFingers.updateHotkeys(payload.settings);
      }
      setMessage(profileMessageEl, `Imported profile ${payload.active_profile} successfully.`, 'success');
    } catch (error) {
      setMessage(profileMessageEl, `Import failed: ${error.message}`, 'danger');
    }
    importProfileFileEl.value = '';
  };
  reader.readAsText(file);
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
    if (payload.settings && typeof window !== 'undefined' && window.betterFingers?.updateHotkeys) {
      window.betterFingers.updateHotkeys(payload.settings);
    }
    await Promise.all([refreshRuntime(), refreshOutputSettings()]);
    setMessage(profileMessageEl, `Deleted ${name}.`, 'success');
  } catch (error) {
    setMessage(profileMessageEl, `Delete failed: ${error.message}`, 'danger');
  }
});

refreshModelsButton?.addEventListener('click', () => {
  refreshModels().catch((error) => setMessage(modelMessageEl, `Refresh failed: ${error.message}`, 'danger'));
});

llmModelSelectEl?.addEventListener('change', () => {
  renderModelPanels();
});

whisperModelSelectEl?.addEventListener('change', () => {
  renderModelPanels();
});

selectLlmModelButton?.addEventListener('click', () => {
  const modelId = llmModelSelectEl?.value;
  runModelAction(selectLlmModelButton, 'Select LLM', () => selectLlmModel(modelId));
});

downloadLlmModelButton?.addEventListener('click', () => {
  runLlmDownloadAction();
});

deleteLlmModelButton?.addEventListener('click', () => {
  const modelId = llmModelSelectEl?.value;
  if (!modelId || !window.confirm(`Delete the downloaded LLM model "${modelId}"? You can re-download it later.`)) return;
  runModelAction(deleteLlmModelButton, 'Delete LLM', () => deleteLlmModel(modelId, undefined, { confirmed: true }));
});

selectWhisperModelButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  runModelAction(selectWhisperModelButton, 'Select Whisper', () => selectWhisperModel(modelSize));
});

downloadWhisperButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  runModelAction(downloadWhisperButton, 'Download Whisper', () => downloadWhisperModel(modelSize));
});

deleteWhisperButton?.addEventListener('click', () => {
  const modelSize = whisperModelSelectEl?.value;
  if (!modelSize || !window.confirm(`Delete the downloaded Whisper model "${modelSize}"? You can re-download it later.`)) return;
  runModelAction(deleteWhisperButton, 'Delete Whisper', () => deleteWhisperModel(modelSize, undefined, { confirmed: true }));
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

provisionVoiceCloningButton?.addEventListener('click', () => {
  // runModelAction sets modelMessage from result.message (ok=false → danger),
  // so the honest "not published yet" / platform-unsupported message surfaces
  // cleanly. The response carries fresh `cloning` availability → re-render.
  installVoiceCloning();
});

saveDraftEditButton?.addEventListener('click', () => drafts.handleSaveDraftEditClick());

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

draftFinalTextEl?.addEventListener('input', () => drafts.handleDraftTextInput());

copyDraftButton?.addEventListener('click', () => drafts.handleCopyClick());

acceptDraftButton?.addEventListener('click', () => drafts.handleAcceptClick());

declineDraftButton?.addEventListener('click', () => drafts.handleDeclineClick());

document.getElementById('historySearchInput')?.addEventListener('input', (event) => {
  handleHistorySearch(event.target.value);
});

clearDraftHistoryButton?.addEventListener('click', () => drafts.handleClearHistoryClick());

retryDraftButton?.addEventListener('click', () => drafts.handleRetryClick());

sendDraftButton?.addEventListener('click', () => drafts.handleSendClick());

document.addEventListener('keydown', (event) => drafts.handleGlobalShortcut(event));

// Tab switching logic
const tabButtons = document.querySelectorAll('.tab-button');
const tabContents = document.querySelectorAll('.tab-content');

function activateTab(button, { focus = false } = {}) {
  const targetTab = button.dataset.tab;

  tabButtons.forEach((btn) => {
    const isActive = btn === button;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    // Roving tabindex: only the active tab is in the Tab order.
    btn.tabIndex = isActive ? 0 : -1;
  });

  tabContents.forEach((content) => {
    content.classList.toggle(
      'active',
      content.id === `tab${targetTab.charAt(0).toUpperCase() + targetTab.slice(1)}`,
    );
  });

  if (focus) {
    button.focus();
  }

  if (targetTab === 'diagnostics') {
    refreshDiagnostics().catch(() => {});
    refreshDoctor().catch(() => {});
  }
}

tabButtons.forEach((button, index) => {
  button.addEventListener('click', () => activateTab(button));

  // Arrow-key navigation per the ARIA tabs pattern.
  button.addEventListener('keydown', (event) => {
    let nextIndex = null;
    if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabButtons.length;
    else if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabButtons.length) % tabButtons.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabButtons.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    activateTab(tabButtons[nextIndex], { focus: true });
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
      { id: 'platform', name: 'Platform Capabilities', data: doctor.platform },
      { id: 'hardware', name: 'Hardware & Model Fit', data: { hardware: doctor.hardware, fit: doctor.model_fit, tier: doctor.hardware_tier } }
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
        // The llama-server binary can exist yet be too old to run the selected
        // model (runtime_compatible === false). That's a permanent block, not a
        // transient "Warming Up" — surface it honestly.
        const runtimeIncompatible = sub.data.llama_server_exists && sub.data.runtime_compatible === false;
        if (isReady) {
          badge.textContent = 'Ready';
          badge.dataset.tone = 'success';
        } else if (runtimeIncompatible) {
          badge.textContent = 'Runtime outdated';
          badge.dataset.tone = 'warning';
        } else if (isInit) {
          badge.textContent = 'Warming Up';
          badge.dataset.tone = 'warning';
        } else {
          badge.textContent = 'Offline';
          badge.dataset.tone = 'danger';
        }
        detailsText = `Initialized: ${isInit ? 'Yes' : 'No'}\nReady: ${isReady ? 'Yes' : 'No'}\nSelected Model: ${sub.data.model_id ?? 'None'}\nllama-server: ${sub.data.llama_server_exists ? 'Found' : 'Missing'}`;
        if (runtimeIncompatible) {
          const needBuild = sub.data.required_runtime_build;
          const haveBuild = sub.data.runtime_build;
          detailsText += `\nRuntime: outdated (have build ${haveBuild ?? '?'}, need ${needBuild ?? '?'}+)`;
          recoveryTriggers.push('outdated_runtime');
        }
        if (!sub.data.llama_server_exists) {
          recoveryTriggers.push('missing_llama_server');
        }
        // Only prompt to download the model when the runtime is actually usable —
        // otherwise "download the model" misdiagnoses a runtime problem.
        if (!isInit && sub.data.llama_server_exists && !runtimeIncompatible && !sub.data.model_exists) {
          recoveryTriggers.push('missing_model');
        }
      } else if (sub.id === 'tts') {
        const isLoaded = sub.data.loaded;
        const isInit = sub.data.initialized;
        badge.textContent = isLoaded ? 'Active' : isInit ? 'Offline' : 'Error';
        badge.dataset.tone = isLoaded ? 'success' : isInit ? 'warning' : 'danger';
        detailsText = `Provider: ${sub.data.backend}\nLoaded: ${isLoaded ? 'Yes' : 'No'}\nStatus: ${sub.data.status_message}\nFallback Active: ${sub.data.fallback ? 'Yes' : 'No'}`;
        if (sub.data.backend === 'none' && sub.data.status_message !== 'TTS is not loaded.') {
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
      } else if (sub.id === 'hardware') {
        const hw = sub.data.hardware ?? {};
        const fit = sub.data.fit ?? {};
        const verdict = fit.verdict ?? 'unknown';
        const verdictMap = {
          good: { label: 'Good Fit', tone: 'success' },
          tight: { label: 'Tight', tone: 'warning' },
          insufficient: { label: 'Insufficient', tone: 'danger' },
          unknown: { label: 'Unknown', tone: 'warning' }
        };
        const v = verdictMap[verdict] ?? verdictMap.unknown;
        badge.textContent = v.label;
        badge.dataset.tone = v.tone;

        if (!hw.available) {
          detailsText = hw.error ?? 'Hardware metrics unavailable.';
        } else {
          const cpu = hw.cpu ?? {};
          const mem = hw.memory ?? {};
          const swap = hw.swap ?? {};
          const gpu = hw.gpu ?? {};
          const gb = (mb) => (typeof mb === 'number' ? `${(mb / 1024).toFixed(1)} GB` : '—');
          const gpuText = gpu.accelerated
            ? `${gpu.name ?? 'GPU'} (${gb(gpu.vram_mb)} VRAM)`
            : `${gpu.name ?? 'None'} — CPU-only`;
          const tier = sub.data.tier ?? {};
          const lines = [
            tier.label ? `Tier: ${tier.label} [${tier.tier}]` : '',
            tier.guidance ? tier.guidance : '',
            ...(Array.isArray(tier.warnings) ? tier.warnings.map((w) => `⚠ ${w}`) : []),
            tier.label ? '' : '',
            `CPU: ${cpu.model ?? 'Unknown'} (${cpu.physical_cores ?? '?'}c / ${cpu.logical_threads ?? '?'}t)`,
            `RAM: ${gb(mem.available_mb)} free of ${gb(mem.total_mb)} (${mem.used_percent ?? '?'}% used)`,
            `Swap: ${gb(swap.used_mb)} / ${gb(swap.total_mb)} used`,
            `GPU: ${gpuText}`,
            ``,
            `Model: ${fit.model_name ?? '—'}`,
            `Needs ~${gb(fit.estimated_runtime_mb)} RAM`,
            fit.recommendation ? `\n${fit.recommendation}` : ''
          ];
          if (Array.isArray(fit.reasons) && fit.reasons.length) {
            lines.push('', ...fit.reasons.map((r) => `• ${r}`));
          }
          detailsText = lines.join('\n');
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
        // Client-side recovery guidance for triggers the backend doesn't supply
        // text for (e.g. an outdated llama-server runtime).
        const clientRecovery = {
          outdated_runtime: 'Your llama-server binary is too old to run the selected model. Update llama-server (Models screen → re-run the runtime setup, or rebuild it) to a build that meets the model\'s minimum.',
        };
        for (const trigger of uniqueTriggers) {
          const recommendation = doctor.recovery[trigger] ?? clientRecovery[trigger];
          if (recommendation) {
            const item = document.createElement('div');
            item.className = 'recovery-item';

            const labelMap = {
              missing_model: 'Model Download Needed',
              missing_llama_server: 'llama-server Required',
              outdated_runtime: 'Runtime Update Needed',
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
      const errSpan = document.createElement('span');
      errSpan.className = 'empty-state';
      errSpan.dataset.tone = 'danger';
      errSpan.textContent = `Doctor check failed: ${error.message}. Is the backend running?`;
      doctorCardsGrid.replaceChildren(errSpan);
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
  runtime.teardown();
});

// Step 7: single async entry point (see the composition-root header comment
// above the imports for the full startup sequence this kicks off).
bootstrap().catch((error) => {
  setBadgeState(backendStatusEl, 'offline', 'danger');
  if (backendDetailEl) {
    backendDetailEl.textContent = error.message;
  }
  setBadgeState(transcriberStatusEl, 'offline', 'danger');
  setBadgeState(llmStatusEl, 'offline', 'danger');
});

// Floating-overlay appearance controls. These talk directly to the Electron main
// process (window.betterFingers.*OverlayAppearance) and persist there, so they
// work without the Python profile round-trip. In a plain browser (no Electron
// bridge) the whole group is hidden.
function initOverlayAppearanceControls() {
  const bridge = window.betterFingers;
  const group = document.getElementById('overlayAppearanceGroup');
  if (!bridge?.getOverlayAppearance || !bridge?.setOverlayAppearance) {
    if (group) group.style.display = 'none';
    return;
  }
  const sizeEl = document.getElementById('settingOverlaySize');
  const placeEl = document.getElementById('settingOverlayPlacement');
  const opacityEl = document.getElementById('settingOverlayOpacity');
  const opacityValEl = document.getElementById('overlayOpacityValue');
  const vibEl = document.getElementById('settingOverlayVibrancy');
  const vibValEl = document.getElementById('overlayVibrancyValue');
  const labelPosEl = document.getElementById('settingOverlayLabelPos');
  const alwaysOnEl = document.getElementById('settingOverlayAlwaysOn');
  if (!sizeEl || !placeEl || !opacityEl || !vibEl || !labelPosEl || !alwaysOnEl) return;

  const pct = (v) => `${Math.round(Number(v) * 100)}%`;

  bridge.getOverlayAppearance().then((a) => {
    if (!a) return;
    sizeEl.value = a.size ?? 'medium';
    placeEl.value = a.placement ?? 'bottom-right';
    opacityEl.value = String(a.opacity ?? 1);
    if (opacityValEl) opacityValEl.textContent = pct(a.opacity ?? 1);
    vibEl.value = String(a.vibrancy ?? 1);
    if (vibValEl) vibValEl.textContent = pct(a.vibrancy ?? 1);
    labelPosEl.value = a.labelPos ?? 'hidden';
    alwaysOnEl.checked = Boolean(a.alwaysOn);
  }).catch(() => {});

  const push = (patch) => { bridge.setOverlayAppearance(patch).catch(() => {}); };
  sizeEl.addEventListener('change', () => push({ size: sizeEl.value }));
  placeEl.addEventListener('change', () => push({ placement: placeEl.value }));
  opacityEl.addEventListener('input', () => { if (opacityValEl) opacityValEl.textContent = pct(opacityEl.value); });
  opacityEl.addEventListener('change', () => push({ opacity: Number(opacityEl.value) }));
  vibEl.addEventListener('input', () => { if (vibValEl) vibValEl.textContent = pct(vibEl.value); });
  vibEl.addEventListener('change', () => push({ vibrancy: Number(vibEl.value) }));
  labelPosEl.addEventListener('change', () => push({ labelPos: labelPosEl.value }));
  alwaysOnEl.addEventListener('change', () => push({ alwaysOn: alwaysOnEl.checked }));
}

initOverlayAppearanceControls();
