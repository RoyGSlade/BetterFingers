"""Audio settings schema: output ducking vs. input voice privacy (D-0010).

The old profile schema conflated two unrelated things under one flag:

- ``audio_ducking`` lowered the *system output* volume while recording, and
- the same flag also gated the push-to-mute key hold (``voice_mute_key``),
  which is an *input privacy* control for whatever voice app is listening.

D-0010 splits them, because they fail independently and need different
platform strategies (output ducking is pycaw/pactl master volume; input
privacy is push-to-mute today and PulseAudio/PipeWire capture isolation on
Linux later). This module owns the two replacement blocks, their sanitizers,
and the one-shot forward migration from the legacy flat keys.

New shape::

    output_ducking:
      enabled: bool
      target_percent: float          # 1..100, level held while recording
      restore_fallback_percent: float  # 1..100, used only if the prior level
                                       # could not be read back
    voice_privacy:
      mode: "off" | "push_to_mute" | "isolate_capture_streams"
      mute_binding: str              # key held while dictating (push-to-mute)
      keep_unmuted_apps: [str]       # never silenced by capture isolation
      announce_failures: bool        # surface privacy failures to the user

``isolate_capture_streams`` is RESERVED: the mode value is accepted and
round-trips so a later build (Wave 8B capture isolation) can select it
without another migration, but no isolation adapter exists yet. Until one
does, :func:`effective_privacy_mode` degrades it to ``push_to_mute`` and the
status vocabulary reports isolation as unavailable rather than pretending.

Legacy compatibility is deliberate and two-way:

- :func:`migrate_audio_settings` derives the new blocks from the legacy keys
  when the blocks are absent. It is unconditional and idempotent (same
  discipline as utils.py's ``_migrate_controller_binding``), so the first
  load after upgrade rewrites the profile and every later load is a no-op.
- :func:`project_legacy_audio_keys` writes the legacy keys back out from the
  new blocks, so consumers not yet ported (utils.py's sanitizer, injector.py,
  the legacy renderer's Settings panel) keep seeing exactly the values they
  saw before. Old profiles therefore load with unchanged semantics.

Pure stdlib; unit-tested in tests/test_audio_schema.py.
"""

OUTPUT_DUCKING_KEY = "output_ducking"
VOICE_PRIVACY_KEY = "voice_privacy"

# Legacy flat keys this module migrates from and projects back to.
LEGACY_DUCKING_ENABLED_KEY = "audio_ducking"
LEGACY_DUCKING_LEVEL_KEY = "audio_ducking_level_percent"
LEGACY_DUCKING_FALLBACK_KEY = "audio_ducking_fallback_return_percent"
LEGACY_MUTE_BINDING_KEY = "voice_mute_key"

LEGACY_AUDIO_KEYS = (
    LEGACY_DUCKING_ENABLED_KEY,
    LEGACY_DUCKING_LEVEL_KEY,
    LEGACY_DUCKING_FALLBACK_KEY,
    LEGACY_MUTE_BINDING_KEY,
)

PRIVACY_MODE_OFF = "off"
PRIVACY_MODE_PUSH_TO_MUTE = "push_to_mute"
PRIVACY_MODE_ISOLATE = "isolate_capture_streams"

PRIVACY_MODES = (PRIVACY_MODE_OFF, PRIVACY_MODE_PUSH_TO_MUTE, PRIVACY_MODE_ISOLATE)
# Accepted and persisted, but not yet implemented by any adapter.
RESERVED_PRIVACY_MODES = frozenset({PRIVACY_MODE_ISOLATE})

MIN_DUCK_PERCENT = 1.0
MAX_DUCK_PERCENT = 100.0

# Defensive cap: a keep-unmuted allowlist is a handful of app names, not a
# dumping ground. Mirrors wake_models.MAX_IMPORT_BYTES' "reject the obvious
# mistake" posture rather than trying to be a real quota.
MAX_KEEP_UNMUTED_APPS = 64
MAX_APP_NAME_CHARS = 200

OUTPUT_DUCKING_DEFAULTS = {
    "enabled": False,
    "target_percent": 18.0,
    "restore_fallback_percent": 100.0,
}

VOICE_PRIVACY_DEFAULTS = {
    "mode": PRIVACY_MODE_OFF,
    "mute_binding": "",
    "keep_unmuted_apps": [],
    "announce_failures": True,
}


def output_ducking_defaults():
    return dict(OUTPUT_DUCKING_DEFAULTS)


def voice_privacy_defaults():
    payload = dict(VOICE_PRIVACY_DEFAULTS)
    payload["keep_unmuted_apps"] = []
    return payload


def _coerce_bool(value, default):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "yes", "on", "1"):
            return True
        if lowered in ("false", "no", "off", "0", ""):
            return False
    return bool(default)


def _coerce_percent(value, default):
    """Clamp to the 1..100 window the ducker's level knobs have always used.

    NaN/inf are rejected to the default rather than clamped — a non-finite
    level would otherwise sail through ``max/min`` and reach the volume API.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number or number in (float("inf"), float("-inf")):
        return float(default)
    return max(MIN_DUCK_PERCENT, min(MAX_DUCK_PERCENT, number))


def _coerce_binding(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return ""
    return str(value).strip()


def _coerce_app_list(value):
    if not isinstance(value, (list, tuple)):
        return []
    cleaned = []
    seen = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            continue
        name = str(item).strip()[:MAX_APP_NAME_CHARS]
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
        if len(cleaned) >= MAX_KEEP_UNMUTED_APPS:
            break
    return cleaned


def sanitize_output_ducking(value):
    """Normalize an ``output_ducking`` block. Never raises; unknown keys are
    dropped and bad values fall back to the defaults."""
    defaults = output_ducking_defaults()
    source = value if isinstance(value, dict) else {}
    return {
        "enabled": _coerce_bool(source.get("enabled", defaults["enabled"]), defaults["enabled"]),
        "target_percent": _coerce_percent(
            source.get("target_percent", defaults["target_percent"]), defaults["target_percent"]
        ),
        "restore_fallback_percent": _coerce_percent(
            source.get("restore_fallback_percent", defaults["restore_fallback_percent"]),
            defaults["restore_fallback_percent"],
        ),
    }


def sanitize_voice_privacy(value):
    """Normalize a ``voice_privacy`` block. An unrecognized mode falls back to
    ``off`` (fail-closed: an unreadable privacy setting must not be treated as
    "some privacy is on")."""
    defaults = voice_privacy_defaults()
    source = value if isinstance(value, dict) else {}

    mode = source.get("mode", defaults["mode"])
    mode = str(mode).strip().lower() if isinstance(mode, (str, int, float)) and not isinstance(mode, bool) else ""
    if mode not in PRIVACY_MODES:
        mode = defaults["mode"]

    return {
        "mode": mode,
        "mute_binding": _coerce_binding(source.get("mute_binding", defaults["mute_binding"])),
        "keep_unmuted_apps": _coerce_app_list(source.get("keep_unmuted_apps", defaults["keep_unmuted_apps"])),
        "announce_failures": _coerce_bool(
            source.get("announce_failures", defaults["announce_failures"]), defaults["announce_failures"]
        ),
    }


def migrate_audio_settings(config):
    """Ensure ``config`` carries sanitized ``output_ducking``/``voice_privacy``
    blocks, deriving them from the legacy flat keys the first time.

    Migration rule (the release plan's one-shot rule, stated exactly):

    - ``audio_ducking=true`` + a non-empty ``voice_mute_key`` becomes
      ``output_ducking.enabled=true`` + ``voice_privacy.mode=push_to_mute``
      with the binding preserved.
    - ``audio_ducking=true`` with no binding becomes ducking-on,
      ``voice_privacy.mode=off`` — there was no key to hold, so no input
      privacy behavior existed to carry forward.
    - ``audio_ducking=false`` becomes ducking-off and ``mode=off`` regardless
      of ``voice_mute_key``, because injector.py's ``hold_mute_key`` has
      always returned early when ducking was off. The binding is still
      preserved so re-enabling restores the user's key instead of losing it.

    Unconditional and idempotent: once the blocks exist they are only
    re-sanitized, so a second call changes nothing. Mutates and returns
    ``config`` (same convention as utils.py's other value-level migrations).
    """
    if not isinstance(config, dict):
        return config

    has_ducking_block = isinstance(config.get(OUTPUT_DUCKING_KEY), dict)
    has_privacy_block = isinstance(config.get(VOICE_PRIVACY_KEY), dict)

    legacy_enabled = _coerce_bool(config.get(LEGACY_DUCKING_ENABLED_KEY, False), False)
    legacy_binding = _coerce_binding(config.get(LEGACY_MUTE_BINDING_KEY, ""))

    if has_ducking_block:
        config[OUTPUT_DUCKING_KEY] = sanitize_output_ducking(config[OUTPUT_DUCKING_KEY])
    else:
        config[OUTPUT_DUCKING_KEY] = sanitize_output_ducking({
            "enabled": legacy_enabled,
            "target_percent": config.get(
                LEGACY_DUCKING_LEVEL_KEY, OUTPUT_DUCKING_DEFAULTS["target_percent"]
            ),
            "restore_fallback_percent": config.get(
                LEGACY_DUCKING_FALLBACK_KEY, OUTPUT_DUCKING_DEFAULTS["restore_fallback_percent"]
            ),
        })

    if has_privacy_block:
        config[VOICE_PRIVACY_KEY] = sanitize_voice_privacy(config[VOICE_PRIVACY_KEY])
    else:
        config[VOICE_PRIVACY_KEY] = sanitize_voice_privacy({
            "mode": PRIVACY_MODE_PUSH_TO_MUTE if (legacy_enabled and legacy_binding) else PRIVACY_MODE_OFF,
            "mute_binding": legacy_binding,
            "keep_unmuted_apps": [],
            "announce_failures": VOICE_PRIVACY_DEFAULTS["announce_failures"],
        })

    return config


def project_legacy_audio_keys(config):
    """Write the legacy flat keys back out from the new blocks.

    The compatibility half of the split: every consumer not yet ported to the
    blocks (utils.py's sanitizer, injector.py's push-to-mute, the legacy
    Settings panel) keeps reading the keys it always read, with the values the
    new blocks imply. Call it after :func:`migrate_audio_settings`, on both
    load and save, so the two representations can never disagree on disk.

    ``audio_ducking`` is deliberately the OR of "output ducking on" and "input
    privacy on", because that single legacy flag gated both behaviors: a user
    who wants only push-to-mute must still see the mute key held.
    """
    if not isinstance(config, dict):
        return config

    ducking = sanitize_output_ducking(config.get(OUTPUT_DUCKING_KEY))
    privacy = sanitize_voice_privacy(config.get(VOICE_PRIVACY_KEY))

    config[LEGACY_DUCKING_ENABLED_KEY] = bool(
        ducking["enabled"] or privacy["mode"] != PRIVACY_MODE_OFF
    )
    config[LEGACY_DUCKING_LEVEL_KEY] = ducking["target_percent"]
    config[LEGACY_DUCKING_FALLBACK_KEY] = ducking["restore_fallback_percent"]
    config[LEGACY_MUTE_BINDING_KEY] = privacy["mute_binding"]
    return config


def output_ducking_of(config):
    """Read the ``output_ducking`` block from a profile dict, tolerating a
    profile that has not been through :func:`migrate_audio_settings` yet
    (e.g. a raw dict handed straight to the recorder in a test)."""
    if not isinstance(config, dict):
        return output_ducking_defaults()
    if isinstance(config.get(OUTPUT_DUCKING_KEY), dict):
        return sanitize_output_ducking(config[OUTPUT_DUCKING_KEY])
    return sanitize_output_ducking({
        "enabled": config.get(LEGACY_DUCKING_ENABLED_KEY, False),
        "target_percent": config.get(LEGACY_DUCKING_LEVEL_KEY, OUTPUT_DUCKING_DEFAULTS["target_percent"]),
        "restore_fallback_percent": config.get(
            LEGACY_DUCKING_FALLBACK_KEY, OUTPUT_DUCKING_DEFAULTS["restore_fallback_percent"]
        ),
    })


def voice_privacy_of(config):
    """Read the ``voice_privacy`` block, falling back to the legacy keys with
    the same rule :func:`migrate_audio_settings` applies."""
    if not isinstance(config, dict):
        return voice_privacy_defaults()
    if isinstance(config.get(VOICE_PRIVACY_KEY), dict):
        return sanitize_voice_privacy(config[VOICE_PRIVACY_KEY])
    legacy_enabled = _coerce_bool(config.get(LEGACY_DUCKING_ENABLED_KEY, False), False)
    legacy_binding = _coerce_binding(config.get(LEGACY_MUTE_BINDING_KEY, ""))
    return sanitize_voice_privacy({
        "mode": PRIVACY_MODE_PUSH_TO_MUTE if (legacy_enabled and legacy_binding) else PRIVACY_MODE_OFF,
        "mute_binding": legacy_binding,
    })


def is_reserved_mode(mode):
    return str(mode or "") in RESERVED_PRIVACY_MODES


def effective_privacy_mode(config, isolation_available=False):
    """The privacy mode that will actually run.

    A stored ``isolate_capture_streams`` degrades to ``push_to_mute`` while no
    isolation adapter is available (Wave 8B), and only when a binding exists —
    otherwise there is nothing to hold and the honest answer is ``off``. The
    caller pairs this with :mod:`audio_status` to tell the user that isolation
    was requested but is unavailable, rather than silently doing something
    else.
    """
    privacy = voice_privacy_of(config)
    mode = privacy["mode"]
    if mode == PRIVACY_MODE_ISOLATE and not isolation_available:
        mode = PRIVACY_MODE_PUSH_TO_MUTE
    if mode == PRIVACY_MODE_PUSH_TO_MUTE and not privacy["mute_binding"]:
        return PRIVACY_MODE_OFF
    return mode
