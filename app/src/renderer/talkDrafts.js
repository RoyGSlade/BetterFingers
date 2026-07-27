// Talk's draft-editor wiring (SPEC 6 keystone).
//
// Builds the REAL drafts feature -- the same features/drafts.js the shipping
// dashboard uses -- against Signal Desk's element ids, so accept / decline /
// retry / send / rewrite behave identically on both surfaces instead of being
// reimplemented and drifting apart.
//
// Lives in its own module rather than inline in the page because it has to be
// constructed BEFORE createTalkWorkspaceFeature (which takes it as
// `hooks.drafts`) while the elements it binds are described here, next to each
// other, where a mismatch is visible.
//
// OWNERSHIP, deliberately split so no element has two writers:
//   drafts.js    the editor's value, status line, token summary, metadata,
//                and the decision + rewrite controls.
//   talkWorkspace.js  the badge (it manages the sd-badge--* classes), the meta
//                strip, Send (its handleSendClick already routes through this
//                same feature), and action enablement.
// Mapping the badge or Send here as well would fire Send twice and let the two
// modules race on the badge.

import { createDraftsFeature } from './features/drafts.js';
import { showToast } from './lib/toast.mjs';

const el = (id, doc = document) => doc.getElementById(id);

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

export function setMessage(target, text, tone = 'info') {
  if (!target) return;
  target.textContent = text || '';
  if (tone) target.dataset.tone = tone;
}

/** The element map, exported so a test can assert it against drafts.js. */
export function collectTalkDraftElements(doc = document) {
  return {
    draftFinalTextEl: el('sdRefinedHero', doc),
    draftRawTextEl: el('sdRawTranscriptText', doc),
    draftMessageEl: el('sdDraftMessage', doc),
    draftMetadataEl: el('sdDraftMetadata', doc),
    draftTokenSummaryEl: el('sdDraftTokenSummary', doc),
    acceptDraftButton: el('sdAcceptButton', doc),
    declineDraftButton: el('sdDeclineButton', doc),
    retryDraftButton: el('sdRetryButton', doc),
    copyDraftButton: el('sdCopyButton', doc),
    saveDraftEditButton: el('sdSaveEditButton', doc),
    rewriteShorterButton: el('sdRewriteShorterButton', doc),
    rewriteClearerButton: el('sdRewriteClearerButton', doc),
    rewriteToneButton: el('sdRewriteToneButton', doc),
    rewriteCustomButton: el('sdRewriteCustomButton', doc),
    customRewriteInstructionEl: el('sdCustomRewriteInstruction', doc),
    readSelectionButton: el('sdReadSelectionButton', doc),
    readFullDraftButton: el('sdReadFullButton', doc),
  };
}

export function buildTalkDrafts(doc = document) {
  const elements = collectTalkDraftElements(doc);

  const drafts = createDraftsFeature({
    elements,
    ui: {
      setMessage,
      showToast,
      escapeHtml,
      // Talk has no send-result detail grid. Surface a failure on the status
      // line rather than dropping it silently.
      renderSendResult: (result) => {
        if (result?.error) setMessage(elements.draftMessageEl, String(result.error), 'danger');
      },
    },
    hooks: {
      // "Destination" is gone; the card now carries the insert method the user
      // actually controls. Empty string means profile default, matching the
      // old #sendActionSelect contract drafts.js already expects.
      getSelectedSendAction: () => el('sdDeliveryType', doc)?.value || '',
      gatherVoiceStudioSettings: () => ({}),
      onDraftEdited: () => {},
      refreshOutputSettings: () => {},
    },
  });

  // Start disabled: an editable-looking box with no draft behind it invites
  // typing that has nowhere to land. drafts.js re-enables on the first draft.
  drafts.setDraftControlsEnabled?.(false);

  bindReviseDrawer(doc);
  return drafts;
}

/**
 * The Revise button toggles the rewrite drawer. It was a documented stub with
 * no handler, because there was no editor for a rewrite to act on.
 */
export function bindReviseDrawer(doc = document) {
  const drawer = el('sdReviseDrawer', doc);
  const button = el('sdReviseButton', doc);
  if (!drawer || !button) return;

  button.setAttribute('aria-expanded', 'false');
  button.addEventListener('click', () => {
    const open = drawer.hidden;
    drawer.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
  });
}
