Original prompt: Pause all ACCOMPLISH.md work and turn the hardened BetterFingers LAN playground into a unique, simple 1–4 player adventure-and-humor game, hosted by this PC, with QR-code joining and BetterFingers persona rewriting integrated. Use Sonnet for bulk implementation and verify independently.

## Direction

- ACCOMPLISH.md work is paused at the user's request; preserve all partial changes.
- Build on `backend/lan_playground/**` and `tools/lan_playground.py`.
- Keep loopback-by-default, explicit `--lan`, access-code gating, no content logging, bounded inputs, rate limits, and local-only model calls.
- Game target: host creates a room; 1–4 phones/computers join by QR/link; short cooperative/competitive card-board adventure with humorous persona-powered text choices; playable without a model via deterministic fallback content.
- Required test hooks: `window.render_game_to_text()` and `window.advanceTime(ms)`, plus fullscreen toggle (`f`).

## TODO

- [x] Receive clean pause handoffs from active ACCOMPLISH workers; their partial changes remain preserved and parked.
- [x] Freeze game rules and API/state contract -- `backend/lan_playground/game.py` + `docs/LAN_GAME_SPEC.md` (board #39, game-engine-sonnet). Pure in-memory `Room`/`GameRegistry`, deterministic 5-encounter co-op combat (Charm/Scheme/Bonk, shared 3 hearts), lobby/choosing/reveal/finished phases, disconnect-safe host succession, tokens/unsubmitted choices never leaked via `public_state()`, cosmetic `set_flavor()` overlay point for persona/LLM rewrite. 35 focused tests in `tests/test_lan_game_engine.py`, all passing. Zero FastAPI/LLM imports -- game-server-sonnet (#40) and game-client-sonnet (#41) build directly on this contract.
- [x] Implement secure room/session engine and QR join flow. Public 8-character room codes, host/player capability tokens, four-player cap, host succession, expiry/caps/rate limits, Host/Origin checks, and fully local SVG QR generation are complete (board #40).
- [x] Implement responsive host/player game UI and deterministic fallback content. Desktop and phone layouts, canvas trail, secret card selection, persona picker, reveal/finale/replay states, polling, fullscreen, and test hooks are complete (board #41/#44).
- [x] Add unit/integration/security tests and independent browser verification. The focused LAN game/playground suite passes 214 tests plus 70 subtests; `app.js` passes `node --check`; desktop and 390px phone screenshots were visually inspected; a real production-wired solo turn completed in 7.5s with the BetterFingers rewrite visible and no console/page errors. Four-player and five-encounter/replay flows are covered by HTTP acceptance and race tests (board #42/#43/#45).

## Verification artifacts

- Full focused test command: `python -m pytest -q tests/test_lan_game_static.py tests/test_lan_game_api.py tests/test_lan_game_engine.py tests/test_lan_game_concurrency.py tests/test_lan_game_e2e.py tests/test_lan_playground_app.py tests/test_lan_playground_rooms.py tests/test_lan_playground_smoke.py tests/test_lan_playground_qr.py tests/test_lan_playground_security.py`
- Result: 214 passed, 1 warning, 70 subtests passed.
- Browser checks exercised access-code auto-fill/URL cleanup, room creation, QR lobby, solo start, card/persona move submission, real local-model polish, reveal, responsive phone layout, and `render_game_to_text()`.
- The supplied 18-image art pack was audited and its production-safe key art, map, card illustrations, and victory/defeat tableaux were integrated through a fixed server allowlist. Desktop and 390px phone layouts were re-inspected after correcting intrinsic image sizing; unused checkerboard/composite assets remain out of the runtime UI.
- Final art pass: repaired the five fake-transparency checkerboard assets non-destructively with the built-in image editor (`*_v2.png`), aligned the engine encounters with the supplied Troll/Goblin HR/Mimic/Riddle Bridge/Red-Tape Dragon art, made the Dragon reliably final, added current-encounter art and a real game icon, and retained the merged UI composite only as source material because its pieces were not cleanly separable enough to justify runtime weight.
- Final browser pass completed a five-round desktop victory and a separate phone turn, inspected choosing/reveal/finale screenshots, verified cold-load placeholders and three-across phone cards, matched `render_game_to_text()` to the visible phase, and recorded zero console/page errors.
