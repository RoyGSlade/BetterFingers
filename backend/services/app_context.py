"""Application context — which application is focused, and which profile that
selects (Wave 7).

``injection_pacing`` has detected the foreground application since M2, but only
ever for one purpose: choosing a keystroke pacing strategy. This service is
built *on* that detection rather than beside it (``normalize`` delegates to
``injection_pacing.normalize_app``, so an app key means the same thing in both
places) and promotes the result into a deterministic profile selection. The
pacing consumers -- ``injector.py`` and ``utils.py`` -- are untouched and keep
calling ``detect_active_app_key`` exactly as before.

WHAT THIS SERVICE MAY DECIDE. Exactly five slots, listed in ``SELECTABLE_SLOTS``
and carried in the snapshot: the writing preset, the performance preset, the
injection policy, the TTS activation policy, and the controller binding.

WHAT IT MAY NEVER DECIDE. Who you are writing to, how you know them, what the
conversation is about, or what you are trying to say. A focused window is not a
person: Discord being in front tells you a chat client is open and nothing
whatsoever about who is on the other end. ``FORBIDDEN_OUTPUT_TERMS`` names that
boundary in code and ``tests/test_app_context.py`` walks every snapshot this
module can produce to prove no such field exists -- because the failure mode is
not a crash, it is a plausible guess about a person, presented as fact.

DETECTION IS CLASS-ONLY, AND THAT IS THE SAME RULE. ``injection_pacing``'s X11
detector falls back to the window *title* when the class is unavailable, which
is correct for pacing (a title is a fine hint that LibreOffice is focused) and
unacceptable here: a title routinely reads "Priya - Discord", and a matcher that
consumed titles would infer a recipient through the back door while every field
name stayed clean. So this module runs its own class-only query, never stores a
title, and ``window_patterns`` in the profile schema match the window CLASS.

WAYLAND AND UNKNOWN RESOLVE TO DEFAULT. There is no portable focused-window
query on Wayland, so detection returns "" there, and "" resolves to the Default
profile with ``source="unknown"`` -- an honest "I cannot see this" rather than a
guess that happens to be right on the reporter's machine.

MODEL LIFECYCLE. Applying a profile never loads or unloads a model. The
performance preset is a data field consumers read; this module imports nothing
from ``model_manager`` / ``model_runtime_coordinator`` / ``llm_engine``, and a
test asserts that stays true. A profile switch that dropped a model would turn
alt-tabbing into a multi-second stall, which is exactly the interruption the
whole activation design exists to avoid.

RECORDING IS NEVER INTERRUPTED. The service is TOLD the recording state
(``set_recording_active``) by whoever already owns it; it does not poll or reach
into the recorder. While recording, a resolved change is held as pending and
applied when recording ends.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Callable, Optional

from backend.domain import gaming_policy
from backend.stores.app_profiles import (
    DEFAULT_PROFILE_ID,
    AppProfileStore,
    normalize_profile_id,
)

logger = logging.getLogger(__name__)

# The five slots a profile may select. Any field added to a snapshot that is not
# derived from one of these (or from the bookkeeping in SNAPSHOT_FIELDS) is a
# scope change somebody has to justify.
SELECTABLE_SLOTS = (
    "writing_preset",
    "performance_preset",
    "injection_policy",
    "tts",
    "bindings",
)

# The complete snapshot vocabulary.
SNAPSHOT_FIELDS = (
    "app_key",
    "detected",
    "profile_id",
    "source",
    "override_active",
    "pinned",
    "deferred",
    "pending_profile_id",
    "announcement",
    "gaming_policy",
) + SELECTABLE_SLOTS

# Substrings that must not appear anywhere in the snapshot's keys. Enforced by
# test, not by convention -- see the module docstring.
FORBIDDEN_OUTPUT_TERMS = (
    "recipient", "contact", "relationship", "conversation", "intent",
    "audience", "person", "people", "sender", "thread", "channel",
    "message", "topic", "who",
)

# How long a newly focused application must stay focused before its profile is
# applied. Alt-tabbing through three windows to find one is a single intent, not
# three profile switches, and a switch that fires on every transient focus is
# both visible churn in the status bar and (once TTS is on) audible churn.
DEFAULT_DEBOUNCE_MS = 600

SOURCE_OVERRIDE = "override"
SOURCE_PINNED = "pinned"
SOURCE_MATCHED = "matched"
SOURCE_DEFAULT = "default"
SOURCE_UNKNOWN = "unknown"


# --- Detection ---------------------------------------------------------------


def _detect_x11_window_class() -> str:
    """The focused window's CLASS on X11, or "" -- never its title.

    Deliberately not ``injection_pacing._detect_x11_app``: that helper falls
    back to ``getwindowname`` (the title). See the module docstring.
    """
    if not os.environ.get("DISPLAY") or not shutil.which("xdotool"):
        return ""
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowclassname"],
            check=False, capture_output=True, timeout=2,
        )
    except Exception as exc:  # subprocess/timeout -- degrade to unknown
        logger.debug("app-context detect (x11 class) failed: %s", exc)
        return ""
    lines = [ln for ln in (out.stdout or b"").decode("utf-8", "replace").splitlines() if ln.strip()]
    return lines[-1].strip() if lines else ""


def detect_foreground_identifier() -> str:
    """The raw class/process name of the foreground application, or "".

    "" on Wayland, on a headless session, and when the platform tool is
    missing. Callers must treat that as unknown, never as "no application".
    """
    import platform_capabilities

    if platform_capabilities.IS_WINDOWS:
        # The Windows detector returns a PROCESS name, not a window title, so
        # it is already class-only in the sense that matters here.
        from injection_pacing import _detect_windows_app

        return _detect_windows_app()
    return _detect_x11_window_class()


# --- Matching ----------------------------------------------------------------


def _matches(profile, app_key: str, raw: str) -> bool:
    """Does this profile claim this application?

    Checked against the normalized key and the raw class/process name only --
    both case-insensitive, both class-level identifiers. A profile with no
    match rules (Default, the generic game) never matches; it is selected by
    fallback or by a pin.
    """
    match = profile.get("match") or {}
    names = match.get("process_names") or []
    key = (app_key or "").lower()
    raw_l = (raw or "").lower()

    for name in names:
        if not name:
            continue
        if name == key or name == raw_l:
            return True
        # A WM_CLASS like "Navigator.Firefox" or a path-ish process name still
        # has to line up with the shipped executable name.
        if raw_l and (raw_l.endswith("." + name) or raw_l.split(".")[-1] == name):
            return True

    import re

    for pattern in match.get("window_patterns") or []:
        for candidate in (raw_l, key):
            if not candidate:
                continue
            try:
                if re.search(pattern, candidate):
                    return True
            except re.error:  # pragma: no cover - patterns are pre-validated
                continue
    return False


# --- The service -------------------------------------------------------------


class ApplicationContextService:
    """Foreground application -> application profile, with debounce, a
    recording-safe apply, a temporary override, and pinning.

    Pass ``store`` explicitly in tests: the default touches the real user data
    root.
    """

    def __init__(
        self,
        store: Optional[AppProfileStore] = None,
        detector: Optional[Callable[[], str]] = None,
        clock: Optional[Callable[[], float]] = None,
        debounce_ms: int = DEFAULT_DEBOUNCE_MS,
        announce_enabled: bool = False,
    ):
        self._store = store if store is not None else AppProfileStore()
        self._detect = detector or detect_foreground_identifier
        self._clock = clock or (lambda: time.monotonic() * 1000.0)
        self.debounce_ms = max(0, int(debounce_ms))
        # Spoken activation ships OFF. A profile's own announce_activation is
        # necessary but not sufficient: the user turns announcements on once,
        # globally, and per-profile settings choose which ones speak.
        self.announce_enabled = bool(announce_enabled)

        self._lock = threading.RLock()
        self._subscribers: list = []

        self._app_key = ""
        self._raw = ""
        self._profile_id = DEFAULT_PROFILE_ID
        self._source = SOURCE_UNKNOWN
        self._override_id = ""
        self._recording = False

        # Debounce bookkeeping: the app we have SEEN most recently but not yet
        # accepted, and when we first saw it.
        self._candidate: Optional[str] = None
        self._candidate_raw = ""
        self._candidate_since = 0.0
        # A resolved change waiting for recording to end.
        self._pending_profile_id = ""
        self._announcement = ""

    # --- the five public verbs -------------------------------------------

    def detect(self) -> str:
        """The raw foreground identifier. "" when it cannot be determined."""
        try:
            return str(self._detect() or "")
        except Exception as exc:  # noqa: BLE001 - detection is best-effort
            logger.debug("app-context detect failed: %s", exc)
            return ""

    def normalize(self, raw) -> str:
        """Normalized app key, shared with injection pacing so one string means
        one application in both features."""
        from injection_pacing import normalize_app

        return normalize_app(raw)

    def classify(self, app_key, raw: str = "") -> tuple[str, str]:
        """``(profile_id, source)`` for an application, ignoring any override.

        Order: a pin the user set beats a shipped match rule, a match rule
        beats the fallback, and an application we could not identify resolves
        to Default with ``source="unknown"`` rather than to a guess.
        """
        key = str(app_key or "")
        if not key and not raw:
            return DEFAULT_PROFILE_ID, SOURCE_UNKNOWN

        pinned = self._store.pinned_for(key or raw)
        if pinned:
            return pinned, SOURCE_PINNED

        for profile in self._store.list_profiles():
            if profile["id"] == DEFAULT_PROFILE_ID:
                continue
            if _matches(profile, key, raw):
                return profile["id"], SOURCE_MATCHED
        return DEFAULT_PROFILE_ID, SOURCE_DEFAULT

    def current(self) -> dict:
        """The snapshot the status bar and the pipeline read."""
        with self._lock:
            return self._snapshot()

    def subscribe(self, callback) -> Callable[[], None]:
        """Register a change listener; returns an unsubscribe callable.

        Listeners are called OUTSIDE the lock with the new snapshot, and a
        listener that raises is logged and skipped -- one bad consumer must not
        stop the status bar updating.
        """
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    # --- driving it -------------------------------------------------------

    def poll(self) -> dict:
        """Detect once and fold the result in. Safe to call on a timer."""
        return self.observe(self.detect())

    def observe(self, raw) -> dict:
        """Fold one observed foreground identifier into the state.

        Returns the current snapshot. Emits to subscribers only when the
        effective profile actually changed.
        """
        now = self._clock()
        with self._lock:
            key = self.normalize(raw)
            changed = self._observe_locked(key, str(raw or ""), now)
            snapshot = self._snapshot()
        if changed:
            self._emit(snapshot)
        return snapshot

    def set_recording_active(self, active: bool) -> dict:
        """Tell the service whether a recording is in progress.

        Pushed in by whoever already owns the recording state; this module
        never reads the recorder. While active, profile changes are held; when
        it clears, the held change is applied.
        """
        with self._lock:
            was = self._recording
            self._recording = bool(active)
            changed = False
            if was and not self._recording and self._pending_profile_id:
                # Re-resolve rather than replaying the source recorded when the
                # change was held: an override or a pin may have been set while
                # the recording ran, and applying a stale (id, source) pair
                # would land the wrong profile with a confident explanation.
                self._pending_profile_id = ""
                changed = self._resolve_locked()
            snapshot = self._snapshot()
        if changed:
            self._emit(snapshot)
        return snapshot

    # --- override + pinning ------------------------------------------------

    def set_override(self, profile_id) -> dict:
        """Use this profile until it is cleared, whatever is focused.

        Temporary and in-memory on purpose: "just for now" and "always here"
        are different promises, and writing the temporary one to disk would
        make it outlive the reason for it. The durable form is ``pin``.
        """
        pid = normalize_profile_id(profile_id)
        with self._lock:
            if pid and self._store.get(pid) is None:
                return {"ok": False, "error": "not_found", "message": f"No profile '{pid}'."}
            self._override_id = pid
            changed = self._resolve_locked()
            snapshot = self._snapshot()
        if changed:
            self._emit(snapshot)
        return {"ok": True, "context": snapshot}

    def clear_override(self) -> dict:
        return self.set_override("")

    def pin_current(self, profile_id) -> dict:
        """"Always use this profile for this application." Durable.

        Refuses when nothing is detected: a pin keyed on "" would apply to
        every unidentifiable application at once, which is not what the button
        says.
        """
        with self._lock:
            app_key = self._app_key
        if not app_key:
            return {"ok": False, "error": "unknown_application",
                    "message": "The focused application could not be identified, so there is nothing to pin to."}
        result = self._store.pin(app_key, profile_id)
        if not result.get("ok"):
            return result
        with self._lock:
            changed = self._resolve_locked()
            snapshot = self._snapshot()
        if changed:
            self._emit(snapshot)
        return {"ok": True, "app_key": app_key,
                "profile_id": result.get("profile_id"), "context": snapshot}

    # --- internals ---------------------------------------------------------

    def _observe_locked(self, key: str, raw: str, now: float) -> bool:
        if key == self._app_key and raw == self._raw:
            # Same application still focused -- nothing pending to debounce.
            self._candidate = None
            return False

        if self._candidate != key:
            self._candidate = key
            self._candidate_raw = raw
            self._candidate_since = now
            return False

        if (now - self._candidate_since) < self.debounce_ms:
            return False

        self._app_key = key
        self._raw = self._candidate_raw or raw
        self._candidate = None
        return self._resolve_locked()

    def _resolve_locked(self) -> bool:
        """Recompute the effective profile from app key + override + pins."""
        if self._override_id:
            return self._apply_locked(self._override_id, SOURCE_OVERRIDE)
        profile_id, source = self.classify(self._app_key, self._raw)
        return self._apply_locked(profile_id, source)

    def _apply_locked(self, profile_id: str, source: str) -> bool:
        if profile_id == self._profile_id:
            # Source can change without the profile changing (a pin that
            # happens to agree with the match rule). Record it, emit nothing.
            self._source = source
            self._pending_profile_id = ""
            return False

        if self._recording:
            # Held, not dropped, and not applied mid-recording: a profile that
            # changed the injection policy underneath an in-flight dictation
            # would change where that dictation lands.
            #
            # _source is deliberately NOT updated here. It explains the profile
            # that is CURRENTLY in effect, and rewriting it to explain a profile
            # that has not been applied yet would have the status panel say
            # "you pinned this profile" beside the profile the user did not pin.
            # The held change is disclosed by `deferred` / `pending_profile_id`.
            self._pending_profile_id = profile_id
            return False

        self._profile_id = profile_id
        self._source = source
        self._pending_profile_id = ""
        self._announcement = self._announcement_for(profile_id)
        return True

    def _announcement_for(self, profile_id: str) -> str:
        if not self.announce_enabled:
            return ""
        profile = self._store.get(profile_id) or {}
        if not (profile.get("tts") or {}).get("announce_activation"):
            return ""
        label = profile_id.replace("_", " ")
        # One short sentence, always. trim_spoken_text is the same helper the
        # gaming policy uses, so the ceiling is enforced in one place.
        return gaming_policy.trim_spoken_text(f"{label} profile.", active=True)

    def _snapshot(self) -> dict:
        profile = self._store.get(self._profile_id) or self._store.get(DEFAULT_PROFILE_ID) or {}
        return {
            "app_key": self._app_key,
            "detected": bool(self._app_key),
            "profile_id": profile.get("id", DEFAULT_PROFILE_ID),
            "source": self._source,
            "override_active": bool(self._override_id),
            "pinned": self._source == SOURCE_PINNED,
            "deferred": bool(self._pending_profile_id),
            "pending_profile_id": self._pending_profile_id or None,
            "announcement": self._announcement,
            "writing_preset": profile.get("writing_preset"),
            "performance_preset": profile.get("performance_preset", "balanced"),
            "injection_policy": profile.get("injection_policy", "auto"),
            "tts": dict(profile.get("tts") or {"announce_activation": False}),
            "bindings": dict(profile.get("bindings") or {}),
            "gaming_policy": gaming_policy.policy_for(profile),
        }

    def _emit(self, snapshot: dict) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
            # An announcement is spoken once, on the change that produced it.
            self._announcement = ""
        for callback in subscribers:
            try:
                callback(snapshot)
            except Exception as exc:  # noqa: BLE001 - one bad listener, not all
                logger.debug("app-context subscriber failed: %s", exc)


# --- Process-wide instance ---------------------------------------------------

_service: Optional[ApplicationContextService] = None
_service_lock = threading.Lock()


def get_service() -> ApplicationContextService:
    """The shared service. Built lazily so importing this module touches no
    disk and starts no detection."""
    global _service
    with _service_lock:
        if _service is None:
            _service = ApplicationContextService()
        return _service


def reset_service_for_tests() -> None:
    global _service
    with _service_lock:
        _service = None
