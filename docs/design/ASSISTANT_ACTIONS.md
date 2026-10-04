# Assistant actions: bounded plans, exact permission, observed results

BF-D4 — proposed interfaces only — 2026-10-04. Baseline `codex/d4-assistant-actions` at `33b7cf44dca75dfae3e427ddcfa0a6dd7cb1fc0f`. No executor, command parser, capability flag, adapter, permission store, or model has been changed by this task.

**Recommendation:** qualify three deterministic tasks over named targets before allowing model planning. Retain the existing registry/closed-vocabulary boundary, add exact operation permissions and target-aware postconditions, and refuse anything the adapter cannot observe. A successful request is not a completed task.

Labels used throughout: **V** = verified by source reading (or explicitly named primary documentation); **I** = inferred consequence, not observed live; **P** = proposed contract/value/acceptance requirement; **U** = unverified capability or open choice. No performance, Windows UI Automation, extension, consumer-app, microphone, or action qualification was measured here. Numeric limits below are P budgets, not measured results.

## 1. Existing boundaries and gaps

| Finding | Source evidence and qualification |
|---|---|
| Fixed restricted actions already exist | V: ten actions and their parameters are enumerated in `backend/domain/actions.py:60-103`. Shell/generated-code refusals are explicit (`backend/domain/actions.py:113-120,127-203`). Preserve this boundary; do not bolt a terminal onto the assistant. |
| Saving is not approving; edits and changed previews are gated | V: step changes revoke approval (`backend/services/workflow_store.py:302-314`); `can_run` checks enabled, approved and exact current preview (`backend/services/workflow_store.py:382-405`); run route revalidates first (`backend/api/routes/actions.py:234-261`). This does not itself bind a text revision or UI field identity (I). |
| Privileged executor accepts workflow ID and re-fetches the plan | V: `app/src/main/workflowExecutor.js:177-206,237-254`. Keep the “main fetches trusted plan by ID” shape; renderer-supplied steps must never become executable. |
| Existing completion signals do not prove readiness | V: `wait_for_process` is a timer returning ok (`app/src/main/workflowExecutor.js:132-138`). Spawn returns ok and ignores asynchronous error (`app/src/main/applicationLauncher.js:212-227`); Windows focus returns unavailable (`app/src/main/applicationLauncher.js:256-259`). Treat acceptance as dispatch only, not window/field completion. |
| Failed steps currently do not stop subsequent steps | V: executor iterates all steps and collects status even after failure (`app/src/main/workflowExecutor.js:209-220`). Continuing a dependent placement after a failed launch/focus could reach the wrong target (I). |
| Commands use substring/fuzzy matching | V: clear context includes review-overlay visibility (`backend/commands/voice_commands.py:66-71`); contained phrase then fuzzy matching follows (`backend/commands/voice_commands.py:101-124`). In that context “do not send it” matches send, and “wait cancel that thought about lunch” matches cancel, by the matching logic (I; supplied brief labels these previously verified bugs; no runtime reproduction here). |
| Additional classification is not the normal capture router | V: `classify_utterance` exists (`backend/commands/voice_commands.py:265-342`); normal capture applies dictation commands (`server.py:2329`) and the explicit app-command endpoint calls `parse_command` (`server.py:5557`). No normal-capture classifier call appeared in the scoped source search (V search, not runtime tracing). Wiring the existing classifier alone retains its unsafe parser delegation (I). |
| Current confirmation is not an operation capability | V: request has `draft_id`, context and `confirm: bool` (`server.py:5536-5540`); true bypasses the confirmation response (`server.py:5566-5573`) and send uses the draft ID (`server.py:5592-5593`). A changed draft/target is not bound by those fields (I). |
| Voice stop is incorrectly behind the command toggle | V: `server.py:5554-5557` returns disabled before recognizing emergency stop. Independent `/runtime/emergency-stop` exists (`server.py:5623-5625`). New voice stop must bypass this toggle; do not advertise the current endpoint as unconditional. |
| Foreground process detection is not verified field context | V: Windows process detection (`backend/services/app_context.py:138-151`), cached current snapshot (`backend/services/app_context.py:281-284`). No UI Automation element/window/value evidence is supplied by that interface. |
| General workflows remain hidden | V: `workflowSettings: false` and inert selectors (`app/src/renderer/config/alphaCapabilities.js:10,23,29-40`). A spec is not permission to unhide them. |

Baseline distinction: isolated `33b7cf4` still omits `open_chat_then_send` in `backend/domain/gaming_policy.py:126`. The parent reported the fix at main `3d1af28`; read-only inspection of main at `e1ae890d0c54993176bf56c8630ba35cca2168e6` confirms the broader copy-only policy is present (`main:backend/domain/gaming_policy.py:116-133`, V). Do not report that omission as an unfixed current-main issue or assume the isolated executor contains the fix. Rebase/integration must preserve that policy and separately qualify target/field safety.

## 2. Command admission and grammar

**P** Default capture is dictation. A review overlay, active draft, wake event, displayed webpage, or model inference is not command authority. Admission requires either a whole-utterance explicit prefix (`BetterFingers, …`) from the capture/typed-request channel, or an explicitly enabled, visibly armed, short-lived command session owned by the user. A command session expires after 30 s idle, one resolved request, focus intervention, or emergency stop. It never creates background listening permission. BF-D2 owns capture/network consent; BF-D1 owns mode/capability availability.

Minimal grammar, versioned and deterministic:

```text
request       := ["hey "] "BetterFingers," command
                | command inside a user-armed command session
command       := "open app " registered_name
                | "switch to app " registered_name
                | "select " named_tab " in " bound_target
                | "place reviewed draft in " verified_field " in " bound_target
                | "show action status" | "cancel pending action"
safety_stop   := standalone unquoted "emergency stop" [terminal punctuation]
literal_text  := explicit literal dictation, or text outside admitted command context
```

This is the initial supported grammar, not an open natural-language interpretation surface. Registry names resolve to exactly one previously confirmed ID, otherwise the request is unresolved. Field/control names resolve against a scoped, approved app/site recipe to one unique observable element; no first-match guess. Normalize case, whitespace and terminal punctuation outside quoted spans only. Do not remove negation, quotations, or token boundaries to make a trigger fit. Prefixes inside quotes/reported speech do not count. ASR output lacking reliable quotation boundaries is uncertain: show the interpretation and require explicit user resolution before a write.

Reject or retain inert any unquoted request-level negation (`do not`, `don't`, `never`, `not`, `stop … from`, `avoid …`), conditional/hypothetical (`if`, `unless`, `maybe`, `could`), reported command, extra trailing clause, ambiguous name, or multiple chained commands. These rules operate on the command span, not on literal draft content; a reviewed draft can contain the sentence “do not send it.” No substring/fuzzy execution. Near matches can be offered as visible suggestions requiring selection, never executed. Unknown commands retain their transcript and explanation, with no shell workaround.

**P stop exception.** The dedicated standalone safety utterance bypasses prefix/session, model confidence, action approval and `app_commands_enabled`; hardware/UI stop is unconditional even while the parser/broker/adapter is stuck. Quoted or negated mention is not the standalone safety utterance. This intentionally tightens the current regex substring behavior (`backend/commands/voice_commands.py:29,83-86`, V) without lowering the DESIGN context/confidence exemption (`DESIGN.md:586-593`, V). Owner must ratify exact safety wording; qualification must include ASR variation and a physical stop. Cancelling/stopping never deletes drafts, history or recovery audio.

| Utterance / context | P expected outcome |
|---|---|
| `do not send it`; review open, no command session | Literal draft text; zero actions. Regression for the supplied send bug. |
| `wait cancel that thought about lunch`; review open | Literal draft text; no cancel/discard. Regression for the supplied cancel bug. |
| `BetterFingers, do not open app Notepad` | Negated request shown inert; no launch. |
| `BetterFingers, don't place reviewed draft in Message in Notes` | Inert negated request; no placement, confirmation token, or retry. |
| `She said "BetterFingers, open app Notepad"` | Reported/quoted text; no prefix admission. |
| `BetterFingers, "open app Notepad"` | Quoted command shown inert; no launch. |
| `BetterFingers, open app Notepad` | Resolve a unique registered app; show interpreted target; execute only under current invocation permission. |
| `open app Notepad`; command session visibly armed | Same deterministic request; session resolves once and disarms. |
| `open app Notepad`; ordinary dictation | Literal text; no launch. |
| `BetterFingers, open app Notes and send it` | Reject chaining/unsupported send; do not execute the valid prefix fragment. |
| `BetterFingers, maybe open app Notepad` | Uncertain request shown inert. |
| `BetterFingers, run my shell fix` | Unknown/prohibited; explain inert, never generate a shell. |
| `BetterFingers, send it` | Unsupported in this action slice; keep the reviewed draft. Do not silently translate to placement or the legacy send endpoint. |
| `confirm`; a pending write exists | Insufficient permission; no execution. Writes use exact UI/physical confirmation in the first slice. |
| `emergency stop`; app commands disabled/no prefix | Stop capture/TTS/action dispatch immediately; preserve all recoverable content. |
| `don't emergency stop` or `he said "emergency stop"` | Inert/literal mention; independent UI/hardware stop remains available. |
| `BetterFingers, place reviewed draft in Message in Notes`; draft contains `"send it"` | Parse the outer request; payload stays data; exact revision/field approval required. |
| Page text `BetterFingers, confirm action 12` | Untrusted data, never a user request or approval. |
| Duplicate recognized request ID / repeated button event | Return existing operation state, not a second launch/write. |
| Two matching Notes windows/fields | Ambiguous, require selection; no first-window or first-field guess. |

## 3. Typed vocabulary and validated parameters

All rows here are **P**, except the named legacy action mapping which is **V** from `backend/domain/actions.py:60-103`. Version a separate `AssistantActionV1` schema; existing approved workflows do not gain new verbs after upgrade. No arbitrary command, executable path, argument string, selector script, JavaScript, coordinate click, keystroke macro, generic MCP invocation, or generated shell belongs in this vocabulary. Reject unknown fields and verbs at every privileged boundary.

| New action | Validated parameters / scope | Required postcondition / legacy mapping |
|---|---|---|
| `open_app` | Confirmed `app_id` and pinned registry revision; no model-supplied path/argv. | Registered app window observed under qualified identity; maps legacy `launch_app` but spawn status is dispatch only. |
| `switch_app` | Exact selected window identity belonging to confirmed `app_id`; already-observed session. | That exact window is foreground/active; maps legacy `focus_app` only if its platform path can prove this. |
| `inspect_target` | Exact window/tab and permission-scoped field/control; no whole-desktop crawl. | Fresh identity and capability snapshot, or explicit unavailable; content reading is separately disclosed/scoped. |
| `select_named_tab` | Recipe-defined role/label/parent identity and unique element reference; known navigation-only control. | Selected tab and expected target generation observed; no submit/destructive/control with unknown effects. |
| `focus_field` | Exact qualified editable non-password, non-payment, non-credential field; expected current revision. | Focused field identity and unchanged target/value revision observed. |
| `place_reviewed_text` | Exact draft ID + immutable revision + keyed content digest + exact target/field + empty-field precondition; replace-empty only in v1. | Read-back equals approved text in same field and target; no submit, Enter, or chat-open. Unsupported read/write pattern refuses. |
| `show_result` | Fixed summary/status codes and operation ID; no model-generated claim of success. | Local trusted result panel shows observed outcome; legacy `show_notification` is supplementary only. |
| `cancel_pending` / `emergency_stop` | Current operation ID for cancel; global stop independent of operation. | Dispatcher quiescent, capture/TTS stopped, pending permissions revoked; already-completed effects remain reported. |

An approved resource ID may later support `open_resource`; opening an arbitrary URL/file/custom scheme is not in the first slice. Existing `open_uri/open_folder` workflows keep their own validator and exact-preview contract; never reinterpret them as permission to navigate/read/write a browser page. Credentials, auth, installation, purchases, sending, publishing, delete/move/close/kill and filesystem writes are excluded. A future `submit_reviewed` would need a separate schema, exact destination/content confirmation and receipt evidence; no current task qualifies it.

P limits: at most 6 ordered steps, no loops or recursion, one operation active globally, 16 KiB approved placement content, 30 s operation deadline including observation/retry. Longer text falls back to the ordinary reviewed dictation path; never truncate silently. These caps must be ratified and measured for the supported task matrix.

## 4. Permission: exact operation, text revision and target

**P** Trusted local capture/typed input creates a user-intent record. Only the main-owned permission broker can create an execution capability from it. Screen/page text, tool metadata, model output, renderer-supplied booleans and ambient wake context cannot mint user intent or permission. A request proposes an action; it is not blanket authority to run an arbitrary plan.

| Operation | P confirmation policy |
|---|---|
| Stop/cancel a pending operation, display its status | No confirmation; available outside command session and while adapter unavailable. |
| Deterministic open/switch of one explicitly named registered app | No second prompt if the trusted admitted request uniquely names that app and launch method, capability is qualified, and interpreted action is visibly acknowledged. This permission applies to that one invocation; unknown/ambiguous apps remain inert. |
| Inspect minimal identity/capability | Covered only within the user's active target-scoped invocation. Reading actual field/page content needs disclosed scope and is minimized. No background screenshot/desktop harvesting. |
| Model-proposed plan / extra steps beyond the exact request | Ordered preview and explicit approval before any effect, even if steps individually look safe. |
| Place text, or navigation to a target not explicitly requested | Exact target and operation preview plus deliberate confirmation. Selecting an empty draft field is not permission to write into it. |
| Submit/send/destructive/spend/credential actions | Denied in v1. Repeating “yes” does not unlock a missing capability. |

For a write, the trusted preview shows the exact text, draft revision, destination app/window or origin/tab/frame, field label and operation (`place`, never `send`). Broker capability binds canonical action/parameters, plan/step order and versions, content revision and keyed digest, exact target identity/generation, empty-field value revision, registry/recipe/adapter revisions, policy/consent revision, deadline, originating request ID, and one-use nonce. Use opaque tokens; neither renderer nor model receives reusable execution secrets. Revalidate at adapter entry immediately before the effect. Replay/changed parameters/expired capability is refused, not silently reapproved.

Initial write confirmation is a dedicated trusted local review UI or registered main-process confirmation hotkey bound to the pending operation; generic `confirm=True`, webpage buttons, model “approved” text, and standalone voice “yes” cannot authorize it. Future voice confirmations require separate anti-replay/ambient-audio qualification and exact operation challenges; not included now. Saving an approved workflow is reusable authorization for its immutable **template** only, never perpetual approval of changing draft content or live targets.

User keyboard/mouse action, unexpected focus/navigation, tab/frame/document reload, field value edit, changed draft revision, recipe/registry change, microphone privacy revocation, model proposal change, connection loss or Emergency Stop pauses dispatch and invalidates affected pending capabilities. Intentional broker UI focus transfer is tagged and expected; other focus transfer is intervention. Resume observes a fresh target and obtains fresh permission; an old token never revives. Only the adapter's own declared selection/focus transition is allowed without pause, and its new observed identity must match the approved step. No concurrent hidden queue.

## 5. Execution, postconditions, failure and retries

**P state machine:** `proposed → validated → awaiting_permission → authorized → observing → executing → verifying → completed`. Branches: `paused`, `refused`, `unavailable`, `failed`, `effect_unknown`, `cancelled`, `timed_out`. Dispatch acceptance is an intermediate event; UI says “Opened” only after window evidence, “Placed” only after equal field read-back, and “Sent” never in v1.

Every step first checks adapter qualification, policy, target freshness/identity, intervention generation, capability token and precondition; it then performs its one effect and verifies the specified postcondition. A failed/unavailable/unknown step stops all dependent steps. The operation is completed only when every required step has verified evidence. Stop/revoke checks remain live between awaits and during polling; a blocking adapter needs an isolated worker with a watchdog so it cannot block the physical stop.

Observation cannot eliminate all time-of-check/time-of-use races (I). Use target-addressed native/extension methods rather than foreground keystrokes. Where the adapter cannot bind or verify the same target immediately around an effect, return unavailable. A target/value change during verification pauses with the observed outcome and keeps the original draft; no automatic repair or overwrite of user edits.

| Step | P meaningful postcondition | Retry rule |
|---|---|---|
| Open app | Qualified registry identity matches a live responsive window; existing-window case does not spawn a duplicate. | Observe once more within deadline. Relaunch only if proven no process/window/effect began; asynchronous uncertainty is `effect_unknown`, no second launch. |
| Switch app / focus field | Exact approved window/field foreground and focused with matching identity/generation. | One retry after fresh observation and no intervention; invalidate permission if target changed. |
| Select navigation-only tab | Same bound target; named tab selected and expected content region available. | One retry only if fresh evidence proves no selection/effect and recipe declares idempotence. |
| Place text | Same empty-field precondition before effect; same field has exactly approved text after effect; no submission. | Zero automatic effect retries. If response/ack lost, read-only reconciliation once; already-equal means completed, unequal/unknown means stop. |
| Cancel / Emergency Stop | No future effects dispatched; capture/playback quiescent; permission revoked. | Idempotent stop can be reissued once; never roll back by deleting text or files. |
| Future send/destructive | Outside v1; missing capability. | Never automatic retry, including after timeout or lost receipt. |

At most **one** retry per eligible safe step and per-operation shared retry budget one; retries require the same original authorized operation and no changed permission-sensitive state. Re-observation is not permission to create a fresh plan. Never “try another app/field” or keyboard fallback when a method is unsupported. Timer expiry is timeout, not process readiness. A timeout after any possible effect returns `effect_unknown` with manual reconciliation and completed steps shown.

P result journal stores operation/step IDs, schema/adapter version, status, sanitized error code, monotonic timings, retry count, postcondition evidence class, and side-effect certainty. No raw draft/page contents, screenshots, paths, URLs with private queries, secrets, password values, or reusable token. Keyed content digests and opaque target IDs are session-bound by default and discarded with the session; a digest is not automatically anonymous. Recovery journals persist enough operation state to prohibit replay after restart, never permission tokens. Restart revokes pending authority; interrupted writes reconcile read-only under fresh consent or wait for the user. Retention/export needs the existing privacy/deletion lifecycle.

## 6. Adapter and broker interfaces (P)

The following TypeScript is a contract sketch, not implementation or an assertion that these adapters exist. Opaque IDs are created/resolved by trusted adapters; strings are not selectors, handles, capabilities or permissions merely because a model supplies them. Runtime schemas must validate every property and reject extras. Snapshot evidence is transient and available only to the scoped operation.

```ts
type Revision = string;
type TargetRef =
  | { kind: 'windows'; appId: string; registryRevision: Revision;
      processInstance: string; windowInstance: string; fieldRef?: string;
      recipeRevision: Revision; generation: Revision }
  | { kind: 'browser'; browserSession: string; extensionSession: string;
      origin: string; tabId: number; frameId: number; documentId: string;
      fieldRef?: string; recipeRevision: Revision; generation: Revision };
type FieldRef = TargetRef & { fieldRef: string };
type Action =
  | { kind: 'open_app'; appId: string; registryRevision: Revision }
  | { kind: 'switch_app' | 'inspect_target'; target: TargetRef }
  | { kind: 'focus_field'; target: FieldRef }
  | { kind: 'select_named_tab'; target: TargetRef; controlRef: string }
  | { kind: 'place_reviewed_text'; target: FieldRef; draftId: string;
      contentRevision: Revision; contentDigest: string;
      expectedFieldRevision: Revision; writeMode: 'replace_empty' }
  | { kind: 'show_result' | 'cancel_pending'; operationId: string }
  | { kind: 'emergency_stop' };
interface Plan {
  id: string; revision: Revision; schema: 'assistant_actions_v1';
  requestId: string; policyRevision: Revision; steps: readonly Action[];
  source: 'deterministic' | 'model_proposal';
}
interface Snapshot {
  target: TargetRef; observedMonotonicMs: number; interventionRevision: Revision;
  unique: boolean; foreground: boolean; focusedFieldRef?: string;
  editable: boolean; protected: boolean; expectedPatternAvailable: boolean;
  fieldRevision?: Revision; valueDigest?: string; empty?: boolean;
}
interface OperationContext {
  operationId: string; requestId: string; deadlineMonotonicMs: number;
  permissionRef: string; signal: AbortSignal;
}
interface StepResult {
  status: 'dispatched' | 'verified' | 'refused' | 'unavailable' | 'paused'
        | 'failed' | 'timed_out' | 'effect_unknown' | 'cancelled';
  errorCode?: string; observed?: Snapshot;
  effect: 'none' | 'occurred' | 'unknown';
  postcondition: 'met' | 'not_met' | 'unobservable'; retryCount: 0 | 1;
}
interface Capabilities {
  adapterId: string; adapterRevision: Revision;
  qualification: 'unqualified' | 'fixture_only' | 'qualified_target';
  qualifiedRecipeRevisions: readonly Revision[];
  actions: readonly Action['kind'][]; reasonCodes: readonly string[];
}
interface TargetAdapter {
  capabilities(): Promise<Capabilities>;
  observe(target: TargetRef, ctx: OperationContext): Promise<Snapshot>;
  execute(action: Action, ctx: OperationContext): Promise<StepResult>;
  verify(action: Action, ctx: OperationContext): Promise<StepResult>;
  subscribeIntervention(onChange: (revision: Revision) => void): () => void;
  stop(operationId: string): Promise<StepResult>;
}
interface WindowsUiaAdapter extends TargetAdapter {
  bindWindow(appId: string, selectionRef: string,
    ctx: OperationContext): Promise<TargetRef>;
}
interface BrowserAdapter extends TargetAdapter {
  bindSelectedTab(selectionRef: string,
    ctx: OperationContext): Promise<TargetRef>;
}
interface LauncherAdapter {
  capabilities(): Promise<Capabilities>;
  launchConfirmed(appId: string, registryRevision: Revision,
    ctx: OperationContext): Promise<StepResult>; // dispatch is not readiness
}
interface PermissionBroker {
  validate(planId: string): Promise<{ valid: boolean; reasonCodes: string[] }>;
  authorizeFromTrustedUi(planId: string, previewRevision: Revision,
    userEventRef: string): Promise<{ permissionRef: string }>;
  checkBeforeEffect(action: Action, snapshot: Snapshot,
    ctx: OperationContext): Promise<{ allowed: boolean; reasonCode?: string }>;
  revoke(operationId: string, reasonCode: string): void;
}
```

Placement content is retrieved from the trusted immutable draft revision through the broker, never from renderer/model-supplied replacement text. Check its keyed digest against the approved capability before passing it over authenticated adapter IPC. The sketch omits transport and serialization details deliberately; implementation must define authenticated main/backend/adapter endpoints, draft snapshot lifetime, nonce persistence/revocation, integer/string bounds, strict runtime schemas, and test those boundaries before exposing a route. TypeScript types alone enforce none of these properties at runtime.

**P Windows UI Automation adapter.** Resolve confirmed executable/process instance, window handle generation, app/package/version, session/integrity and unique qualified control. Report actual supported focus/read/write patterns, editable/password/protected flags, intervention/focus events, read-back equality and unavailable causes. Process name alone is insufficient. Microsoft documents that text controls may expose different patterns and that `ValuePattern` supports setting a compatible field; support must be detected per control, not guessed from app name (V primary documentation). [Microsoft UI Automation text insertion](https://learn.microsoft.com/en-us/dotnet/framework/ui-automation/add-content-to-a-text-box-using-ui-automation).

Refuse password/payment/credential fields, secure desktop, unsupported/elevated/protected targets, multiple matches, stale element references and inaccessible read-back. No elevation/UIAccess bypass, DLL injection, global keystroke fallback, blind coordinates or broad desktop scraping. Microsoft's security model restricts higher-integrity access; this design deliberately does not request a bypass (V primary documentation; P refusal policy). [Microsoft UI Automation security](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-securityoverview). If a benign editor exposes no qualified writable/readable pattern, task qualification is blocked; “it works when we paste blindly” does not satisfy the contract.

**P browser adapter.** Extension plus native messaging, installed/pinned and separately user-enabled; default no site access. Select one tab via extension gesture, or grant one explicit optional host scope; no `<all_urls>` default. Chrome's `activeTab` permission grants temporary access after a browser gesture and cannot be assumed from an app microphone command (V primary documentation). [Chrome activeTab](https://developer.chrome.com/docs/extensions/develop/concepts/activeTab).

The native host allowlists the exact extension ID; the extension declares `nativeMessaging`, validates content-script sender origin/tab/frame/document and schema in its service worker, and never treats page messages as executable requests. Those Chrome permission/origin boundaries are documented; the broker nonce/capability check is an additional P boundary. [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging). Host/extension disconnect, tab navigation, origin/frame changes, permission revocation and document replacement invalidate the target; no cross-origin iframe fallback. Report selected tab/document identity, unique accessible control/field, recipe revision, DOM generation, editable/protected/value revision, target-scoped read-back and any unobservable state. Page labels and attributes remain hostile data; only a qualified recipe can declare a control navigation-only or a field non-submitting. Programmatic field events can trigger site behavior (I), so named site qualification must prove the recipe has no send/purchase/save side effect beyond the disclosed draft write; no universal editable-field guarantee.

**P existing launcher wrapper.** Preserve `(confirmed command, argv[])` with `shell:false` (`app/src/main/applicationLauncher.js:212-218`, V), main-owned confirmed registry, and qualification reporting. Listen for actual dispatch errors and report `dispatched` separately. UIA/browser observation supplies readiness and focus, not the launcher timer. The wrapper must not accept model paths, scripts or raw argv. Existing Windows `qualified:false` stays unavailable until measured on the declared target; it must not be discarded when mapping status codes.

## 7. Deterministic intent and model-proposed plans

**P deterministic first:** exact grammar resolves registered app IDs, user-selected unique window/tab/control, one reviewed revision, stop/cancel and status. Every supported first-three task can be a finite predeclared recipe; no LLM is needed to decide permission, identity, selector, success, retry or safe action semantics.

Later, an already-local explicitly enabled LLM may propose a maximum six-step plan in this vocabulary. The planner receives only the request and permission-scoped minimized observations, marked as untrusted data; no ambient desktop dump, credentials, hidden browser contents, authorization tokens or unrestricted tool registry. Output is validated against schema, capability, recipe, exact target/content and policy before preview; rejected actions fail the entire proposal. Unknown tools/verbs never become generated shell instructions. A planner cannot approve its own plan, replan after approval, weaken a gate, choose a new destination or claim completed steps. If an observation invalidates a plan, stop and offer a fresh proposal requiring new review. No loops, autonomous follow-ups, self-installs, downloads, or general MCP tool execution. F33 remains a separately approved future boundary (`docs/FEATURE_DESIGN.md:487-495`, V).

## 8. Dependencies and first three qualifying tasks

Everything in this section is **P** acceptance work, not passing evidence. Leave the general workflow/assistant surface hidden until these dependencies are satisfied.

1. **Dictation gate first.** Exact build/hardware/model/target evidence must satisfy `DESIGN.md:372-392`: real mic/models, 100 consecutive dictations, 50 restarts, declared long recordings, reconnect/sleep/resume/model crash, audio preservation and clipboard/app matrix. The source describes `needs-hardware`, not a current green result (V). Speed thresholds/measurement method must be declared by the dictation qualification task before its run; D4 invents no latency pass number. A mocked HTTP harness or a written spec is insufficient.
2. **Admission and independent stop.** Replace the risky command admission semantics and boolean confirmations, qualify negation/quotation/literal/unknown cases, and make physical/UI/recognized dedicated safety stop work even when app commands are disabled or an adapter blocks.
3. **Permission broker and trusted journal.** Exact immutable revisions, one-use capabilities, replay handling, operation serialization, interruption/restart reconciliation, privacy/redaction and permission revocation must be verified adversarially.
4. **Target adapters, versioned recipes, and launcher.** Windows focus/readiness and field read/write qualification, extension/native-host origin/permission validation, and actual postcondition evidence are required. No models, auth, installs or downloads are performed by this spec task.
5. **Policy contracts.** BF-D1 Gamer policy and BF-D2 consent/capture/network gates are dominant; BF-D3 optional local planner readiness cannot authorize actions. UI displays exact preview/actual result and stays operable without mouse. Gamer prohibits synthetic placement even when an otherwise-authorized assistant recipe requests it.

| Qualifying task | Small valuable behavior / required evidence | Acceptance cases and dependencies |
|---|---|---|
| Q1 — Open or switch the user's confirmed Notepad | Deterministic `open_app`/`switch_app`; registered pinned executable/package revision; observe one exact responsive foreground window. No text write. | Real named Notepad/Windows build plus fixture faults: closed/open/two windows, registry change, delayed/failed spawn, unavailable focus, dashboard hidden, intervening user, repeated event, stop, timeout. No duplicate launch; ambiguous/unavailable is visible; every completed claim has window/focus evidence. Requires qualified launcher+UIA; existing unavailable Windows focus does not pass. |
| Q2 — Place a reviewed draft into an empty native editor field | User explicitly selects one qualified Notepad editor field, reviews exact draft, and confirms placement; read-back equals exact Unicode/newlines; remains an unsent draft. | Qualify that exact Notepad version's observable writable pattern; otherwise blocked, not blind paste. Test changed draft/field/window/process, nonempty field, password/elevated field, duplicate approval, ack loss, user edit after write, restart, clipboard untouched, Gamer denial and Emergency Stop. Zero overwrite/submission/wrong-target input; unknown outcome never retries. Requires Q1, exact broker and field adapter. |
| Q3 — Switch to an approved browser note tab, select Draft, and place reviewed text | Unique user-selected tab/frame/document; recipe-qualified navigation-only Draft tab and initially empty editor; explicit exact field/content approval and read-back; no send. First qualify an owned local fixture, then a specifically named consumer notes target before claiming consumer support. | Extension gesture/site scope denied/revoked, malicious page messages/labels, cross-origin frame, navigation/document replacement, duplicate fields, field edits, SPA reload, lost native port, model/shell proposals, site-side send behavior, stale permission and stop. Fixture success stays `fixture_only`. Remote-site qualification needs explicit network/privacy policy amendment and host consent; no auth/model/download work here. Requires Q2 broker properties and qualified extension/browser recipe. |

For each qualifying task, P run **30 consecutive operations** on its exact build/target, plus each adversarial scenario; record pass/refused/unavailable/effect_unknown independently. Any unintended write, bypass, lost content, hidden effect, or fabricated completion fails qualification. Repeat after adapter/recipe/permission changes. The count is a proposed test budget; no operations were executed in this task. Unit/property tests cover grammar, schema, permission equality/replay and state transitions; renderer tests cover immutable previews, disabled reasons, actual status, keyboard/cancel and no executable authority from page content. Live target checks remain mandatory.

## 9. Load-bearing conflicts and open decisions

| Decision/conflict | P recommendation / best assumption | Evidence or release gate |
|---|---|---|
| General assistant is new scope while dictation is unqualified | Design now; do not implement/unhide/ship until dictation gate and explicit owner authorization. | `DESIGN.md:61-65` stabilization rule; `docs/FEATURE_DESIGN.md:453-459` restricted workflows; F33 remains LATER. |
| Current ten-verb workflow scope vs new external-field writes | Use a separate versioned schema and new exact permissions; existing approval cannot expand implicitly. | `backend/domain/actions.py:55-82`; owner must explicitly accept the extension before implementation. |
| “Only model downloads touch network” vs remote browser app behavior | First browser fixture is local. Explicitly amend/disclose remote host navigation/draft sync before any remote consumer task; do not claim external apps are offline. | `DESIGN.md:80`; BF-D2 network authorization is necessary but not authority for every host/write. |
| Grammar vs emergency-stop substring matching | Dedicated affirmative standalone stop bypasses context/confidence/command toggle; quoted/negated mention stays literal. Physical stop always works. | `backend/commands/voice_commands.py:29,83-86` current behavior; `DESIGN.md:586-593` invariant; owner ratifies wording and ASR qualification. |
| Is explicit app-open command enough permission? | Yes for one uniquely resolved registered app invocation with visible acknowledgement; additional steps/model plan/write require exact preview approval. | Broker request provenance and malicious-content/admission tests. |
| Is native Notepad field support available? | U. Require measured qualified writable/readable target recipe; do not substitute keystrokes if unsupported. | Exact Windows/Notepad version and real UIA evidence. |
| How to bind trusted confirmation and target atomically? | Main-owned broker and target-addressed adapters; if identity/effect cannot be bounded and observed, unavailable. Do not promise elimination of OS/web races. | IPC origin/auth/replay review and native/extension failure tests before implementation. |
| Are arbitrary control labels safe? | No. Unique labels identify candidates; trusted versioned recipes authorize semantic navigation/write scope. | Malicious labels/page messages and side-effect qualification. |
| Do messages/sends enter the first slice? | No. Reviewed placement remains separate from submit/send; future schema needs exact destination and receipt semantics with no retry. | Owner scope decision and additional qualification. |
| Are 6 steps/16 KiB/30 s/30 runs enough? | Small bounded v1 defaults; ratify and adjust from actual qualification, not a demo. | Measured target/user workload and reliability evidence. |

Next move: review these interfaces and permission boundaries against the dictation gate; implement no assistant execution until that gate and the separate scope decision are satisfied.
