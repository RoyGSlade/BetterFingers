#!/usr/bin/env python3
"""Claude Code hook dispatcher for the collab workspace.

Usage: hooks.py <event>   where event is session_start | user_prompt | pre_tool | post_tool
Hook input JSON arrives on stdin; structured output goes to stdout.

- session_start: heartbeat + inject current workspace status so the session
  knows who else is active before doing anything.
- user_prompt / post_tool: deliver unread messages from other sessions as
  additionalContext (urgent ones interrupt mid-task via post_tool).
- pre_tool (Edit/Write/MultiEdit/NotebookEdit): deny edits to files claimed by
  another live session, and surface urgent messages before the edit runs.
"""
import json
import sys
import time

import collab_lib as cl

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}


def fmt(msgs):
    return "\n".join(
        f"[{time.strftime('%H:%M:%S', time.localtime(m['ts']))}] {m['from']} ({m['kind']}): {m['text']}"
        for m in msgs
    )


def out(obj):
    print(json.dumps(obj))
    sys.exit(0)


def main():
    event = sys.argv[1] if len(sys.argv) > 1 else ""
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
            "[collab-workspace] Other Claude sessions may be active in this repo. "
            f"Currently registered: {names or 'none'}. "
            f"Claimed files: {', '.join(claims) if claims else 'none'}. "
            "Before editing files, register with collab_register and claim files with "
            "collab_claim (see the 'collab' skill). Check collab_inbox for messages."
        )
        out({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}})

    if event in ("user_prompt", "post_tool"):
        # Only deliver here if registered (unregistered sessions get the
        # session_start nudge instead of a firehose).
        if cl.my_claude_pid() not in sessions:
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
            out({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": ctx}})
        else:
            msgs = cl.read_new_messages(mark_read=True)
            if not msgs:
                sys.exit(0)
            ctx = "[collab-workspace] New messages from other sessions:\n" + fmt(msgs)
            out({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}})

    if event == "pre_tool":
        tool = payload.get("tool_name", "")
        if tool not in EDIT_TOOLS:
            sys.exit(0)
        path = (payload.get("tool_input") or {}).get("file_path") or (payload.get("tool_input") or {}).get("notebook_path")
        if not path:
            sys.exit(0)
        holder = cl.claim_holder(path)
        if holder:
            reason = (
                f"[collab-workspace] BLOCKED: {cl.normalize(path)} is claimed by session "
                f"'{holder['session']}' ({holder['reason']}). Do not edit it. "
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
