// Session-level hardening for every window the app opens (Phase 0 items 6, 11).
//
// Electron/Chromium grants a long list of web permissions to any page by
// default: microphone and camera capture, screen capture, clipboard reads,
// geolocation, notifications, HID/serial/USB device pickers. BetterFingers
// renders only its own bundled pages and never needs most of them -- the
// backend records audio, main owns the clipboard and the registry -- so the
// session denies EVERYTHING by default and the policy below carves out the one
// thing a page legitimately does: capture AUDIO (never video) in the dashboard
// window, for the microphone test and the Voice Studio sample recorder.
//
// The decision functions are pure so the privilege boundary is unit-testable
// without launching Electron; installSessionSecurity() only wires them to a
// session.

const { isTrustedRendererUrl } = require('./senderValidation');

// The policy every shipped page is given as a response-header backstop when one
// is served over http (the electron-vite dev server). The packaged pages are
// file:// documents and carry the same policy in a <meta> tag; a unit test keeps
// those tags and this constant identical. No inline script, no remote anything:
// the renderer reaches the backend only through main's IPC proxy, so there is no
// legitimate network request for connect-src to allow.
const RENDERER_CSP = [
  "default-src 'none'",
  "script-src 'self'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  "media-src 'self' blob: data:",
  "connect-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
  "frame-src 'none'",
].join('; ');

// Permissions are checked from two places. The request handler gets the prompt
// ("may this page use X?"); the check handler gets the silent query Chromium
// makes first (for example before it will reveal device labels).
function decidePermission({
  permission,
  webContents,
  details = {},
  captureWebContents = null,
  rendererOptions = {},
} = {}) {
  // Only microphone capture, only in the dashboard window's top frame, only
  // when it is one of our own pages, and only when audio is ALL it asks for.
  if (permission !== 'media') return false;
  if (!captureWebContents || webContents !== captureWebContents) return false;
  if (details.isMainFrame === false) return false;
  const url = details.requestingUrl || details.securityOrigin || '';
  if (!isTrustedRendererUrl(url, rendererOptions)) return false;
  const types = Array.isArray(details.mediaTypes) ? details.mediaTypes : null;
  if (types) return types.length > 0 && types.every((type) => type === 'audio');
  // The check handler reports a single mediaType instead of a list.
  return details.mediaType === 'audio';
}

function installSessionSecurity(ses, {
  getCaptureWebContents = () => null,
  rendererOptions = () => ({}),
  devOrigin = process.env.ELECTRON_RENDERER_URL,
} = {}) {
  const decide = (webContents, permission, details) => decidePermission({
    permission,
    webContents,
    details,
    captureWebContents: getCaptureWebContents(),
    rendererOptions: rendererOptions(),
  });

  ses.setPermissionRequestHandler((webContents, permission, callback, details) => {
    let allowed = false;
    try {
      allowed = decide(webContents, permission, details || {});
    } catch {
      allowed = false;
    }
    if (!allowed) console.warn(`[security] Denied permission request: ${permission}`);
    callback(allowed);
  });

  ses.setPermissionCheckHandler((webContents, permission, requestingOrigin, details) => {
    try {
      return decide(webContents, permission, { ...(details || {}), securityOrigin: requestingOrigin });
    } catch {
      return false;
    }
  });

  // HID / serial / USB / Bluetooth pickers: nothing in the app uses them.
  if (typeof ses.setDevicePermissionHandler === 'function') {
    ses.setDevicePermissionHandler(() => false);
  }
  for (const picker of ['select-hid-device', 'select-serial-port', 'select-usb-device', 'select-bluetooth-device']) {
    if (typeof ses.on === 'function') {
      ses.on(picker, (event, _details, callback) => {
        event.preventDefault();
        if (typeof callback === 'function') callback('');
      });
    }
  }

  // Backstop CSP for documents served over http (the dev server). file:// pages
  // carry the policy in their own <meta> tag.
  const webRequest = ses.webRequest;
  if (webRequest && typeof webRequest.onHeadersReceived === 'function' && devOrigin) {
    let origin = '';
    try { origin = new URL(devOrigin).origin; } catch { origin = ''; }
    webRequest.onHeadersReceived((details, callback) => {
      const headers = { ...(details.responseHeaders || {}) };
      let isOurs = false;
      try { isOurs = origin && new URL(details.url).origin === origin; } catch { isOurs = false; }
      if (isOurs && (details.resourceType === 'mainFrame' || details.resourceType === 'subFrame')) {
        for (const key of Object.keys(headers)) {
          if (key.toLowerCase() === 'content-security-policy') delete headers[key];
        }
        headers['Content-Security-Policy'] = [RENDERER_CSP];
      }
      callback({ responseHeaders: headers });
    });
  }
}

// Every WebContents the app ever creates, not just the four windows we build by
// hand today: a window added later inherits the same locks without anyone
// remembering to call hardenWindowNavigation (Phase 0 review L9).
function guardNewWebContents(app, { isTrustedUrl } = {}) {
  app.on('web-contents-created', (_event, contents) => {
    contents.on('will-attach-webview', (event) => event.preventDefault());
    contents.setWindowOpenHandler?.(() => ({ action: 'deny' }));
    contents.on('will-navigate', (event, url) => {
      if (typeof isTrustedUrl === 'function' && !isTrustedUrl(url)) event.preventDefault();
    });
  });
}

module.exports = {
  RENDERER_CSP,
  decidePermission,
  installSessionSecurity,
  guardNewWebContents,
};
