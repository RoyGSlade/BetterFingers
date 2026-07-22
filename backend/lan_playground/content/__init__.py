"""Content pipeline for The Lost Meaning: Infinite Stacks (board task #2).

`schemas.py` defines the versioned data model, `loader.py` loads YAML packs
into it strictly, `validators.py` runs CI-style cross-file checks (§23.2).
Content is data; the LLM never owns solutions or mechanics (§20.2).
"""

# Lazy re-exports: the repo's architecture gate (tests/test_architecture_smoke.py)
# treats any eager `from .submodule import ...` in a package __init__ as a
# package<->submodule edge, so re-exports must resolve at attribute access.
_EXPORTS = {
    "LoaderError": "loader",
    "load_core_pack": "loader",
    "load_pack": "loader",
    "ContentError": "schemas",
    "ContentPack": "schemas",
    "Finding": "validators",
    "ValidationError": "validators",
    "validate_pack": "validators",
    "validate_pack_dir": "validators",
    # wave 6B: room/object/NPC/Meaning Lattice content (rooms.py, npcs.py,
    # lattice.py) plus their strict-YAML loader/validator pair (room_loader.py,
    # npc_loader.py, study_common.py, study_loader.py, study_validators.py).
    "load_study_pack": "study_loader",
    "StudyContentPack": "study_loader",
    "validate_study_pack": "study_validators",
    "validate_study_pack_strict": "study_validators",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        module = importlib.import_module(f".{_EXPORTS[name]}", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
