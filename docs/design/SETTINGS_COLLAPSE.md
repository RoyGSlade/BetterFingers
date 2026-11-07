# Settings collapse: exact control inventory and staged plan

BF-D6 proposal, 2026-10-04. **Plan only.** Source baseline `33b7cf44dca75dfae3e427ddcfa0a6dd7cb1fc0f` in `codex/d6-settings-collapse`. This changes no runtime, settings, ledger or tests.

**Recommendation:** first delete the five verified ineffective controls, preserving their saved keys. Then consolidate navigation into Profile, Appearance, Privacy and one Advanced entry. Keep important actions beside the draft/microphone they affect. Remove mode/automatic-policy knobs from the routine UI only after their replacements and migrations pass.

BF-D1 [MODES.md](C:/Users/Laptop/Documents/Codex/2026-08-16/p/BetterFingers-wt/d1-modes/docs/design/MODES.md) and BF-D2 [FIRST_RUN.md](C:/Users/Laptop/Documents/Codex/2026-08-16/p/BetterFingers-wt/d2-first-run/docs/design/FIRST_RUN.md) are proposals awaiting owner/Claude decisions, including storage, acquisition, consent and qualification. Root review does not ratify product/schema changes. References to them below describe dependencies, not permission or implemented behavior. Main input `C:\Users\Laptop\Documents\Codex\2026-08-16\p\BetterFingers\docs\arc\SETTINGS_INDEX.md` is read-only/gitignored; audit IDs below refer to it, not the distinct `UI-NN-NNN` parity ledger IDs.

## 1. Scope, counts and evidence

**V** = verified by reading/searching this source; **I** = inference; **P** = proposed, unimplemented. There are no new measured runtime/usability/performance results here. Audit totals 243 rows (105 Advanced, 73 Remove, 39 Auto, 23 Mode, 3 Ask) are classification inputs, not blanket deletion authority (`main:docs/arc/SETTINGS_INDEX.md:418-437`).

The static coverage boundary is `app/src/renderer/signal-desk.html:1978-3377`: entire Utilities and Settings workspaces, including inert/hidden, disabled, readonly key capture, file imports, transient text, radio result choices and privacy confirmation. Strip comments while preserving line numbers; enumerate every `input/select/textarea/button` start tag inside those two actual workspace regions. Context-panel controls after line 3380, consent/persona/voice modals before this boundary, Scribe and legacy `index.html/main.js` are outside the table; they are preserved and rechecked as dependencies.

Verified enumeration [V]:

| Coverage unit | Settings | Utilities | Total |
|---|---:|---:|---:|
| Static native form controls | 47 | 39 | **86** |
| Static buttons, including action/navigation/value-capture buttons | 29 | 59 | **88** |
| Additional runtime-created native selector | 0 | 1 | **1** |
| Repeated dynamic button templates | 1 app-profile selection family | 9 action families | **10 templates**, variable instance count |

Thus **87 native value controls** (86 static + latency selector), plus two already-counted static controller binding recorder buttons and one repeated app-profile choice template that also carry values. Do not equate these units with the audit's 243 persisted-key/control-cluster rows or 108 reachable rows. The audit's 45 + 38 = 83 value-bearing count excludes Settings search and the profile/wake file inputs; adding those three gives 86. This reconciliation is inferred from matching the inventories [I], not a measured UI count. Eleven static forms belong to the gated wake/workflow groups (including hidden wake import file); the Game delivery selector is state-disabled and audience context is locked. Hidden does not mean retired.

No dynamically generated native form controls were found beyond `sdUtilLatencyProbeMode` after inspecting `settingsWorkspace.js`, `utilitiesWorkspace.js`, `applicationProfiles.js` and `gameSetupWizard.js`: Settings generates options/readouts; Utilities generates one selector plus action buttons; application profiles generate repeated selection buttons; the game wizard captures bindings into state rather than creating inputs. These are source checks, not mounted-browser reachability evidence.

Every table fate is P. **Owned by mode** retains a real Advanced override where safe; **derive automatically** retains current values/manual Advanced overrides until measured replacement policy exists. Moving a control never authorizes its hidden capability. **Keep visible** can mean a contextual content editor or Privacy danger area, not an always-open form. **Delete** means remove the misleading/duplicate renderer surface after its dependencies are addressed; it does not delete user content or backend/profile keys.

Reproduce the static census read-only from this worktree; this prints identities and counts without creating files:

~~~powershell
$htmlLines = Get-Content app/src/renderer/signal-desk.html
$region = $htmlLines[1977..3376] -join "`n"
$region = [regex]::Replace($region, '<!--(?s:.*?)-->', { param($m) [regex]::Replace($m.Value, '[^\r\n]', ' ') })
$census = foreach ($m in [regex]::Matches($region, '<(input|select|textarea|button)\b[^>]*>')) {
  [pscustomobject]@{
    Tag = $m.Groups[1].Value
    Id = [regex]::Match($m.Value, '\bid="([^"]+)"').Groups[1].Value
    Line = 1978 + [regex]::Matches($region.Substring(0, $m.Index), '\n').Count
  }
}
$census | Format-Table Tag, Id, Line
$census | Group-Object Tag | Select-Object Name, Count
~~~

Expected: input 66, select 18, textarea 2, button 88. For dynamic coverage, search the four feature modules named above for createElement, generated innerHTML, value/checked writes, recorded binding state and data-app-profile-select; section 2.3/3 lists every discovered template. Re-resolve region boundaries after markup changes instead of reusing stale line offsets.


## 2. Every native form control

For each row, the audit ID maps to `main:docs/arc/SETTINGS_INDEX.md` section 1. `NONE-search` is a transient control omitted from that key-oriented audit. Source location is exact and V. Different fields sharing an audit row remain individually enumerated.

### 2.1 Utilities: 39 static controls

| Element ID | Location | Audit row | Proposed fate | User-visible result |
|---|---|---|---|---|
| `sdUtilLlmSelect` | `app/src/renderer/signal-desk.html:2013` | LLM-03 | derive automatically | Models shows the locally qualified recommendation/readiness; explicit model override remains in Advanced and never downloads on select. |
| `sdUtilWhisperSelect` | `app/src/renderer/signal-desk.html:2032` | STT-01 | owned by mode | Mode requests a qualified STT policy; bundled base.en is bootstrap. Models/Advanced retain explicit installed-model override; acquisition needs its own grant. |
| `sdUtilAudioDeviceSelect` | `app/src/renderer/signal-desk.html:2086` | AUD-01 | keep visible | Talk microphone status opens the actual device picker; first-run confirmation stays optional after consent. Preserve device/fingerprint. |
| `sdUtilHotkeyRecordingInput` | `app/src/renderer/signal-desk.html:2106` | HK-01 | move to one Advanced screen | Bindings: edit Record with live collision/capability validation; Talk shows the actual applied key. |
| `sdUtilHotkeyForceStopInput` | `app/src/renderer/signal-desk.html:2116` | HK-03 | owned by mode | Mode supplies a qualified stop binding; Advanced override and always-visible Emergency Stop remain. |
| `sdUtilHotkeyManualSendInput` | `app/src/renderer/signal-desk.html:2126` | HK-04 | move to one Advanced screen | Bindings: edit Primary Action; keep current Accept-then-place behavior explicit. |
| `sdUtilHotkeyReviewTtsInput` | `app/src/renderer/signal-desk.html:2136` | HK-06 | move to one Advanced screen | Bindings: optional read-aloud shortcut only when its local capability is available. |
| `sdUtilHotkeySelectionRewriteInput` | `app/src/renderer/signal-desk.html:2146` | HK-05 | owned by mode | Mode owns rewrite availability; Advanced override, contextual Rewrite selected text action, and qualification stay. |
| `sdUtilHotkeyChatOpenInput` | `app/src/renderer/signal-desk.html:2156` | HK-07 | move to one Advanced screen | Bindings: legacy open-chat route only, disclose submission effects; do not expose as Gamer protection. |
| `sdUtilHotkeyVoiceMuteInput` | `app/src/renderer/signal-desk.html:2166` | HK-09 | move to one Advanced screen | Audio privacy binding, with actual Windows limitations; never promise app isolation. |
| `sdUtilWakeEnabledToggle` | `app/src/renderer/signal-desk.html:2179` | WAKE-01 | owned by mode | Later point-of-use wake grant/arming; remain hidden and inert while wakeWordSettings=false. Selecting Hands-free never arms it. |
| `sdUtilWakeModelSelect` | `app/src/renderer/signal-desk.html:2184` | WAKE-02 | move to one Advanced screen | Experimental Wake: classifier selection; remains unavailable under current capability gate. |
| `sdUtilWakeImportFile` | `app/src/renderer/signal-desk.html:2188` | WAKE-08 | move to one Advanced screen | Experimental Wake: explicit local ONNX import, hidden file input paired with its import button; gate unchanged. |
| `sdUtilWakeTrainPhrase` | `app/src/renderer/signal-desk.html:2195` | WAKE-08 | move to one Advanced screen | Experimental Wake: phrase authoring; keep hidden/inert until qualification, not first run. |
| `sdUtilWakeSensitivity` | `app/src/renderer/signal-desk.html:2207` | WAKE-03 | move to one Advanced screen | Experimental Wake threshold override; no automatic enabling. |
| `sdUtilWakeCooldown` | `app/src/renderer/signal-desk.html:2211` | WAKE-04 | move to one Advanced screen | Experimental Wake cooldown override; gate unchanged. |
| `sdUtilWakeMaxRecording` | `app/src/renderer/signal-desk.html:2215` | WAKE-05 | delete | Remove this ignored writer only after verifying WAKE-05 again; retain legacy saved value for rollback. |
| `sdUtilDictionaryInput` | `app/src/renderer/signal-desk.html:2237` | STT-14 | keep visible | Contextual Add a word after a draft edit opens the dictionary content editor; full list remains Advanced. |
| `sdUtilMacrosEnabledToggle` | `app/src/renderer/signal-desk.html:2251` | STT-11 | move to one Advanced screen | Commands customization retains disable for existing macros; discovery uses Things you can say, not a setup switch. |
| `sdUtilMacroTrigger` | `app/src/renderer/signal-desk.html:2254` | STT-15 | keep visible | Things you can say → Add a phrase opens the macro trigger editor; distinct from dictionary correction. |
| `sdUtilMacroExpansion` | `app/src/renderer/signal-desk.html:2255` | STT-15 | keep visible | Same contextual macro editor shows the exact expansion before explicit Add. |
| `draftRescueVariantFaithful` | `app/src/renderer/signal-desk.html:2305` | WF-05 | keep visible | Move live draft-bound result choice into Messages/contextual draft rescue; preserve faithful/clearer/alternate semantics and exact reviewed draft. |
| `draftRescueVariantClearer` | `app/src/renderer/signal-desk.html:2306` | WF-05 | keep visible | Move live draft-bound result choice into Messages/contextual draft rescue; preserve faithful/clearer/alternate semantics and exact reviewed draft. |
| `draftRescueVariantAlternate` | `app/src/renderer/signal-desk.html:2307` | WF-05 | keep visible | Move live draft-bound result choice into Messages/contextual draft rescue; preserve faithful/clearer/alternate semantics and exact reviewed draft. |
| `messageRescueVariantFaithful` | `app/src/renderer/signal-desk.html:2349` | WF-05 | delete | Remove production synthetic-preview fixture controls only; retain real draft rescue/Scribe choices and their evidence. |
| `messageRescueVariantClearer` | `app/src/renderer/signal-desk.html:2350` | WF-05 | delete | Remove production synthetic-preview fixture controls only; retain real draft rescue/Scribe choices and their evidence. |
| `messageRescueVariantAlternate` | `app/src/renderer/signal-desk.html:2351` | WF-05 | delete | Remove production synthetic-preview fixture controls only; retain real draft rescue/Scribe choices and their evidence. |
| `sdUtilKeepLlm` | `app/src/renderer/signal-desk.html:2453` | LLM-04 | derive automatically | Qualified memory/cleanup policy controls residency; Advanced manual pin override remains until measured policy ships. |
| `sdUtilKeepStt` | `app/src/renderer/signal-desk.html:2454` | STT-09 | derive automatically | Qualified RAM/latency policy controls residency after consent; never implies download permission. |
| `sdUtilKeepTts` | `app/src/renderer/signal-desk.html:2455` | TTS-10 | owned by mode | Read-back preference plus qualified memory limits; keep off for unavailable engines, Advanced override remains. |
| `sdUtilAudioDucking` | `app/src/renderer/signal-desk.html:2463` | AUD-12 | move to one Advanced screen | Audio → Duck speakers: voluntary setting; distinguish speaker ducking from microphone privacy. |
| `sdUtilWorkflowName` | `app/src/renderer/signal-desk.html:2489` | WF-01 | move to one Advanced screen | Experimental workflows: saved name/content, still hidden and inert; no launch action implied. |
| `sdUtilWorkflowTriggers` | `app/src/renderer/signal-desk.html:2493` | WF-01 | move to one Advanced screen | Experimental workflows: trigger authoring preserved under workflowSettings=false. |
| `sdUtilWorkflowSteps` | `app/src/renderer/signal-desk.html:2497` | WF-01 | move to one Advanced screen | Experimental workflows: ordered content; retain compile/review/approval boundaries. |
| `sdUtilWorkflowEnabled` | `app/src/renderer/signal-desk.html:2508` | WF-01 | move to one Advanced screen | Experimental workflow activation; preserve per-workflow approval and gate, not mode auto-enable. |
| `sdUtilGameSetupChatKey` | `app/src/renderer/signal-desk.html:2547` | HK-28 | delete | Later clipboard-only wizard removes this unsaved chat-key step and dependent hasChatKey gates together; not in slice 1. |
| `sdUtilGameSetupDelivery` | `app/src/renderer/signal-desk.html:2551` | APP-04 | move to one Advanced screen | Game controller setup: show only supported effective clipboard behavior. Legacy injection_policy is not an enforced safety control. |
| `sdUtilGameSetupAcknowledge` | `app/src/renderer/signal-desk.html:2561` | HK-29 | move to one Advanced screen | Point-of-use risk acknowledgement remains only for a qualified risky action; clipboard-only path must not require irrelevant type warning. |
| `sdUtilGameSetupProfileName` | `app/src/renderer/signal-desk.html:2576` | HK-27 | move to one Advanced screen | Game controller setup: profile name saved with bindings; preserve existing application profiles and unknown fields. |

### 2.2 Settings: 47 static controls

| Element ID | Location | Audit row | Proposed fate | User-visible result |
|---|---|---|---|---|
| `sdSetSearchInput` | `app/src/renderer/signal-desk.html:2603` | NONE-search | keep visible | Search includes visible and Advanced destinations; result opens the real control with breadcrumb/gate reason. No new persisted key. |
| `sdSetProfileSelect` | `app/src/renderer/signal-desk.html:2663` | PRIV-06 | keep visible | Profile: current named configuration, distinct from Mode and application matching. |
| `sdSetNewProfileName` | `app/src/renderer/signal-desk.html:2673` | PRIV-06 | keep visible | Profile operations: create/rename/duplicate name with current validation; can be expanded on demand. |
| `sdSetImportProfileFile` | `app/src/renderer/signal-desk.html:2684` | PRIV-06 | keep visible | Profile operations: explicit import preview, schema validation and preserved unknown/legacy fields. |
| `sdSetRecordingMode` | `app/src/renderer/signal-desk.html:2705` | HK-02 | owned by mode | One Mode selector chooses recording behavior; real PTT capability required; explicit Advanced override remains. |
| `sdSetAutoStopSilence` | `app/src/renderer/signal-desk.html:2719` | AUD-06 | owned by mode | Qualified manual-start Hands-free silence stop; no ambient listening, retain custom override. |
| `sdSetAutoStopSilenceMs` | `app/src/renderer/signal-desk.html:2729` | AUD-07 | owned by mode | Mode pause duration with Advanced adjustment and real-mic qualification; Ideas pauses do not silently terminate. |
| `sdSetAutoStopMinMs` | `app/src/renderer/signal-desk.html:2740` | AUD-08 | move to one Advanced screen | Audio: minimum capture guard remains adjustable independently of silence duration. |
| `sdSetVoiceCommands` | `app/src/renderer/signal-desk.html:2751` | STT-10 | owned by mode | Mode command availability; contextual Things you can say exposes supported phrases and whether active. |
| `sdSetNoAudioDuration` | `app/src/renderer/signal-desk.html:2763` | AUD-03 | derive automatically | Only replace after explicit calibrated diagnostic/measurement; keep Advanced override and old value until qualified. |
| `sdSetNoAudioRms` | `app/src/renderer/signal-desk.html:2771` | AUD-04 | derive automatically | Noise-floor policy after qualification; audit C10 shared consumers must be disentangled/tested before replacing this input. |
| `sdSetNoAudioPeak` | `app/src/renderer/signal-desk.html:2779` | AUD-05 | derive automatically | Peak policy after qualification; no two-second spoken mic check masquerading as room-tone calibration. |
| `sdSetSendMode` | `app/src/renderer/signal-desk.html:2798` | REV-01 | owned by mode | Mode review protection plus preserved legacy custom opt-in; Advanced override has truthful open-chat/submission disclosure. |
| `sdSetConfidenceForceReview` | `app/src/renderer/signal-desk.html:2815` | REV-03 | move to one Advanced screen | Review safety: retain enabled invariant/gate; hide from routine Settings, never relax to fake speed. |
| `sdSetConfidenceForceReviewBelow` | `app/src/renderer/signal-desk.html:2822` | REV-04 | move to one Advanced screen | Review confidence threshold with effective-value explanation; preserve saved setting. |
| `sdSetConfidenceAutoSendAbove` | `app/src/renderer/signal-desk.html:2830` | REV-05 | move to one Advanced screen | Qualified custom auto-send threshold; unavailable when review/safety policy forbids it. |
| `sdSetAutoSubmit` | `app/src/renderer/signal-desk.html:2845` | REV-02 | owned by mode | Default false; no mode selection grants Enter/submission. Preserve prior custom intent, enforce Gamer prohibition, point-of-use opt-in. |
| `sdSetRestoreClipboard` | `app/src/renderer/signal-desk.html:2856` | REV-06 | move to one Advanced screen | Placement: restoration preference preserved; explain current text-only restoration limit. |
| `sdSetDraftHistoryLimit` | `app/src/renderer/signal-desk.html:2866` | REV-07 | delete | Remove ignored limit knob; show actual fixed 100-draft cap and retain saved legacy value. Do not alter history retention in UI cleanup. |
| `sdSetLlmEnabled` | `app/src/renderer/signal-desk.html:2885` | LLM-01 | owned by mode | Optional Clean up writing capability action after first draft; stays off until explicit consent/acquisition/readiness; mode tap alone does not enable. |
| `sdSetCurrentPreset` | `app/src/renderer/signal-desk.html:2898` | LLM-02 | owned by mode | Persona selection lives in Studio/contextual mode customization; preserve inactive persona and show when cleanup is off. |
| `sdSetMaxCompletionTokens` | `app/src/renderer/signal-desk.html:2909` | LLM-05 | derive automatically | Measured raw-length/model-context policy with persona overrides accounted for; Advanced override retained until replacement qualifies. |
| `sdSetLongDraftWarningWords` | `app/src/renderer/signal-desk.html:2917` | LLM-08 | move to one Advanced screen | Writing: explicit long-draft warning threshold remains. |
| `sdSetLlmChunkSize` | `app/src/renderer/signal-desk.html:2925` | LLM-07 | derive automatically | Measured context budget, accounting for per-persona chunk_size; cannot delete profile control first. |
| `sdSetWhisperChunkSize` | `app/src/renderer/signal-desk.html:2933` | STT-08 | delete | Remove unused old chunk-size writer; real streaming batch policy is unaffected. Preserve old profile value. |
| `sdSetStitchPass` | `app/src/renderer/signal-desk.html:2944` | LLM-09 | derive automatically | Chunked-input policy after preservation/corpus qualification; retain Advanced override until then. |
| `sdSetUseDeliverySignals` | `app/src/renderer/signal-desk.html:2969` | LLM-14 | owned by mode | Optional disclosed speech-pacing formatting, default off; full D-0005 data/what changes/preservation disclosure follows customization. |
| `sdSetUseAudienceContext` | `app/src/renderer/signal-desk.html:2992` | LLM-15 | move to one Advanced screen | Unavailable explanation with inspect-data action; input remains locked/non-collectable until owner ruling; no new toggling permission. |
| `sdSetAppProfileOverride` | `app/src/renderer/signal-desk.html:3044` | APP-08 | move to one Advanced screen | Application mapping: explicit temporary override with clear restart lifetime, retained alongside stronger mode safety. |
| `sdSetStatusIndicator` | `app/src/renderer/signal-desk.html:3082` | UI-13 | delete | Remove ignored enable knob; actual recording/status overlay remains operational and visible. |
| `sdSetNotificationOverlay` | `app/src/renderer/signal-desk.html:3089` | UI-14 | delete | Remove ignored enable knob; actual notifications/status delivery remains unchanged. |
| `sdSetPreviewOverlay` | `app/src/renderer/signal-desk.html:3096` | UI-15 | delete | Remove ignored enable knob; real review/preview surface remains reachable. |
| `sdSetTheme` | `app/src/renderer/signal-desk.html:3129` | UI-01 | keep visible | Appearance: show actual supported Dark-only state; no invented System/Light theme or automatic theme picker until implemented. |
| `sdSetAccentColor` | `app/src/renderer/signal-desk.html:3144` | UI-02 | keep visible | Appearance: independent user color preference; no automatic or mode overwrite. |
| `sdSetDensity` | `app/src/renderer/signal-desk.html:3156` | UI-03 | keep visible | Appearance: user density preference remains accessible. |
| `sdSetFontSize` | `app/src/renderer/signal-desk.html:3166` | UI-04 | keep visible | Appearance: accessible text size remains prominent, not buried. |
| `sdSetHighContrast` | `app/src/renderer/signal-desk.html:3178` | UI-05 | keep visible | Appearance: explicit high-contrast override preserved; OS preference may suggest, never erase saved choice. |
| `sdSetOverlaySize` | `app/src/renderer/signal-desk.html:3190` | UI-06 | owned by mode | Mode effective overlay size plus Advanced/accessibility override; preserve separate Electron appearance store. |
| `sdSetOverlayPlacement` | `app/src/renderer/signal-desk.html:3202` | UI-08 | keep visible | Appearance: overlay position stays independent of profile/mode. |
| `sdSetOverlayOpacity` | `app/src/renderer/signal-desk.html:3222` | UI-09 | keep visible | Appearance: accessible opacity; mode cannot silently overwrite. |
| `sdSetOverlayVibrancy` | `app/src/renderer/signal-desk.html:3233` | UI-10 | keep visible | Appearance: retain user visual preference. |
| `sdSetOverlayLabelPos` | `app/src/renderer/signal-desk.html:3244` | UI-11 | keep visible | Appearance: retain overlay label placement. |
| `sdSetOverlayAlwaysOn` | `app/src/renderer/signal-desk.html:3260` | UI-07 | owned by mode | Effective mode overlay persistence; not an always-listening indicator. Keep explicit Advanced override and actual capture status. |
| `sdSetPrivacyWipeMode` | `app/src/renderer/signal-desk.html:3319` | PRIV-07 | keep visible | Privacy: preview selected retention/wipe scope; confirmation follows verified postconditions, not generic success. |
| `sdSetPrivacyWipeVoices` | `app/src/renderer/signal-desk.html:3329` | PRIV-07 | keep visible | Privacy: explicit cloned-voice deletion scope, even when cloning UI is disabled. |
| `sdSetPrivacyFactoryResetModels` | `app/src/renderer/signal-desk.html:3349` | PRIV-07 | keep visible | Privacy danger area: explicit model-retention choice with size/scope preview. |
| `sdSetPrivacyFactoryResetConfirm` | `app/src/renderer/signal-desk.html:3355` | PRIV-07 | keep visible | Privacy danger area: typed DELETE EVERYTHING confirmation retained; consent reset only by factory reset. |

### 2.3 Runtime-created and button-carried values

| Element/selector | Location | Audit row | Proposed fate | User-visible result |
|---|---|---|---|---|
| `sdUtilLatencyProbeMode` | `app/src/renderer/features/utilitiesWorkspace.js:2319-2325` | DIAG-04 | move to one Advanced screen | Diagnostics Light/Medium/Hard workload selector; currently stage runners can be unavailable. Selection alone never runs/loads/downloads a model. |
| `sdUtilGameSetupRecordDictation` | `app/src/renderer/signal-desk.html:2539`; `app/src/renderer/features/gameSetupWizard.js:209-217` | HK-27 / APP-06 | move to one Advanced screen | Captures a released controller binding for dictation, not a cosmetic button; preserve chord/device validation and saved binding. |
| `sdUtilGameSetupRecordCommand` | `app/src/renderer/signal-desk.html:2540`; `app/src/renderer/features/gameSetupWizard.js:209-217` | HK-27 / APP-06 | move to one Advanced screen | Distinct command binding with qualification and lost-release stop handling. |
| `[data-app-profile-select="<id>"]` (no unique element ID) | `app/src/renderer/features/applicationProfiles.js:255-277` | APP-01 / APP-07 | move to one Advanced screen | Explicit list selection used by pinning; preserve distinct selected vs active profile identity. |

Counts for the 86 static forms: **10 delete, 27 Advanced, 9 derive, 16 mode, 24 visible**. The ten deletions are five dead routine controls, ignored wake max duration, unsaved game chat-key step, and three synthetic preview radios. Only the first five belong in the first slice. No counted control lacks a fate/audit mapping.

## 3. Action and navigation coverage

The 88 buttons below are included to make routes, keyboard capture, confirm/retry/cancel and retained content reviewable. Most do not store a value; treating them as controls prevents a form-only scan from erasing a workflow. No-ID navigation buttons are identified by source line: 1987 Library and 1988 History both currently route `data-shell-nav="library"`; 1989 Game Mode shares `data-util-nav="advanced"`. These aliases need destination redirects before removal.

| Element ID | Location | Audit row | Proposed fate | User-visible result |
|---|---|---|---|---|
| `sdUtilNavModels` | `app/src/renderer/signal-desk.html:1981` | NONE-navigation | keep visible | Retain contextual Models destination into the single Advanced component. |
| `sdUtilNavSpeech` | `app/src/renderer/signal-desk.html:1982` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `sdUtilNavText` | `app/src/renderer/signal-desk.html:1983` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `sdUtilNavDiagnostics` | `app/src/renderer/signal-desk.html:1984` | NONE-navigation | keep visible | Retain contextual Runtime Diagnostics destination into the single Advanced component. |
| `sdUtilNavAdvanced` | `app/src/renderer/signal-desk.html:1985` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `(no id; line 1987)` | `app/src/renderer/signal-desk.html:1987` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `(no id; line 1988)` | `app/src/renderer/signal-desk.html:1988` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `(no id; line 1989)` | `app/src/renderer/signal-desk.html:1989` | NONE-navigation | delete | Remove this duplicated top-level subsection/alias only after redirecting its deep links to Advanced, Library, History, content editors or qualified controller setup. |
| `sdUtilModelsRefreshButton` | `app/src/renderer/signal-desk.html:2001` | STT-17 | move to one Advanced screen | Models: explicit Models Refresh remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilLlmSelectButton` | `app/src/renderer/signal-desk.html:2020` | STT-17 | move to one Advanced screen | Models: explicit Llm Select remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilLlmDownloadButton` | `app/src/renderer/signal-desk.html:2021` | STT-17 | move to one Advanced screen | Models: explicit Llm Download remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilLlmUnloadButton` | `app/src/renderer/signal-desk.html:2022` | STT-17 | move to one Advanced screen | Models: explicit Llm Unload remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilLlmDeleteButton` | `app/src/renderer/signal-desk.html:2023` | STT-17 | move to one Advanced screen | Models: explicit Llm Delete remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilWhisperSelectButton` | `app/src/renderer/signal-desk.html:2039` | STT-17 | move to one Advanced screen | Models: explicit Whisper Select remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilWhisperDownloadButton` | `app/src/renderer/signal-desk.html:2040` | STT-17 | move to one Advanced screen | Models: explicit Whisper Download remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilWhisperUnloadButton` | `app/src/renderer/signal-desk.html:2041` | STT-17 | move to one Advanced screen | Models: explicit Whisper Unload remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilWhisperDeleteButton` | `app/src/renderer/signal-desk.html:2042` | STT-17 | move to one Advanced screen | Models: explicit Whisper Delete remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilUnloadTtsButton` | `app/src/renderer/signal-desk.html:2061` | STT-17 | move to one Advanced screen | Models: explicit Unload Tts remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilVoiceCloningProvisionButton` | `app/src/renderer/signal-desk.html:2072` | TTS-13 | move to one Advanced screen | Models: explicit Voice Cloning Provision remains; preserve acquisition grant, actual readiness, progress, cancel/error and deletion confirmation; gated cloning stays unavailable. |
| `sdUtilAudioTestMicButton` | `app/src/renderer/signal-desk.html:2089` | AUD-01 | keep visible | Talk microphone recovery action opens consented real-path diagnostic after D2 implementation; current browser test must remain labeled Browser access until then. |
| `sdUtilHotkeyRecordingClear` | `app/src/renderer/signal-desk.html:2107` | HK-01 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeyForceStopClear` | `app/src/renderer/signal-desk.html:2117` | HK-03 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeyManualSendClear` | `app/src/renderer/signal-desk.html:2127` | HK-04 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeyReviewTtsClear` | `app/src/renderer/signal-desk.html:2137` | HK-06 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeySelectionRewriteClear` | `app/src/renderer/signal-desk.html:2147` | HK-05 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeyChatOpenClear` | `app/src/renderer/signal-desk.html:2157` | HK-07 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilHotkeyVoiceMuteClear` | `app/src/renderer/signal-desk.html:2167` | HK-09 | move to one Advanced screen | Bindings: clear exactly this binding, validate collisions/required stop behavior, persist full profile; active mode safety can reject invalid clear. |
| `sdUtilWakeImportButton` | `app/src/renderer/signal-desk.html:2187` | WAKE-08 | move to one Advanced screen | Experimental Wake: explicit import/train/test only, still hidden/inert and subject to local capture/acquisition grants. |
| `sdUtilWakeTrainButton` | `app/src/renderer/signal-desk.html:2196` | WAKE-08 | move to one Advanced screen | Experimental Wake: explicit import/train/test only, still hidden/inert and subject to local capture/acquisition grants. |
| `sdUtilWakeTestButton` | `app/src/renderer/signal-desk.html:2220` | WAKE-08 | move to one Advanced screen | Experimental Wake: explicit import/train/test only, still hidden/inert and subject to local capture/acquisition grants. |
| `sdUtilDictionaryAddButton` | `app/src/renderer/signal-desk.html:2238` | STT-14 | keep visible | Contextual content editor: explicit Add; validation, Enter handling and separate dictionary/macro semantics remain. |
| `sdUtilMacroAddButton` | `app/src/renderer/signal-desk.html:2256` | STT-15 | keep visible | Contextual content editor: explicit Add; validation, Enter handling and separate dictionary/macro semantics remain. |
| `draftRescueCaptureButton` | `app/src/renderer/signal-desk.html:2268` | WF-05 | keep visible | Live Messages/draft rescue: retain explicit context capture/clear/run/cancel; no context capture on mode switch and no lost draft choice. |
| `draftRescueClearContextButton` | `app/src/renderer/signal-desk.html:2269` | WF-05 | keep visible | Live Messages/draft rescue: retain explicit context capture/clear/run/cancel; no context capture on mode switch and no lost draft choice. |
| `draftRescueRunButton` | `app/src/renderer/signal-desk.html:2277` | WF-05 | keep visible | Live Messages/draft rescue: retain explicit context capture/clear/run/cancel; no context capture on mode switch and no lost draft choice. |
| `draftRescueCancelButton` | `app/src/renderer/signal-desk.html:2278` | WF-05 | keep visible | Live Messages/draft rescue: retain explicit context capture/clear/run/cancel; no context capture on mode switch and no lost draft choice. |
| `messageRescueClearContextButton` | `app/src/renderer/signal-desk.html:2326` | WF-05 | delete | Remove synthetic preview action; live draft/Scribe context clearing survives separately. |
| `sdUtilDoctorRefreshButton` | `app/src/renderer/signal-desk.html:2373` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdUtilRecordingsClearButton` | `app/src/renderer/signal-desk.html:2391` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdUtilSidecarLogsClearButton` | `app/src/renderer/signal-desk.html:2406` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdBugReportOpen` | `app/src/renderer/signal-desk.html:2415` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdUtilCopySupportReportButton` | `app/src/renderer/signal-desk.html:2416` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdUtilRefreshDiagnosticsButton` | `app/src/renderer/signal-desk.html:2417` | DIAG-06 | move to one Advanced screen | Diagnostics: retain explicit action, state/error reporting and safe cancellation; never invoke by navigation. |
| `sdUtilWarmupSttButton` | `app/src/renderer/signal-desk.html:2438` | DIAG-05 | move to one Advanced screen | Diagnostics: explicit local readiness/binding repair; no missing-model acquisition fallback, no UI freeze, actual result required. |
| `sdUtilWarmupLlmButton` | `app/src/renderer/signal-desk.html:2439` | DIAG-05 | move to one Advanced screen | Diagnostics: explicit local readiness/binding repair; no missing-model acquisition fallback, no UI freeze, actual result required. |
| `sdUtilStartHotkeysButton` | `app/src/renderer/signal-desk.html:2440` | DIAG-05 | move to one Advanced screen | Diagnostics: explicit local readiness/binding repair; no missing-model acquisition fallback, no UI freeze, actual result required. |
| `sdUtilTestModelLoadButton` | `app/src/renderer/signal-desk.html:2441` | DIAG-05 | move to one Advanced screen | Diagnostics: explicit local readiness/binding repair; no missing-model acquisition fallback, no UI freeze, actual result required. |
| `sdUtilPrimaryActionButton` | `app/src/renderer/signal-desk.html:2444` | HK-04 / HK-03 | keep visible | Talk primary action stays discoverable; Advanced keeps explicit diagnostic action; preserve current reviewed-draft behavior. |
| `sdUtilEmergencyStopButton` | `app/src/renderer/signal-desk.html:2445` | HK-04 / HK-03 | keep visible | Always-reachable Emergency Stop remains outside Advanced as well; cancel/stop is never gated by mode availability. |
| `sdUtilTestPasteCopyButton` | `app/src/renderer/signal-desk.html:2464` | DIAG-07 | move to one Advanced screen | Diagnostics: user-initiated placement/clipboard test into a disposable chosen target; warn about side effects and respect Gamer clamps. |
| `sdUtilWorkflowCompileButton` | `app/src/renderer/signal-desk.html:2501` | WF-01 | move to one Advanced screen | Experimental workflows: retain ordered compile/save/approve/run transitions and run approval binding; hidden/inert gate unchanged. |
| `sdUtilWorkflowSaveButton` | `app/src/renderer/signal-desk.html:2502` | WF-01 | move to one Advanced screen | Experimental workflows: retain ordered compile/save/approve/run transitions and run approval binding; hidden/inert gate unchanged. |
| `sdUtilWorkflowApproveButton` | `app/src/renderer/signal-desk.html:2503` | WF-01 | move to one Advanced screen | Experimental workflows: retain ordered compile/save/approve/run transitions and run approval binding; hidden/inert gate unchanged. |
| `sdUtilWorkflowRunButton` | `app/src/renderer/signal-desk.html:2504` | WF-01 | move to one Advanced screen | Experimental workflows: retain ordered compile/save/approve/run transitions and run approval binding; hidden/inert gate unchanged. |
| `sdUtilGameSetupDetectButton` | `app/src/renderer/signal-desk.html:2534` | HK-27 / APP-06 | move to one Advanced screen | Controller setup: retain explicit detect/rehearse/save; remove unsaved-chat-key dependency coherently and merge full application profile without data loss. |
| `sdUtilGameSetupRecordDictation` | `app/src/renderer/signal-desk.html:2539` | HK-27 / APP-06 | move to one Advanced screen | Controller setup: this button captures a real binding value; preserve release/chord/device validation, cancel/retry and qualification. |
| `sdUtilGameSetupRecordCommand` | `app/src/renderer/signal-desk.html:2540` | HK-27 / APP-06 | move to one Advanced screen | Controller setup: this button captures a real binding value; preserve release/chord/device validation, cancel/retry and qualification. |
| `sdUtilGameSetupRehearseButton` | `app/src/renderer/signal-desk.html:2570` | HK-27 / APP-06 | move to one Advanced screen | Controller setup: retain explicit detect/rehearse/save; remove unsaved-chat-key dependency coherently and merge full application profile without data loss. |
| `sdUtilGameSetupSaveButton` | `app/src/renderer/signal-desk.html:2579` | HK-27 / APP-06 | move to one Advanced screen | Controller setup: retain explicit detect/rehearse/save; remove unsaved-chat-key dependency coherently and merge full application profile without data loss. |
| `sdSetNavProfile` | `app/src/renderer/signal-desk.html:2611` | NONE-navigation | keep visible | Keep this top-level Settings section, keyboard navigation and aria-current. |
| `sdSetNavRecording` | `app/src/renderer/signal-desk.html:2612` | NONE-navigation | delete | Remove old category after replacement is reachable; Recording/Review/Cleanup route to Customize this mode in Advanced; Notifications disappears after five dead controls are removed. |
| `sdSetNavReview` | `app/src/renderer/signal-desk.html:2613` | NONE-navigation | delete | Remove old category after replacement is reachable; Recording/Review/Cleanup route to Customize this mode in Advanced; Notifications disappears after five dead controls are removed. |
| `sdSetNavAiCleanup` | `app/src/renderer/signal-desk.html:2614` | NONE-navigation | delete | Remove old category after replacement is reachable; Recording/Review/Cleanup route to Customize this mode in Advanced; Notifications disappears after five dead controls are removed. |
| `sdSetNavNotifications` | `app/src/renderer/signal-desk.html:2615` | NONE-navigation | delete | Remove old category after replacement is reachable; Recording/Review/Cleanup route to Customize this mode in Advanced; Notifications disappears after five dead controls are removed. |
| `sdSetNavAppearance` | `app/src/renderer/signal-desk.html:2616` | NONE-navigation | keep visible | Keep this top-level Settings section, keyboard navigation and aria-current. |
| `sdSetNavPrivacy` | `app/src/renderer/signal-desk.html:2617` | NONE-navigation | keep visible | Keep this top-level Settings section, keyboard navigation and aria-current. |
| `sdSetUpdatePrimaryButton` | `app/src/renderer/signal-desk.html:2644` | DIAG-03 | move to one Advanced screen | Advanced Help: retain check/download/install/later/resume state-dependent actions; no automatic check/acquisition from opening the page. |
| `sdSetUpdateLaterButton` | `app/src/renderer/signal-desk.html:2645` | DIAG-03 | move to one Advanced screen | Advanced Help: retain check/download/install/later/resume state-dependent actions; no automatic check/acquisition from opening the page. |
| `sdSetUpdateResumeButton` | `app/src/renderer/signal-desk.html:2646` | DIAG-03 | move to one Advanced screen | Advanced Help: retain check/download/install/later/resume state-dependent actions; no automatic check/acquisition from opening the page. |
| `sdSetReplayQuickSetup` | `app/src/renderer/signal-desk.html:2670` | UI-35 | keep visible | Profile/Help: optional replay only; do not delete replay with the auto-run flag. Reconcile stale tutorial first. |
| `sdSetActivateProfileButton` | `app/src/renderer/signal-desk.html:2675` | PRIV-06 | keep visible | Profile operations: preserve explicit activate, validation, Default protection and errors; no mode adoption implied. |
| `sdSetCreateProfileButton` | `app/src/renderer/signal-desk.html:2676` | PRIV-06 | keep visible | Profile operations: preserve explicit create, validation, Default protection and errors; no mode adoption implied. |
| `sdSetRenameProfileButton` | `app/src/renderer/signal-desk.html:2677` | PRIV-06 | keep visible | Profile operations: preserve explicit rename, validation, Default protection and errors; no mode adoption implied. |
| `sdSetDuplicateProfileButton` | `app/src/renderer/signal-desk.html:2678` | PRIV-06 | keep visible | Profile operations: preserve explicit duplicate, validation, Default protection and errors; no mode adoption implied. |
| `sdSetExportProfileButton` | `app/src/renderer/signal-desk.html:2681` | PRIV-06 | keep visible | Profile operations: preserve explicit export, validation, Default protection and errors; no mode adoption implied. |
| `sdSetDeleteProfileButton` | `app/src/renderer/signal-desk.html:2686` | PRIV-06 | keep visible | Profile operations: preserve explicit delete, validation, Default protection and errors; no mode adoption implied. |
| `sdSetDeliverySignalsInspect` | `app/src/renderer/signal-desk.html:2966` | LLM-14 | move to one Advanced screen | Customization: disclosure Inspect action remains beside the feature and its preservation/unavailable reason; no enabling locked feature. |
| `sdSetAudienceContextInspect` | `app/src/renderer/signal-desk.html:2989` | LLM-15 | move to one Advanced screen | Customization: disclosure Inspect action remains beside the feature and its preservation/unavailable reason; no enabling locked feature. |
| `sdSetAppProfileOverrideClear` | `app/src/renderer/signal-desk.html:3045` | APP-08 | move to one Advanced screen | Application mappings: preserve explicit pin/clear override semantics; global mode safety cannot be weakened; do not display unenforced policy as applied. |
| `sdSetAppProfilePinButton` | `app/src/renderer/signal-desk.html:3055` | APP-07 | move to one Advanced screen | Application mappings: preserve explicit pin/clear override semantics; global mode safety cannot be weakened; do not display unenforced policy as applied. |
| `sdSetPrivacyPersonaLearningClear` | `app/src/renderer/signal-desk.html:3301` | PRIV-09 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetPrivacyPersonaLearningVerify` | `app/src/renderer/signal-desk.html:3302` | PRIV-09 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetPrivacyExportButton` | `app/src/renderer/signal-desk.html:3303` | PRIV-07 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetPrivacyWipeButton` | `app/src/renderer/signal-desk.html:3333` | PRIV-07 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetPrivacyFactoryResetButton` | `app/src/renderer/signal-desk.html:3359` | PRIV-07 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetPrivacyFactoryResetVerify` | `app/src/renderer/signal-desk.html:3360` | PRIV-07 | keep visible | Privacy: retain explicit preview/export/clear/reset/verify action, data inventory, per-action confirmation, truthful postconditions and consent-retention rules. |
| `sdSetDiscardButton` | `app/src/renderer/signal-desk.html:3373` | PRIV-06 | keep visible | Shared dirty-state footer for all editable Advanced/Profile settings: preserve unknown keys, cancel/discard and safe persistence, never replacement-save a five-field subset. |
| `sdSetSaveButton` | `app/src/renderer/signal-desk.html:3374` | PRIV-06 | keep visible | Shared dirty-state footer for all editable Advanced/Profile settings: preserve unknown keys, cancel/discard and safe persistence, never replacement-save a five-field subset. |

The 88-button fates are 11 deletions (old category/duplicate route aliases and synthetic preview clear), 48 Advanced and 29 visible/contextual actions. Controller record buttons appear both here and section 2.3, and are counted only once.

Dynamic templates, V source / P destination (no fixed instance count):

| ID/selector or parent | Creation site | Audit row | Fate/result |
|---|---|---|---|
| No ID; Download under `sdUtilWakeBackboneList` | `app/src/renderer/features/utilitiesWorkspace.js:1355-1360` | WAKE-08 | Advanced Experimental Wake; stays gated; one-artifact acquisition consent required. |
| No ID; Delete under same list | `app/src/renderer/features/utilitiesWorkspace.js:1363-1368` | WAKE-08 | Advanced Experimental Wake; preserve imported-classifier deletion/confirmation. |
| No ID; per-term remove under `sdUtilDictionaryList` | `app/src/renderer/features/utilitiesWorkspace.js:2049-2056` | STT-14 | Contextual dictionary editor plus Advanced; explicit delete, no content migration loss. |
| No ID; suggestion under `sdUtilDictionarySuggestions` | `app/src/renderer/features/utilitiesWorkspace.js:2075-2080` | STT-14 | Keep contextual post-edit Add suggestion; a suggestion is not auto-acceptance. |
| No ID; per-macro remove under `sdUtilMacrosList` | `app/src/renderer/features/utilitiesWorkspace.js:2137-2144` | STT-15 | Contextual macro editor plus Advanced; keep exact trigger/expansion and separate dictionary semantics. |
| `sdUtilLatencyProbeRunButton` | `app/src/renderer/features/utilitiesWorkspace.js:2328-2333` | DIAG-04 | Advanced Diagnostics; explicit bounded run, truthful unavailable result, no acquisition fallback. |
| No ID; Re-transcribe under `sdUtilRecordingsList` | `app/src/renderer/features/utilitiesWorkspace.js:2492-2503` | DIAG-06 | Advanced Diagnostics/Library recovery action; retain source recording and explicit retry, no unsolicited inference. |
| No ID; Discard under same list | `app/src/renderer/features/utilitiesWorkspace.js:2504-2518` | DIAG-06 | Recovery/Privacy: explicit discard with honest postcondition, never folded into a general settings save. |
| No ID; Cancel under `sdUtilJobsList` | `app/src/renderer/features/utilitiesWorkspace.js:2549-2557` | DIAG-06 | Diagnostics: retain per-job cancellation and requested-vs-finished state. |
| `[data-app-profile-select]` | `app/src/renderer/features/applicationProfiles.js:272-273` | APP-01/07 | Same choice template counted in 2.3, not an eleventh template. |

Disabled workflow compile/save/approve/run buttons carry approval state but remain action transitions, not four new profile settings. Dynamic options in profile/model/device selects belong to their single selector rows; every option is not a separate control. Display-only store inventories, capability dumps, progress/meter fills, effective mode summaries, update channel and latency tables are retained readouts (DIAG-01/06, PRIV-07, APP-01); they are not editable controls. One `instant_typing` mapping survives without a production input (`app/src/renderer/features/settingsWorkspace.js:546,579,898`); clear those stale renderer mappings with the existing intentional cut, but do not call the backend key dead—it still has consumers.

## 4. Resulting information architecture [P]

```text
Talk persistent header: Mode [Work / Gamer / Ideas / Messages / Hands-free]
  shows Custom / unavailable reason; one selector, not an extra Gamer toggle
Talk next to capture: actual microphone + Record binding + always available Stop
Draft actions: Review / Place / Copy / Rewrite selected text
  Things you can say → supported phrases and current availability
  Add a word / Add a phrase → dictionary and macro content editors
  Optional Clean up writing → explicit capability/model/consent workflow

Settings [search all destinations]
  Profile
    active named profile; expandable create/rename/duplicate/import/export/delete
    optional Take a tour / Help
  Appearance
    supported theme; accent; density; text size; contrast
    overlay placement/opacity/vibrancy/label placement
    effective mode size/persistence plus Customize link
  Privacy
    network activity and on-device store inventory
    export / recordings and learned-example removal / listener state
    danger area: wipe scope + preview + cloned voices + reset models + typed confirm
  Advanced → ONE destination/component (searchable grouped disclosure)
    Customize current mode: effective defaults, overrides, enforced explanations
    Bindings / Audio / Review safety
    Models: acquisition, qualified installed override, integrity/readiness/removal
    Runtime Diagnostics: Doctor / metrics / probe / recovery / jobs / logs
    Application/controller mappings (qualified Game setup, no global mode duplicate)
    Content management (dictionary/macros); Help and explicit update actions
    Experimental unavailable capabilities (current flags preserved)
Library / History / Studio / Scribe remain their actual saved-content/authoring surfaces.
```

Models and Runtime Diagnostics can have contextual direct links from readiness/error status; they route to the same Advanced component. Remove the second Utilities Advanced navigation and the duplicate category strip once redirects work; retain existing workspace IDs/deep-link compatibility during transition. Profile, Mode and matched application profile remain three distinct concepts, not three names for the same state. A backend profile activation still applies its saved bindings/configuration; moving its picker does not create a resolver.

**Explicit deviations from the audit:** keep Appearance accessibility controls prominent instead of hiding font/density or automatically replacing explicit theme/contrast choices (UI-01..05); keep Privacy/destructive scopes accessible instead of burying them under Advanced (PRIV-07). Keep optional tour replay; remove its automatic launch, not its ability to replay (UI-35). Audit AUTO is a hypothesis, not proof that a heuristic safely replaces a knob. No noise-floor derivation from D2's spoken diagnostic alone: that is a signal/device check, not controlled room tone. AUD-04/05 currently feed three subsystems (audit C10), so an automatic policy needs separate behavior tests.

Feature discovery is action-based [P]:
- **Things you can say:** short, capability-aware list for punctuation, edit commands and supported review/stop commands; never advertise “send it” as unconditional safe delivery. Show mode restrictions and actual binding/input support.
- **Dictionary/macros:** suggest after explicit draft edits; Add remains user intent. Distinct correction terms versus expansion phrases remain separate stores/editors.
- **Cleanup/personas:** after the first useful draft, offer an optional action with installed/verified/disabled explanation. No mode tap auto-downloads/enables a multi-GB engine; inactive custom persona choice remains saved. Studio owns authoring, not a second Settings prompt editor.
- **Hands-free/Gamer:** visible mode availability reasons, contextual qualified setup, independent stop. No hidden capture, auto-rearm or game-safety claim because a control disappeared.
- **Wake/workflows/cloning/teach-from-edits/traits:** keep current capability gates, show a local unavailable explanation where relevant, and retain privacy deletion access. A hidden DOM element does not secure its backend route (audit C15); permission enforcement is separate work. This plan grants no activation.
- **Message Rescue:** move the live draft-bound surface/context actions, preserve Scribe's actual result semantics; remove synthetic demo fixtures only. No mock recommendations in a production “help me” feature.
- **Latency diagnostics:** show unavailable until real runners are wired; scope automatic tuning to real inference, quality/preservation and hardware evidence. A UI probe existing is not a measurement.

All moves preserve keyboard paths, focus after navigation, real labels, contrast and accessible sizing. Search indexes Advanced controls/content destinations and disabled reasons; searching cannot bypass an inert capability. Show a breadcrumb and expand the needed group. Keep dirty-state indicators across navigation; only explicit Save applies pending changes, and mode/appearance changes disclose their immediate/persisted behavior separately.

## 5. Verified dead-key evidence and later backend retirement

The following consumer checks were freshly performed against tracked Python/JS, including backend, main, preload, production and legacy renderer; tests, schema coercion/defaults, writers and comments were distinguished from behavioral reads. No runtime trial was made. “No behavior consumer” means no static exact-key use beyond these occurrences [V]; indirect/reflection behavior remains a risk to cover in tests [I].

| Key / audit | Fresh evidence | Renderer action now | Backend action later, after reorg |
|---|---|---|---|
| `status_indicator_enabled` UI-13 | `utils.py:462-464,926` default/coercion; `app/src/renderer/features/settingsWorkspace.js:555,588,907` writes/maps; legacy `app/src/renderer/main.js:375` maps. No main/preload/backend behavior consumer found. | Delete `sdSetStatusIndicator`, metadata/validator/maps/errors; actual capture overlay stays. | Stop generating fresh default/coercion, retain legacy value under compatibility preservation; no overlay feature deletion. |
| `notification_overlay_enabled` UI-14 | `utils.py:454-456,932`; `app/src/renderer/features/settingsWorkspace.js:556,589,908`; legacy `app/src/renderer/main.js:376`. No notification consumer found. | Delete ignored toggle and all collector/map/discovery entries. | Same preservation-first retirement; notifications remain. |
| `preview_overlay_enabled` UI-15 | `utils.py:458-460,939`; `app/src/renderer/features/settingsWorkspace.js:557,590,909`; legacy `app/src/renderer/main.js:377`. No review/preview consumer found. | Delete ignored toggle, retain real review surface. | Same preservation-first retirement; no review weakening. |
| `whisper_chunk_size` STT-08 | `utils.py:606-608,899,1107` coercion/default/validation; `app/src/renderer/features/settingsWorkspace.js:487,553,586,905,943` form plumbing; legacy `app/src/renderer/main.js:362,2250-2256` validation. No STT loader/stream behavior consumer found. | Delete obsolete number/error/writer; keep actual streaming behavior. | Retire default/validation only after saved-profile compatibility proves it does not discard value; real streaming settings remain. |
| `draft_history_limit` REV-07 | `utils.py:612-614,900`; `app/src/renderer/features/settingsWorkspace.js:495,548,581,900,951`. Actual history cap is `server.py:237,260,363,1189` = `MAX_DRAFT_HISTORY` 100; `:4262` returns that constant under this response field, not the profile setting. | Delete pretend retention preference; show fixed cap truthfully. | Retire **profile** default/coercion only; keep runtime response compatibility until separately versioned. Do not remove same-named API field blindly. |
| `wake_word_max_recording_s` WAKE-05 | `app/src/renderer/features/utilitiesWorkspace.js:1882,2011` reads form value/writes settings; legacy `app/src/renderer/main.js:384` map; no Python consumer beyond parity evidence. | Later remove hidden `sdUtilWakeMaxRecording` and its writer/render/map; leave wake gate closed. | Stop accepting it as an active tuning field; retain saved legacy/unknown data for rollback. Do not confuse with consumed `max_recording_seconds` watchdog. |

The first five controls are safe candidates for a renderer-only first slice: they promise configuration the behavior does not consume. This is a proposal, not user permission to remove anything in this task. Their saved values remain untouched, and cross-profile save must round-trip them even after the inputs disappear. An ineffective key is still data the user could want back.

Do **not** put the audit's remaining REMOVE rows into a deletion patch without their own consumer/compatibility checks. Important counterexamples: `instant_typing` has injector consumers; TTS-03..09 have real read-aloud consumers despite no live writer; `sign_off_text`, controller fields and audio aliases have readers; application `injection_policy` is stored/displayed even though enforcement is absent. “No live control,” “no live writer,” and “ignored by one runtime path” are different retirement arguments. Preserve inactive values and qualification gates.

Migration contract [P], independent of renderer moves:
1. First slice changes no profile schema, defaults, routes, retention or files on disk. Existing collection merges a patch into active settings (`app/src/renderer/features/settingsWorkspace.js:1186-1188`); retain that full-profile merge, including keys without DOM controls. Existing backend loading merges defaults with stored data (`utils.py:1050-1058`), and saving processes a complete copy (`:1234-1252`). A new small Settings screen must not replace the full profile with its visible fields.
2. Later retirement reads the raw stored file before defaults blur missing-vs-explicit. Preserve original and unknown keys, actual hotkeys, mic/fingerprint, persona references, custom/disabled opt-ins, imported future schema, executable profiles/pins and content. Create a recoverable versioned pre-migration snapshot plus normal atomic backup before any schema change. Repeated migration is idempotent; failed/conflicting writes leave the original usable.
3. Leave retired keys round-trippable as inert compatibility data (or a versioned legacy map only after export/import/downgrade behavior is specified). Never delete recordings/history/macros/dictionary/consent because a key/control becomes inert. Preserve consent storage and privacy registry independently.
4. If D1 is ratified, missing mode metadata displays `Work · Custom`, preserves legacy behavior until explicit adoption, then uses its versioned defaults/overrides plus stronger safety clamps. Do not infer user intent from equality to old defaults. Modes do not overwrite accessibility, application pins or grant acquisition permission.
5. Automatic settings replace a preference only after D3/other measured policy is qualified and the user accepts any behavior change. Manual overrides remain discoverable with effective values and reasons; unknown hardware, failed probes and no consent use conservative prior defaults. Profile imports cannot mint microphone/network consent.
6. Appearance currently spans renderer localStorage and Electron overlay JSON (audit C6), not profile YAML. Keep that boundary explicit in export/import copy; do not promise these visual choices are in a settings-profile export. If unification is later approved, migrate each store deliberately with backup and physical-window confirmation.
7. Rollback restores original values/content; older builds need their preserved flat keys, not only new mode metadata. Future schema remains read-only under downgrade refusal. Migration logs contain key names/version/result codes, not audio/transcripts/secrets/raw profiles.

No backend implementation or retirement is authorized here.

## 6. Parity ledger impact and exact regeneration plan

Current checked-in ledger has **438 rows: 409 wired / 29 intentional_cut / 0 blocked** (`docs/release/PARITY_INVENTORY.md:68-75`, V document count, not a fresh gate run). Keep source stable IDs; audit UI-13 is not parity UI-13-NNN. Never edit ledger totals by hand or delete historical rows to manufacture completeness.

### First slice: five specific new intentional cuts

| Control/audit | Parity row and ledger source line | Required cut rationale |
|---|---|---|
| `sdSetDraftHistoryLimit` REV-07 | UI-07-043, `docs/release/PARITY_INVENTORY.md:310` | Visible/saved but no behavioral consumer; fixed 100-draft cap remains in status/copy; legacy value retained. |
| `sdSetWhisperChunkSize` STT-08 | UI-07-048, `docs/release/PARITY_INVENTORY.md:315` | Unused legacy chunk preference; actual streaming batch settings remain. |
| `sdSetStatusIndicator` UI-13 | UI-07-148, `docs/release/PARITY_INVENTORY.md:415` | Ignored overlay-enable checkbox removed; real overlay/capture state remains. |
| `sdSetNotificationOverlay` UI-14 | UI-07-149, `docs/release/PARITY_INVENTORY.md:416` | Ignored checkbox removed; real notifications remain. |
| `sdSetPreviewOverlay` UI-15 | UI-07-150, `docs/release/PARITY_INVENTORY.md:417` | Ignored checkbox removed; real review/preview actions remain. |

If those are the only status changes, arithmetic becomes **404 wired / 34 intentional_cut / 0 blocked**, total 438 [I]. A generator/gate run must establish the actual counts. Keep recording/status/review overlay rows UI-01-017, UI-14-008/009 and underlying window behavior wired. Cutting an enable checkbox is not cutting the feature it falsely claimed to control.

Other changes, conditional:
- Hidden ignored wake duration maps to **UI-07-112** (`docs/release/PARITY_INVENTORY.md:379`); after removal a sixth new cut would give 403/35/0 if nothing else changes [I]. No other wake rows are cut because a panel is currently gated.
- `instant_typing` control is **already** cut at UI-07-041 (`:308`); deleting stale renderer map entries adds zero new cut rows.
- Static synthetic preview **already** has an intentional cut at **UI-01-012** (`:134`); remove the remaining fixture markup/test initialization without claiming an extra new retirement. Composite **UI-15-019** (`:552`) still references independent Message Rescue surfaces: inspect all source handles and provide explicit replacement/cut reasoning for the removed fixture portion while preserving live draft and Scribe evidence. Never blanket-cut the functioning workflows. Final composite status/totals require regeneration rather than an invented forecast.
- Moved controls remain wired if reachable and tested. Profile/search/navigation UI-01-014, UI-07-001/002; recording/mode customization UI-07-017..025; bindings UI-07-028..035; review settings UI-07-036..040/042; persona/tuning UI-07-044..047/049; appearance UI-07-151..163; content UI-07-165..170 must be reanchored to their real destinations. Mode/automatic ownership does not automatically turn manual-override capabilities into cuts.
- Moving latency HUD/active jobs/recovery never drops UI-09-004 or UI-15-016/017, nor logs/support evidence. Existing interface IDs may stay while containers/routes change; update semantic evidence so the ledger no longer names old locations.

Proposed implementation procedure:
1. Add approved stable-ID rulings to `tools/parity_anchors.py:CUTS`, naming replacement or verified absence of capability (`:889-895`). Correct stale `HANDLE_ANCHORS/ROW_ANCHORS` and their production/test references. Do not keep dead elements or writer exports merely to satisfy a string-search gate.
2. Update `settingsWorkspace.js` inventory/disclosure maps, field arrays/types/IDs/errors/validators and tests for each removed ID. Retain an explicit inventory tombstone with `wired:false` and the cut reason where completeness tests require a historical key; don't call a dead writer “wired.” Utility maps and HTML/deep-link navigation get equivalent treatment for later slices. Do not suppress unrelated failures.
3. Update assertion locations bound by parity evidence tooling when tests move; add meaningful preservation/replacement assertions. The generator verifies test evidence before classification (`tools/parity_ledger_build.py:389-402`) and writes the ledger (`:543-550`). Comment-only or dead export matches are not evidence.
4. After reorg and implementation, use the existing project Python runtime to run these source-only tools; they write the ledger, so they are **not executed in this plan**:

```powershell
.\.venv\Scripts\python.exe tools\parity_ledger_build.py
.\.venv\Scripts\python.exe tools\parity_anchors.py
.\.venv\Scripts\python.exe -m pytest -q tests\test_parity_inventory.py tests\test_parity_evidence.py tests\test_parity_evidence_rules.py tests\test_parity_evidence_binding.py tests\test_parity_regen.py
```

5. Review regenerated diff, actual totals, strict row/anchor/evidence bindings, no blocked regressions and deterministic regeneration. Preserve all 438 source rows (`tests/test_parity_inventory.py:27-47`); use the generator's own actual CLI, which has no invented `--check`/dry-run argument. The release ledger must describe the production renderer closure, not the QA preview.

Renderer tests that actually change (verify lines after reorg):
- `app/tests/settingsWorkspace.test.mjs:63,674-696`: seven-section expectation and five required dead-control entries; add missing-control-safe collection and unknown/retired key round-trip assertions, retain inventory tombstone reasons.
- `settingsProfileOps.test.mjs`, `signalDeskSettingsSync.test.mjs`: full profile save/activate/import/export preserves hidden/custom values; new routes do not reset state or misapply inactive profile.
- `settingsAppearanceOverlay.test.mjs`, `uiControlContract.test.mjs:211,409-434`: moved controls retain styling/contrast/actual Dark-only choices; font/high-contrast stay accessible. Delete obsolete selector obligations only alongside the replacement; no new Light/System choice without CSS.
- `app/tests/navStructure.test.mjs:43-55`: currently requires Library/History/Runtime Diagnostics/Game Mode under Utilities and the rewrite binding; change to the new reachable routes/redirects with keyboard semantics, not remove destination assertions.
- `utilitiesWorkspace.test.mjs`, `utilitiesInputWake.test.mjs`, `utilitiesTextAdvanced.test.mjs`, `utilitiesDownload.test.mjs`, `utilitiesDiagnosticsPanels.test.mjs`, `utilitiesResilientLoading.test.mjs`: retained content/cancel/diagnostics flows, capability gates, nonblocking status, no acquisition on navigation, moved action bindings.
- `alphaCapabilities.test.mjs`, `applicationProfiles.test.mjs`, `gameSetupWizard.test.mjs`, `messageRescueDraft.test.mjs`, `messageRescuePanel.test.mjs`: gated wake/workflows stay inert; selection/pin semantics survive; coherent removal of chat-key prerequisites; live rescue survives synthetic fixture removal.
- `app/tests/parityGates.test.mjs:23-25,36-74` currently covers Talk/Library/Studio maps rather than Settings; do not pretend it is the Settings completeness gate. Update it only for moved live draft/Studio dependencies; Settings/Utilities own inventory tests need their own maintained coverage.
- Existing QA scenario files are `app/tests/qa/scenarios/signal-desk-sections.mjs`, `shell-status-prod.mjs`, `wave7-app-context.mjs`, `wave10-input.mjs`, `privacy.mjs`, `onboarding.mjs` and `onboarding-prod.mjs` (filenames verified). Run the appropriate production-target harness configuration, not merely preview mocks. Keep mounted production-page assertions for keyboard/search/dirty state and fresh/completed/migrated profiles. Source tests are not native microphone/controller qualification.

## 7. Five independently reviewable slices [P]

| Slice | Bounded change and release value | Dependencies and required tests/evidence |
|---|---|---|
| **1. Remove five ineffective controls** | HTML plus Settings collector/types/IDs/errors/validation/search/inventory entries; remove empty Notifications section/nav. Leave backend/schema/saved keys/API cap unchanged. Add five explicit parity cuts. Users lose fake knobs, not features. | Safe immediately after reorg when exact-key consumer scan is repeated. Cheap Node `settingsWorkspace`, `settingsProfileOps`, `signalDeskSettingsSync`, `uiControlContract`, `navStructure`; full-profile unknown/retired-key fixture assertions; relevant Python profile/settings and parity gates. Production page verifies absent IDs, overlays/review still work, Settings save/restart retains legacy values. No real model loads needed. |
| **2. Consolidate navigation and Advanced** | Profile/Appearance/Privacy plus one Advanced entry; move unchanged live bindings/review/audio/model/diagnostic controls into grouped component, keep contextual redirects and dirty-state/search. No auto-tuning, mode behavior or schema change. | Retained Advanced override/value/actions tests in all affected Settings/Utilities suites; nav/search/focus/aria-current, 1024px/narrow display checks, missing backend/errors, profile-switch and store round-trip; parity moved anchors stay wired; production-page reachability. Safe to ship before mode approval if old controls remain behaviorally identical. |
| **3. Contextual discovery and content** | Add capability-aware Things you can say, dictionary/macro editor links/post-edit suggestions; optional cleanup/persona explanations. Move live rescue only after Messages contract is approved. Remove synthetic fixture; optionally remove hidden ignored WAKE-05 in its own bounded patch. | No automatic capture/acquisition/command execution. Text tools/rescue/alpha capability and actual command policy tests; mode unavailable copy; Privacy stays usable; parity UI-01-012/UI-15-019 mixed-row review, UI-07-112 cut if included; real draft content/choice survives. Can ship general discovery while live rescue waits. |
| **4. Ratified mode replacement, then measured derivation** | After D1 resolver/migration and D2 consent safety exist, one Talk Mode selector owns approved fields; replace redundant routine mode knobs with effective summaries and Advanced customization. Adopt D3's qualified model/residency policies only when evidence exists; audio/token derivations are separate gated subchanges. | Owner/Claude ratification, schema/full-profile migration fixtures, missing/unknown/future mode, rollback/conflicting save, permission isolation, active-job switch rejection, PTT/stop/Gamer guard tests; D3 accuracy/latency proof; no mode/nav network or microphone activity. Keep old overrides until replacements pass. This slice may stop at modes without automatic tuning and still be valuable. |
| **5. Compatibility retirement after stabilization** | Only freshly verified dead profile defaults/coercions/writers retired; preserve legacy values/backups/import/export/API compatibility. Coherent clipboard-only wizard removes unsaved chat field plus dependent flow gates after game behavior is qualified. No blanket 73-key deletion. | Python `test_profile_migration.py`, `test_settings_redesign.py`, `test_server_settings_models.py`, `test_contacts_routes.py`, fixed history tests; renderer profile/game tests; old/new/corrupt/future/unknown profile fixtures; privacy inventory/wipe truth; deterministic parity and source scans; native controller/game verification for claims. Skip wizard subchange until qualification. |

Each slice has its own scoped diff and actual evidence; do not batch backend reorg, model benchmarking, modes, privacy redesign and five dead inputs into one PR. Slice 4 can be split further if automatic policy needs research; the approved part must not wait behind an unmeasured heuristic.

## 8. Review decisions and practical limits

| Decision needed before dependent implementation | Best current assumption |
|---|---|
| Are D1 per-profile mode metadata/resolver and D2 consent/microphone/acquisition contracts approved? | No; they remain proposals. Slice 1 and behavior-preserving slice 2 do not depend on approval. |
| Should “Advanced” mean one literal page or one reusable grouped destination? | One reusable destination/component with searchable disclosure and contextual deep links; no second Utilities Advanced control. |
| Can automatic theme/contrast, room-tone, token or residency policy replace explicit preferences today? | No. Preserve accessibility/manual overrides and existing defaults until the measured replacement passes. |
| Should ignored saved keys be deleted on UI removal? | No; retain them verbatim through full-profile save/import/export and backup. |
| Should workflow/wake/cloning become visible just because discoverability is poor? | No. Capability-aware unavailable explanation is discovery; enabling requires its own decision/qualification/consent. |
| Does “wired” in the ledger prove a key affects runtime? | No. The five controls have a persistence chain but no behavior consumer. Cut reasoning must distinguish these. |
| Can deleting the unsaved game chat field be a five-minute HTML tweak? | No. It participates in wizard state gating (`app/src/renderer/features/gameSetupWizard.js:154-182`); remove its step/prerequisites coherently after enforcing the safe delivery path. |

No user data, backend files, tests, ledger or runtime were changed or executed in this task. Inventory and consumer claims were checked through source enumeration/search; a future implementation needs mounted production-page and applicable native behavior evidence. Main checkout and all other worktrees remain read-only.

**Next move:** owner/Claude review this plan; land slice 1 after the reorg with the five-cut parity diff and saved-profile preservation evidence.
