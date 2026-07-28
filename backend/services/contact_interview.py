"""The contact interview — a short, model-run conversation that ends in a
contact the user approves (Stage 11b, ``docs/CONTACT_WIZARD_DESIGN.md`` §4).

Shape borrowed from the Persona Foundry, deliberately: navigation is
**deterministic and rule-based**, and the model is invoked only at compile time,
where generation is actually the point. That is not just consistency — it is
what makes the design's hard constraint fall out for free:

    "If no model is loaded, the wizard must degrade to the plain form rather
    than blocking contact creation — the feature cannot become a reason the
    user is unable to use the app."

Because the questions need no model, a user with nothing loaded still gets the
whole interview; only the polish at the end is missing. ``compile_contact``
falls back to assembling the answers into prose itself, so their answers are
kept rather than thrown away and re-asked as a form. That is strictly better
than the doc's wording, which assumed the interview itself needed the model.

**Deliberately lighter than the Foundry on pushback.** The Foundry challenges
vague answers because a vague persona is useless. A vague contact is not: "my
brother" is a complete answer. Rule 2's friction budget (§10 of the design doc,
and ``ACCOMPLISH.md`` §3) says a feature heavy enough to go unused protects
nobody, so the only thing this insists on is a name — which is not friction, it
is the minimum for a record the user has to pick out of a list later.

Nothing here persists anything. The interview is a conversation, not a
recording; the compiled result goes back to the caller for review and only
``ContactStore.create`` writes.
"""

from __future__ import annotations

from typing import Optional

from backend.services.contacts import MAX_NAME_LEN, MAX_TEXT_LEN

# Question order matters: name first so an interview abandoned after one answer
# still produces something saveable.
CONTACT_QUESTIONS = [
    {
        "id": "name",
        "kind": "text",
        "required": True,
        "prompt": "Who is this? A name or a nickname is fine.",
    },
    {
        "id": "relationship",
        "kind": "text",
        "required": False,
        "prompt": "How do you know them?",
    },
    {
        "id": "tone",
        "kind": "text",
        "required": False,
        "prompt": "How do you normally talk to them — formal, casual, blunt, warm?",
    },
    {
        "id": "boundaries",
        "kind": "text",
        "required": False,
        "prompt": "Anything they should never be told, or that always needs spelling out?",
    },
    {
        "id": "persona",
        "kind": "text",
        "required": False,
        "prompt": "Is there a persona that already sounds right for them? Leave blank if not.",
    },
]

QUESTION_BY_ID = {q["id"]: q for q in CONTACT_QUESTIONS}

PUSHBACK_NAME_REQUIRED = "I need something to call them — a first name or a nickname is fine."


def new_session() -> dict:
    return {"cursor": 0, "answers": {}, "done": False}


def next_prompt(session) -> Optional[dict]:
    """The question to render now, or None when the interview is complete."""
    if not isinstance(session, dict) or session.get("done"):
        return None
    cursor = int(session.get("cursor", 0))
    if cursor < len(CONTACT_QUESTIONS):
        question = dict(CONTACT_QUESTIONS[cursor])
        question["index"] = cursor
        question["total"] = len(CONTACT_QUESTIONS)
        return question
    return None


def submit_answer(session, answer) -> dict:
    """Advance the interview by one answer, mutating ``session`` in place.

    Returns ``{"pushback": str|None, "done": bool}``. An optional question
    accepts a blank answer as "no" and moves on — there is no separate skip
    verb to discover, because a user who has nothing to say will just press
    send on an empty box.
    """
    if not isinstance(session, dict):
        return {"pushback": None, "done": False}
    session.setdefault("answers", {})

    cursor = int(session.get("cursor", 0))
    if cursor >= len(CONTACT_QUESTIONS):
        session["done"] = True
        return {"pushback": None, "done": True}

    question = CONTACT_QUESTIONS[cursor]
    text = str(answer or "").strip()

    if question["required"] and not text:
        # The one thing worth insisting on: a record with no name cannot be
        # picked out of a list later.
        return {"pushback": PUSHBACK_NAME_REQUIRED, "done": False}

    session["answers"][question["id"]] = text
    session["cursor"] = cursor + 1
    if session["cursor"] >= len(CONTACT_QUESTIONS):
        session["done"] = True
        return {"pushback": None, "done": True}
    return {"pushback": None, "done": False}


# --- Compile -----------------------------------------------------------------

COMPILE_INSTRUCTIONS = (
    "You are turning a short interview about a person into guidance for rewriting "
    "messages addressed to them.\n"
    "\n"
    "Write exactly two sections, each on its own line, using these labels:\n"
    "TONE: one or two sentences describing how to speak to this person.\n"
    "NOTES: one or two sentences of anything else worth knowing.\n"
    "\n"
    "Rules:\n"
    "- Use only what the interview says. Do not invent facts about this person.\n"
    "- Describe how to write, not who they are.\n"
    "- If a section has nothing to say, write the label followed by nothing.\n"
)


def build_compile_prompt(answers) -> str:
    """The interview, rendered for the model.

    The person's NAME is deliberately not included. The model's job is to turn
    'how do I talk to them' into prose about register and word choice, and it
    can do that without being told who they are — so the name never enters a
    prompt, and therefore never enters whatever the model layer logs or caches.
    """
    answers = answers if isinstance(answers, dict) else {}
    lines = []
    for label, key in (
        ("Relationship", "relationship"),
        ("How they are normally spoken to", "tone"),
        ("Boundaries and things to spell out", "boundaries"),
    ):
        value = str(answers.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    if not lines:
        lines.append("(The interview collected nothing beyond a name.)")
    return f"{COMPILE_INSTRUCTIONS}\nInterview:\n" + "\n".join(lines)


def parse_compile_response(text) -> dict:
    """Pull TONE:/NOTES: out of a model response.

    Tolerant by design: a model that answers with only one label, or wraps the
    labels in markdown, still yields something usable. Anything it says outside
    the two labels is discarded rather than guessed at.
    """
    tone_lines: list[str] = []
    notes_lines: list[str] = []
    current = None
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip().lstrip("*# ").strip()
        upper = line.upper()
        if upper.startswith("TONE:"):
            current = tone_lines
            # lstrip again after the label: a model that writes "**TONE:**"
            # leaves the closing asterisks attached to the content.
            line = line[5:].strip().lstrip("*: ").strip()
        elif upper.startswith("NOTES:"):
            current = notes_lines
            line = line[6:].strip().lstrip("*: ").strip()
        elif current is None:
            continue
        if line and current is not None:
            current.append(line)
    return {
        "tone_guidance": " ".join(tone_lines).strip()[:MAX_TEXT_LEN],
        "notes": " ".join(notes_lines).strip()[:MAX_TEXT_LEN],
    }


def compile_without_model(answers) -> dict:
    """Assemble the answers into contact fields with no model involved.

    Used when no model is loaded, and when generation fails. It keeps the user's
    own words verbatim, which is a *worse* summary and a *better* record: the
    fallback for "the model could not help" should never be "your answers are
    gone".
    """
    answers = answers if isinstance(answers, dict) else {}
    tone = str(answers.get("tone") or "").strip()
    boundaries = str(answers.get("boundaries") or "").strip()
    return {
        "tone_guidance": tone[:MAX_TEXT_LEN],
        "notes": boundaries[:MAX_TEXT_LEN],
    }


def compile_contact(session, generate=None) -> dict:
    """Turn a finished interview into a contact for the user to review.

    ``generate`` is a ``(prompt) -> str`` callable; omit it (or let it fail) and
    the deterministic fallback runs instead. Returns
    ``{"contact": {...}, "used_model": bool, "warnings": [...]}``.

    Nothing is saved here. The compiled result is always shown before saving and
    every field stays editable — a wizard the user cannot overrule is a wizard
    that guesses wrong permanently (design doc §4).
    """
    answers = (session or {}).get("answers") if isinstance(session, dict) else None
    answers = answers if isinstance(answers, dict) else {}

    name = str(answers.get("name") or "").strip()[:MAX_NAME_LEN]
    relationship = str(answers.get("relationship") or "").strip()[:MAX_NAME_LEN]
    persona = str(answers.get("persona") or "").strip()[:MAX_NAME_LEN]

    warnings: list[str] = []
    used_model = False
    fields = compile_without_model(answers)

    if callable(generate):
        try:
            response = generate(build_compile_prompt(answers))
            parsed = parse_compile_response(response)
            # Only accept the model's version if it actually said something.
            # A blank response must not overwrite the user's own words with "".
            if parsed["tone_guidance"] or parsed["notes"]:
                fields = {
                    "tone_guidance": parsed["tone_guidance"] or fields["tone_guidance"],
                    "notes": parsed["notes"] or fields["notes"],
                }
                used_model = True
            else:
                warnings.append("The model returned nothing usable, so your own answers were kept.")
        except Exception as exc:  # noqa: BLE001 - any generation failure degrades
            warnings.append(f"Could not reach the model ({exc}); your own answers were kept.")

    return {
        "contact": {
            "name": name,
            "relationship": relationship,
            "notes": fields["notes"],
            "tone_guidance": fields["tone_guidance"],
            "preferred_persona": persona or None,
        },
        "used_model": used_model,
        "warnings": warnings,
    }
