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

// Danger is a tier with its own label, never a bare color (S25 "no color-only
// puzzles" / S24.1 "health danger").
export function heroDangerTier(hero) {
  if (!hero.alive) return { tier: "dead", label: "Dead" };
  if (!hero.conscious) return { tier: "downed", label: "Downed" };
  const ratio = hero.max_hp > 0 ? hero.hp / hero.max_hp : 1;
  if (ratio <= 0.25) return { tier: "critical", label: "Critical" };
  if (ratio <= 0.5) return { tier: "wounded", label: "Wounded" };
  return { tier: "healthy", label: "Healthy" };
}

export function selectHeroCards(state) {
  return Object.values(state.heroes)
    .map((hero) => ({
      heroId: hero.hero_id,
      name: hero.name,
      roomId: hero.room_id,
      isYou: hero.hero_id === state.you.heroId,
      danger: heroDangerTier(hero),
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
// view; state.combat/state.puzzle/state.enteredRoom are mutually-optional,
// server-populated wire objects (wave 2: fixture-driven, see
// tests/fixtures/stacks_ui/).
export function selectActiveScreen(state) {
  if (state.combat) return "combat";
  if (state.puzzle) return "puzzle";
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

// Mystery Chamber puzzle view (infinite_stacks.md S10, S24.4). Wire shape is
// snake_case (state.puzzle); this returns the camelCase plain data
// screens/puzzle.js renders directly.
export function selectPuzzleView(state) {
  const puzzle = state.puzzle;
  if (!puzzle) return null;
  return {
    puzzleId: puzzle.puzzle_id,
    templateLabel: puzzle.template_label,
    difficulty: puzzle.difficulty,
    objects: (puzzle.objects || []).map((object) => ({
      id: object.id,
      label: object.label,
      inspected: !!object.inspected,
      description: object.description || null,
    })),
    privateClue: puzzle.private_clue ? { text: puzzle.private_clue.text, shared: !!puzzle.private_clue.shared } : null,
    sharedNotes: (puzzle.shared_notes || []).map((note) => ({
      id: note.id,
      text: note.text,
      authorName: note.author_name,
      linkedNoteIds: note.linked_note_ids || [],
      contradiction: !!note.contradiction,
    })),
    hints: {
      used: puzzle.hints.used,
      tiers: (puzzle.hints.tiers || []).map((tier) => ({ level: tier.level, description: tier.description, cost: tier.cost })),
      nextHintCost: puzzle.hints.next_hint_cost || null,
      forceProgressAvailable: !!puzzle.hints.force_progress_available,
      forceProgressConsequence: puzzle.hints.force_progress_consequence || null,
    },
    submission: {
      legal: !!puzzle.submission.legal,
      slots: (puzzle.submission.slots || []).map((slot) => ({
        id: slot.id,
        label: slot.label,
        selectedId: slot.selected_id || null,
        options: (slot.options || []).map((option) => ({ id: option.id, label: option.label })),
      })),
    },
  };
}

// Combat view (infinite_stacks.md S14, S24.3). Wire shape is snake_case
// (state.combat); this returns the camelCase plain data screens/combat.js
// renders directly.
export function selectCombatView(state) {
  const combat = state.combat;
  if (!combat) return null;
  const legalActions = combat.legal_actions || {};
  return {
    encounterId: combat.encounter_id,
    round: combat.round,
    initiativeOrder: (combat.initiative_order || []).map((entry) => ({
      id: entry.id,
      name: entry.name,
      initiative: entry.initiative,
      isCurrentTurn: !!entry.is_current_turn,
      hasReactionAvailable: !!entry.has_reaction_available,
    })),
    enemies: (combat.enemies || []).map((enemy) => ({
      id: enemy.id,
      name: enemy.name,
      hp: enemy.hp,
      maxHp: enemy.max_hp,
      intent: { label: enemy.intent.label, glyph: enemy.intent.glyph, description: enemy.intent.description },
      statuses: (enemy.statuses || []).map(mapStatus),
    })),
    heroes: (combat.heroes || []).map((hero) => ({
      id: hero.id,
      name: hero.name,
      hp: hero.hp,
      maxHp: hero.max_hp,
      reactionAvailable: !!hero.reaction_available,
      statuses: (hero.statuses || []).map(mapStatus),
    })),
    legalActions: {
      attacks: (legalActions.attacks || []).map((attack) => ({
        id: attack.id,
        label: attack.label,
        targetId: attack.target_id,
        targetLabel: attack.target_label,
        expectedEffect: attack.expected_effect,
      })),
      maneuvers: (legalActions.maneuvers || []).map((maneuver) => ({
        id: maneuver.id,
        label: maneuver.label,
        targetId: maneuver.target_id,
        targetLabel: maneuver.target_label,
        accuracyModifier: maneuver.accuracy_modifier,
        expectedEffect: maneuver.expected_effect,
      })),
      reactions: (legalActions.reactions || []).map((reaction) => ({ id: reaction.id, label: reaction.label, available: !!reaction.available })),
    },
    lastCheckReceipt: combat.last_check_receipt
      ? {
          action: combat.last_check_receipt.action,
          target: combat.last_check_receipt.target,
          attribute: combat.last_check_receipt.attribute,
          skill: combat.last_check_receipt.skill,
          dieResult: combat.last_check_receipt.die_result,
          modifiers: (combat.last_check_receipt.modifiers || []).map((modifier) => ({ source: modifier.source, value: modifier.value })),
          targetNumber: combat.last_check_receipt.target_number,
          outcome: combat.last_check_receipt.outcome,
        }
      : null,
  };
}
