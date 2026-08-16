import * as backendApi from '../api/backend.js';

const FIELD_IDS = Object.freeze({
  displayName: 'sdPersonaFieldDisplayName',
  description: 'sdPersonaFieldDescription',
  kind: 'sdPersonaFieldKind',
  language: 'sdPersonaFieldLanguage',
  cleanup: 'sdPersonaFieldCleanup',
  strength: 'sdPersonaFieldStrength',
  retention: 'sdPersonaFieldRetention',
  targetLength: 'sdPersonaFieldTargetLength',
  formality: 'sdPersonaFieldFormality',
  directness: 'sdPersonaFieldDirectness',
  warmth: 'sdPersonaFieldWarmth',
  humor: 'sdPersonaFieldHumor',
  vocabulary: 'sdPersonaFieldVocabulary',
  sentenceLength: 'sdPersonaFieldSentenceLength',
  coreImpression: 'sdPersonaFieldCoreImpression',
  speakingHabits: 'sdPersonaFieldSpeakingHabits',
  forbidden: 'sdPersonaFieldForbidden',
});

function list(value) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  return String(value || '').split(/\n/u).map((item) => item.trim().replace(/^[-*]\s*/, '')).filter(Boolean);
}

export function createPersonaEditorState() {
  return {
    name: '',
    confirmed: null,
    draft: null,
    confirmedVersion: 1,
    migration: {},
    legacyPrompt: '',
    dirty: false,
    attempts: [],
  };
}

export function buildStructuredPersonaDraft(confirmed, fields) {
  const base = JSON.parse(JSON.stringify(confirmed || {}));
  base.schema_version = '1.0';
  base.metadata = {
    ...(base.metadata || {}),
    display_name: String(fields.displayName || '').trim(),
    description: String(fields.description || '').trim(),
    kind: String(fields.kind || 'voice_filter'),
    language: String(fields.language || 'en-US').trim(),
  };
  base.transformation = {
    ...(base.transformation || {}),
    cleanup_strength: Number(fields.cleanup),
    persona_strength: Number(fields.strength),
    source_voice_retention: Number(fields.retention),
    target_length: String(fields.targetLength || 'similar'),
  };
  base.voice = {
    ...(base.voice || {}),
    formality: Number(fields.formality),
    directness: Number(fields.directness),
    warmth: Number(fields.warmth),
    humor: Number(fields.humor),
    vocabulary_complexity: Number(fields.vocabulary),
    sentence_length: String(fields.sentenceLength || 'short_to_medium'),
  };
  base.characterization = {
    ...(base.characterization || {}),
    core_impression: list(fields.coreImpression),
    speaking_habits: list(fields.speakingHabits),
    forbidden_devices: list(fields.forbidden),
  };
  base.meaning_lock = {
    ...(base.meaning_lock || {}),
    preserve: {
      core_meaning: true, speaker_intent: true, facts: true, names: true,
      numbers: true, dates_and_times: true, urls_and_code: true,
      uncertainty: true, negation: true, conditions: true, questions: true,
      commitments: true, commands_and_code: true,
    },
  };
  base.output_contract = {
    ...(base.output_contract || {}),
    output_only_rewritten_text: true,
    include_explanation: false,
    include_persona_label: false,
  };
  return base;
}

export function appendPersonaAttempt(attempts, attempt) {
  return [...(attempts || []), {
    attempt_id: String(attempt.attempt_id || `attempt-${Date.now()}`),
    persona_draft_version: Number(attempt.persona_draft_version || 1),
    source_text: String(attempt.source_text || ''),
    generated_text: String(attempt.generated_text || ''),
    created_at: attempt.created_at || new Date().toISOString(),
    model_id: String(attempt.model_id || 'unknown'),
    settings_snapshot: JSON.parse(JSON.stringify(attempt.settings_snapshot || {})),
  }];
}

export function comparableAttempts(attempts) {
  return (attempts || []).slice(-2);
}

export function createStructuredPersonaEditor({ doc, api = backendApi, showToast, onConfirmed } = {}) {
  const editor = doc?.getElementById?.('sdStructuredPersonaEditor');
  const fields = Object.fromEntries(Object.entries(FIELD_IDS).map(([key, id]) => [key, doc?.getElementById?.(id)]));
  let state = createPersonaEditorState();

  function setMessage(text, tone = 'info') {
    const element = doc?.getElementById?.('sdPersonaEditorMessage');
    if (!element) return;
    element.textContent = text;
    element.dataset.tone = tone;
  }

  function fieldValues() {
    return Object.fromEntries(Object.entries(fields).map(([key, element]) => [key, element?.value ?? '']));
  }

  function writeFields(structured) {
    const meta = structured?.metadata || {};
    const transform = structured?.transformation || {};
    const voice = structured?.voice || {};
    const char = structured?.characterization || {};
    const values = {
      displayName: meta.display_name, description: meta.description, kind: meta.kind,
      language: meta.language, cleanup: transform.cleanup_strength,
      strength: transform.persona_strength, retention: transform.source_voice_retention,
      targetLength: transform.target_length, formality: voice.formality,
      directness: voice.directness, warmth: voice.warmth, humor: voice.humor,
      vocabulary: voice.vocabulary_complexity, sentenceLength: voice.sentence_length,
      coreImpression: (char.core_impression || []).join('\n'),
      speakingHabits: (char.speaking_habits || []).join('\n'),
      forbidden: (char.forbidden_devices || []).join('\n'),
    };
    for (const [key, value] of Object.entries(values)) {
      if (fields[key]) fields[key].value = value ?? '';
    }
  }

  function currentDraft() {
    return buildStructuredPersonaDraft(state.confirmed, fieldValues());
  }

  function renderAttempts() {
    const container = doc?.getElementById?.('sdPersonaAttemptHistory');
    if (!container) return;
    container.replaceChildren();
    for (const attempt of comparableAttempts(state.attempts)) {
      const article = doc.createElement('article');
      article.className = 'sd-message-rescue-block';
      const heading = doc.createElement('strong');
      heading.textContent = `Attempt ${attempt.persona_draft_version} · ${new Date(attempt.created_at).toLocaleTimeString()}`;
      const source = doc.createElement('p');
      source.textContent = `Input: ${attempt.source_text}`;
      const output = doc.createElement('p');
      output.textContent = `Output: ${attempt.generated_text}`;
      article.append(heading, source, output);
      container.append(article);
    }
  }

  function render() {
    if (!editor) return;
    editor.hidden = !state.name;
    const status = doc.getElementById('sdPersonaStructuredDraftState');
    if (status) status.textContent = state.dirty || state.draft ? 'Draft' : `Confirmed v${state.confirmedVersion}`;
    const legacy = doc.getElementById('sdPersonaLegacyPrompt');
    if (legacy) legacy.textContent = state.legacyPrompt;
    const migration = doc.getElementById('sdPersonaMigrationStatus');
    if (migration) {
      const review = state.migration?.fields_requiring_review || [];
      migration.textContent = state.migration?.source_format
        ? `Legacy prompt preserved · migration confidence ${Math.round(Number(state.migration.confidence || 0) * 100)}% · ${review.length} fields require review.`
        : 'This persona is already structured.';
    }
    renderAttempts();
  }

  async function load(name) {
    if (!name) {
      state = createPersonaEditorState();
      render();
      return;
    }
    try {
      const payload = await api.fetchPersonaEditor(name);
      state = {
        ...createPersonaEditorState(),
        name,
        confirmed: payload.confirmed,
        draft: payload.draft,
        confirmedVersion: payload.confirmed_version || 1,
        migration: payload.migration || {},
        legacyPrompt: payload.legacy_prompt || '',
      };
      writeFields(payload.draft?.structured || payload.confirmed);
      render();
    } catch (error) {
      setMessage(`Could not open structured editor: ${error.message}`, 'danger');
    }
  }

  async function saveDraft() {
    const structured = currentDraft();
    const result = await api.savePersonaDraft(state.name, structured, state.confirmedVersion);
    state = { ...state, draft: result.draft, dirty: false };
    render();
    setMessage(`Draft v${result.draft?.draft_version || 1} saved separately.`, 'success');
  }

  async function discardDraft() {
    await api.discardPersonaDraft(state.name);
    state = { ...state, draft: null, dirty: false };
    writeFields(state.confirmed);
    render();
    setMessage('Draft discarded; confirmed values restored.', 'success');
  }

  async function confirmDraft() {
    const structured = currentDraft();
    const result = await api.confirmPersonaDraft(state.name, structured);
    state = {
      ...state,
      confirmed: result.structured,
      confirmedVersion: result.confirmed_version,
      draft: null,
      dirty: false,
      migration: { ...state.migration, confirmed: true },
    };
    writeFields(result.structured);
    render();
    setMessage(`Confirmed persona version ${result.confirmed_version}.`, 'success');
    showToast?.(`Confirmed ${state.name}.`, 'success');
    await onConfirmed?.(state.name);
  }

  async function testDraft() {
    const source = doc?.getElementById?.('sdPersonaStructuredTestText')?.value?.trim() || '';
    if (!source) {
      setMessage('Enter test text first.', 'warning');
      return;
    }
    const structured = currentDraft();
    setMessage('Generating preview…', 'info');
    try {
      const [result, models] = await Promise.all([
        api.testPersona({ structured, sample: source }),
        api.fetchLlmModels?.().catch?.(() => null) || null,
      ]);
      state = {
        ...state,
        attempts: appendPersonaAttempt(state.attempts, {
          persona_draft_version: (state.draft?.draft_version || state.confirmedVersion) + (state.dirty ? 1 : 0),
          source_text: source,
          generated_text: result?.result || '',
          model_id: models?.selected_model_id || 'unknown',
          settings_snapshot: structured,
        }),
      };
      renderAttempts();
      setMessage('Preview complete. Current and previous attempts are shown.', 'success');
    } catch (error) {
      setMessage(`Preview failed: ${error.message}`, 'danger');
    }
  }

  async function assistSpeakingHabits() {
    try {
      const guidance = await api.fetchPersonaFieldGuidance('characterization.speaking_habits');
      const promptFn = doc?.defaultView?.prompt;
      const answer = String(promptFn?.(`${guidance.purpose}\n\n${guidance.ask_about?.[0] || 'What behavior should this field capture?'}`) || '').trim();
      if (!answer) return;
      setMessage('Asking the local model for a field-only proposal…', 'info');
      const instruction = [
        `FIELD: characterization.speaking_habits`,
        `PURPOSE: ${guidance.purpose}`,
        `USER ANSWER: ${answer}`,
        `CURRENT VALUE:\n${fields.speakingHabits?.value || '(empty)'}`,
        ...(guidance.avoid || []),
        'Return only a proposed list, one observable behavior per line, at most 8 items. Do not change or discuss any other persona field.',
      ].join('\n');
      const result = await api.refinePersonaPrompt({ prompt: instruction, rules: guidance.avoid || [] });
      const proposal = String(result?.refined_prompt || result?.prompt || result?.result || '').trim();
      if (!proposal) throw new Error('The local model returned no proposal.');
      const confirmFn = doc?.defaultView?.confirm;
      if (confirmFn?.(`Apply this proposed speaking-habits value?\n\n${proposal}`)) {
        fields.speakingHabits.value = proposal;
        state = { ...state, dirty: true };
        render();
        setMessage('Applied the proposed field value to the draft only.', 'success');
      } else {
        setMessage('Proposal rejected; the draft was not changed.', 'info');
      }
    } catch (error) {
      setMessage(`AI Assist failed: ${error.message}`, 'danger');
    }
  }

  function init() {
    for (const field of Object.values(fields)) {
      field?.addEventListener?.('input', () => {
        state = { ...state, dirty: true };
        render();
      });
      field?.addEventListener?.('change', () => {
        state = { ...state, dirty: true };
        render();
      });
    }
    doc?.getElementById?.('sdPersonaSaveDraftButton')?.addEventListener?.('click', () => saveDraft().catch((error) => setMessage(error.message, 'danger')));
    doc?.getElementById?.('sdPersonaDiscardDraftButton')?.addEventListener?.('click', () => discardDraft().catch((error) => setMessage(error.message, 'danger')));
    doc?.getElementById?.('sdPersonaConfirmDraftButton')?.addEventListener?.('click', () => confirmDraft().catch((error) => setMessage(error.message, 'danger')));
    doc?.getElementById?.('sdPersonaStructuredTestButton')?.addEventListener?.('click', () => testDraft());
    doc?.getElementById?.('sdPersonaSpeakingHabitsAssist')?.addEventListener?.('click', () => assistSpeakingHabits());
    render();
    return { load };
  }

  return { init, load, saveDraft, discardDraft, confirmDraft, testDraft, assistSpeakingHabits, getState: () => state, currentDraft };
}
