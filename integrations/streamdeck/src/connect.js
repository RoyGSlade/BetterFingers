// The Stream Deck's entry point. Ceremony only — every decision lives in
// plugin.js, which is why this file has no tests of its own and plugin.js has
// many.
//
// The Stream Deck software calls `connectElgatoStreamDeckSocket` with four
// values, expects a registration message back on the socket, and then streams
// events. The only BetterFingers-specific part is `post`: the plugin talks to
// the local BetterFingers HTTP API with the bearer token the user pasted into
// the property inspector during pairing. That token is stored in the plugin's
// GLOBAL settings (Stream Deck's own per-plugin store), not in a file this
// project writes, and BetterFingers keeps only a fingerprint of it — see
// backend/stores/stream_deck_config.py.

/* global WebSocket, fetch, BetterFingersStreamDeck */

const DEFAULT_ORIGIN = 'http://127.0.0.1:8000';

// eslint-disable-next-line no-unused-vars
function connectElgatoStreamDeckSocket(inPort, inPluginUUID, inRegisterEvent, inInfo) {
  const { createPlugin, registrationMessage } = BetterFingersStreamDeck;
  const socket = new WebSocket(`ws://127.0.0.1:${inPort}`);

  let origin = DEFAULT_ORIGIN;
  let token = '';

  const send = (message) => {
    if (socket.readyState === 1) socket.send(JSON.stringify(message));
  };

  const post = async (path, body) => {
    const response = await fetch(`${origin}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(body),
    });
    return response.json();
  };

  const plugin = createPlugin({ send, post });

  socket.onopen = () => {
    send(registrationMessage({ registerEvent: inRegisterEvent, pluginUUID: inPluginUUID }));
    // Ask for the pairing token the property inspector saved.
    send({ event: 'getGlobalSettings', context: inPluginUUID });
  };

  socket.onmessage = (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.event === 'didReceiveGlobalSettings') {
      const settings = (message.payload || {}).settings || {};
      token = String(settings.token || '');
      origin = String(settings.origin || DEFAULT_ORIGIN);
      if (token) post('/stream-deck/pair', { token }).catch(() => {});
      return;
    }
    plugin.handle(message).catch(() => {});
  };
}
