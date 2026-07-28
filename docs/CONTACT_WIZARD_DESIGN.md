# Contacts — design doc

**Status:** signed off; **landed** (Stage 11, 2026-07-27).
**Landed:** the store, the interview, the routes, privacy coverage, the optional `contact_id`
on drafts, the audience prompt block, and the UI. See §4a and §7a for what implementation
changed about this design.

**Both preservation gates PASS 3/3 on a real model** (Gemma 4 12B Q4, 2026-07-27) — delivery
and audience. `use_audience_context` and `use_delivery_signals` nevertheless remain **off**:
the gate is the evidence, flipping the default is the owner's decision.

**Required by:** `DESIGN.md` §14 ("each returns to the table one at a time, each with its own
design doc"). Contacts are new product surface, not part of §11's incremental UI path, so
this doc gates the code rather than following it.

**Owner decisions already taken** (see session of 2026-07-26):

- Audience model: **full recipient/contact model**, chosen over the cheaper
  audience-label-on-ContextSession option.
- Contact creation: **a wizard run by the local model**, not a form.

---

## 1. Why this exists

BetterFingers can already change *how* a message reads — personas do that. What it cannot do
is change how it reads **for the person receiving it**. "I'll be there around six" to a
partner and to a client are different messages, and today the app has no way to know which
one it is writing.

The gap is total, not partial: repo-wide there is no contact, recipient, or audience concept
anywhere. Three separate UI surfaces currently *imply* one — Talk's "Destination", Library's
destination filter, Studio's "preferred destinations" — and all three were fabrications
backed by no field. All three have since been replaced by the real thing (§6).

## 2. The rule-2 boundary — read this before writing code

`ACCOMPLISH.md` §3 rule 2:

> **Context is explicit.** The user selects or pastes context and can see, remove, and expire
> it. We do not scrape conversations or silently monitor text fields.

A "recipient" concept is the single most tempting place in this product to violate that,
because the obvious implementation is to read the focused window's title, or the active chat,
or an OS contact list, and infer who is being addressed. **That is the prohibited behaviour
with extra steps.**

The binding clarification, which must land in `ACCOMPLISH.md` §3 alongside the first line of
contact code:

> A contact is **created by the user, named by the user, and selected by the user**. The app
> never infers a recipient — not from window titles, not from the OS address book, not from
> message history, not from anything the user did not explicitly hand it. A contact being
> *available* never means it is *applied*; applying one is always a user action.

`injection_pacing.detect_active_app_key()` identifies the focused **application** and is used
solely to choose keystroke pacing. It must never be promoted into a recipient signal — it
does not know a person, and on Wayland it returns nothing at all.

## 3. Shape of the thing

A contact is a small, user-authored record. It is deliberately closer to a persona than to an
address book entry: it describes **how to speak to someone**, not how to reach them. There is
no phone number, no email, no handle — BetterFingers does not send anything anywhere on its
own, so storing routing details would be collecting data the app has no use for.

| Field | Type | Notes |
|---|---|---|
| `id` | str | Generated. Never derived from the name. |
| `name` | str | What the user calls them. Free text; no uniqueness requirement beyond id. |
| `relationship` | str | "manager", "younger brother", "the guild" — free text, not an enum. An enum here would be a guess about the user's life. |
| `notes` | str | Anything the user wants the model to know. The wizard fills this. |
| `tone_guidance` | str | Prose, not axes. See §5. |
| `preferred_persona` | str \| null | Optional link to an existing persona. |
| `created_at` / `updated_at` | ISO-8601 | |

Storage mirrors `PersonaLearningStore`: a single JSON file under the user profile, loaded
lazily, never written outside an explicit user action. It is covered by the existing privacy
wipe (§7.14) from day one — a contact list that survives "delete my data" would be a serious
breach of the product's central promise.

## 4. The wizard

The owner's direction: creation is an interview conducted by the local model, not a form.
This is the right instinct — the interesting fields (`notes`, `tone_guidance`) are exactly the
ones users leave blank when shown an empty textarea, and exactly the ones a few good questions
can draw out.

**Reuse the Persona Foundry pattern wholesale.** `routes_foundry.py` already implements this
shape and it is proven in the product:

```
POST /contacts/interview/start     -> { session_id, question }
POST /contacts/interview/answer    -> { question } | { ready: true }
POST /contacts/compile             -> { contact }        (review before save)
POST /contacts                     -> { saved }          (explicit user action)
```

Session handling copies Foundry's: in-memory, capped, evicted when full. Nothing is persisted
until the user approves the compiled result — the interview is a conversation, not a
recording.

**Interview shape** (4–6 questions, one at a time):

1. Who is this? *(name)*
2. How do you know them? *(relationship)*
3. How do you normally talk to them — formal, casual, blunt, warm?
4. Anything they should never be told, or that always needs spelling out?
5. Is there an existing persona that already sounds right for them?

The model's job is to turn those answers into `notes` and `tone_guidance` prose, then hand it
back for review. **The compiled result is always shown before saving**, and every field stays
editable — a wizard the user cannot overrule is a wizard that guesses wrong permanently.

**Constraint worth stating explicitly:** the interview runs on the local model like everything
else. If no model is loaded, the wizard must degrade to the plain form rather than blocking
contact creation — the feature cannot become a reason the user is unable to use the app.

### 4a. What implementation changed (2026-07-27)

**The interview needs no model at all.** Copying the Foundry's shape brought a property this
doc did not anticipate: Foundry's interview *navigation* is deterministic and rule-based, and
the model is invoked only at compile. Contacts inherit that, so "degrade to the plain form"
turns out to be unnecessary — a user with nothing loaded gets the whole interview, and only
the final polish is missing. `compile_contact` assembles their answers into the fields itself.

That is strictly better than what this doc asked for. Falling back to a blank form would
discard answers the user had just given and make them type it all again; the fallback for
"the model could not help" should never be "your work is gone".

**Compile does not boot a model.** The Foundry calls `ensure_ready()` and waits, which is
right for a feature called "Build with AI". Spinning up a multi-gigabyte model to write two
sentences about someone's brother is not — §10's friction budget applies to latency as much
as to prompts. So compile uses a model that is *already up* and otherwise uses the
deterministic path, reporting which happened via `used_model`. `wait_for_model` is there for
a caller that explicitly wants to wait.

**The person's name never reaches the model.** `build_compile_prompt` sends relationship,
tone and boundaries — not the name. The model's job is to turn "how do I talk to them" into
prose about register, and it can do that without being told who they are. The same holds at
rewrite time: `audience_block()` renders a contact for the prompt and deliberately omits both
name and id. A name in a prompt is a name in whatever the model layer logs or caches.

**Routing details are refused, not merely unsupported.** `sanitize_contact` drops unknown
keys *and returns what it dropped*, so a client that tries to stash an email or a phone number
is told rather than quietly succeeding. §8's "out of scope" is enforced in code.

**Hitting the cap is an error, not an eviction.** `PersonaLearningStore` evicts oldest-first
when full because examples are derived data. Contacts are authored, so the store refuses
instead: losing a learned example costs a little quality, losing a contact someone sat through
an interview to build is losing their work.

## 5. Tone guidance is prose, not sliders

Tempting to reuse the 5-axis trait model here. Don't — not yet.

Those axes are currently renderer-only fiction with no backend field, and making them real is
its own design doc (persona traits, Stage 10). Shipping a second, contact-level copy of an
unbuilt model would mean two speculative schemas to reconcile later.

Prose also happens to be what the prompt actually wants. `compose_persona_system_prompt()`
consumes prose; a numeric axis would have to be rendered back into words before it reached the
model, so the numbers would be a lossy detour on both ends.

If traits become real for personas, contacts can adopt them in a follow-up — with the persona
version already proven.

## 6. Where it surfaces

- **Talk context panel** — a recipient picker, defaulting to none. "None" is a first-class
  state, not an empty slot to be filled: most dictation has no particular audience, and a UI
  that nags for one trains people to pick wrong. **Landed** as "Writing to". The note beneath
  it is blank when nothing is selected — the absence of a note *is* the none state, and a
  permanent line explaining it would be nagging by other means.
- **Status bar** — the Target-app cell gains a sibling only once a contact is *applied*.
  `statusLabelFor()` returns null rather than "none", so nothing is rendered until then: an
  empty state occupying permanent space is a slot asking to be filled.
- **Library** — filter by contact. **Landed**, replacing the `destination` mapper, which read
  `draft.destination_name || draft.destination?.name` — neither field has ever existed, so it
  was always null and the filter above it always matched everything.
- **Studio** — **landed, but read from the other end.** This section proposed "a persona may
  name a default contact". Personas have no such field and adding one would have created a
  second place to keep the relationship in step. Contacts already carry `preferred_persona`,
  so Studio now shows *which contacts prefer this persona* — the same relationship, read from
  the end that actually stores it. That also retires the third destination fabrication
  (`preferred_destinations`, rendered as Discord/Gmail/Slack icons).

### 6a. Creation is the fifth guided flow

The wizard runs on the shell built in stage 13 (`docs/ui/SIGNAL_DESK_GUIDED_FLOWS.md` §4d),
which is what that section reserved it for. Four steps like every other flow: Add a contact →
A few questions → Review & save → Saved.

**"Just save the name" sits on the first screen**, beside "Answer a few questions", rather than
being buried as a skip link. Creating a contact from a name alone is the supported path; the
interview is an offer to make it better. A name typed there is submitted as answer one rather
than being asked again — a wizard that re-asks what it was just told reads as not listening.

**The three placement maps are kept in agreement by a test.** Talk's picker, Library's filter
and Studio's preferred contact are three views of one backing field; while it did not exist
they were three fabrications called "Destination". `parityGates.test.mjs` asserts they never
disagree, and it caught exactly that during this work — Library and Studio were rewired while
Talk's entry still read "Destination (REMOVED)".

## 7. How it reaches the model

Additive and optional, exactly like delivery signals (rule 6):

- `drafts` gains an optional `contact_id` (nullable, defaults null).
- `process_fast_lane` gains an optional `audience=None` kwarg carrying the compiled
  `tone_guidance` + `notes`.
- The prompt block states the audience as **user-declared context**, never as an inference,
  and carries the same preservation clause the delivery-signal block does: audience may inform
  register and word choice; it must not change meaning, facts, or stated intensity.

**Ships default-off behind a profile toggle**, and the gate is the same instrument built for
delivery signals: `delivery_preservation.py`'s differential, extended with audience as a third
axis. The first real run of that probe found the main cleanup path already drops stated
numbers — a contact prompt must not be allowed to make that worse, and right now we would not
be able to tell without the baseline comparison.

### 7a. What landed (2026-07-27)

- `drafts` gained a nullable `contact_id`, and `process_fast_lane` an optional
  `audience_summary=None` — both additive (rule 6).
- Two profile keys: `use_audience_context` (default **false**, gating the prompt) and
  `active_contact_id` (default null). The selection is **sticky like `current_preset`**, per
  §10 — rule 2 is about who decides, not how often they are interrupted.
- **The two are gated separately, deliberately.** The toggle governs whether a contact reaches
  the *prompt*; the draft records the user's standing selection either way. That is what makes
  Library filtering and retroactive application (§9.1) possible while the prompt side is still
  off — speak first, attribute after.
- The prompt block states the audience as *"context the user explicitly selected, not
  something detected or inferred"*. That sentence is load-bearing: this is the one place a
  future contributor could read audience as something the app worked out for itself.
- It also forbids **inventing greetings and sign-offs** — the most likely way an audience
  prompt breaks rule 5 in practice is deciding a message to your manager should open with "Hi
  Priya," and close with "Best", words the speaker never said.
- Same `PRESERVATION_CLAUSE` as delivery signals. Rule 5 does not get a weaker version because
  the input is prose instead of numbers.

**Still outstanding before the default can flip:** `delivery_preservation.py` does not yet
carry audience as a third axis. Until it does, `use_audience_context` stays off — the same
standard delivery signals are held to.

## 8. Explicitly out of scope

- Any form of automatic recipient detection. See §2.
- Importing contacts from the OS, a phone, or any account.
- Storing addresses, handles, or any means of reaching a person.
- Per-contact message history. Library already stores drafts; a second per-person store would
  be a surveillance-shaped feature the product does not need.

## 9. Resolved (owner, 2026-07-26)

1. **Retroactive application: yes.** A contact can be applied to an existing draft, re-cleaning
   it for a different person. This matters more than it looks: it means choosing a contact is
   never a prerequisite for dictating, only an optional improvement afterwards — which is what
   keeps §10's friction budget affordable.
2. **Contact beats persona on tone**, and the UI says so. The contact is the more specific
   choice, and a user who picked a person expects that to win.
3. **The wizard may update an existing contact from a correction** ("that was too formal for
   her"), reusing persona-learning's consent flow — an approved edit becomes guidance only
   after an explicit user action, never silently.

## 10. Friction is a design constraint, not an afterthought

Owner note, recorded because it binds every decision above:

> "too much friction in the app can reduce usage"

This is the real risk to this feature. Rule 2 requires everything be explicit, and the naive
reading of "explicit" is a prompt before every dictation — which would make the fastest part
of the product slower, and would train people to dismiss it. A contact feature that makes
dictation heavier will simply go unused, and an unused feature protects nobody.

The resolution: **explicit means the user chose it once, not that the user is asked every
time.** Concretely, binding on implementation:

- **No contact is the default and always fine.** The picker never blocks, never modals, never
  nags. Most dictation has no particular audience.
- **Selection is sticky, not per-utterance.** Choosing a contact sets it until it is changed,
  the way the active persona already works. Re-confirming a standing choice is friction with
  no safety benefit — the user already made the decision.
- **Retroactive application (§9.1) is what makes this affordable.** Speak first, attribute
  after, only when it is worth it.
- **The wizard is optional, not a gate.** Contacts can be created with a name alone; the
  interview is an offer to make one better, and quitting halfway must still save something
  usable.
- **One consent surface, not many.** Contacts inherit the existing privacy wipe and the
  persona-learning consent flow rather than introducing new prompts of their own.

Where friction and rule 2 genuinely conflict, rule 2 wins — but the conflict is usually a
sign the design is asking at the wrong moment, not that a confirmation is missing.
