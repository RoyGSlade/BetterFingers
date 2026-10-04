# BetterFingers modes: decision-gated specification

Status: proposed for owner/Claude review; BF-D1; 2026-10-04. This document changes no runtime behavior. Source baseline: `f6aaa6f937a3a2c808ee35eadf324a998770eec3` in `codex/d1-modes`. Paths and line numbers below refer to that worktree unless explicitly prefixed `main:`. Recheck references after the backend reorganization.

## Recommendation and scope

Modes are named settings bundles for the existing dictation/review loop. Choose Work by default, offer one mode selector, preserve existing custom settings, and ship the first slice without background listening or automatic model downloads. Gamer must pass the delivery and input gates below before it can be advertised as protection. Ideas is long-form capture, not the parked brainstorm assistant.

The five mode names are the product target, not evidence that five new workflows function today. The smallest valuable implementation is Work / Ideas / Messages plus the migration and single selector; Gamer and Hands-free have explicit availability gates. No new assistant loop, execution permission, contact inference, or memory subsystem is implied by a mode.

Evidence notation: **V** = verified by source inspection in this task; **I** = inferred consequence, not observed at runtime; **P** = proposed behavior/value, requiring implementation and qualification; **U** = unknown. No latency, resource, accuracy, microphone, game, or accessibility measurement was performed. All preset timings are P, not measured results. The main-checkout audits are read-only inputs, not acceptance evidence.

## 1. Mode identity, persistence, and resolution

| UI label | `use_mode` value | User-facing purpose |
|---|---|---|
| Work | `work` | Dictate and review everyday writing. |
| Gamer | `gamer` | Hold to talk; review and copy without game keystrokes. |
| Ideas | `ideas` | Capture a long thought without silence ending it. |
| Messages | `messages` | Hold to talk for short messages; review before placement. |
| Hands-free | `hands_free` | Manually start, pause to stop, and optionally hear the draft. |

**P storage contract.** `use_mode` belongs in each named settings profile YAML, alongside `recording_mode`, not in each executable-matching application profile. New profiles default to `work`. The already-selected settings profile determines the active session mode; changing executable does not silently change the selector. An optional application override may only strengthen safety or provide bindings; it cannot weaken Gamer. Do not add a second global mode preference or make mode selection rewrite `app_profiles.json`.

Keep enum validation explicit. A missing legacy key means `work` as a display grouping, with legacy behavior retained until adoption. An invalid/unknown future value must be preserved on disk, shown as unavailable/custom, and resolved conservatively without starting capture, enabling injection, loading models, or fetching anything. Future-schema files remain read-only, consistent with the current downgrade-refusal contract (`utils.py:1030-1047`, V).

**P companion metadata**, inside the settings profile: `mode_defaults_version: 1`, `mode_adopted: bool`, and `mode_overrides` keyed by mode ID. Existing flat keys remain the persisted explicit user configuration; the effective-settings resolver applies mode defaults and safety clamps without destructively flattening presets into saved data. Preserve keys beyond this schema. The version marks preset semantics, not the settings-file schema; do not conflate them.

Resolution order, from least to most authoritative:

1. Versioned preset defaults for an adopted mode; otherwise the legacy configuration unchanged.
2. Explicit per-mode user overrides. Legacy explicit values are initially preserved as that profile's custom configuration, not guessed from whether a value happens to equal an old default.
3. Qualified runtime/hardware limits and acquisition/consent state. A preferred setting cannot make a missing model available or authorize a download.
4. Safety invariants: active Gamer or a fresh matched legacy `minimal` app profile imposes copy-only and no submission. An unknown target/context imposes copy-only. Enforced values remain visible as such.

Display `Work · Custom` for a legacy/unadopted profile. Choosing a named mode is the explicit adoption action; save the existing configuration first and never erase it. Switching back restores that mode's overrides. “Reset this mode” is an advanced explicit action, not a side effect of choosing a different mode.

**P switch transaction.** Reject a switch during recording, STT, cleanup, TTS, or placement with “Finish or stop the current action first”; keep Emergency Stop available. Validate capability and effective settings, save the complete profile with revision protection, apply backend/main settings, then confirm the selector. If persistence or application fails, restore the previous mode/settings and show the failure. Model choices may report pending readiness separately; never claim the new model is ready merely because a preference was saved. Bind profile switches to the same resolver/apply path. Current renderer save refreshes hotkeys (`app/src/renderer/api/backend.js:141-145`, V), and reconfiguration clears PTT state (`app/src/main/hotkeys.js:324-327`, V), so mid-record mode changes would be unsafe (I).

Overlay preferences currently live separately in Electron `overlay-appearance.json` (`app/src/main/windows.js:46-83,144-146`, V). The mode resolver must own effective `size`/`alwaysOn` without overwriting the user's saved appearance. Provide one effective overlay state to Electron; if application is partial, roll back instead of silently retaining half a preset. Colors, position, opacity, contrast, and accessible scale stay user preferences; do not invent a Gamer opacity guarantee.

## 2. All 23 MODE rows

Every MODE-classified row in `main:docs/arc/SETTINGS_INDEX.md:40-250` appears below. That audit has 22 preset rows because APP-03 and APP-09 share one line (`main:docs/arc/SETTINGS_INDEX.md:420`); this table separates them into **23**. Row IDs match that inventory. All values are P.

**D** = default, user-overridable in Advanced/customization; **E** = enforced while the applicable safety mode/policy is active; **C** = conditional on consent/readiness/qualification and remains unavailable otherwise. A D value never authorizes acquisition or activation. `auto GPU` means verified CUDA inference and hardware headroom, not a name/spec-sheet guess; the fresh-profile bootstrap is CPU (`use_gpu=false`), and BF-D3 owns promotion eligibility. `auto STT` is a BF-D3 resolver request; bootstrap remains an already-local, verified `base.en` CPU/int8, or a missing-model state. BF-D3 owns model selection, not this table.

| Row / setting | Work | Gamer | Ideas | Messages | Hands-free | Rule and rationale |
|---|---|---|---|---|---|---|
| AUD-06 `auto_stop_after_silence_enabled` | false D | false E | false D | false D | true D | Only manual-start Hands-free should stop on a pause; PTT release and long thinking pauses stay deliberate. |
| AUD-07 `auto_stop_silence_ms` | 900 D, inactive | 900 D, inactive | 900 D, inactive | 900 D, inactive | 1200 D | Hands-free gets a proposed longer pause allowance; 1200 ms must be tested with actual users, not called measured. |
| AUD-11 `max_recording_seconds` | 120 D | 30 E ceiling | 1800 D ceiling | 60 D | 300 D | Bound a lost release event while allowing Ideas' existing maximum; every mode remains within the 5–1800 s watchdog range. |
| HK-02 `recording_mode` | toggle D | ptt E | toggle D | ptt D/C | toggle D | Gamer requires a working release-driven stop; Messages may offer clearly disclosed toggle if PTT is unavailable. |
| HK-03 `force_stop_key` | empty D | validated chord E/C | empty D | empty D | validated chord E/C | Gamer and Hands-free need an independent reachable stop; explicit existing working bindings win. |
| HK-05 `selection_rewrite_hotkey` | ctrl+alt+r D/C | empty E | ctrl+alt+r D/C | ctrl+alt+r D/C | empty D | Disable selection capture during games; elsewhere expose only on platforms whose selection/review path is qualified. |
| STT-01 `model_size` | auto STT: accuracy D/C | base.en CPU D/C, measured smaller alternative only | auto STT: accuracy D/C | auto STT: latency D/C | auto STT: latency D/C | Prefer measured fit within BF-D3 limits; Gamer gets no unqualified tiny.en downgrade or download from the mode tap. |
| STT-02 `use_gpu` | auto GPU D/C | false E | auto GPU D/C | auto GPU D/C | auto GPU D/C | Gamer leaves GPU/VRAM to the game; other modes require actual inference readiness and headroom. |
| STT-04 `streaming_transcription_enabled` | true D | false E | true D | true D | true D | Avoid repeated STT work during gameplay; incremental capture can help longer utterances elsewhere. |
| STT-10 `voice_commands_enabled` | true D | false E | true D | true D | true D | These are formatting commands; game speech must not accidentally become formatting instructions. |
| STT-13 `app_commands_enabled` | false D | false E until stop-only scope C | false D | false D | false D until reviewed scoped actions C | Current flag also covers “send it”; never call it emergency-stop-only. Keyboard/UI stop remains independent. |
| LLM-01 `llm_enabled` | false D; local opt-in C | false E | false D; local opt-in C | false D; local opt-in C | false D; local opt-in C | First-run mode choice cannot download a multi-GB LLM or silently change text semantics. Work/Ideas can offer cleanup later. |
| LLM-02 `current_preset` | True Janitor D | preserve, inactive E | True Janitor D | True Janitor D | True Janitor D | Use an existing known preset; it is inert with LLM off, and no “casual” persona is invented or user persona erased. |
| LLM-14 `use_delivery_signals` | false D | false E | false D; qualified opt-in C | false D | false D | Ideas is a candidate, not permission to ship an unmeasured punctuation change. |
| REV-01 `send_mode` | review_first D | review_first E | review_first D | review_first D | review_first D | Review-first everywhere by default; Gamer cannot opt out. Non-Gamer legacy opt-ins are retained with explicit custom indication. |
| REV-02 `auto_submit` | false D | false E | false D | false D | false D | No mode enables Enter/submission; non-Gamer advanced opt-in needs its existing warning and acknowledgement. |
| TTS-01 `review_tts_enabled` | true D/C, on demand | false E | false D/C | false D/C | true D/C, on demand | Read-back stays available for Work/Hands-free after local TTS readiness; mode selection must not speak or download. |
| TTS-10 `model_keep_tts_loaded` | false D | false E | false D | false D | true D/C if TTS ready and memory fits | Hands-free benefits from resident read-back only after opt-in/readiness; enforce hardware limits and idle release. |
| WAKE-01 `wake_word_enabled` | false E | false E | false E | false E | false E in current alpha; future true C after explicit arm | Hidden/unqualified wake cannot be enabled by choosing a friendly label; launch does not silently re-arm. |
| APP-03 app-profile `performance_preset` | balanced D* | minimal E* | quality D* | low_latency D* | balanced D* | These labels are desired effective intents, not app-store rewrites; only minimal has a demonstrated consumer today. |
| APP-09 gaming policy constants | inactive unless matched game C | active E | inactive unless matched game C | inactive unless matched game C | inactive unless matched game C | Mode-level safety removes the foreground-poll dependency for Gamer; a matched game's minimal policy can strengthen every other mode. |
| UI-06 overlay `size` | medium D | small D | medium D | small D | large D | Prefer unobtrusive game/message state and readable Hands-free state; accessible user sizing remains allowed. |
| UI-07 overlay `alwaysOn` | false D | false D | true D | false D | true E during capture/armed state | Long capture needs visible state; Hands-free cannot hide active microphone/armed state via an appearance override. |

`*` APP-03 is a separate store today, so these values describe the proposed effective mode intent, not a new top-level `performance_preset` YAML field. Preserve all stored executable-profile labels and bindings. Do not falsely claim `balanced`, `quality`, or `low_latency` tunes performance before BF-D3/residency consumers exist (`backend/services/app_context.py:472-477`, V; audit's reader census is `main:docs/arc/SETTINGS_INDEX.md:206`).

Stop chord proposal: try `ctrl+shift+f12`, then `ctrl+alt+shift+f12`, checking local bindings and actual registration; if neither works, show “Set a stop key” and leave gated modes unavailable. This detects local conflicts, not every game's reserved keys (U). Keep the on-screen stop even when keyboard hooks fail. Emergency Stop must bypass voice-command, mode, profile, and pending-action gates.

Compared with the audit's proposed table (`main:docs/arc/SETTINGS_INDEX.md:354-375`), Work/Ideas cleanup and Ideas delivery signals remain off until explicit qualified opt-in. Hands-free wake stays off, and Gamer app commands stay off until stop-only scoping exists. This is deliberate: a mode is not consent to download, listen in the background, or send text.

## 3. Gamer guarantees and the existing policy

### Guarantees to implement before enabling the mode

- **Never auto-send or auto-submit.** Require exact reviewed draft acceptance; no speech, persona, app override, raw API action, automation, controller, or primary-action shortcut can bypass it. Keep confidence/review protection. F9 accept-and-place is a separate proposal, not implemented here.
- **Copy-only globally while Gamer is selected**, including when the game cannot be detected, the renderer is closed, or a non-game app is foreground. Show “Copy” and the actual clipboard outcome. Copy does not mean the text reached game chat. Clipboard failure retains the draft and offers retry; it never falls through to injection.
- **Copy-only into games in every mode** when fresh detection identifies a gaming/minimal profile. Get foreground identity at delivery in the backend/platform path, independent of renderer timers; unknown, stale, failing, or changed identity prohibits synthetic input. A user-pinned non-game profile cannot authorize injection into a detected game. Unsupported detection stays copy-only. Never promise protection for undetected/unclassified games; selecting Gamer supplies the unconditional guarantee.
- **Working PTT and independent stop.** Verify a running hook/controller release path, watchdog, lost-release recovery, and stop registration. If unavailable, block Gamer activation and explain; do not silently change it to toggle. Whether hooks/overlays are accepted by a particular anti-cheat remains U and requires game-specific qualification.
- **Minimum work during play.** CPU STT, streaming off, LLM off, TTS off, no automatic downloads/benchmarks/upgrades, and no unnecessary resident GPU model. Release previous mode's idle GPU/LLM/TTS allocations under runtime leases before reporting Gamer active; never unload an in-flight job. CPU utilization and game frame impact need measurement: “minimal” is an intent, not a quantified budget. Record the measured ceiling before a performance claim.
- **No focus theft.** Present state without activation; remain usable when the overlay cannot appear over exclusive fullscreen. Show a qualified tray/earcon alternative. Existing `showInactive` paths are source evidence, not a measured fullscreen guarantee (`main:docs/arc/SETTINGS_INDEX.md:380`).

### Conflict resolution and release gates

| Audit conflict | Current source evidence | Required resolution / ownership |
|---|---|---|
| C3: app fields promise policy but do not enforce it | `backend/services/app_context.py:472-477` copies writing/injection/performance slots to snapshots; `main:docs/arc/SETTINGS_INDEX.md:483` inventories inert readers. V for copying; reader census from audit. | Resolve one effective backend policy. App bindings still compose, but an `injection_policy=type/paste/auto` never weakens copy-only. Treat dormant writing/announce slots as saved metadata, not promises. Future implementation owner required. |
| C4: wizard does not activate minimal policy | `app/src/renderer/features/gameSetupWizard.js:209-220` omits performance; sanitizer chooses balanced (`backend/stores/app_profiles.py:252`); trigger checks minimal (`backend/domain/gaming_policy.py:66-70`). V. | BF-F1 adds minimal in renderer-built profiles. This repairs the trigger only; it does not implement mode-level guarantees, fresh detection, or action completeness. |
| C5: renderer polling supplies stale context | `app/src/renderer/features/applicationProfiles.js:187,413-414` uses a 4 s timer; `backend/services/app_context.py:281-284` returns cached state; `server.py:1257-1259` uses it at placement. V; background throttling effect I/U. | Backend delivery-time foreground check and fail-closed context handling. No dependency on dashboard visibility. Freshness must bind the target identity for the attempted operation, not merely pass a four-second TTL. |
| Additional: missing synthetic action | `backend/domain/gaming_policy.py:126` omits `open_chat_then_send`; `server.py:1248` allows it and `server.py:1451` derives it from legacy auto_send. V; bypass consequence I, not exercised. | Use an allowlist: only explicit copy/review is permitted under restricted policy, all other/unknown actions normalize to copy-only before any chat-open or submit key. Test every action, not just paste/type aliases. |
| Additional: error opens delivery | `server.py:1261-1262` catches policy errors and continues. V. | A policy/context failure must return copy-only or a non-delivery error with draft preserved; never continue synthetic input. |

The existing limits remain ceilings if future manual cleanup/read-back is qualified: 50 completion tokens; at most 2 TTS sentences, each at most 90 characters; no TTS queue (`backend/domain/gaming_policy.py:29-46`, V). Fresh matched games apply these clamps even outside Gamer. Gamer's initial LLM/TTS-off settings are stricter. Constants alone do not supply consumer enforcement.

## 4. Migration with zero user-data loss

Current settings load merges defaults then stored data (`utils.py:1050-1058`, V); save writes a complete payload and backup (`utils.py:1234-1258`, V). The executable profile API **replaces**, not merges (`backend/stores/app_profiles.py:503-521`, V). Consequently, “save a small mode-shaped dictionary” is forbidden.

Migration is a versioned, idempotent transformation with an explicit before/after fixture set:

1. Read the raw stored settings before defaults obscure missing keys. Preserve a recoverable original, its unknown keys, custom personas/references, hotkeys, audio device/fingerprint, consent record, history, recordings, dictionaries, macros, executable mappings, pins, and controller bindings. Do not collect transcript/audio in migration logs.
2. For files without mode metadata, add `use_mode=work`, `mode_adopted=false`, and `mode_defaults_version=1`; retain every existing value. Do not guess Gamer from `recording_mode=ptt` or from a pinned executable profile. Existing `minimal` app policy continues independently.
3. Record explicit legacy MODE keys into the custom snapshot/override metadata. A non-Gamer legacy auto_send/auto_submit opt-in is preserved as custom behavior; no other mode inherits that opt-in automatically. Once Gamer is selected, safety clamps apply without erasing the saved preference. Safety wins over unsafe legacy metadata.
4. On explicit adoption, snapshot legacy/custom settings, use that mode's versioned defaults for uncustomized behavior, and preserve selected microphone, primary hotkey, user content and non-MODE preferences. Existing stop/hotkey conflicts receive validation, never blind replacement. An inactive LLM preset remains saved.
5. Save atomically with a revision check; reject conflicting edits rather than overwrite a newly edited profile. Do not traverse/reserialize app profiles, personas or controller stores. Older/newer/corrupt schema handling must retain the existing quarantine/downgrade discipline and recoverable originals.
6. On rollback to pre-mode runtime, original flat configuration still describes the pre-adoption behavior; keep backups/export. Unknown mode metadata must not activate capabilities in older consumers. Guaranteeing the new effective-mode semantics on an older build is out of scope; communicate this before downgrade.

Acceptance distinguishes content preservation from intended runtime changes: Gamer overrides unsafe delivery at runtime, but the original user's settings and text are recoverable. No task here authorizes deleting obsolete keys/files as part of “cleanup.”

## 5. First-run and one later control

BF-D2 owns the consent/microphone screens. Its mode screen consumes exactly the IDs above, defaults to Work for fresh profiles, and offers one tap/Enter to finish. A mode click changes a preset only; it cannot invoke microphone capture, start the wake listener, acquire a model, enable cleanup, speak, send a draft, or grant permissions. Any disabled choice explains its unmet capability; Work always provides a way forward. Do not add a third screen for Gamer/controller setup or Hands-free wake.

Hands-free's first available variant is **manual start, silence stop** with visible capture state and optional local read-back. Copy: “Start recording yourself; pauses stop it. Background listening is off.” True wake activation is a separate point-of-use permission, physical false-accept/reject and stop qualification, visible armed state, and explicit re-arm. `wakeWordSettings` is currently false (`app/src/renderer/config/alphaCapabilities.js:9`, V); this spec does not flip it. If independent stop and real-path silence-stop qualification are absent, keep Hands-free visible but unavailable with a reason.

Later, put a single **Mode** selector in Talk's persistent header, exposing the current mode/custom status. It is keyboard accessible, names disabled reasons, and shares the first-run resolver. No competing Gamer toggle in Settings. Keep application/controller configuration in Advanced, reached through contextual “Set up a controller” after Gamer, without blocking ordinary dictation setup. No auto-open tour.

After resolver/invariants and migration ship, remove these individual controls from the main Settings surfaces: recording mode, auto-stop enable/timing, voice/app commands, send mode/auto-submit, cleanup enable, active persona, delivery signals, TTS residency/read-back, wake enable, overlay size/always-on, rewrite/stop bindings, and performance-policy labels. Retain real overrides in a discoverable “Customize this mode” Advanced surface, with effective values and enforced explanations; persona authoring stays in Studio, Models shows acquisition/readiness, and Diagnostics shows actual capabilities. Do not remove old controls before their replacement works. Audio device, privacy/consent, drafts/history, and accessibility remain reachable.

The finish hint reflects actual bindings/capabilities: `Record: <binding> · Review draft · Accept, then <primary action> · Stop: <binding/button>`. Current F9 is placement after acceptance; do not promise it performs acceptance until that separate change is qualified (`main:docs/arc/SETUP_AUDIT.md`, headline 4 / §5.4 C10).

## 6. Verification to require at implementation

No implementation tests were run for this documentation-only task. These are acceptance requirements, not passing results.

| Layer | Required cases / observable pass condition |
|---|---|
| Unit: modes/resolver | Exhaust all 5 enums, invalid/missing/future values, 23 rows, default vs override vs clamp, preserved legacy custom state, no cross-mode opt-in inheritance, app minimal strengthening and no weakening. Effective resolution is deterministic and side-effect-free. |
| Unit: migration | Missing mode, every old value at defaults/custom extremes, unknown keys, custom preset/hotkeys/device, app pins/bindings, future schema, corrupt YAML, repeated migration, interrupted write, conflicting save. Original content recoverable; profiles/personas/history/controller bytes not rewritten by mode adoption. |
| Unit: delivery | Table-driven all accepted/unknown actions including `open_chat_then_send`, all mode/app combinations, stale/failing/missing context, clipboard failure and target changes. Assert zero injector/chat-open/Enter calls on every restricted case, with exact reviewed draft and confidence gate preserved. |
| Main/backend integration | Switch/profile activation applies one effective config, hooks and overlay included; mid-capture switch refused; apply/write failure rolls back; models not unloaded mid-job; unavailable PTT blocks Gamer; fallback never labeled PTT. Startup restores effective safety without needing a renderer. |
| Renderer | First-run and later control use identical IDs/default/availability; keyboard/focus/screen-reader coverage; truthful custom/disabled/partial states; no removed control left bound or writable; Hands-free never arms from select; no mode selection API starts a model download, listener, capture, or delivery. |
| Consent/network | Launch unconsented, choose each mode, switch repeatedly, decline, and restart. Instrument actual outbound attempts across Electron/backend/child processes: zero before durable network authorization; local IPC excluded. BF-D2 owns the broader consent matrix. |
| Real Windows/input | PTT down/up, lost release, stop chord registration, focus change, hidden/closed dashboard, controller disconnect, failed hooks, app-context failure. Capture stops and drafts survive; log the actual runtime capability, not package presence. |
| Game/Hands-free qualification | Named game/window modes and target identity races, overlay focus/fullscreen, CPU/RAM/VRAM/frame-time delta against no-BF baseline. Real mic silence/pause/stop tests and accessible stop/read-back. No compatible-with-all-games or numerical efficiency claim without these measurements. |

## 7. NOW / NEXT / LATER and decisions

**NOW:** owner/Claude review this spec against BF-D2/BF-D3; independently review BF-F1's renderer trigger repair. Keep the source guarantee gaps attached to the implementation queue. Five spec files do not equal five shipped features.

**NEXT, smallest shippable slice:** mode schema/resolver plus non-destructive migration; single selector; Work/Ideas/Messages capture defaults only; no LLM/wake/model acquisition implied; exact review protection and real hotkey application preserved. Messages falls back to a disclosed toggle when PTT is unsupported. Leave legacy/custom behavior intact. Ship only after unit/renderer/apply checks above pass and BF-D2's network gate is independently verified. Existing controls remain until their effective replacements pass.

Gamer becomes selectable after central delivery safety, renderer-independent target handling, resource release, PTT, and stop qualification. Hands-free becomes selectable after manual-start silence-stop and accessible independent stop qualification. Wake, persona-based Ideas assistance, automatic cleanup, and broad UI removal are LATER; each has its own gate. This sequencing respects the primary-loop stabilization rule rather than treating mode names as five new top-level assistants (`main:docs/arc/SETUP_AUDIT.md:§5.4 C1`).

Open decisions with best assumptions:

| Decision | Best assumption / recommendation | Gate |
|---|---|---|
| Does mode belong globally or per settings profile? | Per settings profile; its active selection is session-wide. App profiles only strengthen safety/provide bindings. | Owner/Claude ratification before schema work. |
| Can Work/Ideas enable cleanup automatically? | No. Keep false initially; explicit optional local-model setup after first successful dictation. | Consent/acquisition/readiness plus measured quality/latency. |
| Is Gamer CPU base.en adequate under play load? | Use existing qualified base.en until a measured alternative wins; no tiny.en marketing claim. | BF-D3 workload/accuracy evidence; measured resource budget. |
| Should Hands-free mean wake listening at launch? | No. Manual-start silence-stop now; explicit arm only after future wake qualification. | Owner naming approval; physical audio and accessibility gates. |
| Can app commands be emergency-stop-only today? | No evidence of that scope. Keep false in Gamer; independent stop is required. | Scoped dispatch plus bypass-safety tests before enabling voice app commands. |
| How much legacy customization follows a new mode? | Snapshot everything; preserve non-MODE preferences; do not carry unsafe send/permission opt-ins across modes. | Migration fixtures and review of the adoption copy. |
| Can BF-F1 alone make Gamer safe? | No. It fixes the minimal trigger, not stale/failing context or omitted actions. | Backend/main follow-up accepted and verified before guarantee claims. |
| Does a five-second mode/mic flow mean ready in five seconds? | No. It is a decision-effort target; local inference readiness and downloads have separate measured status. | BF-D2/BF-D3 alignment; no invented wall-clock metric. |

Next move: review and ratify the mode/storage/migration contracts, then implement the one-control resolver slice before adding capability claims.
