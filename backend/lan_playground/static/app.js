"use strict";
/*
 * The Lost Meaning -- LAN party game client (board #41, redesign task #3).
 *
 * No microphone/audio/TTS APIs are used here (text-only, DOM game). The
 * site access code and any room/player tokens live only in module-scope
 * variables for this page load -- never persisted by the browser in any
 * way -- and any `?code=`/`?room=` query params are read once, then
 * stripped from the visible URL immediately. All player-supplied strings
 * (names, move text, clues) are rendered with textContent only, never
 * raw-HTML insertion.
 *
 * CONTRACT (per the final engine/server handoff, 2026-07-19): a fixed 4-hero roster
 * (HERO_ROSTER) is auto-bound to players in join order -- there is no
 * character-builder step. Phases: lobby -> spotlight_action -> ally_support
 * -> spotlight_draft -> ally_reaction -> reveal -> finished (+ replay ->
 * lobby). Everything the server sends is funneled through
 * normalizeState(raw) below into one canonical view-model shape (`vm`).
 * Every render function reads only from `vm`, never from the raw payload,
 * so future field-name corrections only touch normalizeState()/the action
 * functions, never layout. Route paths and pending-step names below match
 * the final FastAPI and engine contracts and are covered by static tests.
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

  let state = null; // last raw state document from the server
  let vm = null; // normalizeState(state) -- everything below renders from this
  let screen = "gate"; // gate | home | lobby | round | finale
  let roundStageKey = null; // tracks phase+round+spotlight so forms only reset on real transitions

  let pollTimerId = null;
  let pollFailures = 0;
  let pollInFlight = false;
  const POLL_INTERVAL_MS = 1500;
  const POLL_MAX_INTERVAL_MS = 8000;

  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  const VARIANT_SLOT_COUNT = 3;
  const SCHOOL_ICONS = { charm: "❤", scheme: "⚙", bonk: "✳" };
  const ENCOUNTER_ART = {
    passive_aggressive_troll: "/art/encounter-troll.png",
    goblin_hr_department: "/art/encounter-goblins.png",
    suggestion_box_mimic: "/art/encounter-mimic.png",
    needlessly_complicated_riddle_bridge: "/art/encounter-bridge.png",
    red_tape_dragon: "/art/encounter-dragon.png",
  };

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
    yourHeroPanel: document.getElementById("your-hero-panel"),
    yourHeroName: document.getElementById("your-hero-name"),
    yourHeroPersona: document.getElementById("your-hero-persona"),
    yourHeroAbility: document.getElementById("your-hero-ability"),
    yourHeroCards: document.getElementById("your-hero-cards"),
    startButton: document.getElementById("start-button"),
    lobbyStatus: document.getElementById("lobby-status"),

    round: document.getElementById("round-screen"),
    spotlightBanner: document.getElementById("spotlight-banner"),
    spotlightRound: document.getElementById("spotlight-round"),
    spotlightName: document.getElementById("spotlight-name"),
    objectiveArt: document.getElementById("objective-art"),
    objectiveName: document.getElementById("objective-name"),
    objectiveDescription: document.getElementById("objective-description"),
    heartsDisplay: document.getElementById("hearts-display"),
    playersRoster: document.getElementById("players-roster"),

    privateClue: document.getElementById("private-clue"),
    yourHeroHandPanel: document.getElementById("your-hero-hand-panel"),
    yourHeroHandCards: document.getElementById("your-hero-hand-cards"),

    declaredActionPanel: document.getElementById("declared-action-panel"),
    declaredActionSummary: document.getElementById("declared-action-summary"),
    declaredActionApproved: document.getElementById("declared-action-approved"),
    declaredActionApprovedText: document.getElementById("declared-action-approved-text"),
    declaredActionApprovedIntent: document.getElementById("declared-action-approved-intent"),

    actionBuilderPanel: document.getElementById("action-builder-panel"),
    actionCardChoices: document.getElementById("action-card-choices"),
    actionTargetSelect: document.getElementById("action-target-select"),
    actionOutcomeInput: document.getElementById("action-outcome-input"),
    actionOutcomeCount: document.getElementById("action-outcome-count"),
    actionSubmit: document.getElementById("action-submit"),
    actionStatus: document.getElementById("action-status"),

    supportPanel: document.getElementById("support-panel"),
    supportItemsHint: document.getElementById("support-items-hint"),
    supportDetail: document.getElementById("support-detail"),
    supportDetailCount: document.getElementById("support-detail-count"),
    supportSubmit: document.getElementById("support-submit"),
    supportStatus: document.getElementById("support-status"),

    draftPanel: document.getElementById("draft-panel"),
    draftRoughText: document.getElementById("draft-rough-text"),
    draftRoughCount: document.getElementById("draft-rough-count"),
    draftVoiceButton: document.getElementById("draft-voice-button"),
    draftVoiceStatus: document.getElementById("draft-voice-status"),
    draftGenerateButton: document.getElementById("draft-generate-button"),
    draftLoading: document.getElementById("draft-loading"),
    draftError: document.getElementById("draft-error"),
    variantList: document.getElementById("variant-list"),
    draftApproval: document.getElementById("draft-approval"),
    draftEditText: document.getElementById("draft-edit-text"),
    draftIntentText: document.getElementById("draft-intent-text"),
    draftApproveButton: document.getElementById("draft-approve-button"),
    draftStatus: document.getElementById("draft-status"),

    reactionPanel: document.getElementById("reaction-panel"),
    reactionMessage: document.getElementById("reaction-message"),
    reactionIntent: document.getElementById("reaction-intent"),
    reactionMoveSelect: document.getElementById("reaction-move-select"),
    reactionDetail: document.getElementById("reaction-detail"),
    reactionDetailCount: document.getElementById("reaction-detail-count"),
    reactionSubmit: document.getElementById("reaction-submit"),
    reactionStatus: document.getElementById("reaction-status"),

    revealPanel: document.getElementById("reveal-panel"),
    dieRollDisplay: document.getElementById("die-roll-display"),
    modifierBreakdown: document.getElementById("modifier-breakdown"),
    revealOutcome: document.getElementById("reveal-outcome"),
    revealedCluesWrap: document.getElementById("revealed-clues-wrap"),
    revealedCluesList: document.getElementById("revealed-clues-list"),
    roundLogWrap: document.getElementById("round-log-wrap"),
    roundLogList: document.getElementById("round-log-list"),
    revealNarration: document.getElementById("reveal-narration"),
    revealContinueButton: document.getElementById("reveal-continue-button"),
    revealStatus: document.getElementById("reveal-status"),

    roundWaitingPanel: document.getElementById("round-waiting-panel"),
    roundWaitingText: document.getElementById("round-waiting-text"),
    hostOpenDraftButton: document.getElementById("host-opendraft-button"),
    hostResolveButton: document.getElementById("host-resolve-button"),

    finale: document.getElementById("finale-screen"),
    finaleArt: document.getElementById("finale-art"),
    finaleHeading: document.getElementById("finale-heading"),
    finaleSummary: document.getElementById("finale-summary"),
    finaleRecap: document.getElementById("finale-recap"),
    replayButton: document.getElementById("replay-button"),
  };

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

  function describeApiFailure(status, fallback) {
    if (status === 404) {
      return "The game backend isn't available yet on this server.";
    }
    if (status === 429) {
      return "The server is busy right now. Try again shortly.";
    }
    return fallback + " (status " + status + ")";
  }

  function currentCheckedValue(container) {
    const checked = container.querySelector("input:checked");
    return checked ? checked.value : null;
  }

  function roomPath(suffix) {
    return "/api/game/rooms/" + encodeURIComponent(roomId) + suffix;
  }

  // ---------------------------------------------------------------------
  // Screen management
  // ---------------------------------------------------------------------
  function setScreen(next) {
    if (screen === "round" && next !== "round") {
      roundStageKey = null;
    }
    screen = next;
    els.gate.hidden = next !== "gate";
    els.home.hidden = next !== "home";
    els.lobby.hidden = next !== "lobby";
    els.round.hidden = next !== "round";
    els.finale.hidden = next !== "finale";
  }

  function lockOut(message) {
    accessCode = "";
    hostToken = null;
    playerToken = null;
    roomId = null;
    playerId = null;
    state = null;
    vm = null;
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
    vm = null;
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
  }

  // ---------------------------------------------------------------------
  // Home: create / join
  // ---------------------------------------------------------------------
  async function createRoom(event) {
    event.preventDefault();
    const name = els.createName.value.trim();
    if (!name) {
      els.homeStatus.textContent = "Enter your name first.";
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
      els.homeStatus.textContent = "Enter a room code and your name first.";
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
      const resp = await apiFetch(roomPath("/state"));
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
  // normalizeState -- the one place the real server contract plugs in
  // ---------------------------------------------------------------------
  function normalizeCard(raw) {
    if (raw == null) {
      return null;
    }
    if (typeof raw === "string") {
      return { id: raw, name: raw, school: "bonk", description: "" };
    }
    return {
      id: raw.id || raw.name,
      name: raw.name || raw.id || "Move",
      school: raw.school || "bonk",
      description: raw.description || "",
    };
  }

  function normalizeHero(raw) {
    return {
      hero_id: raw.hero_id,
      name: raw.name || raw.hero_id,
      persona: raw.persona || "",
      ability_name: raw.ability_name || "",
      ability_description: raw.ability_description || "",
      deck: (raw.deck || []).map(normalizeCard).filter(Boolean),
      signature_move: raw.signature_move ? normalizeCard(raw.signature_move) : null,
      player_id: raw.player_id || null,
      is_companion: !!raw.is_companion,
      active: raw.active !== false,
      items_remaining: typeof raw.items_remaining === "number" ? raw.items_remaining : 0,
      voice_calibrated: !!raw.voice_calibrated,
      submitted_current_step: !!raw.submitted_current_step,
    };
  }

  function heroHand(hero) {
    if (!hero) {
      return [];
    }
    return hero.signature_move ? hero.deck.concat([hero.signature_move]) : hero.deck.slice();
  }

  function heroById(viewModel, heroId) {
    if (!heroId) {
      return null;
    }
    return viewModel.heroes.find(function (h) { return h.hero_id === heroId; }) || null;
  }

  function resolveMoveRef(hero, moveRef) {
    if (moveRef == null) {
      return null;
    }
    if (typeof moveRef === "object") {
      return normalizeCard(moveRef);
    }
    const hand = heroHand(hero);
    const found = hand.find(function (c) { return c.id === moveRef; });
    return found || { id: moveRef, name: String(moveRef), school: "bonk", description: "" };
  }

  function normalizeState(raw) {
    if (!raw || typeof raw !== "object") {
      return null;
    }
    const heroes = (raw.heroes || []).map(normalizeHero);
    const heroMap = {};
    heroes.forEach(function (h) { heroMap[h.hero_id] = h; });

    const players = (raw.players || []).map(function (p) {
      return {
        player_id: p.player_id,
        name: p.name || "Hero",
        is_host: !!p.is_host,
        active: p.active !== false,
        hero_id: p.hero_id || null,
        hero: p.hero_id ? heroMap[p.hero_id] || null : null,
      };
    });

    const encounterRaw = raw.encounter || {};
    const targets = (encounterRaw.targets || []).map(function (t, i) {
      if (typeof t === "string") {
        return { id: t, name: t };
      }
      return { id: t.id || t.name || String(i), name: t.name || t.id || String(i) };
    });

    const currentActionRaw = raw.current_action || null;
    const currentAction = currentActionRaw ? {
      hero_id: currentActionRaw.hero_id || raw.spotlight_hero_id || null,
      move: resolveMoveRef(heroMap[currentActionRaw.hero_id || raw.spotlight_hero_id], currentActionRaw.move),
      target_id: currentActionRaw.target_id || null,
      desired_outcome: currentActionRaw.desired_outcome || "",
      approved_text: currentActionRaw.approved_text || null,
      intent: currentActionRaw.intent || null,
    } : null;

    const you = raw.you || {};
    const draftRaw = you.draft || {};
    const voiceRaw = you.voice_profile || {};

    return {
      room_id: raw.room_id || null,
      phase: raw.phase || "lobby",
      hearts: typeof raw.hearts === "number" ? raw.hearts : null,
      max_hearts: typeof raw.max_hearts === "number" ? raw.max_hearts : null,
      host_id: raw.host_id || null,
      spotlight_hero_id: raw.spotlight_hero_id || null,
      players: players,
      heroes: heroes,
      round_index: typeof raw.round_index === "number" ? raw.round_index : 0,
      total_rounds: typeof raw.total_rounds === "number" ? raw.total_rounds : 5,
      encounter: { id: encounterRaw.id || null, name: encounterRaw.name || "", flavor: encounterRaw.flavor || "", targets: targets },
      current_action: currentAction,
      last_round: raw.last_round || null,
      history: raw.history || [],
      finished_victory: typeof raw.finished_victory === "boolean" ? raw.finished_victory : null,
      join_code: raw.join_code || null,
      join_url: raw.join_url || null,
      join_qr_data_url: raw.join_qr_data_url || null,
      join_qr_svg: raw.join_qr_svg || null,
      you: {
        player_id: you.player_id || playerId,
        is_host: !!you.is_host,
        active: you.active !== false,
        hero_id: you.hero_id || null,
        hero: you.hero_id ? heroMap[you.hero_id] || null : null,
        private_clue: you.private_clue || "",
        draft: {
          rough_text: draftRaw.rough_text || "",
          variants: (draftRaw.variants || []).slice(0, VARIANT_SLOT_COUNT).map(function (v, i) {
            if (typeof v === "string") {
              return { id: String(i), text: v, provenance: "" };
            }
            return { id: v.id || String(i), text: v.text || "", provenance: v.provenance || "" };
          }),
          approved_text: draftRaw.approved_text || null,
          intent: draftRaw.intent || null,
        },
        voice_profile: {
          utterance_count: typeof voiceRaw.utterance_count === "number" ? voiceRaw.utterance_count : 0,
          confidence: typeof voiceRaw.confidence === "number" ? voiceRaw.confidence : 0,
          calibrated: !!voiceRaw.calibrated,
        },
        items_remaining: typeof you.items_remaining === "number" ? you.items_remaining : null,
        pending_step: you.pending_step || null,
      },
    };
  }

  function applyState(raw) {
    if (!raw || typeof raw !== "object") {
      return;
    }
    state = raw;
    vm = normalizeState(raw);
    if (!vm) {
      return;
    }
    if (vm.you.player_id) {
      playerId = vm.you.player_id;
    }
    if (vm.join_code) {
      joinCode = vm.join_code;
    }
    if (vm.join_url) {
      joinUrl = vm.join_url;
    }

    if (vm.phase === "finished") {
      setScreen("finale");
      renderFinale(vm);
      announce("The adventure has ended.");
      return;
    }
    if (vm.phase === "lobby") {
      setScreen("lobby");
      renderLobby(vm);
      announce("In the lobby with " + vm.players.length + " hero(es).");
      return;
    }
    setScreen("round");
    renderRound(vm);
  }

  // ---------------------------------------------------------------------
  // Shared card rendering helpers
  // ---------------------------------------------------------------------
  function renderCardChoices(container, cards, radioName, checkedId) {
    container.innerHTML = "";
    cards.forEach(function (card) {
      const label = document.createElement("label");
      label.className = "card-choice";
      label.dataset.card = card.school || "bonk";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = radioName;
      input.value = card.id;
      input.required = true;
      if (card.id === checkedId) {
        input.checked = true;
      }
      label.appendChild(input);
      const face = document.createElement("span");
      face.className = "card-face";
      const icon = document.createElement("span");
      icon.className = "card-icon";
      icon.setAttribute("aria-hidden", "true");
      icon.textContent = SCHOOL_ICONS[card.school] || "✳";
      face.appendChild(icon);
      const name = document.createElement("span");
      name.className = "card-name";
      name.textContent = card.name;
      face.appendChild(name);
      label.appendChild(face);
      container.appendChild(label);
    });
  }

  function renderCardListReadOnly(container, cards, signatureId) {
    container.innerHTML = "";
    cards.forEach(function (card) {
      const li = document.createElement("li");
      li.className = "move-card school-" + (card.school || "bonk") + (card.id === signatureId ? " is-signature" : "");
      const name = document.createElement("span");
      name.className = "move-card-name";
      name.textContent = card.name + (card.id === signatureId ? " (signature)" : "");
      li.appendChild(name);
      const school = document.createElement("span");
      school.className = "move-card-school";
      school.textContent = card.school || "";
      li.appendChild(school);
      if (card.description) {
        const desc = document.createElement("p");
        desc.className = "move-card-description";
        desc.textContent = card.description;
        li.appendChild(desc);
      }
      container.appendChild(li);
    });
  }

  // ---------------------------------------------------------------------
  // Lobby rendering
  // ---------------------------------------------------------------------
  function renderYourHeroPanel(viewModel) {
    const hero = viewModel.you.hero;
    if (!hero) {
      els.yourHeroPanel.hidden = true;
      return;
    }
    els.yourHeroPanel.hidden = false;
    els.yourHeroName.textContent = hero.name;
    els.yourHeroPersona.textContent = hero.persona ? "Persona: " + hero.persona : "";
    els.yourHeroAbility.textContent = hero.ability_name
      ? hero.ability_name + (hero.ability_description ? " — " + hero.ability_description : "")
      : "";
    renderCardListReadOnly(els.yourHeroCards, heroHand(hero), hero.signature_move && hero.signature_move.id);
  }

  function renderLobby(viewModel) {
    els.lobbyCode.textContent = joinCode || "–";
    els.lobbyLink.textContent = joinUrl || "";
    if (joinUrl && /^https?:\/\//i.test(joinUrl)) {
      els.lobbyLink.setAttribute("data-href", joinUrl);
    }

    renderQr(viewModel);

    els.lobbyPlayers.innerHTML = "";
    viewModel.players.forEach(function (p) {
      const li = document.createElement("li");
      li.className = "player-list-item";
      const nameSpan = document.createElement("span");
      nameSpan.className = "player-name";
      nameSpan.textContent = p.name + (p.hero ? " as " + p.hero.name : "");
      li.appendChild(nameSpan);
      if (p.is_host) {
        const tag = document.createElement("span");
        tag.className = "player-tag";
        tag.textContent = "Host";
        li.appendChild(tag);
      }
      if (!p.active) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-warn";
        tag.textContent = "Disconnected";
        li.appendChild(tag);
      }
      els.lobbyPlayers.appendChild(li);
    });

    renderYourHeroPanel(viewModel);

    els.lobbySoloHint.hidden = viewModel.players.length > 1;
    if (viewModel.you.is_host) {
      els.startButton.hidden = false;
      els.startButton.textContent = viewModel.players.length > 1 ? "Start the adventure" : "Start solo adventure";
      els.lobbyStatus.textContent = "";
    } else {
      els.startButton.hidden = true;
      els.lobbyStatus.textContent = "Waiting for the host to begin…";
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

  function renderQr(viewModel) {
    els.lobbyQr.innerHTML = "";
    const dataUrl = viewModel.join_qr_data_url;
    const svgText = viewModel.join_qr_svg;
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
  // Round rendering: shared context (banner/objective/private/log)
  // ---------------------------------------------------------------------
  function spotlightName(viewModel) {
    const hero = heroById(viewModel, viewModel.spotlight_hero_id);
    return hero ? hero.name : "the Spotlight";
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

  function renderRoster(viewModel) {
    els.playersRoster.innerHTML = "";
    viewModel.players.forEach(function (p) {
      const li = document.createElement("li");
      li.className = "player-list-item";
      const nameSpan = document.createElement("span");
      nameSpan.className = "player-name";
      nameSpan.textContent = p.name + (p.hero ? " as " + p.hero.name : "");
      li.appendChild(nameSpan);
      if (p.hero_id === viewModel.spotlight_hero_id) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-spotlight";
        tag.textContent = "Spotlight";
        li.appendChild(tag);
      }
      if (p.is_host) {
        const tag = document.createElement("span");
        tag.className = "player-tag";
        tag.textContent = "Host";
        li.appendChild(tag);
      }
      if (p.hero && p.hero.submitted_current_step) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-ready";
        tag.textContent = "Ready";
        li.appendChild(tag);
      }
      if (!p.active) {
        const tag = document.createElement("span");
        tag.className = "player-tag player-tag-warn";
        tag.textContent = "Disconnected";
        li.appendChild(tag);
      }
      els.playersRoster.appendChild(li);
    });
  }

  function renderObjectiveArt(encounter) {
    const name = encounter.name || "Mysterious administrative obstacle";
    els.objectiveArt.src = ENCOUNTER_ART[encounter.id] || "/art/encounter-troll.png";
    els.objectiveArt.alt = name + " encounter illustration";
    els.objectiveName.textContent = name;
    els.objectiveDescription.textContent = encounter.flavor || "";
  }

  function renderPrivatePanel(viewModel) {
    els.privateClue.textContent = viewModel.you.private_clue || "No clue revealed yet.";
  }

  function renderYourHeroHand(viewModel) {
    const hero = viewModel.you.hero;
    if (!hero) {
      els.yourHeroHandPanel.hidden = true;
      return;
    }
    els.yourHeroHandPanel.hidden = false;
    renderCardListReadOnly(els.yourHeroHandCards, heroHand(hero), hero.signature_move && hero.signature_move.id);
  }

  function renderDeclaredAction(viewModel) {
    const action = viewModel.current_action;
    if (!action) {
      els.declaredActionPanel.hidden = true;
      return;
    }
    els.declaredActionPanel.hidden = false;
    const spotlightHero = heroById(viewModel, action.hero_id) || heroById(viewModel, viewModel.spotlight_hero_id);
    const target = viewModel.encounter.targets.find(function (t) { return t.id === action.target_id; });
    const parts = [];
    parts.push((spotlightHero ? spotlightHero.name : "The Spotlight") + " uses " + (action.move ? action.move.name : "a move"));
    if (target) {
      parts.push("on " + target.name);
    }
    if (action.desired_outcome) {
      parts.push("— hoping to: " + action.desired_outcome);
    }
    els.declaredActionSummary.textContent = parts.join(" ");

    if (action.approved_text) {
      els.declaredActionApproved.hidden = false;
      els.declaredActionApprovedText.textContent = "“" + action.approved_text + "”";
      els.declaredActionApprovedIntent.textContent = action.intent ? "Intent: " + action.intent : "";
    } else {
      els.declaredActionApproved.hidden = true;
    }
  }

  // ---------------------------------------------------------------------
  // Round rendering: per-phase sub-panels
  // ---------------------------------------------------------------------
  function panelForPhase(viewModel) {
    const step = viewModel.you.pending_step;
    if (step === "declare_action" || step === "spotlight_action") {
      return "action-builder";
    }
    if (step === "submit_support" || step === "ally_support") {
      return "support";
    }
    if (["submit_rough_text", "awaiting_variants", "approve_message", "spotlight_draft"].includes(step)) {
      return "draft";
    }
    if (step === "submit_reaction" || step === "ally_reaction") {
      return "reaction";
    }
    if (viewModel.phase === "reveal") {
      return "reveal";
    }
    return "waiting";
  }

  function alliesReady(viewModel) {
    const allies = viewModel.heroes.filter(function (h) {
      return h.active && h.hero_id !== viewModel.spotlight_hero_id;
    });
    if (!allies.length) {
      return true;
    }
    return allies.every(function (h) { return h.submitted_current_step; });
  }

  function renderActionBuilder(viewModel, isNewStage) {
    const hand = heroHand(viewModel.you.hero);
    const checked = isNewStage ? null : currentCheckedValue(els.actionCardChoices);
    renderCardChoices(els.actionCardChoices, hand, "action-card", checked);

    const previousTarget = els.actionTargetSelect.value;
    els.actionTargetSelect.innerHTML = "";
    viewModel.encounter.targets.forEach(function (t) {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name;
      els.actionTargetSelect.appendChild(opt);
    });
    if (!isNewStage && previousTarget && Array.from(els.actionTargetSelect.options).some(function (o) { return o.value === previousTarget; })) {
      els.actionTargetSelect.value = previousTarget;
    }

    if (isNewStage) {
      els.actionOutcomeInput.value = "";
      els.actionOutcomeCount.textContent = "0";
    }
    els.actionSubmit.disabled = false;
    els.actionStatus.textContent = viewModel.encounter.name ? "Facing: " + viewModel.encounter.name : "";
  }

  function renderSupportForm(viewModel, isNewStage) {
    const items = viewModel.you.items_remaining;
    els.supportItemsHint.textContent = typeof items === "number" ? "Items remaining: " + items : "";
    const itemInput = els.supportPanel.querySelector('input[name="support-kind"][value="item"]');
    if (itemInput) {
      const disabled = typeof items === "number" && items <= 0;
      itemInput.disabled = disabled;
      itemInput.closest(".card-choice").classList.toggle("is-disabled", disabled);
    }
    if (isNewStage) {
      const checked = els.supportPanel.querySelector('input[name="support-kind"]:checked');
      if (checked) {
        checked.checked = false;
      }
      els.supportDetail.value = "";
      els.supportDetailCount.textContent = "0";
    }
    els.supportSubmit.disabled = false;
    els.supportStatus.textContent = "";
  }

  function renderVariantList(viewModel) {
    const variants = viewModel.you.draft.variants;
    els.variantList.innerHTML = "";
    if (!variants.length) {
      els.variantList.hidden = true;
      return;
    }
    els.variantList.hidden = false;
    variants.forEach(function (variant) {
      const label = document.createElement("label");
      label.className = "variant-choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "draft-variant";
      input.value = variant.id;
      label.appendChild(input);
      const card = document.createElement("span");
      card.className = "variant-card";
      const badge = document.createElement("span");
      const provenance = variant.provenance || "";
      badge.className = "variant-provenance" + (/fallback|offline/i.test(provenance) ? " provenance-fallback" : "");
      badge.textContent = provenance ? provenance.charAt(0).toUpperCase() + provenance.slice(1) : "Rewrite";
      card.appendChild(badge);
      const text = document.createElement("p");
      text.className = "variant-text";
      text.textContent = variant.text;
      card.appendChild(text);
      label.appendChild(card);
      els.variantList.appendChild(label);
    });
  }

  els.variantList.addEventListener("change", function (event) {
    if (!event.target || event.target.name !== "draft-variant" || !vm) {
      return;
    }
    const variant = vm.you.draft.variants.find(function (v) { return v.id === event.target.value; });
    if (!variant) {
      return;
    }
    els.draftEditText.value = variant.text;
    if (!els.draftIntentText.value) {
      els.draftIntentText.value = (vm.current_action && vm.current_action.desired_outcome) || "";
    }
    els.draftApproval.hidden = false;
  });

  function renderDraftPanel(viewModel, isNewStage) {
    if (isNewStage) {
      els.draftRoughText.value = viewModel.you.draft.rough_text || "";
      els.draftRoughCount.textContent = String(els.draftRoughText.value.length);
      els.draftError.hidden = true;
      els.draftError.textContent = "";
      els.draftLoading.hidden = true;
    }
    const voice = viewModel.you.voice_profile;
    els.draftVoiceStatus.textContent = "Practiced " + voice.utterance_count + " time(s)"
      + (voice.calibrated ? " — voice calibrated." : ".");
    renderVariantList(viewModel);
    if (viewModel.you.draft.variants.length) {
      els.draftApproval.hidden = false;
      if (isNewStage || !els.draftEditText.value) {
        els.draftEditText.value = viewModel.you.draft.approved_text || viewModel.you.draft.variants[0].text || "";
      }
      if (isNewStage || !els.draftIntentText.value) {
        els.draftIntentText.value = viewModel.you.draft.intent || (viewModel.current_action && viewModel.current_action.desired_outcome) || "";
      }
    } else {
      els.draftApproval.hidden = true;
    }
    els.draftStatus.textContent = "";
  }

  function renderReactionForm(viewModel, isNewStage) {
    const action = viewModel.current_action || {};
    els.reactionMessage.textContent = action.approved_text || "";
    els.reactionIntent.textContent = action.intent ? "Intent: " + action.intent : "";
    if (isNewStage) {
      const hand = heroHand(viewModel.you.hero);
      const previous = els.reactionMoveSelect.value;
      els.reactionMoveSelect.innerHTML = "";
      const noneOpt = document.createElement("option");
      noneOpt.value = "";
      noneOpt.textContent = "No move";
      els.reactionMoveSelect.appendChild(noneOpt);
      hand.forEach(function (card) {
        const opt = document.createElement("option");
        opt.value = card.id;
        opt.textContent = card.name;
        els.reactionMoveSelect.appendChild(opt);
      });
      els.reactionMoveSelect.value = previous && Array.from(els.reactionMoveSelect.options).some(function (o) { return o.value === previous; }) ? previous : "";

      const checked = els.reactionPanel.querySelector('input[name="reaction-verb"]:checked');
      if (checked) {
        checked.checked = false;
      }
      els.reactionDetail.value = "";
      els.reactionDetailCount.textContent = "0";
    }
    els.reactionSubmit.disabled = false;
    els.reactionStatus.textContent = "";
  }

  function describeClue(entry) {
    if (typeof entry === "string") {
      return entry;
    }
    if (entry && typeof entry === "object") {
      return (entry.name ? entry.name + ": " : "") + (entry.clue || entry.text || entry.detail || "revealed a clue");
    }
    return "revealed a clue";
  }

  function renderRoundLogEntry(container, item, className) {
    const li = document.createElement("li");
    li.className = "contribution-item";
    const tag = document.createElement("span");
    tag.className = "stance-tag stance-" + (item[className] || "assist");
    tag.textContent = item[className] || "";
    li.appendChild(tag);
    const name = document.createElement("strong");
    name.textContent = (item.name || "Someone") + ": ";
    li.appendChild(name);
    li.appendChild(document.createTextNode(item.detail || ""));
    container.appendChild(li);
  }

  function renderRevealPanel(viewModel) {
    const round = viewModel.last_round;
    els.dieRollDisplay.innerHTML = "";
    els.modifierBreakdown.innerHTML = "";
    els.revealedCluesList.innerHTML = "";
    els.roundLogList.innerHTML = "";

    if (!round) {
      els.revealOutcome.textContent = "Waiting for the roll…";
      els.revealNarration.textContent = "";
      els.revealedCluesWrap.hidden = true;
      els.roundLogWrap.hidden = true;
    } else {
      if (typeof round.die_roll !== "undefined") {
        const li = document.createElement("li");
        li.textContent = "Die roll: " + round.die_roll;
        els.dieRollDisplay.appendChild(li);
      }
      (round.modifiers || []).forEach(function (m) {
        const li = document.createElement("li");
        const value = typeof m.value === "number" ? m.value : 0;
        li.textContent = (m.label || m.source || "modifier") + " (" + (m.affects || "score") + "): ";
        const span = document.createElement("span");
        span.className = value > 0 ? "value-positive" : (value < 0 ? "value-negative" : "");
        span.textContent = (value > 0 ? "+" : "") + value;
        li.appendChild(span);
        els.modifierBreakdown.appendChild(li);
      });

      const target = viewModel.encounter.targets.find(function (t) { return t.id === round.true_target_id; });
      const parts = [];
      if (typeof round.score === "number") {
        parts.push("Score " + round.score);
      }
      if (typeof round.damage === "number") {
        parts.push(round.damage > 0 ? round.damage + " heart(s) lost" : "no damage taken");
      }
      if (typeof round.hearts_before === "number" && typeof round.hearts_after === "number") {
        parts.push(round.hearts_before + " → " + round.hearts_after + " hearts");
      }
      if (target) {
        parts.push("true target: " + target.name);
      }
      els.revealOutcome.textContent = parts.join(" — ");
      els.revealNarration.textContent = round.narration || "";

      const clues = round.revealed_clues || [];
      els.revealedCluesWrap.hidden = clues.length === 0;
      clues.forEach(function (c) {
        const li = document.createElement("li");
        li.textContent = describeClue(c);
        els.revealedCluesList.appendChild(li);
      });

      const support = round.support || [];
      const reactions = round.reactions || [];
      els.roundLogWrap.hidden = support.length === 0 && reactions.length === 0;
      support.forEach(function (s) { renderRoundLogEntry(els.roundLogList, s, "kind"); });
      reactions.forEach(function (r) { renderRoundLogEntry(els.roundLogList, r, "verb"); });
    }

    els.revealContinueButton.hidden = !viewModel.you.is_host;
    els.revealStatus.textContent = viewModel.you.is_host ? "" : "Waiting for the host to continue…";
  }

  function renderRoundWaiting(viewModel) {
    let text = "Waiting for the rest of the party…";
    const isSpotlight = viewModel.you.hero_id === viewModel.spotlight_hero_id;
    if (viewModel.phase === "spotlight_action") {
      text = isSpotlight ? "Waiting…" : "Waiting for " + spotlightName(viewModel) + " to choose a move…";
    } else if (viewModel.phase === "ally_support") {
      text = isSpotlight ? "Your party is chiming in…" : "Support sent — waiting for the rest of the party…";
    } else if (viewModel.phase === "spotlight_draft") {
      text = "Waiting for " + spotlightName(viewModel) + " to find the words…";
    } else if (viewModel.phase === "ally_reaction") {
      text = isSpotlight ? "Waiting for your party to react…" : "Reaction locked in — waiting for the rest of the party…";
    }
    els.roundWaitingText.textContent = text;

    const ready = alliesReady(viewModel);
    els.hostOpenDraftButton.hidden = !(viewModel.you.is_host && viewModel.phase === "ally_support" && ready);
    els.hostResolveButton.hidden = !(viewModel.you.is_host && viewModel.phase === "ally_reaction" && ready);
  }

  function showRoundPanel(viewModel, isNewStage) {
    const panel = panelForPhase(viewModel);
    els.actionBuilderPanel.hidden = panel !== "action-builder";
    els.supportPanel.hidden = panel !== "support";
    els.draftPanel.hidden = panel !== "draft";
    els.reactionPanel.hidden = panel !== "reaction";
    els.revealPanel.hidden = panel !== "reveal";
    els.roundWaitingPanel.hidden = panel !== "waiting";

    if (panel === "action-builder") {
      renderActionBuilder(viewModel, isNewStage);
    } else if (panel === "support") {
      renderSupportForm(viewModel, isNewStage);
    } else if (panel === "draft") {
      renderDraftPanel(viewModel, isNewStage);
    } else if (panel === "reaction") {
      renderReactionForm(viewModel, isNewStage);
    } else if (panel === "reveal") {
      renderRevealPanel(viewModel);
    } else {
      renderRoundWaiting(viewModel);
    }
  }

  function renderRound(viewModel) {
    els.spotlightRound.textContent = "Round " + (viewModel.round_index + 1) + " of " + viewModel.total_rounds;
    const isSpotlight = viewModel.you.hero_id === viewModel.spotlight_hero_id;
    els.spotlightName.textContent = spotlightName(viewModel) + (isSpotlight ? " (you!)" : "");
    els.spotlightBanner.classList.toggle("is-you", isSpotlight);

    renderObjectiveArt(viewModel.encounter);
    renderHearts(viewModel.hearts, viewModel.max_hearts);
    renderRoster(viewModel);
    renderPrivatePanel(viewModel);
    renderYourHeroHand(viewModel);
    renderDeclaredAction(viewModel);

    const stageKey = viewModel.phase + ":" + viewModel.round_index + ":" + (viewModel.spotlight_hero_id || "");
    const isNewStage = stageKey !== roundStageKey;
    roundStageKey = stageKey;
    showRoundPanel(viewModel, isNewStage);
  }

  // ---------------------------------------------------------------------
  // Finale rendering
  // ---------------------------------------------------------------------
  function renderFinale(viewModel) {
    const victory = viewModel.finished_victory === true;
    els.finaleArt.src = victory ? "/art/victory.png" : "/art/defeat.png";
    els.finaleArt.alt = victory
      ? "The adventuring party celebrating amid defeated magical paperwork"
      : "The adventuring party buried beneath an avalanche of enchanted paperwork";
    els.finaleHeading.textContent = victory ? "The words are found." : "The meaning stays lost… for now.";
    const rounds = viewModel.history.length;
    els.finaleSummary.textContent = victory
      ? "Your party talked its way through " + rounds + " encounter(s) with " + (viewModel.hearts || 0) + " heart(s) to spare."
      : "The party's hearts ran out after " + rounds + " encounter(s). The kingdom's meaning stays scrambled — for now.";
    els.finaleRecap.innerHTML = "";
    viewModel.history.forEach(function (round, idx) {
      const li = document.createElement("li");
      const name = (round.encounter && round.encounter.name) || ("Round " + (idx + 1));
      const damage = typeof round.damage === "number" ? (round.damage > 0 ? round.damage + " heart(s) lost" : "no damage") : "";
      li.textContent = (idx + 1) + ". " + name + (damage ? " — " + damage : "");
      els.finaleRecap.appendChild(li);
    });
  }

  // ---------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------
  async function postAction(path, body, statusEl, onSuccess, onFinally) {
    try {
      const resp = await apiFetch(roomPath(path), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body || {}),
      });
      if (resp.status === 401) {
        lockOut("That access code was rejected. Reload the page and try again.");
        return;
      }
      if (!resp.ok) {
        if (statusEl) {
          statusEl.textContent = describeApiFailure(resp.status, "That wasn't accepted.");
        }
        return;
      }
      const data = await resp.json();
      applyState(data.state || data);
      if (onSuccess) {
        onSuccess();
      }
    } catch (err) {
      if (statusEl) {
        statusEl.textContent = "Couldn't reach the game server.";
      }
    } finally {
      if (onFinally) {
        onFinally();
      }
    }
  }

  async function startGame() {
    if (!roomId) {
      return;
    }
    els.lobbyStatus.textContent = "Starting…";
    await postAction("/start", {}, els.lobbyStatus);
  }

  async function submitAction(event) {
    event.preventDefault();
    const cardInput = els.actionBuilderPanel.querySelector('input[name="action-card"]:checked');
    const targetId = els.actionTargetSelect.value;
    const outcome = els.actionOutcomeInput.value.trim();
    if (!cardInput || !targetId || !outcome) {
      els.actionStatus.textContent = "Choose a card, a target, and a desired outcome first.";
      return;
    }
    els.actionSubmit.disabled = true;
    els.actionStatus.textContent = "Declaring…";
    await postAction(
      "/spotlight",
      { move_id: cardInput.value, target_id: targetId, desired_outcome: outcome },
      els.actionStatus,
      null,
      function () { els.actionSubmit.disabled = false; }
    );
  }

  async function submitSupport(event) {
    event.preventDefault();
    const kindInput = els.supportPanel.querySelector('input[name="support-kind"]:checked');
    if (!kindInput) {
      els.supportStatus.textContent = "Choose a kind of support first.";
      return;
    }
    els.supportSubmit.disabled = true;
    els.supportStatus.textContent = "Sending…";
    await postAction(
      "/support",
      { kind: kindInput.value, detail: els.supportDetail.value.trim() },
      els.supportStatus,
      null,
      function () { els.supportSubmit.disabled = false; }
    );
  }

  async function openDraft() {
    await postAction("/open-draft", {}, els.roundWaitingText);
  }

  async function practiceVoice() {
    if (!vm) {
      return;
    }
    const next = vm.you.voice_profile.utterance_count + 1;
    await postAction("/voice-profile", { utterance_count: next }, els.draftVoiceStatus);
  }

  async function generateVariants() {
    if (!roomId) {
      return;
    }
    const roughText = els.draftRoughText.value.trim();
    els.draftError.hidden = true;
    els.draftError.textContent = "";
    els.draftLoading.hidden = false;
    els.draftGenerateButton.disabled = true;
    await postAction(
      "/draft",
      { rough_text: roughText },
      null,
      null,
      function () {
        els.draftLoading.hidden = true;
        els.draftGenerateButton.disabled = false;
      }
    );
  }

  async function approveDraft() {
    if (!roomId) {
      return;
    }
    const variantInput = els.variantList.querySelector('input[name="draft-variant"]:checked');
    const editedText = els.draftEditText.value.trim();
    const intent = els.draftIntentText.value.trim();
    if (!editedText || !intent) {
      els.draftStatus.textContent = "Write your message and your intent before approving.";
      return;
    }
    els.draftApproveButton.disabled = true;
    els.draftStatus.textContent = "Approving…";
    await postAction(
      "/approve",
      { chosen_text: editedText, intent: intent, variant_id: variantInput ? variantInput.value : null },
      els.draftStatus,
      null,
      function () { els.draftApproveButton.disabled = false; }
    );
  }

  async function submitReaction(event) {
    event.preventDefault();
    const verbInput = els.reactionPanel.querySelector('input[name="reaction-verb"]:checked');
    if (!verbInput) {
      els.reactionStatus.textContent = "Choose a verb first.";
      return;
    }
    els.reactionSubmit.disabled = true;
    els.reactionStatus.textContent = "Locking in…";
    await postAction(
      "/react",
      { verb: verbInput.value, detail: els.reactionDetail.value.trim(), move_id: els.reactionMoveSelect.value || null },
      els.reactionStatus,
      null,
      function () { els.reactionSubmit.disabled = false; }
    );
  }

  async function resolveRound() {
    await postAction("/resolve", {}, els.revealStatus);
  }

  async function continueRound() {
    await postAction("/advance", {}, els.revealStatus);
  }

  async function replayGame() {
    if (!roomId) {
      return;
    }
    try {
      const resp = await apiFetch(roomPath("/replay"), { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        applyState(data.state || data);
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

  els.actionOutcomeInput.addEventListener("input", function () {
    els.actionOutcomeCount.textContent = String(els.actionOutcomeInput.value.length);
  });
  els.actionBuilderPanel.addEventListener("submit", submitAction);

  els.supportDetail.addEventListener("input", function () {
    els.supportDetailCount.textContent = String(els.supportDetail.value.length);
  });
  els.supportPanel.addEventListener("submit", submitSupport);

  els.draftRoughText.addEventListener("input", function () {
    els.draftRoughCount.textContent = String(els.draftRoughText.value.length);
  });
  els.draftVoiceButton.addEventListener("click", practiceVoice);
  els.draftGenerateButton.addEventListener("click", generateVariants);
  els.draftApproveButton.addEventListener("click", approveDraft);

  els.reactionDetail.addEventListener("input", function () {
    els.reactionDetailCount.textContent = String(els.reactionDetail.value.length);
  });
  els.reactionPanel.addEventListener("submit", submitReaction);

  els.hostOpenDraftButton.addEventListener("click", openDraft);
  els.hostResolveButton.addEventListener("click", resolveRound);
  els.revealContinueButton.addEventListener("click", continueRound);

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
    } else if (screen === "lobby" && vm) {
      lines.push("room-code: " + joinCode);
      lines.push("players: " + vm.players.length + "/4");
      vm.players.forEach(function (p) {
        lines.push("  - " + p.name + (p.hero ? " as " + p.hero.name : "") + (p.is_host ? " (host)" : "") + (!p.active ? " [disconnected]" : ""));
      });
      lines.push("solo: " + (vm.players.length <= 1));
      lines.push("start-visible: " + !els.startButton.hidden);
    } else if (screen === "round" && vm) {
      lines.push("phase: " + vm.phase);
      lines.push("round: " + (vm.round_index + 1) + "/" + vm.total_rounds + (vm.encounter.name ? " (" + vm.encounter.name + ")" : ""));
      lines.push("hearts: " + (vm.hearts === null ? "?" : vm.hearts) + "/" + (vm.max_hearts === null ? "?" : vm.max_hearts));
      lines.push("spotlight: " + spotlightName(vm) + (vm.you.hero_id === vm.spotlight_hero_id ? " (you)" : ""));
      lines.push("private-clue: " + (vm.you.private_clue ? "[set]" : "[none]"));
      lines.push("hand-size: " + heroHand(vm.you.hero).length);
      const panel = panelForPhase(vm);
      lines.push("panel: " + panel);
      if (panel === "draft") {
        lines.push("variants: " + vm.you.draft.variants.length);
        lines.push("draft-approved: " + !!vm.you.draft.approved_text);
      }
      if (panel === "reveal") {
        lines.push("reveal-outcome: " + els.revealOutcome.textContent);
      }
      vm.players.forEach(function (p) {
        lines.push("player: " + p.name + (p.hero_id === vm.spotlight_hero_id ? " [spotlight]" : ""));
      });
    } else if (screen === "finale" && vm) {
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
