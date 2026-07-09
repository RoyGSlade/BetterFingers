import json
import os
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import mcp_client


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
        patcher = patch("mcp_client.get_user_data_path", return_value=self.tmp.name)
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
        patcher = patch("mcp_client.get_user_data_path", return_value=self.tmp.name)
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
            "mcpServers": {"tiny": {"command": sys.executable, "args": [server_path]}},
        })

    def test_lists_tools_from_live_server(self):
        result = mcp_client.list_tools("tiny", timeout=30.0)
        self.assertTrue(result["ok"], result.get("error"))
        names = [tool["name"] for tool in result["tools"]]
        self.assertIn("add", names)
        add_tool = next(t for t in result["tools"] if t["name"] == "add")
        self.assertIn("Add two integers", add_tool["description"])
        self.assertIn("properties", add_tool["input_schema"])

    def test_connection_failure_returns_error_not_raise(self):
        _write_config(self.tmp.name, {
            "enabled": True,
            "mcpServers": {"broken": {"command": sys.executable, "args": ["-c", "raise SystemExit(1)"]}},
        })
        result = mcp_client.list_tools("broken", timeout=10.0)
        self.assertFalse(result["ok"])
        self.assertIn("error", result)


class McpEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("mcp_client.get_user_data_path", return_value=self.tmp.name)
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
