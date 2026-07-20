// Builds command envelopes matching docs/INFINITE_STACKS_CONTRACTS.md S2.
// Pure functions only: no network, no DOM, no store access. Callers
// (screens/map.js via main.js) supply expectedRevision from the store and
// pass the resulting envelope to core/socket.js's sendCommand.

function generateId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function buildCommand(type, payload, { expectedRevision, encounterId = null, idempotencyKey } = {}) {
  return {
    command_id: generateId(),
    idempotency_key: idempotencyKey || generateId(),
    encounter_id: encounterId,
    expected_revision: expectedRevision,
    type,
    payload: payload || {},
  };
}

export function moveCommand(toRoomId, expectedRevision) {
  return buildCommand("move", { to_room_id: toRoomId }, { expectedRevision });
}

export function breachCommand(direction, expectedRevision) {
  return buildCommand("breach", { direction }, { expectedRevision });
}

export function observeCommand(direction, expectedRevision) {
  return buildCommand("observe", { direction }, { expectedRevision });
}

export function inspectCommand(expectedRevision) {
  return buildCommand("inspect", {}, { expectedRevision });
}

export function passCommand(expectedRevision) {
  return buildCommand("pass", {}, { expectedRevision });
}

export function checkCommand(dc, expectedRevision) {
  return buildCommand("check", { dc }, { expectedRevision });
}

// Wave-2 puzzle commands (docs/INFINITE_STACKS_CONTRACTS.md S2 "Wave-2
// additions"). Payload keys/types match the domain vocabulary exactly:
// inspect_object takes object_id, submit_solution takes an ordered list of
// item ids under the key "solution" (never "answer"), request_hint takes no
// payload at all -- requesting a hint past the last available one is how the
// server force-progresses the room (systems/puzzles.py's handle_request_hint),
// there is no separate force_progress command.
export function inspectObjectCommand(objectId, expectedRevision) {
  return buildCommand("inspect_object", { object_id: objectId }, { expectedRevision });
}

export function submitSolutionCommand(solution, expectedRevision) {
  return buildCommand("submit_solution", { solution }, { expectedRevision });
}

export function requestHintCommand(expectedRevision) {
  return buildCommand("request_hint", {}, { expectedRevision });
}

// Wave-3 combat commands, per stacks-conflict's 17:15 vocabulary post
// (docs/INFINITE_STACKS_COMBAT.md's package + the director's ruling that
// removed client-supplied numeric modifiers): combat_attack/combat_maneuver
// take only target_id/attribute/skill(/maneuver) -- no accuracy or damage
// numbers from the client, those are always server-resolved. EARLY DRAFT:
// stacks-conflict said to expect at most small renames once their code lands.
export function combatAttackCommand(targetId, attribute, skill, expectedRevision, encounterId) {
  return buildCommand("combat_attack", { target_id: targetId, attribute, skill }, { expectedRevision, encounterId });
}

export function combatManeuverCommand(maneuver, targetId, attribute, skill, expectedRevision, encounterId) {
  return buildCommand("combat_maneuver", { maneuver, target_id: targetId, attribute, skill }, { expectedRevision, encounterId });
}

export function combatReactionCommand(reaction, expectedRevision, encounterId) {
  return buildCommand("combat_reaction", { reaction }, { expectedRevision, encounterId });
}

export function combatEndTurnCommand(expectedRevision, encounterId) {
  return buildCommand("combat_end_turn", {}, { expectedRevision, encounterId });
}
