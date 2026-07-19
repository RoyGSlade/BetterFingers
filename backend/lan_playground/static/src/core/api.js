// REST transport for Infinite Stacks (infinite_stacks.md S21.2 REST snapshot
// fallback + room create/join). Every call is a relative path -- no external
// URLs, no cookies, no localStorage. This module only makes network calls; it
// never touches the DOM or the store directly.

const ACCESS_CODE_HEADER = "X-Access-Code";
const PLAYER_TOKEN_HEADER = "X-Player-Token";

async function parseJsonResponse(resp) {
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const detail = data && data.detail;
    const error = new Error(typeof detail === "string" ? detail : "request_failed");
    error.status = resp.status;
    error.detail = detail;
    throw error;
  }
  return data;
}

export async function createRoom({ accessCode, hostName, seed }) {
  const resp = await fetch("/api/stacks/rooms", {
    method: "POST",
    headers: { "Content-Type": "application/json", [ACCESS_CODE_HEADER]: accessCode },
    body: JSON.stringify({ host_name: hostName, seed: seed ?? null }),
  });
  return parseJsonResponse(resp);
}

export async function joinRoom({ accessCode, roomCode, displayName }) {
  const resp = await fetch(`/api/stacks/rooms/${encodeURIComponent(roomCode)}/join`, {
    method: "POST",
    headers: { "Content-Type": "application/json", [ACCESS_CODE_HEADER]: accessCode },
    body: JSON.stringify({ display_name: displayName }),
  });
  return parseJsonResponse(resp);
}

export async function fetchSnapshot({ accessCode, roomCode, playerToken }) {
  const resp = await fetch(`/api/stacks/rooms/${encodeURIComponent(roomCode)}/snapshot`, {
    headers: { [ACCESS_CODE_HEADER]: accessCode, [PLAYER_TOKEN_HEADER]: playerToken },
  });
  return parseJsonResponse(resp);
}

// REST fallback for submitting a command when the WebSocket is unavailable.
// Same command envelope as the socket path (core/commands.js).
export async function submitCommandOverRest({ accessCode, roomCode, playerToken, command }) {
  const resp = await fetch(`/api/stacks/rooms/${encodeURIComponent(roomCode)}/commands`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      [ACCESS_CODE_HEADER]: accessCode,
      [PLAYER_TOKEN_HEADER]: playerToken,
    },
    body: JSON.stringify(command),
  });
  return parseJsonResponse(resp);
}
