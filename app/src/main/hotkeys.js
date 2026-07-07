const { globalShortcut } = require('electron');
const { net } = require('electron');
const { BACKEND_HOST, BACKEND_PORT } = require('./config');

let activeConfig = null;
let authToken = null;

function normalizeToElectronAccelerator(hotkey) {
  if (!hotkey) return null;
  // Convert something like "ctrl+shift+space" or "F8" to "CommandOrControl+Shift+Space" / "F8"
  return hotkey
    .split('+')
    .map(part => {
      const p = part.trim().toLowerCase();
      if (p === 'ctrl' || p === 'control') return 'CommandOrControl';
      if (p === 'shift') return 'Shift';
      if (p === 'alt') return 'Alt';
      if (p === 'super' || p === 'cmd' || p === 'command' || p === 'win' || p === 'windows') return 'Super';
      // capitalize first letter for keys like "Space", "Enter", etc.
      if (p.length > 1) return p.charAt(0).toUpperCase() + p.slice(1);
      // single characters are usually uppercase
      return p.toUpperCase();
    })
    .join('+');
}

function triggerBackendAction(endpoint) {
  if (!authToken) {
    console.error(`Cannot trigger ${endpoint}: authToken is not set.`);
    return;
  }
  
  const request = net.request({
    method: 'POST',
    protocol: 'http:',
    hostname: BACKEND_HOST,
    port: BACKEND_PORT,
    path: endpoint,
  });

  request.setHeader('Authorization', `Bearer ${authToken}`);
  
  request.on('response', (response) => {
    if (response.statusCode !== 200) {
      console.warn(`Hotkey triggered ${endpoint} but backend returned ${response.statusCode}`);
    }
  });

  request.on('error', (error) => {
    console.error(`Hotkey trigger failed for ${endpoint}:`, error);
  });

  request.end();
}

function registerHotkeys(config, token) {
  if (token) {
    authToken = token;
  }
  
  // Unregister all previous hotkeys first
  globalShortcut.unregisterAll();

  if (!config) return;
  activeConfig = config;

  const mapping = [
    { key: config.hotkey, endpoint: '/runtime/recording/toggle' },
    { key: config.force_stop_key, endpoint: '/runtime/emergency-stop' },
    { key: config.manual_send_hotkey, endpoint: '/runtime/primary-action' },
    { key: config.review_tts_hotkey, endpoint: '/runtime/tts/toggle' }
  ];

  for (const { key, endpoint } of mapping) {
    const accelerator = normalizeToElectronAccelerator(key);
    if (accelerator) {
      try {
        const success = globalShortcut.register(accelerator, () => {
          triggerBackendAction(endpoint);
        });
        if (!success) {
          console.warn(`Failed to register global shortcut: ${accelerator}`);
        }
      } catch (err) {
        console.error(`Error registering accelerator ${accelerator}:`, err);
      }
    }
  }
}

function unregisterAllHotkeys() {
  globalShortcut.unregisterAll();
}

module.exports = {
  registerHotkeys,
  unregisterAllHotkeys
};
