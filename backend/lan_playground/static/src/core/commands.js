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
