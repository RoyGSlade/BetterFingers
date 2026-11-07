"""Running server.py as a script must not create a second `server` module.

The sidecar starts the backend as `python server.py` (dev) or as the
PyInstaller entry script (packaged); both execute this file as `__main__`,
and `uvicorn.run(app, ...)` serves THAT module's app. Routers reach shared
state with a lazy `import server`, which would otherwise import server.py a
second time under the name `server` -- a separate copy with its own drafts,
engines, runtime coordinator and wake state that the served app never sees.
Unit tests import `server` normally, so only a script-mode run shows it.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_script_mode_import_server_returns_the_running_module(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    env = dict(os.environ)
    env.pop("PYTEST_CURRENT_TEST", None)
    env.update(
        BETTERFINGERS_DATA_DIR=str(tmp_path / "data"),
        APPDATA=str(tmp_path / "appdata"),
        LOCALAPPDATA=str(tmp_path / "localappdata"),
        USERPROFILE=str(home),
        HOME=str(home),
        BETTERFINGERS_LAZY_STARTUP="1",
        PYTHONPATH=str(REPO_ROOT),
    )
    # --help makes argparse exit before uvicorn starts serving.
    script = textwrap.dedent(
        """
        import runpy, sys
        sys.argv = ["server.py", "--help"]
        try:
            runpy.run_path("server.py", run_name="__main__")
        except SystemExit:
            pass
        import server
        print("SERVER_MODULE_NAME=" + server.__name__)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=300,
    )
    assert "SERVER_MODULE_NAME=__main__" in result.stdout, (
        "import server loaded a second copy instead of the running __main__ module\n"
        + result.stdout[-1500:] + "\n" + result.stderr[-2500:]
    )
