---
name: wake
description: Wake code protocol for the collab workspace - how to wake a sleeping or finishing session, and how the Stop-hook watcher keeps directors/supervisors alive while their spawned sessions run. Use when a session you need has gone quiet, or when you are waiting on reports and must not die.
---

# Wake Protocol

A hook watches every registered Codex session for the **wake call** and
wakes the model instead of letting it go idle or finish.

## The wake call

Either of these is the specific call the watcher looks for:

- `collab_post(kind='wake', to='<session>', text='...')` (preferred), or
- any message whose text **starts with the literal code `WAKE:`**.

`collab_report_up(kind='wake', ...)` sends the same call into your parent
room (supervisor → director).

## What the watcher does (hooks.py, Codex sessions only)

- **Mid-work** (PostToolUse): a pending `wake`/`urgent` message interrupts
  the session's next tool call with `[collab-workspace INTERRUPT]`.
- **At Stop** (the wake watcher): when a session tries to finish, any
  pending message addressed to it — or any `wake`/`urgent`/`WAKE:` message —
  **blocks the stop** with `[collab-workspace WAKE]` and the message text.
  The model wakes, handles it (answer, review the handoff, triage the bug),
  then may finish.
- **Keepalive**: a session with spawned children still running gets its stop
  blocked (`[collab-workspace KEEPALIVE n/10]`) and is told to `collab_wait`.
  After 10 consecutive quiet blocks it may stop, and a system notice
  (`went idle with sessions still running`) is posted so the parent knows.

Codex sessions can't be stop-blocked (no such hook exists there) — a Codex
director must loop `collab_wait` itself and should be woken via a normal
message it will see on its next prompt.

## How to be wakeable / wait correctly

- Stay **registered** — the watcher ignores unregistered sessions.
- Waiting for reports? Don't end your turn and don't poll in a tight loop:
  call `collab_wait` (`seconds=240` for long waits). It returns the moment a
  message lands in your room or parent room, or a child session exits.
- Woken with nothing actionable? Say why and finish — the watcher consumed
  the messages, so it won't re-fire for the same traffic.

## Etiquette

`wake` is a control signal, not chat: use it to restart a stalled supervisor,
force a director to review a finished phase, or pull someone out of
`collab_wait`. Everything informational is `info`/`bug`/`handoff`.
