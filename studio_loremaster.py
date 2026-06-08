"""
Loremaster — the full-story understanding pass (Phase 0 of the Studio overhaul).

THE KEYSTONE FIX. Every other Studio stage used to read a 6,000-char head+tail excerpt
of the source story (`studio_workflow._story_excerpt`), so ~73% of a long manuscript —
including its inciting incident and climax — was invisible to the model. You cannot ask
an LLM to narrate events it was never shown. This module reads the WHOLE story and
distills it into one structured `story_understanding` artifact that every downstream
agent consumes instead of raw (truncated) text.

It works by map-reduce, which is exactly the shape a small local model (e.g. Gemma 12B)
is good at — summarize a 3k window, not swallow 22k and emit a layout:

    chunk   -> split full text into ~3k paragraph-aligned windows
    map     -> one small LLM call per chunk -> structured chunk notes
    reduce  -> deterministically merge chunk notes (events in order, dossiers by name)
    synthesize -> one LLM call turns the merged notes into premise/themes/motifs/
                  setup-payoff candidates (operates on the compact notes, not raw text)

Every step degrades gracefully: with no LLM available the map step falls back to a
per-chunk `studio_analyzer.analyze()` pass and the synthesis falls back to a
deterministic build, so an offline run still produces a faithful (if plainer)
understanding — and, for long stories, a *better* one than the old single excerpt.

The module is deliberately decoupled from StudioWorkflowRunner: it takes an optional
`llm_call` callable shaped like `runner._call_llm_with_fallback`, so it is unit-testable
with no engine and no database.
"""

import logging

import studio_analyzer

logger = logging.getLogger("studio_loremaster")

# Keys a chunk-notes object should expose (used for light shape validation).
CHUNK_NOTE_KEYS = ["events", "characters_seen", "motifs", "world_facts"]
# Keys the final understanding always carries, so downstream readers can rely on them.
UNDERSTANDING_KEYS = [
    "title", "premise", "themes", "tone", "motifs", "timeline",
    "character_dossiers", "world_facts", "setup_payoff_candidates",
]


# --------------------------------------------------------------------------- #
# Chunking
# --------------------------------------------------------------------------- #

def chunk_text(text, max_chars=3000):
    """Split text into ~max_chars windows on paragraph boundaries.

    Never splits mid-paragraph unless a single paragraph already exceeds the window
    (then that paragraph is hard-wrapped on whitespace). Returns a list of strings in
    document order.
    """
    text = (text or "").strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in _split_paragraphs(text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks = []
    buf = []
    size = 0
    for para in paragraphs:
        if len(para) > max_chars:
            # Flush what we have, then hard-wrap the oversized paragraph.
            if buf:
                chunks.append("\n\n".join(buf))
                buf, size = [], 0
            chunks.extend(_hardwrap(para, max_chars))
            continue
        if size + len(para) + 2 > max_chars and buf:
            chunks.append("\n\n".join(buf))
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        chunks.append("\n\n".join(buf))
    return chunks


def _split_paragraphs(text):
    import re
    return re.split(r"\n\s*\n", text)


def _hardwrap(para, max_chars):
    words = para.split()
    out, buf, size = [], [], 0
    for w in words:
        if size + len(w) + 1 > max_chars and buf:
            out.append(" ".join(buf))
            buf, size = [], 0
        buf.append(w)
        size += len(w) + 1
    if buf:
        out.append(" ".join(buf))
    return out


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #

def analyze_full(text, llm_call=None, profile=None, max_chunk_chars=3000, progress=None):
    """Read the WHOLE story and return a structured `story_understanding` dict.

    Args:
        text: the full source manuscript (NOT truncated).
        llm_call: optional callable shaped like
            ``runner._call_llm_with_fallback(prompt, system_prompt, fallback_func, max_output_tokens)``.
            When ``None``, the pass runs fully deterministically off ``studio_analyzer``.
        profile: optional generation profile (for token budgets); falls back to safe defaults.
        max_chunk_chars: target window size for the map step.
        progress: optional ``progress(message)`` callback for live UI notes.

    Returns a dict with the keys in ``UNDERSTANDING_KEYS`` plus ``_grounding`` describing
    how it was produced ("map-reduce" or "analyzer-fallback").
    """
    text = (text or "").strip()
    if not text:
        return _empty_understanding()

    def _note(msg):
        if progress:
            try:
                progress(msg)
            except Exception:
                pass

    # The analyzer pass is always computed: it grounds the fallbacks and seeds names.
    analysis = studio_analyzer.analyze(text)
    chunks = chunk_text(text, max_chunk_chars)
    _note(f"Reading the full story in {len(chunks)} passes...")

    have_llm = callable(llm_call)
    map_tokens = _tokens(profile, "medium", default=1200)
    synth_tokens = _tokens(profile, "large", default=1800)
    # Track whether the LLM actually produced output vs every call quietly falling back (a dead
    # or corrupt model). Without this the label would claim "map-reduce" while running on mocks.
    stats = {"llm": 0, "fallback": 0}

    # --- MAP: one structured note per chunk -------------------------------- #
    chunk_notes = []
    for i, chunk in enumerate(chunks):
        _note(f"Understanding section {i + 1} of {len(chunks)}...")
        chunk_notes.append(_map_chunk(chunk, i, len(chunks), llm_call, map_tokens, have_llm, stats))

    # --- REDUCE: deterministically merge the notes ------------------------- #
    merged = _reduce_notes(chunk_notes, analysis)

    # --- SYNTHESIZE: lift the merged notes into a story understanding ------- #
    _note("Synthesizing themes, motifs, and character dossiers...")
    understanding = _synthesize(merged, analysis, text, llm_call, synth_tokens, have_llm, stats)
    understanding["_grounding"] = _grounding_label(have_llm, stats)
    return understanding


def _grounding_label(have_llm, stats):
    """Honest provenance: only claim 'map-reduce' if the LLM actually produced output."""
    if not have_llm or stats["llm"] == 0:
        return "analyzer-fallback"  # no model, or every call fell back (e.g. corrupt model)
    if stats["fallback"] == 0:
        return "map-reduce"
    return "map-reduce (partial)"


# --------------------------------------------------------------------------- #
# MAP
# --------------------------------------------------------------------------- #

def _map_chunk(chunk, index, total, llm_call, max_tokens, have_llm, stats=None):
    """Turn one chunk into structured notes. Falls back to a per-chunk analyzer pass."""
    stats = stats if stats is not None else {"llm": 0, "fallback": 0}

    def fallback():
        stats["fallback"] += 1
        return _analyzer_chunk_notes(chunk)

    if not have_llm:
        return fallback()

    before = stats["fallback"]

    system_prompt = (
        "You are the Loremaster reading ONE section of a longer story. Extract what HAPPENS "
        "and who is revealed, faithfully — do not invent. Capture subtext (what a character "
        "is hiding, wanting, or feeling beneath the surface) because later sections depend on "
        "it. Output ONLY a JSON object: "
        '{"events": [{"event": "what concretely happens", "characters": ["Name"], '
        '"location": "place or \\"\\"", "significance": "why it matters"}], '
        '"characters_seen": [{"name": "Name", "traits": ["adjective"], "want": "", "wound": "", '
        '"secret": "", "key_lines": ["a real quoted line if present"]}], '
        '"motifs": ["recurring image or symbol"], "world_facts": ["established fact about the world"], '
        '"notable_lines": [{"speaker": "Name", "line": "quoted line"}]}'
    )
    prompt = (
        f"Section {index + 1} of {total} of the story:\n\"\"\"\n{chunk}\n\"\"\"\n"
        "Extract the structured notes for THIS section only."
    )
    result = llm_call(prompt, system_prompt, fallback, max_tokens)
    if not _is_chunk_note(result):
        return fallback()
    # If the fallback counter didn't move, the model genuinely produced this note.
    if stats["fallback"] == before:
        stats["llm"] += 1
    # Always backstop with analyzer extraction so we never lose a real quoted line.
    return _blend_chunk_notes(result, _analyzer_chunk_notes(chunk))


def _analyzer_chunk_notes(chunk):
    """Deterministic per-chunk notes from the heuristic analyzer."""
    a = studio_analyzer.analyze(chunk)
    events = [
        {
            "event": b.get("summary", ""),
            "characters": [],
            "location": "",
            "significance": b.get("name", ""),
        }
        for b in (a.get("beats") or []) if b.get("summary")
    ]
    chars = []
    for c in (a.get("characters") or []):
        chars.append({
            "name": c.get("name", ""),
            "traits": [],
            "want": "",
            "wound": "",
            "secret": "",
            "key_lines": [c["sample_line"]] if c.get("sample_line") else [],
        })
    return {
        "events": events,
        "characters_seen": chars,
        "motifs": [],
        "world_facts": [p.get("name", "") for p in (a.get("locations") or []) if p.get("name")],
        "notable_lines": [
            {"speaker": d.get("speaker", "Narrator"), "line": d.get("text", "")}
            for d in (a.get("dialogue") or []) if d.get("text")
        ][:6],
    }


def _blend_chunk_notes(primary, backup):
    """Fill gaps in an LLM chunk note with the analyzer's extraction (esp. real quotes)."""
    out = dict(primary)
    out.setdefault("events", primary.get("events") or [])
    out["characters_seen"] = _merge_char_lists(
        primary.get("characters_seen") or [], backup.get("characters_seen") or []
    )
    out["motifs"] = _dedupe((primary.get("motifs") or []) + (backup.get("motifs") or []))
    out["world_facts"] = _dedupe((primary.get("world_facts") or []) + (backup.get("world_facts") or []))
    out["notable_lines"] = (primary.get("notable_lines") or []) or (backup.get("notable_lines") or [])
    return out


# --------------------------------------------------------------------------- #
# REDUCE
# --------------------------------------------------------------------------- #

def _reduce_notes(chunk_notes, analysis):
    """Merge per-chunk notes into one structure: ordered timeline + dossiers by name."""
    timeline = []
    order = 0
    dossiers = {}
    motifs, world_facts, lines = [], [], []

    for note in chunk_notes:
        for ev in (note.get("events") or []):
            ev_text = (ev.get("event") or "").strip()
            if not ev_text:
                continue
            order += 1
            timeline.append({
                "order": order,
                "event": ev_text,
                "location": (ev.get("location") or "").strip(),
                "characters": ev.get("characters") or [],
                "significance": (ev.get("significance") or "").strip(),
            })
        for ch in (note.get("characters_seen") or []):
            _fold_dossier(dossiers, ch)
        motifs += note.get("motifs") or []
        world_facts += note.get("world_facts") or []
        lines += note.get("notable_lines") or []

    # Seed any analyzer-known characters we never folded (keeps the roster complete).
    for c in (analysis.get("characters") or []):
        _fold_dossier(dossiers, {
            "name": c.get("name", ""),
            "key_lines": [c["sample_line"]] if c.get("sample_line") else [],
        })

    return {
        "timeline": timeline,
        "dossiers": list(dossiers.values()),
        "motifs": _dedupe(motifs),
        "world_facts": _dedupe(world_facts),
        "notable_lines": lines[:24],
        "mentions": {c.get("name", "").lower(): c.get("mentions", 0) for c in (analysis.get("characters") or [])},
    }


def _dossier_key(name):
    parts = (name or "").strip().split()
    return parts[-1].lower() if parts else ""


def _fold_dossier(dossiers, ch):
    name = (ch.get("name") or "").strip()
    if not name:
        return
    key = _dossier_key(name)
    if key not in dossiers:
        dossiers[key] = {
            "name": name, "traits": [], "want": "", "need": "", "wound": "",
            "secret": "", "relationships": [], "voice": "", "key_lines": [],
        }
    d = dossiers[key]
    # Prefer the longest spelling as canonical ("Freddy Goldstein" over "Goldstein").
    if len(name) > len(d["name"]):
        d["name"] = name
    d["traits"] = _dedupe(d["traits"] + (ch.get("traits") or []))
    for field in ("want", "need", "wound", "secret", "voice"):
        if not d.get(field) and ch.get(field):
            d[field] = ch[field]
    for rel in (ch.get("relationships") or []):
        if rel and rel not in d["relationships"]:
            d["relationships"].append(rel)
    for line in (ch.get("key_lines") or []):
        if line and line not in d["key_lines"]:
            d["key_lines"].append(line)
    d["key_lines"] = d["key_lines"][:5]


def _merge_char_lists(a, b):
    tmp = {}
    for ch in list(a) + list(b):
        _fold_dossier(tmp, ch)
    return list(tmp.values())


# --------------------------------------------------------------------------- #
# SYNTHESIZE
# --------------------------------------------------------------------------- #

def _synthesize(merged, analysis, text, llm_call, max_tokens, have_llm, stats=None):
    """Lift merged notes into premise/themes/motifs/dossiers/setups. Works on the compact
    merged notes (small), never the raw 22k text — that is what keeps the call cheap."""
    stats = stats if stats is not None else {"llm": 0, "fallback": 0}

    def fallback():
        stats["fallback"] += 1
        return _deterministic_synthesis(merged, analysis)

    if not have_llm:
        return fallback()
    before = stats["fallback"]

    # Rank dossiers by mention count so the lead is unambiguous to the model.
    mentions = merged.get("mentions") or {}
    dossiers = sorted(
        merged.get("dossiers") or [],
        key=lambda d: mentions.get(_dossier_key(d.get("name", "")), 0),
        reverse=True,
    )[:6]

    compact = {
        "timeline": [
            {"order": e["order"], "event": e["event"], "location": e.get("location", "")}
            for e in (merged.get("timeline") or [])
        ][:40],
        "characters": dossiers,
        "motifs": merged.get("motifs", []),
        "world_facts": merged.get("world_facts", []),
        "notable_lines": merged.get("notable_lines", []),
    }
    system_prompt = (
        "You are the Loremaster. Below are structured notes distilled from the ENTIRE story "
        "(its real timeline, characters, motifs, and quoted lines). Synthesize them into a "
        "story understanding the rest of the studio will rely on. Be faithful to the notes; "
        "infer subtext (want vs need, wounds, secrets, what makes each character distinctive) "
        "but never contradict the events. Output ONLY a JSON object: "
        '{"title": "", "premise": "2-3 faithful sentences", "themes": ["theme"], '
        '"tone": "the felt mood", "motifs": ["image = meaning"], '
        '"character_dossiers": [{"name": "", "role": "protagonist|antagonist|ally|mentor|supporting", '
        '"traits": ["edge-y adjective"], "want": "", "need": "", "wound": "", "secret": "", '
        '"relationships": [{"who": "", "bond": ""}], "voice": "how they talk", '
        '"key_lines": ["real quoted line"]}], '
        '"setup_payoff_candidates": [{"setup": "what is planted", "possible_payoff": "how it could land later"}]}'
    )
    prompt = "Story notes (whole-story):\n" + _safe_json(compact)
    result = llm_call(prompt, system_prompt, fallback, max_tokens)
    if not isinstance(result, dict) or not result.get("character_dossiers"):
        return fallback()
    if stats["fallback"] == before:
        stats["llm"] += 1

    # The model owns interpretation, but the deterministic timeline/world_facts are the
    # authoritative record of what literally happened — carry them through verbatim.
    result["timeline"] = merged.get("timeline", [])
    result.setdefault("world_facts", merged.get("world_facts", []))
    result.setdefault("motifs", merged.get("motifs", []))
    result["title"] = result.get("title") or analysis.get("title", "Untitled Story")
    result["tone"] = result.get("tone") or analysis.get("tone", "drama")
    # Backfill real quoted lines onto dossiers when the model dropped them.
    _restore_key_lines(result.get("character_dossiers", []), merged.get("dossiers", []))
    return _ensure_understanding_shape(result)


def _deterministic_synthesis(merged, analysis):
    """Build a faithful understanding with zero LLM, from analyzer + merged notes."""
    mentions = merged.get("mentions") or {}
    dossiers_in = sorted(
        merged.get("dossiers") or [],
        key=lambda d: mentions.get(_dossier_key(d.get("name", "")), 0),
        reverse=True,
    )
    roles = ["protagonist", "antagonist", "ally", "supporting", "supporting", "supporting"]
    dossiers = []
    for i, d in enumerate(dossiers_in[:6]):
        dossiers.append({
            "name": d.get("name", ""),
            "role": roles[i] if i < len(roles) else "supporting",
            "traits": d.get("traits", []),
            "want": d.get("want", ""),
            "need": d.get("need", ""),
            "wound": d.get("wound", ""),
            "secret": d.get("secret", ""),
            "relationships": d.get("relationships", []),
            "voice": d.get("voice") or (d["key_lines"][0] if d.get("key_lines") else ""),
            "key_lines": d.get("key_lines", []),
        })
    lead = dossiers[0]["name"] if dossiers else "the protagonist"
    summary = analysis.get("summary") or ""
    premise = (
        f"A faithful adaptation following {lead}. {summary}".strip()
        if summary else f"A faithful adaptation following {lead}."
    )
    return _ensure_understanding_shape({
        "title": analysis.get("title", "Untitled Story"),
        "premise": premise,
        "themes": [],
        "tone": analysis.get("tone", "drama"),
        "motifs": merged.get("motifs", []),
        "timeline": merged.get("timeline", []),
        "character_dossiers": dossiers,
        "world_facts": merged.get("world_facts", []),
        "setup_payoff_candidates": [],
    })


def _restore_key_lines(synth_dossiers, merged_dossiers):
    by_key = {_dossier_key(d.get("name", "")): d for d in merged_dossiers}
    for d in synth_dossiers or []:
        if d.get("key_lines"):
            continue
        src = by_key.get(_dossier_key(d.get("name", "")))
        if src and src.get("key_lines"):
            d["key_lines"] = src["key_lines"]


# --------------------------------------------------------------------------- #
# Shape helpers
# --------------------------------------------------------------------------- #

def _ensure_understanding_shape(u):
    out = dict(u or {})
    out.setdefault("title", "Untitled Story")
    out.setdefault("premise", "")
    out.setdefault("themes", [])
    out.setdefault("tone", "drama")
    out.setdefault("motifs", [])
    out.setdefault("timeline", [])
    out.setdefault("character_dossiers", [])
    out.setdefault("world_facts", [])
    out.setdefault("setup_payoff_candidates", [])
    return out


def _empty_understanding():
    return _ensure_understanding_shape({})


def _is_chunk_note(value):
    return isinstance(value, dict) and (
        isinstance(value.get("events"), list) or isinstance(value.get("characters_seen"), list)
    )


def _dedupe(items):
    out, seen = [], set()
    for x in items or []:
        key = str(x).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(x if not isinstance(x, str) else x.strip())
    return out


def _tokens(profile, shape, default):
    if not profile:
        return default
    try:
        import studio_generation
        return studio_generation.max_tokens_for(profile, shape)
    except Exception:
        return default


def _safe_json(obj):
    import json
    try:
        return json.dumps(obj, ensure_ascii=False)
    except Exception:
        return "{}"
