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
            "a short session name and what you're working on. Re-call to update your focus."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short kebab-case session name, e.g. 'voice-commands'"},
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
            "Claim repo-relative file paths before editing them so other sessions don't step on "
            "your toes. Returns conflicts if another live session already holds a path — in that "
            "case coordinate via collab_post instead of editing."
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
            "Post a message to the shared session chat. kind='urgent' interrupts other sessions "
            "via hooks (merge conflicts, breaking changes, high-value collab opportunities); "
            "'question' asks for input; 'handoff' passes work; 'info' is FYI. "
            "Set 'to' to a session name for a direct message, omit for broadcast."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["info", "urgent", "question", "handoff"]},
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
]


def fmt_ts(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def status_text():
    sessions = cl.get_sessions()
    claims = cl.get_claims()
    me = cl.my_session_id()
    lines = [f"Live sessions ({len(sessions)}):"]
    for pid, s in sessions.items():
        tag = " (you)" if pid == me else ""
        lines.append(f"  - {s['name']}{tag}: {s['focus']} [since {fmt_ts(s['started'])}]")
    if claims:
        lines.append(f"File claims ({len(claims)}):")
        for path, c in sorted(claims.items()):
            lines.append(f"  - {path} -> {c['session']}: {c['reason']}")
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
            out.append("CONFLICTS (do NOT edit these, coordinate via collab_post):")
            for p, c in conflicts.items():
                out.append(f"  - {p} held by {c['session']} ({c['reason']})")
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

    raise ValueError(f"unknown tool {name}")


def main():
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
