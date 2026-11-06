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

Every server is UNTRUSTED: it starts only inside the required confinement
(bubblewrap on Linux), or, where that cannot be established, only after the owner
marked it "trusted on this machine" (see the sandbox section below).
"network": false cuts a confined server's network.

The whole feature is gated by the top-level "enabled" flag (default false) and
kept fully defensive: the `mcp` SDK is imported lazily, and any failure here
must never disrupt the dictation pipeline. Tool *invocation*, llama-server
bridging, and per-persona allowlists are later C12 steps.
"""
import asyncio
import datetime
import functools
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading

from backend.config.utils import get_user_data_path
from backend.privacy.secret_scrub import redact_args, scrubbed_child_env

DEFAULT_TIMEOUT_SECONDS = 15.0

_lock = threading.Lock()
_trust_lock = threading.Lock()


def _config_path():
    return os.path.join(get_user_data_path(), "mcp_servers.json")


def sdk_available():
    try:
        import mcp  # noqa: F401
        return True
    except Exception:
        return False


# --- the MCP subprocess sandbox (round 2, item 3; round 3, item 4) -------------------------
#
# Scrubbing the environment (Phase 0 item 9) stops an MCP server INHERITING credentials; it
# does not stop a hostile same-user executable from looking for them, or from driving the
# desktop. Three layers:
#   1. the backend holds no credential in its environment (backend/privacy/boot_secrets.py),
#   2. the backend is non-dumpable on Linux, so /proc/<pid>/{environ,mem,maps} are not
#      readable by other processes of the same user (and a launch that cannot set that
#      refuses to hold its secrets at all), and
#   3. EVERY MCP SERVER IS UNTRUSTED BY DEFAULT and starts only inside the REQUIRED
#      confinement, which on Linux is bubblewrap (see ``_bwrap_profile``): its own PID, IPC
#      and UTS namespaces, no new privileges, no capabilities, the filesystem read-only, the
#      app's data folder and the usual credential folders replaced by empty ones, a private
#      /tmp, the WHOLE $XDG_RUNTIME_DIR masked (the D-Bus session bus, the Wayland socket,
#      PipeWire, keyrings), the X11 socket directory and X authority files masked, the
#      system bus masked, and the network cut when the server's config says
#      ``"network": false``. It dies with the backend (--die-with-parent).
#
# Where that confinement cannot be established -- no usable bubblewrap, Windows, macOS, or
# a server configured with ``"sandbox": "off"`` -- the server is REFUSED with a clear error,
# unless the owner has marked it "trusted on this machine" in a native dialog (a signed
# ``mcp.trust`` ticket bound to a digest of the server's exact configuration; any change to
# the configuration voids it). A trusted server then runs with the weaker confinement the
# machine has: ``setpriv --no-new-privs`` on Linux, nothing on Windows and macOS. That
# consent is stored in ``mcp_trust.json`` (declared in the privacy inventory, removed by a
# personal-data wipe and a factory reset).
#
# KNOWN LIMIT, stated plainly: with the network ON, a bubblewrap-confined server shares the
# host network namespace, so ABSTRACT unix sockets (for example an X server listening on
# "@/tmp/.X11-unix/X0") stay reachable. The X authority files are masked, which defeats the
# usual cookie authentication, but an X server configured to accept local connections
# without a cookie (xhost +local:) would still accept one. ``"network": false`` closes that.

_CREDENTIAL_DIRS = (".ssh", ".gnupg", ".aws", ".kube", os.path.join(".config", "gcloud"))
_X_AUTH_FILES = (".Xauthority", ".ICEauthority")
_DESKTOP_ENV = ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XAUTHORITY")

REQUIRED_CONFINEMENT = "bubblewrap"
TRUST_FILENAME = "mcp_trust.json"
_TRUST_SCHEMA = 1


class McpConfinementError(PermissionError):
    """The required confinement cannot be established and the owner has not trusted the
    server on this machine. The message says what is missing and what to do."""


@functools.lru_cache(maxsize=4)
def _bwrap_works(path):
    """bubblewrap can be installed and still unusable (unprivileged user namespaces off, an
    AppArmor restriction). Probe once with the flags the profile needs."""
    try:
        result = subprocess.run(
            [path, "--die-with-parent", "--unshare-pid", "--ro-bind", "/", "/", "--dev", "/dev",
             "--proc", "/proc", "--", "true"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def sandbox_kind(*, platform=None, which=shutil.which):
    """The strongest confinement this machine can give an MCP server: 'bubblewrap',
    'no_new_privs' or 'none'. Only 'bubblewrap' is the REQUIRED confinement."""
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return "none"
    bwrap = which("bwrap")
    # A probe only for the real lookup: tests inject ``which`` to describe a machine.
    if bwrap and (which is not shutil.which or _bwrap_works(bwrap)):
        return "bubblewrap"
    if which("setpriv"):
        return "no_new_privs"
    return "none"


def _runtime_dirs(environ):
    dirs = []
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime:
        dirs.append(runtime)
    if hasattr(os, "getuid"):
        dirs.append(f"/run/user/{os.getuid()}")
    out = []
    for directory in dirs:
        real = os.path.realpath(directory)
        if os.path.isdir(real) and real not in out:
            out.append(real)
    return out


def _bwrap_profile(command, args, *, data_root, home, network, environ):
    wrapped = [
        "--die-with-parent", "--new-session", "--unshare-pid", "--unshare-ipc", "--unshare-uts",
        "--unshare-cgroup-try", "--cap-drop", "ALL",
        "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
        # a private /tmp, and in it an empty X11 socket directory
        "--tmpfs", "/tmp", "--tmpfs", "/tmp/.X11-unix",
    ]
    if not network:
        wrapped.append("--unshare-net")
    masked = list(_runtime_dirs(environ))
    if os.path.isdir("/run/dbus"):
        masked.append("/run/dbus")  # the system bus
    masked += [d for d in (data_root,) if d and os.path.isdir(d)]
    masked += [os.path.join(home, rel) for rel in _CREDENTIAL_DIRS if os.path.isdir(os.path.join(home, rel))]
    for directory in masked:
        wrapped += ["--tmpfs", directory]
    auth_files = [environ.get("XAUTHORITY")] + [os.path.join(home, name) for name in _X_AUTH_FILES]
    seen = set()
    for path in auth_files:
        if path and os.path.isfile(path) and path not in seen:
            seen.add(path)
            wrapped += ["--ro-bind", "/dev/null", path]
    return [*wrapped, "--", command, *args]


def sandbox_command(command, args, *, mode="auto", platform=None, which=shutil.which,
                    data_root=None, home=None, network=True, environ=None):
    """``(command, args, kind)`` with the strongest confinement available, as a building
    block. Whether a server may START is ``launch_plan``'s decision, not this one's.

    ``mode`` is the server's ``"sandbox"`` setting: ``"auto"`` (default) or ``"off"``.
    """
    args = [str(item) for item in (args or [])]
    if str(mode).lower() == "off":
        return command, args, "none"
    kind = sandbox_kind(platform=platform, which=which)
    if kind == "bubblewrap":
        home = home or os.path.expanduser("~")
        environ = os.environ if environ is None else environ
        return which("bwrap"), _bwrap_profile(command, args, data_root=data_root, home=home,
                                              network=bool(network), environ=environ), kind
    if kind == "no_new_privs":
        return which("setpriv"), ["--no-new-privs", "--", command, *args], kind
    return command, args, "none"


def config_digest(name, spec):
    """SHA-256 of a server's exact configuration (name, command, arguments, environment block,
    options). A trust record is bound to it; any change to any of these voids the trust."""
    canonical = json.dumps({
        "name": str(name),
        "command": spec.get("command", ""),
        "args": list(spec.get("args", [])),
        "env": dict(spec.get("env", {})),
        "sandbox": spec.get("sandbox", "auto"),
        "network": bool(spec.get("network", True)),
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def _why_unconfinable(spec, *, platform, which):
    if str(spec.get("sandbox", "auto")).lower() == "off":
        return 'its configuration says "sandbox": "off".'
    if not platform.startswith("linux"):
        return "BetterFingers cannot confine MCP servers on this operating system."
    if not which("bwrap"):
        return "bubblewrap (bwrap) is not installed, so BetterFingers cannot confine it."
    return "bubblewrap is installed but cannot create a sandbox on this machine."


def _weaker_kind(*, platform, which):
    if platform.startswith("linux") and which("setpriv"):
        return "no_new_privs"
    return "none"


def launch_plan(name, spec, *, platform=None, which=shutil.which, data_root=None, home=None, environ=None,
                is_trusted=None):
    """How to start server ``name``, or ``McpConfinementError`` when it may not start.

    Default: the required confinement (bubblewrap). Otherwise only a server the owner trusted on
    this machine for exactly this configuration starts, with the weaker confinement available.
    """
    platform = sys.platform if platform is None else platform
    data_root = get_user_data_path() if data_root is None else data_root
    mode = str(spec.get("sandbox", "auto")).lower()
    if mode != "off" and sandbox_kind(platform=platform, which=which) == REQUIRED_CONFINEMENT:
        command, args, kind = sandbox_command(spec["command"], spec["args"], platform=platform, which=which,
                                              data_root=data_root, home=home,
                                              network=spec.get("network", True), environ=environ)
        return {"command": command, "args": args, "kind": kind, "trusted": False}
    reason = _why_unconfinable(spec, platform=platform, which=which)
    check = is_trusted if is_trusted is not None else is_trusted_on_this_machine
    if not check(name, config_digest(name, spec)):
        raise McpConfinementError(
            f"MCP server '{name}' was not started: {reason} It can run with weaker confinement only after "
            "you mark it trusted on this machine in BetterFingers (a confirmation window shows its exact "
            "configuration). Nothing was started."
        )
    weaker = _weaker_kind(platform=platform, which=which)
    command, args = spec["command"], [str(a) for a in spec["args"]]
    if weaker == "no_new_privs":
        return {"command": which("setpriv"), "args": ["--no-new-privs", "--", command, *args], "kind": weaker, "trusted": True}
    return {"command": command, "args": args, "kind": "none", "trusted": True}


# --- "trusted on this machine" (round 3, item 4) ----------------------------------------------

def _trust_path():
    return os.path.join(get_user_data_path(), TRUST_FILENAME)


def _load_trust():
    try:
        with open(_trust_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    servers = data.get("servers") if isinstance(data, dict) else None
    return {str(k): v for k, v in servers.items() if isinstance(v, dict)} if isinstance(servers, dict) else {}


def _save_trust(servers):
    path = _trust_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".mcp_trust.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": _TRUST_SCHEMA, "servers": servers}, handle, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def is_trusted_on_this_machine(name, digest):
    record = _load_trust().get(str(name))
    return bool(record) and record.get("config_sha256") == digest


def trust(name, digest, proof):
    """Record that the owner trusted ``name`` with configuration ``digest``. Needs a proof that
    came out of ``approvals.verify`` for exactly this server and digest."""
    from backend.services import approvals

    if not approvals.require_verified(proof, purpose=approvals.PURPOSE_MCP_TRUST, subject=str(name)) \
            or dict(proof.bind) != approvals.mcp_trust_bind(digest):
        raise PermissionError("Trusting an MCP server needs your approval in the BetterFingers window.")
    with _trust_lock:
        servers = _load_trust()
        servers[str(name)] = {
            "config_sha256": digest,
            "trusted_at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        }
        _save_trust(servers)
    return {"ok": True, "server": str(name), "trusted": True}


def revoke_trust(name):
    """Withdraw trust (always allowed: it only makes things stricter)."""
    with _trust_lock:
        servers = _load_trust()
        existed = servers.pop(str(name), None) is not None
        if existed:
            _save_trust(servers)
    return {"ok": True, "server": str(name), "revoked": existed}


def trust_info(server_name):
    """What the trust dialog shows, and the digest the ticket must bind. KeyError if unknown."""
    config = load_config()
    spec = config["mcpServers"].get(server_name)
    if spec is None:
        raise KeyError(server_name)
    platform = sys.platform
    required_ok = spec["sandbox"] != "off" and sandbox_kind(platform=platform) == REQUIRED_CONFINEMENT
    digest = config_digest(server_name, spec)
    weaker = _weaker_kind(platform=platform, which=shutil.which)
    weaker_text = {"no_new_privs": "no new privileges only (setpriv); no filesystem, desktop or network isolation",
                   "none": "none: it runs as you, like any program you start"}[weaker]
    if not spec["network"]:
        weaker_text += "; the network cannot be cut without bubblewrap"
    return {
        "name": server_name,
        "command": spec["command"],
        "args": redact_args(spec["args"]),
        "env_keys": sorted(spec["env"]),
        "network": spec["network"],
        "sandbox": spec["sandbox"],
        "config_sha256": digest,
        "required_confinement": REQUIRED_CONFINEMENT,
        "required_confinement_available": required_ok,
        "weaker_confinement": weaker_text,
        "why_untrusted": "" if required_ok else _why_unconfinable(spec, platform=platform, which=shutil.which),
        "trusted": is_trusted_on_this_machine(server_name, digest),
    }


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
            # Round 3, item 4: the network stays on unless the config says "network": false
            # (then a bubblewrap-confined server gets no network namespace access at all).
            "network": spec.get("network", True) is not False,
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
        _listing_row(name, spec)
        for name, spec in sorted(config["mcpServers"].items())
    ]


def _listing_row(name, spec):
    try:
        plan = launch_plan(name, spec)
        sandbox, starts = plan["kind"], True
    except McpConfinementError:
        sandbox, starts = "refused", False
    return {
        "name": name,
        "command": spec["command"],
        # The launch command line can carry a credential (``--api-key X``);
        # the listing is an API response, so show it masked.
        "args": redact_args(spec["args"]),
        "enabled": spec["enabled"],
        "network": spec["network"],
        # what confinement this server actually gets on this machine ("refused": it will not
        # start until it can be confined or the owner trusts it on this machine)
        "sandbox": sandbox,
        "will_start": starts,
        "trusted": is_trusted_on_this_machine(name, config_digest(name, spec)),
    }


async def _list_tools_async(plan, spec, timeout):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # An ALLOWLISTED environment plus the server's own configured ``env`` block -- never
    # ``os.environ``, which holds this backend's bearer token and approval key and whatever
    # provider keys the user's shell exports (Phase 0 item 9). Merely listing tools launches
    # the server, so it must not be able to read them. A confined server is also given no
    # desktop session addresses (round 3, item 4): their sockets are masked anyway.
    env = scrubbed_child_env(os.environ, spec["env"])
    if plan["kind"] == REQUIRED_CONFINEMENT:
        for name in _DESKTOP_ENV:
            env.pop(name, None)
    params = StdioServerParameters(command=plan["command"], args=plan["args"], env=env)
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
    if it cannot be confined and is not trusted on this machine, RuntimeError
    if the SDK is missing.
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
    # Round 3, item 4: refuse BEFORE anything starts when the required confinement cannot be
    # established and the owner has not trusted this exact configuration on this machine.
    plan = launch_plan(server_name, spec)
    if plan["kind"] != REQUIRED_CONFINEMENT:
        logging.warning(f"mcp_client: '{server_name}' runs with weaker confinement ({plan['kind']}): trusted on this machine")

    with _lock:
        try:
            tools = asyncio.run(_list_tools_async(plan, spec, timeout))
            return {"ok": True, "server": server_name, "tools": tools}
        except Exception as exc:
            logging.warning(f"mcp_client: listing tools on '{server_name}' failed: {exc}")
            return {"ok": False, "server": server_name, "error": str(exc)}
