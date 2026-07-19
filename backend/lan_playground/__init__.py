"""Isolated LAN persona rewrite playground (board #33).

A small, self-contained demo surface for trusted friends on the user's home
network: pick a persona, paste text, optionally add a custom rewrite
instruction, and see the refined output. No microphone/TTS/audio, no
persistence, no content logging. See docs/LAN_PLAYGROUND.md.

This package is deliberately independent of server.py's app object -- it
only reuses server.py's *functions* (lazily imported at call time) and the
shared backend services (message_rescue, rescue_llm_adapter, personas).
"""
