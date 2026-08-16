---
name: hierarchy
description: Director → Supervisor → Worker orchestration over the collab MCP. Use when acting as the DIRECTOR of a multi-phase build - breaking phases into objectives, spawning Opus 5 supervisors (each with their own room of Sonnet 5 workers), and reviewing their reports. Hard caps 2 Opus / 4 Sonnet running repo-wide.
---

# Hierarchy Protocol (Director playbook)

Three tiers, two collab levels, enforced budgets:

```
DIRECTOR (you: Fable 5 interactive, or GPT in Codex)      — main room
  ├── supervisor A (Opus 5, own room)  ── workers (Sonnet 5) in A's room
  └── supervisor B (Opus 5, own room)  ── workers (Sonnet 5) in B's room
```

- Director ↔ supervisors talk across the **main room** (supervisors use
  `collab_report_up` / `collab_check_up` to reach it from their own rooms).
- Each supervisor ↔ its workers talk in the **supervisor's private room** —
  worker chatter never floods the director.
- **Hard caps, repo-wide across all rooms: 2 Opus + 4 Sonnet running at
  once** (`COLLAB_MAX_OPUS` / `COLLAB_MAX_SONNET` to change). A spawn over
  budget errors until a slot frees. File claims are repo-global, so workers
  under different supervisors can never collide on a file.

## Director loop

1. **Register** in the main room (`collab_register`, e.g. name `director`).
2. **Break the big picture into phases**, each phase into 1–2 self-contained
   **objectives** (scope, file areas, constraints, done-criteria, how to
   verify). An objective is supervisor-sized: bigger than one task, small
   enough to finish in one session.
3. **Spawn up to 2 supervisors**:
   `collab_spawn(name='sup-<area>', role='supervisor', task=<objective>)`.
   Each gets Opus 5, a clean generation-specific private room, and an
   auto-brief telling it to split the objective into ≤3 worker tasks, review
   all worker output, and report up. Reusing a display name never reuses the
   old room, cursors, messages, or spawn state. Worker names are also routing
   keys and cannot be spawned over a live same-name session in their room.
   - A spawn is not announced or recorded until `Codex auth status --json`
     reports `loggedIn: true` and the child survives a short synchronous
     health-check. Missing auth or immediate model/settings/argument failures
     are tool errors with a concise redacted log tail; they are not "Spawned."
     Authentication is an external prerequisite: run `Codex auth login`
     interactively outside the director workflow, then retry. Never attempt
     interactive login from a headless session.
   - The default `permission_mode='taskSafe'` maps to Codex's supported
     `manual` mode plus an explicit `--allowedTools` list for repo reads/edits,
     collab lifecycle calls, and narrowly matched verification commands such
     as targeted pytest. Override `allowed_tools` for a narrower task-specific
     list. `bypassPermissions` adds the CLI's dangerous-skip opt-in and is
     permitted only on a call the user explicitly approved.
4. **Wait, don't poll**: loop `collab_wait` (it returns when a supervisor
   reports up or a spawned session exits). The Stop-hook keepalive will stop
   you finishing while supervisors still run — that's intentional.
5. **Review each `handoff`** from a supervisor: check the claimed
   verification actually happened (diffs, test evidence). Send follow-ups
   with `collab_post(to='sup-...')` — that lands in the main room; the
   supervisor's hooks deliver it. Use `kind='wake'` if the supervisor has
   gone quiet.
6. When a phase's objectives are done, **advance to the next phase** (reuse
   supervisor names or new ones — the cap counts *running* sessions only).
7. `collab_fleet` any time for whole-tree visibility + cap usage.
   `collab_stop` is deliberately narrower: only the exact session in the
   spawning room may stop its direct child. A director cannot signal a
   supervisor's worker merely because it can see it in the fleet; direct the
   owning supervisor to stop that worker. Stop verifies the recorded Linux
   boot/start-time identity and refuses to signal a reused/unrelated PID.
   Logs live under `.Codex/collab/spawn-logs/`.

## Supervisor / worker behavior (auto-briefed at spawn)

Supervisors: register in own room → `collab_check_up` → split objective into
≤3 worker tasks → `collab_spawn(role='worker')` (Sonnet 5; global budget may
force fewer — run what fits, start the rest as slots free) → `collab_wait`
between reports → review every handoff (read diffs, run tests) → triage
worker `bug` reports → `collab_report_up kind='handoff'` when the objective
is reviewed and sound.

Workers: register → claim → do the one task → post `kind='bug'` findings
along the way → release claims → `handoff` to their supervisor.

## Ground rules

- Objectives and tasks must be **self-contained** — spawned sessions cannot
  ask the user anything.
- Never raise the caps in a brief; they're the user-approved budget.
- Spawns must start from the repo root (the default) — elsewhere silently
  disables claim enforcement.
- Fleet/spawn metadata stores only task length and a short digest, never task
  text (even when short). Spawn metadata/logs are mode `0600` (rooms/directories
  `0700`) where POSIX supports it; startup also tightens legacy state under
  `ROOT_WS` without following links outside it. Proved-dead records, logs, and generated
  supervisor rooms older than 14 days are pruned on the next successful-auth
  spawn; set `COLLAB_SPAWN_RETENTION_DAYS=0` only when an operator explicitly
  needs indefinite local retention. Review handoffs before cleanup.
- Cross-room claim conflicts report `supervisor@rooms/<generation>` routing.
  Use `collab_post` from main or `collab_report_up` from a supervisor to reach
  that owner; private-room claimant display names are not globally unique.
- Wake semantics (who wakes whom and how) live in the `wake` skill.
