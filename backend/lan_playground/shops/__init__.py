"""Standalone shop economy package for The Lost Meaning: Infinite Stacks
(infinite_stacks.md §9.6, §6.2, §17.1), wave 4 (board task #15).

Same discipline as `backend.lan_playground.combat` and
`backend.lan_playground.heroes`: pure, deterministic, zero I/O, zero imports
of `domain`/`systems`/`stacks_*.py`/`heroes`/`combat`/`content`. Content pack
data (shop archetypes, item ids) is never loaded by this package -- callers
load it (`content.loader.load_shops()`) and pass the parsed objects in.
Randomness only through an injected structural Protocol (`shops.rng.ShopsRNG`,
shaped like `combat.rng.CombatRNG`/`heroes.rng.HeroesRNG`).

Domain/reducer wiring is wave 5. See docs/INFINITE_STACKS_SHOPS.md for the
full interface contract.
"""
