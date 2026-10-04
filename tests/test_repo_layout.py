"""Repository layout guardrails (the backend reorganization is complete).

Every Python module has moved out of the repository root into the `backend/`
package (one batch per commit). Two layout rules hold from here on:

1. The root is closed. Exactly two root-level `.py` files exist: `server.py`
   (the PyInstaller and dev entry point) and `version.py` (reads the root
   `VERSION` file). A new root-level `.py` file fails this test outright; new
   code belongs under `backend/`. No compatibility aliases remain (see
   tests/test_module_aliases.py), so nothing else belongs on this list.
2. Tests stay flat. Windows CI enumerates `tests/test_*.py` non-recursively
   (`.github/workflows/ci.yml`), so a test file moved into a subfolder would
   silently stop running there.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ROOT_MODULES = frozenset({
    "server.py",
    "version.py",
})


def test_no_new_root_level_python_modules():
    present = {path.name for path in REPO_ROOT.glob("*.py")}
    unexpected = sorted(present - ROOT_MODULES)
    assert not unexpected, (
        f"New root-level Python modules: {unexpected}. Put new code under backend/ "
        "(see docs/arc/REPO_MAP.md section 6b), not in the repository root."
    )


def test_tests_stay_flat():
    nested = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "tests").rglob("test_*.py")
        if path.parent != REPO_ROOT / "tests"
    )
    assert not nested, (
        f"Test files in subfolders: {nested}. Windows CI only runs tests/test_*.py "
        "at the top level, so these would silently stop running there."
    )
