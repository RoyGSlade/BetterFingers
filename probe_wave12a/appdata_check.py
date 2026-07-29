"""Did the PRE-EXISTING app_paths (HEAD) ignore the APPDATA value?

The director's P0 says the APPDATA branch "ignores the APPDATA VALUE completely
and returns the real home root". This runs HEAD's own source to find out,
rather than arguing from a reading of it.
"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

REPO = "/home/donaven/Desktop/BetterFingers"

head_src = subprocess.run(["git", "show", "HEAD:app_paths.py"], cwd=REPO,
                          capture_output=True, text=True, check=True).stdout

sys.path.insert(0, REPO)
head = types.ModuleType("app_paths_head")
head.__dict__["__file__"] = os.path.join(REPO, "app_paths.py")
exec(compile(head_src, "HEAD:app_paths.py", "exec"), head.__dict__)

with tempfile.TemporaryDirectory() as tmp:
    fake_home = Path(tmp) / "fakehome"
    (fake_home / "BetterFingers").mkdir(parents=True)
    (fake_home / "BetterFingers" / "personas.yaml").write_text("a: {}\n")
    appdata = Path(tmp) / "isolated"
    appdata.mkdir()

    env = {k: v for k, v in os.environ.items() if k not in ("BETTERFINGERS_DATA_DIR",)}
    env["APPDATA"] = str(appdata)
    with patch.dict(os.environ, env, clear=True), \
         patch.object(head.Path, "home", staticmethod(lambda: fake_home)):
        base = head.resolve_base()

    print("HEAD app_paths.resolve_base() with APPDATA set")
    print(f"  APPDATA           = {appdata}")
    print(f"  fake HOME         = {fake_home}   (contains a populated BetterFingers/)")
    print(f"  resolved base     = {base}")
    print()
    under_appdata = str(base).startswith(str(appdata))
    under_home = str(base).startswith(str(fake_home))
    print(f"  under APPDATA?    = {under_appdata}")
    print(f"  under HOME?       = {under_home}")
    print()
    if under_appdata and not under_home:
        print("  VERDICT: HEAD HONOURED the APPDATA value. The APPDATA branch is")
        print("           NOT the destroyer; _legacy_home_base() reads APPDATA first.")
    elif under_home:
        print("  VERDICT: HEAD IGNORED APPDATA and resolved onto HOME. Director is right.")
    else:
        print("  VERDICT: neither — inspect manually.")
