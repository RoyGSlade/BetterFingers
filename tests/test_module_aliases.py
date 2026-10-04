"""Compatibility aliases for modules moved during the backend reorganization.

When a batch moves a root module into `backend/` (or `tools/lib/`), the old
root file is replaced by a three-line alias:

    import sys
    from backend.audio import gate as _impl
    sys.modules[__name__] = _impl

so `import audio_gate`, `patch("audio_gate.x")` and `patch.object(audio_gate, ...)`
all act on the one real module object. A plain re-export (`from x import *`)
would instead create a second module, and the ~900 object-form patches in the
suite would silently patch the wrong one.

Each batch adds its moves to MOVED. Once nothing imports the old name, delete
the alias file, drop the entry here and from tests/test_repo_layout.py.
"""
import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# old top-level module name -> new dotted module name
MOVED: dict[str, str] = {}


def test_moved_modules_resolve_to_one_module_object():
    for old, new in sorted(MOVED.items()):
        new_module = importlib.import_module(new)
        old_module = importlib.import_module(old)
        assert old_module is new_module, f"{old} is a separate module object from {new}"
        assert sys.modules[old] is new_module


def test_alias_files_are_sys_modules_aliases():
    for old in sorted(MOVED):
        alias_file = REPO_ROOT / f"{old}.py"
        if not alias_file.exists():
            continue  # alias already retired; the identity test above still covers imports
        text = alias_file.read_text(encoding="utf-8")
        assert "sys.modules[__name__]" in text, (
            f"{alias_file.name} must alias via sys.modules[__name__], not re-export"
        )
