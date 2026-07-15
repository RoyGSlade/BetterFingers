# Redaction Audit — log-surface breadth (Tier-3 M4, Workstream A)

Systematic inventory of every logging/console call site that *could* carry
user-dictated content (raw_text, final_text, prompts, transcripts, clipboard
text, persona examples, TTS phrases), classified SAFE / REDACT / REMOVE, with
the action taken (or planned) for each REDACT verdict.

Legend:
- **SAFE** — no user content in the message (config values, counts, enum
  states, library exception objects that don't echo input).
- **REDACT** — user content can appear in the message; wrap with
  `log_redaction.redact_user_text()` (existing) or the new `redact_exc()`
  helper (Workstream A2).
- **REMOVE** — n/a this pass (nothing found warranting outright removal).

## Already redacted (baseline, verified correct — no action)

| Site | Verdict |
|---|---|
| `intent_engine.py:30` | SAFE — already wraps with `redact_user_text` |
| `server.py:1251` (Speaking text aloud) | SAFE — already wraps with `redact_user_text` |
| `server.py:3727` (Draft TTS Request) | SAFE — already wraps with `redact_user_text` |
| `server.py:4050` (TTS Request) | SAFE — already wraps with `redact_user_text` |

## A. Python — REDACT sites (need `log_redaction` wrapping)

| File:line | Content | Action |
|---|---|---|
| `tts_engine.py:1296` | `logging.debug("Cached audio for: %r", text)` logs raw TTS phrase (draft/persona text read aloud) | Wrap: `redact_user_text(text)` |
| `project_generator.py:14` | `logging.info(f"Generating project '{plan.get('title')}' ...")` logs raw LLM-planned/user-derived title | Wrap: `redact_user_text(plan.get('title'))` |
| `llm_engine.py:1556` (`_mark_error`) | `logging.error(text)` — `text` can embed `"Server stderr: {stderr[:1200]}"` (llama-server stderr, which can echo prompts at higher verbosity) | Redact the stderr slice before it enters `message` (see A3 below); never log raw stderr content |
| `server.py:1808` (`process_recording_result` outer except) | `logging.error(f"Recording processing failed: {exc}")` — broad catch over the whole dictation pipeline; some exception paths could embed transcript/prompt text in their message | Wrap: `redact_exc(exc)` (new helper) |
| `server.py:1865` (`on_recording_complete._worker`) | `logging.exception("Recording worker failed")` — same pipeline, outer safety net | Downgrade to `logging.error(f"Recording worker failed: {redact_exc(exc)}")` so we control what's emitted instead of a raw traceback dump |
| `server.py:3694` (`rewrite_draft` except) | `logging.exception("Draft rewrite failed")` — rewrite operates on `final_text` via the LLM; exception message could echo it | Same treatment: `logging.error(f"Draft rewrite failed: {redact_exc(exc)}")` |
| `server.py:3855` (`/voice-commands/execute` except) | `logging.exception("Voice command execution failed")` — dispatches to copy/read_back/rewrite on `final_text` | Same treatment: `redact_exc(exc)` |

**`redact_exc(exc)` helper (new, in `log_redaction.py`):** returns
`f"{type(exc).__name__}: {redact_user_text(str(exc))}"` — preserves the
exception type (useful for debugging *what kind* of failure) while redacting
whatever message text it carries. Length-only, like `redact_user_text`.

## B. llama-server stderr policy (`llm_engine.py` `_stderr_log`)

Current state: `_read_server_stderr()` reads up to 4000 bytes from the
`TemporaryFile` capturing llama-server's stderr; `_mark_error()` embeds up to
1200 chars of it into `message`, which is then (a) passed to
`logging.error(text)` at line 1556, **and** (b) stored in
`LLMEngine._last_error_details["stderr"]`, which `server.py:2147` serializes
verbatim into the `/doctor` diagnostics response — a queryable export surface,
not just a log line.

**Decision:** keep the raw stderr file on disk only (already the case — it's
a `TemporaryFile`, never written to a log path). Never let raw stderr content
reach `logging.error` or the `/doctor` response unredacted:
- `_mark_error`: redact the `stderr` slice before folding it into `message`
  (`redact_user_text(stderr)` — count only, not content).
- `_last_error_details["stderr"]`: same — store the redacted form, not raw.
- If a developer needs the real content for debugging, `BETTERFINGERS_LOG_RAW_TEXT=1`
  already makes `redact_user_text` a no-op, so the existing opt-in covers this
  with no new escape hatch needed.

## C. MCP tool-call argument logging (`mcp_client.py`)

Current state: `mcp_client.py` only *lists* tools (`list_tools`/`list_servers`/`status`);
there is no tool-*invocation* code path yet (no `call_tool`/`invoke_tool`
anywhere in `server.py` or `llm_engine.py`). The two `logging.warning` sites
that reference user-controlled data (`server '{name}' skipped`, `could not
parse {path}`) only ever log server *names* and file *paths* from
`mcp_servers.json` (operator-authored config), not dictation content.

**Verdict: SAFE, no action needed today.** Noting for the record so a future
session adding tool invocation (passing dictated text as a tool argument)
knows to route argument logging through `redact_user_text` at that time —
this file is not adding that surface now, just documenting the gap is closed
by absence.

## D. Electron (`app/src/main/*.js`, `app/src/renderer/main.js`, `preload.js`, `api/*.js`, `lib/*.js`, `overlay.html`, `review-overlay.html`)

Full sweep of all `console.log|warn|error|info|debug(` call sites (24 in
main-process files + 6 in renderer `main.js`; zero in preload/api/lib/overlay
HTML). None currently print `rawText`/`finalText`/`draft`/`transcript`/
persona example content — every site logs either an `Error` object from a
failed `fetch`/IPC call, a URL/path being blocked, or a hotkey/accelerator
string. Verified by direct grep for those identifiers on `console.*` lines
(zero hits) and manual read of every match.

**Verdict: SAFE today.** Still building the `redact.js` guardrail (A3) and
the lint-style regression test (A4) as planned — the audit found no *current*
leak, but nothing today stops the next feature from adding
`console.log('draft:', finalText)`, and the whole point of this workstream is
a standing gate, not a one-time cleanup. The lint test turns this audit into
a CI-enforced invariant instead of a snapshot that goes stale.

## Summary

| Surface | Verdict | Sites needing wrap |
|---|---|---|
| Electron console.* | SAFE (defensive guardrail still built) | 0 |
| Python tracebacks/exceptions | REDACT | 4 (`server.py` x3, `llm_engine.py` `_mark_error`) |
| llama-server stderr | REDACT | 2 (log line + `/doctor` export) |
| MCP tool-call args | SAFE (no invocation path exists yet) | 0 |
| Diagnostics export (`/doctor`) | REDACT | 1 (`last_error_details.stderr`) |
| Direct raw-text logs (non-exception) | REDACT | 2 (`tts_engine.py:1296`, `project_generator.py:14`) |

Total new wraps: **8 sites** across 4 files (`server.py`, `llm_engine.py`,
`tts_engine.py`, `project_generator.py`), plus one new helper (`redact_exc`)
in `log_redaction.py`.

All landed in Phase 1 (A2), verified in `tests/test_log_redaction.py`
(`RedactExcTests`, `RedactStderrLinesTests`).

## E. Post-Phase-0 addendum — the A4 lint gate found 2 more (Phase 1)

`tests/test_log_redaction.py::LoggingLeakGateTests` (the regression gate A4
asked for) scans every `logging.*()` call for a curated set of user-content-
shaped substrings, unwrapped by a `redact_*` helper. Running it against the
codebase surfaced 12 matches — 2 were real gaps this Phase 0 pass missed
(neither `transcriber.py` nor the raw-audio `/transcribe` route in `server.py`
were in the original file list above), 10 were false positives from the
gate's substring-level matching, verified SAFE by reading and allowlisted
with a reason in the test file itself (mirroring this doc's own SAFE
methodology):

| Site | Verdict | Action |
|---|---|---|
| `transcriber.py:592` (`transcribe_with_confidence` except) | REDACT — broad catch over segment formatting/hallucination-check, which operates directly on the decoded transcript | Wrapped: `redact_exc(exc)` |
| `server.py:4088` (raw-file `/transcribe`-style route except) | REDACT — broad catch around the ASR call, same class of risk as the dictation-pipeline sites above | Wrapped: `redact_exc(e)` |
| `clipboard_capture.py` (8 sites: lines 50/65/91/149/160/211/247/305) | SAFE | pyperclip/Win32 clipboard API exceptions are library/OS failures (access denied, format unavailable, oversized buffer) — these APIs never embed the clipboard's own text content in their exception message. Verified by reading each site; allowlisted in the gate test. |
| `server.py:1013` | SAFE | `logging.exception("Clipboard copy failed")` — no interpolation at all, a static string. |
| `injector.py:262` | SAFE | Exception is from `get_clipboard_text()` failing to READ the clipboard, not from echoing what it would have returned. |

This is the intended shape of a lint-style regression gate: coarse and a bit
noisy (10/12 matches here were false positives), but it caught 2 real,
previously-unaudited gaps that a one-time manual sweep missed — which is
exactly why A4 asked for a standing check instead of leaving this document as
a snapshot.
