# Playtest findings — 2026-07-20 (owner, solo, wave-6 build)

Second human playtest, on the wave-6 "playtest response" build (PR #71).
Documentation only — no fixes authorized yet for most items; the owner is
supplying design direction separately (see the live `dice-ui-overhaul`
session working from `designhelp/uioverhaul.zip`, which owns the static
client at the time of writing). Items numbered J1… for task references,
continuing from the 07-19 doc's A–G series.

**Session-ending bug: the player could not move at all (J12). Review ended
there.**

## J1. Joining flow

Joining sucks. Players must NOT be asked for a hero name while joining a
room — joining should be minimal; hero identity belongs later, in the
creation flow.

## J2. Attributes and skills — no weight, no meaning

The player's attributes and skills neither look nor feel important, and
even if they did, the player has no idea what any of them do. Every
attribute and every skill needs a description surfaced in the UI (what it
governs, when it gets rolled).

## J3. Backgrounds — generic and underexplained

- Background naming is generic/lame.
- The skills each background grants are probably cool, but they don't look
  it and don't describe themselves.
- Each background's ability must have its own UNIQUE NAME, presented as
  that named power — never under the generic label "signature ability."

## J4. Dice — players want to roll

Players will want to roll their own dice. The current roll presentation is
a placeholder ("in progress UI is also in progress"). Direction already in
motion: the `dice-ui-overhaul` session is scoped for 3D physics dice with
shared rolls and custom dice presets.

## J5. Avatar tokens — presets good, customization wanted

The preset avatar tokens are badass. Wanted on top:

- Upload your own image, with crop / shrink / expand controls.
- A visual guide overlay showing exactly what will be visible given the
  game's token scale and cutout method.

## J6. Color selection — concept fine, execution bad

- Selected color should render as a RING BORDER around the token, not the
  current presentation.
- Not a flat color: gradient-based with glow, plus a few spice options so
  it never reads as a nasty solid fill.
- Animation options for the ring: pulse, race-around, flicker, neon,
  speed variants — little things that make it feel "you."
- Borders adjust dynamically as the player tweaks.
- Preset saving: player can save their token/ring setup as a preset,
  downloadable to their device as a small JSON ("memory card" model) that
  the game can re-read next session; host-side saving also allowed.

## J7. Hero-build card choice is fake

- `careful_approach` and `steady_nerve` are both too vague to be useful.
- The UI says "select two" and there are exactly two options — that is not
  a choice.
- One of them reads like "look around" again (the exact E1 offense from
  the 07-19 findings); the other might be card-worthy if reframed as a
  calm effect — e.g. a benefit spent on an important roll when needed.

## J8. BUG — hero name input drops focus every keystroke

On the creation screen, clicking into the hero name box allows exactly one
typed letter before the field kicks the player out. (Likely a re-render
stealing focus on every state change.) Must be fixed whenever the creation
screen is next touched.

## J9. Preview card is stat soup

The build-preview card is just a group of stats — nearly worthless for a
game where roleplaying is the emphasis. The preview should sell the
character, not the spreadsheet.

## J10. Cards overall — scratched, pending owner direction

Owner's call, verbatim intent: scrap the current cards for now. The card
pool as designed misses the game's taste; the owner takes responsibility
for not yet supplying enough taste/ideas/direction, and will provide it.
**Do not redesign the card pool again until that direction lands.** (The
cards-vs-abilities structure from wave 6 stands; this is about the card
CONTENT.)

## J11. Character sidebar — positive

The character sidebar layout is laid out pretty well for a basic setup.
Keep its bones through any restyle.

## J12. BUG (session-ending) — player cannot move at all

From the starting room, the hint reads: "No moves available from here
right now — Pass to let the world round advance, or Inspect your current
room." — and BOTH Inspect and Pass are unavailable for selection. The
player is completely locked out of the game loop from turn one. Likely
suspects (unverified — no code investigation done this pass): the
legal-actions projection returning empty/stale for the entrance room, the
new per-connector move/breach cost gating (wave-6 `legalActions`
move_costs/breach_costs) not matching what the map screen expects, or the
hint line reading a different legality source than the buttons. Highest
priority item in this document.

## Status of the 07-19 findings after this pass

- Verified better: avatar tokens (F1 — "badass"), character sidebar bones
  (D1 partial credit, J11).
- Regressed/still failing in spirit: card content quality (E-series → J7,
  J10 — structure fixed, content still misses).
- New territory: joining flow (J1), dice feel (J4), token customization
  (J5/J6), creation-screen focus bug (J8), movement lockout (J12).
