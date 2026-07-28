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
import importlib.util, json, os, pathlib, shutil, socket, subprocess, sys, tempfile, time, urllib.request

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
    def __init__(self, ws, comm="claude", client="claude", extra_env=None):
        self.client = client
        env = dict(os.environ, COLLAB_WS_DIR=ws.dir, COLLAB_VIEWER_PORT=str(ws.port))
        if extra_env:
            env.update(extra_env)
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
    # Part 0: claim normalization (including explicit symlink policy)
    # ============================================================
    spec = importlib.util.spec_from_file_location(
        "collab_lib_normalize_test", f"{ROOT}/.claude/collab-mcp/collab_lib.py"
    )
    unit_cl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(unit_cl)
    with tempfile.TemporaryDirectory(prefix="collab-normalize-root-") as root_dir, \
            tempfile.TemporaryDirectory(prefix="collab-normalize-outside-") as outside_dir:
        unit_cl.REPO_ROOT = pathlib.Path(root_dir)
        inside = pathlib.Path(root_dir, "inside")
        inside.mkdir()
        pathlib.Path(root_dir, "inside-link").symlink_to(inside, target_is_directory=True)
        pathlib.Path(root_dir, "outside-link").symlink_to(outside_dir, target_is_directory=True)
        check("in-repo symlink aliases canonicalize",
              unit_cl.normalize("inside-link/file.py") == "inside/file.py")
        try:
            unit_cl.normalize("outside-link/file.py")
        except ValueError:
            escaped_symlink_rejected = True
        else:
            escaped_symlink_rejected = False
        check("symlink escape rejected", escaped_symlink_rejected)
        check("pseudo claim is preserved",
              unit_cl.normalize("__full-test-suite__") == "__full-test-suite__")

    # Safe session ids are hashed into fixed filename components. Explicit ids
    # with traversal/control syntax are rejected before any state path is made.
    check("session state filenames are collision-resistant and path-safe",
          unit_cl.session_state_key("env:a:b") != unit_cl.session_state_key("env:a_b")
          and "/" not in unit_cl.session_state_key("env:a:b")
          and "\\" not in unit_cl.session_state_key("env:a:b"))
    previous_sid = os.environ.get("COLLAB_SESSION_ID")
    os.environ["COLLAB_SESSION_ID"] = "../../cursor-escape"
    try:
        unit_cl.my_session_id()
    except ValueError:
        invalid_explicit_sid_rejected = True
    else:
        invalid_explicit_sid_rejected = False
    if previous_sid is None:
        os.environ.pop("COLLAB_SESSION_ID", None)
    else:
        os.environ["COLLAB_SESSION_ID"] = previous_sid
    check("explicit traversal session id rejected", invalid_explicit_sid_rejected)

    # Startup privacy migration is bounded to ROOT_WS, does not follow a
    # symlink outside it, and tightens retained legacy state.
    ws_priv = Workspace()
    priv_root = pathlib.Path(ws_priv.dir)
    legacy_room = priv_root / "rooms" / "legacy-room"
    legacy_cursor = legacy_room / "cursors"
    legacy_log_dir = priv_root / "spawn-logs"
    legacy_cursor.mkdir(parents=True)
    legacy_log_dir.mkdir()
    legacy_files = [
        priv_root / "fleet.json",
        priv_root / "spawns.json",
        priv_root / "messages.jsonl",
        legacy_cursor / "old-cursor",
        legacy_log_dir / "old.log",
    ]
    for path in legacy_files:
        path.write_text("{}")
        os.chmod(path, 0o664)
    for path in (priv_root, priv_root / "rooms", legacy_room, legacy_cursor, legacy_log_dir):
        os.chmod(path, 0o775)
    outside_priv = pathlib.Path(tempfile.mkdtemp(prefix="collab-privacy-outside-"))
    outside_file = outside_priv / "must-stay-public"
    outside_file.write_text("outside")
    os.chmod(outside_priv, 0o775)
    os.chmod(outside_file, 0o664)
    (priv_root / "outside-link").symlink_to(outside_priv, target_is_directory=True)
    PRIV = Client(ws_priv)
    check("legacy collab directories migrate to 0700",
          all((path.stat().st_mode & 0o777) == 0o700 for path in
              (priv_root, priv_root / "rooms", legacy_room, legacy_cursor, legacy_log_dir)))
    check("legacy collab files migrate to 0600",
          all((path.stat().st_mode & 0o777) == 0o600 for path in legacy_files))
    check("privacy migration never follows links outside ROOT_WS",
          (outside_priv.stat().st_mode & 0o777) == 0o775
          and (outside_file.stat().st_mode & 0o777) == 0o664)
    PRIV.stop()
    ws_priv.cleanup()
    shutil.rmtree(outside_priv, ignore_errors=True)

    # Exact cursor tokens close the hook peek/consume race in both own and
    # parent rooms: messages appended after the peek remain unread.
    race_root = tempfile.mkdtemp(prefix="collab-race-root-")
    race_room = pathlib.Path(race_root, "rooms", "sup-race-generation")
    saved_env = {key: os.environ.get(key) for key in (
        "COLLAB_ROOT_DIR", "COLLAB_WS_DIR", "COLLAB_PARENT_WS_DIR",
    )}
    os.environ["COLLAB_ROOT_DIR"] = race_root
    os.environ["COLLAB_WS_DIR"] = str(race_room)
    os.environ["COLLAB_PARENT_WS_DIR"] = race_root
    race_spec = importlib.util.spec_from_file_location(
        "collab_lib_race_test", f"{ROOT}/.claude/collab-mcp/collab_lib.py"
    )
    race_cl = importlib.util.module_from_spec(race_spec)
    race_spec.loader.exec_module(race_cl)
    for key, value in saved_env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    race_cl.my_session_id = lambda: "env:race-reader"
    race_cl.register_session("race-reader", "token regression")
    race_cl.post_message("urgent", "own-before", sender="other")
    race_cl.post_message("urgent", "parent-before", sender="other", base=race_cl.PARENT_WS)
    own_batch, own_token = race_cl.read_new_messages(mark_read=False, with_token=True)
    parent_batch, parent_token = race_cl.read_new_messages(
        mark_read=False, base=race_cl.PARENT_WS, with_token=True
    )
    race_cl.post_message("info", "own-after", sender="other")
    race_cl.post_message("info", "parent-after", sender="other", base=race_cl.PARENT_WS)
    race_cl.consume_pending(own_token, parent_token)
    own_after = race_cl.read_new_messages()
    parent_after = race_cl.read_new_messages(base=race_cl.PARENT_WS)
    check("own-room hook batch consumes through exact token",
          [m["text"] for m in own_batch] == ["own-before"]
          and [m["text"] for m in own_after] == ["own-after"])
    check("parent-room hook batch consumes through exact token",
          [m["text"] for m in parent_batch] == ["parent-before"]
          and [m["text"] for m in parent_after] == ["parent-after"])
    race_cl.my_session_id = lambda: "env:a:b"
    race_cl.stop_block_count(bump=True)
    race_cl.my_session_id = lambda: "env:a_b"
    race_cl.stop_block_count(bump=True)
    stop_files = sorted(path.name for path in race_cl.STOPSTATE.iterdir())
    check("colon and underscore session ids do not alias stop-state",
          len(stop_files) == 2 and all(name.startswith("sid-") for name in stop_files),
          str(stop_files))
    private_runtime_files = (
        list(race_cl.STOPSTATE.iterdir())
        + list((race_room / "cursors").iterdir())
        + list((pathlib.Path(race_root) / "cursors").iterdir())
    )
    check("new cursor and stop-state files are private",
          all((path.stat().st_mode & 0o777) == 0o600 for path in private_runtime_files),
          str(private_runtime_files))
    shutil.rmtree(race_root, ignore_errors=True)

    # ============================================================
    # Part 1: two simulated Claude sessions (original regression coverage)
    # ============================================================
    ws1 = Workspace()

    A = Client(ws1)
    r = A.rpc("tools/list")
    check("tools/list has 15 tools", len(r["result"]["tools"]) == 15, str(r)[:200])
    out = A.call("collab_register", {"name": "sess-a", "focus": "refactoring backend.js"})
    check("A registered", "Registered as 'sess-a'" in out, out)
    out = A.call("collab_register", {"name": "sess-a", "focus": "updated backend focus"})
    check("same session can re-register to update focus",
          "sess-a (you): updated backend focus" in out, out)
    out = A.call("collab_claim", {
        "paths": ["app/src/renderer/api/../api/backend.js"],
        "reason": "refactor",
    })
    check("A claimed backend.js", "Claimed: app/src/renderer/api/backend.js" in out, out)
    out = A.call("collab_claim", {"paths": ["__full-test-suite__"], "reason": "heavy suite"})
    check("A claimed pseudo-resource", "Claimed: __full-test-suite__" in out, out)

    B = Client(ws1)
    out = B.call("collab_register", {"name": "sess-b", "focus": "voice command tests"})
    check("B registered, sees A", "sess-a" in out, out)
    check("B distinct identity from A", "sess-b (you)" in out and "sess-a (you)" not in out, out)
    out = B.call("collab_claim", {"paths": ["app/src/renderer/api/backend.js"], "reason": "also want it"})
    check("B claim conflicts", "CONFLICTS" in out and "sess-a" in out, out)
    out = B.call("collab_claim", {
        "paths": [f"{ROOT}/app/src/renderer/api/backend.js"],
        "reason": "absolute alias",
    })
    check("absolute and relative claims conflict",
          "CONFLICTS" in out and "app/src/renderer/api/backend.js" in out, out)
    out = B.call("collab_claim", {
        "paths": ["app/src/renderer/./api/../api/backend.js"],
        "reason": "relative alias",
    })
    check("equivalent relative aliases conflict",
          "CONFLICTS" in out and "app/src/renderer/api/backend.js" in out, out)
    out = B.call("collab_claim", {"paths": ["__full-test-suite__"], "reason": "heavy suite"})
    check("pseudo-resource claims conflict repo-wide",
          "CONFLICTS" in out and "__full-test-suite__" in out, out)
    for bad_path in ("", ".", "../outside.py", "/tmp/collab-outside.py"):
        r = B.rpc("tools/call", {
            "name": "collab_claim",
            "arguments": {"paths": [bad_path], "reason": "must reject"},
        })
        check(f"dangerous claim rejected: {bad_path!r}",
              r["result"].get("isError") is True, str(r)[:240])
    out = B.call("collab_claim", {"paths": ["voice_commands.py"], "reason": "tests"})
    check("B claims free file", "Claimed: voice_commands.py" in out, out)

    DUP = Client(ws1)
    r = DUP.rpc("tools/call", {
        "name": "collab_register",
        "arguments": {"name": "sess-a", "focus": "ambiguous duplicate"},
    })
    check("duplicate live name in one room rejected",
          r["result"].get("isError") is True and "already used" in
          r["result"]["content"][0]["text"], str(r)[:240])
    for bad_name in ("Not-Kebab", "not_kebab", "a" * 49):
        r = DUP.rpc("tools/call", {
            "name": "collab_register",
            "arguments": {"name": bad_name, "focus": "invalid routing name"},
        })
        check(f"invalid session name rejected: {bad_name!r}",
              r["result"].get("isError") is True and "kebab-case" in
              r["result"]["content"][0]["text"], str(r)[:240])
    DUP.stop()

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

    CL.call("collab_claim", {
        "paths": ["move/source.py", "move/destination.py"],
        "reason": "move regression",
    })
    move_patch = (
        "*** Begin Patch\n"
        "*** Update File: move/dir/../source.py\n"
        "*** Move to: move/out/../destination.py\n"
        "@@\n-old\n+new\n"
        "*** End Patch\n"
    )
    h = CX.hook("pre_tool", {"tool_name": "apply_patch", "tool_input": {"patch": move_patch}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    move_warning = hout.get("systemMessage", "")
    check("Codex move patch checks normalized source and destination claims",
          "move/source.py claimed by" in move_warning
          and "move/destination.py claimed by" in move_warning,
          move_warning)

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

    # ============================================================
    # Part 4: hierarchy — roles, rooms, repo-global caps and claims
    # ============================================================
    ws4 = Workspace()
    fake_cli = os.path.join(SCRATCH, "fake-claude")
    fake_record = os.path.join(SCRATCH, "fake-claude-record.jsonl")
    fake_source = r'''#!/usr/bin/env python3
import json, os, sys, time
record = os.environ.get("FAKE_CLAUDE_RECORD")
if record:
    with open(record, "a") as fh:
        fh.write(json.dumps({
            "argv": sys.argv[1:],
            "env": {k: os.environ.get(k) for k in (
                "COLLAB_ROOT_DIR", "COLLAB_WS_DIR", "COLLAB_PARENT_WS_DIR",
                "COLLAB_PARENT_NAME", "COLLAB_SESSION_ID",
            )},
        }) + "\n")
if sys.argv[1:] == ["auth", "status", "--json"]:
    logged_in = os.environ.get("FAKE_CLAUDE_AUTH", "1") == "1"
    print(json.dumps({"loggedIn": logged_in, "authMethod": "fake" if logged_in else "none",
                      "apiProvider": "test"}))
    raise SystemExit(0 if logged_in else 1)
if "--permission-mode" in sys.argv:
    mode = sys.argv[sys.argv.index("--permission-mode") + 1]
    if mode not in {"acceptEdits", "auto", "bypassPermissions", "manual"}:
        print("invalid permission mode", mode)
        raise SystemExit(2)
if os.environ.get("FAKE_CLAUDE_FAIL") == "1":
    print("model startup rejected; Authorization: Bearer super-secret-token")
    raise SystemExit(37)
time.sleep(60)
'''
    open(fake_cli, "w").write(fake_source)
    os.chmod(fake_cli, 0o755)
    henv = {
        "COLLAB_CLAUDE_CLI": fake_cli,
        "COLLAB_SPAWN_HEALTHCHECK_S": "0.12",
        "FAKE_CLAUDE_RECORD": fake_record,
    }

    D = Client(ws4, extra_env=henv)
    D.call("collab_register", {"name": "director", "focus": "phase orchestration"})
    NAME_TAKEN = Client(ws4, extra_env=henv)
    NAME_TAKEN.call("collab_register", {
        "name": "reserved-worker", "focus": "live routing reservation",
    })

    tools = D.rpc("tools/list")["result"]["tools"]
    spawn_schema = next(t for t in tools if t["name"] == "collab_spawn")["inputSchema"]
    check("spawn schema has no cwd override", "cwd" not in spawn_schema["properties"])
    check("spawn schema exposes installed permission contract",
          spawn_schema["properties"]["permission_mode"]["enum"] ==
          ["taskSafe", "acceptEdits", "auto", "manual", "bypassPermissions"],
          str(spawn_schema["properties"]["permission_mode"]))
    r = D.rpc("tools/call", {
        "name": "collab_spawn",
        "arguments": {"name": "reserved-worker", "task": "must reject", "role": "worker"},
    })
    name_error = r["result"]["content"][0]["text"]
    check("worker spawn reserves live destination-room session names",
          r["result"].get("isError") is True
          and "live session in the destination room" in name_error,
          name_error)
    short_task = "objective A for dev@example.com"
    out = D.call("collab_spawn", {
        "name": "sup-a", "task": short_task, "role": "supervisor",
        "cwd": "/tmp",
    })
    check("supervisor spawns as opus with generation room",
          "claude-opus-5" in out and "rooms/sup-a-" in out, out)
    fleet = json.loads(pathlib.Path(ws4.dir, "fleet.json").read_text())
    sup_a_rec = next(rec for rec in fleet.values() if rec["name"] == "sup-a")
    sup_a_room = pathlib.Path(sup_a_rec["room"])
    check("supervisor generation room created", (sup_a_room / "cursors").is_dir())
    check("raw cwd argument cannot move spawn outside repo",
          sup_a_rec["cwd"] == ROOT, sup_a_rec["cwd"])
    check("fleet metadata omits full task",
          "task" not in sup_a_rec and short_task not in json.dumps(sup_a_rec)
          and short_task not in pathlib.Path(ws4.dir, "spawns.json").read_text()
          and short_task not in pathlib.Path(ws4.dir, "fleet.json").read_text()
          and short_task not in pathlib.Path(ws4.dir, "messages.jsonl").read_text()
          and set(sup_a_rec["task_summary"]) == {"sha256_12", "chars"},
          json.dumps(sup_a_rec))
    check("spawn metadata and log are private",
          (pathlib.Path(ws4.dir, "fleet.json").stat().st_mode & 0o777) == 0o600
          and (pathlib.Path(ws4.dir, "spawns.json").stat().st_mode & 0o777) == 0o600
          and (pathlib.Path(sup_a_rec["log"]).stat().st_mode & 0o777) == 0o600)
    records = [json.loads(line) for line in pathlib.Path(fake_record).read_text().splitlines()]
    sup_a_argv = next(r["argv"] for r in records if "-p" in r["argv"] and "sup-a" in r["argv"][1])
    check("taskSafe argv uses supported manual mode",
          sup_a_argv[sup_a_argv.index("--permission-mode") + 1] == "manual"
          and "--allow-dangerously-skip-permissions" not in sup_a_argv, str(sup_a_argv))
    allowed_arg = sup_a_argv[sup_a_argv.index("--allowedTools") + 1]
    check("taskSafe argv allows targeted pytest without global Bash",
          "Bash(python3 -m pytest *)" in allowed_arg and allowed_arg != "Bash",
          allowed_arg)
    sup_a_launch = next(r for r in records if r["argv"] == sup_a_argv)
    check("spawn env isolates identity and wires generated room",
          sup_a_launch["env"]["COLLAB_SESSION_ID"] is None
          and sup_a_launch["env"]["COLLAB_WS_DIR"] == str(sup_a_room), str(sup_a_launch))

    BAD_AUTH = Client(ws4, extra_env={**henv, "FAKE_CLAUDE_AUTH": "0"})
    BAD_AUTH.call("collab_register", {"name": "auth-checker", "focus": "auth failure seam"})
    r = BAD_AUTH.rpc("tools/call", {"name": "collab_spawn",
                                    "arguments": {"name": "auth-fail", "task": "must not start",
                                                  "role": "worker"}})
    auth_error = r["result"]["content"][0]["text"]
    check("unauthenticated preflight fails clearly",
          r["result"].get("isError") is True and "loggedIn=false" in auth_error
          and "No session or fleet record" in auth_error, auth_error)
    fleet = json.loads(pathlib.Path(ws4.dir, "fleet.json").read_text())
    check("auth failure creates no fleet record",
          not any(rec.get("name") == "auth-fail" for rec in fleet.values()), str(fleet))

    FAIL_FAST = Client(ws4, extra_env={**henv, "FAKE_CLAUDE_FAIL": "1"})
    FAIL_FAST.call("collab_register", {"name": "fail-fast", "focus": "health failure seam"})
    logs_before_failure = set(pathlib.Path(ws4.dir, "spawn-logs").glob("*.log"))
    r = FAIL_FAST.rpc("tools/call", {"name": "collab_spawn",
                                     "arguments": {"name": "instant-fail", "task": "must not persist",
                                                   "role": "worker"}})
    fail_error = r["result"]["content"][0]["text"]
    check("immediate child failure is synchronous and redacted",
          r["result"].get("isError") is True and "status 37" in fail_error
          and "super-secret-token" not in fail_error and "[redacted]" in fail_error,
          fail_error)
    fleet = json.loads(pathlib.Path(ws4.dir, "fleet.json").read_text())
    check("immediate failure creates no running or fleet record",
          not any(rec.get("name") == "instant-fail" for rec in fleet.values())
          and set(pathlib.Path(ws4.dir, "spawn-logs").glob("*.log")) == logs_before_failure,
          str(fleet))

    D.call("collab_spawn", {"name": "sup-b", "task": "objective B", "role": "supervisor"})
    r = D.rpc("tools/call", {"name": "collab_spawn",
                             "arguments": {"name": "sup-c", "task": "objective C", "role": "supervisor"}})
    t = r["result"]["content"][0]["text"]
    check("3rd supervisor blocked by opus cap", r["result"].get("isError") is True
          and "opus cap reached: 2/2" in t, t)

    # Reusing a display name must never reuse the prior private room.
    (sup_a_room / "messages.jsonl").write_text('{"text":"stale generation secret"}\n')
    D.call("collab_stop", {"name": "sup-a"})
    time.sleep(0.35)
    out = D.call("collab_spawn", {"name": "sup-a", "task": "objective A generation 2",
                                  "role": "supervisor"})
    spawns_now = json.loads(pathlib.Path(ws4.dir, "spawns.json").read_text())
    sup_a_room_2 = pathlib.Path(spawns_now["sup-a"]["room"])
    check("repeated supervisor name gets a clean unique room",
          sup_a_room_2 != sup_a_room and (sup_a_room_2 / "cursors").is_dir()
          and not (sup_a_room_2 / "messages.jsonl").exists(),
          f"old={sup_a_room} new={sup_a_room_2}")

    out = D.call("collab_spawn", {"name": "w0", "task": "task 0", "role": "worker"})
    check("worker spawns as sonnet in this room", "claude-sonnet-5" in out and "this room" in out, out)
    for i in range(1, 4):
        D.call("collab_spawn", {"name": f"w{i}", "task": f"task {i}", "role": "worker"})
    r = D.rpc("tools/call", {"name": "collab_spawn",
                             "arguments": {"name": "w4", "task": "task 4", "role": "worker"}})
    t = r["result"]["content"][0]["text"]
    check("5th worker blocked by sonnet cap", r["result"].get("isError") is True
          and "sonnet cap reached: 4/4" in t, t)

    r = D.rpc("tools/call", {"name": "collab_spawn",
                             "arguments": {"name": "x", "task": "t", "role": "boss"}})
    check("invalid role rejected", r["result"].get("isError") is True
          and "role must be one of" in r["result"]["content"][0]["text"], str(r)[:200])

    out = D.call("collab_fleet")
    check("fleet shows caps at limit", "opus 2/2" in out and "sonnet 4/4" in out, out)

    r = BAD_AUTH.rpc("tools/call", {"name": "collab_stop", "arguments": {"name": "w2"}})
    stop_error = r["result"]["content"][0]["text"]
    check("sibling session cannot stop another session's child",
          r["result"].get("isError") is True and "not authorized" in stop_error, stop_error)

    spawns_file = pathlib.Path(ws4.dir, "spawns.json")
    raw_spawns = json.loads(spawns_file.read_text())
    real_identity = raw_spawns["w2"]["process_identity"]
    raw_spawns["w2"]["process_identity"] = "different-boot:1"
    spawns_file.write_text(json.dumps(raw_spawns))
    fleet_file = pathlib.Path(ws4.dir, "fleet.json")
    raw_fleet = json.loads(fleet_file.read_text())
    w2_fleet_id = next(key for key, rec in raw_fleet.items() if rec.get("name") == "w2")
    raw_fleet[w2_fleet_id]["process_identity"] = "different-boot:1"
    fleet_file.write_text(json.dumps(raw_fleet))
    out_workers = D.call("collab_workers")
    out_fleet = D.call("collab_fleet")
    check("PID mismatch is dead for liveness and cap counting",
          "w2 [exited" in out_workers and "sonnet 3/4" in out_fleet,
          out_workers + "\n" + out_fleet)
    r = D.rpc("tools/call", {"name": "collab_stop", "arguments": {"name": "w2"}})
    mismatch_error = r["result"]["content"][0]["text"]
    check("PID identity mismatch refuses to signal",
          r["result"].get("isError") is True and "refusing to signal" in mismatch_error
          and "PID reuse" in mismatch_error, mismatch_error)
    raw_spawns["w2"]["process_identity"] = real_identity
    spawns_file.write_text(json.dumps(raw_spawns))
    raw_fleet[w2_fleet_id]["process_identity"] = real_identity
    fleet_file.write_text(json.dumps(raw_fleet))

    D.call("collab_stop", {"name": "w3"})
    time.sleep(0.5)
    out = D.call("collab_spawn", {"name": "w4", "task": "task 4", "role": "worker"})
    check("sonnet slot frees after collab_stop", "Spawned worker 'w4'" in out, out)
    D.call("collab_stop", {"name": "w4"})
    time.sleep(0.35)
    out = D.call("collab_spawn", {
        "name": "w-bypass", "task": "explicitly approved bypass test", "role": "worker",
        "permission_mode": "bypassPermissions",
    })
    check("explicit bypass call spawns", "bypassPermissions" in out, out)
    records = [json.loads(line) for line in pathlib.Path(fake_record).read_text().splitlines()]
    bypass_argv = next(r["argv"] for r in reversed(records)
                       if "-p" in r["argv"] and "w-bypass" in r["argv"][1])
    check("bypass argv requires both explicit flags",
          "--allow-dangerously-skip-permissions" in bypass_argv
          and bypass_argv[bypass_argv.index("--permission-mode") + 1] == "bypassPermissions"
          and "--allowedTools" not in bypass_argv, str(bypass_argv))

    # a live supervisor session in its own room, wired back to the director
    room = pathlib.Path(ws4.dir, "rooms", "sup-live")
    (room / "cursors").mkdir(parents=True)
    S = Client(ws4, extra_env={**henv, "COLLAB_WS_DIR": str(room), "COLLAB_ROOT_DIR": ws4.dir,
                               "COLLAB_PARENT_WS_DIR": ws4.dir, "COLLAB_PARENT_NAME": "director"})
    S.call("collab_register", {"name": "sup-live", "focus": "objective C"})
    out = S.call("collab_status")
    check("supervisor status shows parent-room wiring", "parent room wired" in out, out)
    S.call("collab_report_up", {"kind": "info", "text": "objective C underway"})
    out = D.call("collab_inbox")
    check("director receives report-up in main room", "objective C underway" in out and "sup-live" in out, out)
    D.call("collab_post", {"kind": "info", "text": "priority update for C", "to": "sup-live"})
    out = S.call("collab_check_up")
    check("supervisor check_up sees director directive", "priority update for C" in out, out)

    S.call("collab_claim", {"paths": ["shared/core.py"], "reason": "objective C"})
    out = D.call("collab_claim", {"paths": ["shared/core.py"], "reason": "director edit"})
    check("cross-room claim conflict includes supervisor route",
          "CONFLICTS" in out and "sup-live@rooms/sup-live" in out
          and "collab_report_up" in out, out)
    h = D.hook("pre_tool", {"tool_name": "Edit", "tool_input": {"file_path": "shared/core.py"}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("hook denies cross-room claimed edit",
          hout.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", str(h))

    route_room_1 = pathlib.Path(ws4.dir, "rooms", "route-one-generation")
    route_room_2 = pathlib.Path(ws4.dir, "rooms", "route-two-generation")
    WROUTE1 = Client(ws4, extra_env={
        **henv, "COLLAB_WS_DIR": str(route_room_1), "COLLAB_ROOT_DIR": ws4.dir,
        "COLLAB_PARENT_WS_DIR": str(route_room_1), "COLLAB_PARENT_NAME": "supervisor-one",
    })
    WROUTE2 = Client(ws4, extra_env={
        **henv, "COLLAB_WS_DIR": str(route_room_2), "COLLAB_ROOT_DIR": ws4.dir,
        "COLLAB_PARENT_WS_DIR": str(route_room_2), "COLLAB_PARENT_NAME": "supervisor-two",
    })
    WROUTE1.call("collab_register", {"name": "duplicate-worker", "focus": "route one"})
    WROUTE2.call("collab_register", {"name": "duplicate-worker", "focus": "route two"})
    WROUTE1.call("collab_claim", {"paths": ["shared/route-one.py"], "reason": "one"})
    WROUTE2.call("collab_claim", {"paths": ["shared/route-two.py"], "reason": "two"})
    out = D.call("collab_claim", {
        "paths": ["shared/route-one.py", "shared/route-two.py"], "reason": "route audit",
    })
    check("duplicate private-room display names have unambiguous routes",
          "duplicate-worker" in out
          and "supervisor-one@rooms/route-one-generation" in out
          and "supervisor-two@rooms/route-two-generation" in out,
          out)
    persisted_claims = json.loads(pathlib.Path(ws4.dir, "claims.json").read_text())
    route_blob = json.dumps({
        "one": persisted_claims["shared/route-one.py"]["route"],
        "two": persisted_claims["shared/route-two.py"]["route"],
    })
    check("claim routing metadata is safe and root-relative",
          ws4.dir not in route_blob
          and persisted_claims["shared/route-one.py"]["route"]["room"]
          == "rooms/route-one-generation"
          and persisted_claims["shared/route-two.py"]["route"]["room"]
          == "rooms/route-two-generation",
          route_blob)

    S.call("collab_report_up", {"kind": "handoff", "text": "objective C done, reviewed"})
    out = D.call("collab_wait", {"seconds": 5})
    check("collab_wait returns the pending handoff", "objective C done" in out, out)

    try:  # kill every fake spawned process group before cleanup
        for rec in json.loads(pathlib.Path(ws4.dir, "fleet.json").read_text()).values():
            for sig_target in (rec.get("pid", -1),):
                try:
                    os.killpg(sig_target, 15)
                except Exception:
                    try:
                        os.kill(sig_target, 15)
                    except Exception:
                        pass
    except Exception:
        pass
    D.stop(); S.stop(); BAD_AUTH.stop(); FAIL_FAST.stop(); NAME_TAKEN.stop()
    WROUTE1.stop(); WROUTE2.stop()
    ws4.cleanup()

    # ============================================================
    # Part 5: wake watcher — interrupts, Stop-blocking, keepalive
    # ============================================================
    ws5 = Workspace()
    A = Client(ws5, extra_env=henv)
    A.call("collab_register", {"name": "wake-target", "focus": "supervising"})
    B = Client(ws5)
    B.call("collab_register", {"name": "waker", "focus": "directing"})

    B.call("collab_post", {"kind": "wake", "text": "WAKE: review sup-a handoff", "to": "wake-target"})
    h = A.hook("post_tool", {"tool_name": "Bash", "tool_response": {}})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    ictx = hout.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("wake interrupts mid-work", "INTERRUPT" in ictx and "review sup-a handoff" in ictx, str(h))

    B.call("collab_post", {"kind": "wake", "text": "WAKE: still need that review", "to": "wake-target"})
    h = A.hook("stop", {"hook_event_name": "Stop"})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("wake blocks Stop", hout.get("decision") == "block"
          and "still need that review" in hout.get("reason", ""), str(h))
    h = A.hook("stop", {"hook_event_name": "Stop"})
    check("quiet Stop allowed after wake consumed", not h["out"].strip() and h["code"] == 0, str(h))

    B.call("collab_post", {"kind": "info", "text": "fyi direct", "to": "wake-target"})
    h = A.hook("stop", {"hook_event_name": "Stop"})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("direct message blocks Stop (flush semantics)", hout.get("decision") == "block"
          and "fyi direct" in hout.get("reason", ""), str(h))
    B.call("collab_post", {"kind": "info", "text": "fyi broadcast"})
    h = A.hook("stop", {"hook_event_name": "Stop"})
    check("broadcast info does not block Stop", not h["out"].strip() and h["code"] == 0, str(h))

    A.call("collab_spawn", {"name": "kid", "task": "spin"})
    h = A.hook("stop", {"hook_event_name": "Stop"})
    hout = json.loads(h["out"]) if h["out"].strip() else {}
    check("keepalive blocks while children run", hout.get("decision") == "block"
          and "KEEPALIVE" in hout.get("reason", ""), str(h))
    A.call("collab_stop", {"name": "kid"})
    time.sleep(0.5)
    h = A.hook("stop", {"hook_event_name": "Stop"})
    check("Stop allowed again after children exit", not h["out"].strip() and h["code"] == 0, str(h))

    A.stop(); B.stop()
    ws5.cleanup()


def test_collab_e2e():
    """pytest entry point — same run, reported as one test item."""
    _run()
    assert not FAILS, "FAILURES: " + ", ".join(FAILS)


if __name__ == "__main__":
    _run()
    print("\n" + ("ALL PASS" if not FAILS else f"FAILURES: {FAILS}"))
    sys.exit(1 if FAILS else 0)
