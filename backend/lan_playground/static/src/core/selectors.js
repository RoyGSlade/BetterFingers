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

export function selectLastError(state) {
  return state.lastError;
}

// Which non-map screen (if any) is active. Combat takes precedence over a
// puzzle in the same room, which takes precedence over a plain entered-room
// view. Both "combat" and "puzzle" are room-keyed as of wave 3 (state.conflicts/
// state.puzzles, docs/INFINITE_STACKS_CONTRACTS.md S5.2 + stacks-conflict's
// wave-3 vocabulary post), not singular slots anymore. state.enteredRoom
// remains a mutually-optional, not-yet-live wire object this wave (see its
// own selector's comment).
export function selectActiveScreen(state) {
  const you = selectYouHero(state);
  if (you && state.conflicts[you.room_id]) return "combat";
  if (you && state.puzzles[you.room_id]) return "puzzle";
  if (state.enteredRoom) return "room";
  return "map";
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
    })),
    threatBudget: conflict.threat_budget || null,
    lastCheckReceipt: state.conflictLastCheckReceipt[roomId] || null,
  };
}
