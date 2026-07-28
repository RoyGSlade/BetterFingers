"""Application profiles — schema v1 and the persistent store (Wave 7).

An *application profile* answers one question: when this application is in the
foreground, how should BetterFingers behave? It selects slots the app already
owns — a writing preset, a performance preset, an injection policy, whether
activation is announced, and the controller binding — and nothing else.

What it deliberately cannot express is the other half of "context": who you are
writing to, what the conversation is about, or what you are trying to say. A
window is not a person. Discord being focused tells you a chat client is open;
it does not tell you which friend is on the other end, and a profile schema with
a ``recipient`` field would be an invitation to guess. The field list below is
therefore closed and enforced (``sanitize_profile`` drops unknown keys and
*reports* what it dropped, the same contract ``backend.services.contacts`` uses),
and ``backend.services.app_context`` re-asserts the same rule on its output.

Storage mirrors ``ContactStore``: one versioned JSON file under the unified data
root (``app_paths.resolve_base()`` via ``utils.get_user_data_path()``, so
``BETTERFINGERS_DATA_DIR`` is honoured), loaded lazily, written atomically,
every mutation re-reading from disk first so a failed write leaves the next read
seeing the last good state. Reads are migration-safe: ``load_versioned_store``
handles version drift and quarantines a corrupt file rather than taking the
feature down with it, and ``_coerce_profile`` degrades a hand-edited record
field by field instead of discarding the whole store.

Built-in profiles live in code, not on disk (``BUILTIN_PROFILES``). A user's
edits are stored as overlay records keyed by the same id, so an app update can
correct a built-in's match rules without having to migrate everyone's copy of
them, and "reset to default" is a delete rather than a rewrite.
"""

from __future__ import annotations

import json
import re
import threading
from typing import Optional

from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (current): {"schema_version": 1, "profiles": {id: <profile>},
#                  "pinned": {app_key: profile_id}}
# Each stored <profile> carries its own "schema_version" as well, because a
# single profile is also a document people hand-write and paste around.
SCHEMA_VERSION = 1

DEFAULT_PROFILE_ID = "default"

# The COMPLETE set of fields a profile carries. Anything else is dropped by
# sanitize_profile. An explicit tuple rather than something inferred, so that
# adding a field -- especially one that could name a person -- is a deliberate
# edit somebody reviews.
PROFILE_FIELDS = (
    "schema_version",
    "id",
    "match",
    "writing_preset",
    "performance_preset",
    "injection_policy",
    "tts",
    "bindings",
)

# Fields a caller may set. schema_version is ours.
EDITABLE_FIELDS = (
    "id",
    "match",
    "writing_preset",
    "performance_preset",
    "injection_policy",
    "tts",
    "bindings",
)

MATCH_FIELDS = ("process_names", "window_patterns")
TTS_FIELDS = ("announce_activation",)

# How hard the app works while this application is focused. Data only: the
# service that applies a profile never loads or unloads a model (see
# app_context.py's MODEL LIFECYCLE note), so nothing here can cost a reload.
PERFORMANCE_PRESETS = ("balanced", "low_latency", "quality", "minimal")

# How text reaches the target application.
#   auto           -- injection_pacing.resolve_pacing() decides (today's behaviour)
#   type / paste   -- pin the strategy injection_pacing already implements
#   clipboard_only -- copy, never synthesise input
#   review_only    -- never deliver automatically; the draft waits for the user
INJECTION_POLICIES = ("auto", "type", "paste", "clipboard_only", "review_only")

# Controller binding slots a profile may address.
#
# Exactly one, because exactly one exists: hotkey_manager holds a single
# InputBinding (``controller_binding``) that starts/stops recording. Listing
# aspirational slots here would be inventing a controller subsystem in a schema
# and shipping the invention as configuration.
BINDING_SLOTS = ("record_toggle",)

MAX_ID_LEN = 64
MAX_NAME_LEN = 120
MAX_PATTERN_LEN = 200
MAX_LIST_LEN = 32
# Generous, but bounded: the file is read whole on every mutation.
DEFAULT_CAP = 200

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


def _empty_store() -> dict:
    return {"profiles": {}, "pinned": {}}


def normalize_profile_id(value) -> str:
    """Lowercase, underscore-separated, ascii. '' if unusable.

    Ids appear in logs, routes and the status bar, so they stay opaque and
    boring on purpose -- they are never derived from anything a user typed
    about a person.
    """
    token = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower()).strip("_")
    token = token[:MAX_ID_LEN]
    return token if _ID_RE.match(token) else ""


def _clean_text(value, limit: int) -> str:
    return str(value or "").strip()[:limit]


def _clean_str_list(value, limit: int) -> list:
    """A bounded, de-duplicated, order-preserving list of non-empty strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        text = _clean_text(item, limit).lower()
        if text and text not in out:
            out.append(text)
        if len(out) >= MAX_LIST_LEN:
            break
    return out


def _clean_patterns(value) -> list:
    """Window-CLASS patterns, each of which must compile as a regex.

    Note the word *class*. These never match a window TITLE. A title routinely
    contains the name of the person you are talking to ("Priya - Discord"), and
    a matcher that reads titles is a recipient-inference channel wearing a
    match-rule costume -- see the app_context.py detection note.

    An uncompilable pattern is dropped rather than raised: one bad regex in a
    hand-edited file must not make the whole profile unusable.
    """
    out = []
    for raw in _clean_str_list(value, MAX_PATTERN_LEN):
        try:
            re.compile(raw)
        except re.error:
            continue
        out.append(raw)
    return out


def _clean_bindings(value) -> tuple[dict, list]:
    """Keep only slots that exist. Returns (bindings, dropped_slot_names)."""
    if not isinstance(value, dict):
        return {}, []
    from input_binding import InputBinding

    bindings, dropped = {}, []
    for slot, spec in value.items():
        if slot not in BINDING_SLOTS:
            dropped.append(f"bindings.{slot}")
            continue
        bindings[slot] = InputBinding.from_dict(spec if isinstance(spec, dict) else None).to_dict()
    return bindings, dropped


def sanitize_profile(payload) -> tuple[dict, list]:
    """Coerce arbitrary input into a valid profile body.

    Returns ``(fields, dropped)``. ``dropped`` names every key thrown away, so
    a caller that tries to stash a recipient, a contact id, or a conversation
    summary on a profile is TOLD rather than believing it worked. That is the
    enforcement point for the Wave 7 rule; ``tests/test_app_profiles_store.py``
    asserts a representative set of such keys is rejected.
    """
    if not isinstance(payload, dict):
        return {}, []

    dropped = [key for key in payload if key not in PROFILE_FIELDS]

    match = payload.get("match")
    match = match if isinstance(match, dict) else {}
    dropped.extend(f"match.{key}" for key in match if key not in MATCH_FIELDS)

    tts = payload.get("tts")
    tts = tts if isinstance(tts, dict) else {}
    dropped.extend(f"tts.{key}" for key in tts if key not in TTS_FIELDS)

    bindings, binding_dropped = _clean_bindings(payload.get("bindings"))
    dropped.extend(binding_dropped)

    performance = _clean_text(payload.get("performance_preset"), MAX_NAME_LEN).lower()
    injection = _clean_text(payload.get("injection_policy"), MAX_NAME_LEN).lower()
    writing = _clean_text(payload.get("writing_preset"), MAX_NAME_LEN)

    fields = {
        "id": normalize_profile_id(payload.get("id")),
        "match": {
            "process_names": _clean_str_list(match.get("process_names"), MAX_NAME_LEN),
            "window_patterns": _clean_patterns(match.get("window_patterns")),
        },
        # Explicitly None rather than "" so "leave the user's preset alone" is
        # one value, not two every consumer has to remember to treat alike.
        "writing_preset": writing or None,
        "performance_preset": performance if performance in PERFORMANCE_PRESETS else "balanced",
        "injection_policy": injection if injection in INJECTION_POLICIES else "auto",
        "tts": {"announce_activation": bool(tts.get("announce_activation", False))},
        "bindings": bindings,
    }
    return fields, sorted(set(dropped))


def _coerce_profile(raw) -> Optional[dict]:
    """Defensively coerce one stored record, or None if it has no usable id."""
    if not isinstance(raw, dict):
        return None
    fields, _dropped = sanitize_profile(raw)
    if not fields.get("id"):
        return None
    return {"schema_version": SCHEMA_VERSION, **fields}


def build_profile(profile_id, **kwargs) -> dict:
    """A complete, valid profile document. Used for the built-ins below."""
    profile = _coerce_profile({"id": profile_id, **kwargs})
    if profile is None:  # pragma: no cover - only reachable via a bad literal
        raise ValueError(f"invalid built-in profile id: {profile_id!r}")
    return profile


# --- Built-in profiles -------------------------------------------------------
#
# MATCH-RULE HONESTY. Every process name below is one this project can point at
# a real, checkable source for: the executable a vendor actually ships, or the
# WM_CLASS/process name observed on Linux. Names that are *plausible* but
# unverified are marked UNCERTAIN in a comment rather than quietly included --
# an invented match rule does not fail loudly, it silently applies the wrong
# performance and injection policy in an application the user cares about.
#
# Matching is case-insensitive and is done against the process name / window
# class only (see app_context.py). ".exe" suffixes are kept because that is the
# literal string Windows reports.

BUILTIN_PROFILES: tuple = (
    # The honest fallback. Matches nothing: it is what you get when detection
    # returns nothing (Wayland, missing xdotool) or when no other profile
    # matches, and "unknown application" must resolve HERE rather than to a
    # guess. Every slot is the app's existing default, so selecting Default
    # changes nothing at all.
    build_profile(
        "default",
        match={"process_names": [], "window_patterns": []},
        writing_preset=None,
        performance_preset="balanced",
        injection_policy="auto",
        tts={"announce_activation": False},
    ),
    # Discord ships its Linux binary/WM_CLASS as "discord" and its Windows
    # executable as Discord.exe; the beta/canary channels append the channel.
    build_profile(
        "discord",
        match={
            "process_names": ["discord", "discord.exe", "discordptb", "discordcanary"],
            "window_patterns": [r"^discord"],
        },
        writing_preset=None,
        performance_preset="low_latency",
        injection_policy="auto",
        tts={"announce_activation": False},
    ),
    # Email clients. thunderbird and evolution are the process name and
    # WM_CLASS on Linux; OUTLOOK.EXE is the classic Outlook desktop executable.
    # UNCERTAIN and therefore ABSENT: the "new Outlook" (a PWA whose process
    # name varies by install), Apple Mail (untested here), and every webmail
    # client -- webmail is a browser tab, and the only signal that would
    # distinguish it is the window title, which this feature refuses to read.
    build_profile(
        "email",
        match={
            "process_names": ["thunderbird", "thunderbird.exe", "evolution", "outlook.exe"],
            "window_patterns": [r"^thunderbird", r"^evolution"],
        },
        writing_preset=None,
        performance_preset="quality",
        injection_policy="auto",
        tts={"announce_activation": False},
    ),
    # Generic game. Matches NOTHING by design: there is no honest way to
    # recognise "a game" from a process name, and a heuristic that tried would
    # mainly mis-fire on the launcher. It exists so a user can pin it to a game
    # this build has never heard of (see AppProfileStore.pin) and get the
    # gaming policy without waiting for a built-in.
    build_profile(
        "game_generic",
        match={"process_names": [], "window_patterns": []},
        writing_preset=None,
        performance_preset="minimal",
        injection_policy="review_only",
        tts={"announce_activation": True},
    ),
    # Rocket League ships as RocketLeague.exe on Windows; the Linux path is
    # Proton, which reports the same executable name to the compositor.
    build_profile(
        "rocket_league",
        match={
            "process_names": ["rocketleague.exe"],
            "window_patterns": [r"rocketleague"],
        },
        writing_preset=None,
        performance_preset="minimal",
        injection_policy="review_only",
        tts={"announce_activation": True},
    ),
    # World of Warcraft ships Wow.exe (retail) and WowClassic.exe (classic).
    # UNCERTAIN and therefore ABSENT: the PTR/beta executables, which vary per
    # cycle.
    build_profile(
        "world_of_warcraft",
        match={
            "process_names": ["wow.exe", "wowclassic.exe"],
            "window_patterns": [r"^wow(classic)?\.exe$"],
        },
        writing_preset=None,
        performance_preset="minimal",
        injection_policy="review_only",
        tts={"announce_activation": True},
    ),
    # Writing applications. soffice/libreoffice/swriter are the LibreOffice
    # process names and WM_CLASSes; WINWORD.EXE is Microsoft Word. The paste
    # policy is not a guess: injection_pacing.DEFAULT_PACING already forces a
    # clipboard paste for LibreOffice because the M2 probe caught fast
    # synthetic typing dropping and reordering characters there.
    # UNCERTAIN and therefore ABSENT: Obsidian, Typora, Scrivener and the rest
    # -- plausible, untested, and each one wrong costs a mangled document.
    build_profile(
        "writing_app",
        match={
            "process_names": ["soffice", "soffice.bin", "libreoffice", "swriter", "winword.exe"],
            "window_patterns": [r"libreoffice", r"^soffice"],
        },
        writing_preset=None,
        performance_preset="quality",
        injection_policy="paste",
        tts={"announce_activation": False},
    ),
)

BUILTIN_PROFILE_IDS = tuple(p["id"] for p in BUILTIN_PROFILES)


def builtin_profiles() -> list:
    """Fresh copies, so a caller mutating one cannot corrupt the constants."""
    return [json.loads(json.dumps(p)) for p in BUILTIN_PROFILES]


def _normalize_store(data) -> dict:
    profiles = {}
    raw_profiles = (data or {}).get("profiles")
    if isinstance(raw_profiles, dict):
        items = raw_profiles.values()
    elif isinstance(raw_profiles, list):
        items = raw_profiles
    else:
        items = []
    for item in items:
        profile = _coerce_profile(item)
        if profile:
            profiles[profile["id"]] = profile

    pinned = {}
    raw_pinned = (data or {}).get("pinned")
    if isinstance(raw_pinned, dict):
        known = set(profiles) | set(BUILTIN_PROFILE_IDS)
        for app_key, profile_id in raw_pinned.items():
            key = _clean_text(app_key, MAX_NAME_LEN).lower()
            pid = normalize_profile_id(profile_id)
            # A pin to a profile that no longer exists resolves to "no pin"
            # rather than to a broken reference -- same rule the contacts
            # active-selection route uses for a deleted contact.
            if key and pid in known:
                pinned[key] = pid

    return {"schema_version": SCHEMA_VERSION, "profiles": profiles, "pinned": pinned}


class AppProfileStore:
    """Application profiles on disk: user overlays plus the pinned map.

    ``path`` should always be passed explicitly in tests -- the default touches
    the real user profile via ``utils.get_user_data_path()``, the
    cross-test-pollution trap this repo already learned to avoid.
    """

    def __init__(self, path: Optional[str] = None, cap: int = DEFAULT_CAP):
        self._path = path
        self.cap = max(1, int(cap))
        self._lock = threading.RLock()

    @property
    def path(self) -> str:
        if self._path is None:
            import os
            from utils import get_user_data_path
            self._path = os.path.join(get_user_data_path(), "app_profiles.json")
        return self._path

    def _load(self) -> dict:
        data, _report = load_versioned_store(
            self.path, SCHEMA_VERSION, {},
            default_factory=_empty_store, parse=json.loads,
        )
        return _normalize_store(data)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))

    # --- inspection -------------------------------------------------------

    def list_profiles(self) -> list:
        """Every profile: built-ins, overlaid by the user's edits, then any
        profiles the user created. Built-ins keep their declared order (Default
        first) so the list reads the same on every launch."""
        with self._lock:
            stored = self._load()["profiles"]
        out, seen = [], set()
        for profile in builtin_profiles():
            out.append(stored.get(profile["id"], profile))
            seen.add(profile["id"])
        for pid in sorted(stored):
            if pid not in seen:
                out.append(stored[pid])
        return out

    def get(self, profile_id) -> Optional[dict]:
        pid = normalize_profile_id(profile_id)
        if not pid:
            return None
        for profile in self.list_profiles():
            if profile["id"] == pid:
                return dict(profile)
        return None

    def pinned_map(self) -> dict:
        with self._lock:
            return dict(self._load()["pinned"])

    def pinned_for(self, app_key) -> str:
        key = _clean_text(app_key, MAX_NAME_LEN).lower()
        return self.pinned_map().get(key, "") if key else ""

    def is_builtin(self, profile_id) -> bool:
        return normalize_profile_id(profile_id) in BUILTIN_PROFILE_IDS

    # --- mutation ---------------------------------------------------------

    def save(self, payload) -> dict:
        """Create or replace a profile (an overlay record for a built-in id)."""
        fields, dropped = sanitize_profile(payload)
        if not fields.get("id"):
            return {"ok": False, "error": "invalid_id",
                    "message": "A profile needs an id of lowercase letters, digits and underscores."}

        with self._lock:
            data = self._load()
            if fields["id"] not in data["profiles"] and len(data["profiles"]) >= self.cap:
                return {"ok": False, "error": "cap_reached",
                        "message": f"You already have {self.cap} stored profiles."}
            profile = {"schema_version": SCHEMA_VERSION, **fields}
            data["profiles"][profile["id"]] = profile
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "profile": dict(profile), "dropped_fields": dropped}

    def reset(self, profile_id) -> dict:
        """Drop the user's overlay. A built-in returns to its shipped rules; a
        user-created profile is deleted outright."""
        pid = normalize_profile_id(profile_id)
        if not pid:
            return {"ok": False, "error": "invalid_id"}
        with self._lock:
            data = self._load()
            existed = data["profiles"].pop(pid, None) is not None
            if not existed:
                return {"ok": True, "reset": False, "builtin": self.is_builtin(pid)}
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "reset": True, "builtin": self.is_builtin(pid)}

    def pin(self, app_key, profile_id) -> dict:
        """"Always use this profile here." Pass a falsy profile_id to unpin.

        A pin beats every match rule, which is the point: it is how a user
        corrects a wrong guess permanently, and how an unrecognised game gets
        the generic game profile without waiting for a release.
        """
        key = _clean_text(app_key, MAX_NAME_LEN).lower()
        if not key:
            return {"ok": False, "error": "invalid_app_key"}
        pid = normalize_profile_id(profile_id)
        with self._lock:
            data = self._load()
            if pid:
                known = set(data["profiles"]) | set(BUILTIN_PROFILE_IDS)
                if pid not in known:
                    return {"ok": False, "error": "not_found",
                            "message": f"No profile '{pid}'."}
                data["pinned"][key] = pid
            else:
                data["pinned"].pop(key, None)
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "app_key": key, "profile_id": pid or None}

    def clear_all(self) -> dict:
        """Privacy clear. The pinned map records which applications this person
        runs, which is personal even though the profile bodies are settings --
        see the data_categories entry."""
        with self._lock:
            try:
                self._save(_normalize_store(_empty_store()))
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True}
