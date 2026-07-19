# AGENTS.md — Codex instructions for the BetterFingers shared checkout

This repo is worked on by multiple agent sessions at once (Claude Code and
Codex CLI), all in the **same checkout**, coordinated through a shared
collaboration workspace. Read this before touching any file.

Full plan and task assignments: [`ACCOMPLISH.md`](ACCOMPLISH.md), especially
§5 (team topology) and §6 (collaboration MCP protocol), which this file
summarizes the Codex-relevant parts of.

## Non-negotiable rules for every session in this checkout

- **No edits without a claim.** See "Collaboration protocol" below. This is
  enforced (imperfectly for Codex — see "Known gap" below) by hooks, but it
  is a repo rule regardless of enforcement.
- **Shell commands may not write source files.** Never use shell redirection,
  `sed -i`, heredocs, `cat >`, or similar to create or modify a tracked file.
  Only `apply_patch` (or the editor-equivalent tools) may write source, because
  only those tool calls go through the collab claim-check hook. A shell
  command that writes a file bypasses claim checking entirely and can silently
  clobber another session's in-progress work — this defeats the whole
  coordination system the same way it would for Claude Code (see
  `.claude/skills/collab/SKILL.md`, "never work around the block by shelling
  out"). Shell commands are for reading, running tests/builds, and other
  non-mutating or generated-artifact work — not for writing tracked source.
- **No agent manages Git.** Do not run `git add`, `git commit`, `git switch`,
  `git checkout`, `git rebase`, `git merge`, `git reset`, `git stash`,
  `git clean`, or tag/release commands. Only the coordinator does this
  (ACCOMPLISH.md §5). Leave your work uncommitted for the coordinator to
  review and stage.
- **Stay inside your claimed files.** Claim narrowly (the files you'll
  actually touch), work only inside that claim, and release as soon as you're
  done editing.

## Collaboration protocol (mandatory lifecycle)

The `collab` MCP server (configured in `.codex/config.toml`; per coordinator
decision 2026-07-18 it points at the MACHINE-WIDE server/room
`~/.claude/collab` — the room this machine's Claude sessions actually
occupy) is your session's window into who else is active. Core tools:
`collab_register`, `collab_status`, `collab_claim`, `collab_release`,
`collab_post`, `collab_inbox`. Workspace hygiene: `collab_clear` (archive
the stale message log to `backlog/` — or discard it — and reset all read
cursors) and `collab_backlog` (list archives); clear only stale/finished
conversation — if other sessions look mid-task in `collab_status`, ask via
`collab_post` first. Director tooling (`collab_board` notes/side-task board,
`collab_spawn`/`collab_agents` sonnet worker spawner max 3 alive,
`collab_perms`/`collab_decide` permission review): see `~/.codex/AGENTS.md`
— any Codex session may act as room director.

1. Call `collab_register` with a short kebab-case session name and a one-line
   focus, before any edits.
2. Call `collab_status` and `collab_inbox`. If another session's focus
   overlaps yours, message them (`collab_post`) before starting.
3. Call `collab_claim` with the exact repo-relative paths you're about to
   touch (production files, test files, generated artifacts, and shared
   pseudo-resources like `__full-test-suite__`). If it returns a conflict, do
   not edit that path — coordinate via `collab_post` instead.
4. Post an `info` message: `START <task-id> — outcome; claimed paths; planned
   tests`.
5. Work only inside the claim. Check `collab_inbox` after contract changes and
   before verification — an interrupt hook may also surface urgent messages
   automatically (see "Hooks" below).
6. Post a `handoff` using the HANDOFF format in ACCOMPLISH.md §6, then call
   `collab_release` and stop. Do not start a dependent task until the
   coordinator posts `ACCEPTED`.

Message kinds: `urgent` (active contract break, shared-file hazard, or
merge-blocking discovery — interrupts other sessions), `question` (need input
from a specific session, set `to`), `handoff` (finished work another session
should pick up), `info` (FYI). Don't cry wolf with `urgent`.

## Session identity

Sessions are identified client-neutrally so Claude Code and Codex CLI agree
without a handshake (`collab_lib.my_session_id()`):

1. An explicit `COLLAB_SESSION_ID` environment variable, if set on the
   process that launches this session — every child process (the MCP server,
   hook scripts) inherits it. Set this yourself if you're running in an
   environment where process ancestry might not resolve cleanly (containers,
   remote executors, nested shells).
2. Otherwise, the nearest ancestor process named `claude` or `codex`, which
   is what a normal local Codex CLI session already looks like — no action
   needed in the common case.

## Hooks

`.codex/hooks.json` wires four lifecycle hooks, all delegating to the same
`.claude/collab-mcp/hooks.py` dispatcher Claude Code uses (invoked with
`--client=codex` so it replies in Codex's flat `{"systemMessage": ...}`
schema instead of Claude's nested `hookSpecificOutput`):

- `SessionStart` — injects current session roster + file claims as a
  `systemMessage` so you know who else is active before your first tool call.
- `UserPromptSubmit` — delivers any unread `collab_post` messages addressed to
  you (or broadcast) as a `systemMessage`.
- `PostToolUse` — surfaces pending `urgent` messages as an interrupt after
  your next tool call.
- `PreToolUse` (matcher: `apply_patch`) — checks whether any path your patch
  touches is claimed by another live session.

Before these run, Codex will ask you to review and trust them (`/hooks` in an
interactive session). Trust them — they're read-only against your working
tree; they only ever read `.claude/collab/` state and never mutate source.

### Known gap: `PreToolUse` cannot block `apply_patch`

As of the current Codex CLI, `PreToolUse` hooks support only a `systemMessage`
field — there is no `continue`/deny mechanism, so a conflicting `apply_patch`
call **cannot be hard-rejected** the way Claude Code's `Edit`/`Write` calls
are (Claude's `PreToolUse` hook does support `permissionDecision: "deny"` and
uses it). The Codex-side hook still fires and attaches a loud
`"WARNING — NOT ENFORCED: ... claimed by ..."` message, but the patch is
applied regardless — the warning is advisory, not a backstop.

**Because of this gap, you must treat claim conflicts as a hard stop
yourself**: if `collab_claim` reports a conflict, or a `PreToolUse`
`systemMessage` warns that a path is claimed by another session, do not
proceed with that `apply_patch`. Coordinate via `collab_post` first. This is
exactly the same discipline Claude Code sessions already follow for claim
conflicts (`.claude/skills/collab/SKILL.md`) — Codex just doesn't get an
enforced backstop for it yet.

## Heavy shared resources

Same rule as Claude Code: claim the pseudo-path `__full-test-suite__` before
running the full pytest suite (`pytest` with no filter) — it loads real
Whisper/TTS models (~6.5 GB) and two concurrent runs have caused OOM kills.
Default to the cheap subset for iteration:
`python3 -m pytest -q -k "not transcriber and not tts_engine"`. Same pattern
for `__llama-server__`, `__port-8000__`, and other shared singletons.
