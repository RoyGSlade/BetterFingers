"""Phase 0 item 4: llama-server is launched locked down, and only we can use it.

The review's finding: llama-server ran with no --api-key, the Web UI and /slots on
and an inherited environment, so any web page (or DNS rebinding) could use the GPU
model or read prompt state on 127.0.0.1:18080. These tests assert the launch
command line, the child's environment, the key plumbing and the existing-server
policy. ``test_real_llama_server_enforces_the_key`` additionally starts the real
binary against a tiny model when one is configured (see its docstring).
"""
import json
import os
import socket
import stat
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from backend.llm.llm_engine import LLMEngine
from backend.models import model_manager
from backend.services import rescue_llm_adapter


def _engine():
    engine = LLMEngine.__new__(LLMEngine)
    engine.port = 8080
    engine.api_url = "http://127.0.0.1:8080"
    engine.model_id = "gemma-4-e2b-q4"
    return engine


class _LaunchCapture:
    """Run ``_start_server`` with Popen replaced, recording what it was given."""

    def __init__(self, test, environ=None):
        self.test = test
        self.environ = environ or {}
        self.cmd = None
        self.env = None
        self.key_at_launch = None
        self.key_file_mode = None

    def run(self):
        engine = _engine()
        LLMEngine.set_admission_fn(None)
        process = Mock()
        process.pid = 4321

        def fake_popen(cmd, **kwargs):
            self.cmd = list(cmd)
            self.env = dict(kwargs.get("env") or {})
            if "--api-key-file" in cmd:
                path = cmd[cmd.index("--api-key-file") + 1]
                with open(path, encoding="utf-8") as handle:
                    self.key_at_launch = handle.read()
                self.key_file_mode = stat.S_IMODE(os.stat(path).st_mode)
                self.key_path = path
            return process

        with patch.dict(os.environ, self.environ), patch(
            "backend.llm.llm_engine.os.path.exists", return_value=True
        ), patch("backend.llm.llm_engine.get_server_path", return_value="/tmp/llama-server"), patch(
            "backend.llm.llm_engine.get_model_path", return_value="/tmp/model.gguf"
        ), patch("backend.llm.llm_engine.subprocess.Popen", side_effect=fake_popen), patch.object(
            engine, "_wait_for_server"
        ):
            engine._start_server()
        return self


class LaunchCommandTests(unittest.TestCase):
    def setUp(self):
        self._saved = (LLMEngine._api_key, LLMEngine._admission_fn, LLMEngine._ready)
        self.addCleanup(self._restore)

    def _restore(self):
        LLMEngine._api_key, LLMEngine._admission_fn, LLMEngine._ready = self._saved

    def test_command_line_locks_the_server_down(self):
        cap = _LaunchCapture(self).run()
        cmd = cap.cmd
        self.assertIsNotNone(cmd, "llama-server was never launched")
        self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
        self.assertIn("--no-webui", cmd)
        self.assertIn("--no-slots", cmd)
        self.assertIn("--api-key-file", cmd)
        for forbidden in ("--agent", "-ag", "--tools", "--webui", "--slots", "--ui", "--metrics", "--props"):
            self.assertNotIn(forbidden, cmd)

    def test_security_flags_come_after_every_tunable_flag(self):
        """llama-server honours the LAST occurrence, so nothing env-tunable or
        model-specific appended earlier may override the lock-down."""
        cap = _LaunchCapture(self, {"BETTERFINGERS_LLM_FLASH_ATTN": "on"}).run()
        cmd = cap.cmd
        for flag in ("--cache-type-k", "--flash-attn", "--batch-size"):
            self.assertLess(cmd.index(flag), cmd.index("--host"))

    def test_key_is_random_per_run_and_known_to_the_client(self):
        first = _LaunchCapture(self).run()
        key_one = LLMEngine._api_key
        second = _LaunchCapture(self).run()
        key_two = LLMEngine._api_key
        self.assertTrue(key_one and key_two)
        self.assertNotEqual(key_one, key_two)
        self.assertGreaterEqual(len(key_one), 32)
        self.assertEqual(first.key_at_launch, key_one)
        self.assertEqual(LLMEngine.api_headers(), {"Authorization": f"Bearer {key_two}"})

    def test_key_is_not_on_the_command_line_or_in_the_environment(self):
        cap = _LaunchCapture(self).run()
        key = LLMEngine._api_key
        self.assertNotIn(key, " ".join(cap.cmd))
        self.assertNotIn(key, "".join(cap.env.values()))
        self.assertNotIn("--api-key", cap.cmd)  # the file form, not the argv form

    def test_key_file_is_owner_only_while_it_exists_and_gone_afterwards(self):
        cap = _LaunchCapture(self).run()
        if os.name == "posix":
            self.assertEqual(cap.key_file_mode, 0o600)
        self.assertFalse(os.path.exists(cap.key_path), "the key file must not outlive startup")
        self.assertFalse(os.path.exists(os.path.dirname(cap.key_path)))

    def test_key_file_is_removed_even_when_startup_fails(self):
        engine = _engine()
        seen = {}

        def fake_popen(cmd, **kwargs):
            seen["path"] = cmd[cmd.index("--api-key-file") + 1]
            return Mock(pid=1)

        with patch("backend.llm.llm_engine.os.path.exists", return_value=True), patch(
            "backend.llm.llm_engine.get_server_path", return_value="/tmp/llama-server"
        ), patch("backend.llm.llm_engine.get_model_path", return_value="/tmp/m.gguf"), patch(
            "backend.llm.llm_engine.subprocess.Popen", side_effect=fake_popen
        ), patch.object(engine, "_wait_for_server", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                engine._start_server()
        self.assertFalse(os.path.exists(seen["path"]))

    def test_failed_spawn_leaves_no_key_behind(self):
        engine = _engine()
        with patch("backend.llm.llm_engine.os.path.exists", return_value=True), patch(
            "backend.llm.llm_engine.get_server_path", return_value="/tmp/llama-server"
        ), patch("backend.llm.llm_engine.get_model_path", return_value="/tmp/m.gguf"), patch(
            "backend.llm.llm_engine.subprocess.Popen", side_effect=OSError("no exec")
        ):
            engine._start_server()
        self.assertIsNone(LLMEngine._api_key)
        self.assertEqual(LLMEngine.api_headers(), {})


class ChildEnvironmentTests(unittest.TestCase):
    def test_llama_arg_variables_and_credentials_are_stripped(self):
        hostile = {
            "LLAMA_ARG_HOST": "0.0.0.0", "LLAMA_ARG_AGENT": "1", "LLAMA_ARG_TOOLS": "all",
            "LLAMA_ARG_UI": "1", "LLAMA_ARG_ENDPOINT_SLOTS": "1", "LLAMA_ARG_API_KEY_FILE": "/etc/x",
            "LLAMA_API_KEY": "someone-elses-key", "llama_arg_port": "9",
            "BETTERFINGERS_AUTH_TOKEN": "t" * 64, "BETTERFINGERS_APPROVAL_KEY": "k" * 64,
            "BETTERFINGERS_LLAMA_API_KEY": "external",
        }
        with patch.dict(os.environ, hostile):
            env = model_manager.get_llama_runtime_env("/tmp/llama/llama-server")
        for name in hostile:
            self.assertNotIn(name.upper(), {k.upper() for k in env}, name)

    def test_gpu_and_loader_variables_survive(self):
        with patch.dict(os.environ, {"CUDA_VISIBLE_DEVICES": "0", "VK_ICD_FILENAMES": "/x", "PATH": "/usr/bin"}):
            env = model_manager.get_llama_runtime_env("/tmp/llama/llama-server")
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "0")
        self.assertEqual(env["VK_ICD_FILENAMES"], "/x")
        self.assertIn("PATH", env)
        if not os.sys.platform.startswith("win"):
            self.assertTrue(env["LD_LIBRARY_PATH"].startswith("/tmp/llama"))

    def test_launch_passes_the_scrubbed_environment(self):
        with patch.dict(os.environ, {"LLAMA_ARG_HOST": "0.0.0.0", "BETTERFINGERS_AUTH_TOKEN": "t" * 64}):
            cap = _LaunchCapture(self).run()
        self.assertNotIn("LLAMA_ARG_HOST", cap.env)
        self.assertNotIn("BETTERFINGERS_AUTH_TOKEN", cap.env)


class RequestAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self._saved = LLMEngine._api_key
        self.addCleanup(setattr, LLMEngine, "_api_key", self._saved)

    def test_chat_completion_carries_the_key(self):
        LLMEngine._api_key = "run-key-123"
        engine = _engine()
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": "cleaned"}}]}
        with patch("backend.llm.llm_engine.requests.post", return_value=response) as post:
            self.assertEqual(engine._call_api("sys", "hello"), "cleaned")
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer run-key-123"})

    def test_message_rescue_adapter_carries_the_key(self):
        LLMEngine._api_key = "run-key-456"
        # A plain namespace, NOT the LLMEngine singleton: assigning attributes on
        # the singleton would leak into every later test.
        engine = SimpleNamespace(
            api_url="http://127.0.0.1:8080", ensure_ready=lambda: True, api_headers=LLMEngine.api_headers,
        )
        response = Mock()
        response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        with patch("backend.services.rescue_llm_adapter.requests.post", return_value=response) as post:
            call = rescue_llm_adapter.build_llm_call_fn(engine)
            call([{"role": "user", "content": "x"}])
        self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer run-key-456"})


class ExistingServerPolicyTests(unittest.TestCase):
    def setUp(self):
        self._saved = (LLMEngine._api_key, LLMEngine._ready, LLMEngine._owns_process, LLMEngine._process_pid)
        self.addCleanup(self._restore)

    def _restore(self):
        (LLMEngine._api_key, LLMEngine._ready, LLMEngine._owns_process, LLMEngine._process_pid) = self._saved

    def test_an_unkeyed_server_already_on_the_port_is_replaced_not_reused(self):
        engine = _engine()
        LLMEngine._ready = False
        state = {"running": True}

        def stop():
            state["running"] = False

        with patch.dict(os.environ, {}, clear=False), patch(
            "backend.llm.llm_engine.is_server_running", side_effect=lambda: state["running"]
        ), patch.object(engine, "_stop_server_on_port", side_effect=stop) as stop_mock, patch.object(
            engine, "_start_server"
        ) as start_mock, patch(
            "backend.llm.llm_engine.check_and_download_resources", return_value={"ok": True}
        ):
            os.environ.pop("BETTERFINGERS_LLAMA_API_KEY", None)
            engine._setup_server()
        stop_mock.assert_called_once()
        start_mock.assert_called_once()

    def test_a_server_that_cannot_be_stopped_is_refused_not_trusted(self):
        engine = _engine()
        LLMEngine._ready = True
        with patch(
            "backend.llm.llm_engine.is_server_running", return_value=True
        ), patch.object(engine, "_stop_server_on_port"), patch.object(engine, "_start_server") as start_mock:
            os.environ.pop("BETTERFINGERS_LLAMA_API_KEY", None)
            engine._setup_server()
        start_mock.assert_not_called()
        self.assertFalse(LLMEngine._ready)
        self.assertIn("BETTERFINGERS_LLAMA_API_KEY", LLMEngine._last_error)

    def test_an_operator_configured_external_server_is_reused_with_their_key(self):
        engine = _engine()
        LLMEngine._ready = False
        with patch.dict(os.environ, {"BETTERFINGERS_LLAMA_API_KEY": "operator-key"}), patch(
            "backend.llm.llm_engine.is_server_running", return_value=True
        ), patch("backend.llm.llm_engine._find_server_pid_on_port", return_value=77), patch.object(
            engine, "_start_server"
        ) as start_mock, patch.object(engine, "_stop_server_on_port") as stop_mock:
            engine._setup_server()
        start_mock.assert_not_called()
        stop_mock.assert_not_called()
        self.assertTrue(LLMEngine._ready)
        self.assertEqual(LLMEngine.api_headers(), {"Authorization": "Bearer operator-key"})


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(
    os.getenv("BETTERFINGERS_TEST_LLAMA_SERVER") and os.getenv("BETTERFINGERS_TEST_GGUF"),
    "set BETTERFINGERS_TEST_LLAMA_SERVER and BETTERFINGERS_TEST_GGUF (a tiny chat model) to run",
)
class RealServerTests(unittest.TestCase):
    def test_real_llama_server_enforces_the_key(self):
        """Start the REAL binary with the exact security flags the engine adds and
        probe it the way a hostile web page would. Opt-in (needs a binary and a
        model); the Phase 0 proof run records its result."""
        exe = os.environ["BETTERFINGERS_TEST_LLAMA_SERVER"]
        model = os.environ["BETTERFINGERS_TEST_GGUF"]
        port = _free_port()
        key = "k" * 40
        with tempfile.TemporaryDirectory() as tmp:
            key_file = os.path.join(tmp, "key")
            with open(key_file, "w") as handle:
                handle.write(key)
            cmd = [exe, "--model", model, "--port", str(port), "--ctx-size", "512", "--n-gpu-layers", "0",
                   "--threads", "2", "--parallel", "1", "--host", "127.0.0.1", "--no-webui", "--no-slots",
                   "--api-key-file", key_file]
            env = model_manager.get_llama_runtime_env(exe)
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env,
                                    cwd=os.path.dirname(os.path.abspath(exe)))
            try:
                base = f"http://127.0.0.1:{port}"
                deadline = time.time() + 120
                while time.time() < deadline:
                    try:
                        if requests.get(f"{base}/health", timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    self.assertIsNone(proc.poll(), "llama-server exited during startup")
                    time.sleep(1)
                else:
                    self.fail("llama-server never became healthy")

                body = {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 4}
                self.assertEqual(requests.post(f"{base}/v1/chat/completions", json=body, timeout=30).status_code, 401)
                self.assertIn(requests.get(f"{base}/slots", timeout=5).status_code, (401, 404))
                self.assertIn(requests.get(f"{base}/props", timeout=5).status_code, (401, 404))
                page = requests.get(f"{base}/", timeout=5)
                self.assertNotIn("<html", page.text.lower().replace(" ", "")[:300] if page.status_code == 200 else "")
                ok = requests.post(f"{base}/v1/chat/completions", json=body, timeout=120,
                                   headers={"Authorization": f"Bearer {key}"})
                self.assertEqual(ok.status_code, 200, ok.text[:200])
                bad = requests.post(f"{base}/v1/chat/completions", json=body, timeout=30,
                                    headers={"Authorization": "Bearer wrong"})
                self.assertEqual(bad.status_code, 401)
                authed_slots = requests.get(f"{base}/slots", timeout=5, headers={"Authorization": f"Bearer {key}"})
                self.assertIn(authed_slots.status_code, (403, 404, 501), "slots must be disabled even with the key")
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=15)


if __name__ == "__main__":
    unittest.main()
