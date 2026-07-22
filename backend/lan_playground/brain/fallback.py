"""Deterministic, no-model authored fallback path for every brain role
(wavebasedgame.md §3.5, infinite_stacks.md §20.3-20.4): "every generation
request declares... a deterministic fallback key... on failure, use
authored fallback prose and continue the game immediately."

A model timeout/absence can never block resolution: every `build_*_packet`
in `packets.py` carries a non-empty `deterministic_fallback_key`, and every
function here maps that key (plus the packet's own declared facts) to
authored, fact-preserving text with zero model involvement and zero I/O.
These are pure functions of their inputs -- same packet in, same fallback
text out, every time.
"""
from __future__ import annotations

from . import packets

_FACT_JOIN = "; "


def _facts_as_text(facts: tuple) -> str:
    """Render a frozen facts tuple (either plain strings or (key, value)
    pairs from `_freeze_facts`) into a short, deterministic clause list."""
    if not facts:
        return ""
    parts = []
    for item in facts:
        if isinstance(item, tuple) and len(item) == 2:
            parts.append(f"{item[0]}: {item[1]}")
        else:
            parts.append(str(item))
    return _FACT_JOIN.join(parts)


def fallback_for_interpreter(packet: packets.InterpreterPacket) -> str:
    """Authored fallback when the Interpreter model is unavailable/timed
    out: degrade to the zero-intent path's narration, never a crash and
    never a silent no-op. Callers pair this with
    `intents.ZERO_INTENT_RESULT` for the structured side."""
    return "Nothing about that request registers as a clear action here."


def fallback_for_npc_performer(packet: packets.NPCPerformerPacket) -> str:
    """Authored fallback NPC line: states the resolved degree/disposition
    plainly from declared facts, with no invented content beyond what the
    engine already authorized."""
    facts = _facts_as_text(packet.allowed_disclosures)
    if packet.disposition:
        base = f"The {packet.npc_id} responds, visibly {packet.disposition}."
    else:
        base = f"The {packet.npc_id} responds."
    if facts:
        return f"{base} ({facts})"
    return base


def fallback_for_narrator(packet: packets.NarratorPacket) -> str:
    """Authored fallback narration: a flat, factual restatement of the
    scene facts and resolved degree -- exactly the §12.5 "factual outcome
    events... generated narration only after those facts are committed"
    guarantee, just without the generative flourish."""
    facts = _facts_as_text(packet.scene_facts)
    degree = packet.resolved_degree or "the outcome is recorded"
    if facts:
        return f"{degree.capitalize()}. {facts}."
    return f"{degree.capitalize()}."


def fallback_for_event_to_book(packet: packets.EventToBookPacket) -> str:
    """Authored fallback book/note prose: a stage-appropriate factual
    stub built only from declared facts and event ids, never inventing
    history not present in those facts (infinite_stacks.md §20.2)."""
    facts = _facts_as_text(packet.declared_facts)
    stage = packet.prose_stage
    if stage == "title":
        return facts.split(_FACT_JOIN)[0] if facts else "Untitled Record"
    if facts:
        return f"A record of {len(packet.event_ids)} event(s): {facts}."
    return f"A record of {len(packet.event_ids)} event(s)."


_FALLBACK_BY_ROLE = {
    packets.BrainRole.INTERPRETER: fallback_for_interpreter,
    packets.BrainRole.NPC_PERFORMER: fallback_for_npc_performer,
    packets.BrainRole.NARRATOR: fallback_for_narrator,
    packets.BrainRole.EVENT_TO_BOOK_PROSE: fallback_for_event_to_book,
}


def resolve_fallback(role: packets.BrainRole, packet) -> str:
    """Single dispatch point: given a role and its matching packet, return
    the deterministic authored fallback text. Raises `KeyError` only for a
    genuinely unknown role (a programming error, not a runtime model
    failure) -- every real role above always has a fallback function."""
    return _FALLBACK_BY_ROLE[role](packet)
