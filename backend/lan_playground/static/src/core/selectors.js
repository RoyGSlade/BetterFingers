// Pure derived-view functions over store state (infinite_stacks.md S22.3:
// "Rendering functions receive state and emit UI"). Nothing here touches the
// DOM, the network, or a timer -- screens/components call these to get
// plain data they then render.

export const ROOM_FAMILY_LABELS = Object.freeze({
  entrance: "Entrance",
  mystery_chamber: "Mystery Chamber",
  passage: "Passage",
  study: "Study",
  wild_place: "Wild Place",
  conflict: "Conflict",
  shop: "Shop",
  social_encounter: "Social Encounter",
  anomaly: "Anomaly",
});

// Every state gets a text label and a decorative (aria-hidden) glyph so
// nothing is encoded by color alone (infinite_stacks.md S24.1/S25). "unstable"
// / "secret_discovered" / "one_way" aren't emitted by the wave-1 engine stub
// yet but are supported here so the UI doesn't need to change when they land.
export const CONNECTOR_DISPLAY = Object.freeze({
  open: { label: "Open", glyph: "→" },
  locked: { label: "Locked", glyph: "•" },
  undiscovered: { label: "Unknown", glyph: "?" },
  none: { label: "No passage", glyph: "·" },
  unstable: { label: "Unstable", glyph: "≈" },
  secret_discovered: { label: "Secret found", glyph: "✲" },
  one_way: { label: "One-way", glyph: "➜" },
});

const DIRECTION_ORDER = ["north", "east", "south", "west"];

export function selectConnectionState(state) {
  return state.connection;
}

export function selectYouHero(state) {
  const heroId = state.you.heroId;
  return heroId ? state.heroes[heroId] || null : null;
}

// Danger is a tier with its own label + glyph, never a bare color (S25 "no
// color-only puzzles" / S24.1 "health danger"). `hero.life_state` is the
// forward-compatible field name for the combat lane's persisted
// Downed/Stable/Dead tri-state (docs/INFINITE_STACKS_COMBAT.md's
// HeroCombatant.life_state vocabulary, ALIVE|DOWNED|STABLE|DEAD) -- as of
// this wave the live wire projection (stacks_projections.py's heroes_view)
// only has `conscious`/`alive` booleans and no Stable distinction yet (wave-3
// board task #9, still in progress), so this falls back to that today and
// picks up the richer tri-state the moment the domain lane lands it under
// this field name, with no selector-shape change required.
export function heroDangerTier(hero) {
  if (hero.life_state) {
    const lifeState = String(hero.life_state).toLowerCase();
    if (lifeState === "dead") return { tier: "dead", label: "Dead", glyph: "†" };
    if (lifeState === "downed") return { tier: "downed", label: "Downed", glyph: "✕" };
    if (lifeState === "stable") return { tier: "stable", label: "Stable", glyph: "✚" };
  } else {
    if (!hero.alive) return { tier: "dead", label: "Dead", glyph: "†" };
    if (!hero.conscious) return { tier: "downed", label: "Downed", glyph: "✕" };
  }
  const ratio = hero.max_hp > 0 ? hero.hp / hero.max_hp : 1;
  if (ratio <= 0.25) return { tier: "critical", label: "Critical", glyph: "▲" };
  if (ratio <= 0.5) return { tier: "wounded", label: "Wounded", glyph: "△" };
  return { tier: "healthy", label: "Healthy", glyph: "●" };
}

// Whether a hero is a participant in the active combat encounter (S24.1
// "whether they are in combat"). No live combat projection is wired into any
// event/snapshot yet (wave-3 board task #9, stacks-conflict, still in
// progress) so state.combat is always null today and this always returns
// false in live play -- ready the moment it lands, since state.combat's
// shape already carries a `heroes` list (tests/fixtures/stacks_ui/combat_encounter.json).
export function heroInCombat(state, heroId) {
  if (!state.combat || !heroId) return false;
  return (state.combat.heroes || []).some((h) => h.id === heroId);
}

export function selectHeroCards(state) {
  return Object.values(state.heroes)
    .map((hero) => ({
      heroId: hero.hero_id,
      name: hero.name,
      roomId: hero.room_id,
      isYou: hero.hero_id === state.you.heroId,
      danger: heroDangerTier(hero),
      inCombat: heroInCombat(state, hero.hero_id),
      connected: !!hero.connected,
      ready: !!hero.ready,
      energyPips: energyPips(hero),
      token: selectHeroToken(hero),
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

// 5-pip Energy display (infinite_stacks.md S8.1/S24.1): an array of booleans,
// filled left to right, so the component only needs to loop and label each pip.
export function energyPips(hero) {
  const pips = [];
  for (let i = 0; i < hero.max_energy; i += 1) pips.push(i < hero.energy);
  return pips;
}

// Map tiles: discovered rooms plus "frontier" fog stubs for undiscovered
// connectors so the map never implies a false boundary (S24.1) -- an
// undiscovered direction renders as fog, not as empty space.
export function selectTiles(state) {
  const tiles = [];
  for (const room of Object.values(state.rooms)) {
    tiles.push({
      kind: "room",
      roomId: room.room_id,
      x: room.x,
      y: room.y,
      familyLabel: ROOM_FAMILY_LABELS[room.family] || room.family || "Unknown",
      family: room.family,
      entered: room.entered,
      required: room.required,
      connectors: DIRECTION_ORDER.map((direction) => ({
        direction,
        ...(CONNECTOR_DISPLAY[room.connectors[direction]?.state] || CONNECTOR_DISPLAY.none),
        state: room.connectors[direction]?.state || "none",
        targetRoomId: room.connectors[direction]?.target_room_id || null,
      })),
      heroesHere: Object.values(state.heroes).filter((h) => h.room_id === room.room_id).map((h) => h.hero_id),
    });
    for (const [direction, connector] of Object.entries(room.connectors)) {
      if (connector.state !== "undiscovered") continue;
      const [dx, dy] = DIRECTION_DELTA[direction];
      tiles.push({
        kind: "fog",
        roomId: `fog_${room.x + dx}_${room.y + dy}`,
        x: room.x + dx,
        y: room.y + dy,
        familyLabel: "Fog of war",
        connectors: [],
        heroesHere: [],
      });
    }
  }
  return tiles;
}

const DIRECTION_DELTA = { north: [0, 1], south: [0, -1], east: [1, 0], west: [-1, 0] };

export function selectDieDisplay(state) {
  if (!state.lastRoll) return null;
  return {
    value: state.lastRoll.value,
    familyLabel: ROOM_FAMILY_LABELS[state.lastRoll.family] || state.lastRoll.family,
    rollerHeroId: state.lastRoll.rollerHeroId,
    worldRound: state.lastRoll.worldRound,
  };
}

// Shortest open-connector path between two discovered rooms, for the route
// preview to a selected ally (S24.1). Returns null if unreachable through
// currently-discovered, open connectors.
export function selectRoutePreview(state, fromRoomId, toRoomId) {
  if (!fromRoomId || !toRoomId || fromRoomId === toRoomId) return { roomIds: [fromRoomId].filter(Boolean), arrivalRounds: 0 };
  const visited = new Set([fromRoomId]);
  let frontier = [[fromRoomId]];
  while (frontier.length) {
    const nextFrontier = [];
    for (const path of frontier) {
      const currentId = path[path.length - 1];
      const room = state.rooms[currentId];
      if (!room) continue;
      for (const connector of Object.values(room.connectors)) {
        if (connector.state !== "open" || !connector.target_room_id) continue;
        if (visited.has(connector.target_room_id)) continue;
        const nextPath = [...path, connector.target_room_id];
        if (connector.target_room_id === toRoomId) {
          return { roomIds: nextPath, arrivalRounds: nextPath.length - 1 };
        }
        visited.add(connector.target_room_id);
        nextFrontier.push(nextPath);
      }
    }
    frontier = nextFrontier;
  }
  return null;
}

export function selectLegalActionsSummary(state) {
  return state.legalActions;
}

// -- Wave-6 playtest response (docs/PLAYTEST_FINDINGS_2026-07-19.md) -------

// Locked defaults (board note 3): move-to-known-room 1 Energy, breach-
// unexplored 3 Energy. Duplicated by value client-side (same convention as
// CHARACTER_ATTRIBUTE_NAMES above) since there is no import boundary to the
// Python package. selectMoveCost/selectBreachCost prefer a real per-target
// wire cost the moment stacks-abilities lands legalActions.move_costs/
// breach_costs (posted to room chat as the reconciliation plan); until then
// every legal move/breach costs the same locked default, so falling back to
// it is exact, not a guess.
export const MOVE_ENERGY_COST = 1;
export const BREACH_ENERGY_COST = 3;

export function selectMoveCost(state, roomId) {
  const costs = (selectLegalActionsSummary(state) || {}).move_costs;
  return costs && typeof costs[roomId] === "number" ? costs[roomId] : MOVE_ENERGY_COST;
}

export function selectBreachCost(state, direction) {
  const costs = (selectLegalActionsSummary(state) || {}).breach_costs;
  return costs && typeof costs[direction] === "number" ? costs[direction] : BREACH_ENERGY_COST;
}

// C1/A3/A4/B2's persistent contextual hint line: one plain-language sentence
// describing what the player can do right now, driven entirely by state
// already on hand (never invents information the wire hasn't confirmed).
export function selectHintText(state) {
  const you = selectYouHero(state);
  if (!you) return "Enter an access code and a display name, then host a run or join one.";
  if (you.sheet == null) {
    if (you.pending_dice) return "Choose a background, assign your rolled dice to attributes, and pick your cards to finish creating your hero.";
    return "Roll your attribute dice to begin creating your hero.";
  }
  if (state.conflicts[you.room_id]) return "You are in combat -- choose an attack or a called maneuver, and answer any reaction prompt before its timer runs out.";
  if (state.puzzles[you.room_id]) return "Inspect objects to gather clues, share what you learn with the party, then submit a solution when you're ready.";
  const legalActions = selectLegalActionsSummary(state) || {};
  const canMove = (legalActions.can_move_to || []).length > 0;
  const canBreach = (legalActions.can_breach_directions || []).length > 0;
  if (canMove && canBreach) {
    return `You have ${you.energy} Energy -- click an adjacent room to move (${MOVE_ENERGY_COST}) or a fogged edge to breach (${BREACH_ENERGY_COST}).`;
  }
  if (canMove) return `You have ${you.energy} Energy -- click an adjacent room to move (${MOVE_ENERGY_COST}).`;
  if (canBreach) return `You have ${you.energy} Energy -- click a fogged edge to breach (${BREACH_ENERGY_COST}).`;
  return "No moves available from here right now -- Pass to let the world round advance, or Inspect your current room.";
}

// F1 tokens: avatar art + a CSS hue-rotate filter class for the hero's
// chosen color, replacing the name-text-only chips the playtest rejected.
// hero.avatar_id/hero.color are not on the live wire yet (posted to room
// chat as this wave's reconciliation plan with stacks-abilities); the
// fallback below is a PURE deterministic hash of hero_id, never client-side
// (tests/test_stacks_static.py's randomness ban covers this file), so two
// clients always render the same hero with the same token without a network
// round-trip, and swap over to the real fields the moment they land with no
// shape change here.
// Palette CONFIRMED by stacks-abilities 04:30 as the landed create_hero
// contract (server validates against exactly these 8 names) -- not a guess.
export const AVATAR_COUNT = 6;
export const TOKEN_COLORS = Object.freeze(["crimson", "azure", "gold", "violet", "emerald", "slate", "coral", "ivory"]);

function stableHash(text) {
  let hash = 0;
  for (let i = 0; i < text.length; i += 1) {
    hash = (hash * 31 + text.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

export function selectHeroToken(hero) {
  if (!hero || !hero.hero_id) return null;
  const avatarId = Number.isInteger(hero.avatar_id) && hero.avatar_id >= 1 && hero.avatar_id <= AVATAR_COUNT ? hero.avatar_id : (stableHash(hero.hero_id) % AVATAR_COUNT) + 1;
  const color = TOKEN_COLORS.includes(hero.color) ? hero.color : TOKEN_COLORS[stableHash(`${hero.hero_id}:color`) % TOKEN_COLORS.length];
  return {
    avatarId,
    avatarSrc: `/src/assets/avatars/avatar-${avatarId}.png`,
    color,
    colorClass: `stacks-token-hue-${color}`,
  };
}

// D1 abilities list: the hero's background signature ability (real data,
// already on the wire via content_catalog + hero.signature_charge) plus any
// forward-compatible hero.abilities the abilities lane adds (fixture-first,
// posted to room chat: {id, name, fallback, accessible, trigger, frequency,
// available}) -- empty array, never undefined, when neither source has data
// yet so callers don't need their own null guard.
export function selectAbilitiesView(state) {
  const you = selectYouHero(state);
  if (!you || !you.sheet) return [];
  const catalog = state.contentCatalog;
  const background = catalog ? catalog.backgrounds[you.sheet.background_id] : null;
  const abilities = [];
  if (background && background.signature_ability) {
    const sig = background.signature_ability;
    const charge = you.signature_charge;
    abilities.push({
      id: sig.id,
      name: sig.name,
      fallback: sig.fallback,
      accessible: sig.accessible,
      frequency: sig.frequency,
      available: charge ? charge.charges_remaining > 0 : true,
      chargesRemaining: charge ? charge.charges_remaining : null,
      maxCharges: charge ? charge.max_charges : null,
    });
  }
  for (const ability of you.abilities || []) {
    abilities.push({
      id: ability.id,
      name: ability.name,
      fallback: ability.fallback,
      accessible: ability.accessible,
      frequency: ability.frequency || ability.trigger,
      available: ability.available !== false,
      chargesRemaining: null,
      maxCharges: null,
    });
  }
  return abilities;
}

// A5 active-effects tray: combat statuses (hero.statuses, same {id,
// rounds_remaining} shape status.js's STATUS_DISPLAY already renders) plus
// forward-compatible hero.active_effects (fixture-first, posted to room
// chat: {id, name, fallback, accessible, rounds_remaining, source}) for
// card/ability effects that last a duration -- e.g. "until end of turn".
// Neither field is on the live wire yet outside a combat encounter, so this
// returns [] rather than guessing at a shape nothing has confirmed.
export function selectActiveEffectsView(state) {
  const you = selectYouHero(state);
  if (!you) return [];
  const statuses = (you.statuses || []).map((status) => ({ kind: "status", id: status.id, roundsRemaining: status.rounds_remaining }));
  const effects = (you.active_effects || []).map((effect) => ({
    kind: "effect",
    id: effect.id,
    name: effect.name,
    fallback: effect.fallback,
    accessible: effect.accessible,
    roundsRemaining: effect.rounds_remaining,
    source: effect.source,
  }));
  return [...statuses, ...effects];
}

// D1/D2's persistent character panel: HP numbers+bar, attributes, skills,
// Energy pips, statuses/active effects, abilities, and inventory, merged
// into one view so the panel never needs more than one selector call.
export function selectCharacterPanelView(state) {
  const you = selectYouHero(state);
  if (!you) return null;
  return {
    heroId: you.hero_id,
    name: you.name,
    token: selectHeroToken(you),
    hp: you.hp,
    maxHp: you.max_hp,
    danger: heroDangerTier(you),
    energyPips: energyPips(you),
    attributes: you.sheet ? you.sheet.attributes : null,
    skills: you.sheet ? you.sheet.skills : null,
    abilities: selectAbilitiesView(state),
    activeEffects: selectActiveEffectsView(state),
    inventory: selectInventoryView(state),
  };
}

// A2/E3 card-face frame kind: CONFIRMED 04:28 by stacks-carddesign as
// `art_ref` (one of the 3 real asset paths this lane copied in,
// `src/assets/cards/{charm,scheme,bonk}.png`, classified per-card at
// authoring time using the exact same rule this heuristic applies) -- prefer
// their authored value once content/packs/core/{cards,abilities}.yaml lands
// it, and keep the heuristic as the fallback for any card/ability that
// doesn't set art_ref yet (or a future pack that never does).
export function cardFrameKind(card) {
  if (card.art_ref) {
    const match = /\/(charm|scheme|bonk)\.png$/.exec(card.art_ref);
    if (match) return match[1];
  }
  const tags = card.tags || [];
  const targets = card.targets || [];
  if (targets.includes("enemy") || tags.includes("melee") || tags.includes("bonk")) return "bonk";
  if (tags.includes("support") || tags.includes("communication") || tags.includes("persona") || tags.includes("wordcraft") || targets.includes("ally")) return "charm";
  return "scheme";
}

export function selectLastError(state) {
  return state.lastError;
}

// Which non-map screen (if any) is active. Character creation (§11) takes
// precedence over everything else -- a hero with no sheet yet has nothing
// legal to do in any other screen (every wave-4 hero command requires
// `_require_sheet`/pending_dice server-side). Combat takes precedence over a
// puzzle in the same room, which takes precedence over a plain entered-room
// view. Both "combat" and "puzzle" are room-keyed as of wave 3 (state.conflicts/
// state.puzzles, docs/INFINITE_STACKS_CONTRACTS.md S5.2 + stacks-conflict's
// wave-3 vocabulary post), not singular slots anymore. state.enteredRoom
// remains a mutually-optional, not-yet-live wire object this wave (see its
// own selector's comment).
export function selectActiveScreen(state) {
  const you = selectYouHero(state);
  if (you && you.sheet == null) return "character-builder";
  if (you && state.conflicts[you.room_id]) return "combat";
  if (you && state.puzzles[you.room_id]) return "puzzle";
  if (state.enteredRoom) return "room";
  return "map";
}

// -- Character creation (infinite_stacks.md S11) ---------------------------

const ATTRIBUTE_NAMES = ["force", "finesse", "insight", "presence"];
const ATTRIBUTE_LABELS = { force: "Force", finesse: "Finesse", insight: "Insight", presence: "Presence" };

export function selectContentCatalog(state) {
  return state.contentCatalog;
}

// §11.1 derived-stat preview formulas, computed client-side purely for
// display before the player submits create_hero -- the server (heroes.
// creation.compute_derived_stats) is always the authoritative computation
// that actually lands on the hero sheet; this is read-only arithmetic on
// public formulas from infinite_stacks.md S11.1, never a value sent back to
// the server as a raw number.
export function computeDerivedStatsPreview(attributes) {
  const force = attributes.force || 0;
  const finesse = attributes.finesse || 0;
  return {
    maxHp: 8 + force * 2,
    defense: 10 + finesse,
    initiativeModifier: finesse,
    carrySlots: 4 + force,
  };
}

// Character-builder view: rolled dice (if any), the background/card catalog
// (fetched once via core/api.js's fetchContentCatalog), and whether a
// pending roll exists yet. `attributeAssignment` is `{dieIndex: attribute}`
// -- a bijection from rolled-die INDEX (not value, since dice can repeat) to
// attribute name, which is what main.js's onCreateHero handler turns into
// the wire's {attribute: value} payload.
export function selectCharacterBuilderView(state) {
  const you = selectYouHero(state);
  const catalog = state.contentCatalog;
  return {
    heroId: you ? you.hero_id : null,
    pendingDice: you ? you.pending_dice || null : null,
    attributeNames: ATTRIBUTE_NAMES,
    attributeLabels: ATTRIBUTE_LABELS,
    backgrounds: catalog ? Object.values(catalog.backgrounds).sort((a, b) => a.name.localeCompare(b.name)) : [],
    generalCards: catalog
      ? Object.values(catalog.cards)
          .filter((c) => c.source === "general" && c.live_at_creation)
          .sort((a, b) => a.name.localeCompare(b.name))
      : [],
    // §13.2's persona signature card is not a player choice this wave (the
    // core pack authors exactly one, "source": "persona") -- selected
    // automatically so the builder form has one fewer decision to make.
    personaCard: catalog ? Object.values(catalog.cards).find((c) => c.source === "persona") || null : null,
    catalogLoaded: !!catalog,
  };
}

// -- Hand / deck / inventory (infinite_stacks.md S13.2, S13.6) -------------

const TIMING_LABELS = {
  main_action: "Main action",
  quick_interaction: "Quick interaction",
  reaction: "Reaction",
  free_speech: "Free speech",
};

// Maps one wire card_id + its content-catalog definition into the plain
// shape components/card.js renders (S13.3's full contract list). `effect`
// uses the card's authored accessible_text (the only complete factual
// description on the wire -- base_effects/check outcome tables are not
// serialized) and `generatedDescription` uses the fallback prose, matching
// S13.3's "generated-description fallback text" contract field.
function cardView(cardId, catalog) {
  const card = catalog && catalog.cards ? catalog.cards[cardId] : null;
  if (!card) {
    return {
      id: cardId,
      name: cardId,
      timing: "",
      cost: "",
      range: "",
      targets: [],
      requirements: "",
      effect: "",
      checkTable: undefined,
      tags: [],
      exhaustOnPlay: false,
      accessibleText: cardId,
      generatedDescription: "",
      frameKind: "scheme",
    };
  }
  const plain = {
    id: card.id,
    name: card.name,
    timing: card.timing,
    cost: TIMING_LABELS[card.timing] || card.timing,
    range: card.range,
    targets: card.legal_targets,
    requirements: (card.required_state || []).join(", "),
    effect: card.accessible_text,
    checkTable: undefined,
    tags: card.combination_tags,
    exhaustOnPlay: card.end_state === "exhaust",
    accessibleText: card.accessible_text,
    generatedDescription: card.fallback,
    art_ref: card.art_ref,
  };
  return { ...plain, frameKind: cardFrameKind(plain) };
}

// A3: best-effort "can this be played right now" from data already on the
// wire (no per-card legal_actions field exists yet) -- a reaction card is
// only playable while a pending reaction targets you; an enemy/ally-only
// card is only playable while a legal target actually exists. Anything this
// can't evaluate (e.g. required_state) defaults to playable rather than
// guessing it's blocked, since a false "inert" reads worse than a card that
// turns out to reject on submit.
function cardPlayableNow(card, { enemiesAlive, alliesHere, reactionAvailableToYou }) {
  if (card.timing === "reaction") return reactionAvailableToYou;
  const targets = card.targets || [];
  if (targets.includes("enemy") && enemiesAlive === 0) return false;
  if (targets.includes("ally") && !targets.includes("self") && alliesHere === 0) return false;
  return true;
}

// Hand/deck view for the viewer's own hero: `hand` is only ever present on
// the wire for `viewer === heroId` (stacks_engine.py's
// `_neutral_hero_creation_snapshot`) -- this selector returns null hand data
// for anyone else's hero rather than guessing at contents.
export function selectHandView(state) {
  const you = selectYouHero(state);
  if (!you || !you.deck) return null;
  const catalog = state.contentCatalog;
  const roomId = you.room_id;
  const conflict = roomId ? state.conflicts[roomId] : null;
  const alliesHere = Object.values(state.heroes).filter((h) => h.room_id === roomId && h.hero_id !== you.hero_id).length;
  const enemiesAlive = conflict ? Object.values(conflict.enemies || {}).filter((e) => e.alive).length : 0;
  const combatView = roomId ? selectCombatView(state) : null;
  const pendingReaction = combatView ? combatView.pendingReaction : null;
  const reactionAvailableToYou = !!pendingReaction && (pendingReaction.defenderId === you.hero_id || pendingReaction.protectorIds.includes(you.hero_id));
  const playability = { enemiesAlive, alliesHere, reactionAvailableToYou };
  return {
    hand: Array.isArray(you.hand)
      ? you.hand.map((cardId) => {
          const card = cardView(cardId, catalog);
          return { ...card, playableNow: cardPlayableNow(card, playability) };
        })
      : null,
    deckCount: you.deck.deck_count,
    discardCount: you.deck.discard.length,
    exhaustedCount: you.deck.exhausted.length,
  };
}

// Inventory view for the viewer's own hero: carried items (name + slot cost
// from the catalog), free/total slots, ground items available to pick up in
// the hero's current room, and any recoverable body loot in that room.
export function selectInventoryView(state) {
  const you = selectYouHero(state);
  if (!you || !you.inventory) return null;
  const catalog = state.contentCatalog;
  const items = catalog ? catalog.items : {};
  const room = state.rooms[you.room_id];

  const carried = you.inventory.items.map((itemId) => ({
    itemId,
    name: items[itemId] ? items[itemId].name : itemId,
    slotCost: items[itemId] ? items[itemId].slot_cost : 1,
  }));
  const usedSlots = carried.reduce((sum, item) => sum + item.slotCost, 0);

  const groundItems = room
    ? Object.entries(room.ground_items || {}).map(([instanceId, itemId]) => ({
        instanceId,
        itemId,
        name: items[itemId] ? items[itemId].name : itemId,
        claimedByHeroId: (room.item_claims || {})[instanceId] || null,
      }))
    : [];

  const recoverableBodies = room
    ? Object.entries(room.body_item_ids || {}).map(([deadHeroId, itemIds]) => ({
        deadHeroId,
        itemIds,
      }))
    : [];

  return {
    carried,
    usedSlots,
    totalSlots: you.inventory.carry_slots,
    groundItems,
    recoverableBodies,
    otherHeroesHere: Object.values(state.heroes).filter((h) => h.hero_id !== you.hero_id && h.room_id === you.room_id),
  };
}

function mapStatus(status) {
  return { id: status.id, roundsRemaining: status.rounds_remaining };
}

// Generic entered-room view (infinite_stacks.md S9/S24.1/S24.4): occupants,
// inspectable objects, exits with their Energy cost, and any corruption
// tells. Wire shape is snake_case (state.enteredRoom); this returns the
// camelCase plain data screens/room.js renders directly.
export function selectEnteredRoomView(state) {
  const room = state.enteredRoom;
  if (!room) return null;
  return {
    roomId: room.room_id,
    familyLabel: ROOM_FAMILY_LABELS[room.family] || room.family || "Unknown",
    subtypeLabel: room.subtype_label || null,
    occupants: (room.occupants || []).map((occupant) => ({
      id: occupant.id,
      name: occupant.name,
      kind: occupant.kind,
      isYou: !!occupant.is_you,
      statuses: (occupant.statuses || []).map(mapStatus),
    })),
    objects: (room.objects || []).map((object) => ({ id: object.id, label: object.label, inspected: !!object.inspected })),
    exits: (room.exits || []).map((exit) => ({
      direction: exit.direction,
      label: exit.label,
      energyCost: exit.energy_cost,
      legal: !!exit.legal,
    })),
    corruptionTells: (room.corruption_tells || []).map((tell) => ({ id: tell.id, text: tell.text })),
  };
}

// Mystery Chamber puzzle view (infinite_stacks.md S10, S24.4;
// docs/INFINITE_STACKS_CONTRACTS.md S5.2 for the wire shape). state.puzzles
// is keyed by room_id (the REAL StacksEngineAdapter.project() shape, wave 3
// board task #10) -- this looks up the viewer's current room rather than
// reading a singular state.puzzle slot. Object roles (anchor/key/
// contradiction/red_herring) are deliberately never surfaced here: S10.2
// "the four design roles are never labeled to the player", only each
// object's own fallback/accessible prose is. Every object's prose is always
// present on the wire (no separate "inspected before you can see it" gate);
// `inspected` here is a purely-local "you've already pressed the button"
// indicator (state.puzzleInspectedObjects) since the wire never tracks that
// per-object -- inspecting is what claims key-object clue fragments and logs
// non-key objects' clue text into state.puzzleClues, not what reveals prose.
export function selectPuzzleView(state) {
  const you = selectYouHero(state);
  const roomId = you ? you.room_id : null;
  const puzzle = roomId ? state.puzzles[roomId] : null;
  if (!puzzle) return null;

  const inspectedIds = new Set(state.puzzleInspectedObjects[roomId] || []);
  const sharedIds = new Set(state.sharedClueIds[roomId] || []);
  const yourPrivateClueIds = new Set((puzzle.your_private_clues || []).map((c) => c.clue_id));
  const knownClues = state.puzzleClues[roomId] || {};

  return {
    roomId,
    instanceId: puzzle.instance_id,
    templateId: puzzle.template_id,
    difficulty: puzzle.difficulty,
    solved: !!puzzle.solved,
    forced: !!puzzle.forced,
    attemptsUsed: puzzle.attempts_used || 0,
    attemptLimit: typeof puzzle.attempt_limit === "number" ? puzzle.attempt_limit : null,
    objects: (puzzle.objects || []).map((object) => ({
      id: object.id,
      fallback: object.fallback,
      accessible: object.accessible,
      inspected: inspectedIds.has(object.id),
    })),
    // Orderable solution items (wire: puzzles[room_id].items, added at wave-3
    // close -- lexicographic-by-item_id, provably independent of the solution
    // order). Empty for older snapshots; the submission UI falls back to
    // freeform text entry in that case.
    items: (puzzle.items || []).map((item) => ({
      itemId: item.item_id,
      fallback: item.fallback,
      accessible: item.accessible,
    })),
    // Key-object clue fragments this hero has personally claimed (S10.3 #8:
    // "no single hero's view ever contains the full key chain" -- this can
    // legitimately hold more than one fragment across separate claims).
    yourPrivateClues: (puzzle.your_private_clues || []).map((clue) => ({
      clueId: clue.clue_id,
      fallback: clue.fallback,
      accessible: clue.accessible,
      shared: sharedIds.has(clue.clue_id),
    })),
    // Clue text learned by inspecting the anchor/contradiction/red_herring
    // objects -- distinct from yourPrivateClues (the key pool only).
    discoveredClues: Object.values(knownClues)
      .filter((clue) => !yourPrivateClueIds.has(clue.clueId))
      .map((clue) => ({ ...clue, shared: sharedIds.has(clue.clueId) })),
    // Party-visible shared notes (S24.4: text, ordering, linking,
    // contradiction marks) -- entirely client-local this wave (state.puzzleManualNotes),
    // populated by manual adds and by pressing Share on a clue.
    sharedNotes: (state.puzzleManualNotes[roomId] || []).map((note) => ({
      id: note.id,
      text: note.text,
      authorName: note.authorName,
      linkedNoteIds: note.linkedNoteIds || [],
      contradiction: !!note.contradiction,
    })),
    hintsRevealed: (puzzle.hints_revealed || []).map((hint) => ({ fallback: hint.fallback, accessible: hint.accessible })),
    canRequestHint: !puzzle.solved && !puzzle.forced,
    canSubmit: !puzzle.solved && !puzzle.forced,
  };
}

// Combat view (infinite_stacks.md S14, S24.3). Wire shape as of stacks-conflict's
// 17:15 wave-3 vocabulary post (docs/INFINITE_STACKS_CONTRACTS.md-style,
// EARLY DRAFT -- confirmed field names, final dict pending stacks_projections.py
// landing): project() gains a top-level "conflict" key parallel to "puzzles",
// {room_id: {encounter_id, status, combat_round, heroes: {hero_id:{hp,max_hp,
// life_state,position,reaction_available}}, enemies: {instance_id:{name,hp,
// max_hp,alive,position}}, initiative_order:[combatant_id...], current_turn,
// last_intent_telegraph, threat_budget}}. state.conflicts is keyed by room_id
// like state.puzzles. There is no legal_actions/last_check_receipt on this
// projection (unlike the wave-2 fixture guess) -- enemy intent and the S12.5
// check receipt are folded client-side from the raw combat/events.py event
// dicts embedded in conflict_turn_resolved's payload.combat_events (see
// core/store.js's applyConflictEvent), using the CONFIRMED, already-shipped
// intent_telegraphed/attack_resolved payload shapes from combat/intents.py
// and combat/actions.py.
export function selectCombatView(state) {
  const you = selectYouHero(state);
  const roomId = you ? you.room_id : null;
  const conflict = roomId ? state.conflicts[roomId] : null;
  if (!conflict) return null;

  const heroesById = conflict.heroes || {};
  const enemiesById = conflict.enemies || {};
  const intents = state.conflictIntents[roomId] || {};

  const combatantName = (id) => {
    if (heroesById[id]) return (state.heroes[id] && state.heroes[id].name) || id;
    if (enemiesById[id]) return enemiesById[id].name || id;
    return id;
  };

  return {
    roomId,
    encounterId: conflict.encounter_id,
    status: conflict.status,
    round: conflict.combat_round,
    currentTurnId: conflict.current_turn || null,
    isYourTurn: !!you && conflict.current_turn === you.hero_id,
    yourHeroId: you ? you.hero_id : null,
    initiativeOrder: (conflict.initiative_order || []).map((combatantId) => ({
      id: combatantId,
      name: combatantName(combatantId),
      isCurrentTurn: conflict.current_turn === combatantId,
      hasReactionAvailable: heroesById[combatantId] ? !!heroesById[combatantId].reaction_available : null,
    })),
    enemies: Object.entries(enemiesById).map(([id, enemy]) => {
      // Prefer the event-folded intent map (state.conflictIntents, always
      // up to date); fall back to the projection's own last_intent_telegraph
      // (only ever describes one enemy at a time) for the case of a fresh
      // reconnect snapshot with no missed events yet to fold.
      const folded = intents[id];
      const fallback =
        !folded && conflict.last_intent_telegraph && conflict.last_intent_telegraph.enemy_id === id ? conflict.last_intent_telegraph : null;
      const intent = folded
        ? { telegraphText: folded.telegraphText, accessibleText: folded.accessibleText, counterplay: folded.counterplay }
        : fallback
          ? { telegraphText: fallback.telegraph_text, accessibleText: fallback.accessible_text, counterplay: fallback.counterplay }
          : null;
      return { id, name: enemy.name, hp: enemy.hp, maxHp: enemy.max_hp, alive: !!enemy.alive, position: enemy.position, intent };
    }),
    heroes: Object.entries(heroesById).map(([id, hero]) => ({
      id,
      name: (state.heroes[id] && state.heroes[id].name) || id,
      hp: hero.hp,
      maxHp: hero.max_hp,
      lifeState: hero.life_state,
      danger: heroDangerTier({ ...(state.heroes[id] || {}), life_state: hero.life_state, hp: hero.hp, max_hp: hero.max_hp }),
      reactionAvailable: !!hero.reaction_available,
      position: hero.position,
      // Per-target attack catalog (docs/INFINITE_STACKS_CONTRACTS.md S5.4
      // item 5, wave-4 board task #13): real accuracy/damage/weapon-die
      // numbers resolved server-side from the hero's actual sheet + equipment
      // -- never a client-suppliable modifier. Empty for a hero with no
      // completed character creation yet.
      legalAttacks: (hero.legal_attacks || []).map((atk) => ({
        targetId: atk.target_id,
        accuracyBonus: atk.accuracy_bonus,
        weaponDieFaces: atk.weapon_die_faces,
        damageBonus: atk.damage_bonus,
      })),
    })),
    threatBudget: conflict.threat_budget || null,
    lastCheckReceipt: state.conflictLastCheckReceipt[roomId] || null,
    // §21.3/§21.4 reaction interrupt window (stacks-enemyroll's wave-5
    // transport-injection spec, board task #16): null until their domain
    // work lands a real `pending_reaction` on the encounter -- combat.js
    // renders nothing while this is null, exactly today's behavior.
    pendingReaction: conflict.pending_reaction
      ? {
          reactionId: conflict.pending_reaction.reaction_id,
          attackerId: conflict.pending_reaction.attacker_id,
          defenderId: conflict.pending_reaction.defender_id,
          protectorIds: conflict.pending_reaction.protector_ids || [],
          hit: conflict.pending_reaction.hit,
          margin: conflict.pending_reaction.margin,
          incomingAttackTotal: conflict.pending_reaction.incoming_attack_total,
          provisionalDamage: conflict.pending_reaction.provisional_damage,
          actionLabel: conflict.pending_reaction.action_label,
        }
      : null,
  };
}
