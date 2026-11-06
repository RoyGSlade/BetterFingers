"""Round 2, item 3: the backend's credentials never sit in its environment.

Codex re-review: Linux keeps a process's INITIAL environment readable through
/proc/<pid>/environ for its whole life (os.environ.pop does not change that copy), so an
MCP server running as the same user could read the bearer token and the approval-signing
key out of the backend and forge approvals. The shell now hands them over on stdin.
"""
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import security
from backend.privacy import boot_secrets

REPO = Path(__file__).resolve().parents[1]
TOKEN = "T0ken" + "a1" * 30
KEY = "ab" * 32
LINUX = sys.platform.startswith("linux")


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("BETTERFINGERS_")}
    env["BETTERFINGERS_LAZY_STARTUP"] = "1"
    env.update(extra)
    return env


class StdinHandOffTests(unittest.TestCase):
    def tearDown(self):
        security.set_runtime_token(None)

    def _stream(self, payload):
        import io
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return io.BytesIO(data)

    def test_a_valid_payload_installs_the_token_and_the_key_in_memory_only(self):
        from backend.services import approvals
        env = {boot_secrets.FLAG: "1"}
        with patch.object(approvals, "configure") as configure:
            installed = boot_secrets.load_from_stdin(env=env, stream=self._stream({"token": TOKEN, "approval_key": KEY}), harden=False)
        self.assertTrue(installed)
        configure.assert_called_once_with(KEY)
        self.assertEqual(security.get_auth_token(), TOKEN)
        self.assertNotIn("BETTERFINGERS_AUTH_TOKEN", env)
        self.assertNotIn(boot_secrets.FLAG, env, "the flag is consumed")

    def test_without_the_flag_nothing_is_read(self):
        stream = self._stream({"token": TOKEN})
        self.assertFalse(boot_secrets.load_from_stdin(env={}, stream=stream, harden=False))
        self.assertEqual(stream.tell(), 0)
        self.assertNotEqual(security.get_auth_token(), TOKEN)

    def test_bad_payloads_install_nothing(self):
        for payload in (b"", b"not json", b"[]", b'"str"', json.dumps({"token": 5, "approval_key": []}).encode(),
                        b"x" * (boot_secrets.MAX_BYTES + 5)):
            self.assertFalse(boot_secrets.load_from_stdin(env={boot_secrets.FLAG: "1"}, stream=self._stream(payload), harden=False))
        self.assertFalse(boot_secrets.load_from_stdin(env={boot_secrets.FLAG: "1"}, stream=self._stream({"approval_key": "short"}), harden=False))

    def test_a_shell_that_never_closes_the_pipe_cannot_hang_startup(self):
        read_fd, write_fd = os.pipe()
        reader = os.fdopen(read_fd, "rb")
        try:
            with patch.object(boot_secrets, "READ_TIMEOUT_S", 0.3):
                started = time.monotonic()
                self.assertFalse(boot_secrets.load_from_stdin(env={boot_secrets.FLAG: "1"}, stream=reader, harden=False))
                self.assertLess(time.monotonic() - started, 3)
        finally:
            # Close the WRITE end first: that lets the helper thread's blocked read finish,
            # otherwise closing the reader waits on it.
            os.close(write_fd)
            reader.close()

    def test_the_environment_token_still_works_for_a_standalone_launch(self):
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "env-token"}):
            self.assertEqual(security.get_auth_token(), "env-token")
            security.set_runtime_token("memory-token")
            self.assertEqual(security.get_auth_token(), "memory-token", "the in-memory token wins")


@unittest.skipUnless(LINUX, "/proc/<pid>/environ is a Linux behaviour")
class ProcEnvironTests(unittest.TestCase):
    """The real thing: a child started the way the shell starts the backend."""

    CHILD = (
        "import json, os, sys, time\n"
        "from backend.privacy import boot_secrets as b\n"
        "ok = b.load_from_stdin(harden=%(harden)s)\n"
        "from backend.api import security\n"
        "from backend.services import approvals\n"
        "print(json.dumps({'ok': ok, 'token_ok': security.get_auth_token() == %(token)r, 'configured': approvals.is_configured(),\n"
        "  'dumpable': b.is_dumpable(), 'env_has_token': any(%(token)r in v for v in os.environ.values())}), flush=True)\n"
        "time.sleep(60)\n"
    )

    def start(self, harden):
        child = subprocess.Popen(
            [sys.executable, "-c", self.CHILD % {"harden": harden, "token": TOKEN}],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, cwd=REPO,
            env=clean_env(**{boot_secrets.FLAG: "1"}),
        )
        self.addCleanup(lambda: (child.kill(), child.wait(timeout=10)))
        child.stdin.write(json.dumps({"token": TOKEN, "approval_key": KEY}).encode())
        child.stdin.close()
        report = json.loads(child.stdout.readline())
        return child, report

    def test_the_initial_environment_of_the_backend_holds_no_key_material(self):
        child, report = self.start(harden=False)  # not hardened, so /proc/<pid>/environ is readable here
        self.assertTrue(report["ok"] and report["token_ok"] and report["configured"], report)
        self.assertFalse(report["env_has_token"])
        environ = Path(f"/proc/{child.pid}/environ").read_bytes()
        self.assertNotIn(TOKEN.encode(), environ, "bearer token found in the initial environment")
        self.assertNotIn(KEY.encode(), environ, "signing key found in the initial environment")
        self.assertNotIn(b"BETTERFINGERS_AUTH_TOKEN", environ)
        self.assertNotIn(b"BETTERFINGERS_APPROVAL_KEY", environ)

    def test_a_hardened_backend_is_not_readable_by_another_process_of_the_same_user(self):
        child, report = self.start(harden=True)
        self.assertEqual(report["dumpable"], 0)
        for name in ("environ", "mem", "maps"):
            with self.assertRaises(PermissionError, msg=name):
                Path(f"/proc/{child.pid}/{name}").read_bytes()

    def test_the_server_module_takes_the_secrets_from_stdin_and_hardens_itself(self):
        code = (
            "import json, os, time\n"
            "import server\n"
            "from backend.api import security\n"
            "from backend.privacy import boot_secrets as b\n"
            "from backend.services import approvals\n"
            "print(json.dumps({'token_ok': security.get_auth_token() == %r, 'configured': approvals.is_configured(),\n"
            "  'dumpable': b.is_dumpable(), 'env_leak': any(k.startswith('BETTERFINGERS_AUTH') or k.startswith('BETTERFINGERS_APPROVAL') for k in os.environ)}), flush=True)\n"
            "time.sleep(60)\n"
        ) % TOKEN
        child = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, cwd=REPO, env=clean_env(**{boot_secrets.FLAG: "1"}))
        self.addCleanup(lambda: (child.kill(), child.wait(timeout=10)))
        child.stdin.write(json.dumps({"token": TOKEN, "approval_key": KEY}).encode())
        child.stdin.close()
        line = b""
        while True:  # importing server prints a pygame banner first
            line = child.stdout.readline()
            if not line or line.startswith(b"{"):
                break
        self.assertTrue(line, "the server module did not start")
        report = json.loads(line)
        self.assertEqual(report, {"token_ok": True, "configured": True, "dumpable": 0, "env_leak": False})
        with self.assertRaises(PermissionError):
            Path(f"/proc/{child.pid}/environ").read_bytes()


class ShellSideContractTests(unittest.TestCase):
    def test_the_shell_does_not_put_credentials_in_the_backend_environment(self):
        source = (REPO / "app" / "src" / "main" / "sidecar.js").read_text(encoding="utf-8")
        self.assertIn("BETTERFINGERS_SECRETS_STDIN", source)
        self.assertNotIn("BETTERFINGERS_APPROVAL_KEY: approvalKey", source)
        self.assertNotIn("BETTERFINGERS_AUTH_TOKEN: authToken", source)


if __name__ == "__main__":
    unittest.main()


class HardeningFailsClosedTests(unittest.TestCase):
    """Round 3, item 4 (Codex re-check 2): ``harden_process()`` could return False and the
    stdin launch carried on holding the token and the signing key in a dumpable process. Where
    hardening applies (Linux), a failure now means the secrets are NOT installed and the
    backend exits with a clear error."""

    def tearDown(self):
        security.set_runtime_token(None)

    def _stream(self, payload):
        import io
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    def test_a_failed_hardening_on_linux_installs_nothing_and_exits(self):
        from backend.services import approvals
        env = {boot_secrets.FLAG: "1"}
        stream = self._stream({"token": TOKEN, "approval_key": KEY})
        with patch.object(boot_secrets, "harden_process", return_value=False), \
             patch.object(boot_secrets.sys, "platform", "linux"), \
             patch.object(approvals, "configure") as configure, \
             self.assertRaises(SystemExit) as caught:
            boot_secrets.load_from_stdin(env=env, stream=stream)
        self.assertNotEqual(caught.exception.code, 0)
        self.assertIn("non-dumpable", str(caught.exception.code))
        configure.assert_not_called()
        self.assertNotEqual(security.get_auth_token(), TOKEN)

    def test_hardening_happens_before_any_secret_is_read(self):
        order = []
        env = {boot_secrets.FLAG: "1"}

        class Recorder:
            def read(self, n):
                order.append("read")
                return json.dumps({"token": TOKEN}).encode("utf-8")

        def harden():
            order.append("harden")
            return True

        with patch.object(boot_secrets, "harden_process", side_effect=harden), patch.object(boot_secrets.sys, "platform", "linux"):
            self.assertTrue(boot_secrets.load_from_stdin(env=env, stream=Recorder()))
        self.assertEqual(order, ["harden", "read"])

    def test_off_linux_hardening_does_not_apply_and_the_launch_proceeds(self):
        env = {boot_secrets.FLAG: "1"}
        with patch.object(boot_secrets, "harden_process", return_value=False), patch.object(boot_secrets.sys, "platform", "win32"):
            self.assertTrue(boot_secrets.load_from_stdin(env=env, stream=self._stream({"token": TOKEN})))
        self.assertEqual(security.get_auth_token(), TOKEN)

    @unittest.skipUnless(LINUX, "the non-dumpable flag is Linux-only")
    def test_the_real_server_exits_when_hardening_is_unavailable(self):
        """End to end: the backend module started as the shell starts it, with prctl made to
        fail, exits non-zero with the error and never serves."""
        code = (
            "import sys\n"
            "sys.path.insert(0, sys.argv[1])\n"
            "from backend.privacy import boot_secrets\n"
            "boot_secrets.harden_process = lambda: False  # prctl refused\n"
            "import server\n"
            "print('SERVED')\n"
        )
        payload = json.dumps({"token": TOKEN, "approval_key": KEY})
        result = subprocess.run([sys.executable, "-c", code, str(REPO)], input=payload, capture_output=True, text=True,
                                timeout=120, cwd=str(REPO), env=clean_env(BETTERFINGERS_SECRETS_STDIN="1"), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("SERVED", result.stdout)
        self.assertIn("non-dumpable", result.stderr)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
