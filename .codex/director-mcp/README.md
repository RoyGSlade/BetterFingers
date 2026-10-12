# BetterFingers Codex Director MCP

This repository-local stdio MCP launches and manages a hierarchy made entirely
of Codex CLI sessions:

```text
interactive Codex director
  |-- Codex supervisor (gpt-5.6-sol, read-only)
  |     `-- Codex workers (gpt-5.6-terra, workspace-write)
  `-- optional direct Codex worker
```

It is separate from `.claude/collab-mcp/server.py`. The director MCP owns
Codex process lifecycle, topology, caps, results, and resumable follow-ups. The
existing collab MCP remains authoritative for shared-checkout registration,
file claims, messages, and handoffs across Codex and Claude sessions.

## Why this uses `codex exec`

Codex documents `codex exec` as its non-interactive automation interface and
`--json` as the machine-readable JSONL event stream. Each agent is launched
from the repository root with explicit model, reasoning effort, sandbox, and
`approval_policy=never`. The server extracts the persisted Codex thread ID so
an exited child can be resumed for a correction instead of losing context.

The implementation is dependency-free Python and speaks newline-delimited
JSON-RPC 2.0 over stdio. Project registration lives in `.codex/config.toml`.
That configuration explicitly forwards the per-agent role and identity
variables into child MCP processes and pre-approves the repository-local
coordination tools for non-interactive use.
For Codex clients it allowlists only the collab claim/message/read tools;
`collab_spawn`, `collab_stop`, and `collab_clear` stay hidden so a worker
cannot bypass the director MCP's role and sandbox boundaries.

## Tool workflow

1. `codex_director_register` once per hierarchy session.
2. `codex_director_status` before dispatch to inspect sessions, children, and
   the independent Codex fleet caps.
3. `codex_director_spawn` with a self-contained objective.
4. `codex_director_wait` until a message or child exit.
5. `codex_director_result` to review the final message and private JSONL log.
6. `codex_director_resume` for a bounded correction on the same Codex thread.
7. `codex_director_stop` only when a direct child must be terminated.

`codex_director_send`, `codex_director_inbox`, and
`codex_director_report` provide topology-limited parent/child communication.
Workers do not receive spawn, wait, result, resume, or stop tools. Supervisors
may spawn workers only. Directors may spawn supervisors or direct workers.
Spawned agents use `codex_director_report` for their parent handoff and use
`collab_post` separately for the repository-global lifecycle; neither channel
silently substitutes for the other.

## Safety contract

- Codex-wide caps default to two running supervisors and four running workers.
  They apply across every process connected to the same director state root.
- Supervisors are forced into the `read-only` sandbox. Workers default to
  `workspace-write`; the MCP exposes no `danger-full-access` option.
- Only the exact spawning session can resume or stop a child. Stop verifies
  Linux boot ID, process start time, and non-zombie state before signaling the
  runner's process group.
- Names are routing keys and must be kebab-case. A live name cannot be reused.
- Fleet metadata stores only a short SHA-256 task digest and character count,
  never the task text. State directories are `0700`; state, cursor, and log
  files are `0600` where POSIX permissions are available.
- Spawned Codex sessions inherit a distinct director identity. The collab MCP
  and hooks intentionally derive identity from the real Codex process ancestry
  so a finished child is pruned immediately instead of lingering for the
  environment-session heartbeat timeout. Their prompt requires the repository
  claim lifecycle and forbids Git mutations.
- Authentication is checked with `codex login status` before a process or
  fleet record is created. Immediate startup failures are returned with
  credential-like text redacted.
- Runtime state is written under `.claude/collab/codex-director/`, which is
  already covered by the repository's collab-state ignore rule.

This implementation targets Linux/POSIX. It uses `fcntl`, `/proc`, POSIX
process groups, and signals; it is not Windows-native.

## Defaults and overrides

| Setting | Default |
|---|---|
| `CODEX_DIRECTOR_SUPERVISOR_MODEL` | `gpt-5.6-sol` |
| `CODEX_DIRECTOR_SUPERVISOR_EFFORT` | `high` |
| `CODEX_DIRECTOR_WORKER_MODEL` | `gpt-5.6-terra` |
| `CODEX_DIRECTOR_WORKER_EFFORT` | `medium` |
| `CODEX_DIRECTOR_MAX_SUPERVISORS` | `2` |
| `CODEX_DIRECTOR_MAX_WORKERS` | `4` |
| `CODEX_DIRECTOR_CLI` | `codex` from `PATH` |
| `CODEX_DIRECTOR_ROOT_DIR` | `.claude/collab/codex-director/` |

Per-call `model` and `reasoning_effort` overrides are available. Supervisor
sandbox overrides remain read-only by design.

## Verification

The E2E suite uses a fake CLI and an isolated temporary state directory; it
does not consume model tokens or touch real Codex sessions:

```bash
python3 .codex/director-mcp/test_director.py
python3 -m pytest -q .codex/director-mcp/test_director.py
python3 -m py_compile .codex/director-mcp/director_lib.py \
  .codex/director-mcp/server.py .codex/director-mcp/test_director.py
codex mcp list
```

After changing `.codex/config.toml`, restart Codex (or start a new session) so
the new stdio server is loaded. Then confirm both `collab` and
`codex_director` appear in `/mcp`.
