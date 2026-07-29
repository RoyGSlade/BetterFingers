// The "cold boot" backend state: every route app/src/renderer/main.js's
// bootstrap() -> loadInitialData() hits on a fresh launch, stubbed with the
// same shape server.py's real handlers return on a pristine profile (no
// models loaded, no drafts, no history). Shapes copied directly from the
// route handlers in server.py / routes_user_config.py / routes_models_resources.py
// / routes_wake.py -- not guessed. Scenario files spread this and override
// only what they need to change (e.g. `{...coldBoot(), 'GET /wake/status': {...}}`).
//
// Keep this in sync as those handlers change -- the D5 handshake posts to
// each owning session exist specifically to catch drift here.

import { createRequire } from 'node:module';

// The app's real version, not a literal. Wave 11 centralized the release
// version on one source (D-0008); this fixture had been pinned to the retired
// `0.1.0`, so the moment the version became real the version-mismatch banner
// fired on EVERY production scenario -- a stale fixture accusing a correct
// product. Deriving it here means the healthy case stays healthy for free,
// and a scenario that wants a disagreement states one explicitly.
const APP_VERSION = createRequire(import.meta.url)('../../../../package.json').version;

// Shared by `GET /settings/profiles` (the list, which carries the active
// profile's settings inline) and `GET /settings/profiles/Default` (the
// per-profile read). One object rather than two copies so the two routes cannot
// drift into disagreeing about the same profile -- which the Settings panel
// would render as a profile whose fields do not match the one it thinks is
// selected.
const DEFAULT_PROFILE_SETTINGS = {
  hotkey: 'f8',
  force_stop_key: '',
  manual_send_hotkey: 'f9',
  recording_mode: 'toggle',
  send_mode: 'review_first',
  confidence_force_review_enabled: true,
  confidence_force_review_below: 0.55,
  confidence_auto_send_above: 0.85,
  auto_stop_after_silence_enabled: false,
  auto_stop_silence_ms: 900,
  auto_stop_min_recording_ms: 700,
  max_completion_tokens: 1600,
  long_draft_warning_words: 1200,
  long_recording_stitch_pass_enabled: true,
  llm_chunk_size: 750,
  whisper_chunk_size: 1000,
  review_tts_enabled: true,
  review_tts_hotkey: 'ctrl+shift+space',
  review_tts_speed: 1.5,
  review_tts_voice_hint: 'english',
  no_audio_min_duration_sec: 0.3,
  no_audio_min_rms: 0.003,
  no_audio_min_peak: 0.015,
  auto_submit: false,
  instant_typing: false,
  restore_clipboard_after_paste: true,
  voice_commands_enabled: true,
  macros_enabled: true,
  input_device_index: -1,
  audio_ducking: false,
  status_indicator_enabled: true,
  notification_overlay_enabled: true,
  preview_overlay_enabled: true,
  model_keep_llm_loaded: false,
  model_keep_stt_loaded: false,
  model_keep_tts_loaded: false,
  wake_word_enabled: false,
  wake_word_model: '',
  wake_word_sensitivity: 0.55,
  wake_word_cooldown_s: 2.5,
  wake_word_max_recording_s: 60,
};

// One built-in persona in the schema v2 shape `llm_engine.default_persona()`
// returns. Only the fields the renderer actually reads are spelled out; the
// point is a well-formed persona object, not a byte-copy of the backend's
// defaults.
const BUILTIN_PERSONA = {
  prompt: 'You are a verbatim text cleaning machine.',
  temperature: null,
  few_shot: [],
  voice: {
    preset: '', base: '', blend: {}, speed: 1.0, pitch: 0.0,
    energy: 0.5, warmth: 0.0, brightness: 0.0, pause_style: 'natural', stability: 0.5,
  },
  format: { caps: 'none', punctuation: true, signoff: '' },
  dictionary_scope: 'global',
  model_hint: '',
  output_policy: 'preserve',
  safety_mode: 'strict',
  max_completion_tokens: null,
  chunk_size: null,
};

export function coldBoot() {
  return {
    'GET /health': {
      status: 'active',
      transcriber: false,
      llm_engine: false,
      active_job_count: 0,
      active_jobs: [],
      last_progress_at: null,
      runtime_leases: {},
    },
    'GET /runtime/version': {
      backend_version: APP_VERSION,
      expected_electron_api_version: APP_VERSION,
      schema_version: 1,
      config_version: 1,
    },
    'GET /runtime/status': {
      transcriber_initialized: false,
      llm_initialized: false,
      hotkey_manager_started: true,
      hotkey_keyboard_hooks_ok: true,
      hotkey_keyboard_hook_errors: [],
      recording_active: false,
      transcriber_loaded: false,
      llm_ready: false,
    },
    'GET /capabilities': {
      platform: 'linux',
      session_type: 'x11',
      is_windows: false,
      is_linux: true,
      is_wayland: false,
      is_x11: true,
      supports_basic_clipboard: true,
      supports_rich_clipboard_restore: true,
      supports_input_injection: true,
      supports_global_hotkeys: true,
      supports_audio_ducking: true,
      supports_stt: true,
      supports_llm: true,
      supports_tts: true,
      injection_method: 'xdotool',
      supports_typing: true,
      clipboard_backend: 'xclip',
      injection_hint: '',
    },
    'GET /drafts': { drafts: [] },
    'GET /drafts/latest': { draft: null },

    // --- Wave 12: routes the walkbook was photographing as 404s --------------
    //
    // These eight were missing from the stub, so on every production-target
    // scenario the composition root's cold-start population hit them, failed,
    // and (correctly, after this wave's resilient-loading work) reported the
    // failure to the user. The result was a walkbook whose screenshots showed
    // a stack of honest error toasts over a partly-404 backend -- an accurate
    // photograph of the stub, and a misleading one of the product. A walkbook
    // is read as "this is what a healthy cold start looks like", so the stub
    // has to be healthy.
    //
    // Shapes copied from the real handlers, per this file's standing rule --
    // NOT guessed:
    //   backend/api/routes/app_context.py  (app_context_status_route,
    //                                       app_context_profiles_route)
    //   backend/api/routes/contacts.py     (list_contacts_route,
    //                                       get_active_contact_route)
    //   backend/api/routes/actions.py      (list_workflows_route,
    //                                       workflow_history_route)
    //   server.py                          (settings_profile)
    //
    // Values are the pristine-profile case that matches the rest of this
    // fixture: nothing configured yet, but every envelope well-formed, so a
    // panel renders its honest EMPTY state rather than its error state.
    'GET /app-context/status': { ok: true, context: null },
    'GET /app-context/profiles': {
      ok: true,
      profiles: [],
      builtin_ids: [],
      pinned: {},
      performance_presets: [],
      injection_policies: [],
      gaming_policy: {},
    },
    'GET /contacts': { ok: true, contacts: [] },
    // A dangling/absent selection reports as "nobody in particular", which the
    // handler treats as a first-class state rather than a missing value.
    'GET /contacts/active': { ok: true, contact_id: null, contact: null },
    'GET /workflows': { ok: true, workflows: [] },
    'GET /workflows/history': { ok: true, history: [] },
    // The per-profile read. `active: true` because 'GET /settings/profiles'
    // above reports Default as the active one -- the two must agree or the
    // Settings panel renders a profile it does not believe is selected.
    'GET /settings/profiles/Default': {
      profile: 'Default',
      active: true,
      settings: DEFAULT_PROFILE_SETTINGS,
    },
    'GET /runtime/output-settings': {
      send_mode: 'review_first',
      auto_submit: false,
      pending_manual_send_ids: [],
      supported_actions: ['copy_only', 'paste', 'type', 'open_chat_then_send'],
      capabilities: { supports_input_injection: true },
    },
    'GET /settings/profiles': {
      active_profile: 'Default',
      profiles: ['Default'],
      settings: DEFAULT_PROFILE_SETTINGS,
    },
    'GET /models/llm': {
      selected_model_id: 'gemma-4-e2b-q4',
      models: [
        {
          id: 'gemma-4-e2b-q4',
          selected: true,
          installed: false,
          ready: false,
          name: 'Gemma 4 E2B (Q4_K_M)',
          download_state: { status: 'not_started' },
          download_active: false,
        },
      ],
      download_state: { status: 'not_started' },
      llama_server_path: '/tmp/llama-server',
      llama_server_exists: false,
    },
    'GET /models/whisper': {
      selected_model_size: 'base.en',
      supported: ['tiny.en', 'base.en', 'small.en'],
      models: [],
      download_state: { status: 'not_started' },
    },
    'GET /models/resources': { ok: true, components: [], total_estimated_mb: 0, available_mb: 8192 },
    'GET /diagnostics/logs': { path: '/tmp/qa-harness-data/debug.log', exists: true, lines: [] },
    'GET /runtime/errors': { errors: [] },
    'GET /diagnostics/paths': { user_data_path: '/tmp/qa-harness-data', models_dir: '/tmp/qa-harness-data/models' },
    'GET /doctor': {
      health: 'active',
      stt: { initialized: false, loaded: false, model_size: null, device: null },
      llm: {
        initialized: false,
        ready: false,
        model_id: 'gemma-4-e2b-q4',
        llama_server_path: '/tmp/llama-server',
        llama_server_exists: false,
        model_exists: false,
        runtime_status: 'missing_llama_server',
        runtime_valid: false,
        runtime_compatible: false,
        runtime_build: null,
        required_runtime_build: null,
        runtime_message: 'llama-server binary is missing.',
        last_error: '',
        last_error_details: {},
      },
      tts: { initialized: false, loaded: false, backend: 'none', status_message: 'TTS is not initialized.', fallback: false },
      hotkeys: { started: true, active: true, keyboard_hooks_ok: true, keyboard_hook_errors: [] },
      models: { models_dir: '/tmp/qa-harness-data/models', models_dir_exists: true, default_model_path: '/tmp/x.gguf', default_model_exists: false },
      audio: { devices: [], default_input_device: -1, default_output_device: -1, error: null },
      platform: { platform: 'linux', session_type: 'x11', is_linux: true, is_windows: false },
      hardware: { memory: { total_mb: 16384 }, cpu: { cores: 8 }, gpu: null },
      hardware_tier: { tier: 'mid', label: 'Standard', guidance: '' },
      model_fit: { fits: true, message: 'Fits comfortably.' },
      recovery: {},
    },
    'GET /runtime/audio-devices': { devices: [], default_input_device: -1, default_output_device: -1, error: null },
    // `{}` here was the FAILURE shape, not a healthy empty state.
    //
    // bootstrap/signalDeskApp.js's loadPersonaList() treats an empty or
    // non-object payload as a failed request on purpose, and its doc comment
    // explains why: llm_engine.load_personas_v2() falls back to
    // _DEFAULT_PERSONAS whenever personas.yaml is missing, empty or corrupt, so
    // a healthy backend ALWAYS answers with at least the built-ins. An empty
    // map can therefore only mean the request failed.
    //
    // So the stub was handing every scenario the one response that means
    // "broken", and the walkbook photographed the resulting honest warnings
    // ("Could not load the persona list", "Could not refresh Studio personas")
    // as though they were the product's normal cold start. Two built-ins,
    // shaped like llm_engine.default_persona()'s schema v2 dict, are what a
    // real pristine install returns. Scenarios that need particular personas
    // already override this key and are unaffected.
    'GET /personas': {
      'True Janitor': BUILTIN_PERSONA,
      Formal: BUILTIN_PERSONA,
    },
    'GET /personas-builtins': { builtins: ['True Janitor', 'Formal'] },
    'GET /tts/voices': { voices: [], cloned: [] },
    'GET /voice-presets': { presets: [] },
    'GET /recordings': { ok: true, recordings: [] },
    // Wave 4: the production Library workspace loads from /library/search on
    // boot (backend-driven filtering + pagination, WAVE3_LIBRARY_CONTRACT §5).
    // Without this every signal-desk-prod scenario would boot straight into
    // Library's error state -- which is a real state worth testing, but not
    // one a cold boot should be forced into.
    'GET /library/search': { ok: true, results: [], total: 0, limit: 25, offset: 0 },
    'GET /jobs': { ok: true, jobs: [], runtime_leases: {} },
    'GET /metrics': {},
    'GET /macros': { ok: true, macros: [] },
    'GET /dictionary': { ok: true, terms: [] },
    'GET /privacy': {
      offline_by_default: true,
      network_touchpoints: [],
      data_locations: [],
      data_directories: [],
      retention: { recordings_persisted_to_disk: true, recordings_in_memory: 0, drafts_in_memory: 0, draft_history_limit: 80 },
      wake_listener: { active: false, persists_audio: false, note: 'Disabled.' },
    },
    'GET /wake/status': { enabled: false, available: false, listening: false, reason: 'disabled' },
    'GET /wake/models': {
      models: [
        { id: 'melspectrogram', name: 'Melspectrogram feature extractor', kind: 'backbone', license: 'Apache-2.0', origin: 'bundled', size_bytes: 1087958, downloaded: false },
        { id: 'embedding_model', name: 'Speech embedding model', kind: 'backbone', license: 'Apache-2.0', origin: 'bundled', size_bytes: 1326578, downloaded: false },
      ],
    },
    'GET /hardware/tier': { ok: true, tier: { tier: 'mid', label: 'Standard', guidance: '' } },
    'GET /models/recommend': { ok: true, recommendation: { model_id: 'gemma-4-e2b-q4', tier_label: 'Standard', tier_guidance: '' } },
  };
}

/**
 * cold-boot with every model installed and ready.
 *
 * Added when the first-run banner landed in Talk (stage 13 §4b). The banner is
 * live status, so on cold-boot state it correctly appears and pushes the
 * workspace down -- which broke a Talk scenario that measures where the Decline
 * button sits.
 *
 * The fix is the state, not the assertion. A scenario about editing a
 * transcribed draft was running on a profile with no Whisper model installed,
 * which could not have produced that draft in the first place. Any scenario
 * whose subject presupposes a working install should spread this instead.
 */
export function readyProfile() {
  const state = coldBoot();
  return {
    ...state,
    'GET /health': { ...state['GET /health'], transcriber: true, llm_engine: true },
    'GET /runtime/status': {
      ...state['GET /runtime/status'],
      transcriber_initialized: true,
      llm_initialized: true,
      transcriber_loaded: true,
      llm_ready: true,
    },
    'GET /models/llm': {
      ...state['GET /models/llm'],
      models: [{ ...state['GET /models/llm'].models[0], installed: true, ready: true }],
      llama_server_exists: true,
    },
    'GET /models/whisper': {
      ...state['GET /models/whisper'],
      models: [{ model_size: 'base.en', installed: true }],
    },
  };
}
