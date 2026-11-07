import json
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch


from backend.dev import mcp_client

BWRAP = staticmethod(lambda name: {"bwrap": "/usr/bin/bwrap", "setpriv": "/usr/bin/setpriv"}.get(name))
SETPRIV_ONLY = staticmethod(lambda name: "/usr/bin/setpriv" if name == "setpriv" else None)
NOTHING = staticmethod(lambda name: None)
STRICT = mcp_client.sandbox_kind() == "bubblewrap"


def _write_config(base_dir, payload):
    path = os.path.join(base_dir, "mcp_servers.json")
    with open(path, "w", encoding="utf-8") as handle:
        if isinstance(payload, str):
            handle.write(payload)
        else:
            json.dump(payload, handle)
    return path


class McpConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_missing_config_means_disabled(self):
        config = mcp_client.load_config()
        self.assertFalse(config["enabled"])
        self.assertEqual(config["mcpServers"], {})

    def test_invalid_json_is_disabled_with_error(self):
        _write_config(self.tmp.name, "{not json")
        config = mcp_client.load_config()
        self.assertFalse(config["enabled"])
        self.assertIn("config_error", config)

    def test_non_object_top_level_is_disabled_with_error(self):
        _write_config(self.tmp.name, json.dumps(["list", "not", "object"]))
        config = mcp_client.load_config()
        self.assertFalse(config["enabled"])
        self.assertIn("config_error", config)

    def test_valid_config_parses_and_defaults(self):
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {
                "good": {"command": "python3", "args": ["srv.py", 8], "env": {"K": 1}},
                "no_command": {"args": ["x"]},
                "blank_command": {"command": "   "},
            },
        })
        config = mcp_client.load_config()
        self.assertTrue(config["enabled"])
        self.assertEqual(sorted(config["mcpServers"]), ["good"])
        good = config["mcpServers"]["good"]
        self.assertEqual(good["args"], ["srv.py", "8"])
        self.assertEqual(good["env"], {"K": "1"})
        self.assertTrue(good["enabled"])

    def test_status_reports_flag_and_count(self):
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"a": {"command": "x"}}})
        report = mcp_client.status()
        self.assertTrue(report["sdk_available"])
        self.assertTrue(report["enabled"])
        self.assertEqual(report["server_count"], 1)

    def test_list_tools_gating(self):
        _write_config(self.tmp.name, {
            "enabled": False,
            "mcpServers": {"a": {"command": "x"}},
        })
        with self.assertRaises(PermissionError):
            mcp_client.list_tools("a")

        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"a": {"command": "x", "enabled": False}},
        })
        with self.assertRaises(PermissionError):
            mcp_client.list_tools("a")
        with self.assertRaises(KeyError):
            mcp_client.list_tools("missing")



# A minimal stdio MCP server using only the standard library: the sandboxed server runs on the
# SYSTEM interpreter (round 5, item 1: nothing is mounted from the home, so the test's own venv
# and its FastMCP are not in the sandbox). It answers initialize, tools/list and ping.
STDLIB_SERVER = """
import json, os, sys
TOOLS = TOOLS_JSON
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": msg["params"]["protocolVersion"], "capabilities": {"tools": {}},
                  "serverInfo": {"name": "stdlib", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""
SYSTEM_PYTHON = "/usr/bin/python3"


@unittest.skipUnless(mcp_client.sdk_available(), "mcp SDK not installed")
@unittest.skipUnless(STRICT and os.path.exists(SYSTEM_PYTHON), "the strict bubblewrap sandbox (or /usr/bin/python3) is not usable here")
class McpLiveStdioTests(unittest.TestCase):
    """Round-trip against a real stdio MCP server, started the only way an MCP server starts now:
    inside the strict bubblewrap sandbox (round 4, item 4), installed in its own folder
    ``<app data>/mcp-servers/<name>/`` (round 5, item 1). The data folder is made outside /tmp,
    which is never mounted."""

    def setUp(self):
        base = os.path.join(os.path.expanduser("~"), ".cache")
        os.makedirs(base, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=base)
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def install(self, name, tools):
        folder = os.path.join(self.tmp.name, "mcp-servers", name)
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "server.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(STDLIB_SERVER.replace("TOOLS_JSON", tools))
        return folder, path

    def configure(self, name, args, folder=None, **extra):
        entry = {"command": SYSTEM_PYTHON, "args": args, **extra}
        if folder:
            entry["install_dir"] = folder
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {name: entry}})

    def test_lists_tools_from_live_server(self):
        folder, server_path = self.install("tiny", json.dumps([{
            "name": "add", "description": "Add two integers.",
            "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}}}]))
        self.configure("tiny", [server_path], folder)
        result = mcp_client.list_tools("tiny", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        add_tool = next(t for t in result["tools"] if t["name"] == "add")
        self.assertIn("Add two integers", add_tool["description"])
        self.assertIn("properties", add_tool["input_schema"])

    def test_a_script_outside_its_folder_is_not_mounted_and_the_server_fails(self):
        """Round 5, item 1: naming a file as an argument no longer mounts it."""
        _folder, server_path = self.install("tiny", "[]")
        self.configure("tiny", [server_path])  # no install_dir: the script is not inside the sandbox
        result = mcp_client.list_tools("tiny", timeout=10.0)
        self.assertFalse(result["ok"])

    def test_connection_failure_returns_error_not_raise(self):
        self.configure("broken", ["-c", "raise SystemExit(1)"])
        result = mcp_client.list_tools("broken", timeout=10.0)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_server_child_does_not_inherit_tokens_or_provider_keys(self):
        """Phase 0 item 9 / red-team case 29: a malicious server that reads os.environ must find
        no BETTERFINGERS_* credential, no provider key, no loader variable and nothing else from
        the backend -- and it still gets its own env block. The server reports what it saw in
        its tool description (the sandbox gives it nowhere on the host to write)."""
        folder, server_path = self.install(
            "snoop", '[{"name": "noop", "description": json.dumps(sorted(os.environ)), "inputSchema": {"type": "object"}}]')
        self.configure("snoop", [server_path], folder, env={
            "SNOOP_OWN_SETTING": "1", "BETTERFINGERS_AUTH_TOKEN": "must-not-pass", "LD_PRELOAD": "/nonexistent.so"})
        secrets = {
            "BETTERFINGERS_AUTH_TOKEN": "t" * 64, "BETTERFINGERS_APPROVAL_KEY": "k" * 64,
            "ANTHROPIC_API_KEY": "sk-ant-leak-leak-leak", "OPENAI_API_KEY": "sk-" + "x" * 30,
            "GITHUB_TOKEN": "ghp_" + "y" * 30, "LLAMA_ARG_HOST": "0.0.0.0", "SOME_PASSWORD": "pw",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1/bus", "DISPLAY": ":0",
        }
        with patch.dict(os.environ, secrets):
            result = mcp_client.list_tools("snoop", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        seen = {name.upper() for name in json.loads(result["tools"][0]["description"])}
        for name in [*secrets, "LD_PRELOAD"]:
            self.assertNotIn(name, seen, f"{name} leaked into the MCP server environment")
        self.assertIn("SNOOP_OWN_SETTING", seen)
        self.assertIn("PATH", seen)


class McpListingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_servers_shows_the_configuration_in_full(self):
        """Round 4, item 4: no masked preview stands in for consent any more; the listing is what
        the owner reads, so arguments and environment values are shown exactly."""
        args = ["srv.py", "--api-key", "topsecretvalue", "--port", "8"]
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"a": {"command": "x", "args": args, "env": {"K": "v"}}}})
        row = mcp_client.list_servers()[0]
        self.assertEqual(row["args"], args)
        self.assertEqual(row["env"], {"K": "v"})
        self.assertFalse(row["network"], "the network is off unless the config says true")

    def test_listing_reports_whether_each_server_can_start_and_why_not(self):
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"a": {"command": "x"}, "b": {"command": "y", "sandbox": "off"}}})
        listed = {item["name"]: item for item in mcp_client.list_servers()}
        self.assertEqual((listed["b"]["sandbox"], listed["b"]["will_start"]), ("disabled", False))
        self.assertIn('"sandbox": "off"', listed["b"]["why"])
        if STRICT:
            self.assertEqual((listed["a"]["sandbox"], listed["a"]["will_start"], listed["a"]["why"]), ("bubblewrap", True, ""))
        else:
            self.assertEqual(listed["a"]["sandbox"], "disabled")
            self.assertIn("disabled", listed["a"]["why"])


class McpSandboxTests(unittest.TestCase):
    """Round 2, item 3 and round 4, item 4: a hostile same-user MCP executable must not be able
    to reach the backend's /proc entry, the app's data folder, the host home or the desktop."""

    SPEC = {"command": "/opt/srv/bin/srv", "args": ["--x"], "env": {}, "enabled": True, "sandbox": "auto", "network": False}

    def plan(self, spec=None, **kw):
        kw.setdefault("platform", "linux")
        kw.setdefault("which", BWRAP)
        kw.setdefault("home", "/nonexistent-home")
        kw.setdefault("environ", {})
        kw.setdefault("data_root", "/nonexistent-data")
        return mcp_client.launch_plan("srv", spec or self.SPEC, **kw)

    def test_the_profile_is_strict_and_the_command_comes_last(self):
        plan = self.plan()
        self.assertEqual((plan["command"], plan["kind"]), ("/usr/bin/bwrap", "bubblewrap"))
        args = plan["args"]
        for flag in ("--unshare-pid", "--die-with-parent", "--new-session", "--cap-drop", "--proc", "--clearenv",
                     "--unshare-net"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--") + 1:], ["/opt/srv/bin/srv", "--x"])
        self.assertIn("/opt/srv/bin", plan["binds"], "an absolute command's own folder is mounted")

    def test_home_data_and_credential_folders_are_never_mounted(self):
        # Round 5, item 1: such a request refuses the server outright instead of being dropped.
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data:
            os.makedirs(os.path.join(home, ".ssh"))
            for install_dir in (home, data, os.path.join(home, ".ssh"), os.path.join(home, ".ssh", ".."), "/"):
                with self.subTest(install_dir=install_dir), self.assertRaises(mcp_client.McpConfinementError):
                    self.plan({**self.SPEC, "install_dir": install_dir}, home=home, data_root=data)

    def test_windows_macos_and_no_bwrap_disable_mcp_with_the_reason(self):
        for platform, which, words in (
            ("win32", BWRAP, "disabled on Windows"), ("darwin", BWRAP, "disabled on macOS"),
            ("linux", SETPRIV_ONLY, "bubblewrap (bwrap) is not installed"), ("linux", NOTHING, "bubblewrap (bwrap) is not installed"),
        ):
            with self.subTest(platform=platform), self.assertRaises(mcp_client.McpConfinementError) as caught:
                self.plan(platform=platform, which=which)
            self.assertIn(words, str(caught.exception))
            self.assertIn("Nothing was started", str(caught.exception))

    def test_list_tools_refuses_before_anything_starts(self):
        with tempfile.TemporaryDirectory() as tmp, patch("backend.dev.mcp_client.get_user_data_path", return_value=tmp):
            _write_config(tmp, {"enabled": True, "mcpServers": {"srv": {"command": "/opt/srv"}}})
            with patch.object(mcp_client, "sandbox_kind", return_value="none"), \
                 patch.object(mcp_client, "sdk_available", return_value=True), \
                 patch.object(mcp_client, "_list_tools_async") as started, \
                 self.assertRaises(mcp_client.McpConfinementError):
                mcp_client.list_tools("srv")
            started.assert_not_called()

    @unittest.skipUnless(STRICT and os.path.exists("/usr/bin/python3"), "bubblewrap is not usable here")
    def test_a_confined_process_cannot_see_the_backend_the_data_folder_or_the_desktop(self):
        probe = (
            "import json, os, sys\n"
            "parent, data = int(sys.argv[1]), sys.argv[2]\n"
            "out = {'parent_visible': str(parent) in os.listdir('/proc'), 'data_visible': os.path.exists(data),\n"
            "       'pid': os.getpid(), 'nnp': open('/proc/self/status').read().count('NoNewPrivs:\\t1'),\n"
            "       'x11': os.path.exists('/tmp/.X11-unix'), 'run': os.path.exists('/run'),\n"
            "       'ifaces': sorted(l.split(':')[0].strip() for l in open('/proc/net/dev').read().splitlines()[2:])}\n"
            "try:\n    open('/usr/bin/sandbox-write-test', 'w').close(); out['wrote_system'] = True\n"
            "except OSError:\n    out['wrote_system'] = False\n"
            "print(json.dumps(out))\n"
        )
        with tempfile.TemporaryDirectory() as data:
            with open(os.path.join(data, "approval.key"), "w") as handle:
                handle.write("not-a-real-key")
            spec = {"command": "/usr/bin/python3", "args": ["-c", probe, str(os.getpid()), data],
                    "env": {}, "enabled": True, "sandbox": "auto", "network": False}
            launch = mcp_client.stdio_launch("srv", spec, data_root=data)
            result = subprocess.run([launch["command"], *launch["args"]], env=launch["env"], capture_output=True,
                                    text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertFalse(report["parent_visible"], "the backend must not exist in the server's /proc")
        self.assertFalse(report["data_visible"], "the data folder is not mounted at all")
        self.assertFalse(report["wrote_system"])
        self.assertLess(report["pid"], 10, "its own PID namespace")
        self.assertEqual(report["nnp"], 1)
        self.assertFalse(report["x11"], "no X11 socket directory")
        self.assertFalse(report["run"], "nothing under /run")
        self.assertEqual(report["ifaces"], ["lo"], "no network by default")


class McpToolsEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"srv": {"command": "/opt/srv", "sandbox": "off"}}})
        from fastapi.testclient import TestClient

        import server
        self.client = TestClient(server.app)

    def test_the_tools_endpoint_reports_a_refused_server_clearly(self):
        with patch.object(mcp_client, "sdk_available", return_value=True):
            response = self.client.get("/mcp/servers/srv/tools")
        self.assertEqual(response.status_code, 403)
        self.assertIn("never runs an MCP server outside its sandbox", response.json()["detail"])


class McpEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

        from fastapi.testclient import TestClient

        import server
        self.client = TestClient(server.app)

    def test_status_endpoint(self):
        response = self.client.get("/mcp/status")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["server_count"], 0)

    def test_servers_endpoint_lists_config(self):
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"a": {"command": "x", "args": ["1"]}},
        })
        response = self.client.get("/mcp/servers")
        self.assertEqual(response.status_code, 200)
        servers = response.json()["servers"]
        self.assertEqual([s["name"] for s in servers], ["a"])

    def test_tools_endpoint_error_mapping(self):
        response = self.client.get("/mcp/servers/nope/tools")
        self.assertEqual(response.status_code, 403)  # feature disabled

        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {}})
        response = self.client.get("/mcp/servers/nope/tools")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
