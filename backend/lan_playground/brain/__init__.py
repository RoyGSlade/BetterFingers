"""Standalone brain package for The Lost Meaning: Infinite Stacks
(infinite_stacks.md §4.1, §12.1-12.3, §19.4, §20; wavebasedgame.md §2.3,
§2.4, §3.2, §3.5, §3.6 -- the 2026-07-21 owner design lock).

Same discipline as `combat/`, `heroes/`, and `shops/`: pure, deterministic,
zero I/O, zero imports of `domain`/`systems`/`content`/`heroes`/`combat`/
`shops`/`stacks_*.py`. Data in, data out -- this package builds bounded
generation packets, parses/validates model output defensively, resolves
social-check DCs and modifiers, and always produces a structured response,
but it never calls a model, never persists anything, and never reaches into
engine state on its own. Domain/reducer wiring (what calls this package, in
what order, with what state) is the next wave's concern.

See docs/INFINITE_STACKS_BRAIN.md for the full interface contract.
"""
from __future__ import annotations
