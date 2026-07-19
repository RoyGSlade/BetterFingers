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
