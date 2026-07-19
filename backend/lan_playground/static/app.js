"use strict";
/*
 * Spellcheck & Sorcery -- LAN party game client (board #41).
 *
 * No microphone/audio/TTS APIs are used here (text-only, canvas-and-DOM
 * game). The site access code and any room/player tokens live only in
 * module-scope variables for this page load -- never persisted by the
 * browser in any way -- and any `?code=`/`?room=` query params are read
 * once, then stripped from the visible URL immediately. All
 * player-supplied strings (names, move text) are rendered with
 * textContent only, never raw-HTML insertion.
 */

(function () {
  // ---------------------------------------------------------------------
  // Virtual scheduler -- lets window.advanceTime(ms) deterministically
  // fast-forward polling/animation without waiting on the real clock, for
  // automated interaction tests.
  // ---------------------------------------------------------------------
  const timers = [];
  let nextTimerId = 1;

  function vSetTimeout(cb, delay) {
    const id = nextTimerId++;
    timers.push({ id, remaining: Math.max(0, delay), delay, cb, repeat: false });
    return id;
  }

  function vSetInterval(cb, delay) {
    const id = nextTimerId++;
    timers.push({ id, remaining: Math.max(1, delay), delay: Math.max(1, delay), cb, repeat: true });
    return id;
  }

  function vClearTimer(id) {
    const idx = timers.findIndex(function (t) { return t.id === id; });
    if (idx !== -1) {
      timers.splice(idx, 1);
    }
  }

  function advanceTime(ms) {
    // Discrete-event step: each iteration consumes elapse = min(time until
    // the nearest timer, remaining budget) from every live timer, then fires
    // whichever timer(s) hit zero. Consuming the full budget even when
    // nothing is due yet is required so repeated small calls (a real-time
    // driver ticking every 100ms, or a test calling advanceTime() several
    // times) accumulate correctly toward a timer whose delay exceeds any
    // single call's budget -- e.g. the 1500ms poll interval.
    let budget = typeof ms === "number" && ms > 0 ? ms : 0;
    let guard = 0;
    while (budget > 0 && timers.length > 0 && guard < 10000) {
      guard += 1;
      let pickIdx = 0;
      for (let i = 1; i < timers.length; i += 1) {
        if (timers[i].remaining < timers[pickIdx].remaining) {
          pickIdx = i;
        }
      }
      const elapse = Math.min(timers[pickIdx].remaining, budget);
      for (let i = 0; i < timers.length; i += 1) {
        timers[i].remaining -= elapse;
      }
      budget -= elapse;
      if (timers[pickIdx].remaining > 0) {
        break; // budget exhausted before the nearest timer came due
      }
      const fired = timers[pickIdx];
      if (fired.repeat) {
        fired.remaining = fired.delay;
      } else {
        timers.splice(pickIdx, 1);
      }
      try {
        fired.cb();
      } catch (err) {
        /* keep advancing even if a callback throws */
      }
    }
  }

  // The virtual scheduler above only fires callbacks in response to
  // advanceTime(ms) -- nothing drives it by itself. window.advanceTime is a
  // required *test* hook (see progress.md) for deterministic fast-forwarding,
  // but real players in a real browser never call it. Without a real-clock
  // driver, polling/animation would run exactly once at boot and then never
  // again. This ticks the same virtual timers off actual elapsed wall-clock
  // time so gameplay works normally outside of tests; a test calling
  // advanceTime(ms) on top of this just fast-forwards further, harmlessly.
  let lastRealTickAt = null;
  function tickRealClock() {
    const now = Date.now();
    const elapsed = lastRealTickAt === null ? 0 : now - lastRealTickAt;
    lastRealTickAt = now;
    if (elapsed > 0) {
      advanceTime(elapsed);
    }
  }
  window.setInterval(tickRealClock, 100);

  // ---------------------------------------------------------------------
  // In-memory-only session state
  // ---------------------------------------------------------------------
  let accessCode = "";
  let roomId = null;
  let hostToken = null;
  let playerToken = null;
  let playerId = null;
  let joinCode = "";
  let joinUrl = "";

  let state = null; // last state document from the server
  let screen = "gate"; // gate | home | lobby | board | finale
  let moveFormRoundKey = null; // tracks which round the move form was last reset for
  let personasLoaded = false;

  let pollTimerId = null;
  let pollFailures = 0;
  let pollInFlight = false;
  const POLL_INTERVAL_MS = 1500;
  const POLL_MAX_INTERVAL_MS = 8000;

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let animRoomIndex = 0;

  // ---------------------------------------------------------------------
  // DOM references
  // ---------------------------------------------------------------------
  const els = {
    status: document.getElementById("game-status"),
    errorBanner: document.getElementById("error-banner"),
    fullscreenToggle: document.getElementById("fullscreen-toggle"),

    gate: document.getElementById("access-gate"),
    gateInput: document.getElementById("access-code-input"),
    gateSubmit: document.getElementById("access-code-submit"),
    gateStatus: document.getElementById("access-gate-status"),

    home: document.getElementById("home-screen"),
    createForm: document.getElementById("create-form"),
    createName: document.getElementById("create-name"),
    joinForm: document.getElementById("join-form"),
    joinCodeInput: document.getElementById("join-code-input"),
    joinNameInput: document.getElementById("join-name-input"),
    homeStatus: document.getElementById("home-status"),

    lobby: document.getElementById("lobby-screen"),
    lobbyCode: document.getElementById("lobby-code"),
    lobbyLink: document.getElementById("lobby-link"),
    copyCodeButton: document.getElementById("copy-code-button"),
    copyLinkButton: document.getElementById("copy-link-button"),
    lobbyQr: document.getElementById("lobby-qr"),
    lobbyPlayers: document.getElementById("lobby-players"),
    lobbySoloHint: document.getElementById("lobby-solo-hint"),
    startButton: document.getElementById("start-button"),
    lobbyStatus: document.getElementById("lobby-status"),

    board: document.getElementById("board-screen"),
    canvas: document.getElementById("board-canvas"),
    encounterArt: document.getElementById("encounter-art"),
    encounterCaption: document.getElementById("encounter-caption"),
    heartsDisplay: document.getElementById("hearts-display"),
    playersRoster: document.getElementById("players-roster"),

    moveForm: document.getElementById("move-form"),
    movePersona: document.getElementById("move-persona"),
    moveText: document.getElementById("move-text"),
    moveTextCount: document.getElementById("move-text-count"),
    moveSubmit: document.getElementById("move-submit"),
    moveStatus: document.getElementById("move-status"),

    waitingPanel: document.getElementById("waiting-panel"),
    waitingCount: document.getElementById("waiting-count"),

    revealPanel: document.getElementById("reveal-panel"),
    revealList: document.getElementById("reveal-list"),
    roundSummary: document.getElementById("round-summary"),
    advanceButton: document.getElementById("advance-button"),
    advanceStatus: document.getElementById("advance-status"),

    finale: document.getElementById("finale-screen"),
    finaleArt: document.getElementById("finale-art"),
    finaleHeading: document.getElementById("finale-heading"),
    finaleSummary: document.getElementById("finale-summary"),
    replayButton: document.getElementById("replay-button"),
  };

  const ctx = els.canvas.getContext("2d");

  // ---------------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------------
  function announce(text) {
    els.status.textContent = text;
  }

  function showError(message, opts) {
    const options = opts || {};
    els.errorBanner.textContent = message;
    els.errorBanner.hidden = false;
    if (!options.sticky) {
      vSetTimeout(function () {
        if (els.errorBanner.textContent === message) {
          clearError();
        }
      }, 6000);
    }
  }

  function clearError() {
    els.errorBanner.hidden = true;
    els.errorBanner.textContent = "";
  }

  function readParamsFromUrl() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const room = params.get("room");
    if (code !== null || room !== null) {
      params.delete("code");
      params.delete("room");
      const rest = params.toString();
      const cleanUrl = window.location.pathname + (rest ? "?" + rest : "");
      window.history.replaceState(null, "", cleanUrl);
    }
    return { code: code || "", room: room || "" };
  }

  async function apiFetch(path, options) {
    const opts = options || {};
    const headers = Object.assign({}, opts.headers || {}, { "X-Access-Code": accessCode });
    if (hostToken) {
      headers["X-Host-Token"] = hostToken;
    }
    if (playerToken) {
      headers["X-Player-Token"] = playerToken;
    }
    return fetch(path, Object.assign({}, opts, { headers }));
  }

  // ---------------------------------------------------------------------
  // Screen management
  // ---------------------------------------------------------------------
  function setScreen(next) {
    screen = next;
    els.gate.hidden = next !== "gate";
    els.home.hidden = next !== "home";
    els.lobby.hidden = next !== "lobby";
    els.board.hidden = next !== "board";
    els.finale.hidden = next !== "finale";
  }

  function lockOut(message) {
    accessCode = "";
    hostToken = null;
    playerToken = null;
    roomId = null;
    playerId = null;
    state = null;
    stopPolling();
    setScreen("gate");
    els.gateStatus.textContent = message;
  }

  function backToHome(message) {
    hostToken = null;
    playerToken = null;
    roomId = null;
    playerId = null;
    state = null;
    stopPolling();
    setScreen("home");
    els.homeStatus.textContent = message || "";
  }

  // ---------------------------------------------------------------------
  // Access gate
  // ---------------------------------------------------------------------
  function unlock(code) {
    accessCode = code;
    setScreen("home");
    loadPersonas();
  }

  async function loadPersonas() {
    if (personasLoaded) {
      return;
    }
    try {
      const resp = await apiFetch("/api/personas");
      if (resp.status === 401) {
        lockOut("That access code was rejected. Reload the page and try again.");
        return;
      }
      if (!resp.ok) {
        return;
      }
      const data = await resp.json();
      const personas = data.personas || [];
      els.movePersona.innerHTML = "";
      personas.forEach(function (name) {
        const opt = document.createElement("option");
        opt.value = name;
        opt.textContent = name;
        els.movePersona.appendChild(opt);
      });
      personasLoaded = personas.length > 0;
    } catch (err) {
      /* persona select will just show the loading placeholder; harmless */
    }
  }

  // ---------------------------------------------------------------------
  // Home: create / join
  // ---------------------------------------------------------------------
  async function createRoom(event) {
    event.preventDefault();
    const name = els.createName.value.trim();
    if (!name) {
      els.homeStatus.textContent = "Enter a hero name first.";
      return;
    }
    els.homeStatus.textContent = "Creating room…";
    try {
      const resp = await apiFetch("/api/game/rooms", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host_name: name }),
      });
      if (resp.status === 401) {
        lockOut("That access code was rejected. Reload the page and try again.");
        return;
      }
      if (!resp.ok) {
        els.homeStatus.textContent = describeApiFailure(resp.status, "The game server couldn't create a room.");
        return;
      }
      const data = await resp.json();
      applyRoomEntry(data);
    } catch (err) {
      els.homeStatus.textContent = "Couldn't reach the game server. Check that it's running and try again.";
    }
  }

  async function joinRoom(event) {
    event.preventDefault();
    const code = els.joinCodeInput.value.trim().toUpperCase();
    const name = els.joinNameInput.value.trim();
    if (!code || !name) {
      els.homeStatus.textContent = "Enter a room code and a hero name first.";
      return;
    }
    els.homeStatus.textContent = "Joining…";
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(code) + "/join", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ join_code: code, display_name: name }),
      });
      if (resp.status === 401) {
        lockOut("That access code was rejected. Reload the page and try again.");
        return;
      }
      if (resp.status === 404) {
        els.homeStatus.textContent = "No room with that code. Double-check it with the host.";
        return;
      }
      if (resp.status === 409) {
        const body = await resp.json().catch(function () { return {}; });
        els.homeStatus.textContent =
          body.detail === "room_full"
            ? "That room already has 4 heroes. Ask the host to open a new one."
            : "That adventure has already started. Ask the host for the next one.";
        return;
      }
      if (!resp.ok) {
        els.homeStatus.textContent = describeApiFailure(resp.status, "Couldn't join that room.");
        return;
      }
      const data = await resp.json();
      roomId = data.room_id || code;
      applyRoomEntry(data);
    } catch (err) {
      els.homeStatus.textContent = "Couldn't reach the game server. Check that it's running and try again.";
    }
  }

  function applyRoomEntry(data) {
    roomId = data.room_id || roomId;
    hostToken = data.host_token || null;
    playerToken = data.player_token || playerToken;
    playerId = data.player_id || playerId;
    joinCode = data.join_code || joinCode;
    joinUrl = data.join_url || joinUrl;
    els.homeStatus.textContent = "";
    applyState(data.state || data);
    startPolling();
  }

  function describeApiFailure(status, fallback) {
    if (status === 404) {
      return "The game backend isn't available yet on this server.";
    }
    if (status === 429) {
      return "The server is busy right now. Try again shortly.";
    }
    return fallback + " (status " + status + ")";
  }

  // ---------------------------------------------------------------------
  // Polling / reconnect
  // ---------------------------------------------------------------------
  function startPolling() {
    stopPolling();
    pollFailures = 0;
    pollTimerId = vSetTimeout(pollTick, 0);
  }

  function stopPolling() {
    if (pollTimerId !== null) {
      vClearTimer(pollTimerId);
      pollTimerId = null;
    }
  }

  async function pollTick() {
    if (!roomId || pollInFlight) {
      scheduleNextPoll();
      return;
    }
    pollInFlight = true;
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(roomId) + "/state");
      if (resp.status === 401) {
        lockOut("That access code was rejected. Reload the page and try again.");
        return;
      }
      if (resp.status === 404) {
        backToHome("That room ended or expired.");
        return;
      }
      if (!resp.ok) {
        pollFailures += 1;
        showError("The game server returned an error (status " + resp.status + "). Retrying…");
        scheduleNextPoll();
        return;
      }
      pollFailures = 0;
      clearError();
      const data = await resp.json();
      applyState(data);
      scheduleNextPoll();
    } catch (err) {
      pollFailures += 1;
      showError("Can't reach the game server. Retrying…", { sticky: true });
      scheduleNextPoll();
    } finally {
      pollInFlight = false;
    }
  }

  function scheduleNextPoll() {
    if (!roomId) {
      return;
    }
    const backoff = Math.min(POLL_INTERVAL_MS * Math.pow(2, Math.min(pollFailures, 4)), POLL_MAX_INTERVAL_MS);
    pollTimerId = vSetTimeout(pollTick, pollFailures > 0 ? backoff : POLL_INTERVAL_MS);
  }

  // ---------------------------------------------------------------------
  // Applying state -> screen + render
  // ---------------------------------------------------------------------
  function isFinale(s) {
    return s.phase === "finished" || s.finished_victory === true || s.finished_victory === false;
  }

  function isLobby(s) {
    return s.phase === "lobby";
  }

  function findYou(s) {
    const you = s.you || {};
    const players = s.players || [];
    const match = players.find(function (p) { return p.player_id === you.player_id || p.player_id === playerId; });
    return Object.assign({}, match || {}, you);
  }

  function applyState(s) {
    if (!s || typeof s !== "object") {
      return;
    }
    state = s;
    if (s.you && s.you.player_id) {
      playerId = s.you.player_id;
    }
    if (s.join_code) {
      joinCode = s.join_code;
    }
    if (s.join_url) {
      joinUrl = s.join_url;
    }

    if (isFinale(s)) {
      setScreen("finale");
      renderFinale(s);
      announce("The adventure has ended.");
      return;
    }
    if (isLobby(s)) {
      setScreen("lobby");
      renderLobby(s);
      announce("In the lobby with " + ((s.players || []).length) + " hero(es).");
      return;
    }
    setScreen("board");
    renderBoard(s);
  }

  // ---------------------------------------------------------------------
  // Lobby rendering
  // ---------------------------------------------------------------------
  function renderLobby(s) {
    // Being back in the lobby (fresh game or a replay) means any leftover
    // move-form state from a previous game is stale; force the next board
    // render to reset it rather than comparing round numbers that also
    // start over at 0 for a replay.
    moveFormRoundKey = null;
    els.lobbyCode.textContent = joinCode || "–";
    els.lobbyLink.textContent = joinUrl || "";
    if (joinUrl && /^https?:\/\//i.test(joinUrl)) {
      els.lobbyLink.setAttribute("data-href", joinUrl);
    }

    renderQr(s);

    const players = s.players || [];
    els.lobbyPlayers.innerHTML = "";
    players.forEach(function (p) {
      const li = document.createElement("li");
      li.className = "player-list-item";
      const nameSpan = document.createElement("span");
      nameSpan.className = "player-name";
      nameSpan.textContent = p.name || "Hero";
      li.appendChild(nameSpan);
      if (p.is_host) {
        const tag = document.createElement("span");
        tag.className = "player-tag";
        tag.textContent = "Host";
        li.appendChild(tag);
      }
      if (p.active === false) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-warn";
        tag.textContent = "Disconnected";
        li.appendChild(tag);
      }
      els.lobbyPlayers.appendChild(li);
    });

    const you = findYou(s);
    els.lobbySoloHint.hidden = players.length > 1;
    if (you.is_host) {
      els.startButton.hidden = false;
      els.startButton.textContent = players.length > 1 ? "Start the adventure" : "Start solo adventure";
      els.lobbyStatus.textContent = "";
    } else {
      els.startButton.hidden = true;
      els.lobbyStatus.textContent = "Waiting for the host to start…";
    }
  }

  const SVG_ALLOWED_TAGS = new Set(["svg", "g", "path", "rect", "polygon", "line", "circle", "title", "desc"]);
  const SVG_ALLOWED_ATTRS = new Set([
    "d", "x", "y", "width", "height", "fill", "viewbox", "xmlns", "class",
    "points", "cx", "cy", "r", "stroke", "stroke-width", "shape-rendering",
  ]);

  function sanitizeSvgElement(el) {
    if (!SVG_ALLOWED_TAGS.has(el.tagName.toLowerCase())) {
      return null;
    }
    for (const attr of Array.from(el.attributes)) {
      if (!SVG_ALLOWED_ATTRS.has(attr.name.toLowerCase())) {
        el.removeAttribute(attr.name);
      }
    }
    for (const child of Array.from(el.children)) {
      if (!sanitizeSvgElement(child)) {
        el.removeChild(child);
      }
    }
    return el;
  }

  function renderQr(s) {
    els.lobbyQr.innerHTML = "";
    const dataUrl = s.join_qr_data_url;
    const svgText = s.join_qr_svg;
    if (typeof dataUrl === "string" && dataUrl.indexOf("data:image/") === 0) {
      const img = document.createElement("img");
      img.src = dataUrl;
      img.width = 176;
      img.height = 176;
      img.alt = "Scan to join room " + (joinCode || "");
      els.lobbyQr.appendChild(img);
      return;
    }
    if (typeof svgText === "string" && svgText.trim().indexOf("<svg") === 0) {
      try {
        const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
        const root = doc.documentElement;
        if (root && root.tagName && root.tagName.toLowerCase() === "svg" && !doc.querySelector("parsererror")) {
          const clean = sanitizeSvgElement(root);
          if (clean) {
            clean.setAttribute("width", "176");
            clean.setAttribute("height", "176");
            clean.setAttribute("role", "img");
            clean.setAttribute("aria-label", "Scan to join room " + (joinCode || ""));
            els.lobbyQr.appendChild(clean);
            return;
          }
        }
      } catch (err) {
        /* fall through to text fallback */
      }
    }
    const fallback = document.createElement("p");
    fallback.className = "hint";
    fallback.textContent = "No scannable code yet — share the room code or link above instead.";
    els.lobbyQr.appendChild(fallback);
  }

  // ---------------------------------------------------------------------
  // Board rendering
  // ---------------------------------------------------------------------
  const CARD_LABELS = { charm: "Charm", scheme: "Scheme", bonk: "Bonk" };
  const ENCOUNTER_ART = {
    passive_aggressive_troll: "/art/encounter-troll.png",
    goblin_hr_department: "/art/encounter-goblins.png",
    suggestion_box_mimic: "/art/encounter-mimic.png",
    needlessly_complicated_riddle_bridge: "/art/encounter-bridge.png",
    red_tape_dragon: "/art/encounter-dragon.png",
  };

  // The engine deliberately never reveals an encounter's weakness ahead of
  // time (see docs/LAN_GAME_SPEC.md) -- card choice is a gamble/vibe check,
  // not a min-max decision. Past encounters come from `history`, the
  // current one from `encounter`; anything further out is unknown.
  function buildEncounterSlots(s) {
    const total = typeof s.total_rounds === "number" ? s.total_rounds : 5;
    const roundIndex = typeof s.round_index === "number" ? s.round_index : 0;
    const history = s.history || [];
    const slots = [];
    for (let i = 0; i < total; i += 1) {
      if (i < roundIndex && history[i]) {
        slots.push({ name: history[i].encounter && history[i].encounter.name, status: "cleared" });
      } else if (i === roundIndex && s.encounter) {
        slots.push({ name: s.encounter.name, status: "current" });
      } else {
        slots.push({ name: null, status: "unknown" });
      }
    }
    return slots;
  }

  function renderBoard(s) {
    const roundIndex = typeof s.round_index === "number" ? s.round_index : 0;
    const slots = buildEncounterSlots(s);

    renderHearts(s.hearts, s.max_hearts);
    renderRoster(s);
    renderEncounterArt(s.encounter || {});
    drawBoardCanvas(slots, roundIndex);

    const you = findYou(s);
    const lastRound = s.last_round;
    const revealing = s.phase === "reveal" && !!lastRound;
    const submitted = !!you.submitted;

    els.moveForm.hidden = revealing || submitted;
    els.waitingPanel.hidden = revealing || !submitted;
    els.revealPanel.hidden = !revealing;

    if (!revealing && !submitted) {
      renderMoveForm(s);
    } else if (!revealing && submitted) {
      const players = s.players || [];
      const total = players.length;
      const received = players.filter(function (p) { return p.submitted; }).length;
      els.waitingCount.textContent = "(" + received + " / " + total + " submitted)";
    } else {
      renderReveal(lastRound, you);
    }
  }

  function renderEncounterArt(encounter) {
    const name = encounter.name || "Mysterious administrative obstacle";
    els.encounterArt.src = ENCOUNTER_ART[encounter.id] || "/art/encounter-troll.png";
    els.encounterArt.alt = name + " encounter illustration";
    els.encounterCaption.textContent = name;
  }

  function renderHearts(hearts, maxHearts) {
    const max = typeof maxHearts === "number" ? maxHearts : 3;
    const current = typeof hearts === "number" ? hearts : max;
    els.heartsDisplay.innerHTML = "";
    for (let i = 0; i < max; i += 1) {
      const span = document.createElement("span");
      span.className = "heart-icon" + (i < current ? " heart-full" : " heart-empty");
      span.textContent = i < current ? "❤" : "♡";
      els.heartsDisplay.appendChild(span);
    }
    els.heartsDisplay.setAttribute("aria-label", current + " of " + max + " hearts remaining");
  }

  function renderRoster(s) {
    const players = s.players || [];
    els.playersRoster.innerHTML = "";
    players.forEach(function (p) {
      const li = document.createElement("li");
      li.className = "player-list-item";
      const nameSpan = document.createElement("span");
      nameSpan.className = "player-name";
      nameSpan.textContent = p.name || "Hero";
      li.appendChild(nameSpan);
      if (p.is_host) {
        const tag = document.createElement("span");
        tag.className = "player-tag";
        tag.textContent = "Host";
        li.appendChild(tag);
      }
      if (p.submitted) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-ready";
        tag.textContent = "Ready";
        li.appendChild(tag);
      }
      if (p.active === false) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-warn";
        tag.textContent = "Disconnected";
        li.appendChild(tag);
      }
      els.playersRoster.appendChild(li);
    });
  }

  function renderMoveForm(s) {
    const encounter = s.encounter || {};
    // renderBoard() re-invokes this on every ~1.5s poll while the form is
    // still showing, so only reset the fields the first time a given round's
    // form appears -- never while the player is mid-typing on that same
    // round (that would erase their draft on every poll), but always when
    // the round has actually moved on (otherwise the previous round's move
    // text/card selection silently carries over as a pre-filled, easy-to-
    // miss resubmission for the new round).
    const roundKey = (encounter.id || "") + ":" + (typeof s.round_index === "number" ? s.round_index : "");
    if (roundKey !== moveFormRoundKey) {
      moveFormRoundKey = roundKey;
      els.moveText.value = "";
      els.moveTextCount.textContent = "0";
      const checked = els.moveForm.querySelector('input[name="move-card"]:checked');
      if (checked) {
        checked.checked = false;
      }
    }
    els.moveSubmit.disabled = false;
    els.moveStatus.textContent = encounter.name ? "Trial: " + encounter.name + (encounter.flavor ? " — " + encounter.flavor : "") : "";
  }

  function renderReveal(roundRecord, you) {
    els.revealList.innerHTML = "";
    (roundRecord.choices || []).forEach(function (entry) {
      const li = document.createElement("li");
      li.className = "reveal-item";

      const head = document.createElement("div");
      head.className = "reveal-head";
      const nameSpan = document.createElement("span");
      nameSpan.className = "player-name";
      nameSpan.textContent = entry.name || entry.player_id || "Hero";
      head.appendChild(nameSpan);
      const approach = entry.approach || entry.card || "";
      const cardSpan = document.createElement("span");
      cardSpan.className = "reveal-card card-" + approach;
      cardSpan.textContent = CARD_LABELS[approach] || approach;
      head.appendChild(cardSpan);
      li.appendChild(head);

      if (entry.move_text) {
        const moveP = document.createElement("p");
        moveP.className = "reveal-move";
        moveP.textContent = entry.move_text;
        li.appendChild(moveP);
      }
      els.revealList.appendChild(li);
    });

    const successes = typeof roundRecord.successes === "number" ? roundRecord.successes : 0;
    const backfires = typeof roundRecord.backfires === "number" ? roundRecord.backfires : 0;
    const damage = typeof roundRecord.damage === "number" ? roundRecord.damage : 0;
    els.roundSummary.textContent =
      successes + " success(es), " + backfires + " backfire(s) → " +
      (damage > 0 ? damage + " heart" + (damage === 1 ? "" : "s") + " lost." : "no damage taken.");

    if (you.is_host) {
      els.advanceButton.hidden = false;
      els.advanceStatus.textContent = "";
    } else {
      els.advanceButton.hidden = true;
      els.advanceStatus.textContent = "Waiting for the host to continue…";
    }
  }

  // ---------------------------------------------------------------------
  // Canvas board art (decorative; all interactive state has a DOM equivalent)
  // ---------------------------------------------------------------------
  const SLOT_COLORS = { cleared: "#9fd8b0", current: "#ff6fae", unknown: "#b9b3d6" };

  function drawBoardCanvas(slots, currentIndex) {
    const w = els.canvas.width;
    const h = els.canvas.height;
    ctx.clearRect(0, 0, w, h);

    // The generated fantasy map is the CSS background; canvas remains a
    // transparent, accessible state overlay so the game still works if the
    // optional art pack is missing or slow to load.
    ctx.fillStyle = "rgba(255, 248, 240, 0.18)";
    ctx.fillRect(0, 0, w, h);

    const count = slots.length;
    const marginX = 60;
    const step = (w - marginX * 2) / Math.max(count - 1, 1);
    const y = h / 2 + 20;
    const points = [];
    for (let i = 0; i < count; i += 1) {
      points.push({ x: marginX + step * i, y: y - Math.sin(i * 1.1) * 40 });
    }

    ctx.strokeStyle = "#c9b8ff";
    ctx.lineWidth = 6;
    ctx.beginPath();
    points.forEach(function (p, i) {
      if (i === 0) {
        ctx.moveTo(p.x, p.y);
      } else {
        ctx.lineTo(p.x, p.y);
      }
    });
    ctx.stroke();

    points.forEach(function (p, i) {
      const slot = slots[i] || { status: "unknown" };
      const isCurrent = slot.status === "current";
      ctx.beginPath();
      ctx.arc(p.x, p.y, isCurrent ? 26 : 20, 0, Math.PI * 2);
      ctx.fillStyle = SLOT_COLORS[slot.status] || SLOT_COLORS.unknown;
      ctx.globalAlpha = slot.status === "cleared" ? 0.6 : 1;
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.lineWidth = isCurrent ? 4 : 2;
      ctx.strokeStyle = "#2a2540";
      ctx.stroke();

      ctx.fillStyle = "#2a2540";
      ctx.font = "bold 14px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(slot.status === "unknown" ? "?" : String(i + 1), p.x, p.y + 5);
    });

    if (!reduceMotion && animRoomIndex !== currentIndex) {
      animRoomIndex += animRoomIndex < currentIndex ? 1 : -1;
      vSetTimeout(function () { drawBoardCanvas(slots, currentIndex); }, 120);
    } else {
      animRoomIndex = currentIndex;
    }

    const tokenPoint = points[Math.max(0, Math.min(points.length - 1, animRoomIndex))];
    if (tokenPoint) {
      ctx.beginPath();
      ctx.arc(tokenPoint.x, tokenPoint.y - 34, 10, 0, Math.PI * 2);
      ctx.fillStyle = "#ffd23f";
      ctx.fill();
      ctx.strokeStyle = "#2a2540";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    const current = slots[currentIndex] || {};
    els.canvas.setAttribute(
      "aria-label",
      "Encounter " + (currentIndex + 1) + " of " + count + (current.name ? ": " + current.name : "")
    );
  }

  // ---------------------------------------------------------------------
  // Finale rendering
  // ---------------------------------------------------------------------
  function renderFinale(s) {
    const victory = s.finished_victory === true;
    els.finaleArt.src = victory ? "/art/victory.png" : "/art/defeat.png";
    els.finaleArt.alt = victory
      ? "The adventuring party celebrating amid defeated magical paperwork"
      : "The adventuring party buried beneath an avalanche of enchanted paperwork";
    els.finaleHeading.textContent = victory ? "The kingdom is saved!" : "The kingdom remains chaotic.";
    const rounds = (s.history || []).length + (s.last_round ? 1 : 0);
    els.finaleSummary.textContent = victory
      ? "Your party talked, schemed, and bonked its way through all 5 encounters with " + (s.hearts || 0) + " heart(s) to spare."
      : "The party's hearts ran out after " + rounds + " encounter(s). The kingdom's miscommunications win this round.";
  }

  // ---------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------
  async function startGame() {
    if (!roomId) {
      return;
    }
    els.lobbyStatus.textContent = "Starting…";
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(roomId) + "/start", { method: "POST" });
      if (resp.status === 403) {
        els.lobbyStatus.textContent = "Only the host can start the adventure.";
        return;
      }
      if (!resp.ok) {
        els.lobbyStatus.textContent = describeApiFailure(resp.status, "Couldn't start the adventure.");
        return;
      }
      const data = await resp.json();
      applyState(data);
    } catch (err) {
      els.lobbyStatus.textContent = "Couldn't reach the game server.";
    }
  }

  async function submitMove(event) {
    event.preventDefault();
    const persona = els.movePersona.value;
    const cardInput = els.moveForm.querySelector('input[name="move-card"]:checked');
    const card = cardInput ? cardInput.value : "";
    const moveText = els.moveText.value.trim();
    if (!persona || !card || !moveText) {
      els.moveStatus.textContent = "Choose a persona, a card, and write your move first.";
      return;
    }
    els.moveSubmit.disabled = true;
    els.moveStatus.textContent = "Submitting…";
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(roomId) + "/moves", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona: persona, approach: card, card: card, move_text: moveText }),
      });
      if (resp.status === 409) {
        els.moveStatus.textContent = "You've already submitted this round.";
        return;
      }
      if (resp.status === 422) {
        els.moveStatus.textContent = "That move wasn't accepted. Try shortening it.";
        els.moveSubmit.disabled = false;
        return;
      }
      if (!resp.ok) {
        els.moveStatus.textContent = describeApiFailure(resp.status, "Couldn't submit your move.");
        els.moveSubmit.disabled = false;
        return;
      }
      els.moveStatus.textContent = "";
      const data = await resp.json().catch(function () { return null; });
      if (data && data.state) {
        applyState(data.state);
      } else {
        // No inline state in the ack -- poll immediately rather than
        // waiting out the regular interval for the waiting view to show.
        stopPolling();
        pollTimerId = vSetTimeout(pollTick, 0);
      }
    } catch (err) {
      els.moveStatus.textContent = "Couldn't reach the game server.";
      els.moveSubmit.disabled = false;
    }
  }

  async function advanceRound() {
    if (!roomId) {
      return;
    }
    els.advanceStatus.textContent = "";
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(roomId) + "/advance", { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        applyState(data);
      }
      /* 404/other failures: rely on the next poll to reflect server-driven advance */
    } catch (err) {
      /* best-effort; polling will recover */
    }
  }

  async function replayGame() {
    if (!roomId) {
      return;
    }
    try {
      const resp = await apiFetch("/api/game/rooms/" + encodeURIComponent(roomId) + "/replay", { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        applyState(data);
      }
    } catch (err) {
      showError("Couldn't reach the game server to start a replay.");
    }
  }

  function copyText(text, statusEl) {
    if (!text) {
      return;
    }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { if (statusEl) { statusEl.textContent = "Copied."; } },
        function () { if (statusEl) { statusEl.textContent = "Couldn't copy — select and copy manually."; } }
      );
    }
  }

  // ---------------------------------------------------------------------
  // Fullscreen
  // ---------------------------------------------------------------------
  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      const req = document.documentElement.requestFullscreen;
      if (req) {
        req.call(document.documentElement).catch(function () { /* ignore */ });
      }
    } else if (document.exitFullscreen) {
      document.exitFullscreen().catch(function () { /* ignore */ });
    }
  }

  document.addEventListener("fullscreenchange", function () {
    els.fullscreenToggle.setAttribute("aria-pressed", document.fullscreenElement ? "true" : "false");
  });

  document.addEventListener("keydown", function (event) {
    const tag = (event.target && event.target.tagName) || "";
    const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
    if (event.key === "f" && !typing && !event.metaKey && !event.ctrlKey && !event.altKey) {
      event.preventDefault();
      toggleFullscreen();
    } else if (event.key === "Escape" && document.fullscreenElement) {
      document.exitFullscreen().catch(function () { /* ignore */ });
    }
  });

  // ---------------------------------------------------------------------
  // Wiring
  // ---------------------------------------------------------------------
  els.gateSubmit.addEventListener("click", function () {
    const code = els.gateInput.value.trim();
    if (!code) {
      els.gateStatus.textContent = "Enter the access code first.";
      return;
    }
    unlock(code);
  });
  els.gateInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      event.preventDefault();
      els.gateSubmit.click();
    }
  });

  els.createForm.addEventListener("submit", createRoom);
  els.joinForm.addEventListener("submit", joinRoom);
  els.copyCodeButton.addEventListener("click", function () { copyText(joinCode, els.lobbyStatus); });
  els.copyLinkButton.addEventListener("click", function () { copyText(joinUrl, els.lobbyStatus); });
  els.startButton.addEventListener("click", startGame);

  els.moveText.addEventListener("input", function () {
    els.moveTextCount.textContent = String(els.moveText.value.length);
  });
  els.moveForm.addEventListener("submit", submitMove);

  els.advanceButton.addEventListener("click", advanceRound);
  els.replayButton.addEventListener("click", replayGame);
  els.fullscreenToggle.addEventListener("click", toggleFullscreen);

  // ---------------------------------------------------------------------
  // Required test hooks
  // ---------------------------------------------------------------------
  function render_game_to_text() {
    const lines = [];
    lines.push("screen: " + screen);
    if (!els.errorBanner.hidden) {
      lines.push("error: " + els.errorBanner.textContent);
    }
    if (screen === "gate") {
      lines.push("gate-status: " + els.gateStatus.textContent);
    } else if (screen === "home") {
      lines.push("home-status: " + els.homeStatus.textContent);
    } else if (screen === "lobby" && state) {
      const players = state.players || [];
      lines.push("room-code: " + joinCode);
      lines.push("players: " + players.length + "/4");
      players.forEach(function (p) {
        lines.push("  - " + (p.name || "hero") + (p.is_host ? " (host)" : "") + (p.active === false ? " [disconnected]" : ""));
      });
      lines.push("solo: " + (players.length <= 1));
      lines.push("start-visible: " + !els.startButton.hidden);
    } else if (screen === "board" && state) {
      const total = typeof state.total_rounds === "number" ? state.total_rounds : 5;
      lines.push("encounter: " + ((state.round_index || 0) + 1) + "/" + total + (state.encounter ? " (" + state.encounter.name + ")" : ""));
      lines.push("hearts: " + (typeof state.hearts === "number" ? state.hearts : "?") + "/" + (typeof state.max_hearts === "number" ? state.max_hearts : "?"));
      if (!els.moveForm.hidden) {
        lines.push("sub-view: choosing-move");
        lines.push("move-text-length: " + els.moveText.value.length + "/140");
      } else if (!els.waitingPanel.hidden) {
        lines.push("sub-view: waiting");
        lines.push("waiting: " + els.waitingCount.textContent);
      } else if (!els.revealPanel.hidden) {
        lines.push("sub-view: reveal");
        const lastRound = state.last_round || {};
        (lastRound.choices || []).forEach(function (entry) {
          lines.push("  - " + (entry.name || entry.player_id) + ": " + (entry.approach || entry.card));
        });
        lines.push("round-summary: " + els.roundSummary.textContent);
        lines.push("advance-visible: " + !els.advanceButton.hidden);
      }
      (state.players || []).forEach(function (p) {
        lines.push("player: " + (p.name || "hero") + (p.submitted ? " submitted" : ""));
      });
    } else if (screen === "finale" && state) {
      lines.push("finale-heading: " + els.finaleHeading.textContent);
      lines.push("finale-summary: " + els.finaleSummary.textContent);
    }
    return lines.join("\n");
  }

  window.render_game_to_text = render_game_to_text;
  window.advanceTime = advanceTime;

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  const urlParams = readParamsFromUrl();
  if (urlParams.code) {
    unlock(urlParams.code);
    if (urlParams.room) {
      els.joinCodeInput.value = urlParams.room.toUpperCase();
    }
  }
})();
