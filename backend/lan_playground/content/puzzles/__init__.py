"""Puzzle generator + solver code for content-owned Mystery Chamber templates.

Distinct from `content/packs/core/puzzles/` (YAML template *metadata*, e.g.
`ordering_sequence.yaml`'s registry entry) -- this package holds the actual
generator and solver functions, which are code, never data (infinite_stacks.md
§10.1, §20.2: the LLM and content packs may name/describe a puzzle's facts but
never own its solution).
"""

from .ordering_sequence import generate_instance
from .solver import solve, solve_instance

__all__ = ["generate_instance", "solve", "solve_instance"]
