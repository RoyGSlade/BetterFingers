#!/usr/bin/env python3
"""E2E test of the collab MCP server + hooks: two simulated Claude sessions,
then one simulated Claude session and one simulated Codex session sharing
the same workspace.

Each Part runs against its own isolated temp workspace/port (via the
COLLAB_WS_DIR / COLLAB_VIEWER_PORT env overrides in collab_lib.py) — it never
touches the real .claude/collab/ directory or the real viewer's port. An
earlier version of this test swapped the real .claude/collab/ directory out
via shutil.move() for isolation; that is NOT safe when a second collab
process (another live session, or a second concurrent test run) touches the
same real path at the same time — it raced with one during development of
this test and briefly exposed stale state. See the C0.1 handoff.

Runnable two ways:
  python3 .claude/collab-mcp/test_collab.py   (prints PASS/FAIL per check,
                                                exits 1 on any failure)
  python3 -m pytest .claude/collab-mcp/test_collab.py
                                               (one test_collab_e2e() item;
                                                same checks, pytest reporting)
"""
import json, os, pathlib, shutil, socket, subprocess, sys, tempfile, time, urllib.request

ROOT = str(pathlib.Path(__file__).resolve().parents[2])
MCP = f"{ROOT}/.claude/collab-mcp/server.py"
HOOKS = f"{ROOT}/.claude/collab-mcp/hooks.py"

FAILS = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond: FAILS.append(name)

WRAPPER = r'''
import json, subprocess, sys
# Acts as the fake client process: spawns the MCP server as a child and runs
# hook scripts as children too. Renames itself to the given comm (argv[3],
# "claude" or "codex") so collab_lib.my_session_id()'s ancestry walk resolves
# to THIS process instead of climbing to the real client running the test.
# Inherits COLLAB_WS_DIR / COLLAB_VIEWER_PORT from its own environment, which
# every child spawned below (the MCP server, hook script subprocesses) also
# inherits by default, so this whole session tree stays inside the isolated
# workspace its Client was constructed with.
import ctypes
libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.prctl(15, sys.argv[3].encode(), 0, 0, 0)  # PR_SET_NAME
mcp_path, hooks_path = sys.argv[1], sys.argv[2]
p = subprocess.Popen([sys.executable, mcp_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
for line in sys.stdin:
    req = json.loads(line)
    if "hook" in req:
        args = [sys.executable, hooks_path, req["hook"]] + req.get("hook_args", [])
        r = subprocess.run(args, input=json.dumps(req["payload"]), capture_output=True, text=True)
        print(json.dumps({"code": r.returncode, "out": r.stdout}), flush=True)
    else:
        p.stdin.write(line); p.stdin.flush()
        if req.get("id") is not None:
            print(p.stdout.readline(), end="", flush=True)
'''
SCRATCH = tempfile.mkdtemp(prefix="collabtest-")
WPATH = os.path.join(SCRATCH, "wrapper.py")
open(WPATH, "w").write(WRAPPER)


def free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Workspace:
    """An isolated collab workspace (temp dir + dedicated port) for one Part
    of this test. Every Client created against it shares its state with every
    other Client on the same Workspace, and with nothing else."""
    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="collabws-")
        self.port = free_port()

    def cleanup(self):
        try:
            vpid_file = pathlib.Path(self.dir) / "viewer.pid"
            if vpid_file.exists():
                os.kill(int(vpid_file.read_text()), 15)
        except Exception:
            pass
        shutil.rmtree(self.dir, ignore_errors=True)


class Client:
    """A simulated collab session against a given Workspace. comm is the
    ancestor process name used for client-neutral identity resolution
    ('claude' or 'codex'); client picks which hook output schema hooks.py
    replies with (--client=<client>)."""
    def __init__(self, ws, comm="claude", client="claude"):
        self.client = client
        env = dict(os.environ, COLLAB_WS_DIR=ws.dir, COLLAB_VIEWER_PORT=str(ws.port))
        self.p = subprocess.Popen([sys.executable, "-u", WPATH, MCP, HOOKS, comm],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
                                  env=env)
        self.i = 0
        self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
        self.notify("notifications/initialized")
    def rpc(self, method, params=None):
        self.i += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.i, "method": method, "params": params or {}}) + "\n")
        return json.loads(self.p.stdout.readline())
    def notify(self, method):
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
    def call(self, tool, args=None):
        r = self.rpc("tools/call", {"name": tool, "arguments": args or {}})
        return r["result"]["content"][0]["text"]
    def hook(self, event, payload):
        hook_args = [f"--client={self.client}"] if self.client != "claude" else []
        self.p.stdin.write(json.dumps({"hook": event, "payload": payload, "hook_args": hook_args}) + "\n")
        return json.loads(self.p.stdout.readline())
    def stop(self): self.p.kill()


def _run():
    # ============================================================
    # Part 1: two simulated Claude sessions (original regression coverage)
    # ============================================================
    ws1 = Workspace()

    A = Client(ws1)
    r = A.rpc("tools/list")
    check("tools/list has 8 tools", len(r["result"]["tools"]) == 8, str(r)[:200])
    out = A.call("collab_register", {"name": "sess-a", "focus": "refactoring backend.js"})
    check("A registered", "Registered as 'sess-a'" in out, out)
    out = A.call("collab_claim", {"paths": ["app/src/renderer/api/backend.js"], "reason": "refactor"})
    check("A claimed backend.js", "Claimed: app/src/renderer/api/backend.js" in out, out)

    B = Client(ws1)
    out = B.call("collab_register", {"name": "sess-b", "focus": "voice command tests"})
    check("B registered, sees A", "sess-a" in out, out)
    check("B distinct identity from A", "sess-b (you)" in out and "sess-a (you)" not in out, out)
    out = B.call("collab_claim", {"paths": ["app/src/renderer/api/backend.js"], "reason": "also want it"})
    check("B claim conflicts", "CONFLICTS" in out and "sess-a" in out, out)
    out = B.call("collab_claim", {"paths": ["voice_commands.py"], "reason": "tests"})
    check("B claims free file", "Claimed: voice_commands.py" in out, out)

    # B's hook should block editing A's file
    h = B.hook("pre_tool", {"tool_name": "Edit", "tool_input": {"file_path": f"{ROOT}/app/src/renderer/api/backend.js"}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("hook denies B editing A's claim", hout.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", str(h))
    # A's own hook must NOT block its own claim (the self-block regression)
    h = A.hook("pre_tool", {"tool_name": "Edit", "tool_input": {"file_path": "app/src/renderer/api/backend.js"}})
    check("hook allows A editing own claim", not h["out"].strip() and h["code"] == 0, str(h))

    # messaging: B posts urgent, A's post_tool hook should surface it
    B.call("collab_post", {"kind": "urgent", "text": "backend.js API is changing, heads up!"})
    h = A.hook("post_tool", {"tool_name": "Bash", "tool_response": {}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    ictx = hout.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("A interrupted by urgent", "INTERRUPT" in ictx and "backend.js API is changing" in ictx, str(h))
    check("interrupt also delivers pending join msg", "sess-b joined" in ictx, ictx)
    h = A.hook("post_tool", {"tool_name": "Bash"})
    check("no duplicate interrupt", not h["out"].strip(), str(h))

    # info message goes via user_prompt, not post_tool
    B.call("collab_post", {"kind": "info", "text": "FYI voice tests green", "to": "sess-a"})
    h = A.hook("post_tool", {"tool_name": "Bash"})
    check("info does not interrupt post_tool", not h["out"].strip(), str(h))
    h = A.hook("user_prompt", {"prompt": "hi"})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("info arrives at user_prompt", "voice tests green" in hout.get("hookSpecificOutput", {}).get("additionalContext", ""), str(h))

    # everything already delivered via hooks — inbox should be clean
    out = A.call("collab_inbox")
    check("A inbox empty after hook delivery", "No new messages" in out, out)

    # release
    out = A.call("collab_release", {})
    check("A released claims", "backend.js" in out, out)
    out = B.call("collab_claim", {"paths": ["app/src/renderer/api/backend.js"], "reason": "now mine"})
    check("B can claim after release", "Claimed: app/src/renderer/api/backend.js" in out, out)

    # viewer should be running (started when B registered, since 2 sessions live)
    time.sleep(0.5)
    try:
        state = json.loads(urllib.request.urlopen(f"http://localhost:{ws1.port}/api/state", timeout=3).read())
        check("viewer API live", "sessions" in state and "messages" in state and len(state["messages"]) >= 3)
        html = urllib.request.urlopen(f"http://localhost:{ws1.port}/", timeout=3).read().decode()
        check("viewer page serves", "Claude Collab Workspace" in html)
    except Exception as e:
        check("viewer API live", False, str(e))

    # session death: kill A, B's status should prune it and its claims
    A.stop(); A.p.wait(); time.sleep(0.3)
    out = B.call("collab_status")
    check("dead session pruned", "sess-a" not in out, out)

    B.stop()
    ws1.cleanup()

    # ============================================================
    # Part 2: one simulated Claude session + one simulated Codex session
    # ============================================================
    ws2 = Workspace()

    CL = Client(ws2, comm="claude", client="claude")
    out = CL.call("collab_register", {"name": "claude-sess", "focus": "server.py extraction"})
    check("Claude session registered", "Registered as 'claude-sess'" in out, out)
    out = CL.call("collab_claim", {"paths": ["server.py"], "reason": "extraction"})
    check("Claude session claimed server.py", "Claimed: server.py" in out, out)

    CX = Client(ws2, comm="codex", client="codex")
    out = CX.call("collab_register", {"name": "codex-sess", "focus": "contracts"})
    check("Codex session registered, sees Claude session", "claude-sess" in out, out)
    check("Codex session has distinct identity", "codex-sess (you)" in out and "claude-sess (you)" not in out, out)

    # Cross-client claim visibility: Codex sees Claude's claim via collab_status
    out = CX.call("collab_status")
    check("Codex sees Claude's claim in collab_status", "server.py" in out and "claude-sess" in out, out)

    # The literal "reject one conflicting claim" requirement: Codex tries to
    # claim the same path the Claude session holds, via the client-neutral
    # collab_claim MCP tool (this path has no client-specific gap — the MCP
    # server rejects conflicting claims identically regardless of which client
    # is asking).
    out = CX.call("collab_claim", {"paths": ["server.py"], "reason": "also want it"})
    check("Codex claim on Claude's path is rejected", "CONFLICTS" in out and "claude-sess" in out, out)
    out = CX.call("collab_claim", {"paths": ["backend/services/rescue.py"], "reason": "contracts work"})
    check("Codex claims a free path", "Claimed: backend/services/rescue.py" in out, out)

    # Cross-client messaging: Codex posts urgent, Claude's post_tool hook (Claude
    # schema: nested hookSpecificOutput) surfaces it.
    CX.call("collab_post", {"kind": "urgent", "text": "server.py contract changing, heads up!"})
    h = CL.hook("post_tool", {"tool_name": "Bash", "tool_response": {}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    ictx = hout.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("Claude session sees Codex's urgent message", "INTERRUPT" in ictx and "server.py contract changing" in ictx, str(h))

    # Reverse direction: Claude posts info, Codex's user_prompt hook (Codex
    # schema: flat systemMessage) delivers it.
    CL.call("collab_post", {"kind": "info", "text": "extraction 80% done", "to": "codex-sess"})
    h = CX.hook("user_prompt", {"prompt": "status?"})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("Codex session sees Claude's info via systemMessage",
          "extraction 80% done" in hout.get("systemMessage", ""), str(h))
    check("Codex output uses flat schema, not Claude's hookSpecificOutput envelope",
          "hookSpecificOutput" not in hout, str(h))

    # Claude's PreToolUse still hard-denies a conflicting Edit (regression: the
    # cross-client work must not have weakened Claude's existing enforcement).
    h = CL.hook("pre_tool", {"tool_name": "Edit", "tool_input": {"file_path": "backend/services/rescue.py"}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("Claude session still hard-denies editing Codex's claim",
          hout.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", str(h))

    # Codex's PreToolUse for a conflicting apply_patch: per the documented Codex
    # hook capability gap (no continue/deny field supported today), this can only
    # warn, not block. Assert the warning fires and is explicitly non-enforcing —
    # do NOT assert a deny here, that would misrepresent what Codex hooks can do.
    patch_body = (
        "*** Begin Patch\n"
        "*** Update File: backend/services/rescue.py\n"
        "@@\n-old\n+new\n"
        "*** End Patch\n"
    )
    h = CX.hook("pre_tool", {"tool_name": "apply_patch", "tool_input": {"patch": patch_body}})
    check("Codex apply_patch on Codex's OWN claim is silent (no self-block)",
          not h["out"].strip() and h["code"] == 0, str(h))

    h = CX.hook("pre_tool", {"tool_name": "apply_patch", "tool_input": {"patch": patch_body.replace(
        "backend/services/rescue.py", "server.py")}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    msg = hout.get("systemMessage", "")
    check("Codex apply_patch on Claude's claim gets a WARNING", "WARNING" in msg and "server.py" in msg, str(h))
    check("Codex warning explicitly says it's not enforced", "NOT ENFORCED" in msg, msg)
    check("Codex warning is a plain systemMessage, not a deny (Codex hooks can't block)",
          "permissionDecision" not in hout, str(h))

    CL.stop(); CX.stop()
    ws2.cleanup()

    # ============================================================
    # Part 3: workspace hygiene — collab_clear / collab_backlog
    # ============================================================
    ws3 = Workspace()

    OLD = Client(ws3)
    OLD.call("collab_register", {"name": "old-sess", "focus": "generating stale history"})
    out = OLD.call("collab_backlog")
    check("backlog starts empty", "Backlog empty" in out, out)
    for i in range(5):
        OLD.call("collab_post", {"kind": "info", "text": f"stale chatter {i}"})

    NEW = Client(ws3)
    NEW.call("collab_register", {"name": "new-sess", "focus": "fresh session clearing stale room"})
    out = NEW.call("collab_clear", {"note": "phase rollover"})
    check("clear archives by default", "Cleared" in out and "archived to" in out, out)

    backlog_dir = pathlib.Path(ws3.dir) / "backlog"
    archives = sorted(backlog_dir.glob("messages-*.jsonl"))
    check("one archive file written", len(archives) == 1, str(archives))
    archived_text = archives[0].read_text() if archives else ""
    check("archive preserves the stale chatter", "stale chatter 3" in archived_text, archived_text[:200])

    # cursors were reset: the old session's next inbox read starts at the fresh
    # log, which contains only the system clear notice — no stale flood.
    out = OLD.call("collab_inbox")
    check("old session sees only the clear notice",
          "chat cleared by new-sess" in out and "stale chatter" not in out, out)
    check("clear notice records the note", "phase rollover" in out, out)

    out = NEW.call("collab_backlog")
    check("collab_backlog lists the archive", "messages-" in out and ".jsonl" in out, out)

    # discard mode: clears without adding an archive
    NEW.call("collab_post", {"kind": "info", "text": "short-lived note"})
    out = NEW.call("collab_clear", {"mode": "discard"})
    check("discard clears without archiving", "discarded" in out, out)
    check("discard adds no archive file", len(sorted(backlog_dir.glob("messages-*.jsonl"))) == 1,
          str(sorted(backlog_dir.glob("messages-*.jsonl"))))

    # bad mode is rejected in-band, not a crash
    r = NEW.rpc("tools/call", {"name": "collab_clear", "arguments": {"mode": "nuke"}})
    check("invalid clear mode rejected", r["result"].get("isError") is True
          and "archive" in r["result"]["content"][0]["text"], str(r)[:200])

    OLD.stop(); NEW.stop()
    ws3.cleanup()


def test_collab_e2e():
    """pytest entry point — same run, reported as one test item."""
    _run()
    assert not FAILS, "FAILURES: " + ", ".join(FAILS)


if __name__ == "__main__":
    _run()
    print("\n" + ("ALL PASS" if not FAILS else f"FAILURES: {FAILS}"))
    sys.exit(1 if FAILS else 0)
