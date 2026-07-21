// Player token art (playtest F1: "Replace [the name string filling the room
// tile] with a token -- player picks an avatar, and its hue is adjusted to
// the player's chosen color"). Takes plain token data (core/selectors.js's
// selectHeroToken) -- pure DOM construction, no network/store/timers. The
// hue-rotate itself lives in CSS (.stacks-token-hue-<color> in stacks.css,
// applied as a class, never an inline style) so it stays CSP-safe.

export function renderToken(token, { size = "md" } = {}) {
  const wrap = document.createElement("span");
  wrap.className = `stacks-token stacks-token--${size}`;
  if (!token) {
    wrap.classList.add("stacks-token--empty");
    return wrap;
  }
  const img = document.createElement("img");
  img.className = `stacks-token-image ${token.colorClass}`;
  img.src = token.avatarSrc;
  // Decorative -- every caller pairs this with the hero's real name as text
  // (S24.1/S25: never identify a hero by art/color alone).
  img.alt = "";
  img.setAttribute("aria-hidden", "true");
  wrap.appendChild(img);
  return wrap;
}
