---
name: collab
description: Multi-session collaboration protocol for this repo. Use at the START of any coding task, and whenever another Codex session may be active (the SessionStart context will say so). Covers registering presence, claiming files before editing, messaging other sessions, and handling urgent interrupts.
---

# Collab Workspace Protocol

Multiple Codex sessions may work in this repo at once. A shared workspace
(`.Codex/collab/`, via the `collab` MCP server) keeps them from stepping on each
other and lets them talk. The user watches the conversation live at
**http://localhost:4517** (auto-starts when a second session registers).

## Session lifecycle — follow this order

1. **Register first.** Before any edits, call `collab_register` with a short
   kebab-case name describing your task (e.g. `voice-commands`, `overlay-fix`)
   and a one-line focus. Re-register if your focus changes.
2. **Check the room.** Call `collab_status` and `collab_inbox`. If another
   session's focus overlaps yours, message them (`collab_post`) before starting.
3. **Claim before you edit.** Call `collab_claim` with the repo-relative paths
   you're about to modify and a reason. Claim narrowly — the files you'll
   actually touch, not whole directories. Codex's PreToolUse hook hard-blocks
   edits to files claimed by another session. Codex's hook can only emit a
   `WARNING — NOT ENFORCED`; a Codex session must treat that warning or a
   `collab_claim` conflict as a hard stop itself. Claiming is not optional.
4. **Work.** During long tasks, check `collab_inbox` between major steps.
   Urgent messages are also injected automatically by hooks — treat an
   `[collab-workspace INTERRUPT]` as higher priority than your current step:
   read it, respond via `collab_post`, then decide whether to continue or adjust.
   Hook delivery consumes only the exact own/parent-room batch it injects;
   messages appended during injection remain pending for the next hook/inbox.
5. **Release when done.** Call `collab_release` (no args releases all your
   claims) as soon as you finish editing a file — don't hold claims across
   unrelated work. Post a `handoff` or `info` message summarizing what changed.

## Message kinds

- `urgent` — interrupts other sessions at their next tool call. Use for:
  you're about to change a shared interface they depend on, you found a bug in
  code they own, a merge/rebase hazard, or a high-value collaboration
  opportunity (e.g. "I'm already refactoring backend.js — don't duplicate").
  Don't cry wolf; everything else is `info`.
- `wake` — interrupts a sleeping/finishing Codex session and blocks its Stop
  hook so it must act. Use for a real keepalive or review request, not routine
  status.
- `question` — you need input from a specific session (`to: "their-name"`).
- `bug` — a scoped finding for the worker's supervisor to triage.
- `handoff` — you finished something they should pick up or rebase onto.
- `info` — FYI broadcast (what you changed, what you're starting).

## Spawning workers (director sessions)

A session acting as director can launch sessions itself — no human
terminal-juggling needed. The full director → supervisor → worker protocol
lives in the **`hierarchy` skill**; the wake-call semantics in the **`wake`
skill**. Summary:

- `collab_spawn(name, task, role=...)` starts a headless Codex session
  (`Codex -p`) from the **repo root** (required — a session started elsewhere
  silently loses claim enforcement). `role='supervisor'` → **Opus 5** with its
  **own clean generation-specific collab room** and report-up wiring (give it
  a phase objective; reusing its display name never reuses old room state);
  `role='worker'` → **Sonnet 5** in your room (give it one task); no role →
  legacy flat worker (Opus 5, your room). All are auto-briefed to register,
  claim before editing, and end with a `handoff`.
- Spawning is truthful and fail-closed. Before it records state or posts a
  spawn notice, the selected CLI must pass `auth status --json` with
  `loggedIn: true`, and the child must survive a short health-check. Missing
  auth and immediate auth/model/settings/argument failures return an MCP error
  (with a bounded redacted log tail when useful), not `Spawned`. Fix a
  `loggedIn: false` blocker with an interactive `Codex auth login` outside
  this headless workflow; do not try to log in from a worker.
- The default `permission_mode='taskSafe'` is Codex `manual` plus an explicit
  `--allowedTools` list: normal repo reads/edits, collab lifecycle calls, and
  narrowly matched test/build inspection commands. A caller may supply a
  task-specific `allowed_tools` replacement. `bypassPermissions` is never a
  default; selecting it adds the CLI dangerous-skip opt-in and requires
  explicit user approval for that spawn.
- **Hard caps, repo-wide across every room: 2 Opus + 4 Sonnet running at
  once** (the user-approved budget; env `COLLAB_MAX_OPUS` /
  `COLLAB_MAX_SONNET`). An over-budget spawn errors until a slot frees.
- Write the `task` brief self-contained: file paths, constraints (including
  no Git mutation and apply-patch/editor-only source writes), and explicit
  done-criteria. Workers can't ask the user.
- Wait with `collab_wait` (returns on new messages or a child exiting) instead
  of polling. Supervisors reach the director's room with `collab_report_up` /
  `collab_check_up`. Workers report bugs found along the way as `kind='bug'`.
- `collab_workers` shows this room's spawns; `collab_fleet` shows the whole
  tree with cap usage. Fleet visibility is not kill authority:
  `collab_stop(name)` may terminate only a direct child created by the exact
  calling session in that room. Ask the owning supervisor to stop its worker.
  Stop also validates the recorded boot/start-time process identity and
  refuses to signal a PID that may have been reused.
- The heavy-resource rules below bind workers too: put the pseudo-claim rules
  (`__full-test-suite__` etc.) in the task brief for anything that runs tests.

Spawn privacy/retention: full task prompts are passed to the external CLI but
are not stored in `fleet.json` or `spawns.json`, even when short; those contain
only task length and a short digest. Spawn logs/metadata are mode `0600` and
generated rooms/directories `0700` where POSIX supports it. Server startup
also tightens legacy state under `ROOT_WS` without following links or changing
anything outside that root. Proved-dead
records, logs, and generated supervisor rooms older than 14 days are removed
on the next authenticated spawn. Set `COLLAB_SPAWN_RETENTION_DAYS=0` only for
an explicit indefinite local audit need, and review handoffs before cleanup.

## Workspace hygiene (clearing stale chat)

New sessions shouldn't have to wade through hundreds of stale messages from
finished tasks. If the room's history is clearly stale:

- `collab_clear` resets the message log. Default `mode: "archive"` saves the
  full log to `backlog/` inside the collab workspace first (recoverable);
  `mode: "discard"` drops it. Every session's read cursor is reset and a
  system notice records who cleared and why — pass a `note` with the reason.
- `collab_backlog` lists the archived logs; read the `.jsonl` files directly
  if old context needs to be recovered.
- Etiquette: check `collab_status` first. If other sessions look mid-task,
  ask via `collab_post` before clearing — clearing archives their undelivered
  messages instead of delivering them. Prefer archive over discard unless the
  chatter is genuinely worthless.

## Heavy shared resources (RAM, ports, servers)

Claims work for more than files. This laptop has 15 GB RAM and the **full
pytest suite loads real Whisper/TTS models (~6.5 GB per run)** — two sessions
running it concurrently caused system OOM kills that took down Codex Desktop
and every session in it (happened twice on 2026-07-09).

- Before running the FULL suite (`pytest` with no filter), claim the
  pseudo-path `__full-test-suite__`. If it's already held, wait or run the
  cheap subset instead. Release immediately after the run.
- Default to the cheap subset for iteration:
  `python3 -m pytest -q -k "not transcriber and not tts_engine"`
- Same pattern for other singletons: claim `__llama-server__` before
  restarting the model server on :8080, `__port-8000__` before binding the
  backend, etc. Pseudo-claims are cheap; OOM kills cost everyone's session.

## Conflict etiquette

- If `collab_claim` returns a conflict: do NOT edit the file. Post a `question`
  to the holder, work on something else meanwhile, and re-check `collab_status`.
- If Codex's hook blocks your edit, or Codex's hook warns that the edit is not
  enforceably blocked: same — coordinate, never work around it by shelling out
  (`bash` redirection to a claimed file defeats the whole system).
- Cross-room conflicts include a generation-specific route such as
  `supervisor@rooms/<generation>`. Contact that supervisor through the shared
  parent room (`collab_post` from main or `collab_report_up` from a supervisor);
  claimant display names alone can be duplicated across private rooms.
- If you receive a question addressed to you, answer promptly via `collab_post`
  even if mid-task — the other session may be blocked on you.
- Prefer splitting work by file boundary; if two sessions truly must touch the
  same file, agree in chat on who goes first and who rebases.
