"""Round 4, item 4 (Codex re-check 3, findings 4 and 5): the MCP boundary.

Finding 4: a persistent "trusted on this machine" record let a server run with weaker or no
confinement from then on, after a dialog that showed masked arguments and only the NAMES of
its environment variables. Phase 0 policy (director): that exception is gone. An MCP server
runs only under the strict bubblewrap sandbox on Linux; where bubblewrap is unavailable
(Windows, macOS, no usable bwrap) MCP servers are disabled with a message that says why. There
is no trust record, no trust route and no trust dialog.

Finding 5: the server's own ``env`` block (``LD_PRELOAD`` included) reached the ``bwrap``
process itself, where a preload library runs before any confinement exists; and the profile
bound the whole host filesystem read-only with the network on by default. Now ``bwrap`` gets a
fixed, trusted environment, the server's variables are installed inside the sandbox with
``--setenv`` (loader and runtime-injection variables refused), the filesystem is the system
runtime plus the server's own install directory only, home is an empty tmpfs, nothing under
``/run`` is mounted, and the network is off unless the config says ``"network": true``.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from backend.dev import mcp_client

BWRAP = staticmethod(lambda name: {"bwrap": "/usr/bin/bwrap", "setpriv": "/usr/bin/setpriv"}.get(name))
# Refused everywhere: never given to bwrap, never installed inside the sandbox.
DENIED = ("LD_PRELOAD", "LD_LIBRARY_PATH", "LD_AUDIT", "LD_DEBUG", "GCONV_PATH", "GETCONF_DIR",
          "HOSTALIASES", "LOCALDOMAIN", "RES_OPTIONS", "NLSPATH", "MALLOC_TRACE", "LOCPATH", "PATH",
          "BETTERFINGERS_AUTH_TOKEN")
# Interpreter settings only affect the confined server itself, so they may be installed INSIDE,
# but they never reach the bwrap process either.
INSIDE_ONLY = ("PYTHONPATH", "NODE_OPTIONS", "BASH_ENV")


def _write_config(base_dir, payload):
    with open(os.path.join(base_dir, "mcp_servers.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)


class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)


class NoTrustExceptionTests(_Case):
    def test_the_trust_machinery_is_gone(self):
        for name in ("trust", "revoke_trust", "trust_info", "is_trusted_on_this_machine", "TRUST_FILENAME"):
            self.assertFalse(hasattr(mcp_client, name), f"mcp_client.{name} still exists")
        from backend.services import approvals

        self.assertFalse(hasattr(approvals, "PURPOSE_MCP_TRUST"))
        self.assertNotIn("mcp.trust", approvals.PURPOSES)

    def test_without_bubblewrap_mcp_is_disabled_with_a_reason_even_for_a_previously_trusted_server(self):
        # A trust record left over from round 3 must not matter.
        with open(os.path.join(self.tmp.name, "mcp_trust.json"), "w") as handle:
            json.dump({"schema_version": 1, "servers": {"srv": {"config_sha256": "x"}}}, handle)
        spec = {"command": "/opt/srv", "args": [], "env": {}, "enabled": True, "sandbox": "auto", "network": False}
        for platform, which, words in (
            ("win32", BWRAP, "Windows"),
            ("darwin", BWRAP, "macOS"),
            ("linux", lambda n: None, "bubblewrap"),
        ):
            with self.subTest(platform=platform), self.assertRaises(mcp_client.McpConfinementError) as caught:
                mcp_client.launch_plan("srv", spec, platform=platform, which=which, home="/nonexistent")
            message = str(caught.exception)
            self.assertIn(words, message)
            self.assertIn("disabled", message)
            self.assertNotIn("trusted", message)

    def test_sandbox_off_is_never_honoured(self):
        spec = {"command": "/opt/srv", "args": [], "env": {}, "enabled": True, "sandbox": "off", "network": False}
        with self.assertRaises(mcp_client.McpConfinementError):
            mcp_client.launch_plan("srv", spec, platform="linux", which=BWRAP, home="/nonexistent")

    def test_the_trust_routes_are_gone(self):
        from fastapi.testclient import TestClient

        import server
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"srv": {"command": "/opt/srv"}}})
        client = TestClient(server.app)
        self.assertEqual(client.get("/mcp/servers/srv/trust").status_code, 404)
        self.assertIn(client.post("/mcp/servers/srv/trust", json={}).status_code, (404, 405))


class BwrapEnvironmentTests(_Case):
    def test_the_bwrap_process_gets_a_trusted_environment_and_the_server_env_goes_inside(self):
        hostile = {name: "/tmp/evil.so" for name in DENIED + INSIDE_ONLY}
        spec = {"command": "/opt/srv/bin/srv", "args": ["--x"], "env": {"OWN_SETTING": "1", **hostile},
                "enabled": True, "sandbox": "auto", "network": False}
        with patch.dict(os.environ, {"LD_PRELOAD": "/tmp/from-backend.so"}):
            launch = mcp_client.stdio_launch("srv", spec, platform="linux", which=BWRAP, home="/nonexistent")
        self.assertEqual(launch["command"], "/usr/bin/bwrap")
        for name in DENIED + INSIDE_ONLY:
            if name == "PATH":
                continue
            self.assertNotIn(name, launch["env"], f"{name} reached the bwrap process")
        self.assertEqual(launch["env"], {"PATH": mcp_client.TRUSTED_PATH}, "bwrap gets a fixed environment")
        args = launch["args"]
        self.assertIn("--clearenv", args)
        setenv = {args[i + 1]: args[i + 2] for i, a in enumerate(args) if a == "--setenv"}
        self.assertEqual(setenv.get("OWN_SETTING"), "1", "an ordinary server variable is installed inside")
        for name in DENIED:
            if name == "PATH":
                self.assertEqual(setenv["PATH"], mcp_client.TRUSTED_PATH, "the server cannot override PATH")
            else:
                self.assertNotIn(name, setenv, f"{name} was installed inside the sandbox")
        for name in INSIDE_ONLY:
            self.assertEqual(setenv.get(name), "/tmp/evil.so", f"{name} only affects the confined server")
        self.assertLess(args.index("--clearenv"), args.index("--setenv"))
        self.assertEqual(args[args.index("--") + 1:], ["/opt/srv/bin/srv", "--x"])

    def test_the_deny_list_is_case_insensitive_and_covers_every_ld_variable(self):
        for name in ("ld_preload", "LD_ANYTHING_NEW", "Ld_Bind_Now", "gconv_path"):
            self.assertTrue(mcp_client.is_denied_env(name), name)
        for name in ("API_URL", "MY_SERVER_MODE", "LANG"):
            self.assertFalse(mcp_client.is_denied_env(name), name)


class StrictProfileTests(_Case):
    def profile(self, network=False, install_dir=None, command="/opt/srv/bin/srv", args=("--x",)):
        with tempfile.TemporaryDirectory() as home:
            spec = {"command": command, "args": list(args), "env": {}, "enabled": True, "sandbox": "auto",
                    "network": network}
            if install_dir:
                spec["install_dir"] = install_dir
            launch = mcp_client.stdio_launch("srv", spec, platform="linux", which=BWRAP, home=home,
                                             environ={"XDG_RUNTIME_DIR": "/run/user/1000"})
            return launch["args"], home

    def test_no_host_root_no_home_and_no_run(self):
        args, home = self.profile()
        binds = [(a, args[i + 1], args[i + 2]) for i, a in enumerate(args) if a in ("--bind", "--ro-bind", "--ro-bind-try", "--bind-try")]
        sources = [source for _flag, source, _dest in binds]
        self.assertNotIn("/", sources, "the host root is not mounted")
        self.assertFalse(any(flag in ("--bind", "--bind-try") for flag, _s, _d in binds), "nothing is writable")
        for source in sources:
            self.assertFalse(source == "/run" or source.startswith("/run/"), f"{source} is under /run")
            self.assertFalse(source == "/home" or source.startswith(home), f"{source} is in the host home")
            self.assertFalse(source.startswith("/etc") and source == "/etc", "not the whole of /etc")
        tmpfs = [args[i + 1] for i, a in enumerate(args) if a == "--tmpfs"]
        self.assertIn(home, tmpfs, "home is an empty tmpfs")
        self.assertIn("/tmp", tmpfs)
        for system in ("/usr",):
            self.assertIn(system, sources)

    def test_the_server_install_dir_is_bound_read_only(self):
        # Round 5, item 1: the install folder must be the server's own folder under the app data
        # (or a system location); a scratch folder under /tmp would be refused.
        base = os.path.join(os.path.expanduser("~"), ".cache")
        os.makedirs(base, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as data:
            install = os.path.join(data, "mcp-servers", "srv")
            os.makedirs(install)
            with tempfile.TemporaryDirectory() as home:
                spec = {"command": os.path.join(install, "srv"), "args": [], "env": {}, "enabled": True,
                        "sandbox": "auto", "network": False, "install_dir": install}
                args = mcp_client.stdio_launch("srv", spec, platform="linux", which=BWRAP, home=home, data_root=data,
                                               environ={})["args"]
        ro = [args[i + 1] for i, a in enumerate(args) if a in ("--ro-bind", "--ro-bind-try")]
        self.assertIn(os.path.realpath(install), ro)

    def test_network_is_off_by_default_and_on_only_when_the_config_says_true(self):
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {
            "quiet": {"command": "/opt/q"}, "online": {"command": "/opt/o", "network": True},
            "truthy": {"command": "/opt/t", "network": "yes"}}})
        servers = mcp_client.load_config()["mcpServers"]
        self.assertFalse(servers["quiet"]["network"])
        self.assertTrue(servers["online"]["network"])
        self.assertFalse(servers["truthy"]["network"], "only a literal true turns it on")
        args, _ = self.profile(network=False)
        self.assertIn("--unshare-net", args)
        args, _ = self.profile(network=True)
        self.assertNotIn("--unshare-net", args)


class FullConfigVisibleTests(_Case):
    def test_the_listing_shows_command_args_env_values_network_and_binds_in_full(self):
        _write_config(self.tmp.name, {"enabled": True, "mcpServers": {"a": {
            "command": "/opt/a", "args": ["--api-key", "visible-value"], "env": {"MODE": "fast", "API_KEY": "k-123"},
            "network": True}}})
        row = mcp_client.list_servers()[0]
        self.assertEqual(row["args"], ["--api-key", "visible-value"], "no masked preview stands in for the config")
        self.assertEqual(row["env"], {"MODE": "fast", "API_KEY": "k-123"})
        self.assertTrue(row["network"])
        self.assertIn("will_start", row)
        self.assertIn("why", row)


@unittest.skipUnless(mcp_client.sandbox_kind() == "bubblewrap" and os.path.exists("/usr/bin/python3"),
                     "bubblewrap or /usr/bin/python3 is not usable here")
class LiveStrictSandboxTests(_Case):
    def test_a_confined_process_sees_no_home_no_run_no_network_and_no_preload(self):
        probe = (
            "import json, os, sys\n"
            "home = sys.argv[1]\n"
            "out = {'home': sorted(os.listdir(home)) if os.path.isdir(home) else None,\n"
            "       'run_user': os.path.exists('/run/user'), 'etc_shadow': os.path.exists('/etc/shadow'),\n"
            "       'ifaces': sorted(l.split(':')[0].strip() for l in open('/proc/net/dev').read().splitlines()[2:]),\n"
            "       'env': sorted(os.environ), 'own': os.environ.get('OWN_SETTING')}\n"
            "print(json.dumps(out))\n"
        )
        home = os.path.expanduser("~")
        # Round 5, item 1: the system interpreter, nothing mounted from the home.
        spec = {"command": "/usr/bin/python3", "args": ["-c", probe, home],
                "env": {"OWN_SETTING": "1", "LD_PRELOAD": "/nonexistent/evil.so"},
                "enabled": True, "sandbox": "auto", "network": False}
        launch = mcp_client.stdio_launch("srv", spec)
        import subprocess

        result = subprocess.run([launch["command"], *launch["args"]], env=launch["env"], capture_output=True,
                                text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertEqual(report["home"], [], "the host home is not visible")
        self.assertFalse(report["run_user"])
        self.assertFalse(report["etc_shadow"])
        self.assertEqual(report["ifaces"], ["lo"])
        self.assertNotIn("LD_PRELOAD", report["env"])
        self.assertEqual(report["own"], "1")


if __name__ == "__main__":
    unittest.main()
