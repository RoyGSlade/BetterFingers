// Production composition root for the Signal Desk UI (signal-desk.html).
//
// Mirrors the wiring signal-desk-preview.html's ~10 script blocks establish
// (see that file for the reference adapter shapes), but as one module, with
// every list starting empty and populated only from the real backend -- no
// sample or placeholder data literals anywhere below.
//
// Construction order matters where one feature's hooks close over another:
// drafts must exist before Talk/Library (they take it as hooks.drafts), and
// several later hooks reference `let`-declared features assigned earlier in
// this function but not invoked until a real user interaction happens well
// after construction finishes -- same hoisting-safe pattern main.js documents
// for the legacy dashboard.

import * as api from '../api/backend.js';
import { showToast } from '../lib/toast.mjs';
import { setMessage } from '../lib/message.mjs';
import { autowireMode, AUTOWIRE_SIGNAL_DESK_VALUE } from '../lib/autowire.mjs';

import { createSignalDeskShellFeature, collectShellElements } from '../features/signalDeskShell.js';
import { createShortcutsFeature, describeShortcuts, ACTIONS } from '../features/shortcuts.js';
import { createStatusBarFeature, collectStatusBarElements } from '../features/statusBar.js';
import { createBackendBannerFeature, collectBackendBannerElements } from '../features/backendBanner.js';
import { createDraftsFeature } from '../features/drafts.js';
import { createTalkWorkspaceFeature, collectTalkElements } from '../features/talkWorkspace.js';
import { createTalkCaptureFeature, collectTalkCaptureElements } from '../features/talkCapture.js';
import { createOverlayBridgeFeature } from '../features/overlayBridge.js';
// Only the element collector -- talkDrafts.js has no import-time side effects,
// and its map is the already-reviewed description of which Signal Desk ids
// drafts.js should own (and which, like Send, it deliberately should not).
import { collectTalkDraftElements } from '../talkDrafts.js';
import { createTalkTeachingFeature, collectTalkTeachingElements } from '../features/talkTeaching.js';
import { createPersonaLearningFeature } from '../features/personaLearning.js';
import { createLibraryWorkspaceFeature, collectLibraryElements } from '../features/libraryWorkspace.js';
import {
  createStudioWorkspaceFeature,
  collectStudioElements,
} from '../features/studioWorkspace.js';
import {
  createUtilitiesWorkspaceFeature,
  collectUtilitiesElements,
  UTILITIES_SECTION_META,
} from '../features/utilitiesWorkspace.js';
import { createSettingsWorkspaceFeature, collectSettingsElements } from '../features/settingsWorkspace.js';
import { createVoiceStudioFeature } from '../features/voiceStudio.js';
import { createPersonasFeature } from '../features/personas.js';
import { createPersonaFlow, collectPersonaWizardElements } from '../features/personaFlow.js';
import {
  createApplicationProfilesFeature,
  collectAppProfileElements,
} from '../features/applicationProfiles.js';
import {
  createWorkflowBuilderFeature,
  collectWorkflowElements,
} from '../features/workflowBuilder.js';
import {
  createGameSetupWizardFeature,
  collectGameSetupElements,
} from '../features/gameSetupWizard.js';
import { createContactsFeature, collectContactElements } from '../features/contacts.js';
import { createContactWizard, collectContactWizardElements } from '../features/contactWizard.js';
import { createOnboardingFlow, collectOnboardingElements } from '../features/onboardingFlow.js';
import {
  needsConsent,
  resolveOnboardingGate,
  createConsentController,
} from '../features/onboardingConsent.js';
import { createFirstRunFeature, collectFirstRunElements } from '../features/firstRun.js';
import { initMessageRescuePanel } from '../features/messageRescuePanel.js';
import { initTextPlayground } from '../features/textPlayground.js';

// Same implementation main.js's own escapeHtml wraps (drafts.js's `ui.escapeHtml`
// contract) -- kept local since drafts.js intentionally has no DOM/string-utils
// import of its own.
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (ch) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]),
  );
}

/**
 * Fetches the persona list without ever downgrading a good list to an empty one.
 *
 * The product owner's build rendered #sdSetCurrentPreset with ZERO options on a
 * clean profile. That cannot be a data problem: llm_engine.load_personas_v2()
 * falls back to _DEFAULT_PERSONAS whenever personas.yaml is missing, empty or
 * corrupt, so a healthy backend always answers with at least the built-ins. An
 * empty list therefore only ever means the REQUEST failed -- and the old code
 * turned that into `loadedPersonas = {}` silently, presenting a fault as if the
 * user simply had no personas.
 *
 * Three rules, all about not lying to the user:
 *   * a failure KEEPS the previous list rather than blanking a working dropdown
 *     (and the user's current selection with it);
 *   * it is retried once, because the field failure is a slow first response
 *     against api/backend.js's 2500 ms budget, not a permanently dead endpoint;
 *   * an empty or non-object payload counts as a failure, not as an empty state.
 *
 * @param {() => Promise<object>} fetchPersonas
 * @param {object} previous last known-good list, returned unchanged on failure
 * @returns {Promise<{personas: object, failed: boolean}>}
 */
export async function loadPersonaList(fetchPersonas, previous = {}) {
  const usable = (value) => Boolean(value)
    && typeof value === 'object'
    && !Array.isArray(value)
    && Object.keys(value).length > 0;

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const fetched = await fetchPersonas();
      if (usable(fetched)) return { personas: fetched, failed: false };
    } catch (_error) {
      // fall through to the retry / to the caller's last-good list
    }
  }
  return { personas: previous, failed: true };
}

/**
 * @param {Document} doc
 * @returns {{ destroy(): void }} teardown handle -- closes the voice-status
 *   socket, clears the status-bar poll, and tears down the Talk signal core.
 */
export function startSignalDeskApp(doc = document) {
  // --- Shell + keyboard shortcuts ------------------------------------------

  const shell = createSignalDeskShellFeature({ elements: collectShellElements(doc) });
  shell.init('talk');

  const shortcutSheet = doc.getElementById('sdShortcutSheet');
  const shortcutSheetBody = doc.getElementById('sdShortcutSheetBody');
  const clickById = (id) => doc.getElementById(id)?.click();

  function renderShortcutSheet(supported) {
    if (!shortcutSheetBody) return;
    shortcutSheetBody.innerHTML = describeShortcuts(supported)
      .map(
        (group) =>
          `<div class="sd-shortcut-group">` +
          `<span class="sd-shortcut-group__label">${escapeHtml(group.group)}</span>` +
          group.items
            .map(
              (item) =>
                `<div class="sd-shortcut-row">` +
                `<span class="sd-shortcut-row__label">${escapeHtml(item.label)}</span>` +
                `<kbd class="sd-shortcut-row__keys">${escapeHtml(item.accelerator)}</kbd>` +
                `</div>`,
            )
            .join('') +
          `</div>`,
      )
      .join('');
  }

  const setShortcutSheetOpen = (open) => {
    if (shortcutSheet) shortcutSheet.hidden = !open;
  };

  const shortcutHandlers = {
    [ACTIONS.GO_TALK]: () => shell.goTo('talk'),
    [ACTIONS.GO_LIBRARY]: () => shell.goTo('library'),
    [ACTIONS.GO_STUDIO]: () => shell.goTo('studio'),
    [ACTIONS.GO_UTILITIES]: () => shell.goTo('utilities'),
    [ACTIONS.GO_SETTINGS]: () => shell.goTo('settings'),
    [ACTIONS.TOGGLE_CONTEXT]: () => shell.toggleContextCollapsed(),
    [ACTIONS.SHOW_HELP]: () => setShortcutSheetOpen(true),
    [ACTIONS.SEND]: () => clickById('sdSendButton'),
    [ACTIONS.ACCEPT]: () => clickById('sdAcceptButton'),
    [ACTIONS.DECLINE]: () => clickById('sdDeclineButton'),
    [ACTIONS.RETRY]: () => clickById('sdRetryButton'),
    [ACTIONS.SAVE_EDIT]: () => clickById('sdSaveEditButton'),
    [ACTIONS.COPY]: () => clickById('sdCopyButton'),
    [ACTIONS.LISTEN]: () => clickById('sdListenButton'),
    [ACTIONS.REVISE]: () => clickById('sdReviseButton'),
    [ACTIONS.CANCEL]: () => {
      if (shortcutSheet && !shortcutSheet.hidden) {
        setShortcutSheetOpen(false);
        return;
      }
      doc.activeElement?.blur?.();
    },
  };

  renderShortcutSheet(Object.keys(shortcutHandlers));
  doc.getElementById('sdShortcutSheetClose')?.addEventListener('click', () => setShortcutSheetOpen(false));

  const shortcuts = createShortcutsFeature({ handlers: shortcutHandlers, doc });
  shortcuts.init();

  // --- Status bar (application status, SPEC 3d) ---------------------------

  const statusBar = createStatusBarFeature({ elements: collectStatusBarElements(doc), api });
  statusBar.refresh().catch(() => {});
  const statusBarInterval = setInterval(() => statusBar.refresh().catch(() => {}), 3000);

  // --- Backend health / version banner + Quit (Wave 11B) -------------------
  //
  // Polled on the same 3s cadence as the status bar and for the same reason:
  // the conditions it reports (sidecar crashed, restarting, not answering,
  // built for a different app version) all arise between user actions, so
  // there is no event to hang it on. It renders nothing until one is real.
  const backendBanner = createBackendBannerFeature({
    elements: collectBackendBannerElements(doc),
    api,
    hooks: { confirmFn: (message) => doc.defaultView?.confirm?.(message) ?? true },
  });
  backendBanner.init();
  backendBanner.refresh().catch(() => {});
  const backendBannerInterval = setInterval(() => backendBanner.refresh().catch(() => {}), 3000);

  // --- Shared send-action state (drafts.js's hooks.getSelectedSendAction) --
  //
  // Wave 2: the Talk Delivery segmented control is now the single source of
  // truth for the insertion method, and talkWorkspace.resolveSendAction()
  // reproduces the profile-derived default this function used to compute on its
  // own. So the default lives in exactly one place, and an explicit user choice
  // overrides it instead of being silently ignored (which is what happened when
  // two competing controls both claimed to own this decision).
  //
  // talkWorkspace is constructed further down but only ever CALLED from a later
  // user interaction or from the initial refresh at the bottom of this
  // function -- the same hoisting-safe pattern main.js documents for the legacy
  // dashboard.

  let outputSettings = null;
  let profileSettings = null;

  // talkWorkspace needs both halves of the picture: send_mode/capabilities from
  // /runtime/output-settings, and the confidence thresholds, which are profile
  // settings and are NOT part of the output-settings payload. Merging them here
  // (rather than having the Talk module fetch anything itself) keeps that module
  // free of network access, which is what makes it unit-testable.
  function talkSettingsSnapshot() {
    if (!outputSettings && !profileSettings) return null;
    return { ...(profileSettings || {}), ...(outputSettings || {}) };
  }

  function pushTalkSettings() {
    talkWorkspace?.setOutputSettings?.(talkSettingsSnapshot());
  }

  async function refreshOutputSettings() {
    try {
      outputSettings = await api.fetchOutputSettings();
    } catch (_error) {
      outputSettings = null;
    }
    pushTalkSettings();
    renderDeliveryMode();
    return outputSettings;
  }

  // The active profile's settings carry confidence_force_review_enabled /
  // confidence_force_review_below / confidence_auto_send_above (rendered
  // read-only in Talk, owned by Settings) and current_preset (the active
  // persona Talk displays).
  async function refreshProfileSettings() {
    try {
      const payload = await api.fetchProfiles();
      profileSettings = payload?.settings ?? null;
    } catch (_error) {
      profileSettings = null;
    }
    pushTalkSettings();
    renderActivePersona();
    renderDeliveryMode();
    return profileSettings;
  }

  function getSelectedSendAction() {
    return talkWorkspace?.getSelectedSendAction?.() ?? 'copy_only';
  }

  // Wave 2: drafts.js's `ui.renderSendResult(sendResult)` contract is finally
  // honoured. It used to be a deliberate no-op because Talk had no send-result
  // panel, which meant a send that silently fell back to the clipboard was
  // indistinguishable from one that typed into the target app. drafts.js passes
  // only the send_result, so the draft itself (needed for the submission state)
  // is read back from the same feature instance.
  function renderSendResult(sendResult) {
    talkWorkspace?.renderSendResult?.(sendResult ?? null, drafts?.getLatestDraft?.() ?? null);
  }

  // Talk DISPLAYS the active persona; Settings OWNS it (it is the profile field
  // `current_preset`, behind the Settings save bar). See the markup comment in
  // signal-desk.html for why this is not an editable picker in this wave.
  // Same display-here / own-in-Settings split as persona and the confidence
  // thresholds: `send_mode` is a profile field behind the Settings save bar.
  const SEND_MODE_TEXT = {
    auto_send: 'Send immediately',
    review_first: 'Review first',
  };

  function renderDeliveryMode() {
    const el = doc.getElementById('sdDeliveryModeValue');
    if (!el) return;
    const mode = outputSettings?.send_mode ?? profileSettings?.send_mode;
    el.textContent = mode ? SEND_MODE_TEXT[mode] || mode : '—';
  }

  function renderActivePersona() {
    const nameEl = doc.getElementById('sdTalkActivePersona');
    const noteEl = doc.getElementById('sdTalkActivePersonaNote');
    if (!nameEl) return;
    const preset = profileSettings?.current_preset;
    nameEl.textContent = preset || '—';
    if (noteEl) {
      noteEl.textContent = preset ? '' : 'No persona selected for this profile.';
    }
  }

  // --- Utilities workspace (models, speech input, text tools, diagnostics,
  //     advanced -- constructed before drafts since drafts.hooks.onDraftEdited
  //     feeds its already-real suggestFromEdit()) ---------------------------

  const utilitiesElements = collectUtilitiesElements(doc);
  const utilitiesWorkspace = createUtilitiesWorkspaceFeature({
    elements: utilitiesElements,
    hooks: { showToast, confirmFn: (message) => doc.defaultView?.confirm?.(message) },
  });
  utilitiesWorkspace.init('models');

  // messageRescuePanel.js / textPlayground.js are "REUSED VERBATIM" by
  // utilitiesWorkspace.js's own header comment -- it side-effect-imports them
  // and used to rely on their import-time self-init. Both now gate that
  // self-init behind lib/autowire.mjs's shouldAutowire() (data-bf-autowire on
  // <html>), which this page deliberately does not set (so importing them
  // doesn't reach into a document that isn't theirs) -- so this composition
  // root is now the explicit caller autowire.mjs's own contract expects.
  initMessageRescuePanel({ doc });
  initTextPlayground({ doc });

  function syncUtilitiesContext(sectionId) {
    const meta = UTILITIES_SECTION_META[sectionId];
    const labelEl = doc.getElementById('sdUtilCtxSectionLabel');
    const descEl = doc.getElementById('sdUtilCtxSectionDesc');
    if (labelEl) labelEl.textContent = meta?.label || '';
    if (descEl) descEl.textContent = meta?.description || '';
  }
  doc.querySelectorAll('[data-util-nav]').forEach((button) => {
    button.addEventListener('click', () => {
      const sectionId = button.dataset.utilNav;
      utilitiesWorkspace.goToSection(sectionId);
      syncUtilitiesContext(sectionId);
    });
  });
  syncUtilitiesContext('models');

  // --- Voice Studio (shared: Studio's blend strip + drafts' rewrite hook) -

  const voiceStudio = createVoiceStudioFeature({
    ui: { setMessage, showToast },
    hooks: {
      // Matches the preview's own choice: Studio has no settings-save-bar
      // equivalent to mark dirty against, so this is a deliberate no-op, not
      // a dropped call.
      markProfileDirty: () => {},
      // No voice-cloning status/badge markup exists on this page (Studio
      // only ever built the blend strip) -- same deliberate no-op.
      renderVoiceCloningPanel: () => {},
    },
  });
  voiceStudio.init?.({ doc });
  voiceStudio.refreshVoices?.(doc).catch(() => {});

  const voiceCloneConsent = doc.getElementById('voiceCloneConsent');
  const voiceCloneUpload = doc.getElementById('voiceCloneUploadButton');
  const syncVoiceCloneConsent = () => {
    if (voiceCloneUpload) voiceCloneUpload.disabled = !voiceCloneConsent?.checked;
  };
  voiceCloneConsent?.addEventListener('change', syncVoiceCloneConsent);
  syncVoiceCloneConsent();

  // --- Drafts (shared state/business logic for Talk + Library) ------------
  //
  // Wave 2 correction. This used to pass `elements: {}` on the reasoning that
  // "Talk renders the real state itself". That was wrong in two ways, and both
  // shipped as dead controls on the production page:
  //
  //   1. drafts.js does NOT bind its own click listeners -- the host does. With
  //      an empty element map and no listeners here, Save Edit, Accept,
  //      Decline, Retry, Copy and all four rewrite buttons were inert, and the
  //      keyboard shortcuts that .click() them (ACTIONS.SAVE_EDIT/ACCEPT/... in
  //      the map above) clicked buttons nothing was listening to.
  //   2. Nothing called saveCurrentDraftEdit(), which is the only caller of
  //      hooks.onDraftEdited -- so the dictionary-suggestion hook below could
  //      never fire either, and neither could teach-from-edit.
  //
  // The element map comes from talkDrafts.js, which already describes exactly
  // this binding for the preview page (importing only the collector; that
  // module has no import-time side effects). Note it deliberately omits the
  // Send button: talkWorkspace.js owns #sdSendButton, and two modules writing
  // one button's disabled state is how they end up racing.

  const draftElements = collectTalkDraftElements(doc);

  // Assigned below; the hooks that reference it only fire on a later user
  // action -- the same hoisting-safe pattern documented in this file's header.
  let talkTeaching;

  const drafts = createDraftsFeature({
    elements: draftElements,
    ui: { setMessage, showToast, escapeHtml, renderSendResult },
    hooks: {
      getSelectedSendAction,
      gatherVoiceStudioSettings: () => voiceStudio.gatherVoiceStudioSettings(),
      // Two consumers of the same edit, composed rather than one replacing the
      // other: dictionary suggestions (already real) and teach-from-edit.
      // Must return a promise: drafts.js calls onDraftEdited(...).catch(...)
      // directly on the return value.
      onDraftEdited: async (rawText, editedText) => {
        // The model output is NOT recoverable here: saveCurrentDraftEdit()
        // calls renderDraft(draft) -- reassigning latestDraft to the POST-edit
        // value -- before it fires this hook, so getLatestDraft().final_text is
        // already the edited text by now. modelTextSnapshot is captured at the
        // start of whichever user action is about to save (see
        // snapshotModelText below).
        talkTeaching?.onDraftEdited?.({ rawText, modelText: modelTextSnapshot, editedText });
        await utilitiesWorkspace.suggestFromEdit(rawText, editedText);
      },
      refreshOutputSettings,
    },
  });

  // Teach-from-edit needs all three texts: what the user said, what the MODEL
  // wrote, and what the user changed it to. Only the middle one is perishable
  // -- saveCurrentDraftEdit() overwrites latestDraft.final_text before the
  // onDraftEdited hook runs -- so it is captured here, at the start of every
  // user action that can trigger a save. A rewrite counts: its output is model
  // output too, so the snapshot taken before the NEXT save is correctly the
  // rewritten text.
  let modelTextSnapshot = '';
  function snapshotModelText() {
    modelTextSnapshot = drafts?.getLatestDraft?.()?.final_text ?? '';
  }

  // The listeners drafts.js expects its host to provide.
  const bindClick = (el, handler) => el?.addEventListener?.('click', () => handler());
  const bindSavingClick = (el, handler) =>
    bindClick(el, () => {
      snapshotModelText();
      return handler();
    });

  bindSavingClick(draftElements.saveDraftEditButton, () => drafts.handleSaveDraftEditClick());
  bindClick(draftElements.acceptDraftButton, () => drafts.handleAcceptClick());
  bindClick(draftElements.declineDraftButton, () => drafts.handleDeclineClick());
  bindClick(draftElements.retryDraftButton, () => drafts.handleRetryClick());
  bindClick(draftElements.copyDraftButton, () => drafts.handleCopyClick());
  // runRewriteAction(button, action, customInstruction) takes the button first
  // so it can show its own in-flight label.
  bindSavingClick(draftElements.rewriteShorterButton, () =>
    drafts.runRewriteAction(draftElements.rewriteShorterButton, 'shorter'),
  );
  bindSavingClick(draftElements.rewriteClearerButton, () =>
    drafts.runRewriteAction(draftElements.rewriteClearerButton, 'clearer'),
  );
  bindSavingClick(draftElements.rewriteToneButton, () =>
    drafts.runRewriteAction(draftElements.rewriteToneButton, 'tone'),
  );
  bindSavingClick(draftElements.rewriteCustomButton, () =>
    drafts.runRewriteAction(
      draftElements.rewriteCustomButton,
      'custom',
      draftElements.customRewriteInstructionEl?.value || '',
    ),
  );
  bindSavingClick(draftElements.readSelectionButton, () => drafts.runDraftTts(true));
  bindSavingClick(draftElements.readFullDraftButton, () => drafts.runDraftTts(false));
  draftElements.draftFinalTextEl?.addEventListener?.('input', () => drafts.handleDraftTextInput());

  // Start disabled: an editable-looking box with no draft behind it invites
  // typing that has nowhere to land. drafts.js re-enables on the first draft.
  drafts.setDraftControlsEnabled?.(false);

  // --- Talk workspace -------------------------------------------------------

  const talkWorkspace = createTalkWorkspaceFeature({
    elements: collectTalkElements(doc),
    hooks: {
      showToast,
      // Send performs a silent save first (drafts.js's handleSendClick calls
      // saveCurrentDraftEdit({silent:true})), so it can fire the edit hook too
      // and needs the same pre-save snapshot the other saving actions take.
      drafts: {
        ...drafts,
        handleSendClick: () => {
          snapshotModelText();
          return drafts.handleSendClick();
        },
      },
      // The segmented control is the single source of truth for the insertion
      // method; drafts.js reads it back through getSelectedSendAction() at send
      // time, so nothing needs to be cached here -- this hook exists so the
      // choice is observable (and so a future per-draft persistence has a seam).
      onDeliverySelectionChanged: () => {},
      // The Revise button toggles the rewrite drawer. talkWorkspace owns the
      // button's click listener, so the drawer toggle arrives as this hook
      // rather than a second listener on the same element.
      onReviseRequested: () => {
        const drawer = doc.getElementById('sdReviseDrawer');
        const button = doc.getElementById('sdReviseButton');
        if (!drawer) return;
        const opening = drawer.hidden;
        drawer.hidden = !opening;
        button?.setAttribute('aria-expanded', String(opening));
      },
      // Talk links to the threshold owner rather than duplicating it.
      onOpenConfidenceSettings: () => {
        shell.goTo('settings');
        settingsWorkspace.goToSection('review');
      },
    },
  });
  talkWorkspace.init();

  // --- Talk capture actions (Start / Stop / Emergency Stop) ----------------
  //
  // Before this, the production Signal Desk had NO capture control at all: the
  // ring was display-only and the legacy dashboard's #toggleRecordingButton
  // does not exist on this page, so the global hotkey was the only path that
  // worked. Both paths now converge on talkCapture.js's reducer, with the
  // voice-status stream authoritative -- so the buttons can never disagree with
  // what the recorder is actually doing.

  const talkCapture = createTalkCaptureFeature({
    elements: collectTalkCaptureElements(doc),
    hooks: { api, showToast },
  });
  talkCapture.init();

  // --- Teach from this edit (restores the D-0018 trigger) ------------------
  //
  // Saving an edit OFFERS to learn; it never learns. The only path that reaches
  // the network is personaLearning.js's own prepare -> consent -> confirm
  // sequence, and this is a dedicated instance of it wired to Talk's live edit
  // rather than to Studio's teach panel. Two instances, never one shared: they
  // read different sources and render different ids (talkTeaching.js owns the
  // sdTalkTeach* elements; personaLearning's own `elements` stays empty so it
  // renders nothing and cannot fight over them).

  const talkPersonaLearning = createPersonaLearningFeature({
    elements: {},
    hooks: {
      getPersonaName: () => talkTeaching?.getState?.().personaName || '',
      getDraftPair: () => ({
        raw: talkTeaching?.getState?.().rawText || '',
        // The FINAL EDITED text is what gets taught -- teaching the model its
        // own output back would be a no-op example.
        out: talkTeaching?.getState?.().editedText || '',
      }),
    },
  });

  talkTeaching = createTalkTeachingFeature({
    elements: collectTalkTeachingElements(doc),
    hooks: {
      showToast,
      personaLearning: talkPersonaLearning,
      getActivePersonaName: () => String(profileSettings?.current_preset ?? '').trim(),
    },
  });
  talkTeaching.init();

  // --- The two floating windows (Wave 11C) ---------------------------------
  //
  // Until now this page had NO caller for `overlay:update-status` or
  // `review:show`. The windows ship and their QA drives them, but the only
  // renderer that ever reached them was the legacy `main.js` -- so since the
  // Wave 11 default flip, every user got no floating capture overlay while
  // dictating and no Review Deck at all. That is the product gap Wave 11B
  // recorded against 21 parity rows; this is its caller.
  //
  // It is a third consumer of the same voice-status stream, not a replacement
  // for either existing one: the in-page ring (talkWorkspace) and the action row
  // (talkCapture) are what the user sees when the dashboard is focused, and the
  // overlay is what they see when it is not. All show/hide policy stays in the
  // main process, so both pages put the windows away identically.
  const overlayBridge = createOverlayBridgeFeature({
    bridge: doc.defaultView?.betterFingers,
    hooks: {
      // The rewrite/edit statuses carry no draft, so a re-push has to fetch the
      // current one. Reuses the drafts feature rather than fetching here.
      getLatestDraft: () => drafts.refreshLatestDraft(),
      // Deliberately not a toast: the overlay is a secondary view of state the
      // page is already showing, so a failed forward is a console note, not an
      // interruption.
      onError: (error) => console.warn('[overlay-bridge] forward failed:', error),
    },
  });

  const voiceStatusConnection = api.connectVoiceStatus({
    // Three consumers, not one instead of the others: talkWorkspace owns the
    // ring/status/meter, talkCapture owns the action row's enablement, and
    // overlayBridge owns the two floating windows.
    onMessage: (payload) => {
      talkWorkspace.handleVoiceStatusMessage(payload);
      talkCapture.handleVoiceStatusMessage(payload);
      overlayBridge.handleVoiceStatusMessage(payload);
    },
    // Wave 11B: these two were empty closures, which meant a dropped voice
    // stream was completely invisible -- the Signal Core simply stopped moving
    // and nothing on screen said why. Both now report into the status bar's
    // Stream cell. onError carries the reason as the cell's detail rather than
    // swallowing it.
    onConnectionChange: (state, detail) => statusBar.setStreamState(state, detail),
    onError: (error) => statusBar.setStreamState('error', error?.message || ''),
  });

  // --- Library workspace ---------------------------------------------------

  // Wave 4. Library now drives the real /library/* surface, so it needs three
  // things the Phase-3 adapter did without:
  //
  //   drafts        -- to hand a reopened record to the Talk editor
  //   talkWorkspace -- to repaint Talk's action row for that record (a bare
  //                    renderDraft leaves Send/Revise dead until the next
  //                    voice-status message, the same defect Wave 2 fixed for
  //                    the initial load)
  //   shell         -- to actually take the user to Talk once it is loaded
  //
  // All three are public entry points of features constructed above; Library
  // never reaches into their internals. Reopen is the only caller.
  const libraryWorkspace = createLibraryWorkspaceFeature({
    elements: collectLibraryElements(doc),
    hooks: {
      showToast,
      drafts,
      talkWorkspace,
      shell,
    },
  });
  libraryWorkspace.init();

  // --- Studio workspace (constructs its own personaLearning internally --
  //     do not build a second createPersonaLearningFeature here) -----------

  let personaFlow; // assigned below; hooks only fire on later user clicks.

  const studioWorkspace = createStudioWorkspaceFeature({
    elements: collectStudioElements(doc),
    hooks: {
      showToast,
      confirmFn: (message) => doc.defaultView?.confirm?.(message),
      onNewPersonaRequested: () => personaFlow?.openWizard(),
      onOpenFoundryRequested: () => personaFlow?.openFoundry(),
      onEditPersonaRequested: (name) => personaFlow?.openWizardForEdit(name),
      getActivePersonaName: () => String(profileSettings?.current_preset ?? '').trim(),
    },
  });
  studioWorkspace.init();

  // --- Settings workspace ---------------------------------------------------

  const settingsElements = collectSettingsElements(doc);
  const settingsWorkspace = createSettingsWorkspaceFeature({
    elements: settingsElements,
    hooks: { showToast, confirmFn: (message) => doc.defaultView?.confirm?.(message) },
  });
  settingsWorkspace.init('profile');
  doc.querySelectorAll('[data-set-nav]').forEach((button) => {
    button.addEventListener('click', () => settingsWorkspace.goToSection(button.dataset.setNav));
  });

  // --- Application profiles (Wave 7) ---------------------------------------
  //
  // Owns the /app-context poll and the Settings > AI Cleanup > Application
  // Profiles group, and pushes each new context snapshot to the status bar --
  // the same push-in pattern the contacts feature uses for the contact cell,
  // and for the same reason: the status bar's own poll does not fetch this, so
  // without the push the next health poll would clear the cell.
  //
  // If api has no application-context methods (the main-process proxy's route
  // allowlist has to carry /app-context/* before they can exist), the feature
  // reports itself unavailable in one sentence and paints nothing. It never
  // invents a profile to fill the gap.
  const applicationProfiles = createApplicationProfilesFeature({
    elements: collectAppProfileElements(doc),
    api,
    hooks: {
      showToast,
      escapeHtml,
      onContextChanged: (context) => statusBar.setAppContext(context),
    },
  });
  applicationProfiles.init();

  // --- Launch workflows (Wave 9) ------------------------------------------
  //
  // Owns Utilities > Advanced > Launch Workflows: describe, compile, validate,
  // exact preview, explicit approval, save disabled-or-enabled, run only after
  // approval.
  //
  // WHERE THE VALIDATION CONTEXT COMES FROM. The confirmed application registry
  // is owned by the Electron main process (main/applicationRegistry.js), which
  // is the side that can see the desktop; it reaches the renderer over the
  // typed IPC bridge. Until that bridge lands (documented as D-4 in
  // docs/release/WAVE9_INTEGRATION_DIFFS.md) the registry is EMPTY, and empty
  // is the safe answer rather than a broken one: the backend fails closed, so
  // every launch step is refused with "that is not one of the applications you
  // confirmed" instead of being assumed valid. Profiles come from the Wave 7
  // feature, which already has them.
  // The bridge call is async (every preload channel is an ipcRenderer.invoke),
  // and the validation context has to be readable synchronously the moment the
  // user presses "Build preview". So the confirmed registry is cached here and
  // refreshed whenever the bridge exists. The cache starts EMPTY, and empty is
  // the safe answer rather than a broken one: the backend fails closed, so every
  // launch step is refused with "that is not one of the applications you
  // confirmed" instead of being assumed valid.
  let confirmedApplications = [];

  async function refreshConfirmedApplications() {
    const bridge = typeof window !== 'undefined' ? window.betterFingers?.applications : null;
    if (typeof bridge?.list !== 'function') return confirmedApplications;
    try {
      const payload = await bridge.list();
      confirmedApplications = Array.isArray(payload?.entries) ? payload.entries : [];
    } catch (_error) {
      confirmedApplications = [];
    }
    return confirmedApplications;
  }

  const workflowBuilder = createWorkflowBuilderFeature({
    elements: collectWorkflowElements(doc),
    api,
    hooks: {
      showToast,
      escapeHtml,
      getValidationContext: () => ({
        registry: confirmedApplications,
        profile_ids: applicationProfiles.getProfiles().map((profile) => profile.id),
        personas: Object.keys(loadedPersonas || {}),
        writing_presets: [],
      }),
    },
  });
  workflowBuilder.init();
  refreshConfirmedApplications().catch(() => {});

  // Wave 10 game setup wizard. It shares the api adapter with everything else,
  // which is the point: the buttons it records reach the same contracts the
  // dashboard and the keyboard use. Its rehearsal step is answered by the
  // backend's handler-less dispatcher, so nothing it sends can fire.
  const gameSetupWizard = createGameSetupWizardFeature({
    elements: collectGameSetupElements(doc),
    api,
    onMessage: (text, tone) => {
      if (tone === 'danger') showToast(text, 'danger');
    },
  });
  gameSetupWizard.init();

  // --- Persona wizard / Foundry + persona list refresh (shared) -----------

  let loadedPersonas = {};

  // See loadPersonaList() above for the rule and the reasoning.
  async function refreshPersonasAndVoices() {
    const { personas, failed } = await loadPersonaList(() => api.fetchPersonas(), loadedPersonas);
    loadedPersonas = personas;
    if (failed && !Object.keys(loadedPersonas).length) {
      showToast('Could not load the persona list; the preset dropdown may be empty.', 'warning');
    }
    settingsWorkspace.setPersonaOptions(Object.keys(loadedPersonas));
    // Library's persona filter maps to /library/search?persona=, which the
    // backend matches against a draft's `preset` (contract Amendment A1) --
    // the same names this list holds. Sourced from the live list rather than
    // from whatever personas happen to appear on the loaded page, so a
    // persona with no messages yet is still selectable (and honestly returns
    // nothing) instead of being invisible.
    libraryWorkspace.setPersonaOptions(Object.keys(loadedPersonas));
    await Promise.all([
      studioWorkspace.refresh().catch(() => {}),
      voiceStudio.refreshVoices?.(doc).catch(() => {}),
    ]);
  }

  const personas = createPersonasFeature({
    elements: {
      ...collectPersonaWizardElements(doc),
      currentPresetSelect: settingsElements.fields?.current_preset,
    },
    ui: { setMessage, showToast },
    // The explicit doc stops personas.js's Foundry/step lookups falling back
    // to the ambient document — there is one document of record here.
    doc,
    hooks: {
      getLoadedPersonas: () => loadedPersonas,
      refreshPersonasAndVoices,
      markProfileDirty: () => {},
    },
  });
  personas.initWizard();
  personas.initFoundry();

  personaFlow = createPersonaFlow({
    root: doc.getElementById('foundryOverlay'),
    footer: doc.getElementById('sdPersonaFlowFooter'),
    foundryTrigger: doc.getElementById('openFoundryButton'),
    doc,
    openPersonaForEdit: personas.openPersonaForEdit,
  });

  // --- Contacts + contact wizard (shared with Studio's "Preferred contact") -

  const contactWizard = createContactWizard({
    elements: collectContactWizardElements(doc),
    api,
    doc,
    hooks: {
      setMessage,
      onSaved: (contact, meta) => {
        showToast(`${meta?.edited ? 'Updated' : 'Saved'} contact "${contact?.name || ''}".`, 'success');
        // Refresh the picker, but do NOT select the new contact: creating
        // someone is not the same as declaring you are writing to them.
        refreshContactsAndShare().catch(() => {});
      },
    },
  });

  const contacts = createContactsFeature({
    elements: collectContactElements(doc),
    api,
    doc,
    hooks: {
      showToast,
      onCreateRequested: () => contactWizard.open(),
      onEditRequested: (contact) => contactWizard.openForEdit(contact),
      onManageRequested: () => {},
      onApplied: (contact) => statusBar.setContact(contact),
      onSelect: async (contactId) => {
        try {
          await api.setActiveContact(contactId);
        } catch (error) {
          showToast(`Failed to set active contact: ${error.message}`, 'danger');
        }
      },
    },
  });

  async function refreshContactsAndShare() {
    const list = await contacts.refresh();
    studioWorkspace.setContacts?.(contacts.getContacts());
    // Library needs the same list twice over: to resolve a draft's contact_id
    // into a readable name on the card, and to populate its contact filter.
    libraryWorkspace.setContacts?.(contacts.getContacts());
    return list;
  }

  // --- Onboarding + first-run panel -----------------------------------------

  // Durable consent gate: resolve the record (migrating the legacy
  // localStorage flag at most once), then hand the flow a consent controller
  // so acceptance closes the gate only after the durable write is confirmed.
  const onboardingBridge = doc.defaultView?.betterFingers?.onboarding;
  const consentVersion = 1;
  const onboardingReady = (async () => {
    const gate = await resolveOnboardingGate({
      bridge: onboardingBridge,
      storage: doc.defaultView?.localStorage,
      consentVersion,
    });
    const consent = createConsentController({
      bridge: onboardingBridge,
      consentVersion,
      onError: (error) =>
        showToast(`Saving consent failed: ${error?.message || error}`, 'danger'),
    });
    const onboardingElements = collectOnboardingElements(doc);
    const onboarding = createOnboardingFlow({
      elements: onboardingElements,
      doc,
      consent,
      shouldShow: () => gate.show,
      // Durable acceptance OR the live checkbox: on first run the durable
      // record cannot exist until finish() writes it, so the checkbox must be
      // able to open the consent step's advance gate; finish() still refuses
      // to close the flow until the durable write confirms ok.
      isConsented: () =>
        !needsConsent(gate.state, consentVersion) ||
        Boolean(onboardingElements.consent?.checked),
      hooks: {
        quitApp: () => doc.defaultView?.betterFingers?.quitApp?.(),
        fetchWhisperModels: () => api.fetchWhisperModels(),
        fetchRecommendation: () => api.fetchModelRecommendation(),
        onConsentError: (error) =>
          showToast(`Saving consent failed: ${error?.message || error}`, 'danger'),
      },
    });
    onboarding.init();
    return onboarding;
  })();
  onboardingReady.catch(() => {});

  const firstRun = createFirstRunFeature({
    elements: collectFirstRunElements(doc, { prefix: 'sdFirstRun' }),
    ui: { setMessage, showToast },
    api,
    hooks: {
      goToModelsTab: () => {
        shell.goTo('utilities');
        utilitiesWorkspace.goToSection('models');
        syncUtilitiesContext('models');
      },
      afterModelsChanged: () => utilitiesWorkspace.refreshModels().catch(() => {}),
      onReady: () => showToast('Setup complete — BetterFingers is ready.', 'success'),
    },
  });
  firstRun.init().catch(() => {});

  // --- App version (no bridge exists yet -- see handoff for the exact
  //     preload/main diff needed; renders an honest placeholder until then) -

  const versionEl = doc.querySelector('.sd-nav__version-num');
  if (versionEl) {
    Promise.resolve(doc.defaultView?.betterFingers?.getAppVersion?.())
      .then((version) => {
        versionEl.textContent = version || '—';
      })
      .catch(() => {
        versionEl.textContent = '—';
      });
  }

  // --- Initial real-data population (every list starts empty until this) --

  // Talk's persona chip and its "change it in Settings" link (current_preset
  // lives in Settings > AI Cleanup).
  doc.getElementById('sdTalkPersonaSettingsLink')?.addEventListener('click', () => {
    shell.goTo('settings');
    settingsWorkspace.goToSection('aicleanup');
  });

  // send_mode lives in Settings > Review & Drafts, same section as the
  // confidence thresholds.
  doc.getElementById('sdDeliveryModeSettingsLink')?.addEventListener('click', () => {
    shell.goTo('settings');
    settingsWorkspace.goToSection('review');
  });

  // Through talkWorkspace.refresh(), not drafts.refreshLatestDraft() alone:
  // the workspace paints Send/Revise enablement and the confidence strip from
  // the fetched draft. A bare drafts refresh renders the text but leaves the
  // action row dead until the first voice-status message — visible to any
  // user who restarts with a pending draft.
  function populateInitialData() {
    talkWorkspace.refresh().catch(() => {});
    libraryWorkspace.refresh().catch(() => {});
    refreshOutputSettings().catch(() => {});
    refreshProfileSettings().catch(() => {});
    studioWorkspace.refresh().catch(() => {});
    utilitiesWorkspace.refreshAll().catch(() => {});
    settingsWorkspace.refreshAll().catch(() => {});
    refreshPersonasAndVoices().catch(() => {});
    refreshContactsAndShare()
      .then(() => api.fetchActiveContact())
      .then((active) => {
        contacts.setSelected(active?.contact_id || '');
        statusBar.setContact(contacts.getSelected());
      })
      .catch(() => {});
  }
  populateInitialData();

  // The window is up seconds before the Python sidecar accepts connections, so
  // the population above can lose that race wholesale: every loader swallows
  // its error and none of them re-fire on their own — only the panels with
  // their own 3s poll (status bar, banner, app-context) ever recovered, which
  // left profiles, personas, settings and every list empty until a manual
  // refresh. Watch /health on the same cadence and re-populate on each
  // down->up transition; that heals the cold-start race and a mid-session
  // backend restart alike.
  let backendWasHealthy = false;
  const initialPopulateInterval = setInterval(() => {
    api.fetchHealth()
      .then(() => {
        if (!backendWasHealthy) {
          backendWasHealthy = true;
          populateInitialData();
        }
      })
      .catch(() => {
        backendWasHealthy = false;
      });
  }, 3000);

  return {
    destroy() {
      clearInterval(statusBarInterval);
      clearInterval(backendBannerInterval);
      clearInterval(initialPopulateInterval);
      applicationProfiles.destroy?.();
      voiceStatusConnection.close?.();
      talkWorkspace.destroy?.();
      talkCapture.destroy?.();
      // Puts the Review Deck away. An always-on-top window whose owner has torn
      // down is stranded on the user's screen with nothing left to close it.
      overlayBridge.destroy?.();
    },
  };
}

// Auto-start only when the host document explicitly opts in via
// data-bf-autowire="signal-desk" (signal-desk.html carries that marker on
// its <html> element; see lib/autowire.mjs's autowireMode()). Deliberately
// not based on any per-script identity property: per the HTML spec, the
// property browsers use to identify a document's own entry script is unset
// throughout a *module* script's evaluation (it only ever gets set for
// classic scripts), so a guard built on it can never be true for this file
// -- it is loaded as `<script type="module" src="...">` -- and would leave
// the page permanently unwired. A test importing this file as a plain ES
// module sees a document without the marker (or no document at all) and
// binds nothing, same as any other page that imports this module without
// carrying the marker.
if (typeof document !== 'undefined' && autowireMode(document) === AUTOWIRE_SIGNAL_DESK_VALUE) {
  startSignalDeskApp(document);
}
