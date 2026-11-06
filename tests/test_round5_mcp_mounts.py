"""Round 5, item 1 (Codex re-check 4, blocker 1): configurable MCP mounts defeated the sandbox.

``install_binds`` accepted any ``install_dir``, the folder of any absolute command and every
existing absolute FILE argument, and rejected only a folder that was, or contained, the home or
the data folder. So a configuration could mount ``/run`` (host D-Bus, Wayland and PipeWire
sockets: read-only does not stop a socket accepting commands), the host ``/proc``, and private
home descendants such as ``~/.ssh`` or one key file named as an argument. And the binds were
added AFTER the private ``/dev``, ``/proc`` and ``/tmp``, so a bind could replace them.

Director's decisions, applied here:
  * absolute file arguments are never mounted automatically;
  * ``install_dir`` and an absolute command's folder may only be (a) inside the server's own
    folder ``<app data>/mcp-servers/<server name>/`` (created by the app) or (b) a read-only
    system location under ``/usr``, ``/opt`` or ``/nix/store``, judged on the REAL path (every
    symlink resolved first);
  * anything else is refused, with the reason, and the whole server is refused: a mount is never
    silently dropped;
  * configured binds come before the private ``/dev``, ``/proc`` and ``/tmp``, so an isolation
    mount is always the last mount for its path;
  * ``"network": true`` stays as it is, with its abstract-socket risk shown in the listing.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

from backend.dev import mcp_client

BWRAP = staticmethod(lambda name: {"bwrap": "/usr/bin/bwrap"}.get(name))
LINUX = sys.platform.startswith("linux")
SYSTEM_PYTHON = next((p for p in ("/usr/bin/python3",) if os.path.exists(p)), None)
STRICT = mcp_client.sandbox_kind() == "bubblewrap"
ISOLATION_FLAGS = {"--dev", "--proc", "--tmpfs"}
MOUNT_FLAGS = {"--ro-bind", "--ro-bind-try", "--bind", "--bind-try", "--dev-bind", "--dev-bind-try"}


def _scratch_base():
    """Scratch folders OUTSIDE /tmp: /tmp is itself a refused location now, so a fake home and
    data folder made there would be refused for the wrong reason."""
    base = os.path.join(os.path.expanduser("~"), ".cache")
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix="bf-mcp-round5-", dir=base)


def _mounts(args):
    """Every mount operation in argv order: (flag, destination)."""
    out = []
    i = 0
    while i < len(args):
        flag = args[i]
        if flag == "--":
            break
        if flag in MOUNT_FLAGS or flag == "--symlink":
            out.append((flag, args[i + 2]))
            i += 3
            continue
        if flag in ISOLATION_FLAGS:
            out.append((flag, args[i + 1]))
            i += 2
            continue
        i += 1
    return out


def _ro_sources(args):
    return [args[i + 1] for i, a in enumerate(args) if a in ("--ro-bind", "--ro-bind-try", "--bind", "--bind-try")]


@unittest.skipUnless(LINUX, "the MCP sandbox (and these paths) exist on Linux only")
class _Case(unittest.TestCase):
    def setUp(self):
        self.base = _scratch_base()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.home, ".local", "share", "BetterFingers")
        os.makedirs(os.path.join(self.home, ".ssh"))
        os.makedirs(self.data)
        self.key = os.path.join(self.home, ".ssh", "id_probe")
        with open(self.key, "w") as handle:
            handle.write("not a real key")
        self.root = os.path.join(self.data, "mcp-servers", "srv")

    def spec(self, **extra):
        return {"command": "srv", "args": [], "env": {}, "enabled": True, "sandbox": "auto", "network": False, **extra}

    def plan(self, spec, name="srv"):
        return mcp_client.launch_plan(name, spec, platform="linux", which=BWRAP, home=self.home,
                                      data_root=self.data, environ={})

    def assertRefused(self, spec, *words, name="srv"):
        with self.assertRaises(mcp_client.McpConfinementError) as caught:
            self.plan(spec, name=name)
        message = str(caught.exception)
        self.assertIn("Nothing was started", message)
        for word in words:
            self.assertIn(word, message)
        return message


class AbsoluteFileArgumentsTests(_Case):
    def test_an_existing_private_file_named_as_an_argument_is_not_mounted(self):
        plan = self.plan(self.spec(command="/usr/bin/python3", args=[self.key, "--config", self.key]))
        self.assertEqual(plan["binds"], [], "an argument is never an authority to mount")
        self.assertNotIn(self.key, _ro_sources(plan["args"]))
        self.assertNotIn(os.path.realpath(self.key), _ro_sources(plan["args"]))
        # The argument is still passed through unchanged: it just names nothing inside.
        self.assertEqual(plan["args"][plan["args"].index("--") + 1:], ["/usr/bin/python3", self.key, "--config", self.key])


class RefusedLocationsTests(_Case):
    def test_codex_synthetic_mounts_are_all_refused(self):
        # The exact plan Codex built: /run, /proc, ~/.ssh and a key file. Each is refused alone.
        for install_dir in ("/run", "/proc", os.path.join(self.home, ".ssh")):
            with self.subTest(install_dir=install_dir):
                message = self.assertRefused(self.spec(install_dir=install_dir), install_dir)
                self.assertIn("mcp-servers", message, "the refusal says where to install instead")

    def test_service_process_temporary_and_config_locations_are_refused(self):
        tmp = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(shutil.rmtree, tmp, True)
        for install_dir in ("/run", "/run/user", "/var/run", "/proc", "/proc/self", "/sys", "/dev", "/dev/shm",
                            "/tmp", tmp, "/var/tmp", "/etc", "/etc/ssh", "/", "/home", "/var", "/srv", "/root"):
            with self.subTest(install_dir=install_dir):
                self.assertRefused(self.spec(install_dir=install_dir))

    def test_home_descendants_and_the_app_data_folder_are_refused(self):
        other = os.path.join(self.data, "mcp-servers", "other")
        os.makedirs(other)
        os.makedirs(self.root)
        for install_dir in (self.home, os.path.join(self.home, ".ssh"), os.path.join(self.home, "projects"),
                            self.data, os.path.join(self.data, "mcp-servers"), other, os.path.join(self.root, "..", "other"),
                            "~/.ssh", "relative/folder"):
            with self.subTest(install_dir=install_dir):
                self.assertRefused(self.spec(install_dir=install_dir))

    def test_a_symlink_that_leaves_the_allowed_roots_is_refused(self):
        os.makedirs(self.root)
        os.symlink(os.path.join(self.home, ".ssh"), os.path.join(self.root, "keys"))
        self.assertRefused(self.spec(install_dir=os.path.join(self.root, "keys")))
        # A server folder that is ITSELF a link out of the data folder is not a server folder.
        os.makedirs(os.path.join(self.data, "mcp-servers"), exist_ok=True)
        os.symlink(os.path.join(self.home, ".ssh"), os.path.join(self.data, "mcp-servers", "linked"))
        self.assertRefused(self.spec(install_dir=os.path.join(self.data, "mcp-servers", "linked")), name="linked")

    def test_an_absolute_command_outside_the_allowed_roots_is_refused(self):
        bindir = os.path.join(self.home, ".local", "bin")
        os.makedirs(bindir)
        tool = os.path.join(bindir, "srv")
        with open(tool, "w") as handle:
            handle.write("#!/bin/sh\n")
        self.assertRefused(self.spec(command=tool))
        tmp = tempfile.mkdtemp(dir="/tmp")
        self.addCleanup(shutil.rmtree, tmp, True)
        self.assertRefused(self.spec(command=os.path.join(tmp, "srv")))

    def test_one_bad_mount_refuses_the_whole_server_instead_of_being_dropped(self):
        os.makedirs(self.root)
        self.assertRefused(self.spec(install_dir=[self.root, "/run"]), "/run")

    def test_a_malformed_install_dir_is_refused_not_ignored(self):
        for value in (5, ["/usr/lib", 7], {"path": "/usr"}):
            with self.subTest(value=value):
                self.assertRefused(self.spec(install_dir=value))

    def test_a_server_name_that_cannot_be_a_folder_gets_no_install_folder(self):
        for name in ("a/b", "..", ".hidden", "x\ny"):
            with self.subTest(name=name):
                folder = os.path.join(self.data, "mcp-servers", *name.split("/"))
                os.makedirs(folder, exist_ok=True)
                self.assertRefused(self.spec(install_dir=folder), name=name)


class AllowedLocationsTests(_Case):
    def test_the_server_folder_is_created_and_may_be_mounted(self):
        plan = self.plan(self.spec())
        self.assertTrue(os.path.isdir(self.root), "<app data>/mcp-servers/<name>/ is created for the server")
        self.assertEqual(plan["binds"], [], "nothing is mounted unless the config asks")
        sub = os.path.join(self.root, "lib")
        os.makedirs(sub)
        plan = self.plan(self.spec(install_dir=[self.root, sub]))
        self.assertEqual(plan["binds"], [os.path.realpath(self.root), os.path.realpath(sub)])

    def test_a_command_inside_the_server_folder_mounts_its_folder(self):
        bindir = os.path.join(self.root, "bin")
        os.makedirs(bindir)
        plan = self.plan(self.spec(command=os.path.join(bindir, "srv")))
        self.assertEqual(plan["binds"], [os.path.realpath(bindir)])

    def test_system_locations_under_usr_opt_and_nix_store_are_allowed(self):
        plan = self.plan(self.spec(install_dir="/usr/lib", command="/usr/bin/python3"))
        self.assertEqual(plan["binds"], ["/usr/lib"])
        root = os.path.realpath(self.root)
        for real in ("/opt/vendor/server", "/nix/store/abc123-server", "/usr/lib/node_modules/x"):
            with self.subTest(real=real):
                self.assertIsNone(mcp_client.mount_refusal(real, server_root=root, home=self.home, data_root=self.data))
        for real in ("/opt", "/nix/store", "/nix", "/optional/x", "/usrx/lib", "/nix/storefront/x"):
            with self.subTest(real=real):
                self.assertIsNotNone(mcp_client.mount_refusal(real, server_root=root, home=self.home, data_root=self.data))

    def test_binds_are_read_only(self):
        os.makedirs(self.root)
        args = self.plan(self.spec(install_dir=self.root))["args"]
        flags = [args[i] for i, a in enumerate(args) if a.startswith("--") and i + 1 < len(args) and args[i + 1] == os.path.realpath(self.root)]
        self.assertTrue(flags and all(flag in ("--ro-bind", "--ro-bind-try") for flag in flags), flags)


class MountOrderTests(_Case):
    def test_configured_binds_come_before_the_private_dev_proc_and_tmp(self):
        os.makedirs(os.path.join(self.root, "bin"))
        plan = self.plan(self.spec(install_dir=["/usr/lib", self.root], command=os.path.join(self.root, "bin", "srv")))
        mounts = _mounts(plan["args"])
        configured = [i for i, (flag, dest) in enumerate(mounts) if flag in ("--ro-bind", "--ro-bind-try") and dest in plan["binds"]]
        self.assertEqual(len(configured), len(plan["binds"]))
        for path, flag in (("/dev", "--dev"), ("/proc", "--proc"), ("/tmp", "--tmpfs")):
            index = mounts.index((flag, path))
            self.assertGreater(index, max(configured), f"{flag} {path} comes after every configured bind")

    def test_each_isolation_mount_is_the_last_mount_for_its_path(self):
        os.makedirs(self.root)
        plan = self.plan(self.spec(install_dir=["/usr/lib", self.root], network=True))
        mounts = _mounts(plan["args"])
        home = os.path.realpath(self.home)
        for path, flag in (("/dev", "--dev"), ("/proc", "--proc"), ("/tmp", "--tmpfs"), (home, "--tmpfs")):
            index = mounts.index((flag, path))
            for later_flag, dest in mounts[index + 1:]:
                covers = path == dest or path.startswith(dest.rstrip("/") + "/")
                self.assertFalse(covers, f"{later_flag} {dest} after {flag} {path} would replace it")
        # The server folder lives under the home, so it is mounted after the empty home (a strict
        # descendant of it: it cannot replace the home itself).
        root = os.path.realpath(self.root)
        self.assertLess(mounts.index(("--tmpfs", home)), mounts.index(("--ro-bind-try", root)))
        self.assertTrue(root.startswith(home + "/"))


class ListingTests(_Case):
    def setUp(self):
        super().setUp()
        patcher = patch("backend.dev.mcp_client.get_user_data_path", return_value=self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("backend.dev.mcp_client.sandbox_kind", return_value="bubblewrap")
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch("backend.dev.mcp_client.shutil.which", side_effect=lambda n: "/usr/bin/bwrap" if n == "bwrap" else None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, servers):
        with open(os.path.join(self.data, "mcp_servers.json"), "w") as handle:
            json.dump({"enabled": True, "mcpServers": servers}, handle)

    def test_a_refused_mount_shows_why_and_where_to_install(self):
        self.write({"bad": {"command": "srv", "install_dir": "/run"}})
        row = mcp_client.list_servers()[0]
        self.assertFalse(row["will_start"])
        self.assertIn("/run", row["why"])
        self.assertEqual(row["install_root"], os.path.join(os.path.realpath(self.data), "mcp-servers", "bad"))
        self.assertTrue(os.path.isdir(row["install_root"]))

    def test_network_true_carries_a_warning_and_network_off_does_not(self):
        self.write({"online": {"command": "srv", "network": True}, "quiet": {"command": "srv"}})
        rows = {row["name"]: row for row in mcp_client.list_servers()}
        self.assertIn("abstract", rows["online"]["warning"].lower())
        self.assertTrue(rows["online"]["network"])
        self.assertEqual(rows["quiet"]["warning"], "")


class InstallFoldersAreUserDataTests(unittest.TestCase):
    """The servers' folders hold whatever the person installed for MCP, so they are part of the
    "MCP configuration" category: clearing personal data (and the factory reset) removes them."""

    def test_clearing_personal_data_removes_the_server_folders(self):
        import pathlib

        from backend.privacy import data_categories as dc
        from backend.privacy import data_lifecycle as dl
        from backend.privacy import data_registry as dr

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            with patch("backend.config.app_paths.resolve_base", return_value=root):
                server = root / "mcp-servers" / "srv"
                server.mkdir(parents=True)
                (server / "server.py").write_text("print('hi')\n", encoding="utf-8")
                (root / "mcp_servers.json").write_text("{}", encoding="utf-8")
                registry = dc.build_registry()
                self.assertIn(root / "mcp-servers", registry.get("mcp_config").paths())
                result = dl.execute_mode(registry, dr.WIPE_MODE_PERSONAL)
                self.assertTrue(result["categories"]["mcp_config"]["verified"], result)
                self.assertFalse((root / "mcp-servers").exists())


@unittest.skipUnless(LINUX and STRICT and SYSTEM_PYTHON, "bubblewrap and /usr/bin/python3 are needed")
class LiveMountTests(unittest.TestCase):
    """A real server, installed the documented way, under the real bwrap: it sees its own folder,
    and nothing of the home or /run around it."""

    def test_a_server_in_its_folder_runs_and_sees_nothing_else(self):
        base = _scratch_base()
        self.addCleanup(shutil.rmtree, base, True)
        data = os.path.join(base, "data")
        root = os.path.join(data, "mcp-servers", "probe")
        os.makedirs(root)
        script = os.path.join(root, "probe.py")
        with open(script, "w") as handle:
            handle.write(textwrap.dedent("""
                import json, os, sys
                home = os.path.expanduser("~")
                print(json.dumps({"own": open(sys.argv[0]).read().startswith("\\nimport json"),
                                  "home": sorted(os.listdir(home)), "run": os.path.exists("/run"),
                                  "ssh": os.path.exists(os.path.join(home, ".ssh"))}))
                """))
        spec = {"command": SYSTEM_PYTHON, "args": [script], "env": {}, "enabled": True, "sandbox": "auto",
                "network": False, "install_dir": root}
        launch = mcp_client.stdio_launch("probe", spec, data_root=data)
        result = subprocess.run([launch["command"], *launch["args"]], env=launch["env"], capture_output=True,
                                text=True, timeout=60, check=False)
        self.assertEqual(result.returncode, 0, result.stderr[-600:])
        report = json.loads(result.stdout.strip().splitlines()[-1])
        self.assertTrue(report["own"], "the server reads its own installed file")
        home = os.path.realpath(os.path.expanduser("~"))
        real_root = os.path.realpath(root)
        expected = [os.path.relpath(real_root, home).split(os.sep)[0]] if real_root.startswith(home + os.sep) else []
        self.assertEqual(report["home"], expected, "only the path down to the server's own folder")
        self.assertFalse(report["run"])
        self.assertFalse(report["ssh"])


if __name__ == "__main__":
    unittest.main()
