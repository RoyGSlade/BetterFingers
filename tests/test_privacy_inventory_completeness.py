"""E2 -- the privacy inventory covers EVERY artifact the app can write.

The packaged QA pass (ALPHA4_QA.md, D2) found that a factory reset could never
finish on a profile where the app had written ``persona_drafts.json`` (user
written persona text) or ``tts/kokoro_onnx/`` (the downloaded Kokoro voice
files): neither was in the privacy inventory, so the reset's residual sweep
refused to call the install fresh, and neither was in the uninstaller's
"remove my data" allowlist, so that path could not clear the folder either.

The wipe and verify machinery was fine. The inventory was incomplete, and
nothing made an incomplete inventory a test failure. This module does:

* ``WRITTEN_BY_THE_APP`` lists what the backend and the Electron main process
  can create under the data root. It is built from the writers (every
  ``get_user_data_path`` join, every Electron ``userData`` writer), NOT from
  the inventory, so it cannot be satisfied by copying the inventory.
* Every entry must be claimed by a category, removed by the wipe that matches
  its meaning, and be an uninstaller target. A new store that skips any of
  those fails here, not in a QA pass.
* The sources are scanned for every name joined onto the data root, so a new
  writer fails here even if nobody remembers to extend the tables.
* The writers' own path accessors are compared with the declared locations
  (the same discipline as ``test_privacy_report_agreement``).

Electron's ``userData`` is the unified root on a packaged Windows install
(productName "BetterFingers"), so these tests collapse the two into one
directory; that is the topology the factory reset really runs against.
"""

import json
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from backend.privacy import data_categories as dc
from backend.privacy import data_lifecycle as dl
from backend.privacy import data_paths
from backend.privacy import data_registry as dr
import server


ROOT = pathlib.Path(__file__).resolve().parents[1]
INSTALLER_INCLUDE = ROOT / "app/build/installer.nsh"


# --- what the app can write ---------------------------------------------------
#
# relative path under the data root -> the writer that creates it. Directories
# are listed by a file inside them. Opt-in downloads are in their own table
# because a reset keeps them unless the user asks otherwise.

WRITTEN_BY_THE_APP = {
    # Conversation data
    "draft_history.json": "backend/stores/drafts.py DraftStore",
    "draft_history.json.migrated": "backend/stores/drafts.py load_history (rename)",
    "history.db": "backend/stores/history_store.py",
    "history.db-wal": "SQLite sidecar of history.db",
    "history.db-shm": "SQLite sidecar of history.db",
    "history.db-journal": "SQLite sidecar of history.db",
    "recordings/take-1.wav": "backend/stores/recordings.py",
    "recordings/take-1.json": "backend/stores/recordings.py",
    "persona_learning.json": "backend/services/persona_learning.py",
    "persona_learning.json.bak-v1": "backend/config/store_migration.py",
    "contacts.json": "backend/services/contacts.py",
    "contacts.json.corrupt": "backend/config/store_migration.py (quarantine)",
    # Personal data
    "personas.yaml": "backend/llm/llm_engine.py",
    "personas.yaml.bak-v1": "backend/config/store_migration.py",
    "persona_drafts.json": "backend/services/persona_drafts.py",
    "persona_drafts.json.bak-v1": "backend/config/store_migration.py",
    "persona_drafts.json.corrupt": "backend/config/store_migration.py (quarantine)",
    "persona_drafts.json.1760000000.corrupt": "backend/config/store_migration.py (2nd quarantine)",
    "dictionary.json": "backend/stores/dictionary.py",
    "macros.json": "backend/stores/macros.py",
    "user_profile.json": "backend/stores/user_profile_manager.py",
    "voices/cloned_me.wav": "backend/api/routes/tts.py (voice clone upload)",
    "voices/cloned_me.meta.json": "backend/api/routes/tts.py (voice clone upload)",
    "wake_models/hey.npz": "backend/wake/wake_trainer.py",
    "wake_models/imported_models.json": "backend/wake/wake_models.py",
    "audio_privacy_journal.json": "backend/platform/audio_privacy/journal.py",
    "mcp_servers.json": "backend/dev/mcp_client.py",
    "graph.json": "server.py",
    "debug.log": "backend/config/utils.py setup_logging",
    "app_profiles.json": "backend/stores/app_profiles.py",
    "launcher_workflows.json": "backend/services/workflow_store.py",
    "controller_bindings.json": "backend/stores/controller_bindings.py",
    "stream_deck_config.json": "backend/stores/stream_deck_config.py",
    # Settings
    "voice_presets.json": "backend/stores/voice_presets.py",
    "profiles/Default.yaml": "backend/config/utils.py save_profile",
    "profiles/Default.yaml.bak": "backend/config/utils.py save_profile (backup)",
    "config.yaml": "pre-profiles settings; read-only migration source, present on older installs",
    "app_state.yaml": "backend/config/utils.py",
    "app_state.yaml.corrupt": "backend/config/store_migration.py (utils.load_app_state quarantine)",
    ".first_run_complete": "backend/config/utils.py check_first_run",
    # Written by the Electron main process
    "onboarding.json": "app/src/main/onboardingStore.js",
    "application_registry.json": "app/src/main/applicationRegistry.js",
    "overlay-position.json": "app/src/main/windows.js (userData)",
    "overlay-appearance.json": "app/src/main/windows.js (userData)",
    "sidecar_backend_raw.log": "app/src/main/sidecar.js (userData)",
}

# Opt-in downloads: kept by a reset unless the user ticks "also delete
# downloaded models", and removed by the uninstaller's models checkbox.
OPT_IN_DOWNLOADS = {
    "models/model.gguf": "backend/models/model_manager.py",
    "models/model.gguf.part": "backend/models/model_manager.py (resumable download)",
    "models/llama-server.exe": "backend/models/model_manager.py (runtime)",
    "models/clone-runtime/bin/python.exe": "backend/tts/voice_clone_engine.py (runtime)",
    "tts/kokoro_onnx/kokoro-v1.0.onnx": "backend/tts/tts_engine.py (Kokoro model download)",
    "tts/kokoro_onnx/voices-v1.0.bin": "backend/tts/tts_engine.py (Kokoro voice pack download)",
    "tts/kokoro_onnx/kokoro-v1.0.onnx.part": "backend/tts/tts_engine.py (interrupted download)",
    "runtimes/cuda12/cublas/bin/cublas64_12.dll": "backend/stt/cuda_runtime.py (reserved GPU pack location)",
}

# Derived metadata inside the opt-in models directory that a factory reset
# removes while keeping the model blobs (data_paths.model_runtime_metadata).
VERIFY_CACHE = {"models/.verify_cache.json": "backend/models/model_manager.py"}

KEPT_BY_A_DEFAULT_RESET = set(OPT_IN_DOWNLOADS)


# --- harness ------------------------------------------------------------------


@pytest.fixture
def root(isolated_data_root, monkeypatch):
    """The data root, with Electron's userData collapsed onto it (packaged
    Windows: productName "BetterFingers" => %APPDATA%\\BetterFingers)."""
    monkeypatch.setattr(data_paths, "electron_user_data_candidates",
                        lambda: [isolated_data_root])
    monkeypatch.setenv("BETTERFINGERS_LAZY_STARTUP", "1")
    return isolated_data_root


def _write(root, relative):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"PRIVATE {relative}", encoding="utf-8")
    return path


def _seed(root, *tables):
    for table in tables:
        for relative in table:
            _write(root, relative)


def _files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _allowlisted_names():
    text = INSTALLER_INCLUDE.read_text(encoding="utf-8")
    return set(re.findall(r'!insertmacro BfSafeDeleteCanonical "([^"]+)"', text))


def _top(relative):
    return relative.split("/", 1)[0]


# ``<store>.bak-v<N>`` / ``.corrupt`` / ``.<ts>.corrupt`` / ``.migrated`` are swept
# by the macro call for ``<store>`` itself; they are not allowlist entries.
_SIBLING = re.compile(r"^(?P<store>.+?)\.(?:bak-v[0-9]+|corrupt|[0-9]+\.corrupt|corrupt-.+|migrated)$")


def _store_name(relative):
    top = _top(relative)
    match = _SIBLING.match(top)
    return match.group("store") if match else top


# --- the reported defect ------------------------------------------------------


def test_factory_reset_over_everything_the_app_can_write_verifies_clean(root):
    _seed(root, WRITTEN_BY_THE_APP, OPT_IN_DOWNLOADS, VERIFY_CACHE)
    registry = dc.build_registry()

    result = dl.factory_reset(registry)

    assert result["residual_files"] == [], "files no category claims: the reset can never finish"
    assert result["failed"] == []
    assert result["ok"] is True, result
    # Only the opt-in downloads survive a default reset; every other artifact
    # the app writes is gone, including the two that D2 found.
    assert _files(root) == KEPT_BY_A_DEFAULT_RESET
    assert dl.verify_factory_reset(registry)["ok"] is True


def test_factory_reset_that_includes_downloads_leaves_an_empty_data_root(root):
    _seed(root, WRITTEN_BY_THE_APP, OPT_IN_DOWNLOADS, VERIFY_CACHE)

    result = dl.factory_reset(dc.build_registry(), include_models=True)

    assert result["ok"] is True, result
    assert result["models"]["remaining"] == []
    assert sorted(p.name for p in root.iterdir()) == [], "a fresh install has an empty data root"


def test_factory_reset_route_answers_200_and_verified_over_a_fully_written_root(root):
    """The packaged QA symptom: HTTP 500, ok:false, verified:false."""
    _seed(root, WRITTEN_BY_THE_APP, OPT_IN_DOWNLOADS, VERIFY_CACHE)
    with TestClient(server.app) as client:
        response = client.post("/privacy/factory-reset",
                               json={"confirm": server.FACTORY_RESET_CONFIRMATION})
        on_disk = _files(root)
    body = response.json()
    assert response.status_code == 200, body
    assert body["ok"] is True and body["verified"] is True
    assert body["residual_files"] == []
    # Listed inside the app's lifetime: its shutdown may rewrite its own
    # envelopes, which is not what this test is about.
    assert "persona_drafts.json" not in on_disk
    assert set(OPT_IN_DOWNLOADS) <= on_disk, "a default reset must keep the opt-in downloads"


def test_factory_reset_route_with_downloads_removes_them_too(root):
    _seed(root, WRITTEN_BY_THE_APP, OPT_IN_DOWNLOADS, VERIFY_CACHE)
    with TestClient(server.app) as client:
        response = client.post("/privacy/factory-reset",
                               json={"confirm": server.FACTORY_RESET_CONFIRMATION,
                                     "delete_downloaded_models": True})
        on_disk = _files(root)
    body = response.json()
    assert response.status_code == 200, body
    assert body["ok"] is True and body["residual_files"] == []
    assert not [f for f in on_disk if _top(f) in {"persona_drafts.json", "models", "tts", "runtimes"}]


# --- the real writers, not stand-in names --------------------------------------


def test_declared_locations_are_where_the_writers_really_write(root):
    from backend.services import persona_drafts
    from backend.stt import cuda_runtime
    from backend.tts import tts_engine

    persona_drafts.save_draft("True Janitor", {"metadata": {"id": "True Janitor"}})
    draft_file = pathlib.Path(persona_drafts._path())
    assert draft_file.is_file()

    kokoro = pathlib.Path(tts_engine.kokoro_onnx_dir())
    kokoro.mkdir(parents=True)
    voices = kokoro / "voices-v1.0.bin"
    voices.write_bytes(b"\0" * 16)

    runtime = cuda_runtime._pack_root()
    assert runtime is not None
    runtime.mkdir(parents=True)

    registry = dc.build_registry()
    assert dl.category_for_path(registry, draft_file).id == "personas"
    assert dl.category_for_path(registry, voices).id == "downloaded_models"
    assert dl.category_for_path(registry, runtime).id == "downloaded_models"
    assert dl.unmapped_files(registry) == []

    # And it is the real writer's file that the reset removes.
    result = dl.factory_reset(registry)
    assert result["ok"] is True, result
    assert not draft_file.exists()
    assert voices.exists(), "Kokoro voice files are opt-in downloads, kept unless requested"


# --- category wipes -----------------------------------------------------------

PERSONA_DRAFT_FILES = (
    "persona_drafts.json", "persona_drafts.json.bak-v1", "persona_drafts.json.corrupt",
    "persona_drafts.json.1760000000.corrupt",
)


def test_clear_personal_data_removes_persona_drafts_and_their_recovery_copies(root):
    _seed(root, PERSONA_DRAFT_FILES, ["personas.yaml"])
    registry = dc.build_registry()

    result = dl.execute_mode(registry, dr.WIPE_MODE_PERSONAL)

    assert result["categories"]["personas"]["verified"] is True, result["categories"]["personas"]
    for name in (*PERSONA_DRAFT_FILES, "personas.yaml"):
        assert not (root / name).exists(), f"{name} survived 'clear personal data'"


def test_persona_drafts_are_personal_data_not_conversation_data(root):
    """They sit in the same tier as personas.yaml: a conversations wipe keeps
    both, a personal wipe removes both."""
    _seed(root, PERSONA_DRAFT_FILES, ["personas.yaml"])

    dl.execute_mode(dc.build_registry(), dr.WIPE_MODE_CONVERSATIONS)

    for name in (*PERSONA_DRAFT_FILES, "personas.yaml"):
        assert (root / name).exists(), f"{name} was removed by a conversations-only wipe"


def test_a_leftover_persona_draft_fails_verification_of_the_personas_category(root):
    _seed(root, ["persona_drafts.json"])
    verification = dc.build_registry().get("personas").verify()
    assert verification.ok is False
    assert [pathlib.Path(p).name for p in verification.remaining] == ["persona_drafts.json"]


def test_privacy_wipe_route_for_personal_data_removes_persona_drafts(root):
    from backend.services import persona_drafts

    persona_drafts.save_draft("True Janitor", {"metadata": {"id": "True Janitor"}})
    draft_file = pathlib.Path(persona_drafts._path())
    assert draft_file.is_file()
    with TestClient(server.app) as client:
        response = client.post("/privacy/wipe", json={"mode": dr.WIPE_MODE_PERSONAL})
    body = response.json()
    assert response.status_code == 200, body
    assert body["postconditions"]["category_personas_verified"] is True
    assert not draft_file.exists()


def test_the_privacy_export_includes_persona_drafts(root):
    """Persona drafts are the user's own text; portability follows ownership."""
    _seed(root, ["persona_drafts.json"])
    (root / "persona_drafts.json").write_text(json.dumps({"drafts": {"a": {"x": 1}}}), encoding="utf-8")
    exported = server._build_privacy_export()["categories"]["personas"]
    assert str(root / "persona_drafts.json") in (exported["content"] or {})


@pytest.mark.parametrize("mode", [dr.WIPE_MODE_CONVERSATIONS, dr.WIPE_MODE_PERSONAL, dr.WIPE_MODE_FACTORY_RESET])
def test_no_wipe_mode_removes_the_kokoro_voice_files_or_the_gpu_runtime(root, mode):
    """Multi-gigabyte downloads leave only through the explicit opt-in. The
    Kokoro "voices" are a downloaded model, not the user's cloned voices."""
    _seed(root, OPT_IN_DOWNLOADS)
    registry = dc.build_registry()

    result = dl.execute_mode(registry, mode)

    assert result["ok"] is True, result
    # (A wipe may leave empty store envelopes elsewhere; the downloads are what
    # this test is about.)
    downloads_on_disk = {f for f in _files(root) if _top(f) in {"models", "tts", "runtimes"}}
    assert downloads_on_disk == set(OPT_IN_DOWNLOADS)
    assert registry.get("downloaded_models").verify().ok is True


def test_the_downloads_category_names_the_kokoro_and_runtime_folders(root):
    _seed(root, OPT_IN_DOWNLOADS)
    declared = {p.name for p in data_paths.downloaded_models()}
    assert declared == {"models", "tts", "runtimes"}
    category = dc.build_registry().get("downloaded_models")
    assert category.wipe_modes == frozenset(), "downloads must stay opt-in"
    assert category.size() == sum(len(f"PRIVATE {r}") for r in OPT_IN_DOWNLOADS)


def test_a_wipe_of_the_downloads_removes_kokoro_and_runtime_folders(root):
    _seed(root, OPT_IN_DOWNLOADS)
    result = dc.build_registry().get("downloaded_models").wipe()
    assert result.ok is True, result
    assert _files(root) == set()


# --- the residual sweep must not be fooled by a look-alike name -----------------


@pytest.mark.parametrize("name", ["models.old", "models_backup.json", "tts_cache.json", "runtimes.txt"])
def test_an_undeclared_file_beside_a_download_folder_is_still_a_residual(root, name):
    """The sweep excluded anything whose path merely STARTED WITH a retained
    download folder's path, so ``tts_cache.json`` beside ``tts/`` was invisible
    and a reset called itself clean with it on disk."""
    _seed(root, OPT_IN_DOWNLOADS)
    stray = _write(root, name)

    result = dl.factory_reset(dc.build_registry())

    assert result["ok"] is False
    assert str(stray.resolve()) in result["residual_files"]
    assert str(stray.resolve()) in dl.verify_factory_reset(dc.build_registry())["residual_files"]


# --- the writer table is tied to both lists -------------------------------------


def test_every_artifact_the_app_writes_is_claimed_by_a_category(root):
    registry = dc.build_registry()
    _seed(root, WRITTEN_BY_THE_APP, OPT_IN_DOWNLOADS, VERIFY_CACHE)
    unclaimed = []
    for relative in (*WRITTEN_BY_THE_APP, *OPT_IN_DOWNLOADS, *VERIFY_CACHE):
        if dl.category_for_path(registry, root / relative) is None:
            unclaimed.append(relative)
    assert unclaimed == [], f"written by the app but declared by no category: {unclaimed}"
    assert dl.unmapped_files(registry) == []


def test_every_top_level_artifact_the_app_writes_is_an_uninstaller_target(root):
    allowlist = _allowlisted_names()
    missing = sorted({_store_name(r) for r in (*WRITTEN_BY_THE_APP, *OPT_IN_DOWNLOADS, *VERIFY_CACHE)} - allowlist)
    assert missing == [], f"written by the app but not removable by 'remove my data': {missing}"

# --- discovery: the writers themselves are scanned -------------------------------
#
# The tables above are maintained by hand, so on their own they only fail when
# someone remembers to extend them. This scan reads the sources instead: every
# place the backend joins a name onto the data root, and every file the Electron
# main process puts in its user-data folder, must be claimed by a category. A new
# ``os.path.join(get_user_data_path(), "something.json")`` fails here the day it
# is written, which is how persona_drafts.json and tts/ would have been caught.
#
# It is a source scan, so it has blind spots (a name built in a variable, a
# directory made by a third-party library); the tables and the real writers
# above cover what it cannot see.

_PY_WRITER = re.compile(
    r'(?:os\.path\.join\(\s*(?:get_user_data_path\(\)|[\w.]*_data_dir_fn\(\))\s*,'
    r'|Path\(get_user_data_path\(\)\)\s*/)\s*'
    r'(?:"(?P<lit>[^"]+)"|(?P<const>[A-Z][A-Z0-9_]+)\b)'
)
_PY_APPDATA_WRITER = re.compile(r'"BetterFingers"\s*,\s*"(?P<lit>[^"]+)"')
_JS_USERDATA_WRITER = re.compile(r"getPath\('userData'\)\s*,\s*'(?P<lit>[^']+)'")
_JS_FILE_CONSTANT = re.compile(r"^const (?:FILE_NAME|[A-Z_]*FILENAME)\s*=\s*'(?P<lit>[^']+)'", re.M)


# Files the app only READS from the data folder: a user puts them there, no code
# path creates them. They are not declared, so a factory reset reports one as
# residual and the uninstaller leaves it. That is a decision for the owner (declare
# it as personal data, or document it as the user's own file), not an oversight to
# hide in a test: delete an entry here the day it is declared.
USER_SUPPLIED_AND_UNDECLARED = {
    "context_rules.yaml": "backend/llm/llm_engine.py reads %APPDATA%\\BetterFingers\\context_rules.yaml; nothing writes it",
}


def _discovered_top_level_names():
    """``{name: [source file, ...]}`` for everything the sources write directly under
    the data root (or Electron's user-data folder)."""
    found = {}

    def add(name, source):
        found.setdefault(name, []).append(source.relative_to(ROOT).as_posix())

    python_sources = [ROOT / "server.py", *sorted((ROOT / "backend").rglob("*.py"))]
    for source in python_sources:
        if "privacy" in source.parts:  # the declarations themselves
            continue
        text = source.read_text(encoding="utf-8")
        for match in _PY_WRITER.finditer(text):
            name = match.group("lit")
            if name is None:
                constant = re.search(rf'^{match.group("const")}\s*=\s*"([^"]+)"', text, re.M)
                assert constant, f"{source}: cannot resolve {match.group('const')}"
                name = constant.group(1)
            add(name, source)
        for match in _PY_APPDATA_WRITER.finditer(text):
            add(match.group("lit"), source)
    for source in sorted((ROOT / "app/src/main").glob("*.js")):
        text = source.read_text(encoding="utf-8")
        for pattern in (_JS_USERDATA_WRITER, _JS_FILE_CONSTANT):
            for match in pattern.finditer(text):
                add(match.group("lit"), source)
    return found


def test_the_source_scan_finds_the_writers_it_exists_for():
    names = _discovered_top_level_names()
    assert len(names) >= 25, sorted(names)
    assert {
        "persona_drafts.json", "tts", "runtimes", "models", "personas.yaml", "voices",
        "onboarding.json", "application_registry.json", "overlay-position.json",
        "sidecar_backend_raw.log", "user_profile.json", "audio_privacy_journal.json",
        "draft_history.json", "app_state.yaml",
    } <= set(names), sorted(names)


def test_every_name_the_sources_write_under_the_data_root_is_declared(root):
    registry = dc.build_registry()
    undeclared = {}
    discovered = _discovered_top_level_names()
    assert set(USER_SUPPLIED_AND_UNDECLARED) <= set(discovered), (
        "a USER_SUPPLIED_AND_UNDECLARED entry is no longer found in the sources; delete it"
    )
    for name, sources in sorted(discovered.items()):
        if name in USER_SUPPLIED_AND_UNDECLARED:
            continue
        # Seeded as a plain file: a declared directory is matched by path
        # equality, so this works for files and folders alike.
        _write(root, name)
        if dl.category_for_path(registry, root / name) is None:
            undeclared[name] = sorted(set(sources))
    assert undeclared == {}, (
        "written under the data root but declared by no privacy category "
        f"(backend/privacy/data_paths.py), so a factory reset cannot finish: {undeclared}"
    )
