// Voice Studio: base voice, blend, and modulation controls, extracted from
// main.js (side-track: voice blending UI redesign + canonical TTS voice sync).
//
// The bug this closes: base voice, blend, and modulation used to live only in
// ephemeral DOM/JS state. The two preview paths (Audition button, drafts.js
// "Read aloud") always read that live state, so they looked correct. But the
// *canonical* automatic playback path (server.py speak_text_aloud, behind the
// Review TTS hotkey and voice-command read-back) reads the saved profile —
// and blend/modulation were never part of the profile schema at all, so they
// silently reset to nothing on every reload and never reached that path.
//
// Fix: every control here now marks the profile dirty like the rest of the
// settings panel (hooks.markProfileDirty), and this module exposes
// getPersistableState()/restoreFromProfile() so main.js's
// collectProfileSettings()/renderProfileSettings() carry the full voice
// (base + speed + blend + modulation) through the existing save/reload
// boundary — the same one every other setting already uses. No new
// persistence mechanism, no separate "active voice" pointer to go stale.
//
// Pure helpers (no DOM) are exported for unit testing, matching this repo's
// convention (see messageRescuePanel.js) of testing DOM-driven features via
// plain data in/out rather than jsdom. createVoiceStudioFeature()'s init()
// accepts an optional `doc` for the same reason; its network calls
// (fetchTtsVoices/etc.) are similarly injectable via an `api` override so
// refreshVoices()/preset actions are testable without a real backend.
import * as backendApi from '../api/backend.js';
import { assessTtsCompatibility } from '../lib/modelCompat.mjs';
import { isAlphaCapabilityEnabled } from '../config/alphaCapabilities.js';

export const MAX_BLEND_LAYERS = 3; // base + 3 extra = 4-way alpha cap

export const VOICE_BLEND_QUICK_PRESETS = {
  softer: { blend: { bf_emma: 0.25 }, energy: 0.35, warmth: 0.3 },
  brighter: { blend: { af_nicole: 0.3 }, brightness: 0.35 },
  lower: { blend: { am_michael: 0.3 }, pitch: -3 },
  narrator: { base: 'bm_george', blend: {}, energy: 0.45, pause_style: 'natural' },
  assistant: { base: 'af_heart', blend: {}, energy: 0.55, brightness: 0.1 },
};

export const VOICE_MODULATION_QUICK_PRESETS = {
  clear: { speed: 1.0, pitch: 0, energy: 0.6, warmth: 0.1, brightness: 0.1, pause_style: 'natural' },
  quiet: { speed: 0.9, pitch: 0, energy: 0.3, warmth: 0.2, brightness: 0, pause_style: 'compact' },
  presentation: { speed: 0.95, pitch: 0, energy: 0.7, warmth: 0.1, brightness: 0.2, pause_style: 'dramatic' },
  character: { speed: 1.0, pitch: 3, energy: 0.8, warmth: 0.3, brightness: 0.1, pause_style: 'dramatic' },
  fast: { speed: 1.8, pitch: 0, energy: 0.5, warmth: 0, brightness: 0, pause_style: 'compact' },
  accessibility: { speed: 0.75, pitch: 0, energy: 0.5, warmth: 0, brightness: 0, pause_style: 'natural' },
};

const PAUSE_STYLES = new Set(['natural', 'compact', 'dramatic']);

// --- Pure helpers (unit-testable without a DOM) -----------------------------

/**
 * Blend layers as edited in the UI -> the {voiceId: weight} dict the backend
 * expects. Duplicate voiceIds (two rows pointing at the same voice) collapse
 * to one entry (last one wins) instead of silently double-counting; weights
 * are clamped to [0,1] and non-finite/<=0 entries are dropped. The backend
 * (voice_blend.blend_many) normalizes weights to sum to 1 — this is just a
 * client-side safety net so nothing malformed is ever sent.
 */
export function normalizeBlendForSend(layers) {
  const map = new Map();
  for (const layer of layers || []) {
    const id = String(layer?.voiceId || '').trim();
    if (!id) continue;
    const weight = Number(layer?.weight);
    if (!Number.isFinite(weight) || weight <= 0) continue;
    map.set(id, Math.min(1, Math.max(0, weight)));
  }
  return map.size ? Object.fromEntries(map) : null;
}

export function normalizeCustomVoiceSources(baseVoiceId, layers, availableIds = null) {
  const raw = [{ voiceId: baseVoiceId, weight: 1 }, ...(layers || [])];
  const available = Array.isArray(availableIds) ? new Set(availableIds) : null;
  const seen = new Set();
  const sources = [];
  for (const item of raw) {
    const voiceId = String(item?.voiceId || '').trim();
    const key = voiceId.toLowerCase();
    if (!voiceId) continue;
    if (available && !available.has(voiceId)) throw new Error(`Source voice "${voiceId}" is no longer available.`);
    if (seen.has(key)) throw new Error(`Source voice "${voiceId}" is selected more than once.`);
    seen.add(key);
    const weight = Number(item?.weight);
    sources.push({ voice_id: voiceId, weight: Number.isFinite(weight) && weight > 0 ? weight : 1 });
  }
  if (!sources.length) throw new Error('Select at least one source voice.');
  if (sources.length > 4) throw new Error('A custom voice can use at most four source voices.');
  const total = sources.reduce((sum, source) => sum + source.weight, 0);
  let running = 0;
  return sources.map((source, index) => {
    const weight = index === sources.length - 1 ? Math.max(0, 1 - running) : Math.round((source.weight / total) * 1e8) / 1e8;
    running += weight;
    return { voice_id: source.voice_id, weight };
  });
}

export function buildCustomVoicePayload(name, settings, { availableIds = null, sourcePresetId = '', replace = false } = {}) {
  const displayName = String(name || '').trim();
  if (!displayName) throw new Error('A custom voice name is required.');
  const sources = normalizeCustomVoiceSources(settings?.base, settings?.blendLayers || [], availableIds);
  return {
    name: displayName,
    display_name: displayName,
    sources,
    source_preset_id: String(sourcePresetId || ''),
    customized: true,
    replace: Boolean(replace),
    modulation: {
      speed: settings.speed,
      pitch: settings.pitch,
      energy: settings.energy,
      warmth: settings.warmth,
      brightness: settings.brightness,
      pause_style: settings.pause_style,
    },
  };
}

/**
 * Resolves a stored/selected voice id against the currently available voice
 * ids. If it's still available, it's used as-is. Otherwise (deleted cloned
 * voice, renamed default, stale profile) falls back to `preferredFallbackId`
 * if that's available, else the first available voice, else ''. Never
 * silently leaves a selection pointing at a voice that doesn't exist.
 */
export function resolveAvailableVoiceId(selectedId, availableIds, preferredFallbackId) {
  const ids = Array.isArray(availableIds) ? availableIds : [];
  if (selectedId && ids.includes(selectedId)) {
    return { id: selectedId, fellBack: false };
  }
  const fallback = preferredFallbackId && ids.includes(preferredFallbackId) ? preferredFallbackId : (ids[0] || '');
  return { id: fallback, fellBack: Boolean(selectedId) && selectedId !== fallback };
}

/** Drops blend layers whose voiceId is no longer available. Returns the kept
 * layers plus the names that were dropped, so callers can warn the user. */
export function filterAvailableBlendLayers(layers, availableIds) {
  const ids = Array.isArray(availableIds) ? availableIds : [];
  const kept = [];
  const dropped = [];
  for (const layer of layers || []) {
    if (ids.includes(layer.voiceId)) {
      kept.push(layer);
    } else {
      dropped.push(layer.voiceId);
    }
  }
  return { layers: kept, dropped };
}

/** Effective mix after backend normalization (base always enters at weight
 * 1.0; blend_many normalizes every entry to sum to 1 — see
 * tts_engine.py:_resolve_voice_spec). Purely informational, for the UI to
 * show the user what will actually play instead of raw slider weights. */
export function computeEffectiveMix(baseLabel, layers) {
  const entries = (layers || []).filter((l) => l.voiceId && Number(l.weight) > 0);
  const total = 1 + entries.reduce((sum, l) => sum + Number(l.weight), 0);
  const parts = [{ label: baseLabel || 'base', pct: Math.round((1 / total) * 100) }];
  for (const layer of entries) {
    parts.push({ label: layer.voiceId, pct: Math.round((Number(layer.weight) / total) * 100) });
  }
  return parts;
}

/** Human-readable duration used by the user-recorded sample preview. */
export function formatVoiceSampleDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) return 'duration unavailable';
  if (value < 60) return `${value.toFixed(1)}s`;
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(Math.round(value % 60)).padStart(2, '0')}`;
}

/**
 * The clone upload is only safe once the backend has explicitly reported that
 * the clone runtime/model is available.  Do not treat a legacy `installed`
 * flag, a missing payload, or a provisioning response as proof: those values
 * do not describe whether synthesis can run right now.
 */
export function normalizeVoiceCloningAvailability(cloning) {
  if (cloning && typeof cloning.available === 'boolean') {
    return {
      known: true,
      available: cloning.available,
      message: cloning.available
        ? 'Voice cloning model is installed and ready.'
        : 'Voice cloning requires its model. Install voice cloning before uploading a sample.',
    };
  }
  return {
    known: false,
    available: false,
    message: 'Checking whether the voice-cloning model is available…',
  };
}

export function canUploadVoiceClone(cloning) {
  const status = normalizeVoiceCloningAvailability(cloning);
  return status.known && status.available;
}

/** The full "what to speak with" shape used by both preview paths (Audition,
 * drafts.js runDraftTts) and by profile persistence. */
export function gatherVoiceStudioSettingsFromInputs({ base, speed, blendLayers, pitch, energy, warmth, brightness, pauseStyle }) {
  return {
    base: base || 'standard_female',
    speed: Number.isFinite(Number(speed)) ? Number(speed) : 1.0,
    blend: normalizeBlendForSend(blendLayers),
    pitch: Number.isFinite(Number(pitch)) ? Number(pitch) : 0,
    energy: Number.isFinite(Number(energy)) ? Number(energy) : 0.5,
    warmth: Number.isFinite(Number(warmth)) ? Number(warmth) : 0,
    brightness: Number.isFinite(Number(brightness)) ? Number(brightness) : 0,
    pause_style: PAUSE_STYLES.has(pauseStyle) ? pauseStyle : 'natural',
  };
}

/** The subset of profile keys Voice Studio owns, ready to merge into a
 * saveProfile() payload alongside the rest of collectProfileSettings(). Base
 * voice + speed are NOT included here — those stay owned by settingEls'
 * generic settings loop (unchanged), same as before this module existed. */
export function buildPersistableVoiceStudioSettings({ blendLayers, pitch, energy, warmth, brightness, pauseStyle }) {
  return {
    review_tts_blend: normalizeBlendForSend(blendLayers) || {},
    review_tts_pitch: Number.isFinite(Number(pitch)) ? Number(pitch) : 0,
    review_tts_energy: Number.isFinite(Number(energy)) ? Number(energy) : 0.5,
    review_tts_warmth: Number.isFinite(Number(warmth)) ? Number(warmth) : 0,
    review_tts_brightness: Number.isFinite(Number(brightness)) ? Number(brightness) : 0,
    review_tts_pause_style: PAUSE_STYLES.has(pauseStyle) ? pauseStyle : 'natural',
  };
}

/** Inverse of buildPersistableVoiceStudioSettings: a loaded/saved profile ->
 * the in-memory blend-layer list + modulation values to restore into the UI
 * on reload. Unknown/missing fields fall back to the same defaults the
 * backend uses (utils.py _profile_defaults), so an old profile that predates
 * these keys restores to "no blend, neutral modulation" rather than crashing
 * or leaving stale UI state. */
export function extractVoiceStudioStateFromProfile(settings) {
  const blendDict = (settings && typeof settings.review_tts_blend === 'object' && settings.review_tts_blend) || {};
  const blendLayers = Object.entries(blendDict)
    .map(([voiceId, weight]) => ({ voiceId, weight: Number(weight) }))
    .filter((layer) => Number.isFinite(layer.weight) && layer.weight > 0);
  return {
    blendLayers,
    pitch: Number.isFinite(Number(settings?.review_tts_pitch)) ? Number(settings.review_tts_pitch) : 0,
    energy: Number.isFinite(Number(settings?.review_tts_energy)) ? Number(settings.review_tts_energy) : 0.5,
    warmth: Number.isFinite(Number(settings?.review_tts_warmth)) ? Number(settings.review_tts_warmth) : 0,
    brightness: Number.isFinite(Number(settings?.review_tts_brightness)) ? Number(settings.review_tts_brightness) : 0,
    pauseStyle: PAUSE_STYLES.has(settings?.review_tts_pause_style) ? settings.review_tts_pause_style : 'natural',
  };
}

// --- DOM-wiring feature -------------------------------------------------
// Everything below owns its own document.getElementById lookups (same
// pattern as personas.js's Persona Foundry) so main.js doesn't need to know
// Voice Studio's internal element ids — only the cross-cutting hooks below.

export function createVoiceStudioFeature({ ui, hooks, api } = {}) {
  const { setMessage, showToast } = ui || {};
  const { markProfileDirty, renderVoiceCloningPanel } = hooks || {};
  const {
    fetchTtsVoices, fetchVoicePresets, saveVoicePreset, deleteVoicePreset,
    setDefaultVoicePreset, clearDefaultVoicePreset, cloneVoice, speakTts, stopTts, provisionVoiceCloning,
    fetchTtsStatus, fetchProfiles, saveProfile,
  } = api || backendApi;

  let voiceOptionsCache = []; // [{id, name}]
  let voiceBlendLayers = []; // [{voiceId, weight}]
  let loadedVoicePresets = [];
  let loadedVoicePresetDefault = null;
  let playbackRun = 0;
  let playbackState = 'idle';
  let playbackText = '';
  let initialized = false;
  let voiceCloningAvailability = normalizeVoiceCloningAvailability(null);
  let ttsRuntimeStatus = null;

  function availableVoiceIds() {
    return voiceOptionsCache.map((v) => v.id);
  }

  function voiceLabel(id) {
    return voiceOptionsCache.find((v) => v.id === id)?.name || id;
  }

  function currentTtsCompatibility(voiceId = '', capability) {
    const status = ttsRuntimeStatus || {};
    const capabilities = status.capabilities || {};
    return assessTtsCompatibility({
      runtime: capabilities.runtime || status.raw_backend || status.backend,
      model: capabilities.model || capabilities.model_id || status.model || status.model_id
        || capabilities.quantization || status.kokoro_quantization,
      voiceId,
      capability,
      runtimeCapabilities: capabilities,
    });
  }

  /**
   * Runtime/model compatibility is advisory for unknown mappings, but a
   * loaded backend voice table or explicit capability refusal is authoritative
   * and must disable the unsupported option.
   */
  function renderTtsCompatibility(doc) {
    const select = doc.getElementById('settingReviewTtsVoiceHint');
    if (!select) return;
    let note = doc.getElementById('voiceModelCompatibilityNote');
    if (!note) {
      note = doc.createElement('p');
      note.id = 'voiceModelCompatibilityNote';
      note.className = 'sd-voice-studio__hint';
      select.parentNode?.appendChild?.(note);
    }
    const result = currentTtsCompatibility(select.value, voiceBlendLayers.length ? 'blend' : undefined);
    note.hidden = !result.caution;
    note.textContent = result.caution
      ? `Compatibility guidance: ${result.caution}`
      : 'Compatibility confirmed by the local guidance table.';
    note.dataset.compatibility = result.knownBad ? 'known-bad' : result.known ? 'known' : 'unknown';
  }

  function annotateVoiceOption(option, voiceId) {
    const result = currentTtsCompatibility(voiceId);
    option.disabled = !result.offered;
    if (result.caution) {
      option.title = result.caution;
      option.setAttribute('data-compatibility', result.knownBad ? 'known-bad' : 'unknown');
    }
    return option;
  }

  /**
   * Wave 12A, finding (3): one sentence naming what is actually available to
   * blend. Exported-in-spirit as a pure string builder so the unit test can
   * assert the wording without a DOM. Caps the list so a 40-voice install
   * does not produce a paragraph; the count is always exact, so a truncated
   * list still tells the truth about how many there are.
   */
  function availableVoicesSentence(limit = 6) {
    if (voiceOptionsCache.length === 0) {
      return 'No voices are loaded yet, so there is nothing to blend.';
    }
    const names = voiceOptionsCache.map((v) => v.name);
    const shown = names.slice(0, limit);
    const rest = names.length - shown.length;
    const list = rest > 0 ? `${shown.join(', ')} and ${rest} more` : shown.join(', ');
    return `No blend layers — auditioning the base voice alone. ${names.length} ${names.length === 1 ? 'voice is' : 'voices are'} available to blend: ${list}.`;
  }

  /**
   * Wave 12A, finding (3): the active voice, named in text.
   *
   * The <select> knows which voice is selected, but a closed native select on
   * a dark page reads as a slab of chrome, and the product owner reported not
   * being able to see which voice was active at all. Naming it in page text
   * beside the control answers the question without opening anything -- and is
   * assertable by QA, which a rendered <select> value is not.
   */
  function renderActiveVoiceName(doc) {
    const el = doc.getElementById('voiceActiveVoiceName');
    if (!el) return;
    const baseId = doc.getElementById('settingReviewTtsVoiceHint')?.value || '';
    el.textContent = baseId ? voiceLabel(baseId) : 'None selected';
  }

  function messageEl(doc) {
    return doc.getElementById('profileMessage');
  }

  function dirty() {
    markProfileDirty?.();
  }

  // --- Blend rows -----------------------------------------------------
  //
  // WAVE 12A CLASS NAMES. Every class emitted here used to be a LEGACY one --
  // `setting-row`, `settings-input`, `min-w-160`, `secondary-button`,
  // `setting-desc`, `voice-blend-weight-label`. Those live in
  // styles/base.css, and signal-desk.html links only styles/signal-desk.css.
  // On the production page (the default page since the Wave 11 flip) that made
  // this entire Blend surface render as raw unstyled HTML: the product owner
  // reported it as "the remove button on blend voices looks like a generic
  // html button" and "the dropdowns look like blank html". The names below are
  // the Signal Desk primitives, all defined in styles/signal-desk.css.
  function renderVoiceBlendRows(doc) {
    // The Add button's click handler already refuses past MAX_BLEND_LAYERS,
    // but nothing disabled the button itself -- a user at the cap could click
    // it forever with no feedback at all (Wave 12 collab task C). Kept ahead
    // of the container guard below so it stays in sync even on a host that
    // omits the rows container.
    const addButton = doc.getElementById('addVoiceLayerButton');
    if (addButton) {
      const atMax = voiceBlendLayers.length >= MAX_BLEND_LAYERS;
      const blendStatus = currentTtsCompatibility('', 'blend');
      const blendUnavailable = blendStatus.knownBad && !blendStatus.offered;
      addButton.disabled = atMax || blendUnavailable;
      addButton.title = atMax
        ? `Up to ${MAX_BLEND_LAYERS} extra voices can be blended with the base.`
        : blendUnavailable ? blendStatus.caution : '';
    }
    const container = doc.getElementById('voiceBlendRows');
    if (!container) return;
    container.innerHTML = '';
    if (voiceBlendLayers.length === 0) {
      const empty = doc.createElement('p');
      empty.className = 'sd-voice-studio__hint';
      // Naming the candidates is the point, not the empty state itself: before
      // this the surface said only "no layers", so the voices available to
      // blend were discoverable ONLY by adding a layer and reading the
      // dropdown. That is the UI half of the product owner's finding (3).
      empty.textContent = availableVoicesSentence();
      container.appendChild(empty);
      renderEffectiveMix(doc);
      renderTtsCompatibility(doc);
      return;
    }
    voiceBlendLayers.forEach((layer, index) => {
      const row = doc.createElement('div');
      row.className = 'sd-voice-studio__blend-row';

      const select = doc.createElement('select');
      select.className = 'sd-select';
      select.setAttribute('aria-label', `Blend voice ${index + 1}`);
      for (const voice of voiceOptionsCache) {
        const option = doc.createElement('option');
        option.value = voice.id;
        option.textContent = voice.name;
        annotateVoiceOption(option, voice.id);
        select.appendChild(option);
      }
      select.value = layer.voiceId;
      select.addEventListener('change', () => {
        const next = select.value;
        const baseId = doc.getElementById('settingReviewTtsVoiceHint')?.value || '';
        const duplicate = next === baseId || voiceBlendLayers.some((other, otherIndex) => otherIndex !== index && other.voiceId === next);
        if (duplicate) {
          select.value = voiceBlendLayers[index].voiceId;
          showToast?.('Each source voice can be selected only once.', 'warning');
          return;
        }
        voiceBlendLayers[index].voiceId = select.value;
        dirty();
        renderEffectiveMix(doc);
      });

      const weightInput = doc.createElement('input');
      weightInput.type = 'range';
      weightInput.min = '0';
      weightInput.max = '1';
      weightInput.step = '0.05';
      weightInput.value = String(layer.weight);
      weightInput.setAttribute('aria-label', `Blend voice ${index + 1} weight`);

      const weightLabel = doc.createElement('span');
      weightLabel.className = 'sd-voice-studio__blend-weight';
      weightLabel.textContent = layer.weight.toFixed(2);
      weightInput.addEventListener('input', () => {
        voiceBlendLayers[index].weight = parseFloat(weightInput.value);
        weightLabel.textContent = voiceBlendLayers[index].weight.toFixed(2);
        dirty();
        renderEffectiveMix(doc);
      });

      const removeButton = doc.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'sd-btn sd-btn--danger';
      removeButton.textContent = 'Remove';
      removeButton.setAttribute('aria-label', `Remove blend voice ${index + 1}`);
      removeButton.addEventListener('click', () => {
        voiceBlendLayers.splice(index, 1);
        dirty();
        renderVoiceBlendRows(doc);
      });

      const previewButton = doc.createElement('button');
      previewButton.type = 'button';
      previewButton.className = 'sd-btn';
      previewButton.textContent = 'Preview source';
      previewButton.addEventListener('click', async () => {
        const text = doc.getElementById('voicePreviewText')?.value?.trim() || 'This is a quick source voice preview.';
        try {
          await speakTts(text, layer.voiceId, 1.0, 0, {});
        } catch (error) {
          showToast?.(`Source preview failed: ${error.message}`, 'danger');
        }
      });

      row.appendChild(select);
      row.appendChild(weightInput);
      row.appendChild(weightLabel);
      row.appendChild(previewButton);
      row.appendChild(removeButton);
      container.appendChild(row);
    });
    renderEffectiveMix(doc);
    renderTtsCompatibility(doc);
  }

  function renderEffectiveMix(doc) {
    // The active-voice readout tracks the same state, and every caller of
    // renderEffectiveMix is a point where that state may have moved.
    renderActiveVoiceName(doc);
    const el = doc.getElementById('voiceEffectiveMix');
    if (!el) return;
    const baseSelect = doc.getElementById('settingReviewTtsVoiceHint');
    const baseId = baseSelect?.value || '';
    const parts = computeEffectiveMix(voiceLabel(baseId) || 'base', voiceBlendLayers);
    el.textContent = parts.length > 1
      ? `Effective mix: ${parts.map((p) => `${p.label} ${p.pct}%`).join(' + ')}`
      : '';
  }

  // --- Modulation -------------------------------------------------------
  function updateModulationLabels(doc) {
    const fields = [
      ['voicePitch', 'voicePitchValue', 1],
      ['voiceEnergy', 'voiceEnergyValue', 2],
      ['voiceWarmth', 'voiceWarmthValue', 2],
      ['voiceBrightness', 'voiceBrightnessValue', 2],
    ];
    for (const [inputId, labelId, decimals] of fields) {
      const input = doc.getElementById(inputId);
      const label = doc.getElementById(labelId);
      if (input && label) {
        label.textContent = parseFloat(input.value).toFixed(decimals);
      }
    }
  }

  function setModulationControls(doc, settings) {
    const map = {
      voicePitch: settings.pitch,
      voiceEnergy: settings.energy,
      voiceWarmth: settings.warmth,
      voiceBrightness: settings.brightness,
    };
    for (const [id, value] of Object.entries(map)) {
      const el = doc.getElementById(id);
      if (el && value !== undefined && value !== null) {
        el.value = value;
      }
    }
    const pauseStyleEl = doc.getElementById('voicePauseStyle');
    if (pauseStyleEl && settings.pause_style) {
      pauseStyleEl.value = settings.pause_style;
    }
    updateModulationLabels(doc);
  }

  // --- Gather / apply -----------------------------------------------------
  function gatherVoiceStudioSettings(doc) {
    const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
    if (!activeDoc) {
      return gatherVoiceStudioSettingsFromInputs({ blendLayers: voiceBlendLayers });
    }
    return gatherVoiceStudioSettingsFromInputs({
      base: activeDoc.getElementById('settingReviewTtsVoiceHint')?.value,
      speed: activeDoc.getElementById('settingReviewTtsSpeed')?.value,
      blendLayers: voiceBlendLayers,
      pitch: activeDoc.getElementById('voicePitch')?.value,
      energy: activeDoc.getElementById('voiceEnergy')?.value,
      warmth: activeDoc.getElementById('voiceWarmth')?.value,
      brightness: activeDoc.getElementById('voiceBrightness')?.value,
      pauseStyle: activeDoc.getElementById('voicePauseStyle')?.value,
    });
  }

  function applyVoiceStudioState(doc, state) {
    const baseSelect = doc.getElementById('settingReviewTtsVoiceHint');
    if (baseSelect && state.base) {
      const { id, fellBack } = resolveAvailableVoiceId(state.base, availableVoiceIds(), state.base);
      baseSelect.value = id;
      if (fellBack) {
        showToast?.(`"${state.base}" is no longer available; switched to ${voiceLabel(id) || 'the first available voice'}.`, 'warning');
      }
    }
    const speedInput = doc.getElementById('settingReviewTtsSpeed');
    if (speedInput && state.speed !== undefined) {
      speedInput.value = state.speed;
    }
    const { layers, dropped } = filterAvailableBlendLayers(
      Object.entries(state.blend || {}).map(([voiceId, weight]) => ({ voiceId, weight })),
      availableVoiceIds(),
    );
    voiceBlendLayers = layers;
    if (dropped.length) {
      showToast?.(`Dropped unavailable blend voice${dropped.length > 1 ? 's' : ''}: ${dropped.join(', ')}.`, 'warning');
    }
    renderVoiceBlendRows(doc);
    setModulationControls(doc, state);
  }

  function applyVoicePreset(doc, preset, { markDirtyAfter = true } = {}) {
    if (!preset) return;
    applyVoiceStudioState(doc, {
      base: preset.base,
      speed: preset.speed,
      blend: preset.blend || {},
      pitch: preset.pitch,
      energy: preset.energy,
      warmth: preset.warmth,
      brightness: preset.brightness,
      pause_style: preset.pause_style,
    });
    if (markDirtyAfter) dirty();
  }

  // --- Presets ------------------------------------------------------------
  // Retried once (a slow first response, not a dead endpoint) before giving
  // up. On total failure `loadedVoicePresets` and the DOM are left as they
  // were -- kept separate from the voices failure below: presets failing
  // must not blank the base/blend controls, and must not silently leave the
  // presets dropdown/list looking stale with no explanation either.
  async function refreshVoicePresets(doc) {
    let data = null;
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        data = await fetchVoicePresets();
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) {
      showToast?.(`Could not refresh voice presets: ${lastError.message}`, 'danger');
      return;
    }
    loadedVoicePresets = Array.isArray(data.presets) ? data.presets : [];
    loadedVoicePresetDefault = data.default || loadedVoicePresets.find((preset) => preset.is_default)?.name || null;
    renderVoicePresetSelect(doc);
    renderVoicePresetList(doc);
    const activePreset = loadedVoicePresets.find((preset) => preset.name === loadedVoicePresetDefault);
    if (activePreset) applyVoicePreset(doc, activePreset, { markDirtyAfter: false });
    renderUnifiedVoiceSelect(doc);
  }

  function renderVoicePresetSelect(doc) {
    const select = doc.getElementById('voicePresetSelect');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">— Custom (unsaved) —</option>';
    for (const preset of loadedVoicePresets) {
      const option = doc.createElement('option');
      option.value = preset.name;
      option.textContent = preset.name;
      select.appendChild(option);
    }
    if (current && loadedVoicePresets.some((p) => p.name === current)) {
      select.value = current;
    }
  }

  function renderUnifiedVoiceSelect(doc) {
    const select = doc.getElementById('studioActiveVoiceSelect');
    if (!select) return;
    const currentBase = doc.getElementById('settingReviewTtsVoiceHint')?.value || '';
    select.replaceChildren();
    const builtins = doc.createElement('optgroup');
    builtins.label = 'Built-in Voices';
    for (const voice of voiceOptionsCache) {
      const option = doc.createElement('option');
      option.value = `builtin:${voice.id}`;
      option.textContent = voice.name;
      builtins.append(option);
    }
    select.append(builtins);
    if (loadedVoicePresets.length) {
      const custom = doc.createElement('optgroup');
      custom.label = 'Custom Voices';
      for (const preset of loadedVoicePresets) {
        const option = doc.createElement('option');
        option.value = `custom:${preset.id || preset.name}`;
        option.textContent = preset.display_name || preset.name;
        custom.append(option);
      }
      select.append(custom);
    }
    const activePreset = loadedVoicePresets.find((preset) => preset.name === loadedVoicePresetDefault);
    select.value = activePreset ? `custom:${activePreset.id || activePreset.name}` : `builtin:${currentBase}`;
    const label = activePreset?.display_name || activePreset?.name || voiceLabel(currentBase) || 'None selected';
    const activeName = doc.getElementById('sdStudioActiveVoice');
    if (activeName) activeName.textContent = label;
  }

  async function persistBuiltInVoice(doc, voiceId) {
    if (typeof fetchProfiles !== 'function' || typeof saveProfile !== 'function') return;
    const payload = await fetchProfiles();
    const profileName = payload?.active_profile || payload?.profile || 'Default';
    const settings = { ...(payload?.settings || {}), review_tts_voice_hint: voiceId };
    await saveProfile(profileName, settings);
    await clearDefaultVoicePreset?.();
  }

  function renderVoicePresetList(doc) {
    const container = doc.getElementById('voicePresetList');
    if (!container) return;
    container.innerHTML = '';
    if (loadedVoicePresets.length === 0) {
      const empty = doc.createElement('p');
      empty.className = 'sd-voice-studio__hint';
      empty.textContent = 'No saved presets yet.';
      container.appendChild(empty);
      return;
    }
    for (const preset of loadedVoicePresets) {
      // Same Wave 12A class swap as renderVoiceBlendRows: `setting-row` /
      // `setting-info` / `setting-control` / `setting-desc` / `status-label`
      // are base.css names, and signal-desk.html does not load base.css.
      const row = doc.createElement('div');
      row.className = 'sd-voice-studio__blend-row';
      if (preset.name === loadedVoicePresetDefault) row.setAttribute('data-active', 'true');

      const info = doc.createElement('div');
      info.className = 'sd-voice-studio__active';
      const label = doc.createElement('span');
      label.className = 'sd-voice-studio__active-name';
      label.textContent = preset.name;
      const desc = doc.createElement('span');
      desc.className = 'sd-voice-studio__hint';
      const blendKeys = Object.keys(preset.blend || {});
      desc.textContent = `${preset.base || 'default voice'}${blendKeys.length ? ` + ${blendKeys.join(', ')}` : ''}`;
      info.appendChild(label);
      info.appendChild(desc);

      const controls = doc.createElement('div');
      controls.className = 'sd-actions-row';
      if (preset.name === loadedVoicePresetDefault) {
        const activeBadge = doc.createElement('span');
        activeBadge.className = 'sd-badge';
        activeBadge.textContent = 'Active';
        activeBadge.setAttribute('aria-label', 'Globally active voice preset');
        controls.appendChild(activeBadge);
      }
      const applyButton = doc.createElement('button');
      applyButton.type = 'button';
      applyButton.className = 'sd-btn';
      applyButton.textContent = 'Apply';
      applyButton.addEventListener('click', () => {
        const select = doc.getElementById('voicePresetSelect');
        if (select) select.value = preset.name;
        applyVoicePreset(doc, preset);
      });
      const activeButton = doc.createElement('button');
      activeButton.type = 'button';
      activeButton.className = 'sd-btn';
      activeButton.textContent = preset.name === loadedVoicePresetDefault ? 'Active' : 'Make active';
      activeButton.disabled = preset.name === loadedVoicePresetDefault;
      activeButton.addEventListener('click', async () => {
        if (typeof setDefaultVoicePreset !== 'function') {
          setMessage?.(messageEl(doc), 'This backend cannot set an active voice preset.', 'danger');
          return;
        }
        try {
          await setDefaultVoicePreset(preset.name);
          loadedVoicePresetDefault = preset.name;
          applyVoicePreset(doc, preset);
          renderVoicePresetList(doc);
          setMessage?.(messageEl(doc), `Voice preset "${preset.name}" is now active.`, 'success');
        } catch (error) {
          setMessage?.(messageEl(doc), `Failed to activate preset: ${error.message}`, 'danger');
        }
      });
      const renameButton = doc.createElement('button');
      renameButton.type = 'button';
      renameButton.className = 'sd-btn';
      renameButton.textContent = 'Rename';
      renameButton.addEventListener('click', async () => {
        const promptFn = doc.defaultView?.prompt || globalThis.prompt;
        const nextName = typeof promptFn === 'function' ? promptFn('Rename voice preset', preset.name) : '';
        const trimmedName = String(nextName || '').trim();
        if (!trimmedName || trimmedName.toLowerCase() === preset.name.toLowerCase()) return;
        try {
          const { name: _oldName, created_at: _createdAt, updated_at: _updatedAt, ...fields } = preset;
          await saveVoicePreset(trimmedName, fields);
          if (preset.name === loadedVoicePresetDefault && typeof setDefaultVoicePreset === 'function') {
            await setDefaultVoicePreset(trimmedName);
          }
          await deleteVoicePreset(preset.name);
          await refreshVoicePresets(doc);
          setMessage?.(messageEl(doc), `Renamed voice preset to "${trimmedName}".`, 'success');
        } catch (error) {
          setMessage?.(messageEl(doc), `Failed to rename preset: ${error.message}`, 'danger');
        }
      });
      const duplicateButton = doc.createElement('button');
      duplicateButton.type = 'button';
      duplicateButton.className = 'sd-btn';
      duplicateButton.textContent = 'Duplicate';
      duplicateButton.addEventListener('click', async () => {
        const names = new Set(loadedVoicePresets.map((item) => item.name.toLowerCase()));
        const baseName = `${preset.name} (copy)`;
        let nextName = baseName;
        let suffix = 2;
        while (names.has(nextName.toLowerCase())) nextName = `${baseName} ${suffix++}`;
        try {
          const {
            name: _oldName,
            id: _sourceId,
            version: _sourceVersion,
            created_at: _createdAt,
            updated_at: _updatedAt,
            ...fields
          } = preset;
          await saveVoicePreset(nextName, fields);
          await refreshVoicePresets(doc);
          setMessage?.(messageEl(doc), `Duplicated voice preset as "${nextName}".`, 'success');
        } catch (error) {
          setMessage?.(messageEl(doc), `Failed to duplicate preset: ${error.message}`, 'danger');
        }
      });
      const deleteButton = doc.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'sd-btn sd-btn--danger';
      deleteButton.textContent = 'Delete';
      deleteButton.addEventListener('click', async () => {
        try {
          await deleteVoicePreset(preset.name);
          await refreshVoicePresets(doc);
        } catch (error) {
          setMessage?.(messageEl(doc), `Failed to delete preset: ${error.message}`, 'danger');
        }
      });
      controls.appendChild(activeButton);
      controls.appendChild(applyButton);
      controls.appendChild(renameButton);
      controls.appendChild(duplicateButton);
      controls.appendChild(deleteButton);

      row.appendChild(info);
      row.appendChild(controls);
      container.appendChild(row);
    }
  }

  // --- Voices ---------------------------------------------------------
  // Retried once (a slow first response against api/backend.js's timeout
  // budget, not a dead endpoint -- mirrors bootstrap/signalDeskApp.js's
  // loadPersonaList) before giving up. On total failure the existing
  // voiceOptionsCache/DOM are left untouched: bootstrap only re-fires this on
  // a backend DOWN->UP transition, so a one-off slow response while the
  // backend was never actually down would otherwise get no second chance at
  // all, leaving the voice picker/blend rows/presets unpopulated indefinitely
  // with no explanation.
  async function refreshVoices(doc) {
    const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
    if (!activeDoc) return;
    let voicesData = null;
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        voicesData = await fetchTtsVoices();
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) {
      showToast?.(`Could not refresh voices: ${lastError.message}`, 'danger');
      return false;
    }
    // Runtime status is optional: if unavailable, compatibility stays
    // fail-open. When present, loaded model/voice capabilities are used to
    // disable only combinations the backend explicitly rejects.
    ttsRuntimeStatus = null;
    if (typeof fetchTtsStatus === 'function') {
      try {
        ttsRuntimeStatus = await fetchTtsStatus();
      } catch {
        ttsRuntimeStatus = null;
      }
    }
    voiceCloningAvailability = normalizeVoiceCloningAvailability(voicesData.cloning);
    renderVoiceCloningPanel?.(voicesData.cloning);
    renderVoiceCloneAvailability(activeDoc, voiceCloningAvailability);
    voiceOptionsCache = [
      ...(Array.isArray(voicesData.defaults) ? voicesData.defaults : []),
      ...(isAlphaCapabilityEnabled('voiceCloning') && Array.isArray(voicesData.cloned)
        ? voicesData.cloned.map((v) => ({ id: v.id, name: `${v.name} (Cloned)` }))
        : []),
    ];
    const voiceSelect = activeDoc.getElementById('settingReviewTtsVoiceHint');
    if (voiceSelect) {
      const currentSelected = voiceSelect.value;
      voiceSelect.innerHTML = '';
      for (const voice of voiceOptionsCache) {
        const option = activeDoc.createElement('option');
        option.value = voice.id;
        option.textContent = voice.name;
        annotateVoiceOption(option, voice.id);
        voiceSelect.appendChild(option);
      }
      if (currentSelected) {
        const { id, fellBack } = resolveAvailableVoiceId(currentSelected, availableVoiceIds(), currentSelected);
        voiceSelect.value = id;
        if (fellBack) {
          showToast?.(`"${currentSelected}" is no longer available; switched to ${voiceLabel(id) || 'the first available voice'}.`, 'warning');
          dirty();
        }
      }
    }
    renderTtsCompatibility(activeDoc);
    // Existing blend rows may reference a voice that's now gone (deleted clone).
    const { layers, dropped } = filterAvailableBlendLayers(voiceBlendLayers, availableVoiceIds());
    if (dropped.length) {
      voiceBlendLayers = layers;
      showToast?.(`Dropped unavailable blend voice${dropped.length > 1 ? 's' : ''}: ${dropped.join(', ')}.`, 'warning');
      dirty();
    }
    renderVoiceBlendRows(activeDoc);
    await refreshVoicePresets(activeDoc).catch((error) => console.error('Failed to load voice presets:', error));
    renderUnifiedVoiceSelect(activeDoc);
    return true;
  }

  // --- Read-aloud transport ----------------------------------------------
  // The backend owns the audio device and exposes a stop route, so pause is a
  // safe stop-with-intent-to-resume (the next Play starts the requested text
  // again). Keeping the transport here means every action gathers the live
  // voice/blend controls at the moment it starts, rather than replaying stale
  // settings captured by the first audition.
  function renderReadAloudState(doc, state, detail = '') {
    playbackState = state;
    const status = doc.getElementById('readAloudPlaybackState');
    if (!status) return;
    const labels = { idle: 'Ready', playing: 'Playing…', paused: 'Paused', stopped: 'Stopped' };
    status.textContent = detail || labels[state] || 'Ready';
    status.dataset.state = state;
  }

  async function stopCurrentTts() {
    if (typeof stopTts !== 'function') return;
    try {
      await stopTts();
    } catch (error) {
      // A stop failure is surfaced by the transport caller; never turn it into
      // a false "stopped" state.
      throw error;
    }
  }

  async function playReadAloud(doc, textOverride = '') {
    const text = textOverride || doc.getElementById('voicePreviewText')?.value?.trim()
      || 'This is a test of the BetterFingers text to speech voice synthesis.';
    const settings = gatherVoiceStudioSettings(doc);
    const run = ++playbackRun;
    playbackText = text;
    renderReadAloudState(doc, 'playing');
    try {
      const result = await speakTts(text, settings.base, settings.speed, settings.pitch, {
        blend: settings.blend,
        energy: settings.energy,
        warmth: settings.warmth,
        brightness: settings.brightness,
        pause_style: settings.pause_style,
      });
      if (run !== playbackRun) return result;
      if (result && result.ok === false) {
        renderReadAloudState(doc, 'stopped', `Playback failed: ${result.message || result.error || 'Unknown error'}`);
      } else {
        renderReadAloudState(doc, 'idle', 'Ready — playback complete');
      }
      return result;
    } catch (error) {
      if (run === playbackRun) renderReadAloudState(doc, 'stopped', `Playback failed: ${error.message}`);
      throw error;
    }
  }

  function createTransportButton(doc, id, label) {
    const button = doc.createElement('button');
    button.id = id;
    button.type = 'button';
    button.className = 'sd-btn';
    button.textContent = label;
    return button;
  }

  function ensureReadAloudControls(doc) {
    const existing = {
      play: doc.getElementById('readAloudPlayButton'),
      pause: doc.getElementById('readAloudPauseButton'),
      stop: doc.getElementById('readAloudStopButton'),
      restart: doc.getElementById('readAloudRestartButton'),
      status: doc.getElementById('readAloudPlaybackState'),
    };
    const audition = doc.getElementById('testTtsButton');
    const host = audition?.parentNode || audition;
    const controls = [
      ['play', 'readAloudPlayButton', 'Play'],
      ['pause', 'readAloudPauseButton', 'Pause'],
      ['stop', 'readAloudStopButton', 'Stop'],
      ['restart', 'readAloudRestartButton', 'Restart'],
    ];
    for (const [key, id, label] of controls) {
      if (!existing[key] && host?.appendChild) {
        existing[key] = createTransportButton(doc, id, label);
        host.appendChild(existing[key]);
      }
    }
    if (!existing.status && host?.appendChild) {
      existing.status = doc.createElement('span');
      existing.status.id = 'readAloudPlaybackState';
      existing.status.className = 'sd-voice-studio__result';
      existing.status.setAttribute('role', 'status');
      existing.status.setAttribute('aria-live', 'polite');
      host.appendChild(existing.status);
    }
    return existing;
  }

  function initReadAloud(doc) {
    const controls = ensureReadAloudControls(doc);
    renderReadAloudState(doc, 'idle');
    controls.play?.addEventListener('click', async () => {
      try { await playReadAloud(doc); } catch (error) { setMessage?.(messageEl(doc), `Read aloud failed: ${error.message}`, 'danger'); }
    });
    controls.pause?.addEventListener('click', async () => {
      ++playbackRun;
      try {
        await stopCurrentTts();
        renderReadAloudState(doc, 'paused');
      } catch (error) {
        renderReadAloudState(doc, 'playing', `Pause failed: ${error.message}`);
      }
    });
    controls.stop?.addEventListener('click', async () => {
      ++playbackRun;
      try {
        await stopCurrentTts();
        renderReadAloudState(doc, 'stopped');
      } catch (error) {
        renderReadAloudState(doc, 'playing', `Stop failed: ${error.message}`);
      }
    });
    controls.restart?.addEventListener('click', async () => {
      ++playbackRun;
      try {
        await stopCurrentTts();
        await playReadAloud(doc, playbackText);
      } catch (error) {
        setMessage?.(messageEl(doc), `Read aloud restart failed: ${error.message}`, 'danger');
      }
    });
  }

  // --- Voice cloning (sample upload) --------------------------------------
  function renderVoiceCloneAvailability(doc, status = voiceCloningAvailability) {
    const statusEl = doc.getElementById('voiceCloneStatusNote');
    const installButton = doc.getElementById('voiceCloneInstallButton');
    if (statusEl) {
      statusEl.textContent = status.message;
      statusEl.hidden = false;
    }
    if (installButton) {
      installButton.hidden = status.available;
      installButton.disabled = status.available || typeof provisionVoiceCloning !== 'function';
      installButton.textContent = status.known && !status.available ? 'Install voice cloning model' : 'Check voice cloning model';
    }
    const consentEl = doc.getElementById('voiceCloneConsent');
    const nameEl = doc.getElementById('voiceCloneName');
    const fileEl = doc.getElementById('voiceCloneFile');
    const uploadButton = doc.getElementById('voiceCloneUploadButton');
    const recordButton = doc.getElementById('voiceCloneRecordButton');
    const previewButton = doc.getElementById('voiceClonePreviewButton');
    const discardButton = doc.getElementById('voiceCloneDiscardButton');
    const enabled = Boolean(consentEl?.checked);
    const modelUnavailable = status.known && !status.available;
    if (nameEl) nameEl.disabled = !enabled || modelUnavailable;
    if (fileEl) fileEl.disabled = !enabled || modelUnavailable;
    if (uploadButton) uploadButton.disabled = !enabled || modelUnavailable;
    if (recordButton) recordButton.disabled = !enabled || modelUnavailable;
    if (previewButton) previewButton.disabled = !enabled || modelUnavailable || !previewButton.dataset.hasSample;
    if (discardButton) discardButton.disabled = !enabled || modelUnavailable || !discardButton.dataset.hasSample;
  }

  function initVoiceCloning(doc) {
    const consentEl = doc.getElementById('voiceCloneConsent');
    const nameEl = doc.getElementById('voiceCloneName');
    const fileEl = doc.getElementById('voiceCloneFile');
    const uploadButton = doc.getElementById('voiceCloneUploadButton');
    const resultEl = doc.getElementById('voiceCloneResult');
    if (!consentEl || !nameEl || !fileEl || !uploadButton || !resultEl) return;

    let recordedSample = null;
    let sampleUrl = '';
    let recorder = null;
    let recorderStream = null;
    let recorderChunks = [];
    const host = uploadButton.parentNode || resultEl.parentNode || uploadButton;
    const statusEl = doc.getElementById('voiceCloneStatusNote') || doc.createElement('p');
    statusEl.id = 'voiceCloneStatusNote';
    statusEl.className = 'sd-voice-studio__result';
    if (!doc.getElementById('voiceCloneStatusNote')) host?.appendChild?.(statusEl);
    const installButton = doc.getElementById('voiceCloneInstallButton') || doc.createElement('button');
    installButton.id = 'voiceCloneInstallButton';
    installButton.type = 'button';
    installButton.className = 'sd-btn';
    if (!doc.getElementById('voiceCloneInstallButton')) host?.appendChild?.(installButton);
    const makeControl = (id, label) => {
      const button = doc.getElementById(id) || doc.createElement('button');
      button.id = id;
      button.type = 'button';
      button.className = 'sd-btn';
      button.textContent = label;
      if (!doc.getElementById(id)) host?.appendChild?.(button);
      return button;
    };
    const recordButton = makeControl('voiceCloneRecordButton', 'Record sample');
    const previewButton = makeControl('voiceClonePreviewButton', 'Preview recording');
    const discardButton = makeControl('voiceCloneDiscardButton', 'Discard / re-record');
    const sampleAudio = doc.getElementById('voiceCloneSampleAudio') || doc.createElement('audio');
    sampleAudio.id = 'voiceCloneSampleAudio';
    sampleAudio.controls = true;
    sampleAudio.hidden = true;
    if (!doc.getElementById('voiceCloneSampleAudio')) host?.appendChild?.(sampleAudio);
    const sampleState = doc.getElementById('voiceClonePlaybackState') || doc.createElement('span');
    sampleState.id = 'voiceClonePlaybackState';
    sampleState.className = 'sd-voice-studio__result';
    sampleState.setAttribute('role', 'status');
    sampleState.setAttribute('aria-live', 'polite');
    if (!doc.getElementById('voiceClonePlaybackState')) host?.appendChild?.(sampleState);

    const updateSampleState = (message) => { sampleState.textContent = message; };
    const stopStream = () => {
      recorderStream?.getTracks?.().forEach((track) => track.stop());
      recorderStream = null;
      recorder = null;
    };
    const sampleName = (file) => file?.name || 'recorded sample';
    const showSample = (file) => {
      if (!file) return;
      recordedSample = file?.__voiceStudioRecorded ? file : null;
      if (sampleUrl && globalThis.URL?.revokeObjectURL) globalThis.URL.revokeObjectURL(sampleUrl);
      try {
        sampleUrl = globalThis.URL?.createObjectURL ? globalThis.URL.createObjectURL(file) : '';
      } catch {
        sampleUrl = '';
      }
      if (sampleUrl) sampleAudio.src = sampleUrl;
      sampleAudio.hidden = false;
      previewButton.disabled = false;
      discardButton.disabled = false;
      previewButton.dataset.hasSample = 'true';
      discardButton.dataset.hasSample = 'true';
      const duration = Number(file.duration);
      updateSampleState(`Sample ready: ${sampleName(file)} · ${formatVoiceSampleDuration(duration)}`);
    };
    const currentSample = () => recordedSample || fileEl.files?.[0] || null;
    const discardSample = () => {
      sampleAudio.pause?.();
      sampleAudio.removeAttribute?.('src');
      sampleAudio.hidden = true;
      if (sampleUrl && globalThis.URL?.revokeObjectURL) globalThis.URL.revokeObjectURL(sampleUrl);
      sampleUrl = '';
      recordedSample = null;
      if ('value' in fileEl) fileEl.value = '';
      previewButton.disabled = true;
      discardButton.disabled = true;
      delete previewButton.dataset.hasSample;
      delete discardButton.dataset.hasSample;
      updateSampleState('No recording selected. Record or choose a sample.');
    };
    fileEl.addEventListener('change', () => {
      recordedSample = null;
      showSample(fileEl.files?.[0]);
    });
    sampleAudio.addEventListener?.('loadedmetadata', () => {
      const duration = Number(sampleAudio.duration);
      if (Number.isFinite(duration)) updateSampleState(`Sample ready: ${sampleName(currentSample())} · ${formatVoiceSampleDuration(duration)}`);
    });
    sampleAudio.addEventListener?.('play', () => updateSampleState(`Playing recording: ${sampleName(currentSample())}`));
    sampleAudio.addEventListener?.('pause', () => {
      if (!sampleAudio.ended) updateSampleState(`Paused recording: ${sampleName(currentSample())}`);
    });
    sampleAudio.addEventListener?.('ended', () => updateSampleState(`Finished recording: ${sampleName(currentSample())}`));
    previewButton.addEventListener('click', () => {
      if (!currentSample()) {
        updateSampleState('No recording selected. Record or choose a sample.');
        return;
      }
      const playResult = sampleAudio.play?.();
      playResult?.catch?.(() => updateSampleState('Could not play this recording.'));
    });
    discardButton.addEventListener('click', discardSample);
    recordButton.addEventListener('click', async () => {
      if (recorder) {
        recorder.stop();
        recordButton.disabled = true;
        return;
      }
      const mediaDevices = globalThis.navigator?.mediaDevices || globalThis.window?.navigator?.mediaDevices;
      const MediaRecorderCtor = globalThis.MediaRecorder;
      if (!mediaDevices?.getUserMedia || typeof MediaRecorderCtor !== 'function') {
        updateSampleState('Recording is unavailable in this environment; choose an audio file instead.');
        return;
      }
      try {
        recorderStream = await mediaDevices.getUserMedia({ audio: true });
        recorderChunks = [];
        recorder = new MediaRecorderCtor(recorderStream);
        recorder.addEventListener?.('dataavailable', (event) => { if (event.data?.size) recorderChunks.push(event.data); });
        recorder.addEventListener?.('stop', () => {
          const blob = new Blob(recorderChunks, { type: recorder.mimeType || 'audio/webm' });
          const file = typeof File === 'function'
            ? new File([blob], 'recorded-voice-sample.webm', { type: blob.type })
            : blob;
          try { Object.defineProperty(file, 'name', { value: 'recorded-voice-sample.webm' }); } catch {}
          try { Object.defineProperty(file, '__voiceStudioRecorded', { value: true }); } catch { file.__voiceStudioRecorded = true; }
          recordedSample = file;
          showSample(file);
          recordButton.disabled = false;
          recordButton.textContent = 'Re-record sample';
          stopStream();
        });
        recorder.start();
        recordButton.textContent = 'Stop recording';
        updateSampleState('Recording… speak clearly, then stop when finished.');
      } catch (error) {
        stopStream();
        updateSampleState(`Could not record sample: ${error.message}`);
      }
    });

    const syncConsent = () => {
      const enabled = consentEl.checked;
      nameEl.disabled = !enabled;
      fileEl.disabled = !enabled;
      const modelUnavailable = voiceCloningAvailability.known && !voiceCloningAvailability.available;
      nameEl.disabled = !enabled || modelUnavailable;
      fileEl.disabled = !enabled || modelUnavailable;
      uploadButton.disabled = !enabled || modelUnavailable;
      recordButton.disabled = !enabled || modelUnavailable;
      previewButton.disabled = !enabled || modelUnavailable || !currentSample();
      discardButton.disabled = !enabled || modelUnavailable || !currentSample();
      if (!enabled) {
        resultEl.textContent = '';
        if (recorder) recorder.stop();
        discardSample();
      }
    };
    consentEl.addEventListener('change', syncConsent);
    installButton.addEventListener('click', async () => {
      if (typeof provisionVoiceCloning !== 'function') {
        updateSampleState('Install voice cloning from the Models page before uploading a sample.');
        return;
      }
      installButton.disabled = true;
      installButton.textContent = 'Installing voice cloning model…';
      try {
        await provisionVoiceCloning();
        await refreshVoices(doc);
      } catch (error) {
        updateSampleState(`Could not install voice cloning model: ${error.message}`);
        installButton.disabled = false;
        installButton.textContent = 'Install voice cloning model';
      }
    });
    renderVoiceCloneAvailability(doc);
    updateSampleState('No recording selected. Record or choose a sample.');
    syncConsent();

    uploadButton.addEventListener('click', async () => {
      const file = currentSample();
      const name = nameEl.value.trim();
      if (!consentEl.checked) {
        resultEl.textContent = 'Consent is required before uploading a sample.';
        return;
      }
      if (!file) {
        resultEl.textContent = 'Choose a WAV sample to upload.';
        return;
      }
      if (!name) {
        resultEl.textContent = 'A voice name is required.';
        return;
      }

      // On a cold page load the voices request may still be in flight. Verify
      // the backend's explicit availability report before accepting any sample
      // so an upload cannot fail after the user has recorded it.
      if (!voiceCloningAvailability.known) {
        resultEl.textContent = 'Checking whether the voice-cloning model is available…';
        const refreshed = await refreshVoices(doc);
        if (!refreshed) {
          resultEl.textContent = 'Could not verify the voice-cloning model. Install it from the Models page, then try again.';
          return;
        }
      }
      if (voiceCloningAvailability.known && !voiceCloningAvailability.available) {
        resultEl.textContent = voiceCloningAvailability.message;
        return;
      }

      uploadButton.disabled = true;
      uploadButton.textContent = 'Validating...';
      resultEl.textContent = '';

      try {
        const result = await cloneVoice(file, name, true);
        const warnings = result.warnings || [];
        resultEl.textContent = warnings.length
          ? `Saved "${name}" with warnings: ${warnings.join(' ')}`
          : `Saved "${name}" — sample passed all quality checks.`;
        await refreshVoices(doc);
      } catch (error) {
        const warnings = error.detail?.warnings || [];
        resultEl.textContent = warnings.length ? warnings.join(' ') : (error.message || 'Clone upload failed.');
      } finally {
        uploadButton.disabled = false;
        uploadButton.textContent = 'Upload & Validate Sample';
      }
    });
  }

  // --- Init -----------------------------------------------------------
  function init({ doc } = {}) {
    const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
    if (!activeDoc || typeof activeDoc.getElementById !== 'function') return;
    if (initialized) return; // idempotent: guards against double-wiring listeners
    initialized = true;

    renderVoiceBlendRows(activeDoc);
    updateModulationLabels(activeDoc);

    const customWorkflow = activeDoc.getElementById('customVoiceWorkflow');
    activeDoc.getElementById('createCustomVoiceButton')?.addEventListener('click', () => {
      if (customWorkflow) customWorkflow.hidden = false;
      activeDoc.getElementById('voicePresetNameInput')?.focus?.();
    });
    activeDoc.getElementById('closeCustomVoiceButton')?.addEventListener('click', () => {
      if (customWorkflow) customWorkflow.hidden = true;
    });
    activeDoc.getElementById('studioActiveVoiceSelect')?.addEventListener('change', async (event) => {
      const [kind, id] = String(event.target.value || '').split(':', 2);
      try {
        if (kind === 'custom') {
          const preset = loadedVoicePresets.find((item) => (item.id || item.name) === id);
          if (!preset) throw new Error('That custom voice is no longer available.');
          applyVoicePreset(activeDoc, preset);
          await setDefaultVoicePreset?.(preset.name);
          loadedVoicePresetDefault = preset.name;
        } else if (kind === 'builtin') {
          const baseSelect = activeDoc.getElementById('settingReviewTtsVoiceHint');
          if (baseSelect) baseSelect.value = id;
          await persistBuiltInVoice(activeDoc, id);
          loadedVoicePresetDefault = null;
          renderActiveVoiceName(activeDoc);
          renderEffectiveMix(activeDoc);
        }
        renderUnifiedVoiceSelect(activeDoc);
        renderVoicePresetList(activeDoc);
        setMessage?.(messageEl(activeDoc), 'Active voice saved.', 'success');
      } catch (error) {
        setMessage?.(messageEl(activeDoc), `Could not activate voice: ${error.message}`, 'danger');
        renderUnifiedVoiceSelect(activeDoc);
      }
    });

    ['voicePitch', 'voiceEnergy', 'voiceWarmth', 'voiceBrightness'].forEach((id) => {
      activeDoc.getElementById(id)?.addEventListener('input', () => {
        updateModulationLabels(activeDoc);
        dirty();
      });
    });
    activeDoc.getElementById('voicePauseStyle')?.addEventListener('change', dirty);

    // Wave 12A. The base-voice select had NO change listener at all: picking a
    // different read-aloud voice neither marked the profile dirty nor moved
    // the effective-mix line, so the blend readout could sit there describing
    // a base the user had already changed away from. Found while wiring the
    // active-voice readout, which needs this same event.
    activeDoc.getElementById('settingReviewTtsVoiceHint')?.addEventListener('change', () => {
      const baseId = activeDoc.getElementById('settingReviewTtsVoiceHint')?.value;
      const before = voiceBlendLayers.length;
      voiceBlendLayers = voiceBlendLayers.filter((layer) => layer.voiceId !== baseId);
      if (voiceBlendLayers.length !== before) showToast?.('Removed the duplicate source from the blend.', 'warning');
      renderEffectiveMix(activeDoc);
      renderTtsCompatibility(activeDoc);
      dirty();
    });

    activeDoc.getElementById('addVoiceLayerButton')?.addEventListener('click', () => {
      if (voiceBlendLayers.length >= MAX_BLEND_LAYERS) return;
      const baseId = activeDoc.getElementById('settingReviewTtsVoiceHint')?.value;
      const fallbackVoice = voiceOptionsCache.find((v) => v.id !== baseId)?.id || voiceOptionsCache[0]?.id || 'af_bella';
      voiceBlendLayers.push({ voiceId: fallbackVoice, weight: 0.3 });
      dirty();
      renderVoiceBlendRows(activeDoc);
    });

    activeDoc.getElementById('resetVoiceBlendButton')?.addEventListener('click', () => {
      voiceBlendLayers = [];
      dirty();
      renderVoiceBlendRows(activeDoc);
    });

    activeDoc.getElementById('voicePresetSelect')?.addEventListener('change', (event) => {
      const name = event.target.value;
      if (!name) return;
      const preset = loadedVoicePresets.find((p) => p.name === name);
      if (preset) applyVoicePreset(activeDoc, preset);
    });

    activeDoc.getElementById('saveVoicePresetButton')?.addEventListener('click', async () => {
      const nameInput = activeDoc.getElementById('voicePresetNameInput');
      const name = nameInput?.value?.trim();
      if (!name) {
        setMessage?.(messageEl(activeDoc), 'A preset name is required to save.', 'danger');
        return;
      }
      const settings = gatherVoiceStudioSettings(activeDoc);
      try {
        const replacing = loadedVoicePresets.some((preset) => preset.name.toLowerCase() === name.toLowerCase());
        if (replacing) {
          const confirmFn = activeDoc.defaultView?.confirm || globalThis.confirm;
          if (typeof confirmFn !== 'function' || !confirmFn(`Replace the saved custom voice "${name}" with this new version?`)) return;
        }
        const payload = buildCustomVoicePayload(name, {
          ...settings,
          blendLayers: voiceBlendLayers,
        }, {
          availableIds: availableVoiceIds(),
          sourcePresetId: activeDoc.getElementById('voicePresetSelect')?.value || '',
          replace: replacing,
        });
        await saveVoicePreset(name, payload);
        await setDefaultVoicePreset?.(name);
        loadedVoicePresetDefault = name;
        setMessage?.(messageEl(activeDoc), `Saved and activated custom voice "${name}".`, 'success');
        if (nameInput) nameInput.value = '';
        await refreshVoicePresets(activeDoc);
      } catch (error) {
        setMessage?.(messageEl(activeDoc), `Failed to save preset: ${error.message}`, 'danger');
      }
    });

    activeDoc.querySelectorAll('[data-blend-preset]').forEach((button) => {
      button.addEventListener('click', () => {
        const preset = VOICE_BLEND_QUICK_PRESETS[button.dataset.blendPreset];
        if (!preset) return;
        applyVoiceStudioState(activeDoc, {
          base: preset.base,
          blend: preset.blend || {},
          pitch: preset.pitch,
          energy: preset.energy,
          warmth: preset.warmth,
          brightness: preset.brightness,
          pause_style: preset.pause_style,
        });
        dirty();
      });
    });

    activeDoc.querySelectorAll('[data-mod-preset]').forEach((button) => {
      button.addEventListener('click', () => {
        const preset = VOICE_MODULATION_QUICK_PRESETS[button.dataset.modPreset];
        if (!preset) return;
        const speedInput = activeDoc.getElementById('settingReviewTtsSpeed');
        if (speedInput && preset.speed !== undefined) {
          speedInput.value = preset.speed;
        }
        setModulationControls(activeDoc, preset);
        dirty();
      });
    });

    const testTtsButton = activeDoc.getElementById('testTtsButton');
    testTtsButton?.addEventListener('click', async () => {
      testTtsButton.disabled = true;
      testTtsButton.textContent = 'Speaking...';
      try {
        const res = await playReadAloud(activeDoc);
        if (res && res.ok === false) {
          setMessage?.(messageEl(activeDoc), `TTS Audition failed: ${res.message || res.error || 'Unknown error'}`, 'danger');
        } else {
          setMessage?.(messageEl(activeDoc), `TTS Audition: ${res?.message || 'Playback complete.'}`, 'success');
        }
      } catch (error) {
        setMessage?.(messageEl(activeDoc), `TTS Audition failed: ${error.message}`, 'danger');
      } finally {
        testTtsButton.disabled = false;
        testTtsButton.textContent = 'Audition Voice / Test TTS API';
      }
    });

    initReadAloud(activeDoc);
    initVoiceCloning(activeDoc);
  }

  return {
    init,
    refreshVoices,
    gatherVoiceStudioSettings: (doc) => gatherVoiceStudioSettings(doc),
    getPersistableState: (doc) => {
      const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
      return buildPersistableVoiceStudioSettings({
        blendLayers: voiceBlendLayers,
        pitch: activeDoc?.getElementById('voicePitch')?.value,
        energy: activeDoc?.getElementById('voiceEnergy')?.value,
        warmth: activeDoc?.getElementById('voiceWarmth')?.value,
        brightness: activeDoc?.getElementById('voiceBrightness')?.value,
        pauseStyle: activeDoc?.getElementById('voicePauseStyle')?.value,
      });
    },
    restoreFromProfile: (settings, doc) => {
      const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
      if (!activeDoc) return;
      // renderProfileSettings() just wrote settings.review_tts_voice_hint
      // straight into the select's .value; if that voice is no longer
      // available (deleted clone, stale profile) the select silently ends up
      // with no matching option selected. Re-validate it here, in the same
      // pass as the rest of the restore, rather than leaving it to whatever
      // next touches the select.
      const baseSelect = activeDoc.getElementById('settingReviewTtsVoiceHint');
      if (baseSelect) {
        const { id, fellBack } = resolveAvailableVoiceId(baseSelect.value, availableVoiceIds(), baseSelect.value);
        if (fellBack) {
          const previous = baseSelect.value;
          baseSelect.value = id;
          showToast?.(`"${previous}" is no longer available; switched to ${voiceLabel(id) || 'the first available voice'}.`, 'warning');
          dirty();
        }
      }
      const restored = extractVoiceStudioStateFromProfile(settings);
      const { layers, dropped } = filterAvailableBlendLayers(restored.blendLayers, availableVoiceIds());
      voiceBlendLayers = layers;
      if (dropped.length) {
        showToast?.(`Dropped unavailable blend voice${dropped.length > 1 ? 's' : ''}: ${dropped.join(', ')}.`, 'warning');
      }
      renderVoiceBlendRows(activeDoc);
      setModulationControls(activeDoc, {
        pitch: restored.pitch,
        energy: restored.energy,
        warmth: restored.warmth,
        brightness: restored.brightness,
        pause_style: restored.pauseStyle,
      });
    },
  };
}
