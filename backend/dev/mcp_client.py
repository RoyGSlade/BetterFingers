"""Minimal MCP client (C12, step 1): list a configured server's tools.

Configuration lives in `<userdata>/mcp_servers.json`, Claude-Desktop style:

    {
      "enabled": false,
      "mcpServers": {
        "example": {
          "command": "python3",
          "args": ["/path/to/server.py"],
          "env": {},
          "enabled": true,
          "network": true
        }
      }
    }

Every server is UNTRUSTED and runs only inside the strict bubblewrap sandbox on Linux
(see the sandbox section below). Where bubblewrap is unavailable -- Windows, macOS, or Linux
without a usable bwrap -- MCP servers are DISABLED, with a message that says why. There is no
"trusted on this machine" exception (round 4, item 4). "network": true gives a server the
network; it is off otherwise. "install_dir" names the server's own install folder, which is
mounted read-only (an absolute command's folder and absolute file arguments are mounted too).

The whole feature is gated by the top-level "enabled" flag (default false) and
kept fully defensive: the `mcp` SDK is imported lazily, and any failure here
must never disrupt the dictation pipeline. Tool *invocation*, llama-server
bridging, and per-persona allowlists are later C12 steps.
"""
import asyncio
import functools
import json
import logging
import os
import shutil
import subprocess
import sys
import threading

from backend.config.utils import get_user_data_path

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


# --- the MCP subprocess sandbox (round 2, item 3; round 3, item 4; round 4, item 4) -------------
#
# Scrubbing the environment (Phase 0 item 9) stops an MCP server INHERITING credentials; it
# does not stop a hostile same-user executable from looking for them, or from driving the
# desktop. Three layers:
#   1. the backend holds no credential in its environment (backend/privacy/boot_secrets.py),
#   2. the backend is non-dumpable on Linux, so /proc/<pid>/{environ,mem,maps} are not
#      readable by other processes of the same user (and a launch that cannot set that
#      refuses to hold its secrets at all), and
#   3. EVERY MCP SERVER RUNS ONLY INSIDE THE STRICT BUBBLEWRAP SANDBOX (``_bwrap_profile``):
#      its own PID, IPC and UTS namespaces, no new privileges, no capabilities, and a
#      filesystem made of ONLY the system runtime (/usr and the /lib*, /bin, /sbin links,
#      read-only), a handful of /etc files programs need to start, the server's own install
#      folder (read-only), an empty tmpfs home, a private /tmp, a fresh /dev and /proc. The host
#      home, the app's data folder, /run (the D-Bus buses, Wayland, PipeWire, keyrings,
#      $XDG_RUNTIME_DIR) and the X11 sockets are simply not there. The network is cut unless the
#      server's config says ``"network": true``. It dies with the backend (--die-with-parent).
#
# Round 4 (Codex re-check 3, finding 5): ``bwrap`` itself is started with a FIXED, trusted
# environment (``TRUSTED_PATH`` and nothing the server config supplied). The server's own
# ``env`` block is installed INSIDE the sandbox with ``--clearenv`` / ``--setenv``, and loader or
# runtime-injection variables (``LD_*``, ``GCONV_PATH`` and the rest of glibc's unsecure list,
# ``PATH``, ``BETTERFINGERS_*``) are refused outright: an ``LD_PRELOAD`` reaching a dynamically
# linked bwrap would run before any confinement existed.
#
# Round 4 (finding 4, director's Phase 0 policy): where that sandbox cannot be established --
# Windows, macOS, no bwrap, a bwrap that cannot create namespaces, or a config that says
# ``"sandbox": "off"`` -- MCP servers are DISABLED with a message that says why. The round 3
# "trusted on this machine" exception (persistent consent to run weaker or unconfined) is gone,
# with its storage, its route and its dialog: a one-time tap cannot make every later launch of
# an unconfined process harmless. MCP on Windows and macOS waits for a real sandbox (SECURITY.md).
#
# KNOWN LIMIT, stated plainly: with ``"network": true`` a server shares the host network
# namespace, so ABSTRACT unix sockets (for example an X server listening on "@/tmp/.X11-unix/X0")
# stay reachable. No X authority file is mounted, which defeats cookie authentication, but an X
# server configured to accept local connections without a cookie (xhost +local:) would still
# accept one. That is why the network is off by default and the listing shows the flag.

REQUIRED_CONFINEMENT = "bubblewrap"
TRUSTED_PATH = "/usr/local/bin:/usr/bin:/bin"

# The system runtime a program needs to start: read-only, and a symlink stays a symlink.
_SYSTEM_PATHS = ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/lib32", "/libx32")
# The /etc files a program needs to start (dynamic loader, users, time zone, alternatives)...
_ETC_BASE = (
    "/etc/ld.so.cache", "/etc/ld.so.conf", "/etc/ld.so.conf.d", "/etc/alternatives", "/etc/localtime",
    "/etc/nsswitch.conf", "/etc/passwd", "/etc/group",
)
# ...and, only for a server allowed the network, name resolution and the CA certificates.
_ETC_NETWORK = (
    "/etc/resolv.conf", "/etc/hosts", "/etc/host.conf", "/etc/gai.conf", "/etc/ssl", "/etc/ca-certificates",
    "/etc/pki",
)

# Never given to bwrap, and never installed inside the sandbox either: glibc's "unsecure"
# variables (ignored for setuid programs because they load code or redirect lookups), every
# LD_* variable, PATH (the sandbox's own PATH is fixed) and the app's own credentials.
_DENIED_ENV = frozenset({
    "GCONV_PATH", "GETCONF_DIR", "HOSTALIASES", "LOCALDOMAIN", "LOCPATH", "MALLOC_TRACE", "NIS_PATH",
    "NLSPATH", "RESOLV_HOST_CONF", "RES_OPTIONS", "TMPDIR", "TZDIR", "MALLOC_CHECK_", "MALLOC_PERTURB_",
    "PATH",
})
_DENIED_ENV_PREFIXES = ("LD_", "BETTERFINGERS_")


class McpConfinementError(PermissionError):
    """MCP servers cannot run here (no strict sandbox), or this one is configured to run outside
    it. The message says why and what would make it work. Nothing is ever started."""


def is_denied_env(name):
    """True for a variable that may reach neither bwrap nor the sandboxed server."""
    upper = str(name).upper()
    return upper in _DENIED_ENV or upper.startswith(_DENIED_ENV_PREFIXES)


@functools.lru_cache(maxsize=4)
def _bwrap_works(path):
    """bubblewrap can be installed and still unusable (unprivileged user namespaces off, an
    AppArmor restriction). Probe once with flags the profile needs."""
    try:
        result = subprocess.run(
            [path, "--die-with-parent", "--unshare-pid", "--unshare-net", "--clearenv",
             "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
             "--symlink", "usr/lib64", "/lib64", "--dev", "/dev", "--proc", "/proc", "--", "/usr/bin/true"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
            env={"PATH": TRUSTED_PATH},
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sandbox_kind(*, platform=None, which=shutil.which):
    """'bubblewrap' when the strict sandbox can be established here, otherwise 'none' (and MCP
    servers are disabled)."""
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return "none"
    bwrap = which("bwrap")
    # A probe only for the real lookup: tests inject ``which`` to describe a machine.
    if bwrap and (which is not shutil.which or _bwrap_works(bwrap)):
        return REQUIRED_CONFINEMENT
    return "none"


def _why_disabled(spec, *, platform, which):
    if str(spec.get("sandbox", "auto")).lower() == "off":
        return ('its configuration says "sandbox": "off", and BetterFingers never runs an MCP server outside '
                "its sandbox. Remove that setting.")
    if platform.startswith("win"):
        return ("MCP servers are disabled on Windows: BetterFingers runs them only inside a strict sandbox, "
                "and it does not have one for Windows yet.")
    if platform == "darwin":
        return ("MCP servers are disabled on macOS: BetterFingers runs them only inside a strict sandbox, "
                "and it does not have one for macOS yet.")
    if not platform.startswith("linux"):
        return "MCP servers are disabled on this operating system: BetterFingers has no strict sandbox for it."
    if not which("bwrap"):
        return ("MCP servers are disabled on this computer: they run only inside the bubblewrap sandbox, and "
                "bubblewrap (bwrap) is not installed. Install it to use MCP servers.")
    return ("MCP servers are disabled on this computer: bubblewrap is installed but cannot create a sandbox "
            "here (unprivileged user namespaces may be turned off).")


def _is_system_path(path):
    return any(path == root or path.startswith(root + os.sep) for root in _SYSTEM_PATHS)


def _contains(parent, child):
    parent, child = os.path.realpath(parent), os.path.realpath(child)
    return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)


def install_binds(spec, *, home, data_root):
    """The server's own files, mounted read-only: its ``install_dir`` folder(s), the folder of an
    absolute command outside the system runtime, and every absolute argument that names an
    existing FILE (that file only). A folder that is, or contains, the host home or the app's
    data folder is never mounted."""
    wanted = []
    configured = spec.get("install_dir")
    for item in configured if isinstance(configured, list) else [configured]:
        if isinstance(item, str) and item.strip():
            wanted.append(os.path.expanduser(item.strip()))
    command = str(spec.get("command", ""))
    if os.path.isabs(command) and not _is_system_path(command):
        wanted.append(os.path.dirname(command))
    for arg in spec.get("args", []):
        arg = str(arg)
        if os.path.isabs(arg) and os.path.isfile(arg) and not _is_system_path(arg):
            wanted.append(arg)
    out = []
    for path in wanted:
        real = os.path.realpath(path)
        if real in ("/", "") or _contains(real, home) or (data_root and _contains(real, data_root)):
            continue
        if data_root and _contains(data_root, real):
            continue
        if real not in out:
            out.append(real)
    return out


def _bwrap_profile(command, args, *, home, network, binds, env):
    wrapped = [
        "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--unshare-cgroup-try", "--cap-drop", "ALL",
    ]
    if not network:
        wrapped.append("--unshare-net")
    for path in _SYSTEM_PATHS:
        if os.path.islink(path):
            wrapped += ["--symlink", os.readlink(path), path]
        elif os.path.exists(path):
            wrapped += ["--ro-bind", path, path]
    for path in _ETC_BASE + (_ETC_NETWORK if network else ()):
        wrapped += ["--ro-bind-try", path, path]
    wrapped += ["--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--tmpfs", home]
    for path in binds:
        wrapped += ["--ro-bind-try", path, path]
    wrapped.append("--clearenv")
    for name, value in env.items():
        wrapped += ["--setenv", name, value]
    return [*wrapped, "--chdir", home, "--", command, *args]


def _inside_env(spec, *, home, environ):
    env = {"PATH": TRUSTED_PATH, "HOME": home, "TMPDIR": "/tmp"}
    for name, value in environ.items():
        upper = str(name).upper()
        if upper in ("LANG", "LANGUAGE", "TZ", "TERM") or upper.startswith("LC_"):
            env[str(name)] = str(value)
    for name, value in spec.get("env", {}).items():
        if not is_denied_env(name):
            env[str(name)] = str(value)
    return env


def launch_plan(name, spec, *, platform=None, which=shutil.which, data_root=None, home=None, environ=None):
    """How to start server ``name`` inside the strict sandbox, or ``McpConfinementError`` (with
    the reason) when MCP servers cannot run here or this one is configured to run outside it."""
    platform = sys.platform if platform is None else platform
    data_root = get_user_data_path() if data_root is None else data_root
    mode = str(spec.get("sandbox", "auto")).lower()
    if mode == "off" or sandbox_kind(platform=platform, which=which) != REQUIRED_CONFINEMENT:
        reason = _why_disabled(spec, platform=platform, which=which)
        raise McpConfinementError(f"MCP server '{name}' was not started. {reason} Nothing was started.")
    home = os.path.realpath(home or os.path.expanduser("~"))
    environ = os.environ if environ is None else environ
    network = spec.get("network") is True
    binds = install_binds(spec, home=home, data_root=data_root)
    inside = _inside_env(spec, home=home, environ=environ)
    args = _bwrap_profile(spec["command"], [str(a) for a in spec.get("args", [])], home=home,
                          network=network, binds=binds, env=inside)
    return {"command": which("bwrap"), "args": args, "kind": REQUIRED_CONFINEMENT, "network": network,
            "binds": binds}


def stdio_launch(name, spec, **kw):
    """What the stdio client starts: ``bwrap`` with its profile, and the FIXED environment the
    bwrap process itself gets (never the server's ``env`` block; that is inside the profile)."""
    plan = launch_plan(name, spec, **kw)
    return {"command": plan["command"], "args": plan["args"], "env": {"PATH": TRUSTED_PATH}, "plan": plan}


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
            "sandbox": "off" if str(spec.get("sandbox", "auto")).lower() == "off" else "auto",
            # Round 4, item 4: the network is OFF unless the config says exactly "network": true.
            "network": spec.get("network", False) is True,
        }
        install_dir = spec.get("install_dir")
        if isinstance(install_dir, str) or (isinstance(install_dir, list) and all(isinstance(i, str) for i in install_dir)):
            cleaned[name]["install_dir"] = install_dir
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
        _listing_row(name, spec)
        for name, spec in sorted(config["mcpServers"].items())
    ]


def _listing_row(name, spec):
    """Round 4, item 4: the FULL configuration -- command, every argument, every environment
    value, the network flag and the folders mounted into the sandbox. With no trust dialog there
    is no consent screen for a masked preview to stand in for; this listing is what the owner
    reads, so it hides nothing."""
    try:
        plan = launch_plan(name, spec)
        sandbox, starts, why, binds = plan["kind"], True, "", plan["binds"]
    except McpConfinementError as exc:
        sandbox, starts, why, binds = "disabled", False, str(exc), []
    return {
        "name": name,
        "command": spec["command"],
        "args": list(spec["args"]),
        "env": dict(spec["env"]),
        "enabled": spec["enabled"],
        "network": spec["network"],
        "install_dir": spec.get("install_dir"),
        "mounted_read_only": binds,
        "sandbox": sandbox,
        "will_start": starts,
        "why": why,
    }


async def _list_tools_async(launch, timeout):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # ``bwrap`` gets ONLY the fixed environment from ``stdio_launch`` (round 4, item 4). The
    # server's own variables are installed inside the sandbox by the profile; the backend's
    # environment (bearer token, approval key, provider keys) reaches neither.
    params = StdioServerParameters(command=launch["command"], args=launch["args"], env=launch["env"])
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
    feature or the server is disabled, McpConfinementError (a PermissionError)
    if the strict sandbox cannot be established here, RuntimeError if the SDK
    is missing.
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
    # Refuse BEFORE anything starts when the strict sandbox cannot be established.
    launch = stdio_launch(server_name, spec)

    with _lock:
        try:
            tools = asyncio.run(_list_tools_async(launch, timeout))
            return {"ok": True, "server": server_name, "tools": tools}
        except Exception as exc:
            logging.warning(f"mcp_client: listing tools on '{server_name}' failed: {exc}")
            return {"ok": False, "server": server_name, "error": str(exc)}
