#!/usr/bin/env python3
"""Minimal stdio MCP server exposing the multi-session collab workspace.

No dependencies: speaks newline-delimited JSON-RPC 2.0 on stdin/stdout.
Shared by Claude Code and Codex CLI (see .mcp.json / .codex/config.toml).
State helpers live in collab_lib.py; identity is client-neutral — see
collab_lib.my_session_id().
"""
import json
import sys
import time

import collab_lib as cl

TOOLS = [
    {
        "name": "collab_register",
        "description": (
            "Register this session in the shared workspace so other sessions in this "
            "repo (Claude Code or Codex CLI) can see you. Call once at the start of work with "
            "a short kebab-case name unique among live sessions in this room and what you're "
            "working on. Re-call from the same session to update your focus."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                    "maxLength": cl.SESSION_NAME_MAX,
                    "description": "Short kebab-case session name, e.g. 'voice-commands'",
                },
                "focus": {"type": "string", "description": "One line: what this session is working on"},
            },
            "required": ["name", "focus"],
        },
    },
    {
        "name": "collab_status",
        "description": "List all live sessions, their focus, and every file claim currently held. Use before starting work to see who else is active and what they own.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_claim",
        "description": (
            "Claim repo-relative file paths or virtual pseudo-resources such as "
            "'__full-test-suite__' before using them so other sessions don't step on your toes. "
            "Equivalent in-repo paths canonicalize to one claim; paths outside the repo are "
            "rejected. Returns conflicts if another live session already holds a path — in that "
            "case do not edit. The result includes a generation-specific room/supervisor route "
            "so cross-room conflicts can be coordinated through the shared parent channel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string", "description": "Why you need these files"},
            },
            "required": ["paths", "reason"],
        },
    },
    {
        "name": "collab_release",
        "description": "Release file claims when done editing. Omit paths to release everything this session holds. Always release before ending a task.",
        "inputSchema": {
            "type": "object",
            "properties": {"paths": {"type": "array", "items": {"type": "string"}}},
        },
    },
    {
        "name": "collab_post",
        "description": (
            "Post a message to this room's shared chat. kind='urgent' interrupts other sessions "
            "via hooks (merge conflicts, breaking changes, high-value collab opportunities); "
            "'question' asks for input; 'handoff' passes work; 'bug' reports a bug found along "
            "your task lines (route it to your supervisor); 'wake' wakes a sleeping/finishing "
            "session — it interrupts them mid-work AND blocks their Stop so they must act "
            "(equivalently, start any message text with 'WAKE:'); 'info' is FYI. "
            "Set 'to' to a session name for a direct message, omit for broadcast."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["info", "urgent", "question", "handoff", "bug", "wake"]},
                "text": {"type": "string"},
                "to": {"type": "string", "description": "Target session name (optional, broadcast if omitted)"},
            },
            "required": ["kind", "text"],
        },
    },
    {
        "name": "collab_inbox",
        "description": "Read messages from other sessions posted since you last checked. Check when starting a task and periodically during long work.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_clear",
        "description": (
            "Clear the shared message log so new sessions aren't flooded with stale history. "
            "Default mode 'archive' saves the current log to .claude/collab/backlog/ before "
            "clearing (recoverable via collab_backlog); 'discard' drops it outright. Resets "
            "every session's read cursor and posts a system notice saying who cleared and why. "
            "Etiquette: clear only stale or finished conversation — if other sessions look "
            "mid-task in collab_status, ask via collab_post first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["archive", "discard"],
                    "description": "archive (default): save the log to backlog/ first; discard: drop it",
                },
                "note": {"type": "string", "description": "Optional reason, recorded in the system notice"},
            },
        },
    },
    {
        "name": "collab_backlog",
        "description": (
            "List message logs archived by collab_clear (oldest first). Each entry is a "
            ".jsonl file under .claude/collab/backlog/ that can be read directly if old "
            "context needs to be recovered."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_spawn",
        "description": (
            "Spawn a headless Claude Code session (`claude -p`) into the hierarchy. "
            "role='supervisor' -> Opus 5 with its OWN collab room (its workers report there) "
            "and report-up wiring back to your room; give it a phase OBJECTIVE and it breaks "
            "that into <=3 worker tasks, reviews the results, and reports back. "
            "role='worker' -> Sonnet 5 joining YOUR room; give it one self-contained task. "
            "No role -> legacy flat worker (Opus 5, your room). Every spawned session starts "
            "from the repo root (callers cannot override the working directory), so project "
            "hooks and claim enforcement stay active. Before success is reported, the CLI must "
            "pass `auth status --json` and the child must survive a bounded health-check; "
            "immediate auth/model/settings failures return an error and create no fleet record. "
            "Default permission_mode=taskSafe uses manual plus an explicit allowed-tools list "
            "for repo edits and targeted tests, not global bypass. HARD CAPS, repo-wide across every room (the "
            f"user-approved budget): {cl.MAX_OPUS} Opus and {cl.MAX_SONNET} Sonnet sessions "
            "running at once — a blocked spawn errors until a slot frees (collab_stop or wait). "
            "Watch progress via collab_workers/collab_fleet and the session's private log file."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$",
                    "maxLength": cl.SESSION_NAME_MAX,
                    "description": "Kebab-case session name, e.g. 'sup-audio' or 'worker-overlay-fix'",
                },
                "task": {"type": "string", "description": "Supervisors: the phase objective. Workers: the full task brief — self-contained, with file paths and done-criteria"},
                "role": {
                    "type": "string",
                    "enum": ["supervisor", "worker"],
                    "description": "supervisor = Opus 5 + own room (director use); worker = Sonnet 5 in your room (supervisor use). Omit for a legacy flat worker.",
                },
                "model": {"type": "string", "description": "Model override (default: role preset, else claude-opus-5)"},
                "effort": {
                    "type": "string",
                    "enum": ["low", "medium", "high"],
                    "description": "Reasoning effort (default medium)",
                },
                "permission_mode": {
                    "type": "string",
                    "enum": list(cl.PERMISSION_MODES),
                    "description": "Default taskSafe = manual with explicit allowed tools. bypassPermissions is only for an explicitly selected, user-approved call.",
                },
                "allowed_tools": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 160},
                    "minItems": 1,
                    "description": "Optional per-spawn replacement allowlist, only with permission_mode=taskSafe. Uses Claude --allowedTools permission strings.",
                },
            },
            "required": ["name", "task"],
        },
    },
    {
        "name": "collab_fleet",
        "description": (
            "Repo-wide view of every spawned session across ALL rooms (the whole "
            "director/supervisor/worker tree): role, model, room, running state, and cap "
            "usage per model family. Use before spawning to see what the budget allows."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_report_up",
        "description": (
            "Post a message into your PARENT room (the room of the session that spawned you). "
            "Supervisors report to the director this way: kind='handoff' for a finished, "
            "reviewed objective; 'bug' for findings; 'question' when blocked; 'wake' to wake "
            "a sleeping director. Defaults to addressing your spawner."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["info", "urgent", "question", "handoff", "bug", "wake"]},
                "text": {"type": "string"},
                "to": {"type": "string", "description": "Target session name in the parent room (default: your spawner)"},
            },
            "required": ["kind", "text"],
        },
    },
    {
        "name": "collab_check_up",
        "description": (
            "Read new messages from your PARENT room (directives from the director, or "
            "traffic from sibling supervisors reporting up). Check after registering and "
            "between phases."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_wait",
        "description": (
            "Sleep until something happens: a new message arrives in your room or parent "
            "room, or one of your spawned sessions exits. Returns immediately with whatever "
            "arrived, or empty after the timeout. This is how a director/supervisor waits "
            "for reports without burning turns polling — loop it while workers run."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "number", "description": "Max seconds to wait (default 60, cap 240)"},
            },
        },
    },
    {
        "name": "collab_workers",
        "description": (
            "List sessions spawned via collab_spawn: running or exited, exit status, model, "
            "and log path (read the log for the worker's output/hand-back)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "collab_stop",
        "description": (
            "Stop one direct child after verifying the caller is the exact spawning session "
            "in the owner room and the PID start identity still matches. Fleet visibility does "
            "not grant fleet-wide stop authority; PID reuse is never signaled."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Worker name from collab_workers"}},
            "required": ["name"],
        },
    },
]


def fmt_ts(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def status_text():
    sessions = cl.get_sessions()
    claims = cl.get_claims()
    me = cl.my_session_id()
    lines = []
    if cl.has_parent_room():
        lines.append(f"Room: {cl.WS.name} (parent room wired — collab_report_up/collab_check_up reach it)")
    lines.append(f"Live sessions ({len(sessions)}):")
    for pid, s in sessions.items():
        tag = " (you)" if pid == me else ""
        lines.append(f"  - {s['name']}{tag}: {s['focus']} [since {fmt_ts(s['started'])}]")
    if claims:
        lines.append(f"File claims ({len(claims)}):")
        for path, c in sorted(claims.items()):
            lines.append(
                f"  - {path} -> {c['session']}: {c['reason']} "
                f"[{cl.describe_claim_route(c)}]"
            )
    else:
        lines.append("File claims: none")
    return "\n".join(lines)


def handle_tool(name, args):
    if name == "collab_register":
        pid, sessions = cl.register_session(args["name"], args["focus"])
        cl.post_message("system", f"{args['name']} joined: {args['focus']}", sender="workspace")
        url = cl.start_viewer_if_needed()
        out = f"Registered as '{args['name']}' (claude pid {pid}).\n" + status_text()
        if url:
            out += f"\n\nLive conversation panel is up: {url} (open it in a browser to watch sessions talk)."
        return out

    if name == "collab_status":
        return status_text()

    if name == "collab_claim":
        granted, conflicts = cl.claim_paths(args["paths"], args.get("reason", ""))
        out = []
        if granted:
            out.append("Claimed: " + ", ".join(granted))
        if conflicts:
            out.append("CONFLICTS (do NOT edit these; use the route shown):")
            for p, c in conflicts.items():
                out.append(
                    f"  - {p} held by {c['session']} ({c['reason']}); "
                    f"{cl.describe_claim_route(c)}"
                )
        return "\n".join(out) or "Nothing to do."

    if name == "collab_release":
        released = cl.release_paths(args.get("paths"))
        return "Released: " + (", ".join(released) if released else "nothing (no matching claims held by you)")

    if name == "collab_post":
        msg = cl.post_message(args["kind"], args["text"], to=args.get("to"))
        note = " Other sessions will be interrupted at their next tool call." if args["kind"] == "urgent" else ""
        return f"Posted [{msg['kind']}] as {msg['from']}.{note}"

    if name == "collab_inbox":
        msgs = cl.read_new_messages()
        if not msgs:
            return "No new messages."
        return "\n".join(
            f"[{fmt_ts(m['ts'])}] {m['from']} ({m['kind']}{', to you' if m.get('to') else ''}): {m['text']}"
            for m in msgs
        )

    if name == "collab_clear":
        mode = args.get("mode") or "archive"
        if mode not in ("archive", "discard"):
            raise ValueError("mode must be 'archive' or 'discard'")
        count, archive = cl.clear_messages(mode=mode, note=args.get("note"))
        if not count:
            return "Message log already empty — nothing to clear."
        where = f"archived to {archive}" if archive else "discarded (no archive)"
        return (
            f"Cleared {count} message(s); {where}. All read cursors reset; "
            "a system notice was posted so other sessions know."
        )

    if name == "collab_backlog":
        entries = cl.list_backlog()
        if not entries:
            return "Backlog empty — no archived message logs. collab_clear (mode=archive) creates them."
        return "Archived message logs (oldest first):\n" + "\n".join(
            f"  - {e['file']} ({e['messages']} messages)" for e in entries
        )

    if name == "collab_spawn":
        rec = cl.spawn_worker(
            args["name"], args["task"],
            model=args.get("model"), effort=args.get("effort"),
            permission_mode=args.get("permission_mode") or "taskSafe",
            role=args.get("role"), allowed_tools=args.get("allowed_tools"),
        )
        where = f"its own room ({rec['room']})" if rec.get("role") == "supervisor" else "this room"
        return (
            f"Spawned {rec.get('role') or 'worker'} '{args['name']}' (pid {rec['pid']}, {rec['model']}, "
            f"effort {rec['effort']}, {rec['permission_mode']}) in {where}.\n"
            f"Log: {rec['log']}\n"
            "Wait for its reports with collab_wait; watch collab_workers/collab_fleet, or tail the log."
        )

    if name == "collab_workers":
        spawns = cl.get_spawns()
        if not spawns:
            return "No spawned workers yet. collab_spawn creates one."
        lines = [f"Sessions spawned from this room ({sum(r['running'] for r in spawns.values())} running; "
                 "repo-wide caps in collab_fleet):"]
        for wname, r in sorted(spawns.items(), key=lambda kv: kv[1].get("ts", 0)):
            state = "RUNNING" if r["running"] else (
                f"exited status={r['exit_status']}" if r["exit_status"] is not None else "exited (status unknown)"
            )
            lines.append(f"  - {wname} [{state}] {r.get('role') or 'worker'} {r['model']}/{r['effort']}, "
                         f"by {r.get('spawned_by', '?')} at {fmt_ts(r.get('ts', 0))}")
            lines.append(f"      log: {r['log']}")
        return "\n".join(lines)

    if name == "collab_fleet":
        fleet = cl.get_fleet()
        counts = cl.fleet_counts()
        lines = ["Fleet caps: " + ", ".join(
            f"{fam} {counts.get(fam, 0)}/{cl.family_cap(fam)}" for fam in ("opus", "sonnet")
        )]
        if not fleet:
            lines.append("No sessions spawned anywhere yet.")
            return "\n".join(lines)
        for fleet_id, r in sorted(fleet.items(), key=lambda kv: kv[1].get("ts", 0)):
            wname = r.get("name", fleet_id)
            state = "RUNNING" if r["running"] else (
                f"exited status={r['exit_status']}" if r["exit_status"] is not None else "exited (status unknown)"
            )
            lines.append(f"  - {wname} [{state}] {r.get('role') or 'worker'} {r['model']}, "
                         f"by {r.get('spawned_by', '?')}, room {r.get('room', '?')}")
            lines.append(f"      log: {r['log']}")
        return "\n".join(lines)

    if name == "collab_report_up":
        if not cl.PARENT_WS:
            return ("Error: no parent room — this session is at the top of the hierarchy here. "
                    "Use collab_post to talk in your own room.")
        msg = cl.post_message(args["kind"], args["text"],
                              to=args.get("to") or cl.PARENT_NAME, base=cl.PARENT_WS)
        target = msg["to"] or "everyone in the parent room"
        return f"Reported up [{msg['kind']}] as {msg['from']} to {target}."

    if name == "collab_check_up":
        if not cl.has_parent_room():
            return ("No separate parent room (directors have none; workers share their room "
                    "with their supervisor — use collab_inbox).")
        msgs = cl.read_new_messages(base=cl.PARENT_WS)
        if not msgs:
            return "No new messages in the parent room."
        return "Parent room:\n" + "\n".join(
            f"[{fmt_ts(m['ts'])}] {m['from']} ({m['kind']}{', to you' if m.get('to') else ''}): {m['text']}"
            for m in msgs
        )

    if name == "collab_wait":
        exited, msgs, up = cl.wait_for_activity(args.get("seconds") or 60)
        if not (exited or msgs or up):
            running = [n for n, r in cl.get_spawns().items() if r["running"]]
            tail = f" Still running: {', '.join(running)}." if running else ""
            return (f"No activity before the timeout.{tail} collab_wait again, or check "
                    "worker logs if this keeps happening.")
        lines = []
        if exited:
            spawns = cl.get_spawns()
            for n in exited:
                st = spawns.get(n, {}).get("exit_status")
                log = spawns.get(n, {}).get("log", "?")
                lines.append(f"EXITED: {n} (status {st}) — read its log for the hand-back: {log}")
        for m in msgs:
            lines.append(f"[{fmt_ts(m['ts'])}] {m['from']} ({m['kind']}{', to you' if m.get('to') else ''}): {m['text']}")
        for m in up:
            lines.append(f"[parent room] [{fmt_ts(m['ts'])}] {m['from']} ({m['kind']}): {m['text']}")
        return "\n".join(lines)

    if name == "collab_stop":
        rec = cl.stop_worker(args["name"])
        return f"Sent SIGTERM to worker '{args['name']}' (pid {rec['pid']}). Its log: {rec['log']}"

    raise ValueError(f"unknown tool {name}")


def main():
    # Startup also migrates legacy state permissions. The migration is bounded
    # to ROOT_WS and never follows symlinks.
    cl.ensure_ws()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        rid = req.get("id")
        method = req.get("method", "")
        resp = None
        if method == "initialize":
            resp = {
                "protocolVersion": req.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "collab-workspace", "version": "1.0.0"},
            }
        elif method == "tools/list":
            resp = {"tools": TOOLS}
        elif method == "tools/call":
            params = req.get("params", {})
            try:
                text = handle_tool(params.get("name"), params.get("arguments") or {})
                resp = {"content": [{"type": "text", "text": text}]}
            except Exception as e:  # report tool errors in-band
                resp = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
        elif method == "ping":
            resp = {}
        elif rid is None:
            continue  # notification (e.g. notifications/initialized)
        else:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }) + "\n")
            sys.stdout.flush()
            continue
        if rid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": resp}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
