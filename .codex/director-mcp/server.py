#!/usr/bin/env python3
"""Dependency-free stdio MCP server for Codex-native agent direction."""

from __future__ import annotations

import json
import sys
import time

import director_lib as dl


INSTRUCTIONS = (
    "Register first. This MCP launches only Codex agents in a director -> supervisor -> worker "
    "hierarchy. Directors may spawn supervisors or workers; supervisors may spawn workers; workers "
    "cannot spawn. Global caps are 2 supervisors and 4 workers. Use wait, inspect each result, and "
    "resume for corrections. Stop only your direct children. Agents must also obey AGENTS.md and the "
    "collab claim lifecycle; no agent manages Git."
)


def _tool(name, title, description, properties=None, required=None, read_only=False, destructive=False):
    return {
        "name": name,
        "title": title,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "openWorldHint": False,
        },
    }


COMMON_TOOLS = [
    _tool(
        "codex_director_register",
        "Register Codex hierarchy session",
        "Call first with a unique kebab-case name and one-line focus. Binds this MCP process to its director, supervisor, or worker identity.",
        {
            "name": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "maxLength": 48},
            "focus": {"type": "string", "minLength": 1, "maxLength": 300},
        },
        ["name", "focus"],
    ),
    _tool(
        "codex_director_status",
        "Inspect Codex hierarchy",
        "Show live registered sessions, every spawned Codex agent, task digests, state, ownership, models, and global cap usage.",
        read_only=True,
    ),
    _tool(
        "codex_director_inbox",
        "Read hierarchy messages",
        "Read new messages from your direct parent or children. Spawned agents should check before verification.",
    ),
    _tool(
        "codex_director_send",
        "Message a parent or child",
        "Send a bounded message to a live registered direct parent or child.",
        {
            "kind": {"type": "string", "enum": ["info", "question", "urgent", "handoff", "bug"]},
            "text": {"type": "string", "minLength": 1, "maxLength": 12000},
            "to": {"type": "string"},
        },
        ["kind", "text", "to"],
    ),
    _tool(
        "codex_director_report",
        "Report to parent",
        "Send a result, blocker, question, or finding to the spawning parent. The top-level director has no parent.",
        {
            "kind": {"type": "string", "enum": ["info", "question", "urgent", "handoff", "bug"]},
            "text": {"type": "string", "minLength": 1, "maxLength": 12000},
        },
        ["kind", "text"],
    ),
]

SPAWN_TOOL = _tool(
    "codex_director_spawn",
    "Spawn a Codex agent",
    "Launch a headless `codex exec --json` direct child from the repository root. Tasks must be self-contained. Supervisors are read-only integrators; workers default to workspace-write. No danger-full-access option is exposed.",
    {
        "name": {"type": "string", "pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "maxLength": 48},
        "task": {"type": "string", "minLength": 1, "maxLength": dl.MAX_TASK_CHARS},
        "role": {"type": "string", "enum": ["supervisor", "worker"]},
        "model": {"type": "string", "minLength": 1, "maxLength": 100},
        "reasoning_effort": {"type": "string", "enum": list(dl.REASONING_EFFORTS)},
        "sandbox": {"type": "string", "enum": list(dl.SANDBOXES)},
    },
    ["name", "task", "role"],
)

CONTROL_TOOLS = [
    _tool(
        "codex_director_wait",
        "Wait for child activity",
        "Wait without polling until a direct child exits, a hierarchy message arrives, or the bounded timeout expires.",
        {"seconds": {"type": "number", "minimum": 0, "maximum": 240}},
    ),
    _tool(
        "codex_director_result",
        "Read a child result",
        "Return a direct child's latest state and final Codex agent message, plus its private JSONL log path for audit.",
        {"name": {"type": "string"}},
        ["name"],
        read_only=True,
    ),
    _tool(
        "codex_director_resume",
        "Resume a Codex child",
        "Resume an exited direct child's persisted Codex thread with a bounded correction or follow-up. Keeps its model, role, and sandbox.",
        {"name": {"type": "string"}, "task": {"type": "string", "minLength": 1, "maxLength": dl.MAX_TASK_CHARS}},
        ["name", "task"],
    ),
    _tool(
        "codex_director_stop",
        "Stop a Codex child",
        "SIGTERM one running direct child only after Linux boot/start-time identity verification. Cannot stop grandchildren or unrelated PIDs.",
        {"name": {"type": "string"}},
        ["name"],
        destructive=True,
    ),
]


def available_tools():
    role = dl.current_role()
    tools = list(COMMON_TOOLS)
    if role in ("director", "supervisor"):
        tools.append(SPAWN_TOOL)
        tools.extend(CONTROL_TOOLS)
    return tools


def _fmt_time(ts):
    return time.strftime("%H:%M:%S", time.localtime(float(ts)))


def _status_text():
    dl.require_principal()
    principals = dl.get_principals()
    fleet = dl.get_fleet()
    usage = dl.cap_usage(fleet)
    lines = [
        f"Codex fleet caps: supervisors {usage['supervisor']}/{dl.MAX_SUPERVISORS}; "
        f"workers {usage['worker']}/{dl.MAX_WORKERS}",
        f"Live sessions ({len(principals)}):",
    ]
    for sid, principal in sorted(principals.items(), key=lambda item: item[1].get("started", 0)):
        you = " (you)" if sid == dl.session_id() else ""
        lines.append(
            f"  - {principal['name']}{you} [{principal['role']}]: {principal['focus']} "
            f"[since {_fmt_time(principal['started'])}]"
        )
    lines.append(f"Spawned agents ({len(fleet)}):")
    for rec in sorted(fleet.values(), key=lambda value: value.get("created_at", 0)):
        state = "RUNNING" if rec.get("running") else f"EXITED status={rec.get('exit_status')}"
        summary = rec.get("task_summary", {})
        lines.append(
            f"  - {rec['name']} [{state}] {rec['role']} {rec['model']}/{rec['reasoning_effort']} "
            f"sandbox={rec['sandbox']} parent={rec['parent_name']} generation={rec.get('generation', 1)} "
            f"task={summary.get('sha256_12', '?')}:{summary.get('chars', '?')}chars"
        )
    return "\n".join(lines)


def _record_text(prefix, rec):
    return (
        f"{prefix} '{rec['name']}' ({rec['role']}, {rec['model']}/{rec['reasoning_effort']}, "
        f"sandbox={rec['sandbox']}, pid={rec['pid']}, generation={rec.get('generation', 1)}).\n"
        f"Log: {rec['log']}"
    )


def handle_tool(name, args):
    if name == "codex_director_register":
        principal = dl.register(args["name"], args["focus"])
        return f"Registered '{principal['name']}' as {principal['role']}.\n" + _status_text()
    if name == "codex_director_status":
        return _status_text()
    if name == "codex_director_spawn":
        rec = dl.spawn(
            args["name"],
            args["task"],
            args["role"],
            model=args.get("model"),
            reasoning_effort=args.get("reasoning_effort"),
            sandbox=args.get("sandbox"),
        )
        return _record_text("Spawned", rec) + "\nUse codex_director_wait, then inspect codex_director_result."
    if name == "codex_director_inbox":
        messages = dl.read_messages()
        if not messages:
            return "No new hierarchy messages."
        return "\n".join(
            f"[{_fmt_time(msg['ts'])}] {msg['from']} ({msg['kind']}): {msg['text']}" for msg in messages
        )
    if name == "codex_director_send":
        msg = dl.send_message(args["kind"], args["text"], args["to"])
        return f"Sent [{msg['kind']}] to {msg['to']}."
    if name == "codex_director_report":
        msg = dl.report(args["kind"], args["text"])
        return f"Reported [{msg['kind']}] to {msg['to']}."
    if name == "codex_director_wait":
        activity = dl.wait_for_activity(args.get("seconds", 60))
        lines = []
        lines.extend(
            f"MESSAGE {msg['from']} ({msg['kind']}): {msg['text']}" for msg in activity["messages"]
        )
        lines.extend(
            f"EXITED {rec['name']} status={rec.get('exit_status')} log={rec['log']}" for rec in activity["exited"]
        )
        return "\n".join(lines) if lines else "No activity before timeout."
    if name == "codex_director_result":
        result = dl.result_for(args["name"])
        text = (
            f"{result['name']} [{('RUNNING' if result['running'] else 'EXITED')}] "
            f"status={result['exit_status']} generation={result['generation']} "
            f"thread={result['thread_id'] or '?'}\nLog: {result['log']}"
        )
        if result["final_message"]:
            text += "\n\nFinal message:\n" + result["final_message"]
        return text
    if name == "codex_director_resume":
        return _record_text("Resumed", dl.resume(args["name"], args["task"]))
    if name == "codex_director_stop":
        return _record_text("Sent SIGTERM to", dl.stop(args["name"]))
    raise ValueError(f"unknown or role-forbidden tool: {name}")


def main():
    dl.ensure_state()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        rid = request.get("id")
        method = request.get("method")
        if method == "initialize":
            result = {
                "protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "betterfingers-codex-director", "version": "1.0.0"},
                "instructions": INSTRUCTIONS,
            }
        elif method == "tools/list":
            result = {"tools": available_tools()}
        elif method == "tools/call":
            params = request.get("params", {})
            try:
                text = handle_tool(params.get("name"), params.get("arguments") or {})
                result = {"content": [{"type": "text", "text": text}]}
            except Exception as exc:
                result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
        elif method == "ping":
            result = {}
        elif rid is None:
            continue
        else:
            response = {
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
            print(json.dumps(response), flush=True)
            continue
        if rid is not None:
            print(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}), flush=True)


if __name__ == "__main__":
    main()
