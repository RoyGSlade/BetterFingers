'use strict';

// Which page may call which IPC channel (Phase 0 item 7).
//
// Every IPC handler already checked that the sender is ONE OF the app's own pages
// (senderValidation.js). That is not enough: the always-on-top Signal Engineer face,
// the review overlay and the splash used to receive the dashboard's whole bridge,
// so a bug in any of them would have been able to approve workflows, send drafts,
// factory-reset or open paths. Each window now gets a minimal preload with only the
// calls its page makes, and this table makes main refuse a channel from any page
// that is not listed for it, even if a page somehow had the bridge method.

const DASHBOARD_PAGES = Object.freeze(['signal-desk.html', 'signal-desk-preview.html', 'index.html']);
const OVERLAY_PAGES = Object.freeze(['overlay.html']);
const REVIEW_PAGES = Object.freeze(['review-overlay.html']);
const SPLASH_PAGES = Object.freeze(['splash.html']);

// Channels that are NOT dashboard-only. Anything not listed here is dashboard-only,
// so a new channel is closed to every other window until someone opens it on purpose.
const CHANNEL_PAGES = Object.freeze({
  // The splash's boot state and its Retry button.
  'splash:get-state': SPLASH_PAGES,
  'splash:retry': SPLASH_PAGES,
  // The face/ring overlay only ever toggles click-through.
  'overlay:set-ignore-mouse-events': OVERLAY_PAGES,
  // The review overlay acknowledges which draft it painted, and can close itself.
  'review:displayed': REVIEW_PAGES,
  'review:hide': [...REVIEW_PAGES, ...DASHBOARD_PAGES],
  // The review overlay reads and edits drafts through the proxy, and its Accept /
  // Place buttons use the brokered send (a native dialog still approves it).
  'backend:request': [...DASHBOARD_PAGES, ...REVIEW_PAGES],
  'backend:send-draft': [...DASHBOARD_PAGES, ...REVIEW_PAGES],
});

function allowedPagesFor(channel) {
  return CHANNEL_PAGES[channel] || DASHBOARD_PAGES;
}

function isPageAllowed(channel, pageName) {
  return typeof pageName === 'string' && allowedPagesFor(channel).includes(pageName);
}

module.exports = {
  DASHBOARD_PAGES,
  OVERLAY_PAGES,
  REVIEW_PAGES,
  SPLASH_PAGES,
  CHANNEL_PAGES,
  allowedPagesFor,
  isPageAllowed,
};
