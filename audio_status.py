"""Honest status vocabulary for voice privacy and wake detection
(Wave 8A package H, under D-0009's "measured status, not aspiration" rule).

Two audiences, two vocabularies, deliberately kept apart:

**Capability** — "can this build, on this machine, do the thing at all?" Uses
D-0009's fixed capability words (``supported``,
``supported_with_requirements``, ``clipboard_only``, ``experimental``,
``unavailable``, ``unknown``) and nothing else. This is what
``/capabilities`` answers.

**Runtime status** — "what is it doing right now, and if it isn't working,
why?" Voice privacy is ``inactive`` / ``active`` / ``unavailable`` /
``partially_restored``; wake is ``disabled`` / ``ready`` / ``listening`` /
``unavailable`` / ``classifier_missing``. This is what a status route and
(later) the renderer's failure surface answer.

``partially_restored`` exists because it is the one outcome the old code
could not express: the privacy lease was released, but the prior audio state
could not be fully put back. Silently reporting "inactive" there would be a
lie, and reporting "unavailable" would be a different lie. D-0010's
lease-based exact restoration lands in Wave 8B; this vocabulary is what it
will report through.

Every builder returns ``{"status", "reason", "detail", "announce"}`` plus
feature-specific fields. ``reason`` is a stable machine-readable code (the
renderer keys copy off it), ``detail`` is a short human string, and
``announce`` says whether the user asked to be told about failures
(``voice_privacy.announce_failures``). Nothing here formats user-facing copy
— that belongs to the renderer.

Pure stdlib; depends only on :mod:`audio_schema`.
"""

import audio_schema

# --- vocabularies -------------------------------------------------------

# D-0009 capability words. This tuple is the whole allowed set; anything else
# is a bug, not a new status.
CAPABILITY_STATUSES = (
    "supported",
    "supported_with_requirements",
    "clipboard_only",
    "experimental",
    "unavailable",
    "unknown",
)

VOICE_PRIVACY_INACTIVE = "inactive"
VOICE_PRIVACY_ACTIVE = "active"
VOICE_PRIVACY_UNAVAILABLE = "unavailable"
VOICE_PRIVACY_PARTIALLY_RESTORED = "partially_restored"

VOICE_PRIVACY_STATUSES = (
    VOICE_PRIVACY_INACTIVE,
    VOICE_PRIVACY_ACTIVE,
    VOICE_PRIVACY_UNAVAILABLE,
    VOICE_PRIVACY_PARTIALLY_RESTORED,
)

WAKE_DISABLED = "disabled"
WAKE_READY = "ready"
WAKE_LISTENING = "listening"
WAKE_UNAVAILABLE = "unavailable"
WAKE_CLASSIFIER_MISSING = "classifier_missing"

WAKE_STATUSES = (WAKE_DISABLED, WAKE_READY, WAKE_LISTENING, WAKE_UNAVAILABLE, WAKE_CLASSIFIER_MISSING)

# Stable reason codes. Kept as constants so a typo is an AttributeError here
# rather than an unmatched string in the renderer.
REASON_PRIVACY_OFF = "privacy_off"
REASON_NO_MUTE_BINDING = "no_mute_binding"
REASON_PUSH_TO_MUTE_UNAVAILABLE = "push_to_mute_unavailable"
REASON_ISOLATION_UNAVAILABLE = "isolation_unavailable"
REASON_ISOLATION_DEGRADED = "isolation_degraded_to_push_to_mute"
REASON_RESTORE_INCOMPLETE = "restore_incomplete"
REASON_PRIVACY_ACTIVE = "privacy_active"

REASON_WAKE_DISABLED = "wake_disabled"
REASON_WAKE_ENGINE_UNAVAILABLE = "wake_engine_unavailable"
REASON_WAKE_CLASSIFIER_MISSING = "wake_classifier_missing"
REASON_WAKE_MICROPHONE_UNAVAILABLE = "wake_microphone_unavailable"
REASON_WAKE_LISTENING = "wake_listening"
REASON_WAKE_READY = "wake_ready"


def _payload(status, reason, detail, announce, **extra):
    result = {"status": status, "reason": reason, "detail": detail, "announce": bool(announce)}
    result.update(extra)
    return result


# --- voice privacy ------------------------------------------------------

def voice_privacy_status(
    config,
    isolation_available=False,
    push_to_mute_available=True,
    engaged=False,
    restore_complete=True,
    detail="",
):
    """Runtime status of input voice privacy.

    Args:
      config: profile dict (migrated or not — :mod:`audio_schema` handles both).
      isolation_available: whether a capture-isolation adapter exists yet
        (Wave 8B). False today on every platform.
      push_to_mute_available: whether the mute key can actually be held —
        false on a Linux box with no injection tool, for example.
      engaged: whether privacy is currently applied (a hold is in effect).
      restore_complete: False when a release could not fully put the prior
        state back; that is the ``partially_restored`` case.
      detail: optional short human string appended to the default.

    Ordering matters: an unavailable mechanism outranks "not engaged", and an
    incomplete restore outranks everything, because a half-restored system is
    the state the user most needs told about.
    """
    privacy = audio_schema.voice_privacy_of(config)
    announce = privacy["announce_failures"]
    requested = privacy["mode"]
    effective = audio_schema.effective_privacy_mode(config, isolation_available=isolation_available)

    def out(status, reason, text):
        return _payload(
            status, reason, detail or text, announce,
            requested_mode=requested, effective_mode=effective,
            isolation_available=bool(isolation_available),
        )

    if not restore_complete:
        return out(
            VOICE_PRIVACY_PARTIALLY_RESTORED,
            REASON_RESTORE_INCOMPLETE,
            "Voice privacy was released but the previous audio state could not be fully restored.",
        )

    if requested == audio_schema.PRIVACY_MODE_OFF:
        return out(VOICE_PRIVACY_INACTIVE, REASON_PRIVACY_OFF, "Voice privacy is off.")

    if requested == audio_schema.PRIVACY_MODE_ISOLATE and not isolation_available:
        if effective == audio_schema.PRIVACY_MODE_OFF:
            return out(
                VOICE_PRIVACY_UNAVAILABLE,
                REASON_ISOLATION_UNAVAILABLE,
                "Capture isolation is not available on this system and no mute key is set.",
            )
        if not push_to_mute_available:
            return out(
                VOICE_PRIVACY_UNAVAILABLE,
                REASON_ISOLATION_UNAVAILABLE,
                "Capture isolation is not available on this system and push-to-mute cannot run.",
            )
        return out(
            VOICE_PRIVACY_ACTIVE if engaged else VOICE_PRIVACY_INACTIVE,
            REASON_ISOLATION_DEGRADED,
            "Capture isolation is not available yet; using push-to-mute instead.",
        )

    if effective == audio_schema.PRIVACY_MODE_OFF:
        return out(
            VOICE_PRIVACY_UNAVAILABLE,
            REASON_NO_MUTE_BINDING,
            "Push-to-mute is selected but no mute key is set.",
        )

    if effective == audio_schema.PRIVACY_MODE_PUSH_TO_MUTE and not push_to_mute_available:
        return out(
            VOICE_PRIVACY_UNAVAILABLE,
            REASON_PUSH_TO_MUTE_UNAVAILABLE,
            "No input tool is available to hold the mute key on this system.",
        )

    if engaged:
        return out(VOICE_PRIVACY_ACTIVE, REASON_PRIVACY_ACTIVE, "Voice privacy is active.")
    return out(VOICE_PRIVACY_INACTIVE, REASON_PRIVACY_ACTIVE, "Voice privacy is ready.")


def voice_privacy_capability(config=None, isolation_available=False, push_to_mute_available=True):
    """D-0009 capability word for voice privacy on this machine.

    Push-to-mute needs a working input-injection path, so where one exists the
    honest answer is ``supported_with_requirements`` (the user must still
    choose a key), and where none does it is ``unavailable``. Capture
    isolation has no adapter yet, so it never raises the answer above
    push-to-mute's.
    """
    del config
    if isolation_available:
        return "supported"
    if push_to_mute_available:
        return "supported_with_requirements"
    return "unavailable"


# --- wake detection -----------------------------------------------------

def wake_status(
    enabled=False,
    listening=False,
    engine_available=True,
    classifier_selected=True,
    microphone_available=True,
    announce=True,
    detail="",
):
    """Runtime status of the wake detector.

    ``classifier_missing`` is its own status rather than a flavor of
    ``unavailable`` because it is the expected steady state of a fresh
    install: the catalog ships zero wake-phrase classifiers on purpose
    (license gate, see docs/release/WAKE_MODEL_PROVENANCE.md), so "you have no
    phrase model yet" is a setup step, not a broken feature.
    """
    def out(status, reason, text):
        return _payload(status, reason, detail or text, announce, enabled=bool(enabled))

    if not engine_available:
        return out(
            WAKE_UNAVAILABLE,
            REASON_WAKE_ENGINE_UNAVAILABLE,
            "The wake detector could not load its models on this system.",
        )
    if not classifier_selected:
        return out(
            WAKE_CLASSIFIER_MISSING,
            REASON_WAKE_CLASSIFIER_MISSING,
            "No wake-phrase model is selected. Train or import one to use wake word.",
        )
    if not enabled:
        return out(WAKE_DISABLED, REASON_WAKE_DISABLED, "Wake word is off.")
    if not microphone_available:
        return out(
            WAKE_UNAVAILABLE,
            REASON_WAKE_MICROPHONE_UNAVAILABLE,
            "Wake word is on but the microphone could not be opened.",
        )
    if listening:
        return out(WAKE_LISTENING, REASON_WAKE_LISTENING, "Listening for the wake phrase.")
    return out(WAKE_READY, REASON_WAKE_READY, "Wake word is ready.")


def wake_capability(engine_available=True, classifier_available=False, qualified=False):
    """D-0009 capability word for wake detection.

    Stays ``experimental`` until a measured qualification (false
    accept/reject, latency, CPU, handoff, device recovery) exists — the
    release plan requires evidence before a support claim, and none has been
    produced yet.
    """
    if not engine_available:
        return "unavailable"
    if not classifier_available:
        return "supported_with_requirements"
    return "supported" if qualified else "experimental"


# --- combined snapshot --------------------------------------------------

def audio_status_snapshot(config, broker_status=None, **kwargs):
    """One dict for a status route: privacy, wake, and who holds the mic.

    ``broker_status`` is :meth:`audio_input_broker.AudioInputBroker.status`'s
    output, passed in rather than fetched so this module stays free of audio
    imports and remains trivially testable.
    """
    privacy_keys = (
        "isolation_available", "push_to_mute_available", "engaged", "restore_complete",
    )
    wake_keys = (
        "enabled", "listening", "engine_available", "classifier_selected",
        "microphone_available", "announce",
    )
    privacy_args = {k: v for k, v in kwargs.items() if k in privacy_keys}
    wake_args = {k: v for k, v in kwargs.items() if k in wake_keys}

    snapshot = {
        "voice_privacy": voice_privacy_status(config, **privacy_args),
        "wake": wake_status(**wake_args),
    }
    if broker_status is not None:
        snapshot["audio_input"] = {
            "open": bool(broker_status.get("open", False)),
            "device": broker_status.get("device"),
            "holders": list(broker_status.get("subscribers", [])),
            "last_error": broker_status.get("last_error", ""),
        }
    return snapshot
