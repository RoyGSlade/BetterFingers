// WebSocket transport for Infinite Stacks (infinite_stacks.md S21.2). Owns
// exactly one concern: opening/maintaining the socket connection and moving
// bytes. It never mutates the store and never touches the DOM -- callers pass
// in onMessage/onConnectionChange callbacks and this module only calls them.

const RECONNECT_DELAYS_MS = [500, 1000, 2000, 4000, 8000, 8000];

// Connection states surfaced to the UI, per S21.2/S24 "visible connection,
// ready, composing, reacting, and reconnecting states".
export const CONNECTION_STATES = Object.freeze({
  IDLE: "idle",
  CONNECTING: "connecting",
  OPEN: "open",
  RECONNECTING: "reconnecting",
  CLOSED: "closed",
});

export function createStacksSocket({ roomCode, accessCode, playerToken, onMessage, onConnectionChange }) {
  let ws = null;
  let attempt = 0;
  let sinceRevision = 0;
  let closedByUser = false;
  let reconnectTimer = null;

  function setConnectionState(state) {
    if (onConnectionChange) onConnectionChange(state);
  }

  function buildUrl() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const params = new URLSearchParams({
      access_code: accessCode,
      token: playerToken,
      since_revision: String(sinceRevision),
    });
    return `${proto}//${window.location.host}/ws/stacks/${encodeURIComponent(roomCode)}?${params.toString()}`;
  }

  function trackRevision(message) {
    if (typeof message.revision === "number") {
      sinceRevision = Math.max(sinceRevision, message.revision);
    }
    if (message.kind === "reconnect_summary" && message.snapshot && typeof message.snapshot.revision === "number") {
      sinceRevision = Math.max(sinceRevision, message.snapshot.revision);
    }
  }

  function connect() {
    closedByUser = false;
    setConnectionState(attempt === 0 ? CONNECTION_STATES.CONNECTING : CONNECTION_STATES.RECONNECTING);
    ws = new WebSocket(buildUrl());

    ws.addEventListener("open", () => {
      attempt = 0;
      setConnectionState(CONNECTION_STATES.OPEN);
    });

    ws.addEventListener("message", (evt) => {
      let message;
      try {
        message = JSON.parse(evt.data);
      } catch {
        return;
      }
      trackRevision(message);
      onMessage(message);
    });

    ws.addEventListener("close", () => {
      if (closedByUser) {
        setConnectionState(CONNECTION_STATES.CLOSED);
        return;
      }
      setConnectionState(CONNECTION_STATES.RECONNECTING);
      scheduleReconnect();
    });

    ws.addEventListener("error", () => {
      // The close handler always follows an error and does the real work.
    });
  }

  function scheduleReconnect() {
    const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)];
    attempt += 1;
    reconnectTimer = window.setTimeout(connect, delay);
  }

  function send(message) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(message));
      return true;
    }
    return false;
  }

  function sendCommand(command) {
    return send({ kind: "command", command });
  }

  function sendPresence(ready) {
    return send({ kind: "presence", ready });
  }

  function close() {
    closedByUser = true;
    if (reconnectTimer) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (ws) ws.close();
  }

  return { connect, close, sendCommand, sendPresence };
}
