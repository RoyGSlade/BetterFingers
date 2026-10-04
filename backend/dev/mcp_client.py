"""Minimal MCP client (C12, step 1): list a configured server's tools.

Configuration lives in `<userdata>/mcp_servers.json`, Claude-Desktop style:

    {
      "enabled": false,
      "mcpServers": {
        "example": {
          "command": "python3",
          "args": ["/path/to/server.py"],
          "env": {},
          "enabled": true
        }
      }
    }

The whole feature is gated by the top-level "enabled" flag (default false) and
kept fully defensive: the `mcp` SDK is imported lazily, and any failure here
must never disrupt the dictation pipeline. Tool *invocation*, llama-server
bridging, and per-persona allowlists are later C12 steps.
"""
import asyncio
import json
import logging
import os
import threading

from utils import get_user_data_path

DEFAULT_TIMEOUT_SECONDS = 15.0

_lock = threading.Lock()


def _config_path():
    return os.path.join(get_user_data_path(), "mcp_servers.json")


def sdk_available():
    try:
        import mcp  # noqa: F401
        return True
    except Exception:
        return False


def load_config():
    """Parse mcp_servers.json. Missing or invalid files mean 'disabled'."""
    path = _config_path()
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except FileNotFoundError:
        return {"enabled": False, "mcpServers": {}}
    except Exception as exc:
        logging.warning(f"mcp_client: could not parse {path}: {exc}")
        return {"enabled": False, "mcpServers": {}, "config_error": str(exc)}

    if not isinstance(raw, dict):
        return {"enabled": False, "mcpServers": {}, "config_error": "top level must be an object"}

    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    cleaned = {}
    for name, spec in servers.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("command"), str) or not spec["command"].strip():
            logging.warning(f"mcp_client: server '{name}' skipped (missing command)")
            continue
        cleaned[name] = {
            "command": spec["command"],
            "args": [str(item) for item in spec.get("args", []) if isinstance(item, (str, int, float))],
            "env": {str(k): str(v) for k, v in spec.get("env", {}).items()} if isinstance(spec.get("env"), dict) else {},
            "enabled": bool(spec.get("enabled", True)),
        }
    return {"enabled": bool(raw.get("enabled", False)), "mcpServers": cleaned}


def status():
    config = load_config()
    payload = {
        "sdk_available": sdk_available(),
        "enabled": config["enabled"],
        "config_path": _config_path(),
        "server_count": len(config["mcpServers"]),
    }
    if "config_error" in config:
        payload["config_error"] = config["config_error"]
    return payload


def list_servers():
    config = load_config()
    return [
        {
            "name": name,
            "command": spec["command"],
            "args": spec["args"],
            "enabled": spec["enabled"],
        }
        for name, spec in sorted(config["mcpServers"].items())
    ]


async def _list_tools_async(spec, timeout):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=spec["command"],
        args=spec["args"],
        env={**os.environ, **spec["env"]},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            result = await asyncio.wait_for(session.list_tools(), timeout)
    return [
        {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.inputSchema,
        }
        for tool in result.tools
    ]


def list_tools(server_name, timeout=DEFAULT_TIMEOUT_SECONDS):
    """Connect to one configured stdio server and return its tool list.

    Returns {"ok": bool, "tools": [...]} or {"ok": False, "error": str}.
    Raises KeyError if the server is not configured, PermissionError if the
    feature or the server is disabled, RuntimeError if the SDK is missing.
    """
    config = load_config()
    if not config["enabled"]:
        raise PermissionError("MCP support is disabled (set \"enabled\": true in mcp_servers.json)")
    spec = config["mcpServers"].get(server_name)
    if spec is None:
        raise KeyError(server_name)
    if not spec["enabled"]:
        raise PermissionError(f"MCP server '{server_name}' is disabled")
    if not sdk_available():
        raise RuntimeError("the 'mcp' Python SDK is not installed")

    with _lock:
        try:
            tools = asyncio.run(_list_tools_async(spec, timeout))
            return {"ok": True, "server": server_name, "tools": tools}
        except Exception as exc:
            logging.warning(f"mcp_client: listing tools on '{server_name}' failed: {exc}")
            return {"ok": False, "server": server_name, "error": str(exc)}
