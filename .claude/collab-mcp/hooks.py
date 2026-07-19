#!/usr/bin/env python3
"""Client-neutral collab-workspace hook dispatcher — Claude Code and Codex CLI.

Usage: hooks.py <event> [--client=claude|codex]
  event is session_start | user_prompt | pre_tool | post_tool
Hook input JSON arrives on stdin; structured output goes to stdout.

--client defaults to "claude" (unchanged from the original Claude-only
implementation, so .claude/settings.json needs no changes and existing
behavior/output shape is preserved exactly). Pass --client=codex from
.codex/hooks.json — Codex speaks a different, flat hook-output schema
({"systemMessage": ...}) instead of Claude's nested
{"hookSpecificOutput": {...}}, so the two paths share all the collab_lib
logic but format their response differently.

- session_start: heartbeat + inject current workspace status so the session
  knows who else is active before doing anything.
- user_prompt / post_tool: deliver unread messages from other sessions as
  additional context (urgent ones interrupt mid-task via post_tool).
- pre_tool (Claude Edit/Write/MultiEdit/NotebookEdit, Codex apply_patch):
  surface a claim conflict on the touched path(s).
    - Claude: hard-denies the edit (permissionDecision=deny) — unchanged
      behavior.
    - Codex: as of the current Codex CLI (verified against the live Codex
      manual), PreToolUse hooks can only attach a systemMessage — there is no
      supported field to block/deny the call. This is therefore a WARNING
      only, not an enforced block. See AGENTS.md and ACCOMPLISH.md §6 for the
      documented gap and the shell-commands-may-not-write-source-files rule
      that is the actual backstop for Codex.
"""
import json
import re
import sys
import time

import collab_lib as cl

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
PATCH_TOOLS = {"apply_patch"}

# Best-effort parse of the standard apply_patch envelope. Codex's exact
# PreToolUse payload shape for apply_patch isn't precisely documented at the
# time of writing (see HANDOFF risk notes), so instead of trusting one
# specific JSON key we scan every string value in the payload for these
# markers, which is the stable, documented apply_patch patch-body format.
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Update|Add|Delete) File: (.+)$", re.MULTILINE)


def fmt(msgs):
    return "\n".join(
        f"[{time.strftime('%H:%M:%S', time.localtime(m['ts']))}] {m['from']} ({m['kind']}): {m['text']}"
        for m in msgs
    )


def out(obj):
    print(json.dumps(obj))
    sys.exit(0)


def emit_context(event_name, ctx, client):
    """Emit an additional-context / systemMessage response in the right
    client's schema and exit 0."""
    if client == "codex":
        out({"systemMessage": ctx})
    out({"hookSpecificOutput": {"hookEventName": event_name, "additionalContext": ctx}})


def _extract_patch_paths(payload):
    """Every repo-relative path touched by an apply_patch call, however it's
    nested in the payload (see _PATCH_FILE_RE docstring above)."""
    paths = set()

    def walk(v):
        if isinstance(v, str):
            for m in _PATCH_FILE_RE.finditer(v):
                paths.add(m.group(1).strip())
        elif isinstance(v, dict):
            for vv in v.values():
                walk(vv)
        elif isinstance(v, list):
            for vv in v:
                walk(vv)

    walk(payload)
    return paths


def _touched_paths(tool, tool_input, payload):
    if tool in PATCH_TOOLS:
        return _extract_patch_paths(payload)
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    return {path} if path else set()


def main():
    event = None
    client = "claude"
    for a in sys.argv[1:]:
        if a.startswith("--client="):
            client = a.split("=", 1)[1]
        elif event is None:
            event = a
    event = event or ""

    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = {}

    sessions, _ = cl.heartbeat()

    if event == "session_start":
        if not sessions:
            sys.exit(0)
        names = ", ".join(f"{s['name']} ({s['focus']})" for s in sessions.values())
        claims = cl.get_claims()
        ctx = (
            "[collab-workspace] Other sessions may be active in this repo. "
            f"Currently registered: {names or 'none'}. "
            f"Claimed files: {', '.join(claims) if claims else 'none'}. "
            "Before editing files, register with collab_register and claim files with "
            "collab_claim (see the 'collab' skill / AGENTS.md). Check collab_inbox for messages."
        )
        emit_context("SessionStart", ctx, client)

    if event in ("user_prompt", "post_tool"):
        # Only deliver here if registered (unregistered sessions get the
        # session_start nudge instead of a firehose).
        if cl.my_session_id() not in sessions:
            sys.exit(0)
        if event == "post_tool":
            # Mid-task interrupts are for urgent traffic only; peek without
            # consuming so info/question messages still arrive at the next
            # user_prompt or inbox check.
            pending = cl.read_new_messages(mark_read=False)
            if not any(m["kind"] == "urgent" for m in pending):
                sys.exit(0)
            # deliver everything pending (not just the urgent ones) so nothing
            # is consumed silently by the cursor advance
            cl.read_new_messages(mark_read=True)
            ctx = (
                "[collab-workspace INTERRUPT] Urgent message(s) from other sessions — "
                "address before continuing:\n" + fmt(pending)
            )
            emit_context("PostToolUse", ctx, client)
        else:
            msgs = cl.read_new_messages(mark_read=True)
            if not msgs:
                sys.exit(0)
            ctx = "[collab-workspace] New messages from other sessions:\n" + fmt(msgs)
            emit_context("UserPromptSubmit", ctx, client)

    if event == "pre_tool":
        tool = payload.get("tool_name", "")
        if tool not in EDIT_TOOLS and tool not in PATCH_TOOLS:
            sys.exit(0)
        tool_input = payload.get("tool_input") or {}
        paths = _touched_paths(tool, tool_input, payload)
        if not paths:
            sys.exit(0)
        conflicts = {p: cl.claim_holder(p) for p in paths}
        conflicts = {p: h for p, h in conflicts.items() if h}
        if not conflicts:
            sys.exit(0)
        detail = "; ".join(
            f"{cl.normalize(p)} claimed by '{h['session']}' ({h['reason']})"
            for p, h in conflicts.items()
        )
        if client == "codex":
            reason = (
                f"[collab-workspace] WARNING — NOT ENFORCED: {detail}. "
                "Codex PreToolUse hooks cannot block a tool call today (no continue/deny "
                "field is supported yet), so this apply_patch is proceeding anyway. Do not "
                "apply it — coordinate via collab_post ('question' or 'urgent') or wait for "
                "the claim to release (collab_status). See AGENTS.md."
            )
            out({"systemMessage": reason})
        reason = (
            f"[collab-workspace] BLOCKED: {detail}. Do not edit. "
            f"Coordinate with them via collab_post (kind='question' or 'urgent'), "
            f"or wait for the claim to be released (collab_status to check)."
        )
        out({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        })
        sys.exit(0)

    sys.exit(0)


if __name__ == "__main__":
    main()
