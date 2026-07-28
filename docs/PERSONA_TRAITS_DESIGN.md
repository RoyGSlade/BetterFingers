# Persona traits — design doc

**Status:** proposal, awaiting owner sign-off.
**Required by:** `DESIGN.md` §14 — this adds a field to the persona v2 schema, which is beyond
§11's persona paragraph, so the doc gates the code rather than following it.
**Plan item:** Stage 10.

---

## 1. What exists today

Studio's persona cards show five sliders — Warmth, Directness, Detail, Formality, Confidence.
They render as **empty tracks**, and have since the archetype fabrication was removed.

That fabrication is worth remembering, because it is what this design has to avoid repeating.
`derivePersonaTraits()` used to key numbers off five persona *names* read from mockup 03
(natural / direct / warm / professional / playful) — names that do not exist in this app,
whose real built-ins are True Janitor, Formal, Polished, Unhinged and Pompous 1800s Lord. So
every real persona rendered either a flat 50 or, worse, another persona's numbers, presented
as if measured.

Today `derivePersonaTraits()` reads `persona.traits` if present and reports `null` otherwise,
and `traitsAreUnknown()` exists so the UI can render an honest empty state. **The renderer is
already waiting for this field.** The work is in the schema, the prompt, and the decisions
below.

## 2. Why numbers here, when contacts got prose

`CONTACT_WIZARD_DESIGN.md` §5 argued *against* numeric axes and for prose, on the grounds that
`compose_persona_system_prompt()` consumes prose, so numbers are "a lossy detour on both
ends". That argument still holds. It just does not lead to the same answer here, for one
reason:

**A persona is authored once and reused thousands of times; a contact is authored per person.**
Sliders are a better *authoring* affordance than a blank textarea — they tell you what is
adjustable, which prose does not — and the cost of the numbers→prose detour is paid once per
persona rather than once per person. The reverse held for contacts: the interesting fields
were exactly the ones people leave blank, and an interview drew them out better than five
dials would have.

Both can be true. What must not happen is contacts growing a copy of this trait model — §5 of
that doc still stands.

## 3. The false-precision problem, and what to do about it

A 0–100 slider offers 101 values. A language model can act on perhaps five. Warmth 63 and
warmth 67 produce the same prompt and therefore the same behaviour, and a UI that implies
otherwise is lying with a smaller number of pixels than the archetype presets did.

**Proposal: store 0–100, render in five bands, and show the band.**

| Band | Range | Emits |
|---|---|---|
| very low | 0–19 | an instruction |
| low | 20–39 | an instruction |
| **neutral** | **40–59** | **nothing at all** |
| high | 60–79 | an instruction |
| very high | 80–100 | an instruction |

The slider keeps its full range so it feels continuous and stores exactly what the user set,
but the label beside it reads the band. Dragging from 44 to 56 shows "Neutral" the whole way,
which is the truth.

**Neutral emitting nothing is not a detail.** `compose_persona_system_prompt()` already works
this way for every field it renders — output policy, safety mode, format rules all stay silent
at their defaults, so "a persona carrying only a prompt returns exactly that prompt". A traits
block that always emitted five sentences would break that property for every existing persona
in the app.

## 4. The axes, and the two problems in them

### 4a. `detail` collides with `output_policy`

`output_policy` (preserve / tighten / expand / summarize) already exists, already renders into
the prompt, and already governs length. A `detail` slider is a second control over roughly the
same thing, and they can be set in opposition: detail 90 with output_policy `tighten` is an
instruction to elaborate and an instruction to compress, in one prompt.

**Proposal:** define them as different questions and say so in the prompt.

- `output_policy` governs **length** — how much text comes out.
- `detail` governs **specificity within that length** — whether the supporting particulars the
  speaker gave survive, or get compressed into a general phrase.

They then compose sensibly: tighten + high detail is "short, but keep the numbers". And
`lint_persona()` gains a warning for the genuinely contradictory corner (summarize + very high
detail), which is the existing mechanism for exactly this — non-blocking guidance in the
builder, never a refusal to save.

### 4b. `confidence` is the one axis that can break rule 5

Rule 5 makes stated emotional intensity a preservation invariant, and the same logic covers
stated *commitment*. Turning confidence up on someone else's dictation means writing their
"I think maybe we can ship Friday" as "we can ship Friday" — which is not a tone change, it is
the app making a promise the user did not make.

**Proposal, and the line to hold:** confidence governs *phrasing*, never *claims*. It may
tighten verbal tics ("um", "sort of", a trailing "I guess" used as filler). It must preserve
semantic hedges — "maybe", "I think", "probably", "should", "might" — because those carry
meaning. Every band's phrasing says so explicitly.

That distinction is subtle enough that it should not be taken on trust, which is what §6 is
for. **If the differential does not pass with confidence at 100, this axis does not ship.**
Cutting one slider is much cheaper than shipping one that quietly upgrades hedges to promises.

### 4c. The other three

`warmth`, `directness` and `formality` are register controls with no facts in them. Warmth and
formality overlap in feel but are genuinely independent — warm-and-formal and warm-and-casual
are both real registers — so both stay.

## 5. What the prompt says

Rendered as one block, only for non-neutral axes, in a fixed axis order so the same persona
always produces the same prompt:

```
PERSONA TRAITS (how this persona should sound; the persona's own instructions
above take precedence where they conflict):
- <axis instruction>
- <axis instruction>
These affect wording and register only. They must not change the meaning, the
facts, or the stated intensity of the message.
<PRESERVATION_CLAUSE>
```

Two deliberate choices in that wrapper:

**The persona's own prompt wins.** A user who wrote "You are a blunt editor" and then dragged
warmth to 90 has written a contradiction, and the free text is the more specific, more
considered statement of intent. A slider silently overriding hand-written instructions is the
worse failure — it would make the prompt box feel unreliable.

**The same `PRESERVATION_CLAUSE` delivery signals and audience carry.** Traits are the third
thing that can change the words a user sends, and rule 5 does not get a weaker version because
the input is a slider.

### Draft band phrasings

Numbers are never mentioned; the model gets the instruction, not the value.

| Axis | very low | low | high | very high |
|---|---|---|---|---|
| warmth | Keep the tone impersonal and businesslike. | Lean cool and matter-of-fact. | Lean warm and personable. | Be notably warm and encouraging. |
| directness | Soften requests and criticism; prefer indirect phrasing. | Cushion direct statements a little. | Be direct; lead with the main point. | Be blunt. Lead with the point and cut hedging language that carries no meaning. |
| detail | Keep supporting explanation to a minimum. | Explain sparingly. | Keep the supporting specifics the speaker gave. | Keep every specific the speaker gave — names, numbers, times — in full. |
| formality | Use casual, conversational language and contractions. | Lean informal. | Lean formal. | Use formal language; avoid contractions and slang. |
| confidence | Keep the speaker's qualifiers, and phrase tentatively. | Phrase a little more tentatively. | Phrase crisply and without filler, but keep every qualifier the speaker used. | Phrase assertively and cut filler. Never remove or weaken a hedge ("maybe", "I think", "probably") — those carry meaning. |

Note `detail`'s phrasing throughout: *the specifics the speaker gave*. Never "add detail".
An axis that could invite invention is an axis that breaks rule 5 by construction.

## 6. Rule 3, and the trap this feature sets

Rule 3 says emotion is presented as an uncertain signal, never a diagnosis. Traits are clear of
it — "warmth" here is an attribute of a **persona the user configured**, not a claim about the
user's state. Nothing is inferred about anybody.

But this feature creates a specific, tempting way to violate rule 3 later, and the boundary
belongs in writing now, exactly as the recipient boundary did for contacts:

> Traits are **set by the user and never inferred**. Nothing may derive a trait value from
> speech signals, transcripts, draft history, or edit patterns. `arousal`, `urgency` and
> `hesitation` already exist and are numbers on the same 0–1 scale — wiring "detected arousal"
> into a confidence trait would be a diagnosis wearing a slider, and is the exact behaviour
> rule 3 forbids.

If this is signed off, that paragraph lands in `ACCOMPLISH.md` §3 rule 3 alongside the first
line of trait code, the way the audience clarification landed with contacts.

## 7. Why there is no `use_persona_traits` toggle

Delivery signals and audience both ship behind a default-off profile flag, because both are
things the *app* adds to the prompt on the user's behalf.

Traits are not. They are the user editing their own persona, and the default is neutral, which
emits nothing. **The feature is opt-in by construction and per-persona** — there is no state in
which it acts without someone having dragged a slider. A global flag would be a second switch
for something already switched off.

The gate still applies to the *rendering*: §8.

## 8. The gate

`delivery_preservation.py` already runs a differential on two axes. Traits become a third,
reusing the same scoring — the same probe transcripts, the same intensity markers, the same
baseline-vs-variant attribution that separates "the model does this anyway" from "the feature
made it do this".

Variants: **all-neutral** (baseline), **warm/indirect/formal** and **blunt/confident/terse** —
the two corners most likely to editorialise, in opposite directions.

Acceptance, all three required:

1. An all-neutral persona composes to a prompt **byte-identical** to today's. Anything else is
   a change to every existing persona in the app.
2. The traits differential passes on a real model, the same standard delivery and audience
   were held to.
3. It passes **with confidence at 100 specifically**. If it does not, `confidence` is cut and
   the remaining four ship (§4b).

## 9. Migration and compatibility

- `normalize_persona()` fills `traits` with neutral, like `voice` and `format`, so every
  persona has a complete dict regardless of vintage.
- Absent, null, partial and all-neutral `traits` must all compose identically — to nothing.
- Built-in personas ship neutral. No existing persona changes behaviour on upgrade, which is
  rule 7's requirement, not a nicety.
- The wizard's Advanced section gains the five sliders. The Foundry does **not** set traits
  from its interview: that would be the model choosing values the user never saw, which is the
  §6 boundary in a different coat.

## 10. Decisions needed before code

1. **`confidence` — ship it, or cut it now?** §4b argues it can ship *if* the gate passes with
   it at maximum. The alternative is cutting it up front and shipping four axes, which is
   safer and loses a slider the mockup shows.
2. **`detail` vs `output_policy` — the split in §4a, or drop `detail`?** They overlap. The
   proposed split is defensible but subtle; dropping `detail` leaves `output_policy` as the
   single length control and loses nothing the app cannot already do.
3. **Band labels beside the sliders (§3)** — this is a visible change to Studio's persona
   cards, which are pixel-specified in mockup 03. Worth it for honesty, but it is a mockup
   deviation and yours to approve.

## 11. Explicitly out of scope

- Inferring traits from anything. See §6.
- Traits on contacts. `CONTACT_WIZARD_DESIGN.md` §5 stands.
- Per-draft trait overrides. Traits belong to a persona; a per-utterance dial is a different
  feature with a different friction budget.
- Any trait that encodes a fact rather than a register (length, language, terminology). Those
  are existing fields.
