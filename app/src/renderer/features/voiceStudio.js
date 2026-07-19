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

export const MAX_BLEND_LAYERS = 2; // base + 2 extra = 3-way blend cap

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
    fetchTtsVoices, fetchVoicePresets, saveVoicePreset, deleteVoicePreset, cloneVoice, speakTts,
  } = api || backendApi;

  let voiceOptionsCache = []; // [{id, name}]
  let voiceBlendLayers = []; // [{voiceId, weight}]
  let loadedVoicePresets = [];
  let initialized = false;

  function availableVoiceIds() {
    return voiceOptionsCache.map((v) => v.id);
  }

  function voiceLabel(id) {
    return voiceOptionsCache.find((v) => v.id === id)?.name || id;
  }

  function messageEl(doc) {
    return doc.getElementById('profileMessage');
  }

  function dirty() {
    markProfileDirty?.();
  }

  // --- Blend rows -----------------------------------------------------
  function renderVoiceBlendRows(doc) {
    const container = doc.getElementById('voiceBlendRows');
    if (!container) return;
    container.innerHTML = '';
    if (voiceBlendLayers.length === 0) {
      const empty = doc.createElement('p');
      empty.className = 'setting-desc';
      empty.textContent = 'No blend layers — auditioning the base voice alone.';
      container.appendChild(empty);
      renderEffectiveMix(doc);
      return;
    }
    voiceBlendLayers.forEach((layer, index) => {
      const row = doc.createElement('div');
      row.className = 'setting-row voice-blend-row';

      const select = doc.createElement('select');
      select.className = 'settings-input min-w-160';
      select.setAttribute('aria-label', `Blend voice ${index + 1}`);
      for (const voice of voiceOptionsCache) {
        const option = doc.createElement('option');
        option.value = voice.id;
        option.textContent = voice.name;
        select.appendChild(option);
      }
      select.value = layer.voiceId;
      select.addEventListener('change', () => {
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
      weightInput.className = 'settings-input';
      weightInput.setAttribute('aria-label', `Blend voice ${index + 1} weight`);

      const weightLabel = doc.createElement('span');
      weightLabel.className = 'status-label voice-blend-weight-label';
      weightLabel.textContent = layer.weight.toFixed(2);
      weightInput.addEventListener('input', () => {
        voiceBlendLayers[index].weight = parseFloat(weightInput.value);
        weightLabel.textContent = voiceBlendLayers[index].weight.toFixed(2);
        dirty();
        renderEffectiveMix(doc);
      });

      const removeButton = doc.createElement('button');
      removeButton.type = 'button';
      removeButton.className = 'secondary-button';
      removeButton.textContent = 'Remove';
      removeButton.setAttribute('aria-label', `Remove blend voice ${index + 1}`);
      removeButton.addEventListener('click', () => {
        voiceBlendLayers.splice(index, 1);
        dirty();
        renderVoiceBlendRows(doc);
      });

      row.appendChild(select);
      row.appendChild(weightInput);
      row.appendChild(weightLabel);
      row.appendChild(removeButton);
      container.appendChild(row);
    });
    renderEffectiveMix(doc);
  }

  function renderEffectiveMix(doc) {
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

  function applyVoicePreset(doc, preset) {
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
    dirty();
  }

  // --- Presets ------------------------------------------------------------
  async function refreshVoicePresets(doc) {
    const data = await fetchVoicePresets();
    loadedVoicePresets = Array.isArray(data.presets) ? data.presets : [];
    renderVoicePresetSelect(doc);
    renderVoicePresetList(doc);
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

  function renderVoicePresetList(doc) {
    const container = doc.getElementById('voicePresetList');
    if (!container) return;
    container.innerHTML = '';
    if (loadedVoicePresets.length === 0) {
      const empty = doc.createElement('p');
      empty.className = 'setting-desc';
      empty.textContent = 'No saved presets yet.';
      container.appendChild(empty);
      return;
    }
    for (const preset of loadedVoicePresets) {
      const row = doc.createElement('div');
      row.className = 'setting-row voice-preset-row';

      const info = doc.createElement('div');
      info.className = 'setting-info';
      const label = doc.createElement('span');
      label.className = 'status-label';
      label.textContent = preset.name;
      const desc = doc.createElement('span');
      desc.className = 'setting-desc';
      const blendKeys = Object.keys(preset.blend || {});
      desc.textContent = `${preset.base || 'default voice'}${blendKeys.length ? ` + ${blendKeys.join(', ')}` : ''}`;
      info.appendChild(label);
      info.appendChild(desc);

      const controls = doc.createElement('div');
      controls.className = 'setting-control';
      const applyButton = doc.createElement('button');
      applyButton.type = 'button';
      applyButton.className = 'secondary-button';
      applyButton.textContent = 'Apply';
      applyButton.addEventListener('click', () => {
        const select = doc.getElementById('voicePresetSelect');
        if (select) select.value = preset.name;
        applyVoicePreset(doc, preset);
      });
      const deleteButton = doc.createElement('button');
      deleteButton.type = 'button';
      deleteButton.className = 'secondary-button';
      deleteButton.textContent = 'Delete';
      deleteButton.addEventListener('click', async () => {
        try {
          await deleteVoicePreset(preset.name);
          await refreshVoicePresets(doc);
        } catch (error) {
          setMessage?.(messageEl(doc), `Failed to delete preset: ${error.message}`, 'danger');
        }
      });
      controls.appendChild(applyButton);
      controls.appendChild(deleteButton);

      row.appendChild(info);
      row.appendChild(controls);
      container.appendChild(row);
    }
  }

  // --- Voices ---------------------------------------------------------
  async function refreshVoices(doc) {
    const activeDoc = doc || (typeof document !== 'undefined' ? document : null);
    if (!activeDoc) return;
    const voicesData = await fetchTtsVoices();
    renderVoiceCloningPanel?.(voicesData.cloning);
    voiceOptionsCache = [
      ...(Array.isArray(voicesData.defaults) ? voicesData.defaults : []),
      ...(Array.isArray(voicesData.cloned) ? voicesData.cloned.map((v) => ({ id: v.id, name: `${v.name} (Cloned)` })) : []),
    ];
    const voiceSelect = activeDoc.getElementById('settingReviewTtsVoiceHint');
    if (voiceSelect) {
      const currentSelected = voiceSelect.value;
      voiceSelect.innerHTML = '';
      for (const voice of voiceOptionsCache) {
        const option = activeDoc.createElement('option');
        option.value = voice.id;
        option.textContent = voice.name;
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
    // Existing blend rows may reference a voice that's now gone (deleted clone).
    const { layers, dropped } = filterAvailableBlendLayers(voiceBlendLayers, availableVoiceIds());
    if (dropped.length) {
      voiceBlendLayers = layers;
      showToast?.(`Dropped unavailable blend voice${dropped.length > 1 ? 's' : ''}: ${dropped.join(', ')}.`, 'warning');
      dirty();
    }
    renderVoiceBlendRows(activeDoc);
    await refreshVoicePresets(activeDoc).catch((error) => console.error('Failed to load voice presets:', error));
  }

  // --- Voice cloning (sample upload) --------------------------------------
  function initVoiceCloning(doc) {
    const consentEl = doc.getElementById('voiceCloneConsent');
    const nameEl = doc.getElementById('voiceCloneName');
    const fileEl = doc.getElementById('voiceCloneFile');
    const uploadButton = doc.getElementById('voiceCloneUploadButton');
    const resultEl = doc.getElementById('voiceCloneResult');
    if (!consentEl || !nameEl || !fileEl || !uploadButton || !resultEl) return;

    consentEl.addEventListener('change', () => {
      const enabled = consentEl.checked;
      nameEl.disabled = !enabled;
      fileEl.disabled = !enabled;
      uploadButton.disabled = !enabled;
      if (!enabled) {
        resultEl.textContent = '';
      }
    });

    uploadButton.addEventListener('click', async () => {
      const file = fileEl.files?.[0];
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

    ['voicePitch', 'voiceEnergy', 'voiceWarmth', 'voiceBrightness'].forEach((id) => {
      activeDoc.getElementById(id)?.addEventListener('input', () => {
        updateModulationLabels(activeDoc);
        dirty();
      });
    });
    activeDoc.getElementById('voicePauseStyle')?.addEventListener('change', dirty);

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
        await saveVoicePreset(name, { ...settings, blend: settings.blend || {} });
        setMessage?.(messageEl(activeDoc), `Saved voice preset "${name}".`, 'success');
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
      const previewText = activeDoc.getElementById('voicePreviewText')?.value?.trim();
      const text = previewText || 'This is a test of the BetterFingers text to speech voice synthesis.';
      const settings = gatherVoiceStudioSettings(activeDoc);

      testTtsButton.disabled = true;
      testTtsButton.textContent = 'Speaking...';

      try {
        const res = await speakTts(text, settings.base, settings.speed, settings.pitch, {
          blend: settings.blend,
          energy: settings.energy,
          warmth: settings.warmth,
          brightness: settings.brightness,
          pause_style: settings.pause_style,
        });
        // A cloned voice can fail honestly (sample missing / clone engine not
        // installed) — surface that as an error, not a green "success".
        if (res && res.ok === false) {
          setMessage?.(messageEl(activeDoc), `TTS Audition failed: ${res.message || res.error || 'Unknown error'}`, 'danger');
        } else {
          setMessage?.(messageEl(activeDoc), `TTS Audition: ${res.message}`, 'success');
        }
      } catch (error) {
        setMessage?.(messageEl(activeDoc), `TTS Audition failed: ${error.message}`, 'danger');
      } finally {
        testTtsButton.disabled = false;
        testTtsButton.textContent = 'Audition Voice / Test TTS API';
      }
    });

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
