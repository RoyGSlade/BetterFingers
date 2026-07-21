"""Standalone combat core for The Lost Meaning: Infinite Stacks (infinite_stacks.md §14-16).

Pure and deterministic: every module here is rng-injected, does zero I/O, calls no
LLM, and never imports backend.lan_playground.domain or backend.lan_playground.systems
(those are the wave-3 reducer-wiring lane's concern, owned elsewhere this wave).
`intents.py` is the sole exception: it may read backend.lan_playground.content
read-only to load enemy intent telegraphs authored in content/packs/core/enemies.yaml.

See docs/INFINITE_STACKS_COMBAT.md for the event/interface contract.
"""
from __future__ import annotations
