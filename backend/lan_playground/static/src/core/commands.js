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

// §21.4 reaction interrupt window (stacks-enemyroll's wave-5 transport-
// injection spec, board task #16): resolve_reaction takes only the pending
// interrupt's reaction_id (so a stale/duplicate click can never resolve the
// wrong reaction) plus the chosen reaction name -- no client-supplied
// incoming_attack_total/incoming_damage/position, unlike the wave-3
// freeform combat_reaction command it replaces in the UI (that one required
// exactly the raw numeric modifiers this codebase's wire contract forbids
// from ever leaving the client; see combat.js's renderReactionPrompt).
export function resolveReactionCommand(reactionId, reaction, expectedRevision, encounterId) {
  return buildCommand("resolve_reaction", { reaction_id: reactionId, reaction }, { expectedRevision, encounterId });
}

export function combatEndTurnCommand(expectedRevision, encounterId) {
  return buildCommand("combat_end_turn", {}, { expectedRevision, encounterId });
}

// Wave-5 hero commands (docs/INFINITE_STACKS_CONTRACTS.md S5.4, board task
// #17): payload keys/types match the domain vocabulary systems/heroes_wire.py
// validates exactly. No raw numeric modifier ever leaves the client here --
// attribute_assignment sends the die VALUES the player rolled (server-
// supplied, already public via attribute_dice_rolled), never a made-up
// score, and item/card selections are always ids.
export function rollAttributeDiceCommand(expectedRevision) {
  return buildCommand("roll_attribute_dice", {}, { expectedRevision });
}

export function createHeroCommand(
  { name, backgroundId, attributeAssignment, generalCardIds, personaCardId, equipmentCardIds, avatarId, color },
  expectedRevision,
) {
  return buildCommand(
    "create_hero",
    {
      name,
      background_id: backgroundId,
      attribute_assignment: attributeAssignment,
      general_card_ids: generalCardIds,
      persona_card_id: personaCardId,
      equipment_card_ids: equipmentCardIds || [],
      // F1 tokens (playtest): CONFIRMED contract, stacks-abilities 04:30 --
      // validated + auto-assigned server-side if omitted (null is legal).
      avatar_id: avatarId || null,
      color: color || null,
    },
    { expectedRevision },
  );
}

export function drawCardsCommand(count, expectedRevision) {
  return buildCommand("draw_cards", { count }, { expectedRevision });
}

export function playCardCommand(cardId, { targetHeroId = null, targetEnemyId = null } = {}, expectedRevision, encounterId) {
  return buildCommand(
    "play_card",
    { card_id: cardId, target_hero_id: targetHeroId, target_enemy_id: targetEnemyId },
    { expectedRevision, encounterId },
  );
}

export function safeRestCommand(expectedRevision) {
  return buildCommand("safe_rest", {}, { expectedRevision });
}

export function pickupItemCommand(itemInstanceId, expectedRevision) {
  return buildCommand("pickup_item", { item_instance_id: itemInstanceId }, { expectedRevision });
}

export function dropItemCommand(itemId, expectedRevision) {
  return buildCommand("drop_item", { item_id: itemId }, { expectedRevision });
}

export function tradeItemCommand(toHeroId, itemId, expectedRevision) {
  return buildCommand("trade_item", { to_hero_id: toHeroId, item_id: itemId }, { expectedRevision });
}

export function recoverBodyLootCommand(deadHeroId, itemIds, expectedRevision) {
  return buildCommand("recover_body_loot", { dead_hero_id: deadHeroId, item_ids: itemIds || null }, { expectedRevision });
}

// D1 abilities panel "Use" control: stacks-abilities' 04:30 post names the
// command `use_ability`, charge-gated the same way signature charges are.
// If the server hasn't wired it yet this resolves to an ordinary
// CommandError, handled the same as any other rejected command.
export function useAbilityCommand(abilityId, expectedRevision) {
  return buildCommand("use_ability", { ability_id: abilityId }, { expectedRevision });
}

// Wave-6B part 4 (docs/INFINITE_STACKS_CONTRACTS.md S5.11): interact/converse
// payloads match the domain vocabulary exactly. `interact` names an object +
// one of its own declared interaction ids -- never a free-text verb.
// `converse` never takes a modifier/tier from the client (standing rule #5):
// `appealObjectiveId` is a ROLEPLAY CHOICE naming which of the NPC's own
// disclosed objectives the hero is appealing to (or omitted entirely for "no
// appeal") -- the server derives the actual MotiveAlignment from its own
// authored NPC data, never trusting a client-supplied strength/tier. A
// legacy `motive_alignment` field is deliberately never built here at all.
export function interactCommand(objectId, interactionId, expectedRevision) {
  return buildCommand("interact", { object_id: objectId, interaction_id: interactionId }, { expectedRevision });
}

export function converseCommand(npcId, appealObjectiveId, expectedRevision) {
  return buildCommand("converse", { npc_id: npcId, appeal_objective_id: appealObjectiveId || null }, { expectedRevision });
}
