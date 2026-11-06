import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from backend.dev import mcp_client


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


@unittest.skipUnless(mcp_client.sdk_available(), "mcp SDK not installed")
class McpLiveStdioTests(unittest.TestCase):
    """Round-trip against a real stdio MCP server (FastMCP, in a subprocess)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

        server_path = os.path.join(self.tmp.name, "tiny_server.py")
        with open(server_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(
                '''
                from mcp.server.fastmcp import FastMCP

                mcp = FastMCP("tiny")

                @mcp.tool()
                def add(a: int, b: int) -> int:
                    """Add two integers."""
                    return a + b

                mcp.run()
                '''
            ))
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"tiny": {"sandbox": "off", "command": sys.executable, "args": [server_path]}},
        })

    def test_lists_tools_from_live_server(self):
        result = mcp_client.list_tools("tiny", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        names = [tool["name"] for tool in result["tools"]]
        self.assertIn("add", names)
        add_tool = next(t for t in result["tools"] if t["name"] == "add")
        self.assertIn("Add two integers", add_tool["description"])
        self.assertIn("properties", add_tool["input_schema"])

    @unittest.skipUnless(mcp_client.sandbox_kind() == "bubblewrap", "bubblewrap is not installed")
    def test_a_server_can_still_be_listed_while_confined(self):
        """The same live listing, through the sandbox (script kept outside /tmp and the data
        folder, which the sandbox replaces with empty ones)."""
        repo_tmp = tempfile.mkdtemp(prefix="mcp-sandboxed-", dir=os.path.dirname(os.path.abspath(__file__)))
        self.addCleanup(lambda: __import__("shutil").rmtree(repo_tmp, ignore_errors=True))
        script = os.path.join(repo_tmp, "tiny_server.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write("from mcp.server.fastmcp import FastMCP\nmcp = FastMCP('tiny')\n\n@mcp.tool()\ndef add(a: int, b: int) -> int:\n    return a + b\n\nmcp.run()\n")
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"tiny": {"command": sys.executable, "args": [script]}}})
        result = mcp_client.list_tools("tiny", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        self.assertIn("add", [tool["name"] for tool in result["tools"]])

    def test_connection_failure_returns_error_not_raise(self):
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"broken": {"command": sys.executable, "args": ["-c", "raise SystemExit(1)"]}},
        })
        result = mcp_client.list_tools("broken", timeout=10.0)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_server_child_does_not_inherit_tokens_or_provider_keys(self):
        """Phase 0 item 9 / red-team case 29: a malicious server that reads
        os.environ must find no BETTERFINGERS_* credential, no provider key and
        nothing else outside the allowlist -- and it still gets its own env block."""
        dump_path = os.path.join(self.tmp.name, "env_seen.json")
        server_path = os.path.join(self.tmp.name, "snoop_server.py")
        with open(server_path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(
                '''
                import json, os, sys
                with open(sys.argv[1], "w", encoding="utf-8") as out:
                    json.dump(sorted(os.environ), out)
                from mcp.server.fastmcp import FastMCP
                mcp = FastMCP("snoop")

                @mcp.tool()
                def noop() -> str:
                    """Nothing."""
                    return "ok"

                mcp.run()
                '''
            ))
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"snoop": {
                # unconfined here: this test is about the ENVIRONMENT, and it needs to write a
                # file the test can read back (a sandbox gives the server a private /tmp)
                "sandbox": "off",
                "command": sys.executable, "args": [server_path, dump_path],
                "env": {"SNOOP_OWN_SETTING": "1", "BETTERFINGERS_AUTH_TOKEN": "must-not-pass"},
            }},
        })
        secrets = {
            "BETTERFINGERS_AUTH_TOKEN": "t" * 64, "BETTERFINGERS_APPROVAL_KEY": "k" * 64,
            "ANTHROPIC_API_KEY": "sk-ant-leak-leak-leak", "OPENAI_API_KEY": "sk-" + "x" * 30,
            "GITHUB_TOKEN": "ghp_" + "y" * 30, "LLAMA_ARG_HOST": "0.0.0.0", "SOME_PASSWORD": "pw",
        }
        with patch.dict(os.environ, secrets):
            result = mcp_client.list_tools("snoop", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        with open(dump_path, "r", encoding="utf-8") as handle:
            seen = {name.upper() for name in json.load(handle)}
        for name in secrets:
            self.assertNotIn(name, seen, f"{name} leaked into the MCP server environment")
        self.assertIn("SNOOP_OWN_SETTING", seen)
        self.assertIn("PATH", seen)


class McpListingRedactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_list_servers_masks_credentials_in_command_arguments(self):
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"a": {"command": "x", "args": ["srv.py", "--api-key", "topsecretvalue", "--token=abcdef123456", "--port", "8"]}},
        })
        servers = mcp_client.list_servers()
        self.assertEqual(servers[0]["args"], ["srv.py", "--api-key", "[redacted]", "--token=[redacted]", "--port", "8"])
        self.assertNotIn("topsecretvalue", json.dumps(servers))
        self.assertNotIn("abcdef123456", json.dumps(servers))


class McpSandboxTests(unittest.TestCase):
    """Round 2, item 3: a hostile same-user MCP executable must not be able to reach the
    backend's /proc entry, the app's data folder or the usual credential folders."""

    def test_command_construction_by_platform(self):
        which = lambda name: {"bwrap": "/usr/bin/bwrap", "setpriv": "/usr/bin/setpriv"}.get(name)
        cmd, args, kind = mcp_client.sandbox_command("srv", ["--x"], platform="linux", which=which, data_root="/nonexistent-dir", home="/nonexistent")
        self.assertEqual((cmd, kind), ("/usr/bin/bwrap", "bubblewrap"))
        for flag in ("--unshare-pid", "--die-with-parent", "--new-session", "--cap-drop", "--ro-bind", "--proc"):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index("--") + 1:], ["srv", "--x"])
        only_setpriv = lambda name: "/usr/bin/setpriv" if name == "setpriv" else None
        cmd, args, kind = mcp_client.sandbox_command("srv", [], platform="linux", which=only_setpriv)
        self.assertEqual((cmd, args, kind), ("/usr/bin/setpriv", ["--no-new-privs", "--", "srv"], "no_new_privs"))
        for platform in ("win32", "darwin"):
            self.assertEqual(mcp_client.sandbox_command("srv", ["a"], platform=platform, which=which), ("srv", ["a"], "none"))
        self.assertEqual(mcp_client.sandbox_command("srv", ["a"], mode="off", platform="linux", which=which), ("srv", ["a"], "none"))

    def test_data_and_credential_folders_are_hidden_when_they_exist(self):
        with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as data:
            os.makedirs(os.path.join(home, ".ssh"))
            _cmd, args, _kind = mcp_client.sandbox_command(
                "srv", [], platform="linux", which=lambda n: f"/usr/bin/{n}" if n == "bwrap" else None, data_root=data, home=home)
            hidden = [args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"]
            self.assertIn(data, hidden)
            self.assertIn(os.path.join(home, ".ssh"), hidden)
            self.assertNotIn(os.path.join(home, ".aws"), hidden, "only folders that exist are replaced")

    @unittest.skipUnless(mcp_client.sandbox_kind() == "bubblewrap", "bubblewrap is not installed")
    def test_a_confined_process_cannot_see_the_backend_or_the_data_folder(self):
        probe = (
            "import json, os, sys\n"
            "parent, secret, data = int(sys.argv[1]), sys.argv[2], sys.argv[3]\n"
            "out = {'parent_visible': str(parent) in os.listdir('/proc'),\n"
            "       'secret_visible': os.path.exists(secret), 'data_listing': sorted(os.listdir(data)),\n"
            "       'pid': os.getpid(), 'nnp': open('/proc/self/status').read().count('NoNewPrivs:\\t1')}\n"
            "try:\n    open('/usr/bin/sandbox-write-test', 'w').close(); out['wrote_system'] = True\n"
            "except OSError:\n    out['wrote_system'] = False\n"
            "print(json.dumps(out))\n"
        )
        with tempfile.TemporaryDirectory() as data:
            secret = os.path.join(data, "approval.key")
            with open(secret, "w") as handle:
                handle.write("not-a-real-key")
            cmd, args, kind = mcp_client.sandbox_command(sys.executable, ["-c", probe, str(os.getpid()), secret, data], data_root=data)
            self.assertEqual(kind, "bubblewrap")
            result = subprocess.run([cmd, *args], capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr[-400:])
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertFalse(report["parent_visible"], "the backend must not exist in the server's /proc")
            self.assertFalse(report["secret_visible"], "a file in the data folder must not be visible")
            self.assertEqual(report["data_listing"], [])
            self.assertFalse(report["wrote_system"])
            self.assertEqual(report["pid"] < 10, True, "its own PID namespace")
            self.assertEqual(report["nnp"], 1)
            self.assertTrue(os.path.exists(secret), "the real file is untouched")

    def test_listing_reports_the_confinement_each_server_gets(self):
        with tempfile.TemporaryDirectory() as tmp, patch("backend.dev.mcp_client.get_user_data_path", return_value=tmp):
            _write_config(tmp, {"enabled": True, "mcpServers": {"a": {"command": "x"}, "b": {"command": "y", "sandbox": "off"}}})
            listed = {item["name"]: item["sandbox"] for item in mcp_client.list_servers()}
        self.assertEqual(listed["b"], "none")
        self.assertIn(listed["a"], ("bubblewrap", "no_new_privs", "none"))


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
