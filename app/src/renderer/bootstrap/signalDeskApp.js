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
import { createDraftsFeature } from '../features/drafts.js';
import { createTalkWorkspaceFeature, collectTalkElements } from '../features/talkWorkspace.js';
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

  // --- Shared send-action state (drafts.js's hooks.getSelectedSendAction) --
  // TODO(phase-integration): talkWorkspace.js's own header comment (see
  // bindDeliverySegmented) documents that its Send/Insert/Copy segmented
  // control isn't fed into send-action selection yet -- main.js sources the
  // real default the same way this does, from the profile's send_mode /
  // supports_input_injection capability, not from that control.

  let outputSettings = null;
  async function refreshOutputSettings() {
    try {
      outputSettings = await api.fetchOutputSettings();
    } catch (_error) {
      outputSettings = null;
    }
    return outputSettings;
  }

  function getSelectedSendAction() {
    if (!outputSettings) return 'copy_only';
    if (!outputSettings?.capabilities?.supports_input_injection) return 'copy_only';
    return outputSettings.send_mode === 'auto_send' ? 'open_chat_then_send' : 'paste';
  }

  // renderSendResult(sendResult) is part of drafts.js's `ui` contract, but
  // Signal Desk's Talk workspace has no send-result panel (the preview never
  // added one either) -- the real user-facing feedback is drafts.js's own
  // setMessage(draftMessageEl, ...) call right after send, so this stays a
  // deliberate no-op rather than inventing a second panel.
  function renderSendResult() {}

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
  // No legacy-dashboard draft-editor elements exist on this page, so
  // `elements` is empty -- every DOM write inside drafts.js is already
  // optional-chained (`if (els.x) ...`), and Talk/Library render the real
  // state themselves via hooks.drafts.getLatestDraft()/renderDraft(). See
  // talkWorkspace.js/libraryWorkspace.js's own header comments confirming
  // this is the one live drafts-feature instance both share.

  const drafts = createDraftsFeature({
    elements: {},
    ui: { setMessage, showToast, escapeHtml, renderSendResult },
    hooks: {
      getSelectedSendAction,
      gatherVoiceStudioSettings: () => voiceStudio.gatherVoiceStudioSettings(),
      onDraftEdited: (rawText, editedText) => utilitiesWorkspace.suggestFromEdit(rawText, editedText),
      refreshOutputSettings,
    },
  });

  // --- Talk workspace -------------------------------------------------------

  const talkWorkspace = createTalkWorkspaceFeature({
    elements: collectTalkElements(doc),
    hooks: { showToast, drafts },
  });
  talkWorkspace.init();

  const voiceStatusConnection = api.connectVoiceStatus({
    onMessage: (payload) => talkWorkspace.handleVoiceStatusMessage(payload),
    onConnectionChange: () => {},
    onError: () => {},
  });

  // --- Library workspace ---------------------------------------------------

  const libraryWorkspace = createLibraryWorkspaceFeature({
    elements: collectLibraryElements(doc),
    hooks: { showToast, drafts },
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

  // --- Persona wizard / Foundry + persona list refresh (shared) -----------

  let loadedPersonas = {};

  async function refreshPersonasAndVoices() {
    try {
      loadedPersonas = await api.fetchPersonas();
    } catch (_error) {
      loadedPersonas = {};
    }
    settingsWorkspace.setPersonaOptions(Object.keys(loadedPersonas));
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
  });

  // --- Contacts + contact wizard (shared with Studio's "Preferred contact") -

  const contactWizard = createContactWizard({
    elements: collectContactWizardElements(doc),
    api,
    doc,
    hooks: {
      setMessage,
      onSaved: (contact) => {
        showToast(`Saved contact "${contact?.name || ''}".`, 'success');
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

  drafts.refreshLatestDraft().catch(() => {});
  libraryWorkspace.refresh().catch(() => {});
  refreshOutputSettings().catch(() => {});
  studioWorkspace.refresh().catch(() => {});
  utilitiesWorkspace.refreshAll().catch(() => {});
  settingsWorkspace.refreshAll().catch(() => {});
  refreshPersonasAndVoices().catch(() => {});
  refreshContactsAndShare()
    .then(() => api.fetchActiveContact())
    .then((active) => contacts.setSelected(active?.contact_id || ''))
    .catch(() => {});

  return {
    destroy() {
      clearInterval(statusBarInterval);
      voiceStatusConnection.close?.();
      talkWorkspace.destroy?.();
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
