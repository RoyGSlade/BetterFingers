// Draft state/render/event helpers extracted from main.js (Phase 1, A1.3).
// main.js stays the composition root: it owns the DOM element lookups and
// wires these functions to listeners in the same order as before. This module
// owns the draft/draftHistory state and everything that reads or renders it.
import {
  acceptDraft,
  clearDrafts,
  declineDraft,
  editDraft,
  fetchDrafts,
  fetchLatestDraft,
  retryDraft,
  rewriteDraft,
  searchHistory,
  sendDraft,
  speakDraft,
} from '../api/backend.js';

const STOP_REASON_LABELS = {
  manual: 'stopped manually',
  silence: 'auto-stopped on silence',
  max_duration: 'reached max length',
  max_recording_seconds: 'reached max length',
  error: 'stopped on error',
};

// User-facing summary: humanized duration + stop reason. The raw signal
// telemetry (samples/peak/rms) is developer diagnostics — kept out of the
// primary line and surfaced as a hover tooltip instead (see formatDraftMetadataDetail).
export function formatDraftMetadata(draft) {
  const metadata = draft?.metadata ?? {};
  if (!Object.keys(metadata).length) {
    return 'No recording metadata available.';
  }

  const duration = Number(metadata.duration_seconds || 0).toFixed(1);
  const stopReason = metadata.stop_reason || 'unknown';
  const stopLabel = STOP_REASON_LABELS[stopReason] || stopReason;
  return `${duration}s recording · ${stopLabel}`;
}

// The raw acoustic telemetry, for a hover tooltip / power users.
export function formatDraftMetadataDetail(draft) {
  const metadata = draft?.metadata ?? {};
  if (!Object.keys(metadata).length) {
    return '';
  }
  const rms = Number(metadata.rms_amplitude || 0).toFixed(5);
  const peak = Number(metadata.max_amplitude || 0).toFixed(5);
  const samples = metadata.sample_count ?? 0;
  const rate = metadata.sample_rate ?? 0;
  return `samples ${samples} @ ${rate} Hz · peak ${peak} · rms ${rms}`;
}

/**
 * @param {object} deps
 * @param {object} deps.elements draft-related DOM element references (looked up by main.js)
 * @param {object} deps.ui shared render helpers: setMessage, showToast, escapeHtml, renderSendResult
 * @param {object} deps.hooks cross-feature callbacks: getSelectedSendAction, gatherVoiceStudioSettings, onDraftEdited, refreshOutputSettings
 */
export function createDraftsFeature({ elements, ui, hooks }) {
  const els = elements;
  const { setMessage, showToast, escapeHtml, renderSendResult } = ui;
  const { getSelectedSendAction, gatherVoiceStudioSettings, onDraftEdited, refreshOutputSettings } = hooks;

  let latestDraft = null;
  let draftHistory = [];
  let historySearchTimer = null;

  function getLatestDraft() {
    return latestDraft;
  }

  function getDraftHistory() {
    return draftHistory;
  }

  function getDraftEditorText() {
    if (!els.draftFinalTextEl) {
      return latestDraft?.final_text ?? '';
    }

    return els.draftFinalTextEl.value ?? latestDraft?.final_text ?? '';
  }

  function getSelectedDraftText() {
    if (!els.draftFinalTextEl) {
      return getDraftEditorText();
    }

    const start = Number(els.draftFinalTextEl.selectionStart ?? 0);
    const end = Number(els.draftFinalTextEl.selectionEnd ?? 0);
    const value = getDraftEditorText();
    if (end > start) {
      return value.slice(start, end);
    }
    return value;
  }

  function renderTokenSummary(draft) {
    if (!els.draftTokenSummaryEl) {
      return;
    }

    if (!draft) {
      els.draftTokenSummaryEl.textContent = '0 tokens';
      delete els.draftTokenSummaryEl.dataset.state;
      return;
    }

    const tokenCount = Number(draft.token_count ?? 0);
    const tokenLimit = Number(draft.token_limit ?? 0);
    const longText = Boolean(draft.long_text || (tokenLimit && tokenCount > tokenLimit));
    els.draftTokenSummaryEl.textContent = tokenLimit
      ? `${tokenCount} / ${tokenLimit} tokens${longText ? ' · long text' : ''}`
      : `${tokenCount} tokens`;
    if (longText) {
      els.draftTokenSummaryEl.dataset.state = 'warning';
    } else {
      delete els.draftTokenSummaryEl.dataset.state;
    }
  }

  function setDraftControlsEnabled(enabled) {
    const status = latestDraft?.status ?? '';
    const hasDraft = enabled && Boolean(latestDraft?.id);
    const hasFinalText = hasDraft && Boolean(getDraftEditorText().trim());
    const canReview = hasDraft && status === 'pending';
    const canRetry = hasDraft && ['blocked', 'error'].includes(status);
    const canEdit = hasDraft;

    if (els.draftFinalTextEl) {
      els.draftFinalTextEl.disabled = !canEdit;
    }
    if (els.saveDraftEditButton) {
      els.saveDraftEditButton.disabled = !canEdit;
    }
    for (const button of [els.rewriteShorterButton, els.rewriteClearerButton, els.rewriteToneButton, els.rewriteCustomButton]) {
      if (button) {
        button.disabled = !canEdit || !hasFinalText;
      }
    }
    if (els.customRewriteInstructionEl) {
      els.customRewriteInstructionEl.disabled = !canEdit;
    }
    if (els.readSelectionButton) {
      els.readSelectionButton.disabled = !canEdit || !hasFinalText;
    }
    if (els.readFullDraftButton) {
      els.readFullDraftButton.disabled = !canEdit || !hasFinalText;
    }

    if (els.copyDraftButton) {
      els.copyDraftButton.disabled = !hasFinalText;
    }
    if (els.acceptDraftButton) {
      els.acceptDraftButton.disabled = !canReview;
    }
    if (els.declineDraftButton) {
      els.declineDraftButton.disabled = !enabled;
    }
    if (els.retryDraftButton) {
      els.retryDraftButton.disabled = !canRetry;
    }
    if (els.sendDraftButton) {
      els.sendDraftButton.disabled = !hasFinalText;
    }
  }

  // Confidence is rendered, not hidden (C4): show a score badge, tinted by how sure
  // the transcriber was, so the user can trust or double-check at a glance.
  function renderConfidenceBadge(draft) {
    const el = document.getElementById('draftConfidence');
    if (!el) return;
    const score = draft?.confidence?.score;
    if (score === null || score === undefined) {
      el.classList.add('hidden');
      return;
    }
    const pct = Math.round(score * 100);
    el.textContent = `${pct}% confident`;
    el.dataset.tone = score >= 0.65 ? 'success' : score >= 0.4 ? 'warning' : 'danger';
    el.classList.remove('hidden');
  }

  function renderDraft(draft) {
    latestDraft = draft ?? null;

    if (!latestDraft) {
      if (els.draftStatusEl) {
        els.draftStatusEl.textContent = 'No draft yet';
        delete els.draftStatusEl.dataset.state;
      }
      if (els.draftRawTextEl) {
        els.draftRawTextEl.textContent = 'Waiting for a recording...';
      }
      if (els.draftFinalTextEl) {
        els.draftFinalTextEl.value = 'Nothing to preview yet.';
        els.draftFinalTextEl.disabled = true;
      }
      renderTokenSummary(null);
      if (els.draftMetadataEl) {
        els.draftMetadataEl.textContent = 'No recording metadata yet.';
        els.draftMetadataEl.removeAttribute('title');
      }
      setMessage(els.draftMessageEl, '');
      renderSendResult(null);
      setDraftControlsEnabled(false);
      return;
    }

    if (els.draftStatusEl) {
      els.draftStatusEl.textContent = latestDraft.status ?? 'pending';
      els.draftStatusEl.dataset.state = ['blocked', 'error'].includes(latestDraft.status) ? 'error' : latestDraft.status === 'pending' ? 'connecting' : 'connected';
    }
    if (els.draftRawTextEl) {
      els.draftRawTextEl.textContent = latestDraft.raw_text || '(empty transcript)';
    }
    if (els.draftFinalTextEl) {
      els.draftFinalTextEl.value = latestDraft.final_text || '';
    }
    renderTokenSummary(latestDraft);
    renderConfidenceBadge(latestDraft);
    if (els.draftMetadataEl) {
      els.draftMetadataEl.textContent = formatDraftMetadata(latestDraft);
      const detail = formatDraftMetadataDetail(latestDraft);
      if (detail) {
        els.draftMetadataEl.title = detail;
      } else {
        els.draftMetadataEl.removeAttribute('title');
      }
    }

    if (latestDraft.error) {
      const reasons = Array.isArray(latestDraft.gate_reasons) && latestDraft.gate_reasons.length
        ? ` (${latestDraft.gate_reasons.join(', ')})`
        : '';
      setMessage(els.draftMessageEl, `${latestDraft.error}${reasons}`, 'danger');
    } else {
      const tokenLimit = Number(latestDraft.token_limit ?? 0);
      const tokenCount = Number(latestDraft.token_count ?? 0);
      if (latestDraft.long_text || (tokenLimit && tokenCount > tokenLimit)) {
        setMessage(els.draftMessageEl, 'Long text warning: this draft may need shortening before send.', 'warning');
      } else {
        setMessage(els.draftMessageEl, '');
      }
    }

    renderSendResult(latestDraft.send_result);

    setDraftControlsEnabled(true);
  }

  function renderDraftHistory(drafts) {
    if (!els.draftHistoryListEl) {
      return;
    }

    draftHistory = Array.isArray(drafts) ? drafts : [];
    els.draftHistoryListEl.innerHTML = '';

    if (!draftHistory.length) {
      els.draftHistoryListEl.innerHTML = '<span class="empty-state">No draft history yet.</span>';
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
      els.draftHistoryListEl.append(item);
    }
  }

  // Render FTS archive search results (C8) into the history list; clicking copies.
  function renderHistoryResults(results) {
    if (!els.draftHistoryListEl) return;
    els.draftHistoryListEl.innerHTML = '';
    if (!results || !results.length) {
      els.draftHistoryListEl.innerHTML = '<span class="empty-state">No matching history.</span>';
      return;
    }
    for (const row of results) {
      const item = document.createElement('button');
      item.className = 'draft-history-item';
      item.type = 'button';
      item.dataset.status = row.status ?? '';
      const title = document.createElement('strong');
      const when = row.created_at ? new Date(row.created_at).toLocaleString() : `#${row.id}`;
      title.textContent = `${when} · ${row.status ?? ''}`;
      const detail = document.createElement('small');
      const text = row.final_text || row.raw_text || 'No text';
      detail.textContent = text.length > 140 ? `${text.slice(0, 140)}...` : text;
      item.append(title, detail);
      item.addEventListener('click', async () => {
        const copyText = row.final_text || row.raw_text || '';
        try {
          await window.betterFingers?.writeClipboardText?.(copyText);
          showToast('Copied to clipboard.', 'success', 2000);
        } catch (error) {
          showToast(`Copy failed: ${error.message}`, 'danger');
        }
      });
      els.draftHistoryListEl.append(item);
    }
  }

  function handleHistorySearch(query) {
    const q = String(query || '').trim();
    if (historySearchTimer) clearTimeout(historySearchTimer);
    if (!q) {
      // Empty query restores the normal recent-drafts view.
      refreshDrafts().catch(() => {});
      return;
    }
    historySearchTimer = setTimeout(async () => {
      try {
        const payload = await searchHistory(q, 50);
        renderHistoryResults(payload?.results || []);
      } catch (error) {
        if (els.draftHistoryListEl) {
          els.draftHistoryListEl.innerHTML = `<span class="empty-state">Search failed: ${escapeHtml(error.message)}</span>`;
        }
      }
    }, 250);
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

  async function saveCurrentDraftEdit({ silent = false } = {}) {
    if (!latestDraft?.id) {
      return null;
    }

    const finalText = getDraftEditorText();
    if (finalText === (latestDraft.final_text ?? '')) {
      return latestDraft;
    }

    const rawTextBefore = latestDraft.raw_text ?? '';
    const draft = await editDraft(latestDraft.id, finalText);
    renderDraft(draft);
    await refreshDrafts();
    if (!silent) {
      setMessage(els.draftMessageEl, 'Draft edit saved.', 'success');
    }
    // Auto-learn dictionary terms from what the user corrected (C1).
    onDraftEdited(rawTextBefore, finalText).catch(() => {});
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
        setMessage(els.draftMessageEl, `Rewrite failed: ${result.error || 'Unknown error'}`, 'danger');
        return;
      }
      renderDraft(result);
      await refreshDrafts();
      setMessage(els.draftMessageEl, `${action === 'custom' ? 'Custom' : action} rewrite complete.`, 'success');
    } catch (error) {
      setMessage(els.draftMessageEl, `Rewrite failed: ${error.message}`, 'danger');
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
      setMessage(els.draftMessageEl, 'No draft text is available to read.', 'warning');
      return;
    }

    try {
      await saveCurrentDraftEdit({ silent: true });
      const settings = gatherVoiceStudioSettings();
      const result = await speakDraft(latestDraft.id, {
        text, voiceId: settings.base, speed: settings.speed, pitch: settings.pitch,
        extra: {
          blend: settings.blend, energy: settings.energy, warmth: settings.warmth,
          brightness: settings.brightness, pause_style: settings.pause_style,
        },
      });
      setMessage(els.draftMessageEl, result?.message || 'Draft read-aloud request sent.', result?.ok === false ? 'warning' : 'success');
    } catch (error) {
      setMessage(els.draftMessageEl, `Read aloud failed: ${error.message}`, 'danger');
    }
  }

  async function copyCurrentDraftText() {
    if (!latestDraft?.id) {
      return;
    }

    const text = getDraftEditorText();
    if (!text.trim()) {
      setMessage(els.draftMessageEl, 'No cleaned output is available to copy.', 'warning');
      return;
    }

    await window.betterFingers?.writeClipboardText?.(text);
    setMessage(els.draftMessageEl, 'Cleaned output copied to clipboard.', 'success');
  }

  async function handleSaveDraftEditClick() {
    if (!latestDraft?.id) {
      return;
    }

    els.saveDraftEditButton.disabled = true;
    els.saveDraftEditButton.textContent = 'Saving...';
    try {
      await saveCurrentDraftEdit();
    } catch (error) {
      setMessage(els.draftMessageEl, `Save failed: ${error.message}`, 'danger');
    } finally {
      els.saveDraftEditButton.textContent = 'Save Edit';
      setDraftControlsEnabled(Boolean(latestDraft));
    }
  }

  async function handleCopyClick() {
    try {
      await copyCurrentDraftText();
    } catch (error) {
      setMessage(els.draftMessageEl, `Copy failed: ${error.message}`, 'danger');
    }
  }

  async function handleAcceptClick() {
    if (!latestDraft?.id) {
      return;
    }

    try {
      await saveCurrentDraftEdit({ silent: true });
      const draft = await acceptDraft(latestDraft.id);
      renderDraft(draft);
      await refreshOutputSettings();
      setMessage(els.draftMessageEl, 'Draft accepted and queued for primary action send.', 'success');
    } catch (error) {
      setMessage(els.draftMessageEl, `Accept failed: ${error.message}`, 'danger');
    }
  }

  async function handleDeclineClick() {
    if (!latestDraft?.id) {
      return;
    }

    try {
      const draft = await declineDraft(latestDraft.id);
      renderDraft(draft);
      await refreshOutputSettings();
      setMessage(els.draftMessageEl, 'Draft declined.', 'success');
    } catch (error) {
      setMessage(els.draftMessageEl, `Decline failed: ${error.message}`, 'danger');
    }
  }

  async function handleClearHistoryClick() {
    try {
      await clearDrafts();
      renderDraft(null);
      await refreshDrafts();
      setMessage(els.draftMessageEl, 'Draft history cleared.', 'success');
    } catch (error) {
      setMessage(els.draftMessageEl, `Failed to clear history: ${error.message}`, 'danger');
    }
  }

  async function handleRetryClick() {
    if (!latestDraft?.id) {
      return;
    }

    els.retryDraftButton.disabled = true;
    els.retryDraftButton.textContent = 'Retrying...';
    try {
      const draft = await retryDraft(latestDraft.id);
      renderDraft(draft);
      await refreshDrafts();
      setMessage(els.draftMessageEl, draft.status === 'pending' ? 'Retry created a new draft.' : 'Retry completed with a draft state update.', draft.status === 'pending' ? 'success' : 'warning');
    } catch (error) {
      setMessage(els.draftMessageEl, `Retry failed: ${error.message}`, 'danger');
    } finally {
      els.retryDraftButton.textContent = 'Retry';
      setDraftControlsEnabled(Boolean(latestDraft));
    }
  }

  async function handleSendClick() {
    if (!latestDraft?.id) {
      return;
    }

    els.sendDraftButton.disabled = true;
    els.sendDraftButton.textContent = 'Sending...';
    try {
      await saveCurrentDraftEdit({ silent: true });
      const action = getSelectedSendAction();
      const draft = await sendDraft(latestDraft.id, { action });
      renderDraft(draft);
      await Promise.all([refreshDrafts(), refreshOutputSettings()]);
      setMessage(els.draftMessageEl, draft.send_result?.message || 'Draft send completed.', draft.send_result?.ok ? 'success' : 'danger');
    } catch (error) {
      setMessage(els.draftMessageEl, `Send failed: ${error.message}`, 'danger');
    } finally {
      els.sendDraftButton.textContent = 'Send / Copy';
      setDraftControlsEnabled(Boolean(latestDraft));
    }
  }

  function handleDraftTextInput() {
    const words = getDraftEditorText().trim().split(/\s+/).filter(Boolean).length;
    const tokenLimit = Number(latestDraft?.token_limit ?? 0);
    renderTokenSummary({
      token_count: words,
      token_limit: tokenLimit,
      long_text: Boolean(tokenLimit && words > tokenLimit),
    });
    setDraftControlsEnabled(Boolean(latestDraft));
  }

  async function handleGlobalShortcut(event) {
    const modifier = event.ctrlKey || event.metaKey;
    if (!modifier || !latestDraft?.id) {
      return;
    }

    const key = event.key.toLowerCase();
    try {
      if (event.shiftKey && key === 'enter') {
        event.preventDefault();
        els.sendDraftButton?.click();
      } else if (key === 'enter') {
        event.preventDefault();
        els.acceptDraftButton?.click();
      } else if (event.shiftKey && key === 'c') {
        event.preventDefault();
        await copyCurrentDraftText();
      } else if (key === 's') {
        event.preventDefault();
        await saveCurrentDraftEdit();
      } else if (key === 'd') {
        event.preventDefault();
        els.declineDraftButton?.click();
      }
    } catch (error) {
      setMessage(els.draftMessageEl, `Shortcut failed: ${error.message}`, 'danger');
    }
  }

  return {
    getLatestDraft,
    getDraftHistory,
    getDraftEditorText,
    getSelectedDraftText,
    renderTokenSummary,
    renderConfidenceBadge,
    setDraftControlsEnabled,
    renderDraft,
    renderDraftHistory,
    renderHistoryResults,
    handleHistorySearch,
    refreshLatestDraft,
    refreshDrafts,
    saveCurrentDraftEdit,
    runRewriteAction,
    runDraftTts,
    copyCurrentDraftText,
    handleSaveDraftEditClick,
    handleCopyClick,
    handleAcceptClick,
    handleDeclineClick,
    handleClearHistoryClick,
    handleRetryClick,
    handleSendClick,
    handleDraftTextInput,
    handleGlobalShortcut,
  };
}
