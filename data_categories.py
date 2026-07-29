"""The concrete persistent data-category inventory (Wave 6: fully wired).

Read-write lifecycle metadata for every persistent store BetterFingers owns.
As of Wave 6 the ``paths``/``size``/``wipe``/``verify`` callables are **real**:
each category knows where it lives (``data_paths``), how big it is, how to
delete itself, and how to prove it is gone (``data_lifecycle``). The privacy
report, the wipe modes, the factory reset, and the filesystem-agreement test
are all generated from this one list, so the report cannot lie by omission and
the wipe cannot miss a store the report shows.

The completeness rule this file is judged against, in both directions:

    A category without a store is as wrong as a store without a category.

Wave 6 reconciled both directions against the modules on disk:

* **Added** ``persona_learning`` (a real store since F2.6, never declared) and
  ``user_profile`` (a real store since long before that, never declared, and
  it resolves its own root outside ``app_paths`` — so it survived every wipe
  mode *and* was invisible to the report).
* **Cut** ``support_report``. It has no store: ``server.gather_support_report``
  renders Markdown in memory and returns it over HTTP; nothing writes it to
  disk. A category whose size is always 0, whose wipe deletes nothing, and
  whose verify passes vacuously is a line of reassurance, not a fact. If the
  user saves the report themselves it lands wherever they chose — outside our
  roots, where we can neither report nor wipe it, and claiming otherwise would
  be the lie this inventory exists to prevent.
* **Considered and rejected** as categories, because no store backs them:
  ``voice_profile_versions`` (nothing in the tree writes one),
  ``wake_training_samples`` (``wake_training_data`` builds windows purely in
  memory), and ``wake_classifier_metadata`` (the only wake manifest is
  ``imported_models.json`` *inside* the wake-models directory, already covered
  by ``wake_models``).

Kept separate from ``data_registry.py`` (the mechanism) so the mechanism stays
dependency-free, and from ``data_paths.py`` (the locations) so this file stays
readable as an inventory.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, Optional

import data_lifecycle
import data_paths
from data_registry import (
    DataCategory,
    DataRegistry,
    VerificationResult,
    WipeResult,
    WIPE_MODE_CONVERSATIONS as _CONV,
    WIPE_MODE_FACTORY_RESET as _FACT,
    WIPE_MODE_PERSONAL as _PERS,
)


# --- Wipe-mode membership (nesting-valid; see data_registry validation) -------

_CONVERSATIONS = frozenset({_CONV, _PERS, _FACT})  # cleared even by the lightest mode
# ^ Membership of this set is not a taste question: it is the exact set the
#   shipped POST /privacy/wipe deletes. Wave 6 made the wipe registry-driven,
#   so if a store were listed in a mode the endpoint did not really clear (or
#   cleared a store no mode listed) the report and the filesystem would
#   disagree again — which is the one failure this whole file exists to
#   prevent. See the notes on persona_learning and contacts below for why
#   those two are conversation data rather than merely personal data.
_PERSONAL = frozenset({_PERS, _FACT})              # cleared by personal + factory
_FACTORY = frozenset({_FACT})                      # only a factory reset removes it
_OPT_IN = frozenset()                              # never auto-wiped (separate opt-in)


def _cat(cid, label, owner, sensitivity, retention, wipe_modes, *,
         paths: Callable[[], list[Path]],
         in_report=True, in_export=False, user_text=False,
         wipe: Optional[Callable[[], WipeResult]] = None,
         verify: Optional[Callable[[], VerificationResult]] = None,
         ) -> DataCategory:
    """Declare one category. ``paths`` is the only required callable — size,
    wipe, and verify are derived from it unless a store needs special handling
    (the history DB must be recreated, not merely deleted; opt-in stores must
    not report their own survival as a failure).

    New stores should supply ``paths`` and nothing else. If a store cannot be
    expressed as "these paths, deleted", that is a signal about the store.
    """
    return DataCategory(
        id=cid,
        label=label,
        owner=owner,
        sensitivity=sensitivity,
        paths=paths,
        retention=retention,
        wipe_modes=wipe_modes,
        included_in_report=in_report,
        included_in_export=in_export,
        may_contain_user_text=user_text,
        size=data_lifecycle.make_size(paths),
        wipe=wipe or data_lifecycle.make_wipe(paths),
        verify=verify or data_lifecycle.make_verify(paths),
    )


# --- Stores that cannot be "just delete the paths" ---------------------------


def _wipe_history_db() -> WipeResult:
    """Delegate to ``history_store``, which removes the DB *and its -wal/-shm
    companions* and then recreates an empty schema. Deleting the file alone
    would leave the app with a schemaless database on next write; deleting it
    without the WAL would leave committed transcription text recoverable."""
    import history_store
    result = history_store.wipe_database()
    removed = [str(Path(history_store.get_db_path()).parent / name)
               for name in result.get("removed", [])]
    # "Deleted" and "left in a usable empty state" are two different claims and
    # the caller needs both: a DB that was removed but whose schema could not be
    # recreated is a broken install, not a clean one.
    detail = {"recreated": bool(result.get("recreated"))}
    if result.get("ok"):
        return WipeResult(ok=True, removed=removed, detail=detail,
                          message="history database wiped and recreated empty")
    return WipeResult(
        ok=False, removed=removed, error="history_db_wipe_failed", detail=detail,
        message=(f"failed={result.get('failed')} leftover={result.get('leftover')} "
                 f"recreated={result.get('recreated')}"))


def _verify_history_db() -> VerificationResult:
    """The DB file is *expected* to exist after a wipe (recreated empty), so
    presence is not the test — emptiness is. The -wal/-shm companions must be
    gone, and the drafts table must hold zero rows."""
    # Resolved through data_paths, which never creates anything. Opening the
    # database would create an empty one where a factory reset had removed it,
    # and the verification would then report the file it had just conjured.
    present = data_paths.history_db()
    db_path = next((p for p in present if p.name == "history.db"), None)
    companions = [str(p) for p in present if p.name != "history.db"]
    if db_path is None:
        if companions:
            return VerificationResult(
                ok=False, remaining=companions,
                detail=f"history database is gone but companions remain: {companions}")
        return VerificationResult(ok=True, detail="no history database on disk")
    import history_store
    try:
        rows = history_store.count()
    except Exception as exc:  # noqa: BLE001 - an unreadable DB is a real failure
        return VerificationResult(ok=False, remaining=[str(db_path)],
                                  detail=f"could not read history database: {exc}")
    if rows or companions:
        return VerificationResult(
            ok=False, remaining=([str(db_path)] if rows else []) + companions,
            detail=f"{rows} history row(s) remain; companions={companions}")
    return VerificationResult(ok=True, detail="history database is empty")


def _wipe_raw_recordings() -> WipeResult:
    """Delegate to ``recordings``, which owns the directory.

    ``rmtree`` on the directory would also work — ``get_recordings_dir()``
    recreates it — but ``clear_recordings()`` additionally sweeps orphaned
    ``.wav`` files and half-written ``.tmp`` siblings that an interrupted save
    left behind, and it is the same call the shipped wipe already made. The
    registry existing does not make the module that owns a store wrong.
    """
    import recordings
    # Snapshot the real filenames before deleting so `removed` is the list of
    # things that actually went, not a directory name standing in for them.
    # The caller reports a count from this, and a count derived from a
    # one-element list containing a directory would have been wrong for every
    # value except one.
    directory = Path(recordings.get_recordings_dir())
    try:
        before = sorted(str(p) for p in directory.iterdir() if p.is_file())
    except OSError:
        before = []
    recordings.clear_recordings()
    # clear_recordings() sweeps the shapes it knows about (recordings, their
    # sidecars, interrupted temps). The category declares the whole directory,
    # so anything else in there is still this category's data and still has to
    # go — otherwise the wipe would be narrower than the verification and a
    # stray file would make every wipe report failure forever.
    errors: list[str] = []
    for leftover in list(directory.glob("*")) if directory.is_dir() else []:
        try:
            if leftover.is_dir() and not leftover.is_symlink():
                shutil.rmtree(leftover)
            else:
                leftover.unlink()
        except OSError as exc:
            errors.append(f"{leftover}: {exc}")
    if errors:
        return WipeResult(ok=False, removed=[], error="recordings_leftover",
                          message="; ".join(errors[:5]))
    return WipeResult(ok=True, removed=before,
                      message=f"removed {len(before)} recording file(s)")


def _verify_raw_recordings() -> VerificationResult:
    """The directory is expected to survive (it is recreated on next use), so
    emptiness is the test, not absence.

    Reads the directory through ``data_paths`` rather than through
    ``recordings.list_leftover_files()``, which resolves its directory via
    ``get_recordings_dir()`` and mkdirs as a side effect. A verification that
    creates the directory it is checking is the P0 the voices path already hit
    once: the postcondition check resurrects what the wipe just deleted and
    then reports success.
    """
    paths = data_paths.raw_recordings()
    if not paths:
        return VerificationResult(ok=True, detail="no recordings directory")
    leftover: list[str] = []
    for directory in paths:
        try:
            leftover.extend(str(p) for p in directory.iterdir() if p.is_file())
        except OSError:
            continue
    if leftover:
        return VerificationResult(ok=False, remaining=sorted(leftover)[:20],
                                  detail=f"{len(leftover)} recording file(s) remain")
    return VerificationResult(ok=True, detail="no recordings remain")


def _wipe_persona_learning() -> WipeResult:
    """Clear through the store's own API rather than unlinking the file.

    The store's guarantees (atomic write, canonical dedupe, per-persona caps,
    one-shot consent with no persisted consent flag) live in
    ``PersonaLearningStore``; going around it with ``unlink`` would work today
    and silently stop working the moment the store gains an index or a second
    file. Keys are dropped, not blacklisted — a later add_example with fresh
    consent recreates them.
    """
    from backend.services.persona_learning import PersonaLearningStore
    store = PersonaLearningStore()
    path = store.path
    result = store.clear_all()
    if result.get("ok") and not store.list_personas():
        return WipeResult(ok=True, removed=[path],
                          message="all learned persona examples cleared")
    return WipeResult(ok=False, removed=[], error="persona_learning_clear_failed",
                      message=str(result.get("message") or "personas remain after clear"))


def _verify_persona_learning() -> VerificationResult:
    """Re-read the store: zero personas with zero examples. The file itself may
    remain as an empty envelope, which is why this counts examples rather than
    checking for absence.

    Reads the JSON directly instead of instantiating ``PersonaLearningStore``.
    That is a deliberate exception to "go through the store's API", and the
    reason is specific: opening the store runs ``load_versioned_store``, which
    completes any pending v1->v2 migration and writes a ``.bak-v1`` copy of the
    user's examples as a side effect. A verification that writes a fresh copy
    of the very data it is checking for is worse than useless — it made the
    factory reset's own read-only check create a file. Counting here duplicates
    a little schema knowledge; the alternative duplicates the user's data.
    """
    paths = data_paths.persona_learning()
    if not paths:
        return VerificationResult(ok=True, detail="no learned persona examples remain")
    import json
    remaining: list[str] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            # Unreadable is not provably empty, so it is not a pass.
            remaining.append(str(path))
            continue
        personas = data.get("personas") if isinstance(data, dict) else None
        if not isinstance(personas, dict):
            continue
        for name, value in personas.items():
            # v2 wraps examples in {"examples": [...]}; v1 stored a bare list.
            examples = value.get("examples") if isinstance(value, dict) else value
            if examples:
                remaining.append(f"{path.name}:{name}")
    if remaining:
        return VerificationResult(
            ok=False, remaining=remaining,
            detail=f"{len(remaining)} persona(s) still hold learned examples")
    return VerificationResult(ok=True, detail="no learned persona examples remain")


def _wipe_contacts() -> WipeResult:
    """Clear through ``ContactStore`` for the same reason as persona learning:
    the store owns its own atomicity and id bookkeeping."""
    from backend.services.contacts import ContactStore
    store = ContactStore()
    path = store.path
    result = store.clear_all()
    if result.get("ok") and store.count() == 0:
        return WipeResult(ok=True, removed=[path], message="all contacts cleared")
    return WipeResult(ok=False, removed=[], error="contacts_clear_failed",
                      message=str(result.get("message") or "contacts remain after clear"))


def _verify_contacts() -> VerificationResult:
    # Goes through the store rather than short-circuiting on "no file on disk".
    # ContactStore reads without migrating, so there is no write side effect to
    # avoid here (unlike persona_learning), and asking the store keeps a store
    # that reports contacts it cannot write from passing verification.
    from backend.services.contacts import ContactStore
    store = ContactStore()
    count = store.count()
    if count:
        return VerificationResult(ok=False, remaining=[store.path],
                                  detail=f"{count} contact(s) remain")
    return VerificationResult(ok=True, detail="no contacts remain")


# --- The inventory -----------------------------------------------------------
# One entry per persistent store. Ordered roughly by wipe breadth (conversation
# data first, settings/electron state last). Sensitivity and may_contain_user_text
# are kept honest — under-claiming either would defeat the privacy report.

CATEGORIES: list[DataCategory] = [
    # Conversation data — removed by every wipe mode.
    _cat("raw_recordings", "Raw recordings", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         paths=data_paths.raw_recordings,
         wipe=_wipe_raw_recordings, verify=_verify_raw_recordings),
    _cat("drafts", "Draft JSON", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         paths=data_paths.drafts, in_export=True, user_text=True),
    _cat("history_db", "Transcription history (SQLite)", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         paths=data_paths.history_db, in_export=True, user_text=True,
         wipe=_wipe_history_db, verify=_verify_history_db),
    _cat("temp_audio", "Temporary audio & conversion artifacts", "python", "sensitive",
         "Ephemeral; swept on wipe and on restart.", _CONVERSATIONS,
         paths=data_paths.temp_audio),
    # Learned persona examples (F2.6). Declared in Wave 6 after the store had
    # existed undeclared: approved raw-to-final rewrite pairs are the user's own
    # words on BOTH sides, which makes this one of the most sensitive stores in
    # the product and the one most obviously owed an explicit disclosure.
    #
    # Conversation data, not merely personal data. An example is a verbatim
    # dictation the user gave and the final text it became — the same content
    # as a draft, kept under a different filename. "Clear my conversations"
    # that left a copy of those sentences behind would be the wipe lying, and
    # the shipped endpoint has always cleared them, so listing this any lower
    # would have made the registry disagree with the code.
    #
    # The store is consent-gated per add with no persisted consent flag, so a
    # wipe drops the data without leaving anything that could re-authorize
    # itself.
    _cat("persona_learning", "Learned persona examples", "python", "sensitive",
         "Only examples you explicitly approved; kept until you delete them or "
         "conversations are cleared.", _CONVERSATIONS,
         paths=data_paths.persona_learning, in_export=True, user_text=True,
         wipe=_wipe_persona_learning, verify=_verify_persona_learning),
    # Contacts (Stage 11). Also conversation-tier, for the reason the store's
    # own tests give: a contact list that survived "delete my data" would be a
    # breach of the product's central promise. The notes and tone guidance are
    # prose the user dictated about a person, and drafts reference contacts by
    # id — clearing the drafts while keeping the named people would leave the
    # more identifying half on disk. user_text for the same reason.
    _cat("contacts", "Contacts", "python", "personal",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         paths=data_paths.contacts, in_export=True, user_text=True,
         wipe=_wipe_contacts, verify=_verify_contacts),

    # Personal data — removed by personal + factory.
    _cat("cloned_voices", "Cloned voices & metadata", "python", "sensitive",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.cloned_voices),
    _cat("personas", "Personas", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.personas, in_export=True, user_text=True),
    _cat("dictionary", "Personal dictionary", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.dictionary, in_export=True, user_text=True),
    _cat("macros", "Macros", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.macros, in_export=True, user_text=True),
    # User profile. Declared in Wave 6; the store predates the registry and was
    # missed because it does NOT resolve through app_paths -- user_profile_manager
    # builds its own root, so on an install whose base is XDG this file sits in a
    # second directory the privacy screen never listed. It survived every wipe
    # mode including factory reset. user_text because "hobbies" is free prose the
    # user wrote about themselves.
    _cat("user_profile", "Personal profile (vibe, work style, hobbies)", "python",
         "personal", "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.user_profile, in_export=True, user_text=True),
    _cat("wake_models", "Wake models & training artifacts", "python", "sensitive",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.wake_models),
    # Audio privacy crash-recovery journal (Wave 8B, D-0010). Written before
    # any capture stream is muted and cleared on the next clean release or at
    # the next startup, so it is normally absent. Declared "configuration"
    # sensitivity and user_text=False because it holds only audio-server
    # stream indices and a boolean prior mute state — no names, no audio, no
    # prose. Cleared by a personal wipe rather than only a factory reset,
    # because it is operational state, not a setting.
    _cat("audio_privacy_journal", "Audio privacy recovery journal", "python", "configuration",
         "Transient; cleared when voice privacy is released and on wipe.", _PERSONAL,
         paths=data_paths.audio_privacy_journal),
    _cat("mcp_config", "MCP configuration", "python", "sensitive",
         "Kept until personal data is cleared; may contain credentials/tokens.", _PERSONAL,
         paths=data_paths.mcp_config),
    _cat("graph_data", "Graph data", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.graph_data, user_text=True),
    _cat("debug_log", "Debug log", "python", "personal",
         "Rolling; cleared with personal data.", _PERSONAL,
         paths=data_paths.debug_log, user_text=True),
    _cat("sidecar_raw_log", "Sidecar backend raw log", "electron", "personal",
         "Rolling; cleared with personal data (Electron-owned).", _PERSONAL,
         paths=data_paths.sidecar_raw_log, user_text=True),

    # Settings / configuration — removed only by a factory reset.
    _cat("voice_presets", "Voice presets", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY,
         paths=data_paths.voice_presets, in_export=True),
    _cat("profiles", "Profiles & settings", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY,
         paths=data_paths.profiles, in_export=True),
    _cat("app_state", "App state & first-run marker", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY,
         paths=data_paths.app_state),
    _cat("overlay_position", "Overlay position", "electron", "configuration",
         "Settings; removed on factory reset (Electron-owned).", _FACTORY,
         paths=data_paths.overlay_position),
    _cat("overlay_appearance", "Overlay appearance", "electron", "configuration",
         "Settings; removed on factory reset (Electron-owned).", _FACTORY,
         paths=data_paths.overlay_appearance),
    _cat("onboarding_consent", "Onboarding consent record", "electron", "configuration",
         "Consent record; removed only on factory reset (Electron-owned).", _FACTORY,
         paths=data_paths.onboarding_consent),
    # Application profiles (Wave 7). The profile BODIES are settings, but the
    # same store holds the pinned map -- which applications this person runs --
    # so it is declared personal rather than configuration. Under-claiming that
    # would defeat the privacy report. No user prose: ids, process names and
    # preset names only.
    _cat("app_profiles", "Application profiles & pins", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.app_profiles, in_export=True, user_text=False),
    # Launcher workflows (Wave 9). Personal rather than configuration: a
    # workflow names the applications this person runs and the folders they
    # keep work in, and the same file holds the run history. user_text because
    # trigger phrases and notification/confirmation messages are prose the user
    # wrote. Run history itself holds status CODES only -- never speech.
    _cat("launcher_workflows", "Launch workflows & run history", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.launcher_workflows, in_export=True, user_text=True),
    # Confirmed application registry (Wave 9). Electron-owned: the main process
    # is the side that can see the desktop. A behavioural fingerprint -- which
    # applications this person has installed and confirmed -- with no prose.
    _cat("application_registry", "Confirmed applications", "electron", "personal",
         "Kept until personal data is cleared (Electron-owned).", _PERSONAL,
         paths=data_paths.application_registry, in_export=True, user_text=False),
    # Controller bindings and Stream Deck configuration (Wave 10). Shapes
    # supplied by the lane that owns those stores and verified against
    # backend/stores/controller_bindings.py before declaring, rather than
    # guessed. Personal rather than configuration for a reason worth keeping:
    # the `devices` map records the physical controllers this person owns,
    # keyed by the device's self-reported product name. That is a hardware
    # fingerprint, not an app setting, so it goes with the personal data.
    # user_text=False is a checked claim, not an assumption — a binding row is
    # a closed action enum, a press/hold mode, a token-and-timing InputBinding
    # document, and a param bounded by normalize_param(); there is no free-text
    # label field anywhere in the file.
    _cat("controller_bindings", "Controller bindings", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.controller_bindings, in_export=True, user_text=False),
    # user_text=True where controller_bindings is False, and the difference is
    # the point: this store holds a Stream Deck KEY TITLE, which is a string
    # the user typed with their own hands ("Ping Priya"). The flag does not
    # mean "prose" -- it means a human reading this file learns something the
    # user wrote, and a deck full of contact-named keys is exactly that. The
    # 80-character bound limits the volume, not the kind.
    _cat("stream_deck_config", "Stream Deck configuration", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         paths=data_paths.stream_deck_config, in_export=True, user_text=True),
    # The model verification cache (hashes keyed by file signature), not the
    # models themselves -- derived metadata a factory reset rebuilds, sitting
    # inside the opt-in models directory. Declared as its own exact file so the
    # agreement test maps it without the models directory swallowing it.
    _cat("model_runtime_metadata", "Model / runtime metadata", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY,
         paths=data_paths.model_runtime_metadata),

    # Opt-in — never removed by a standard wipe (separate 'also delete models').
    _cat("downloaded_models", "Downloaded models", "python", "public",
         "Opt-in only; removed via a separate 'also delete downloaded models' choice.",
         _OPT_IN, paths=data_paths.downloaded_models,
         verify=data_lifecycle.never_wiped_verify(data_paths.downloaded_models)),
]


def build_registry() -> DataRegistry:
    """A fresh registry populated with every category (each is validated)."""
    reg = DataRegistry()
    for category in CATEGORIES:
        reg.register(category)
    return reg


def get_registry() -> DataRegistry:
    """The process-wide registry, populated on first use.

    ``data_registry.REGISTRY`` is the declared home for it; populating it lazily
    here keeps ``data_registry`` free of any dependency on the inventory.
    """
    from data_registry import REGISTRY
    if not len(REGISTRY):
        for category in CATEGORIES:
            REGISTRY.register(category)
    return REGISTRY
