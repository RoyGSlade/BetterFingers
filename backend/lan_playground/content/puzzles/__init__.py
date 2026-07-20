"""Puzzle generator + solver code for content-owned Mystery Chamber templates.

Distinct from `content/packs/core/puzzles/` (YAML template *metadata*, e.g.
`ordering_sequence.yaml`'s registry entry) -- this package holds the actual
generator and solver functions, which are code, never data (infinite_stacks.md
§10.1, §20.2: the LLM and content packs may name/describe a puzzle's facts but
never own its solution).
"""

# Lazy re-exports: the repo's architecture gate (tests/test_architecture_smoke.py)
# treats any eager `from .submodule import ...` in a package __init__ as a
# package<->submodule edge, so re-exports must resolve at attribute access.
_EXPORTS = {
    "generate_instance": "ordering_sequence",
    "solve": "solver",
    "solve_instance": "solver",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name in _EXPORTS:
        import importlib

        module = importlib.import_module(f".{_EXPORTS[name]}", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
