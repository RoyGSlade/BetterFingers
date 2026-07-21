"""Standalone character-creation + deck/inventory package (infinite_stacks.md
§11, §13), wave 3 (board task #11).

Same discipline as `backend.lan_playground.combat`: zero I/O, zero imports of
`domain`/`systems`/`stacks_*.py`, randomness only through an injected
structural Protocol (`heroes.rng.HeroesRNG`, shaped like `combat.rng.CombatRNG`
so the real `domain.rng.StacksRNG` satisfies both unmodified). Content pack
data (backgrounds/cards/items) is never loaded by this package -- callers load
it (e.g. `content.loader.load_core_pack()`) and pass the parsed objects in.

Domain/reducer wiring is wave 4. See docs/INFINITE_STACKS_HEROES.md for the
full interface contract.
"""
