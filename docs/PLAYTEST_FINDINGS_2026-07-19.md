# Playtest findings — 2026-07-19 (owner, solo, wave-5 build)

First human playtest of the Infinite Stacks build (branch
`feat/infinite-stacks-wave5`). Verdict: **mechanics work, presentation is
unacceptable**. The player did not want to keep playing. This document is
the canonical input to wave 6; items are numbered for task references.

## A. Cards — layout and behavior

- **A1.** Hand is rendered on the LEFT side of the screen. It must be
  center-bottom (standard card-game hand position).
- **A2.** Cards have no card anatomy. Required layout, top-down: **title →
  art slot → keywords → description → effect**. Cards need a frame and a
  card backing. (Art exists: `gameassets/.../03_Cards_and_UI/` has
  Charm/Scheme/Bonk frames + alternates in `05_Composites_and_Extras/`.)
- **A3.** No affordance for playability — nothing signifies WHEN a card can
  be used. Playable-now must be visually obvious; unplayable must be
  visibly inert.
- **A4.** Clicking a card appears to instantly discard/play it. Click must
  select/inspect; playing requires an explicit target + confirm step.
- **A5.** No visibility into what is "useful now" or currently active —
  effects that last "until end of turn" (or any duration) need a visible
  active-effects tray.

## B. Onboarding — none exists

- **B1.** No rules are explained anywhere. A first-time player has no idea
  what to do, including the most basic action: **how to move**.
- **B2.** Needs: a first-run rules overlay (move/breach costs, Energy,
  cards, combat, reactions), a persistent contextual hint line ("You have
  5 Energy — click an adjacent room to move (1) or a fogged edge to
  breach (3)"), and an always-available help control.

## C. Exploration UX

- **C1.** Cannot click rooms adjacent to the starting location to move or
  breach. Movement must be click-the-map-tile driven with the Energy cost
  shown at the point of click and a confirm.

## D. Character information

- **D1.** No character sheet. Health shows only a tier word ("Healthy") —
  meaningless without numbers. HP must be shown as numbers (and bar),
  plus attributes, skills, Energy, statuses, and abilities, in a
  persistent panel.
- **D2.** Inventory is buried below the fold and context-free ("you have
  7 slots, good luck"). It belongs inside the character panel as a visual
  slot grid.

## E. Card content quality — the core design complaint

> "A card should only be given when it's earned and should be something
> actually cool — not a basic ability like 'I look around.'"

- **E1.** Basic capabilities must become **abilities** (passive, or
  triggered when their condition occurs), listed on the character sheet —
  NOT cards. Named offenders: `read_the_room`-type observation cards,
  `veteran_instinct` (benefit totally unclear).
- **E2.** Filler cards with no real mechanics must be cut or redesigned
  with explicit rules text: `plain_warning` ("records when a warning is
  given" — means nothing), `trophy_note` (worthless), `signature_moment`
  (does nothing).
- **E3.** Every card must state its actual mechanics on its face: numbers,
  targets, duration. `bestiary_page` is a cool concept with zero mechanic
  info — the player wanted to know why it's good and couldn't.
- **E4.** `family_notes` must NOT consume a carry slot — it's a few pages,
  not equipment. (This is also a spec violation: infinite_stacks.md §13.6
  says quest knowledge doesn't consume ordinary slots.)

## F. Map presentation

- **F1.** The player's NAME string fills the room tile. Replace with a
  **token**: player picks an avatar (art exists in the asset pack), and
  its hue is adjusted to the player's chosen color.
- **F2.** Party tracker is functionally okay but visually poor.

## G. Overall

- **G1.** The whole UI reads as clunky and ugly; no key art, no theme.
  The asset pack (`gameassets/Spellcheck_and_Sorcery_Art_Pack/`) is
  entirely unused: key art, game icon, map art, enemy art, card frames,
  avatars, victory/defeat tableaus.

## Spec §26.4 debrief mapping

- "Which decision felt obvious or fake?" → E1/E2 (cards that do nothing).
- "When were you waiting without anything useful to do?" → B1/C1 (didn't
  know how to act at all).
- Best-story / responsibility questions unanswerable — session ended at
  the UI wall. **The UI is currently the gate on all Definition-of-Fun
  evaluation.**
