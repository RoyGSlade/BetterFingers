// Application profiles (Wave 7) — the Settings section and the /app-context poll.
//
// This module owns exactly one backend concern: which application is focused
// and which profile that selects. It renders the profile list, the current
// resolution, a temporary override, and the durable "always use this profile
// here" pin, and it pushes each new context snapshot to the status bar.
//
// WHAT IT WILL NOT DISPLAY. Nothing about a recipient, a contact, a
// relationship, or a conversation. The backend snapshot has no such fields (the
// vocabulary is closed and tested in backend/services/app_context.py), and this
// module never derives one — a status rail that named a person because Discord
// was focused would be a guess presented as fact, which is the exact failure
// Wave 7 exists to make impossible.
//
// UNAVAILABLE IS A REAL STATE, NOT AN EMPTY LIST. The backend routes reach the
// renderer through the main-process proxy's exact (method, route) allowlist. If
// the api adapter has no application-context methods, or the call fails, this
// section says so in one sentence rather than rendering an empty profile list —
// an empty list and a broken feature look identical, and only one of them means
// "you have no profiles".
//
// Every mapper below is pure and separately exported, so the display rules are
// testable without a DOM or a backend.

export const APP_PROFILE_ELEMENT_IDS = {
  section: 'sdSetAppProfileGroup',
  currentValue: 'sdSetAppProfileCurrent',
  currentSource: 'sdSetAppProfileSource',
  detectedValue: 'sdSetAppProfileDetected',
  list: 'sdSetAppProfileList',
  overrideSelect: 'sdSetAppProfileOverride',
  overrideClear: 'sdSetAppProfileOverrideClear',
  pinButton: 'sdSetAppProfilePinButton',
  pinNote: 'sdSetAppProfilePinNote',
  announceNote: 'sdSetAppProfileAnnounceNote',
  unavailable: 'sdSetAppProfileUnavailable',
};

export const UNKNOWN = '—';

const REQUIRED_API_METHODS = [
  'fetchAppContextStatus',
  'fetchAppProfiles',
  'overrideAppProfile',
  'pinAppProfile',
];

/** Built-in labels, shared with the status bar so one profile reads one way. */
export const PROFILE_LABELS = {
  default: 'Default',
  discord: 'Discord',
  email: 'Email',
  game_generic: 'Game (generic)',
  rocket_league: 'Rocket League',
  world_of_warcraft: 'World of Warcraft',
  writing_app: 'Writing',
};

export function profileLabel(profileId) {
  const id = typeof profileId === 'string' ? profileId.trim() : '';
  if (!id) return '';
  if (PROFILE_LABELS[id]) return PROFILE_LABELS[id];
  return id
    .split('_')
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * How the current profile was arrived at, in words.
 *
 * "matched" and "pinned" are deliberately distinguishable: one is a rule this
 * build shipped and the other is a decision the user made, and a user trying to
 * work out why an app behaves oddly needs to know which of those they are
 * looking at. "unknown" says the application could not be identified rather
 * than implying Default was chosen for a reason.
 */
export function describeSource(context) {
  switch (context?.source) {
    case 'override':
      return 'Held by a temporary override.';
    case 'pinned':
      return 'You pinned this profile to this application.';
    case 'matched':
      return 'Matched by this profile’s rules.';
    case 'default':
      return 'No profile matches this application, so Default applies.';
    case 'unknown':
    default:
      return 'The focused application could not be identified, so Default applies.';
  }
}

/**
 * The detected application, or an honest reason there isn't one.
 *
 * Wayland has no portable focused-window query, so "" is a routine answer on a
 * large fraction of Linux desktops. Saying so beats a dash the user has to
 * interpret, and beats a guess outright.
 */
export function describeDetected(context) {
  const key = typeof context?.app_key === 'string' ? context.app_key.trim() : '';
  if (key) return key;
  return 'Not identified on this desktop session';
}

/** One profile row's summary line. Only the slots a profile may actually set. */
export function describeProfile(profile) {
  if (!profile || typeof profile !== 'object') return '';
  const parts = [];
  if (profile.writing_preset) parts.push(`Writing: ${profile.writing_preset}`);
  parts.push(`Performance: ${profile.performance_preset || 'balanced'}`);
  parts.push(`Delivery: ${profile.injection_policy || 'auto'}`);
  if (profile.tts?.announce_activation) parts.push('Announces activation');
  return parts.join(' · ');
}

/** The match rules, or an explicit statement that there are none. */
export function describeMatch(profile) {
  const names = profile?.match?.process_names || [];
  const patterns = profile?.match?.window_patterns || [];
  if (!names.length && !patterns.length) {
    return 'Matches nothing automatically — select or pin it yourself.';
  }
  const shown = names.slice(0, 4).join(', ');
  const more = names.length > 4 ? ` +${names.length - 4} more` : '';
  return `Applications: ${shown}${more}`;
}

/** Is the feature usable at all? Returns {available, reason}. */
export function computeAvailability(api) {
  const missing = REQUIRED_API_METHODS.filter((name) => typeof api?.[name] !== 'function');
  if (missing.length) {
    return {
      available: false,
      reason:
        'Application profiles are not reachable in this build — the backend route is not '
        + 'connected yet. Nothing is being detected and no profile is being applied.',
    };
  }
  return { available: true, reason: '' };
}

/** The pin button's label + enablement for a context. */
export function computePinAction(context) {
  if (!context?.detected) {
    return {
      label: 'Always use here',
      disabled: true,
      note: 'The focused application could not be identified, so there is nothing to pin to.',
    };
  }
  if (context.pinned) {
    return {
      label: 'Remove pin',
      disabled: false,
      note: `${profileLabel(context.profile_id)} is pinned to ${context.app_key}.`,
    };
  }
  return {
    label: 'Always use here',
    disabled: false,
    note: `Pin the selected profile to ${context.app_key} so it is used every time.`,
  };
}

export function collectAppProfileElements(root = document) {
  const els = {};
  for (const [key, id] of Object.entries(APP_PROFILE_ELEMENT_IDS)) {
    els[key] = root?.getElementById?.(id) ?? null;
  }
  return els;
}

/**
 * @param {object} opts
 * @param {object} opts.elements  from collectAppProfileElements()
 * @param {object} opts.api       backend api module
 * @param {object} [opts.hooks]   { showToast, onContextChanged, escapeHtml }
 * @param {number} [opts.pollMs]  status poll interval; 0 disables the timer
 */
export function createApplicationProfilesFeature({
  elements = {},
  api = null,
  hooks = {},
  pollMs = 4000,
} = {}) {
  const escapeHtml =
    hooks.escapeHtml
    || ((value) =>
      String(value ?? '').replace(/[&<>"']/g, (ch) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch])));

  const availability = computeAvailability(api);
  let context = null;
  let profiles = [];
  let timer = null;
  // The row the user has highlighted — what "Always use here" pins. Distinct
  // from the ACTIVE profile: pinning the active one when the user has just
  // selected a different row would pin the wrong thing silently.
  let selectedId = '';

  function renderUnavailable() {
    if (elements.unavailable) {
      elements.unavailable.hidden = false;
      elements.unavailable.textContent = availability.reason;
    }
    if (elements.currentValue) elements.currentValue.textContent = UNKNOWN;
    if (elements.currentSource) elements.currentSource.textContent = '';
    if (elements.detectedValue) elements.detectedValue.textContent = UNKNOWN;
    if (elements.list) elements.list.innerHTML = '';
    if (elements.overrideSelect) elements.overrideSelect.disabled = true;
    if (elements.overrideClear) elements.overrideClear.disabled = true;
    if (elements.pinButton) elements.pinButton.disabled = true;
  }

  function renderCurrent() {
    if (elements.unavailable) elements.unavailable.hidden = true;
    if (elements.currentValue) {
      elements.currentValue.textContent = context ? profileLabel(context.profile_id) : UNKNOWN;
    }
    if (elements.currentSource) {
      elements.currentSource.textContent = context ? describeSource(context) : '';
    }
    if (elements.detectedValue) {
      elements.detectedValue.textContent = context ? describeDetected(context) : UNKNOWN;
    }
    if (elements.overrideSelect) {
      elements.overrideSelect.disabled = false;
      elements.overrideSelect.value = context?.override_active ? context.profile_id : '';
    }
    if (elements.overrideClear) {
      elements.overrideClear.disabled = !context?.override_active;
    }
    const pin = computePinAction(context);
    if (elements.pinButton) {
      elements.pinButton.textContent = pin.label;
      elements.pinButton.disabled = pin.disabled;
      elements.pinButton.dataset.pinned = String(Boolean(context?.pinned));
    }
    if (elements.pinNote) elements.pinNote.textContent = pin.note;
  }

  function renderList() {
    if (!elements.list) return;
    if (!profiles.length) {
      // Distinct from renderUnavailable()'s blank list: the feature IS
      // reachable, there is just nothing configured (or the last refresh
      // failed and reported it separately via a toast) -- never a silent
      // blank with no explanation at all.
      elements.list.innerHTML = '<div class="sd-appprofile-row__empty">No application profiles are configured yet.</div>';
      return;
    }
    elements.list.innerHTML = profiles
      .map((profile) => {
        const active = context?.profile_id === profile.id;
        const selected = selectedId === profile.id;
        return (
          `<div class="sd-appprofile-row${active ? ' is-active' : ''}"`
          + ` data-app-profile="${escapeHtml(profile.id)}"`
          + ` data-active="${active ? 'true' : 'false'}"`
          + ` data-selected="${selected ? 'true' : 'false'}">`
          + `<div class="sd-appprofile-row__head">`
          + `<span class="sd-appprofile-row__name">${escapeHtml(profileLabel(profile.id))}</span>`
          + (active
            ? `<span class="sd-appprofile-row__badge" data-app-profile-active>Active</span>`
            : '')
          + `</div>`
          + `<span class="sd-appprofile-row__summary">${escapeHtml(describeProfile(profile))}</span>`
          + `<span class="sd-appprofile-row__match">${escapeHtml(describeMatch(profile))}</span>`
          + `<button type="button" class="sd-appprofile-row__select"`
          + ` data-app-profile-select="${escapeHtml(profile.id)}">Select</button>`
          + `</div>`
        );
      })
      .join('');
  }

  function renderOverrideOptions() {
    if (!elements.overrideSelect) return;
    const options = [
      '<option value="">No override (use the detected application)</option>',
      ...profiles.map(
        (profile) =>
          `<option value="${escapeHtml(profile.id)}">${escapeHtml(profileLabel(profile.id))}</option>`,
      ),
    ];
    elements.overrideSelect.innerHTML = options.join('');
    elements.overrideSelect.value = context?.override_active ? context.profile_id : '';
  }

  function publish(next) {
    const changedProfile = context?.profile_id !== next?.profile_id
      || context?.override_active !== next?.override_active;
    context = next || null;
    renderCurrent();
    if (changedProfile) {
      renderList();
      hooks.onContextChanged?.(context);
    }
  }

  async function refreshStatus() {
    if (!availability.available) return null;
    try {
      const payload = await api.fetchAppContextStatus();
      publish(payload?.context ?? null);
      return context;
    } catch (_error) {
      // A failed poll leaves the last known state alone rather than blanking
      // the rail: a dropped request is not evidence the profile changed.
      return context;
    }
  }

  async function refreshProfiles() {
    if (!availability.available) return [];
    // Retried once (a slow first response, not a dead endpoint) before giving
    // up. On a genuine failure `profiles` is left as whatever it already
    // held -- the same "don't blank a working rail" rule refreshStatus()
    // above already follows for context polls, now applied consistently to
    // the profile list and override dropdown too.
    let payload = null;
    let lastError = null;
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        payload = await api.fetchAppProfiles();
        lastError = null;
        break;
      } catch (error) {
        lastError = error;
      }
    }
    if (lastError) {
      hooks.showToast?.(`Could not refresh application profiles: ${lastError.message}`, 'danger');
    } else {
      profiles = Array.isArray(payload?.profiles) ? payload.profiles : [];
    }
    if (!selectedId && profiles.length) selectedId = profiles[0].id;
    renderOverrideOptions();
    renderList();
    return profiles;
  }

  async function setOverride(profileId) {
    if (!availability.available) return null;
    try {
      const result = await api.overrideAppProfile(profileId || '');
      publish(result?.context ?? null);
      renderList();
      return context;
    } catch (error) {
      hooks.showToast?.(`Could not change the profile override: ${error.message}`, 'danger');
      return context;
    }
  }

  async function togglePin() {
    if (!availability.available) return null;
    // Unpin sends an empty profile id; pin sends whichever row is selected.
    const wantsUnpin = Boolean(context?.pinned);
    try {
      const result = await api.pinAppProfile(wantsUnpin ? '' : selectedId);
      publish(result?.context ?? null);
      renderList();
      hooks.showToast?.(
        wantsUnpin ? 'Pin removed.' : `Pinned ${profileLabel(selectedId)} to ${context?.app_key || 'this application'}.`,
        'success',
      );
      return context;
    } catch (error) {
      hooks.showToast?.(`Could not pin the profile: ${error.message}`, 'danger');
      return context;
    }
  }

  function selectProfile(profileId) {
    selectedId = String(profileId || '');
    renderList();
    renderCurrent();
    return selectedId;
  }

  function bind() {
    elements.overrideSelect?.addEventListener?.('change', (event) => {
      setOverride(event.target.value);
    });
    elements.overrideClear?.addEventListener?.('click', () => setOverride(''));
    elements.pinButton?.addEventListener?.('click', () => togglePin());
    elements.list?.addEventListener?.('click', (event) => {
      const id = event.target?.dataset?.appProfileSelect;
      if (id) selectProfile(id);
    });
  }

  function init() {
    if (elements.announceNote) {
      // Disclosed rather than offered: there is no switch here because the
      // backend ships announcements off and exposes no route to turn them on
      // yet. A control that silently did nothing would be worse than this
      // sentence.
      elements.announceNote.textContent =
        'Spoken profile announcements are off. When enabled they are one short sentence, '
        + 'never queued, and only for profiles that ask for one.';
    }
    if (!availability.available) {
      renderUnavailable();
      return { available: false };
    }
    bind();
    refreshProfiles().then(() => refreshStatus());
    if (pollMs > 0) {
      timer = setInterval(() => refreshStatus(), pollMs);
    }
    return { available: true };
  }

  function destroy() {
    if (timer) clearInterval(timer);
    timer = null;
  }

  return {
    init,
    destroy,
    refreshStatus,
    refreshProfiles,
    setOverride,
    togglePin,
    selectProfile,
    getContext: () => context,
    getProfiles: () => profiles.slice(),
    getSelectedId: () => selectedId,
    isAvailable: () => availability.available,
  };
}
