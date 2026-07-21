"""Event-sourced authoritative core for The Lost Meaning: Infinite Stacks.

`state` holds the aggregates, `commands`/`events` the envelopes, `reducer`
the pure command->events->state pipeline, `rng` the single injectable
randomness source, and `replay` the seed+log determinism guarantee
(docs/INFINITE_STACKS_CONTRACTS.md).
"""
