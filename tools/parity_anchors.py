#!/usr/bin/env python3
"""Human-authored production anchors and cut rulings for the Wave 11 parity audit.

Data only. ``tools/parity_evidence.py`` loads this table through
``load_anchor_table()``, validates every entry against the production closure in
``validate_anchor_table()``, and consumes it during ``collect()``;
``tools/parity_ledger_build.py`` turns ``CUTS`` into ``intentional_cut`` rulings.
Nothing here decides a status on its own.

WHY THE TABLE EXISTS
--------------------
``parity_evidence.py``'s docstring always promised an ``ANCHORS`` escape hatch
and, until Wave 11B, did not have one. Its absence is the single largest
distortion in the Wave 11 result. The collector's rename rule strips exactly ONE
``sd<workspace>`` token, so it follows a rename INSIDE a workspace
(``#settingRecordingMode`` -> ``#sdSetRecordingMode``) but cannot follow a
control that MOVED workspace on the way. Signal Desk moved whole inventory
groups:

    inventory §7.3 Hotkeys        Settings  -> Utilities / Speech Input
    inventory §7.7 Audio Devices  Settings  -> Utilities / Speech Input
    inventory §7.8 Wake Word      Settings  -> Utilities / Speech Input
    inventory §7.13 Voice Macros  Settings  -> Utilities / Text Tools
    inventory §8   Models tab     own tab   -> Utilities / Models
    inventory §9   Diagnostics    own tab   -> Utilities / Diagnostics
    inventory §6   Draft history  Dashboard -> Library

Every row in a moved group fell through to "no production anchor" and was
reported as a PRODUCT gap. It is not one. ``#settingHotkey`` is
``#sdUtilHotkeyRecordingInput``: built, wired to the same profile field,
shipping. The Wave 11 blockers list said a user "cannot rebind a hotkey or train
a wake phrase from the product". They can. The audit could not see it, and a
measurement defect reported as a missing feature is the same failure as a
missing feature reported as shipped.

WHAT AN ANCHOR IS, AND IS NOT
-----------------------------
An anchor is a CLAIM, made by a person, that one specific production element
carries the capability an inventory row describes — verified by reading both.
It is not a convenience mapping to make a number move. Four properties keep that
honest, and three of them are enforced by ``validate_anchor_table()`` rather
than by good intentions:

* every anchor names a concrete production handle, which the ledger prints, so
  a reviewer can open the page and check it;
* an anchor that does not resolve in the production closure FAILS THE BUILD —
  delete the element and this breaks, rather than the ledger quietly continuing
  to report the row as anchored;
* a handle that ALREADY resolves may not be declared here at all, so the table
  can never redirect a row away from evidence the collector found by itself;
* an anchor supplies only the LOCATION leg of the D-0015 chain. The row still
  has to clear the coverage leg on its own. Anchoring alone cannot make a row
  ``wired``; rows anchored here that no production-target QA scenario or unit
  test names stay ``blocked (evidence)`` — correctly, and visibly.

A note on comments, kept because the history matters. The collector originally
accepted a quoted or ``#``-prefixed id appearing ANYWHERE in reachable source —
including inside a comment — as evidence that the id lived in production.
Writing "replaces the legacy ``#backendStatus`` card" in a shipped module was
therefore enough to make that row resolve against nothing but the prose. Three
Wave 11B comments did exactly that before review caught it. Two fixes landed:
the comments now spell legacy ids without the ``#``, and
``parity_evidence.strip_comments()`` now blanks comments before any matching, so
the hole is closed at the source. Both are kept — the collector guarantees it,
and the convention means a reader is never misled either.

CUTS carry the same burden in the other direction: every entry names what
replaced the capability, by handle, or says plainly that there was no capability
to replace.

Self-check::

    python3 -c "import sys; sys.path.insert(0,'.'); \\
        from tools import parity_anchors as p; sys.exit(p.main())"
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Handshake with parity_evidence.ANCHOR_SCHEMA_VERSION. A mismatch is an error
# there, not a silent downgrade: a table the collector half-understands is worse
# than no table.
SCHEMA_VERSION = 1


# --- HANDLE_ANCHORS -----------------------------------------------------------
#
# Keyed by the handle EXACTLY as the source inventory writes it (backtick
# contents, so `#settingHotkey` keeps its `#`). Applied only after mechanical
# resolution has failed.

HANDLE_ANCHORS: dict[str, dict[str, str]] = {
    # --- Wave 12 (D-0034 / Ruling B): legacy ids that never shipped ----------
    #
    # tools/anchor_audit.py found rows naming a DOM id present in NO shipping
    # page -- only in legacy `index.html` -- yet reported as anchored in
    # `signal-desk.html`. They resolved through the collector's old
    # "an id may live in JS" rule, which accepted any quoted mention in the
    # reachable module text, so a `getElementById('draftFinalText')` LOOKUP in
    # a features/*.js module counted as evidence the element ships.
    # parity_evidence.js_creates_id() now requires the JS to CREATE the id, so
    # these stopped resolving on their own and can finally be mapped honestly.
    #
    # Declared per HANDLE rather than per row: `#draftFinalText` is cited by
    # both UI-06-023 and UI-06-057, and a per-row declaration is rejected for
    # UI-06-057 (its other four handles resolve on their own, so the row is not
    # wholly unanchored). Mapping the handle fixes every row that cites it.
    #
    # Every capability below SHIPS. Only the id naming it was stale.
    '#draftRawText': {
        'anchor': '#sdRawTranscriptText',
        'why': 'The read-only raw transcript, rebuilt as the Talk meta strip\'s raw cell (features/talkWorkspace.js TALK_ELEMENT_IDS `rawTranscriptText`)',
    },
    '#draftFinalText': {
        'anchor': '#sdRefinedHero',
        'why': 'The cleaned-output editor, shipping as the Refined Message card\'s editable textarea, labelled "Cleaned message, editable"',
    },
    '#voiceStatus': {
        'anchor': '#sdSignalCoreStatusLabel',
        'why': 'The latest status keyword, shipping as the Signal Core\'s status label (TALK_ELEMENT_IDS `statusLabel`), with its detail line in `#sdSignalCoreStatusDetail`',
    },
    '#personaLearningSection': {
        'anchor': '#sdTeachSection',
        'why': (
            'Persona Learning ships as Studio\'s "Teach from my edits" panel. The distinct '
            '`sdTeach*` naming is deliberate and documented in features/studioWorkspace.js: '
            'personaLearning.js self-initialises at import time and queries '
            '`#personaLearningSection`, so reusing that canonical id would make the self-init '
            'IIFE wire the same DOM a second time with the wrong default hooks and double-fire '
            'every click. By that same design the legacy id exists in NO shipping page, which '
            'is why it was the clearest proof the old id-in-JS rule was wrong by design rather '
            'than by accident'
        ),
    },

    # --- inventory §7.3 Hotkeys: moved to Utilities / Speech Input ----------
    #
    # This is the group the Wave 11 blockers doc named as a substantive product
    # gap. All six fields, their clear buttons and the click-to-record chord
    # widget ship there, bound to the same profile keys the inventory names —
    # plus per-field collision detection the legacy page never had.
    '#settingHotkey': {
        'anchor': '#sdUtilHotkeyRecordingInput',
        'why': 'Recording Hotkey field in Utilities / Speech Input; same profile key `hotkey`, click-to-record capture wired by features/utilitiesWorkspace.js wireHotkeyRecorder()',
    },
    '#settingForceStopKey': {
        'anchor': '#sdUtilHotkeyForceStopInput',
        'why': 'Emergency Stop key field in Utilities / Speech Input; same profile key `force_stop_key`',
    },
    '#settingManualSendHotkey': {
        'anchor': '#sdUtilHotkeyManualSendInput',
        'why': 'Primary Action key field in Utilities / Speech Input; same profile key `manual_send_hotkey`',
    },
    '#settingReviewTtsHotkey': {
        'anchor': '#sdUtilHotkeyReviewTtsInput',
        'why': 'Review TTS Hotkey field in Utilities / Speech Input; same profile key `review_tts_hotkey`',
    },
    '#settingChatOpenKey': {
        'anchor': '#sdUtilHotkeyChatOpenInput',
        'why': 'Open Chat Key field in Utilities / Speech Input; same profile key `chat_open_key`',
    },
    '#settingVoiceMuteKey': {
        'anchor': '#sdUtilHotkeyVoiceMuteInput',
        'why': 'Voice Mute Key field in Utilities / Speech Input; same profile key `voice_mute_key`',
    },
    '#waylandHotkeyWarning': {
        'anchor': '#sdUtilHotkeyWaylandWarning',
        'why': 'Conditional Wayland limitation banner, shown from fetchCapabilities().is_wayland',
    },
    'setupHotkeyRecording': {
        'anchor': 'wireHotkeyRecorder',
        'why': 'The click-to-record chord widget, renamed in features/utilitiesWorkspace.js: same keydown chord accumulation over all six fields, plus collision detection',
    },

    # --- inventory §7.7 Audio Devices: moved to Utilities / Speech Input ----
    '#testMicButton': {
        'anchor': '#sdUtilAudioTestMicButton',
        'why': 'Browser microphone test toggle in Utilities / Speech Input; same getUserMedia + AnalyserNode level loop',
    },
    '#micMeterBar': {
        'anchor': '#sdUtilAudioMeterBar',
        'why': 'Live mic level bar container in Utilities / Speech Input',
    },
    '#micMeterFill': {
        'anchor': '#sdUtilAudioMeterFill',
        'why': 'Live mic level fill, driven by the AnalyserNode loop',
    },
    '#settingInputDevice': {
        'anchor': '#sdUtilAudioDeviceSelect',
        'why': 'Microphone picker in Utilities / Speech Input, built from fetchAudioDevices() -> GET /runtime/audio-devices and filtered to input-capable devices; persists `input_device_index`. NOTE: this anchor was NOT declarable before Wave 11B — the element existed but was a permanently disabled stub, so a user could not actually choose a device. It was wired in the same wave that declared this anchor',
    },

    # --- inventory §7.8 Voice Control / Wake Word: moved to Utilities -------
    #
    # The other group the blockers doc called a product gap. Enable/disable,
    # classifier selection, .onnx import, phrase TRAINING with live progress and
    # a reliability verdict, the three tuning numbers and the timed live test
    # all ship, against the real routes in routes_wake.py.
    '#settingWakeWordEnabled': {
        'anchor': '#sdUtilWakeEnabledToggle',
        # No literal `|` in any rationale: the ledger is a Markdown TABLE and
        # parity_validator splits rows on the pipe. The generator escapes it
        # now, but a rationale that does not need one should not rely on that.
        'why': 'Wake enable/disable toggle -> enableWake()/disableWake() -> POST /wake/enable and POST /wake/disable',
    },
    'handleWakeToggle()': {
        'anchor': 'enableWake',
        'why': 'The wake toggle handler, features/utilitiesWorkspace.js wakeEnabledToggle change listener, calling enableWake()/disableWake() and restoring the checkbox when the call fails',
    },
    '#settingWakeWordModel': {
        'anchor': '#sdUtilWakeModelSelect',
        'why': 'Imported-classifier dropdown; same profile key `wake_word_model`',
    },
    '#importWakeModelButton': {
        'anchor': '#sdUtilWakeImportButton',
        'why': '"Import model file… (.onnx)" -> importWakeModel() -> POST /wake/models/import',
    },
    '#importWakeModelFile': {
        'anchor': '#sdUtilWakeImportFile',
        'why': 'Hidden .onnx file input behind the import button',
    },
    '#importWakeModelStatus': {
        'anchor': '#sdUtilWakeImportStatus',
        'why': 'Import status line',
    },
    '#wakeTrainingGroup': {
        'anchor': '#sdUtilWakeTrainGroup',
        'why': '"Build a Wake Phrase" group: phrase input, train button, live progress and reliability verdict -> POST /wake/train + polled GET /wake/train/status',
    },
    '#settingWakeWordSensitivity': {
        'anchor': '#sdUtilWakeSensitivity',
        'why': 'Detection threshold; same profile key `wake_word_sensitivity`',
    },
    '#settingWakeWordCooldown': {
        'anchor': '#sdUtilWakeCooldown',
        'why': 'Cooldown seconds; same profile key `wake_word_cooldown_s`',
    },
    '#settingWakeWordMaxRecording': {
        'anchor': '#sdUtilWakeMaxRecording',
        'why': 'Max recording seconds; same profile key `wake_word_max_recording_s`',
    },
    '#testWakeButton': {
        'anchor': '#sdUtilWakeTestButton',
        'why': '"Test Wake Detection" -> testWake() -> POST /wake/test, peak score and sample count reported in #sdUtilWakeTestResult',
    },

    # --- inventory §7.13 Voice Macros: moved to Utilities / Text Tools ------
    '#settingMacrosEnabled': {
        'anchor': '#sdUtilMacrosEnabledToggle',
        'why': 'Macros enable toggle in Utilities / Text Tools; same profile key `macros_enabled`',
    },

    # --- inventory §7.0 sticky save bar: stayed in Settings, renamed --------
    '#discardProfileChangesButton': {
        'anchor': '#sdSetDiscardButton',
        'why': '"Discard" -> re-fetches the active profile and drops local edits',
    },
    '#saveProfileButton': {
        'anchor': '#sdSetSaveButton',
        'why': '"Save Settings" -> saveProfile(collectSettings()); disabled while validationErrors is non-empty, the same save-blocked-on-error gate',
    },

    # --- inventory §7.5.1 Persona Wizard: rebuilt as a guided flow ----------
    '.wizard-container': {
        'anchor': '.sd-persona-flow',
        'why': 'The four-step Persona Wizard, rebuilt as a Signal Desk guided flow (features/personaFlow.js, #sdPersonaFlowTitle/#sdPersonaFlowFooter)',
    },

    # --- inventory §8 Models tab: moved to Utilities / Models ---------------
    '#refreshModelsButton': {
        'anchor': '#sdUtilModelsRefreshButton',
        'why': '"Refresh Models" -> fetchLlmModels() + fetchWhisperModels()',
    },
    '#modelRecommendation': {
        'anchor': '#sdUtilModelsRecommendation',
        'why': 'Hardware-tier recommendation box <- GET /models/recommend',
    },
    '#modelStatusSummary': {
        'anchor': '#sdUtilModelsStatusSummary',
        'why': 'LLM / Whisper / Runtime overview, computed client-side from both model payloads',
    },
    '#modelMessage': {
        'anchor': '#sdUtilModelsMessage',
        'why': 'Shared status line for every model action in the section',
    },
    '#llmModelBadge': {'anchor': '#sdUtilLlmBadge', 'why': 'LLM Installed/Missing/Selected badge'},
    '#llmModelSelect': {'anchor': '#sdUtilLlmSelect', 'why': 'LLM model picker'},
    '#llmModelDetails': {'anchor': '#sdUtilLlmDetails', 'why': 'LLM detail grid (selected/viewing/install state/approx size/runtime)'},
    '#selectLlmModelButton': {'anchor': '#sdUtilLlmSelectButton', 'why': '"Use This LLM" -> selectLlmModel() -> POST /models/llm/select'},
    '#downloadLlmModelButton': {'anchor': '#sdUtilLlmDownloadButton', 'why': '"Download" -> downloadLlmModel(); polled progress in #sdUtilLlmProgress/#sdUtilLlmProgressFill/#sdUtilLlmProgressPercent'},
    '#deleteLlmModelButton': {'anchor': '#sdUtilLlmDeleteButton', 'why': '"Delete" behind a confirmation -> deleteLlmModel() -> typed IPC DELETE /models/llm/:id'},
    '#unloadLlmButton': {'anchor': '#sdUtilLlmUnloadButton', 'why': '"Unload" -> unloadModel(\'llm\') -> POST /models/unload/:component'},
    '#whisperModelBadge': {'anchor': '#sdUtilWhisperBadge', 'why': 'Whisper Installed/Missing/Selected badge'},
    '#whisperModelSelect': {'anchor': '#sdUtilWhisperSelect', 'why': 'Whisper model picker'},
    '#whisperModelDetails': {'anchor': '#sdUtilWhisperDetails', 'why': 'Whisper detail grid'},
    '#selectWhisperModelButton': {'anchor': '#sdUtilWhisperSelectButton', 'why': '"Use This" -> selectWhisperModel() -> POST /models/whisper/select'},
    '#downloadWhisperButton': {'anchor': '#sdUtilWhisperDownloadButton', 'why': '"Download" -> downloadWhisperModel() -> POST /models/whisper/download'},
    '#deleteWhisperButton': {'anchor': '#sdUtilWhisperDeleteButton', 'why': '"Delete" behind a confirmation -> deleteWhisperModel() -> typed IPC DELETE /models/whisper/:size'},
    '#unloadSttButton': {'anchor': '#sdUtilWhisperUnloadButton', 'why': '"Unload" -> unloadModel(\'stt\') -> POST /models/unload/:component'},
    '#provisionVoiceCloningButton': {
        'anchor': '#sdUtilVoiceCloningProvisionButton',
        'why': '"Install voice cloning" -> provisionVoiceCloning() -> POST /tts/clone/provision, outcome reported in #sdUtilVoiceCloningStatus',
    },

    # --- inventory §9 Diagnostics: moved to Utilities / Diagnostics ---------
    '#refreshDoctorButton': {
        'anchor': '#sdUtilDoctorRefreshButton',
        'why': '"Run Doctor Check" -> GET /doctor, rendered into #sdUtilDoctorCardsGrid with recovery actions in #sdUtilDoctorRecoveryList',
    },
    '#clearSidecarLogsButton': {
        'anchor': '#sdUtilSidecarLogsClearButton',
        'why': 'Clears the sidecar startup log tail (#sdUtilSidecarLogsTail)',
    },

    # --- inventory §6 dashboard status cards -> the persistent status rail --
    #
    # The legacy page reported these in three cards on one tab; Signal Desk
    # reports them in the bottom rail, glanceable from every workspace. The
    # Backend and Stream cells did NOT exist before Wave 11B -- these anchors
    # would have been false until they were built (features/statusBar.js
    # mapBackend()/mapStream()).
    '#backendStatus': {
        'anchor': '#sdStatusBackendValue',
        'why': 'Backend reachability cell in the status rail <- GET /health; reports Unreachable on a failed fetch rather than an unknown dash, which is the distinction the legacy card also drew',
    },
    '#backendDetail': {
        'anchor': '#sdStatusBackendValue',
        'why': 'Same cell: the detail (active job count, or why /health did not answer) is carried as that element\'s title so the rail stays one line',
    },
    '#transcriberStatus': {
        'anchor': '#sdStatusSttValue',
        'why': 'STT readiness cell in the status rail; mapStt() prefers the /runtime/status probe over /health, same as the legacy card',
    },
    '#llmStatus': {
        'anchor': '#sdStatusLlmValue',
        'why': 'LLM readiness cell in the status rail; mapLlm() reports readiness rather than the invariant "Local"',
    },
    '#wsConnection': {
        'anchor': '#sdStatusStreamValue',
        'why': 'Voice-status stream cell in the status rail, carrying the same connecting/connected/reconnecting/error states; built in Wave 11B, before which connectVoiceStatus()\'s onConnectionChange/onError were empty closures and a dropped stream was invisible',
    },
    '#draftStatus': {
        'anchor': '#sdRefinedBadge',
        'why': 'Draft state badge on the refined card, painted by features/talkWorkspace.js',
    },
    '#recordingControlStatus': {
        'anchor': '#sdCaptureMessage',
        'why': 'Capture hint/error line under the record controls, painted by features/talkCapture.js; surfaces hotkey-hook failures the same way',
    },

    # --- inventory §6 draft actions: same handlers, Signal Desk ids ---------
    '#saveDraftEditButton': {'anchor': '#sdSaveEditButton', 'why': '"Save Edit" -> editDraft() -> POST /drafts/:id/edit, in the Revise drawer'},
    '#readFullDraftButton': {'anchor': '#sdReadFullButton', 'why': '"Read Full" read-aloud over the whole draft'},
    '#copyDraftButton': {'anchor': '#sdCopyButton', 'why': '"Copy" -> window.betterFingers.writeClipboardText'},
    '#acceptDraftButton': {'anchor': '#sdAcceptButton', 'why': '"Accept" -> acceptDraft() -> POST /drafts/:id/accept'},
    '#declineDraftButton': {'anchor': '#sdDeclineButton', 'why': '"Decline" -> declineDraft() -> POST /drafts/:id/decline'},
    '#retryDraftButton': {'anchor': '#sdRetryButton', 'why': '"Retry" -> retryDraft() -> POST /drafts/:id/retry'},
    '#sendDraftButton': {'anchor': '#sdSendButton', 'why': '"Send" -> sendDraft() -> typed IPC POST /drafts/:id/send'},
    '#sendResultPanel': {'anchor': '#sdSendResult', 'why': 'Send-result detail grid: requested/actual action, fallback + reason, clipboard and submission'},

    # --- inventory §6 draft history: moved to the Library workspace ---------
    '#clearDraftHistoryButton': {
        'anchor': '#sdLibraryClearDraftsButton',
        'why': '"Clear drafts" in Library, behind the same confirmation contract (#sdLibraryConfirm)',
    },
    '#historySearchInput': {
        'anchor': '#sdLibrarySearchInput',
        'why': 'Library full-text search; an empty query restores the unfiltered timeline, same behaviour as the legacy box',
    },
    '#draftHistoryList': {
        'anchor': '#sdLibraryTimeline',
        'why': 'Library timeline; selecting an entry loads it into the context panel and can reopen it in Talk',
    },

    # --- inventory §1 surfaces: the legacy tab shells ----------------------
    #
    # These rows describe a legacy TAB and everything inside it. The tab STRIP
    # is already cut (the five-workspace rail); these anchors name where each
    # tab's CONTENT went, which is a different question and a real one.
    '.status-grid': {
        'anchor': '.sd-statusbar',
        'why': 'The three backend status cards are the persistent status rail\'s Backend / STT / LLM cells (#sdStatusBackendValue, #sdStatusSttValue, #sdStatusLlmValue) — glanceable from every workspace rather than only the dashboard tab',
    },
    '.stream-panel': {
        'anchor': '.sd-statusbar',
        'why': 'The voice-status stream is reported in the persistent status rail\'s Stream cell (#sdStatusStreamValue) rather than as a dashboard panel',
    },
    '#tabDashboard': {
        'anchor': '#workspace-talk',
        'why': 'The Dashboard tab\'s capture/refine/send core is the Talk workspace; its draft HISTORY became the Library workspace and its status cards became the status rail — see the .status-grid and #draftHistoryList anchors',
    },
    'settingEls': {
        'anchor': 'SETTINGS_ELEMENT_IDS',
        'why': 'The legacy main.js element map the row refers to; features/settingsWorkspace.js declares SETTINGS_ELEMENT_IDS and collects it through collectSettingsElements(). `draft_history_limit` IS present in it, which is the wiring gap this row asks about',
    },
    'InsufficientDiskSpaceError': {
        'anchor': 'isDiskSpaceMessage',
        'why': 'The renderer never names the backend exception class — it detects its MESSAGE SHAPE, which is exactly what the inventory row describes. features/firstRun.js exports isDiskSpaceMessage(), matched against model_manager.py\'s "Not enough disk space to download this file: need X GB free, only Y GB available" text, and shows #sdFirstRunDiskWarning rather than a generic download failure',
    },
    'maybeLearnFromEdit': {
        'anchor': 'suggestFromEdit',
        'why': 'Dictionary auto-learn from an edited draft, renamed in features/utilitiesWorkspace.js and called from the production bootstrap\'s draft-edit save path (bootstrap/signalDeskApp.js) — same raw-vs-edited diff feeding POST /dictionary/suggest',
    },
    '#tabSettings': {
        'anchor': '#workspace-settings',
        'why': 'The Settings workspace: search (#sdSetSearchInput), section sub-nav, seven section panels and the sticky Save/Discard bar (#sdSetSaveBar). The remaining legacy categories moved to Utilities and Studio — see the UI-07-002 cut for the full 14-category mapping',
    },
    '#tabModels': {
        'anchor': '#sdUtilSectionModels',
        'why': 'The Models section of Utilities: LLM manager, Whisper manager, wake-word backbone list (#sdUtilWakeBackboneList), runtime residency keeps and the Voice Cloning panel',
    },
    '#tabDiagnostics': {
        'anchor': '#sdUtilSectionDiagnostics',
        'why': 'The Diagnostics section of Utilities: Doctor grid, recovery list, metrics HUD, active jobs, sidecar logs and the runtime paths/errors/debug-log readouts',
    },

    # --- inventory §14 per-panel inline status lines -----------------------
    #
    # This row writes RENDERER VARIABLE names with a `#` in front of them
    # (`#draftMessageEl` is a `const` in main.js, never an element id). Each one
    # is anchored to the production element that variable stood for.
    '#draftMessageEl': {
        'anchor': '#sdDraftMessage',
        'why': 'The draft status line on the refined card; the legacy `draftMessageEl` variable, painted through the same setMessage(el, text, tone) pattern',
    },
    '#profileMessageEl': {
        'anchor': '#sdSetProfileMessage',
        'why': 'The Settings profile status line; the legacy `profileMessageEl` variable',
    },
    '#modelMessageEl': {
        'anchor': '#sdUtilModelsMessage',
        'why': 'The shared model-action status line in Utilities / Models; the legacy `modelMessageEl` variable',
    },
    '#warmupMessageEl': {
        'anchor': '#sdUtilWarmupMessage',
        'why': 'The warm-up status line in Utilities / Advanced; the legacy `warmupMessageEl` variable',
    },
    '#firstRunMessageEl': {
        'anchor': '#sdFirstRunMessage',
        'why': 'The first-run setup status line; the legacy `firstRunMessageEl` variable, on the same features/firstRun.js contract',
    },

    # --- inventory §2 Onboarding: the wizard SHIPPED, under new handles ------
    #
    # Wave 11C, and this reverses a reading rather than adding to one. A prior
    # lane looked at the production page, saw the consent screen, and concluded
    # Signal Desk had replaced the 4-step wizard with a single-screen gate --
    # which would have made these rows correct CUTS. It has not. `#sdOnboarding`
    # in `signal-desk.html` carries four `[data-flow-step]` bodies (welcome,
    # data-stays-here consent, how-it-works, speech models), four progress dots,
    # a Back that hides on step 1 and a forward button that relabels per step;
    # `features/onboardingFlow.js`'s `buildOnboardingSteps()` names all four with
    # their titles and primary labels, and `features/guidedFlow.js` does the
    # stepping, the dot states, the focus move and the swallowed Escape. That is
    # the same wizard, re-expressed on the shared guided-flow shell.
    #
    # It is not a rename the collector could follow on its own: the legacy ids
    # became attribute hooks (`[data-flow-back]`, `[data-flow-primary]`) or
    # classes, and an attribute name is not a handle this collector can resolve.
    # Where a control had no addressable handle at all, Wave 11C gave it the id
    # its two siblings in the same footer already had (`#sdOnboardBack`,
    # `#sdOnboardNext`) rather than anchoring the row to a function that merely
    # binds it -- an element row deserves an element anchor.
    '#onboardingOverlay': {
        'anchor': '#sdOnboarding',
        'why': 'The first-run gate itself: role="dialog" aria-modal, non-dismissible (features/guidedFlow.js `dismissible: false`), Escape swallowed and no close button in the markup — the same modal contract, on the shared guided-flow shell',
    },
    '#onboardingProgress': {
        'anchor': '.sd-flow__dot',
        'why': 'The progress dots, one per step, carrying `data-state` current/done/upcoming from features/guidedFlow.js `progressStates()`; the containing `[data-flow-progress]` row announces "Step N of 4" for anyone who cannot see them',
    },
    '#onboardingBody': {
        'anchor': '.sd-flow__step',
        'why': 'The per-step body. Four sections in markup rather than one container rebuilt with innerHTML per step — deliberately, since the legacy version had to escapeHtml() every backend string it interpolated into the recommendation box',
    },
    '#onboardingBackButton': {
        'anchor': '#sdOnboardBack',
        'why': 'The Back control in the onboarding footer, hidden on step 1 by features/guidedFlow.js (`back.hidden = isFirstStep(index)`), which is exactly the behaviour this row names',
    },
    '#onboardingNextButton': {
        'anchor': '#sdOnboardNext',
        'why': 'The forward control, relabelled per step by features/guidedFlow.js `primaryLabelFor()` from the labels features/onboardingFlow.js declares — "Get started" / "Accept & continue" / "Next" / "Finish", the exact four this row lists — and disabled until the step\'s `canAdvance` gate passes',
    },
    'finishOnboarding()': {
        'anchor': 'markOnboardingComplete',
        'why': 'Completion on the last step. `markOnboardingComplete` is the same localStorage write this row names, kept in features/onboardingFlow.js as the legacy path; production supplies the `consent` seam instead, so completion goes to the durable main-process record (features/onboardingConsent.js -> onboarding:accept) and the gate only closes once that write confirms. A stronger contract than the flag, not a missing one',
    },
}


# --- ROW_ANCHORS --------------------------------------------------------------
#
# For PROSE rows that name no handle at all. Owned by the evidence lane
# (inventory §B-6); kept here so both kinds of human anchoring are validated by
# one mechanism. Keyed by stable id; a row that already resolves on its own may
# not appear here.

ROW_ANCHORS: dict[str, dict] = {
    # Authored by the evidence lane (B-6) and re-verified here before landing:
    # every id below was independently confirmed to exist in the file claimed
    # for it (overlay.html, review-overlay.html, glitch-ring.js,
    # signal-desk.html), not taken on trust. Additive by agreement — append
    # rather than restructure so both lanes can write here.

    # --- shell / header ---
    'UI-01-003': {
        'anchors': ['#sdHeaderTitle', '#sdHeaderSubtitle', '#sdQuitButton'],
        'why': 'The app shell header: workspace title, tagline and the Quit button. Quit is the piece this row named that did NOT exist until Wave 11B built it — before that the row could not have been anchored honestly',
    },
    'UI-04-001': {
        'anchors': ['#sdHeaderBreadcrumb', '#sdHeaderTitle', '#sdHeaderSubtitle'],
        'why': 'The static header copy: breadcrumb, title and lede, repainted per workspace by features/signalDeskShell.js',
    },

    # --- the "biggest single panel" and its parts ---
    'UI-01-009': {
        'anchors': ['#sdRefinedHero', '#sdReviseDrawer', '#sdSendButton'],
        'why': 'The Review Draft panel, split across Talk\'s refined card, the Revise drawer and the action row rather than kept as one monolith',
    },
    'UI-06-015': {
        'anchors': ['#sdCaptureStartButton', '#sdCaptureStopButton', '#sdCaptureMessage'],
        'why': 'The recording controls: start, stop, and the hint/error line beneath them',
    },
    'UI-06-019': {
        'anchors': ['#sdRefinedHero', '#sdRawTranscriptText'],
        'why': 'The draft preview: the editable refined text and the raw transcript it came from',
    },
    'UI-06-024': {
        'anchors': ['#sdReviseDrawer', '#sdRewriteClearerButton', '#sdRewriteShorterButton', '#sdRewriteToneButton'],
        'why': 'The review/rewrite tools row, moved into the Revise drawer so it does not crowd the send path',
    },
    'UI-06-033': {
        'anchors': ['#sdAcceptButton', '#sdSendButton', '#sdCopyButton', '#sdDeclineButton'],
        'why': 'The draft action row: accept, send, copy and decline',
    },
    'UI-06-042': {
        'anchors': ['#sdLibraryTimeline', '#sdLibraryItemsCount'],
        'why': 'Draft history, promoted from a dashboard list to the Library workspace timeline with a live item count',
    },
    'UI-06-046': {
        'anchors': ['#sdShortcutSheet', 'createShortcutsFeature'],
        'why': 'The global keyboard shortcuts, owned by features/shortcuts.js and made discoverable by the shortcut sheet the legacy page had no equivalent of',
    },
    'UI-06-010': {
        'anchors': ['#sdFirstRunPanel', '#sdFirstRunDismissButton'],
        'why': 'The first-run panel and its dismissal; a banner inside Talk rather than a modal, so it cannot fight the onboarding gate',
    },

    # --- overlay windows (production surfaces in their own right) ---
    'UI-01-017': {
        'anchors': ['#statusRing', '#overlayWrap'],
        'why': 'overlay.html, the floating always-on-top status indicator: the glitch ring and its wrapper',
    },
    'UI-01-018': {
        'anchors': ['#rawToggleButton', '#draftSummary'],
        'why': 'review-overlay.html, the floating draft-review window with its own raw/refined toggle and summary',
    },
    'UI-12-004': {
        'anchors': ['#statusText', 'interpretOverlayStatus'],
        'why': 'The overlay\'s status mapping: interpretOverlayStatus() turns each voice-status payload kind into a ring state and the label #statusText shows',
    },
    'UI-12-005': {
        'anchors': ['setAmplitude'],
        'why': 'Live amplitude pulsing, glitch-ring.js\'s setAmplitude() driven from the recording payload',
    },
    'UI-12-006': {
        'anchors': ['#overlayWrap', 'applyAppearance'],
        'why': 'Pushed appearance settings: applyAppearance() sizes and positions #overlayWrap on load and on every settings change',
    },
    'UI-12-007': {
        'anchors': ['setIgnoreMouseEvents'],
        'why': 'The click-through/drag affordance, toggled on mouseenter and mouseleave',
    },
    'UI-12-015': {
        'anchors': ['#acceptChevronButton', '#rewritePreset'],
        'why': 'The review overlay\'s footer actions: the accept split-button and the rewrite preset picker',
    },
    'UI-12-023': {
        'anchors': ['#draftSummary', '#ttsBackendBadge'],
        'why': 'The draft push: a full re-render of the summary plus the refreshed TTS backend badge',
    },
    'UI-12-024': {
        'anchors': ['#statusBadge', '#commandBadge'],
        'why': 'The status push: speaking/stopped state and the voice-command badge',
    },
    'UI-12-025': {
        'anchors': ['#closeButton', 'createShortcutsFeature'],
        'why': 'Escape dismisses (hides, never declines) — the same close path as the button',
    },

    # --- persona wizard steps ---
    'UI-07-053': {
        'anchors': ['#wizardRole', '#wizardCustomRole'],
        'why': 'Wizard step 1, Goal & Role: the preset role picker and its free-text alternative',
    },
    'UI-07-059': {
        'anchors': ['#wizardTone', '#wizardCustomTone'],
        'why': 'Wizard step 2, Tone: the preset tone picker and its free-text alternative',
    },
    'UI-07-062': {
        'anchors': ['#wizardRuleNoPreamble', '#wizardRuleSanitize', '#wizardRuleCommands', '#wizardRuleLength'],
        'why': 'Wizard step 3, Rules: the four rule toggles that shape the generated prompt',
    },
    'UI-07-067': {
        'anchors': ['#wizardPromptPreview', '#wizardRegeneratePromptButton'],
        'why': 'Wizard step 4, Review & Save: the generated prompt shown before saving, with a regenerate action',
    },
    'UI-15-024': {
        'anchors': ['#wizardDeleteButton'],
        'why': 'The wizard\'s Delete Custom Persona, gated on the persona being neither builtin nor loaded',
    },

    # --- hotkeys / wake, the groups that moved to Utilities ---
    'UI-07-035': {
        'anchors': ['#sdUtilHotkeyRecordingClear', '#sdUtilHotkeyForceStopClear', '#sdUtilHotkeyManualSendClear'],
        'why': 'The per-field clear buttons that replace the legacy `.clear-hotkey-btn` class, one per hotkey field',
    },
    'UI-15-002': {
        'anchors': ['#sdUtilHotkeyRecordingInput', '#sdUtilHotkeyWaylandWarning', '#sdUtilHotkeyMessage'],
        'why': 'The hotkey configuration group as a whole: capture fields, the conditional Wayland banner and the shared status line, all in Utilities / Speech Input',
    },
    'UI-07-109': {
        'anchors': ['#sdUtilWakeSensitivity', '#sdUtilWakeCooldown', '#sdUtilWakeMaxRecording'],
        'why': 'Wake detection tuning: the three numeric fields backing wake_word_sensitivity/cooldown_s/max_recording_s',
    },
    'UI-07-113': {
        'anchors': ['#sdUtilWakeTestButton', '#sdUtilWakeTestResult', '#sdUtilWakeScoreBar'],
        'why': 'The live wake test: the timed trigger, the peak-score readout and the score meter',
    },
    'UI-15-009': {
        'anchors': ['#sdUtilWakeTrainGroup', '#sdUtilWakeTrainButton', '#sdUtilWakeTrainResult'],
        'why': 'The whole Build a Wake Phrase group: phrase input, the synthesize-and-train flow, and the reliability verdict',
    },
    'UI-14-012': {
        'anchors': ['#sdUtilWakeTrainProgress', '#sdUtilWakeTrainProgressFill', '#sdUtilWakeTrainProgressPercent'],
        'why': 'Live wake-training progress, polled from GET /wake/train/status',
    },

    # --- voice studio ---
    'UI-07-122': {
        'anchors': ['#voicePresetSelect', '#voicePresetList', '#saveVoicePresetButton'],
        'why': 'Voice presets: the picker, the saved-preset list and the save action',
    },
    'UI-07-127': {
        'anchors': ['#sdVoiceBlendCards'],
        'why': 'The blend surface, rebuilt as Signal Desk voice-blend cards',
    },
    'UI-07-139': {
        'anchors': ['#sdUtilVoiceCloningPanel', '#sdUtilVoiceCloningProvisionButton'],
        'why': 'Voice cloning provisioning, homed in Utilities / Models — the same panel the UI-07-142 cut names as the replacement for the dead legacy install button',
    },
    'UI-07-140': {
        'anchors': ['#voiceCloneConsent'],
        'why': 'The cloning consent gate, which must be ticked before the upload flow will run',
    },

    # --- models / diagnostics / settings ---
    'UI-08-004': {
        'anchors': ['#sdUtilLlmSelect', '#sdUtilLlmBadge', '#sdUtilLlmDownloadButton'],
        'why': 'The LLM panel: picker, install-state badge and download action',
    },
    'UI-08-012': {
        'anchors': ['#sdUtilWhisperSelect', '#sdUtilWhisperBadge', '#sdUtilWhisperDownloadButton'],
        'why': 'The Whisper panel: picker, install-state badge and download action',
    },
    'UI-09-011': {
        'anchors': ['#sdUtilRuntimeStatusList', '#sdUtilCapabilitiesList'],
        'why': 'Runtime diagnostics: the runtime-status dump and the platform capabilities readout',
    },
    'UI-14-013': {
        'anchors': ['#sdUtilLlmProgressFill', '#sdFirstRunLlmProgressFill', '#sdFirstRunWhisperProgressFill'],
        'why': 'Model download progress bars in both places a download can start: Utilities / Models and the first-run panel',
    },
    'UI-15-016': {
        'anchors': ['#sdUtilJobsList'],
        'why': 'The active-jobs list in Diagnostics, kept as its own surface rather than folded into recordings or Doctor',
    },
    'UI-15-023': {
        'anchors': ['#sdSetStitchPass'],
        'why': 'The Long Recording Stitch Pass toggle, backing long_recording_stitch_pass_enabled in Settings / AI Cleanup',
    },
    'UI-15-006': {
        'anchors': ['#sdSetRenameProfileButton', '#sdSetDuplicateProfileButton'],
        'why': 'Rename and Duplicate profile, really bound here through collectSettingsElements() — this is the surface that makes the §0 Bug #1 undeclared-identifier fault unreproducible on the shipping page',
    },
    'UI-07-164': {
        'anchors': ['#sdSetOverlayAppearanceGroup'],
        'why': 'The floating-overlay appearance group, hidden wholesale when the Electron bridge does not expose the overlay-appearance methods',
    },
    'UI-15-025': {
        'anchors': ['#sdFirstRunDismissButton'],
        'why': 'The sticky per-device first-run dismissal, deliberately separate from the one-time onboarding gate',
    },

    # --- status / notification ---
    'UI-14-008': {
        'anchors': ['#statusRing', '#statusText'],
        'why': 'The floating status overlay window, cross-referenced from §12.1',
    },
    'UI-14-009': {
        'anchors': ['#statusBadge', '#ttsBackendBadge', '#commandBadge'],
        'why': 'The review overlay\'s three badges: session status, TTS backend and voice command, cross-referenced from §12.2',
    },

    # --- Wave 13 (B-1): onboarding wizard step content + keyboard trap -----
    #
    # These three rows cite no handle at all in the source inventory -- they
    # are prose describing step content and a keyboard contract, not an
    # element id. #sdOnboarding's four `.sd-flow__step` bodies have no
    # per-step id of their own (guidedFlow.js addresses bare `data-flow-step`
    # sections by POSITION, not by id -- see its render() comment), so the
    # concrete handle a human can verify is the step DEFINITION
    # (features/onboardingFlow.js buildOnboardingSteps()) plus the shared
    # title element it paints into.
    'UI-02-005': {
        'anchors': ['#sdOnboardingTitle', 'buildOnboardingSteps'],
        'why': (
            'Step 1 "Welcome": buildOnboardingSteps() (features/onboardingFlow.js:64) declares the '
            '`welcome` step with title \'Welcome to BetterFingers\' and primaryLabel \'Get started\', '
            'and states no `canAdvance` gate -- the "no gating" this row names, since guidedFlow.js '
            'treats an absent gate as always-advanceable. render() paints that title into '
            '#sdOnboardingTitle (signal-desk.html:94) and shows the first `.sd-flow__step` body '
            '(signal-desk.html:104-113), the static "what you\'ll do" copy this row calls out. '
            'Covered behaviourally, not just for existence, by onboarding-prod.mjs\'s '
            '`the-first-run-gate-is-a-four-step-wizard`, which walks this exact step and asserts its '
            'title, its forward label, that exactly one body is visible, its copy, and that clicking '
            'Next actually advances the wizard.'
        ),
    },
    'UI-02-007': {
        'anchors': ['#sdOnboardingTitle', 'buildOnboardingSteps'],
        'why': (
            'Step 3 "How it works": buildOnboardingSteps() (features/onboardingFlow.js:71) declares '
            'the `how` step with title \'How it works\' and primaryLabel \'Next\', painted into '
            '#sdOnboardingTitle and the third `.sd-flow__step` body (signal-desk.html:132-141) -- the '
            'record -> review -> send explainer bullets this row names. Covered behaviourally by '
            'onboarding-prod.mjs\'s `the-first-run-gate-is-a-four-step-wizard`, which advances to this '
            'step via a real Next click and asserts its title, forward label, single-visible-body '
            'invariant, and its record/review/send copy.'
        ),
    },
    'UI-02-012': {
        'anchors': ['trapTab', 'dismissible'],
        'why': (
            'Keyboard trap: guidedFlow.js\'s trapTab() (bound on every keydown while `#sdOnboarding` is '
            'open) cycles Tab and Shift+Tab between the dialog\'s own focusable controls instead of '
            'letting focus leave it, and onboardingFlow.js passes `dismissible: false` '
            '(features/onboardingFlow.js:231) into createGuidedFlow(), which its onKeydown uses to '
            'swallow Escape (`event.preventDefault()`, no close()) rather than dismiss the gate -- '
            'exactly the "Tab cycles, Escape is swallowed" contract this row names. Covered by '
            'onboarding-prod.mjs\'s new `keyboard-trap-cycles-focus-and-swallows-escape` scenario, which '
            'Tabs forward through all four real focusable controls on the consent step and asserts the '
            'last wraps back to the first, Shift+Tabs back and asserts the first wraps to the last, then '
            'presses Escape and asserts the dialog stays open with focus undisturbed -- a real keyboard '
            'round-trip, not a check that the dialog merely exists.'
        ),
    },

    # --- Wave 13 (B-2): Talk voice-status fan-out + shared message-rescue -----
    #
    # Three prose rows citing no handle at all in the source inventory.
    'UI-06-063': {
        'anchors': ['connectVoiceStatus', 'handleVoiceStatusMessage'],
        'why': (
            'Event-driven refresh surfaces: api/backend.js\'s connectVoiceStatus() (bound in '
            'bootstrap/signalDeskApp.js:593-601) fans one voice-status WS message out to THREE '
            'independent handleVoiceStatusMessage() implementations -- features/talkWorkspace.js:557 '
            '(Signal Core ring/label/meter), features/talkCapture.js:258 (capture action-row state, '
            'including the long_recording_detected/chunking_*/chunking_stitching cases that produce '
            'this row\'s "long-recording/chunking progress text"), and features/overlayBridge.js:241 '
            '(the row\'s "overlay window status pushes" AND "review-overlay draft pushes" -- '
            'REVIEW_SHOW/REVIEW_REFRESH/REVIEW_HIDE_STATUSES). Two of the six legacy effects this row '
            'lists are RE-ARCHITECTED rather than reproduced verbatim, not silently dropped: '
            '"draft-history refresh" moved off the WS push onto direct calls in features/drafts.js '
            '(refreshDrafts() runs off the accept/decline/send/edit response itself, a stronger '
            'guarantee than waiting for a follow-up event); the "watchdog-timeout toast" for '
            '`watchdog_timeout_warning` (server.py:723 _broadcast_watchdog_timeout) reaches the same '
            'fan-out and its real message text is shown on the capture status line '
            '(#sdCaptureMessage, talkCapture.js\'s default-state message path) rather than a discrete '
            'toast popup -- surfaced, just not in the exact legacy presentation. Flagged for the '
            'director in room chat rather than silently claimed.'
        ),
    },
    'UI-06-074': {
        'anchors': ['formatAssessmentSummary', 'formatDeliverySignals', 'formatClarification'],
        'why': (
            'Assessment / delivery / clarification regions, "same shared renderer as 6.4/6.6": '
            'features/messageRescue.js\'s formatAssessmentSummary()/formatDeliverySignals()/'
            'formatClarification() (lines 159/196/178) are the literal shared renderer this row '
            'names, called from formatMessageRescueViewModel() and reused VERBATIM (same canonical '
            'ids, comment at signal-desk.html:1963/2022/2064) by all three Message Rescue surfaces: '
            'the Talk-adjacent draft-bound live panel (features/messageRescueDraft.js, now hosted in '
            'Utilities / Text Tools via initMessageRescueDraft() at utilitiesWorkspace.js:1822 -- a '
            'workspace move, same pattern as the Hotkeys/Wake Word groups above), the static preview '
            '(#messageRescueAssessment) and the Text Playground (#textPlaygroundAssessment). '
            'app/tests/messageRescue.test.mjs already exercises all three functions on real, '
            'malformed and empty input (percentage formatting, non-string filtering, missing-question '
            'null-handling) -- behavioral coverage, not existence checks.'
        ),
    },
    'UI-06-076': {
        'anchors': ['formatPreservationChecks', 'formatWarnings'],
        'why': (
            'Preservation checks / warnings lists: features/messageRescue.js\'s '
            'formatPreservationChecks()/formatWarnings() (lines 233/250), the same shared renderer as '
            'UI-06-074, reused verbatim across the three Message Rescue surfaces '
            '(#draftRescuePreservationList/#draftRescueWarningsList and their message-rescue/'
            'textPlayground siblings). app/tests/messageRescue.test.mjs asserts real behavior: mixed '
            'pass/fail entries, an entry with neither a `passed` nor `ok` field defaulting to FAILED '
            'rather than silently passing, and non-array/malformed warnings collapsing to an empty '
            'list rather than throwing.'
        ),
    },

    # --- Wave 13 (B-6): blend / modulation quick-preset chips ---------------
    #
    # Three prose rows citing legacy attribute selectors (`[data-blend-preset]`
    # / `[data-mod-preset]`), which this collector cannot resolve as a handle
    # (an attribute name is not an id/class/endpoint/symbol) -- so they read as
    # "no code handle" even though the same attributes ship verbatim on the
    # production page (signal-desk.html:1558-1562 / 1644-1649).
    'UI-07-133': {
        'anchors': ['VOICE_BLEND_QUICK_PRESETS'],
        'why': (
            'Quick-blend chips: features/voiceStudio.js exports VOICE_BLEND_QUICK_PRESETS and binds '
            'a `[data-blend-preset]` click handler over it (signal-desk.html:1556-1563 ships all five '
            'chips -- softer/brighter/lower/narrator/assistant -- with matching data-blend-preset '
            'values). Covered by shell-status-prod.mjs\'s '
            '`voice-studio-quick-presets-exist-and-match-their-handlers`, which clicks the "softer" '
            'chip and asserts the real #voiceEnergy/#voiceWarmth sliders move to that preset\'s exact '
            'values -- proof the handler is live, not just that the button exists.'
        ),
    },
    'UI-07-134': {
        'anchors': ['setModulationControls'],
        'why': (
            'The "Modulation:" group heading itself (its four sliders are already anchored '
            'individually at UI-07-109): features/voiceStudio.js\'s setModulationControls() is the '
            'one function that paints pitch/energy/warmth/brightness/pause-style as a group, called '
            'both by profile load and by every modulation quick-preset click. Covered by the same '
            'shell-status-prod.mjs scenario, which clicks a modulation chip and asserts multiple '
            'sliders in the group move together to that preset\'s values.'
        ),
    },
    'UI-07-138': {
        'anchors': ['VOICE_MODULATION_QUICK_PRESETS'],
        'why': (
            'Quick-modulation chips: features/voiceStudio.js exports VOICE_MODULATION_QUICK_PRESETS '
            'and binds a `[data-mod-preset]` click handler over it (signal-desk.html:1642-1650 ships '
            'all six chips -- clear/quiet/presentation/character/fast/accessibility -- with matching '
            'data-mod-preset values; "accessibility" is the 0.75x-speed affordance that had silently '
            'gone missing from the shipping page). Covered by shell-status-prod.mjs\'s '
            '`voice-studio-quick-presets-exist-and-match-their-handlers`, which clicks the "quiet" '
            'chip and asserts energy/warmth/brightness/pause-style/speed all move to that preset\'s '
            'exact values in one click -- a second, different set of values than the blend click '
            'that ran immediately before it, which only a live binding could produce twice in a row.'
        ),
    },

    # --- Wave 12 (D-0034 / director Ruling B): legacy-id re-anchors -----------
    #
    # tools/anchor_audit.py found seven rows naming a DOM id that exists in no
    # shipping page -- only in legacy `index.html` -- yet reported as anchored
    # "in signal-desk.html". They resolved through the collector's old
    # "an id may live in JS" rule, which accepted any quoted mention in the
    # reachable module text: a `getElementById('draftConfidence')` LOOKUP in a
    # features/*.js module counted as evidence the element SHIPS.
    #
    # parity_evidence.js_creates_id() now requires the JS to CREATE the id
    # (`.id =`, `setAttribute('id', …)`, or `id="…"` inside built markup)
    # rather than merely look it up, so these five stopped resolving on their
    # own -- which is what finally allows them to be re-anchored here. Until
    # that fix, the collector's "already resolves in production" guard rejected
    # every one of these declarations, so the guard against redundancy was the
    # thing preserving the mislabelling.
    #
    # The five legacy-id rows this audit found (UI-06-020, UI-06-023,
    # UI-06-057, UI-06-061, UI-15-001) are re-anchored by HANDLE at the top of
    # HANDLE_ANCHORS rather than per row, because `#draftFinalText` is cited by
    # two of them and a per-row declaration is rejected for the row whose other
    # handles already resolve. See that block for the rulings and rationale.
}


# --- CUTS ---------------------------------------------------------------------
#
# Keyed by stable id. Every entry names what replaced the capability, by handle,
# or states plainly that there was no capability to replace. Turned into
# `intentional_cut` by parity_ledger_build.py.

CUTS: dict[str, str] = {
    'UI-07-002': (
        'Intentional cut: the 14-button `.settings-nav-button` sidebar is replaced by the '
        'workspace split Signal Desk is built around. Its 14 categories now live behind three '
        'navs, all of which ship: the 7-item Settings sub-nav (`#sdSetNavProfile`/`Recording`/'
        '`Review`/`AiCleanup`/`Notifications`/`Appearance`/`Privacy`), the 5-item Utilities '
        'sub-nav (`#sdUtilNavModels`/`Speech`/`Text`/`Diagnostics`/`Advanced`, which carries '
        'legacy Hotkeys, Audio Devices, Voice Control, Send & Injection, Dictionary, Macros and '
        'Advanced), and the Studio workspace (legacy TTS / Voice Studio plus the persona '
        'builders). The capability — reach every settings group — ships; the 14 legacy buttons '
        'deliberately do not.'
    ),
    'UI-07-116': (
        'Intentional cut: `#ttsWarningBadge` was a STATIC prose paragraph rendered '
        'unconditionally on every platform, telling every user about Linux libsndfile1 whether '
        'or not they were on Linux or using Kokoro. It was never driven by a capability probe, '
        'so it was as likely to mislead as to help. Replaced by two surfaces that compute the '
        'answer: the Doctor grid\'s "TTS (Read-Aloud)" card (`#sdUtilDoctorCardsGrid` <- '
        '`GET /doctor`, with a recovery action when it fails) and the platform capabilities '
        'readout (`#sdUtilCapabilitiesList` <- `GET /capabilities`, reporting `supports_tts`). '
        'A conditional truth replaces an unconditional guess.'
    ),
    'UI-07-121': (
        'Intentional cut: `#voiceLivePreview` re-auditioned the voice automatically ~600ms after '
        'any blend/modulation/base/speed tweak. Replaced by explicit, user-initiated preview — '
        '`#sdVoicePreviewButton` on the blend card and `#testTtsButton` in the Voice Studio. The '
        'capability (hear the mix you just built) ships; the automatic re-trigger deliberately '
        'does not, because it started audio nobody asked for while the user was still moving a '
        'slider.'
    ),
    'UI-07-130': (
        'Intentional cut: `#voiceBlendBackendNote` is one half of the §0 Bug #2 pair — its '
        'population call `refreshVoiceBlendCapabilityNote()` was never defined anywhere, so the '
        'element had no contract and never rendered anything on any page. Replaced by the Voice '
        'Cloning panel\'s real, populated status in Utilities / Models: `#sdUtilVoiceCloningBadge`, '
        '`#sdUtilVoiceCloningStatus` and `#sdUtilVoiceCloningHint`. An element that never had a '
        'data source is not a capability being removed — and this closes half of UI-00-002.'
    ),
    'UI-07-137': (
        'Intentional cut: `#voiceStability` shipped `disabled` and labelled "experimental — '
        'reserved, not yet applied". It was wired to nothing, applied to nothing, and had no '
        'backend field. There is NO replacement, because there was no capability: a permanently '
        'disabled control is a promise the product never kept, and carrying it into Signal Desk '
        'would have repeated the promise.'
    ),
    'UI-07-141': (
        'Intentional cut: `#voiceCloneStatusNote` is the other half of the §0 Bug #2 pair — its '
        'population call `refreshCloneStatusNote()` was never defined. Replaced by '
        '`#sdUtilVoiceCloningStatus` in Utilities / Models, which is genuinely populated from the '
        'clone provisioning/status data alongside `#sdUtilVoiceCloningBadge`.'
    ),
    'UI-07-142': (
        'Intentional cut: `#voiceCloneInstallButton` was hidden with no click handler anywhere in '
        'the legacy page — the inventory row says so itself. Replaced by '
        '`#sdUtilVoiceCloningProvisionButton` in Utilities / Models, which has a real handler: '
        'provisionVoiceCloning() -> POST /tts/clone/provision, with the outcome reported in '
        '`#sdUtilVoiceCloningStatus`.'
    ),
    'UI-15-011': (
        'Intentional cut: this orphan-list row exists to warn that three voice-cloning entry '
        'points are easy to conflate, and the only handle it names is '
        '(c), `#voiceCloneInstallButton` — the hidden, unwired one, cut at UI-07-142. The other '
        'two ship and are anchored: (a) Models-tab provisioning is '
        '`#sdUtilVoiceCloningProvisionButton` -> provisionVoiceCloning() -> POST '
        '/tts/clone/provision, and (b) the consent+upload flow is `#voiceCloneUploadButton` in '
        'the Studio Voice Studio. Signal Desk resolves the confusion this row documents by '
        'having two entry points instead of three; the row is cut because the thing it points '
        'at is the one that went away.'
    ),
    'UI-06-062': (
        'Intentional cut: `#voiceStatusDetail` dumped the raw JSON of the latest voice-status '
        'message, and the inventory row itself calls it developer-facing. A payload readout is '
        'not a product surface. Both things a user needs from it ship: the CONNECTION state is '
        'the status rail\'s Stream cell (`#sdStatusStreamValue`, built in Wave 11B, with the '
        'failure reason as its title) and the message CONTENT drives the Signal Core ring, meter '
        'and capture controls. Raw payloads remain available to a developer through Utilities / '
        'Diagnostics (`#sdUtilDebugLogTail`).'
    ),

    # --- inventory §0: the two Gate 0 known bugs, formally closed -----------
    #
    # Wave 11C. Both rows are DEFECT REPORTS against `index.html`, carried since
    # Gate 0 and named as still-open by WAVE11_BLOCKERS B-7. Neither is a
    # capability the product owes a user, and leaving a bug report `blocked`
    # forever reports a gap that does not exist on the page that ships. They are
    # cut, and each names the production surface that carries the capability the
    # defect was about.
    'UI-00-001': (
        'Intentional cut: this row is a DEFECT REPORT against `index.html`, and it asks for one '
        'thing — "verify this in a live DevTools console before the redesign". Closed on both '
        'halves. (1) The capability ships on the production page under real, collected ids: '
        '`#sdSetRenameProfileButton`, `#sdSetDuplicateProfileButton` and '
        '`#sdSetExportProfileButton`, declared in features/settingsWorkspace.js\'s '
        'SETTINGS_ELEMENT_IDS, captured by collectSettingsElements() and bound in '
        'bindProfileButtons(), with unit coverage in app/tests/settingsWorkspace.test.mjs and '
        'app/tests/settingsProfileOps.test.mjs. Every access there is via `els.*`, so the '
        'bare-identifier pattern the row describes cannot exist on the shipping page. (2) On the '
        'legacy page the predicted ReferenceError does not reproduce: `main.js` is loaded as a '
        'module whose outer scope is the global scope, and an element with an `id` is exposed on '
        'the window as a named property, so `renameProfileButton` resolves to the button rather '
        'than throwing — which is why the legacy QA board boots at all, since a top-level throw '
        'would abort bootstrap() and take the whole legacy dashboard with it. The row is cut '
        'rather than wired because a bug report is not a shipped surface.'
    ),
    'UI-00-002': (
        'Intentional cut: the row records that `refreshVoiceBlendCapabilityNote()` and '
        '`refreshCloneStatusNote()` were removed from main.js (so the ReferenceError they caused '
        'is gone), that their DOM targets `#voiceBlendBackendNote` and `#voiceCloneStatusNote` '
        'survive in `index.html`, and that the intended behaviour "was not reimplemented because '
        'its contract was unknown" — it asks to stay blocked until those surfaces have a defined '
        'contract. They now do, on the page that ships, and both halves are already cut '
        'individually with the same replacement named: UI-07-130 and UI-07-141 point at '
        '`#sdUtilVoiceCloningBadge`, `#sdUtilVoiceCloningStatus` and `#sdUtilVoiceCloningHint` in '
        'Utilities / Models, which are genuinely populated from clone provisioning/status data. '
        'This §0 row is the umbrella over those two and is cut consistently with them: an element '
        'that never had a data source is not a capability being removed.'
    ),

    # --- Wave 12 ruling C-6 (release director) --------------------------------
    #
    # Both rows are the same capability seen from §6 and §14. Declared here
    # rather than hand-written into the ledger so regeneration reproduces the
    # ruling. See docs/release/DECISIONS.md D-0032.
    'UI-06-021': (
        'Intentional cut: Wave 12 ruling C-6 — the `#draftConfidence` badge is superseded by '
        'the Talk meta strip on the shipping page. `#draftConfidence` occurs zero times in '
        '`signal-desk.html`; it resolved only through the "an id may live in JS" fallback, '
        'matching features/drafts.js\'s getElementById call, so `renderConfidenceBadge()` is a '
        'permanent no-op on the page a user actually sees. The CAPABILITY is not removed: the '
        'confidence read-out ships live as `#sdConfidenceValue` / `#sdConfidenceBarFill`, '
        'evidenced by app/tests/talkDraftSurfaces.test.mjs, which also pins the honest case — '
        'an unknown score reads as an em dash, not 0%. The legacy element and its behaviour '
        'are deliberately RETAINED in index.html, which is the rollback path.'
    ),
    'UI-14-007': (
        'Intentional cut: Wave 12 ruling C-6, same capability as UI-06-021 seen from §14 — the '
        'confidence badge is superseded by Talk\'s meta strip (`#sdConfidenceValue` / '
        '`#sdConfidenceBarFill`, evidenced by app/tests/talkDraftSurfaces.test.mjs). The id '
        'this row named, `#draftConfidence`, exists only in the legacy `index.html` rollback '
        'page and never in the production composition root.'
    ),
}


# --- self-check ---------------------------------------------------------------


def main() -> int:  # pragma: no cover - CLI
    """Run the collector's own validation over this table and report."""
    sys.path.insert(0, str(ROOT))
    from tools import parity_evidence as pe
    from tools import parity_validator as pv

    prod = pe.Closure.build(
        'production', pe.PROD_ENTRY_HTML, pe.PROD_ENTRY_JS, pe.PROD_EXTRA_PAGES
    )
    prod_index = pe.build_id_index(prod)
    source_ids = {row.stable_id for row in pv.parse_source()}
    try:
        pe.validate_anchor_table(
            HANDLE_ANCHORS, ROW_ANCHORS, CUTS, prod, prod_index, source_ids
        )
    except pe.AnchorError as exc:
        print(exc)
        return 1
    print(
        f'{len(HANDLE_ANCHORS)} handle anchor(s), {len(ROW_ANCHORS)} row anchor(s) and '
        f'{len(CUTS)} cut ruling(s) all hold against the production closure'
    )
    return 0


if __name__ == '__main__':  # pragma: no cover - CLI
    sys.exit(main())
