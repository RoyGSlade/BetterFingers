#!/usr/bin/env python3
"""Isolated E2E coverage for the Codex director MCP.

The suite uses a fake ``codex`` executable and a temporary state root. It never
touches real authentication, sessions, collaboration state, or models.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / ".codex" / "director-mcp" / "server.py"


FAKE_CODEX = r'''#!/usr/bin/env python3
import json, os, sys, time

args = sys.argv[1:]
if args == ["login", "status"]:
    if os.environ.get("FAKE_CODEX_AUTH", "1") == "1":
        print("Logged in using ChatGPT")
        raise SystemExit(0)
    print("Not logged in; token=super-secret-token")
    raise SystemExit(1)

prompt = sys.stdin.read()
record = os.environ.get("FAKE_CODEX_RECORD")
if record:
    with open(record, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "argv": args,
            "prompt": prompt,
            "env": {key: os.environ.get(key) for key in (
                "CODEX_DIRECTOR_ROLE", "CODEX_DIRECTOR_AGENT_ID",
                "CODEX_DIRECTOR_PARENT_ID", "CODEX_DIRECTOR_SESSION_ID",
                "COLLAB_SESSION_ID",
            )},
        }) + "\n")

if os.environ.get("FAKE_CODEX_FAIL") == "1":
    print("startup failed Authorization: Bearer super-secret-token", flush=True)
    raise SystemExit(37)

is_resume = "resume" in args
thread_id = next((arg for arg in args if arg.startswith("thread-test-")), None) or "thread-test-001"
print(json.dumps({"type": "thread.started", "thread_id": thread_id}), flush=True)
print(json.dumps({"type": "turn.started"}), flush=True)
time.sleep(float(os.environ.get("FAKE_CODEX_SLEEP", "60")))
label = "resumed result" if is_resume else "reviewed handoff"
print(json.dumps({"type": "item.completed", "item": {
    "id": "answer", "type": "agent_message", "text": label,
}}), flush=True)
print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 4}}), flush=True)
'''


class Client:
    def __init__(self, state: Path, cli: Path, sid: str, role="director", agent_id=None,
                 parent_id=None, extra_env=None):
        env = dict(
            os.environ,
            CODEX_DIRECTOR_ROOT_DIR=str(state),
            CODEX_DIRECTOR_CLI=str(cli),
            CODEX_DIRECTOR_SESSION_ID=sid,
            CODEX_DIRECTOR_ROLE=role,
            CODEX_DIRECTOR_HEALTHCHECK_S="0.05",
            CODEX_DIRECTOR_SESSION_TIMEOUT_S="60",
        )
        if agent_id:
            env["CODEX_DIRECTOR_AGENT_ID"] = agent_id
        else:
            env.pop("CODEX_DIRECTOR_AGENT_ID", None)
        if parent_id:
            env["CODEX_DIRECTOR_PARENT_ID"] = parent_id
        else:
            env.pop("CODEX_DIRECTOR_PARENT_ID", None)
        if extra_env:
            env.update(extra_env)
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.index = 0
        self.rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})

    def rpc(self, method, params=None):
        self.index += 1
        request = {"jsonrpc": "2.0", "id": self.index, "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(request) + "\n")
        self.proc.stdin.flush()
        return json.loads(self.proc.stdout.readline())

    def call_raw(self, tool, args=None):
        return self.rpc("tools/call", {"name": tool, "arguments": args or {}})["result"]

    def call(self, tool, args=None):
        return self.call_raw(tool, args)["content"][0]["text"]

    def tools(self):
        return {tool["name"]: tool for tool in self.rpc("tools/list")["result"]["tools"]}

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _fleet(state: Path):
    return json.loads((state / "fleet.json").read_text())


def _record(state: Path, name: str):
    matches = [rec for rec in _fleet(state).values() if rec["name"] == name]
    return max(matches, key=lambda rec: rec["created_at"])


def _wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.03)
    return False


def _stop_record(rec):
    try:
        os.killpg(int(rec["pid"]), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def test_codex_director_e2e():
    with tempfile.TemporaryDirectory(prefix="codex-director-test-") as temp:
        temp_path = Path(temp)
        state = temp_path / "state"
        fake = temp_path / "fake-codex"
        fake.write_text(FAKE_CODEX)
        fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
        record_file = temp_path / "fake-record.jsonl"
        common_env = {"FAKE_CODEX_RECORD": str(record_file), "FAKE_CODEX_SLEEP": "60"}
        clients = []
        running_records = []
        try:
            tmp_mode = Path("/tmp").stat().st_mode & 0o777
            unsafe = subprocess.run(
                [sys.executable, str(SERVER)],
                cwd=ROOT,
                env=dict(os.environ, CODEX_DIRECTOR_ROOT_DIR="/tmp", CODEX_DIRECTOR_SESSION_ID="unsafe"),
                input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n",
                capture_output=True,
                text=True,
                timeout=3,
            )
            assert unsafe.returncode != 0 and "dedicated state subdirectory" in unsafe.stderr
            assert Path("/tmp").stat().st_mode & 0o777 == tmp_mode

            director = Client(state, fake, "director-session", extra_env=common_env)
            clients.append(director)
            init = director.rpc("initialize", {"protocolVersion": "2025-06-18"})["result"]
            assert "Register first" in init["instructions"]
            assert init["serverInfo"]["name"] == "betterfingers-codex-director"
            director_tools = director.tools()
            assert "codex_director_spawn" in director_tools
            assert director_tools["codex_director_stop"]["annotations"]["destructiveHint"] is True
            assert director_tools["codex_director_status"]["annotations"]["readOnlyHint"] is True
            sandbox_values = director_tools["codex_director_spawn"]["inputSchema"]["properties"]["sandbox"]["enum"]
            assert sandbox_values == ["read-only", "workspace-write"]

            out = director.call("codex_director_register", {
                "name": "codex-director", "focus": "orchestrate isolated test",
            })
            assert "Registered 'codex-director' as director" in out

            secret_task = "review objective for private.person@example.com without leaking it"
            out = director.call("codex_director_spawn", {
                "name": "sup-a", "task": secret_task, "role": "supervisor",
            })
            assert "Spawned 'sup-a'" in out and "gpt-5.6-sol/high" in out and "sandbox=read-only" in out
            sup_a_rec = _record(state, "sup-a")
            running_records.append(sup_a_rec)
            assert sup_a_rec["cwd"] == str(ROOT)
            assert set(sup_a_rec["task_summary"]) == {"chars", "sha256_12"}
            assert "task" not in sup_a_rec
            assert secret_task not in (state / "fleet.json").read_text()
            assert (state.stat().st_mode & 0o777) == 0o700
            assert ((state / "fleet.json").stat().st_mode & 0o777) == 0o600
            assert (Path(sup_a_rec["log"]).stat().st_mode & 0o777) == 0o600

            launches = [json.loads(line) for line in record_file.read_text().splitlines()]
            sup_launch = next(item for item in launches if item["env"]["CODEX_DIRECTOR_AGENT_ID"] == sup_a_rec["id"])
            assert "--dangerously-bypass-approvals-and-sandbox" not in sup_launch["argv"]
            assert 'approval_policy="never"' in sup_launch["argv"]
            assert "--ask-for-approval" not in sup_launch["argv"]
            assert sup_launch["argv"][0] == "exec"
            assert sup_launch["argv"][sup_launch["argv"].index("--sandbox") + 1] == "read-only"
            assert sup_launch["env"]["CODEX_DIRECTOR_ROLE"] == "supervisor"
            assert sup_launch["env"]["COLLAB_SESSION_ID"] is None
            assert secret_task in sup_launch["prompt"]
            assert "final parent handoff through codex_director_report" in sup_launch["prompt"]

            result = director.call_raw("codex_director_spawn", {
                "name": "bad-sup", "task": "must reject", "role": "supervisor",
                "sandbox": "workspace-write",
            })
            assert result.get("isError") is True and "read-only integrators" in result["content"][0]["text"]

            director.call("codex_director_spawn", {"name": "sup-b", "task": "objective b", "role": "supervisor"})
            sup_b_rec = _record(state, "sup-b")
            running_records.append(sup_b_rec)
            result = director.call_raw("codex_director_spawn", {
                "name": "sup-c", "task": "objective c", "role": "supervisor",
            })
            assert result.get("isError") is True and "supervisor cap reached: 2/2" in result["content"][0]["text"]

            supervisor = Client(
                state, fake, f"agent-{sup_a_rec['id']}", role="supervisor",
                agent_id=sup_a_rec["id"], extra_env=common_env,
            )
            clients.append(supervisor)
            assert "codex_director_spawn" in supervisor.tools()
            supervisor.call("codex_director_register", {"name": "sup-a", "focus": "review objective a"})

            director.call("codex_director_send", {
                "kind": "info", "text": "review privacy boundary", "to": "sup-a",
            })
            assert "review privacy boundary" in supervisor.call("codex_director_inbox")

            out = supervisor.call("codex_director_spawn", {
                "name": "worker-a", "task": "implement one bounded fixture", "role": "worker",
            })
            assert "gpt-5.6-terra/medium" in out and "sandbox=workspace-write" in out
            worker_rec = _record(state, "worker-a")
            running_records.append(worker_rec)
            assert worker_rec["parent_agent_id"] == sup_a_rec["id"]

            worker = Client(
                state, fake, f"agent-{worker_rec['id']}", role="worker",
                agent_id=worker_rec["id"], parent_id=sup_a_rec["id"], extra_env=common_env,
            )
            clients.append(worker)
            worker_tools = worker.tools()
            assert "codex_director_spawn" not in worker_tools
            assert "codex_director_stop" not in worker_tools
            worker.call("codex_director_register", {"name": "worker-a", "focus": "bounded fixture"})
            worker.call("codex_director_report", {"kind": "handoff", "text": "fixture reviewed and ready"})
            assert "fixture reviewed and ready" in supervisor.call("codex_director_inbox")

            outsider = Client(state, fake, "outsider-session", extra_env=common_env)
            clients.append(outsider)
            outsider.call("codex_director_register", {"name": "other-director", "focus": "authorization check"})
            result = outsider.call_raw("codex_director_stop", {"name": "sup-a"})
            assert result.get("isError") is True and "not a child spawned by this exact session" in result["content"][0]["text"]

            director.call("codex_director_stop", {"name": "sup-b"})
            assert _wait_until(lambda: not _record(state, "sup-b").get("pid") or not _pid_alive(_record(state, "sup-b")["pid"]))
            out = director.call("codex_director_spawn", {
                "name": "sup-c", "task": "objective c after slot release", "role": "supervisor",
            })
            assert "Spawned 'sup-c'" in out
            sup_c_rec = _record(state, "sup-c")
            running_records.append(sup_c_rec)

            quick = Client(
                state, fake, "quick-session", extra_env={
                    "FAKE_CODEX_RECORD": str(record_file), "FAKE_CODEX_SLEEP": "0.18",
                },
            )
            clients.append(quick)
            quick.call("codex_director_register", {"name": "quick-director", "focus": "result and resume"})
            quick.call("codex_director_spawn", {"name": "quick-worker", "task": "finish quickly", "role": "worker"})
            quick_rec = _record(state, "quick-worker")
            assert _wait_until(lambda: "reviewed handoff" in quick.call("codex_director_result", {"name": "quick-worker"}), timeout=4)
            result_text = quick.call("codex_director_result", {"name": "quick-worker"})
            assert "reviewed handoff" in result_text and "thread-test-001" in result_text
            assert "EXITED quick-worker status=0" in quick.call(
                "codex_director_wait", {"seconds": 0}
            )
            assert "No activity before timeout" in quick.call(
                "codex_director_wait", {"seconds": 0}
            )
            quick.call("codex_director_resume", {"name": "quick-worker", "task": "apply one correction"})
            assert _wait_until(lambda: "resumed result" in quick.call("codex_director_result", {"name": "quick-worker"}), timeout=4)
            resumed = quick.call("codex_director_result", {"name": "quick-worker"})
            assert "generation=2" in resumed and "resumed result" in resumed
            resume_launches = [json.loads(line) for line in record_file.read_text().splitlines()]
            assert any("resume" in item["argv"] and "thread-test-001" in item["argv"] for item in resume_launches)

            unauth = Client(
                state, fake, "unauth-session",
                extra_env={"FAKE_CODEX_AUTH": "0", "FAKE_CODEX_RECORD": str(record_file)},
            )
            clients.append(unauth)
            unauth.call("codex_director_register", {"name": "unauth-director", "focus": "auth failure"})
            before = len(_fleet(state))
            result = unauth.call_raw("codex_director_spawn", {
                "name": "auth-fail", "task": "must not start", "role": "worker",
            })
            auth_text = result["content"][0]["text"]
            assert result.get("isError") is True and "not authenticated" in auth_text
            assert "super-secret-token" not in auth_text and "[redacted]" in auth_text
            assert len(_fleet(state)) == before

            fail_fast = Client(
                state, fake, "fail-session",
                extra_env={
                    "FAKE_CODEX_FAIL": "1", "FAKE_CODEX_RECORD": str(record_file),
                    "FAKE_CODEX_SLEEP": "0",
                },
            )
            clients.append(fail_fast)
            fail_fast.call("codex_director_register", {"name": "fail-director", "focus": "startup failure"})
            result = fail_fast.call_raw("codex_director_spawn", {
                "name": "instant-fail", "task": "must not persist", "role": "worker",
            })
            fail_text = result["content"][0]["text"]
            assert result.get("isError") is True and "status 37" in fail_text
            assert "super-secret-token" not in fail_text and "[redacted]" in fail_text
            assert not any(rec["name"] == "instant-fail" for rec in _fleet(state).values())

            status_text = director.call("codex_director_status")
            assert "Codex fleet caps:" in status_text
            assert "task=" in status_text and secret_task not in status_text
        finally:
            if state.exists() and (state / "fleet.json").exists():
                running_records.extend(_fleet(state).values())
            seen = set()
            for rec in running_records:
                if rec.get("pid") in seen:
                    continue
                seen.add(rec.get("pid"))
                _stop_record(rec)
            for client in reversed(clients):
                client.close()


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return Path(f"/proc/{int(pid)}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


if __name__ == "__main__":
    test_codex_director_e2e()
    print("PASS codex director MCP E2E")
