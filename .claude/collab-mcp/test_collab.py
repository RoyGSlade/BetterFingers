#!/usr/bin/env python3
"""E2E test of the collab MCP server + hooks, simulating two Claude sessions."""
import json, os, pathlib, shutil, subprocess, sys, tempfile, time, urllib.request

ROOT = str(pathlib.Path(__file__).resolve().parents[2])
MCP = f"{ROOT}/.claude/collab-mcp/server.py"
HOOKS = f"{ROOT}/.claude/collab-mcp/hooks.py"
WS = f"{ROOT}/.claude/collab"
BACKUP = WS + ".test-backup"
# preserve real workspace state; restore at the end
shutil.rmtree(BACKUP, ignore_errors=True)
if os.path.exists(WS):
    shutil.move(WS, BACKUP)

FAILS = []
def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" | {detail}" if detail and not cond else ""))
    if not cond: FAILS.append(name)

WRAPPER = r'''
import json, subprocess, sys
# Acts as the fake "claude" process: spawns the MCP server as a child and runs
# hook scripts as children too. Renames itself to "claude" (comm) so
# collab_lib.my_claude_pid()'s ancestry walk resolves to THIS process instead
# of climbing to the real claude session running the test.
import ctypes
libc = ctypes.CDLL("libc.so.6", use_errno=True)
libc.prctl(15, b"claude", 0, 0, 0)  # PR_SET_NAME
mcp_path, hooks_path = sys.argv[1], sys.argv[2]
p = subprocess.Popen([sys.executable, mcp_path], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
for line in sys.stdin:
    req = json.loads(line)
    if "hook" in req:
        r = subprocess.run([sys.executable, hooks_path, req["hook"]],
                           input=json.dumps(req["payload"]), capture_output=True, text=True)
        print(json.dumps({"code": r.returncode, "out": r.stdout}), flush=True)
    else:
        p.stdin.write(line); p.stdin.flush()
        if req.get("id") is not None:
            print(p.stdout.readline(), end="", flush=True)
'''
SCRATCH = tempfile.mkdtemp(prefix="collabtest-")
WPATH = os.path.join(SCRATCH, "wrapper.py")
open(WPATH, "w").write(WRAPPER)

class Claude:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, "-u", WPATH, MCP, HOOKS],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
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
        self.p.stdin.write(json.dumps({"hook": event, "payload": payload}) + "\n")
        return json.loads(self.p.stdout.readline())
    def stop(self): self.p.kill()

# --- Session A ---
A = Claude()
r = A.rpc("tools/list")
check("tools/list has 6 tools", len(r["result"]["tools"]) == 6, str(r)[:200])
out = A.call("collab_register", {"name": "sess-a", "focus": "refactoring backend.js"})
check("A registered", "Registered as 'sess-a'" in out, out)
out = A.call("collab_claim", {"paths": ["app/src/renderer/api/backend.js"], "reason": "refactor"})
check("A claimed backend.js", "Claimed: app/src/renderer/api/backend.js" in out, out)

# --- Session B ---
B = Claude()
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
    state = json.loads(urllib.request.urlopen("http://localhost:4517/api/state", timeout=3).read())
    check("viewer API live", "sessions" in state and "messages" in state and len(state["messages"]) >= 3)
    html = urllib.request.urlopen("http://localhost:4517/", timeout=3).read().decode()
    check("viewer page serves", "Claude Collab Workspace" in html)
except Exception as e:
    check("viewer API live", False, str(e))

# session death: kill A, B's status should prune it and its claims
A.stop(); A.p.wait(); time.sleep(0.3)
out = B.call("collab_status")
check("dead session pruned", "sess-a" not in out, out)

B.stop()
# stop viewer and restore the real workspace state
try:
    vpid = int(open(f"{WS}/viewer.pid").read()); os.kill(vpid, 15)
except Exception: pass
shutil.rmtree(WS, ignore_errors=True)
if os.path.exists(BACKUP):
    shutil.move(BACKUP, WS)

print("\n" + ("ALL PASS" if not FAILS else f"FAILURES: {FAILS}"))
sys.exit(1 if FAILS else 0)
