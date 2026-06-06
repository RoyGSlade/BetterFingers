"""Procedural story analyzer for Studio Mode.

When the local LLM sidecar is not ready, Studio's production stages fall back to
mock data. The original mocks were generic ("Young Archivist's situation unfolds")
and ignored the manuscript entirely, so a dropped story like *The Loss of a Brother*
came out as steampunk filler with characters named "Young Archivist" / "Masked Rival".

This module gives those fallbacks something to stand on: a dependency-free analysis
of the actual source text. It performs lightweight named-entity extraction (people vs
places), pulls real quoted dialogue with speaker attribution, segments the story into
beats, and infers tone/aesthetic from the vocabulary. The result is a *faithful*
adaptation that uses the manuscript's real names, places, and lines — no model required.

Everything here is pure Python (no external deps) and deterministic, so it is safe to
call from any pipeline stage and easy to unit-test.
"""

import re
from collections import Counter, defaultdict

# Words that look like proper nouns at sentence start but almost never are names.
# Kept lowercase; matched case-insensitively against single-token candidates.
_STOPWORDS = {
    "the", "a", "an", "and", "but", "or", "nor", "for", "so", "yet", "of", "to",
    "in", "on", "at", "by", "with", "from", "into", "onto", "upon", "over", "under",
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "hers", "ours",
    "this", "that", "these", "those", "here", "there", "then", "now", "when", "where",
    "what", "who", "whom", "whose", "why", "how", "which",
    "is", "am", "are", "was", "were", "be", "been", "being", "do", "does", "did",
    "have", "has", "had", "will", "would", "shall", "should", "can", "could", "may",
    "might", "must", "not", "no", "yes", "if", "as", "than", "then", "because",
    "while", "though", "although", "until", "unless", "since", "after", "before",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "chapter", "prologue", "epilogue", "scene", "act", "part",
    "every", "some", "any", "all", "none", "one", "two", "three", "four", "five",
    "maybe", "like", "just", "even", "still", "only", "also", "very", "too",
    "out", "up", "down", "off", "again", "once", "ever", "never", "always",
    "his", "their", "her",
    # Interjections / dialogue openers that get capitalized inside quotes.
    "listen", "sorry", "please", "well", "hey", "okay", "ok", "yeah", "nope",
    "hell", "damn", "jesus", "christ", "god", "wait", "look", "thanks", "hello",
    "goodbye", "oh", "ah", "huh", "hmm", "guess", "thought", "remember",
}

# Tokens that, when trailing a capitalized phrase, mark it as a *place* not a person.
_PLACE_SUFFIXES = {
    "city", "town", "village", "side", "room", "club", "pulse", "channel", "street",
    "bridge", "district", "dam", "office", "bar", "den", "alley", "harbor", "harbour",
    "docks", "dockside", "market", "hall", "tower", "station", "quarter", "ward",
    "river", "lake", "sea", "mountain", "valley", "forest", "woods", "house", "manor",
    "castle", "fort", "temple", "shrine", "cathedral", "church", "plaza", "square",
    "avenue", "road", "lane", "court", "yard", "gate", "vault", "vaults", "complex",
}

# Strongly locational prepositions. Deliberately excludes "to"/"from"/"near"/"toward",
# which just as often take a person ("said to Louis", "a gift from Goldstein").
_PLACE_PREPS = {"in", "at", "through", "across", "into"}

# Verbs of speech used to attribute quoted dialogue to a speaker.
_SPEECH_VERBS = {
    "said", "asked", "replied", "muttered", "whispered", "shouted", "yelled",
    "called", "answered", "spoke", "added", "continued", "murmured", "growled",
    "snapped", "hissed", "cried", "exclaimed", "demanded", "stated", "remarked",
    "told", "responded", "began", "laughed", "chuckled", "sighed",
}

# Pronouns whose presence near a name suggests the name is a person.
_PERSON_PRONOUNS = {"he", "she", "him", "her", "his", "hers", "himself", "herself"}

_TONE_LEXICON = {
    "noir": {
        "smoke", "cigarette", "cigar", "jazz", "shadow", "shadows", "neon", "rain",
        "gun", "pistol", "blood", "dame", "detective", "whisky", "whiskey", "scotch",
        "ash", "fog", "alley", "dock", "betrayal", "corpse", "fedora", "trench",
        "midnight", "gutter", "grime", "scar", "bullet", "smirk",
    },
    "fantasy": {
        "magic", "arcane", "spell", "sword", "dragon", "wizard", "rune", "enchant",
        "kingdom", "elf", "dwarf", "sorcerer", "prophecy", "realm", "myth",
    },
    "sci-fi": {
        "robot", "android", "laser", "ship", "starship", "warp", "cyber", "neon",
        "android", "circuit", "reactor", "orbit", "alien", "quantum", "drone",
    },
    "horror": {
        "blood", "scream", "corpse", "dread", "haunt", "ghost", "demon", "rot",
        "decay", "shadow", "nightmare", "terror", "flesh", "grave",
    },
    "romance": {
        "love", "heart", "kiss", "tender", "embrace", "longing", "warmth", "sweetheart",
    },
}

# Map an inferred tone to a concrete visual aesthetic description.
_TONE_AESTHETIC = {
    "noir": "Hard-boiled noir: rain-slick streets, smoke and neon, deep shadows and amber jazz-bar light, muted desaturated palette with pools of warm light.",
    "fantasy": "High-fantasy illustration: painterly lighting, rich saturated color, ornate detail and a sense of myth.",
    "sci-fi": "Sci-fi cinematic: cold blue-and-teal palette, hard rim light, chrome and neon, atmospheric haze.",
    "horror": "Horror chiaroscuro: heavy blacks, sickly greens, harsh single-source light, grain and dread.",
    "romance": "Warm romantic palette: soft golden light, shallow focus, tender intimate framing.",
    "drama": "Grounded cinematic drama: naturalistic light, restrained palette, character-focused framing.",
}


def _split_sentences(text):
    """Naive but robust sentence splitter that keeps quoted speech intact."""
    # Normalize whitespace/newlines into spaces for sentence-level work.
    flat = re.sub(r"\s+", " ", text).strip()
    if not flat:
        return []
    # Split on sentence-ending punctuation followed by a space + capital/quote.
    parts = re.split(r'(?<=[.!?])\s+(?=[A-Z"“])', flat)
    return [p.strip() for p in parts if p.strip()]


def _capitalized_runs(text):
    """Yield (tokens, starts_sentence) for every run of space-separated capitalized words.

    Crucially, runs are only joined across a *single space* — punctuation (commas,
    periods) breaks a run, so "Cautiously, Louis" yields ["Cautiously"] then ["Louis"]
    rather than a bogus merged name. ``starts_sentence`` marks runs that begin a
    sentence, where the leading capital is likely incidental grammar, not a name.
    """
    for sentence in _split_sentences(text):
        for m in re.finditer(r"[A-Z][A-Za-z'’]*(?:\s+[A-Z][A-Za-z'’]*)*", sentence):
            tokens = m.group(0).split()
            yield tokens, m.start() == 0


def _strip_apostrophe(tok):
    """Cut a token at its first apostrophe: "Goldstein's"->"Goldstein", "I'd"->"I"."""
    return re.split(r"[’']", tok, 1)[0]


def _normalize_name(phrase):
    """Strip possessives/contractions and leading/trailing stopword tokens."""
    words = [_strip_apostrophe(w) for w in phrase.split()]
    words = [w for w in words if w]
    while words and words[0].lower() in _STOPWORDS:
        words.pop(0)
    while words and words[-1].lower() in _STOPWORDS:
        words.pop()
    return " ".join(words)


def _is_place(phrase, text):
    """Heuristic: does this capitalized phrase name a location rather than a person?"""
    last = phrase.split()[-1].lower()
    if last in _PLACE_SUFFIXES:
        return True
    # "in <Phrase>", "at <Phrase>", "through <Phrase>" strongly implies a place.
    for prep in _PLACE_PREPS:
        if re.search(rf"\b{prep}\s+(the\s+)?{re.escape(phrase)}\b", text):
            # but not if it's also attributed as a speaker / has person pronouns nearby
            if not _has_person_signal(phrase, text):
                return True
    return False


def _has_person_signal(phrase, text):
    """True if the phrase behaves like a person (speaks, or sits near person pronouns)."""
    # Spoken attribution: "<Name> said" or "said <Name>".
    for verb in _SPEECH_VERBS:
        if re.search(rf"\b{re.escape(phrase)}[’']?s?\b\s+\w*\s*{verb}\b", text):
            return True
        if re.search(rf"\b{verb}\s+{re.escape(phrase)}\b", text):
            return True
    # Possessive followed by a body/feeling/voice word is very person-like.
    if re.search(rf"\b{re.escape(phrase)}[’']s\s+(voice|eyes|face|hand|hands|men|smirk|jaw|gaze|words|presence)\b", text):
        return True
    return False


def _first_mention_sentence(phrase, sentences):
    for s in sentences:
        if re.search(rf"\b{re.escape(phrase)}\b", s):
            return s
    return ""


def extract_entities(text):
    """Return (characters, locations) as ordered lists of dicts.

    characters: [{"name", "mentions", "description", "first_sentence"}]
    locations:  [{"name", "mentions", "description"}]
    """
    sentences = _split_sentences(text)

    # Pass 1: tally individual capitalized tokens. A token seen capitalized in a
    # non-sentence-initial position is almost certainly a proper noun ("strong").
    # Tokens that only ever start a sentence ("Cautiously", "Thought") stay weak.
    token_counts = Counter()
    strong = set()
    runs = list(_capitalized_runs(text))
    for tokens, starts in runs:
        for idx, tok in enumerate(tokens):
            key = _strip_apostrophe(tok).lower()
            if not key or key in _STOPWORDS:
                continue
            token_counts[key] += 1
            # Non-initial occurrence (or any non-leading token in a run) => strong.
            if not (starts and idx == 0):
                strong.add(key)
    # A non-stopword capitalized token that recurs is a proper noun even if it only
    # ever opens sentences (e.g. a protagonist named at the start of each paragraph).
    for key, c in token_counts.items():
        if c >= 2:
            strong.add(key)

    # Pass 2: count full phrases, trimming incidental sentence-initial weak leads.
    phrase_counts = Counter()
    phrase_form = {}  # lowercased phrase -> best original casing
    for tokens, starts in runs:
        toks = list(tokens)
        # Drop a leading token that only appears because it starts a sentence.
        if starts and toks and _strip_apostrophe(toks[0]).lower() not in strong:
            toks = toks[1:]
        name = _normalize_name(" ".join(toks))
        if len(name) < 2:
            continue
        key = name.lower()
        if len(name.split()) == 1 and key in _STOPWORDS:
            continue
        phrase_counts[key] += 1
        if key not in phrase_form or len(name) > len(phrase_form[key]):
            phrase_form[key] = name

    people = []
    places = []
    seen = set()
    for key, n in phrase_counts.most_common():
        if key in seen:
            continue
        name = phrase_form[key]
        words = name.split()
        is_person = _has_person_signal(name, text)
        is_place = _is_place(name, text)
        # Multi-word names must recur to count (kills one-off "Thought Rodney"),
        # unless they carry a place/person signal (keeps one-off "Grimstow City").
        if len(words) > 1 and n < 2 and not (is_person or is_place):
            continue
        # Single tokens must be strong proper nouns or carry a person/place signal.
        if len(words) == 1 and key not in strong and not is_person and not is_place:
            continue
        if n < 2 and len(words) == 1 and not is_person and not is_place:
            continue
        seen.add(key)
        first = _first_mention_sentence(name, sentences)
        if is_place and not is_person:
            places.append({"name": name, "mentions": n, "description": first})
        else:
            people.append({
                "name": name,
                "mentions": n,
                "first_sentence": first,
                "description": first,
            })

    # De-duplicate people whose name is a substring of a longer person name,
    # keeping the most-mentioned spelling as canonical and folding mentions.
    people = _merge_name_variants(people)
    people.sort(key=lambda c: c["mentions"], reverse=True)
    places.sort(key=lambda c: c["mentions"], reverse=True)
    return people, places


def _merge_name_variants(people):
    """Fold "Goldstein" into "Freddy Goldstein", "Louis" stays distinct from "Louie"."""
    by_name = {p["name"]: p for p in people}
    names = sorted(by_name, key=lambda n: len(n), reverse=True)
    removed = set()
    for short in list(names):
        if short in removed:
            continue
        for long in names:
            if long == short or long in removed:
                continue
            # surname containment: "Goldstein" within "Freddy Goldstein"
            if short in long.split() and short != long:
                by_name[long]["mentions"] += by_name[short]["mentions"]
                removed.add(short)
                break
    return [p for n, p in by_name.items() if n not in removed]


def extract_dialogue(text):
    """Return a list of {"speaker", "text"} for quoted lines, attributing speakers."""
    lines = []
    # Match straight or curly double quotes.
    for m in re.finditer(r'[\"“]([^\"”]{2,400}?)[\"”]', text):
        quote = m.group(1).strip()
        if not quote:
            continue
        # Look at a window after the quote for "<Name> said" / "said <Name>".
        tail = text[m.end():m.end() + 80]
        head = text[max(0, m.start() - 80):m.start()]
        speaker = _attribute_speaker(head, tail)
        lines.append({"speaker": speaker, "text": quote})
    return lines


def _attribute_speaker(head, tail):
    """Find a likely speaker name in the text immediately around a quote.

    Pronoun "speakers" (He/She/I/They) carry no identity, so they are rejected in
    favor of Narrator — which, for a first-person story, reads correctly as voiceover.
    """
    window = tail + " " + head
    # "said Rodney" / "Rodney said" / "Goldstein's voice"
    for verb in _SPEECH_VERBS:
        m = re.search(rf"\b{verb}\s+([A-Z][a-z]+)", tail)
        if m and not _is_pronoun(m.group(1)):
            return m.group(1)
        m = re.search(rf"([A-Z][a-z]+)\s+\w*\s*{verb}\b", window)
        if m and not _is_pronoun(m.group(1)):
            return m.group(1)
    m = re.search(r"([A-Z][a-z]+)[’']s\s+(voice|words)", window)
    if m and not _is_pronoun(m.group(1)):
        return m.group(1)
    return "Narrator"


def _is_pronoun(word):
    return word.lower() in {"he", "she", "they", "i", "we", "it", "you", "him", "her", "them"}


def segment_beats(text, n=3):
    """Split the story into ``n`` ordered beats.

    Prefers explicit chapter markers; otherwise splits paragraphs evenly. Each beat
    is summarized by its most substantive sentence (longest non-dialogue sentence).
    """
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = _split_sentences(text)

    # If chapters exist, group by them first.
    chapter_idx = [i for i, p in enumerate(paragraphs) if re.match(r"^\s*(chapter|part|act)\b", p, re.I)]
    if len(chapter_idx) >= n:
        groups = []
        bounds = chapter_idx + [len(paragraphs)]
        for a, b in zip(bounds, bounds[1:]):
            groups.append(paragraphs[a:b])
    else:
        # Even split into n groups.
        size = max(1, len(paragraphs) // n)
        groups = [paragraphs[i:i + size] for i in range(0, len(paragraphs), size)]
        # Collapse trailing extras into the last group.
        if len(groups) > n:
            groups[n - 1:] = [sum(groups[n - 1:], [])]

    beat_names = ["Setup", "Confrontation", "Turn", "Fallout", "Resolution"]
    beats = []
    for i, group in enumerate(groups[:n]):
        blob = " ".join(group)
        summary = _representative_sentence(blob)
        beats.append({
            "name": beat_names[i] if i < len(beat_names) else f"Beat {i + 1}",
            "summary": summary,
            "text": blob,
        })
    return beats


def _representative_sentence(blob):
    """Pick a concise, content-bearing sentence to summarize a block of prose."""
    sentences = _split_sentences(blob)
    # Prefer non-dialogue sentences of moderate length.
    candidates = [s for s in sentences if not s.startswith(('"', "“"))]
    candidates = candidates or sentences
    if not candidates:
        return blob[:160]
    # Score by length but cap so we avoid run-ons.
    best = min(candidates, key=lambda s: abs(len(s) - 140))
    return best[:240].strip()


def infer_tone(text):
    """Return (tone_label, aesthetic_description) inferred from vocabulary."""
    words = re.findall(r"[a-z]+", text.lower())
    wordset = Counter(words)
    scores = {}
    for tone, lex in _TONE_LEXICON.items():
        scores[tone] = sum(wordset[w] for w in lex)
    tone = max(scores, key=lambda t: scores[t]) if scores else "drama"
    if scores.get(tone, 0) == 0:
        tone = "drama"
    return tone, _TONE_AESTHETIC.get(tone, _TONE_AESTHETIC["drama"])


def derive_title(text):
    """Best-effort title: first non-empty line, trimmed to a headline length."""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip obvious meta first lines.
        if line.lower() in ("what i give out", "what do i get back?"):
            continue
        # Use the first sentence of the opening line as a title seed.
        first = _split_sentences(line)
        seed = (first[0] if first else line).strip(' .')
        return seed[:80].title() if seed else "Untitled Story"
    return "Untitled Story"


def analyze(text):
    """Full structured analysis of a manuscript. The one entry point stages call."""
    text = (text or "").strip()
    if not text:
        return _empty_analysis()
    people, places = extract_entities(text)
    dialogue = extract_dialogue(text)
    beats = segment_beats(text, n=3)
    tone, aesthetic = infer_tone(text)

    # Attach each character's strongest spoken line, if any, for voice grounding.
    spoken_by = defaultdict(list)
    for line in dialogue:
        spoken_by[line["speaker"].lower()].append(line["text"])
    for person in people:
        key = person["name"].split()[-1].lower()
        first_key = person["name"].split()[0].lower()
        samples = spoken_by.get(key) or spoken_by.get(first_key) or []
        person["sample_line"] = samples[0] if samples else ""

    return {
        "title": derive_title(text),
        "tone": tone,
        "aesthetic": aesthetic,
        "characters": people,
        "locations": places,
        "dialogue": dialogue,
        "beats": beats,
        "summary": _representative_sentence(text),
    }


def _empty_analysis():
    return {
        "title": "Untitled Story",
        "tone": "drama",
        "aesthetic": _TONE_AESTHETIC["drama"],
        "characters": [],
        "locations": [],
        "dialogue": [],
        "beats": [],
        "summary": "",
    }
