---
name: collab
description: Multi-session collaboration protocol for this repo. Use at the START of any coding task, and whenever another Claude session may be active (the SessionStart context will say so). Covers registering presence, claiming files before editing, messaging other sessions, and handling urgent interrupts.
---

# Collab Workspace Protocol

Multiple Claude Code sessions may work in this repo at once. A shared workspace
(`.claude/collab/`, via the `collab` MCP server) keeps them from stepping on each
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
   actually touch, not whole directories. A PreToolUse hook will hard-block
   edits to files claimed by another session, so claiming is not optional.
4. **Work.** During long tasks, check `collab_inbox` between major steps.
   Urgent messages are also injected automatically by hooks — treat an
   `[collab-workspace INTERRUPT]` as higher priority than your current step:
   read it, respond via `collab_post`, then decide whether to continue or adjust.
5. **Release when done.** Call `collab_release` (no args releases all your
   claims) as soon as you finish editing a file — don't hold claims across
   unrelated work. Post a `handoff` or `info` message summarizing what changed.

## Message kinds

- `urgent` — interrupts other sessions at their next tool call. Use for:
  you're about to change a shared interface they depend on, you found a bug in
  code they own, a merge/rebase hazard, or a high-value collaboration
  opportunity (e.g. "I'm already refactoring backend.js — don't duplicate").
  Don't cry wolf; everything else is `info`.
- `question` — you need input from a specific session (`to: "their-name"`).
- `handoff` — you finished something they should pick up or rebase onto.
- `info` — FYI broadcast (what you changed, what you're starting).

## Heavy shared resources (RAM, ports, servers)

Claims work for more than files. This laptop has 15 GB RAM and the **full
pytest suite loads real Whisper/TTS models (~6.5 GB per run)** — two sessions
running it concurrently caused system OOM kills that took down Claude Desktop
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
- If the hook blocks your edit: same — coordinate, never work around the block
  by shelling out (`bash` redirection to a claimed file defeats the whole system).
- If you receive a question addressed to you, answer promptly via `collab_post`
  even if mid-task — the other session may be blocked on you.
- Prefer splitting work by file boundary; if two sessions truly must touch the
  same file, agree in chat on who goes first and who rebases.
