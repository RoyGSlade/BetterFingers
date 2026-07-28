#!/usr/bin/env python3
"""Client-neutral collab-workspace hook dispatcher — Claude Code and Codex CLI.

Usage: hooks.py <event> [--client=claude|codex]
  event is session_start | user_prompt | pre_tool | post_tool | stop
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
  additional context (urgent/wake ones interrupt mid-task via post_tool).
- stop (the WAKE watcher, Claude only): when the session tries to finish,
  watch for the wake call — a pending message addressed to it, kind
  'wake'/'urgent', or text starting with 'WAKE:' — and BLOCK the stop so the
  model wakes up and handles it instead of dying. Also keeps a
  director/supervisor alive while sessions it spawned are still running
  (bounded by a quiet-block counter so an abandoned room can't spin forever).
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
_PATCH_FILE_RE = re.compile(
    r"^\*\*\* (?:(?:Update|Add|Delete) File:|Move to:) (.+)$",
    re.MULTILINE,
)


def fmt(msgs, tag=""):
    prefix = f"[{tag}] " if tag else ""
    return "\n".join(
        f"{prefix}[{time.strftime('%H:%M:%S', time.localtime(m['ts']))}] {m['from']} ({m['kind']}): {m['text']}"
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
        has_up = cl.has_parent_room()
        if event == "post_tool":
            # Mid-task interrupts are for urgent/wake traffic only; peek
            # without consuming so info/question/bug messages still arrive at
            # the next user_prompt or inbox check.
            def hot(m):
                return m["kind"] in cl.WAKE_KINDS or str(m.get("text", "")).startswith(cl.WAKE_CODE)
            pending, own_token = cl.read_new_messages(mark_read=False, with_token=True)
            if has_up:
                pending_up, parent_token = cl.read_new_messages(
                    mark_read=False, base=cl.PARENT_WS, with_token=True
                )
            else:
                pending_up, parent_token = [], None
            if not any(hot(m) for m in pending + pending_up):
                sys.exit(0)
            # deliver everything pending (not just the urgent ones) so nothing
            # is consumed silently. Advance only through the exact batches
            # copied below; later appends remain pending for the next hook.
            cl.consume_pending(own_token, parent_token)
            ctx = (
                "[collab-workspace INTERRUPT] Urgent/wake message(s) from other sessions — "
                "address before continuing:\n" + fmt(pending)
            )
            if pending_up:
                ctx += ("\n" if pending else "") + fmt(pending_up, tag="parent room")
            emit_context("PostToolUse", ctx, client)
        else:
            msgs = cl.read_new_messages(mark_read=True)
            up = cl.read_new_messages(mark_read=True, base=cl.PARENT_WS) if has_up else []
            if not msgs and not up:
                sys.exit(0)
            ctx = "[collab-workspace] New messages from other sessions:\n" + fmt(msgs)
            if up:
                ctx += ("\n" if msgs else "") + fmt(up, tag="parent room")
            emit_context("UserPromptSubmit", ctx, client)

    if event == "stop":
        # The WAKE watcher. Codex has no blockable Stop hook, and unregistered
        # sessions aren't workspace participants — leave both alone.
        if client != "claude" or cl.my_session_id() not in sessions:
            sys.exit(0)
        msgs, up, running, own_token, parent_token = cl.stop_report()
        woken = [m for m in msgs + up if cl.is_wake(m)]
        if woken:
            # Flush EVERYTHING pending (the cursor advances past it all) and
            # wake the session: it must handle these before it may finish.
            cl.consume_pending(own_token, parent_token)
            cl.stop_block_count(bump=False)
            reason = (
                "[collab-workspace WAKE] You have messages that need handling before you "
                "finish:\n" + fmt(msgs) + (("\n" + fmt(up, tag="parent room")) if up else "") +
                "\n\nAct on them now: answer questions/wakes via collab_post (or "
                "collab_report_up for the parent room), review handoffs, triage bugs. "
                "If they require no action, say why and finish."
            )
            out({"decision": "block", "reason": reason})
        if running:
            n = cl.stop_block_count(bump=True)
            if n <= 10:
                out({"decision": "block", "reason": (
                    f"[collab-workspace KEEPALIVE {n}/10] Sessions you spawned are still "
                    f"running: {', '.join(running)}. Don't finish yet — their reports come to "
                    "you. Call collab_wait (seconds=240) to sleep until one reports or exits, "
                    "then review the handoff. If a worker looks hung, read its log and "
                    "collab_stop it. After 10 quiet blocks you'll be allowed to stop."
                )})
            cl.post_message("system",
                            f"{cl.session_name()} went idle with sessions still running: {', '.join(running)}",
                            sender="workspace")
            sys.exit(0)
        cl.stop_block_count(bump=False)
        sys.exit(0)

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
            f"{cl.normalize(p)} claimed by '{h['session']}' ({h['reason']}; "
            f"{cl.describe_claim_route(h)})"
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
