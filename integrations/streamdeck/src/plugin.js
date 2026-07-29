// The BetterFingers Stream Deck plugin — a thin adapter, and nothing more.
//
// WHAT "THIN" MEANS HERE, precisely: this file contains no workflow
// definitions, no action semantics, and no idea what dictation is. It knows how
// to turn a Stream Deck event into one BetterFingers action id and how to POST
// it. Everything a key can ask for is an id from
// backend/domain/input_actions.py, and the id is read out of the ACTION UUID the
// Stream Deck software itself sends -- never out of the key's settings -- so a
// key cannot be made to mean something other than the action it was created as.
//
// WHY THAT MATTERS MORE THAN IT LOOKS. A Stream Deck plugin runs outside
// BetterFingers, on a user's machine, and its settings blobs are user-editable
// JSON. If this file could assemble work -- a step list, a command, a message --
// it would be a second, unreviewed authoring surface for a product whose whole
// Wave 9 design is that authoring goes through an approval gate. So it cannot.
// `workflow.run` sends an id of a workflow the user already read and approved;
// BetterFingers re-fetches and re-validates it, and the Electron main process is
// the only thing that performs the steps.
//
// TRANSPORT IS INJECTED. `createPlugin` takes `send` (to the Stream Deck) and
// `post` (to BetterFingers). That is what makes the protocol testable with no
// deck and no server, which is the whole of the qualification story here: see
// QUALIFICATION.md. Nothing in this file constructs a socket.
//
// HOLDS. A holdable action (dictate, command) fires its begin id on keyDown and
// its end id on keyUp, and marks the keyDown `hold: true` so BetterFingers knows
// this key is holding something. If the deck is unplugged mid-sentence, that
// flag is what lets BetterFingers release the recording through the same path an
// unplugged controller uses -- there is no second unplug handler here.

const PLUGIN_UUID = 'com.betterfingers.streamdeck';

// The release half of each holdable action. Mirrors input_actions.py; asserted
// against it by tests/test_stream_deck_config.py so it cannot drift silently.
const RELEASE_FOR = {
  'dictation.begin': 'dictation.end',
  'command.begin': 'command.end',
};

// Which BetterFingers status codes mean "show the user something went wrong".
// `ok` is silent: a key that flashes on every successful press is a key that
// trains people to ignore it.
const ALERT_STATUSES = new Set([
  'unknown_action', 'unavailable', 'suspended', 'disabled', 'needs_param', 'failed',
]);

/** `com.betterfingers.streamdeck.latest.copy` -> `latest.copy`, else ''. */
function actionIdFor(pluginAction) {
  const text = String(pluginAction || '');
  const prefix = `${PLUGIN_UUID}.`;
  return text.startsWith(prefix) ? text.slice(prefix.length) : '';
}

/**
 * @param {object} deps
 * @param {function} deps.send  (message) => void          to the Stream Deck
 * @param {function} deps.post  (path, body) => Promise    to BetterFingers
 */
function createPlugin({ send, post } = {}) {
  // context -> { action, settings, device }. The Stream Deck is the source of
  // truth for what a key is; this map exists only so a keyDown can be answered
  // without asking for settings first.
  const keys = new Map();

  function reply(context, status) {
    if (!context) return;
    // showAlert / showOk are the only two feedback verbs a Stream Deck key has.
    // Using them honestly -- alert for anything that did not happen -- is what
    // makes a key that silently does nothing impossible.
    send({ event: ALERT_STATUSES.has(status) ? 'showAlert' : 'showOk', context });
  }

  async function dispatch(context, actionId, { hold = false } = {}) {
    const entry = keys.get(context) || {};
    const settings = entry.settings || {};
    const body = {
      action_id: actionId,
      // The parameter is whatever the property inspector stored. It is bounded
      // and validated on the BetterFingers side; nothing here interprets it.
      param: String(settings.param || ''),
      source: 'stream_deck',
      device_key: entry.device ? `stream_deck:${entry.device}` : 'stream_deck:unknown',
      hold,
    };
    try {
      const result = await post('/input/dispatch', body);
      reply(context, (result && result.status) || 'failed');
      return result;
    } catch {
      // A BetterFingers that is not running is the common case, not an
      // exception: the deck sits there all day and the app comes and goes.
      reply(context, 'failed');
      return { ok: false, status: 'failed' };
    }
  }

  /** Mirror a key into BetterFingers so the dashboard can show what the deck does. */
  async function mirror(context) {
    const entry = keys.get(context);
    if (!entry) return;
    try {
      await post('/stream-deck/key', {
        context,
        action: entry.action,
        device: entry.device || '',
        title: entry.title || '',
        coordinates: entry.coordinates || {},
        settings: entry.settings || {},
      });
    } catch {
      // A mirror that fails is cosmetic: the key still works, because a key
      // press carries its own action id. Never surface this to the user.
    }
  }

  /** One Stream Deck event in. Returns whatever it did, for tests. */
  async function handle(message) {
    const event = String((message && message.event) || '');
    const context = message && message.context;
    const payload = (message && message.payload) || {};

    switch (event) {
      case 'willAppear': {
        keys.set(context, {
          action: message.action,
          device: message.device,
          settings: payload.settings || {},
          title: payload.title || '',
          coordinates: payload.coordinates || {},
        });
        await mirror(context);
        return { mirrored: true };
      }
      case 'didReceiveSettings': {
        const entry = keys.get(context);
        if (entry) {
          entry.settings = payload.settings || {};
          entry.title = payload.title || entry.title;
        }
        await mirror(context);
        return { mirrored: true };
      }
      case 'titleParametersDidChange': {
        const entry = keys.get(context);
        if (entry) entry.title = payload.title || '';
        await mirror(context);
        return { mirrored: true };
      }
      case 'willDisappear': {
        keys.delete(context);
        try {
          await post('/stream-deck/key/forget', { context });
        } catch { /* cosmetic, as above */ }
        return { forgotten: true };
      }
      case 'deviceDidConnect': {
        try {
          await post('/stream-deck/device', {
            device: message.device,
            name: (message.deviceInfo || {}).name || '',
            size: ((message.deviceInfo || {}).size) || {},
            connected: true,
          });
        } catch { /* cosmetic */ }
        return { device: message.device };
      }
      case 'deviceDidDisconnect': {
        // The one event that is NOT cosmetic. Anything a key was holding has to
        // be released, and BetterFingers does that through the same path an
        // unplugged controller uses -- which is why this posts a disconnect
        // rather than trying to send release ids itself.
        try {
          await post('/stream-deck/device/disconnected', { device: message.device });
        } catch { /* the app is gone too; nothing is being held */ }
        return { device: message.device, released: true };
      }
      case 'keyDown': {
        const actionId = actionIdFor(message.action);
        if (!actionId) {
          reply(context, 'unknown_action');
          return { ignored: true };
        }
        // A holdable key waits for keyUp to end. A non-holdable one is done.
        return dispatch(context, actionId, { hold: Boolean(RELEASE_FOR[actionId]) });
      }
      case 'keyUp': {
        const actionId = actionIdFor(message.action);
        const releaseId = RELEASE_FOR[actionId];
        if (!releaseId) return { ignored: true };
        return dispatch(context, releaseId);
      }
      default:
        return { ignored: true };
    }
  }

  return { handle, actionIdFor, knownKeys: () => [...keys.keys()] };
}

/**
 * The Stream Deck registration handshake.
 *
 * Separate from `createPlugin` because it is the one part that is pure
 * ceremony: the deck passes these four values on the command line and expects
 * exactly this message back before it will send anything else.
 */
function registrationMessage({ registerEvent, pluginUUID }) {
  return { event: registerEvent, uuid: pluginUUID };
}

const api = {
  createPlugin,
  registrationMessage,
  actionIdFor,
  PLUGIN_UUID,
  RELEASE_FOR,
  ALERT_STATUSES,
};

// Dual export: the Stream Deck loads this file in its own browser-ish host with
// no module system, while the tests require it as CommonJS. Neither is optional
// -- a plugin that only works under the test harness is not a plugin.
if (typeof module !== 'undefined' && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== 'undefined') {
  globalThis.BetterFingersStreamDeck = api;
}
