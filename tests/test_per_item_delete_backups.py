"""Per-item deletion canaries in real migration and pre-existing backup files."""
import json
from pathlib import Path

import pytest
import yaml
from backend.config.store_migration import backup_before_migration
from backend.llm import llm_engine
from backend.services.contacts import ContactStore
from backend.services.persona_learning import PersonaLearningStore, _compute_id
from backend.stores import dictionary, macros, history_store, voice_presets
from backend.stores.drafts import DraftStore
from backend.services.library import LibraryService

CANARY = "H6_DELETE_PRIVATE_CANARY"
SURVIVOR = "H6_SURVIVING_ITEM"


def assert_scrubbed(path):
    assert CANARY not in Path(path).read_text(encoding="utf-8")
    assert SURVIVOR in Path(path).read_text(encoding="utf-8")


def test_persona_delete_scrubs_natural_migration_backup(tmp_path):
    path = tmp_path / "persona_learning.json"
    path.write_text(json.dumps({"schema_version": 1, "personas": {
        "Coach": [{"raw": CANARY, "out": CANARY}],
    }}), encoding="utf-8")
    store = PersonaLearningStore(path=str(path))
    store.add_example("Coach", SURVIVOR, SURVIVOR, consent=True)
    backup = Path(str(path) + ".bak-v1")
    assert CANARY in backup.read_text()
    assert store.delete_example("Coach", _compute_id(CANARY, CANARY))["deleted"]
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_persona_clear_scrubs_natural_migration_backup(tmp_path):
    path = tmp_path / "persona_learning.json"
    path.write_text(json.dumps({"schema_version": 1, "personas": {
        "Coach": [{"raw": CANARY, "out": CANARY}],
        "Friend": [{"raw": SURVIVOR, "out": SURVIVOR}],
    }}), encoding="utf-8")
    store = PersonaLearningStore(path=str(path))
    store.add_example("Friend", "second", "second", consent=True)
    backup = Path(str(path) + ".bak-v1")
    assert CANARY in backup.read_text()
    assert store.clear_persona("Coach")["cleared"]
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_contact_delete_scrubs_existing_version_backup(tmp_path):
    path = tmp_path / "contacts.json"
    store = ContactStore(path=str(path))
    target = store.create({"name": CANARY})["contact"]["id"]
    store.create({"name": SURVIVOR})
    backup = backup_before_migration(path, 1)
    assert store.delete(target)["deleted"]
    assert_scrubbed(path)
    assert_scrubbed(backup)


@pytest.mark.parametrize("kind", ["dictionary", "macro"])
def test_raw_store_delete_scrubs_existing_version_backup(tmp_path, monkeypatch, kind):
    module = dictionary if kind == "dictionary" else macros
    monkeypatch.setattr(module, "get_user_data_path", lambda: str(tmp_path))
    path = tmp_path / ("dictionary.json" if kind == "dictionary" else "macros.json")
    if kind == "dictionary":
        dictionary.add_term(CANARY)
        dictionary.add_term(SURVIVOR)
    else:
        macros.add_macro("private", CANARY)
        macros.add_macro("keep", SURVIVOR)
    backup = backup_before_migration(path, 1)
    if kind == "dictionary":
        dictionary.remove_term(CANARY)
    else:
        macros.remove_macro("private")
    assert_scrubbed(path)
    assert_scrubbed(backup)


@pytest.fixture
def legacy_drafts(tmp_path, monkeypatch):
    monkeypatch.setattr(history_store, "get_user_data_path", lambda: str(tmp_path))
    monkeypatch.setattr(history_store, "_initialized_path", None)
    path = tmp_path / "draft_history.json"
    path.write_text(json.dumps([
        {"id": 1, "raw_text": CANARY, "final_text": CANARY, "status": "pending"},
        {"id": 2, "raw_text": SURVIVOR, "final_text": SURVIVOR, "status": "pending"},
    ]), encoding="utf-8")
    store = DraftStore(lambda: str(tmp_path), history_store, "fake-process")
    store.load_history()
    migrated = Path(str(path) + ".migrated")
    assert CANARY in migrated.read_text()
    store.save_history()
    backup = Path(backup_before_migration(path, 1))
    return store, path, migrated, backup


def test_draft_delete_scrubs_snapshots(legacy_drafts):
    store, path, migrated, backup = legacy_drafts
    assert store.delete_draft(1, save_fn=store.save_history)
    for artifact in (path, migrated, backup):
        assert_scrubbed(artifact)


def test_archive_delete_scrubs_legacy_snapshots(legacy_drafts):
    _, path, migrated, backup = legacy_drafts
    assert history_store.delete_draft(1)
    assert history_store.get(1) is None
    for artifact in (path, migrated, backup):
        assert_scrubbed(artifact)


def test_archive_delete_leaves_no_deleted_text_in_the_database_file(legacy_drafts):
    # Without secure_delete SQLite only marks the page free, so the deleted
    # dictation stays readable in history.db.
    assert history_store.delete_draft(1)
    data = Path(history_store._db_path()).read_bytes()
    assert CANARY.encode() not in data
    assert SURVIVOR.encode() in data


@pytest.fixture
def contact_recovery(tmp_path):
    path = tmp_path / "contacts.json"
    store = ContactStore(path=str(path))
    target = store.create({"name": CANARY})["contact"]["id"]
    store.create({"name": SURVIVOR})
    original = path.read_text(encoding="utf-8")
    backup = Path(backup_before_migration(path, 1))
    return store, target, path, backup, original


def test_failed_backup_scrub_leaves_live_item_retryable(contact_recovery, monkeypatch):
    from backend.config import store_migration
    store, target, path, backup, original = contact_recovery
    real_write = store_migration.write_atomic

    def fail(*args, **kwargs):
        raise OSError("backup locked")

    monkeypatch.setattr(store_migration, "write_atomic", fail)
    assert not store.delete(target)["ok"]
    assert path.read_text() == original
    assert CANARY in backup.read_text()
    monkeypatch.setattr(store_migration, "write_atomic", real_write)
    assert store.delete(target)["deleted"]
    assert_scrubbed(backup)


def test_failed_live_write_preserves_live_recovery_and_survivor_backup(contact_recovery, monkeypatch):
    store, target, path, backup, original = contact_recovery

    def fail(_):
        raise OSError("live file locked")

    monkeypatch.setattr(store, "_save", fail)
    assert not store.delete(target)["ok"]
    assert path.read_text() == original
    assert store.get(target)["name"] == CANARY
    assert_scrubbed(backup)
    assert json.loads(backup.read_text())["schema_version"] == 1


def test_idempotent_contact_delete_repairs_old_backup(contact_recovery):
    store, target, _, backup, original = contact_recovery
    assert store.delete(target)["deleted"]
    backup.write_text(original, encoding="utf-8")
    assert store.delete(target) == {"ok": True, "deleted": False}
    assert_scrubbed(backup)


@pytest.mark.parametrize("future", ["payload", "suffix"])
def test_future_schema_backups_refused_untouched(contact_recovery, future):
    store, target, path, backup, original = contact_recovery
    if future == "payload":
        data = json.loads(original)
        data["schema_version"] = 999
        backup.write_text(json.dumps(data), encoding="utf-8")
    else:
        backup = backup.with_name(path.name + ".bak-v999")
        backup.write_text(original, encoding="utf-8")
    future_bytes = backup.read_bytes()
    assert not store.delete(target)["ok"]
    assert path.read_text() == original
    assert backup.read_bytes() == future_bytes


def test_unrelated_suffix_files_untouched(contact_recovery):
    store, target, path, _, original = contact_recovery
    unrelated = path.with_name(path.name + ".bak-v1.notes")
    unrelated.write_text(original, encoding="utf-8")
    assert store.delete(target)["deleted"]
    assert unrelated.read_text() == original


def test_missing_live_store_never_empties_recoverable_backup(contact_recovery):
    store, target, path, backup, original = contact_recovery
    path.unlink()
    assert not store.delete(target)["ok"]
    assert backup.read_text() == original


def test_idempotent_persona_delete_repairs_old_backup(tmp_path):
    path = tmp_path / "persona_learning.json"
    store = PersonaLearningStore(path=str(path))
    target = store.add_example("Coach", CANARY, CANARY, consent=True)["id"]
    store.add_example("Coach", SURVIVOR, SURVIVOR, consent=True)
    original = path.read_text()
    backup = Path(backup_before_migration(path, 1))
    assert store.delete_example("Coach", target)["deleted"]
    backup.write_text(original, encoding="utf-8")
    assert store.delete_example("Coach", target) == {"ok": True, "deleted": False}
    assert_scrubbed(backup)


def test_persona_delete_cannot_overwrite_future_backup_during_load(tmp_path):
    path = tmp_path / "persona_learning.json"
    path.write_text(json.dumps({"schema_version": 1, "personas": {
        "Coach": [{"raw": CANARY, "out": CANARY}],
    }}), encoding="utf-8")
    backup = Path(str(path) + ".bak-v1")
    backup.write_text(json.dumps({"schema_version": 999, "personas": {"Future": SURVIVOR}}), encoding="utf-8")
    original_live, original_backup = path.read_bytes(), backup.read_bytes()
    result = PersonaLearningStore(path=str(path)).delete_example("Coach", _compute_id(CANARY, CANARY))
    assert not result["ok"]
    assert path.read_bytes() == original_live
    assert backup.read_bytes() == original_backup


@pytest.mark.parametrize("kind", ["dictionary", "macro"])
def test_raw_store_locked_backup_fails_without_live_removal(tmp_path, monkeypatch, kind):
    from backend.config import store_migration
    module = dictionary if kind == "dictionary" else macros
    monkeypatch.setattr(module, "get_user_data_path", lambda: str(tmp_path))
    path = tmp_path / ("dictionary.json" if kind == "dictionary" else "macros.json")
    if kind == "dictionary":
        dictionary.add_term(CANARY)
        dictionary.add_term(SURVIVOR)
    else:
        macros.add_macro("private", CANARY)
        macros.add_macro("keep", SURVIVOR)
    backup = backup_before_migration(path, 1)
    original = path.read_text()
    monkeypatch.setattr(store_migration, "write_atomic", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        dictionary.remove_term(CANARY) if kind == "dictionary" else macros.remove_macro("private")
    assert path.read_text() == original
    assert Path(backup).read_text() == original


def test_idempotent_archive_delete_repairs_remaining_snapshots(legacy_drafts):
    _, path, migrated, backup = legacy_drafts
    original = path.read_text()
    assert history_store.delete_draft(1)
    for artifact in (path, migrated, backup):
        artifact.write_text(original, encoding="utf-8")
    assert history_store.delete_draft(1) is False  # already absent, recovery still repaired
    for artifact in (path, migrated, backup):
        assert_scrubbed(artifact)


def test_draft_scrub_failure_keeps_queue_item_for_retry(legacy_drafts, monkeypatch):
    from backend.stores import draft_artifacts
    store, _, _, _ = legacy_drafts

    def fail(*args, **kwargs):
        raise OSError("backup locked")

    monkeypatch.setattr(draft_artifacts, "write_atomic", fail)
    with pytest.raises(OSError, match="locked"):
        store.delete_draft(1, save_fn=store.save_history)
    assert store.get_draft_by_id(1)["raw_text"] == CANARY
    assert history_store.get(1)["raw_text"] == CANARY


def test_archive_scrub_failure_keeps_db_item_for_retry(legacy_drafts, monkeypatch):
    from backend.stores import draft_artifacts
    _, _, _, _ = legacy_drafts
    monkeypatch.setattr(draft_artifacts, "write_atomic", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    assert history_store.delete_draft(1) is False
    assert history_store.get(1)["raw_text"] == CANARY


def test_library_archive_delete_survives_ordinary_queue_save(legacy_drafts):
    store, path, migrated, backup = legacy_drafts
    service = LibraryService(store, history_store, object(), store.save_history, lambda: set())
    assert service.delete_item("history_entry", 1, confirmed=True)["ok"]
    store.save_history()
    assert history_store.get(1) is None
    assert store.get_draft_by_id(1) is None
    for artifact in (path, migrated, backup):
        assert_scrubbed(artifact)


def test_library_idempotent_delete_repairs_retained_backups(legacy_drafts):
    store, path, migrated, backup = legacy_drafts
    service = LibraryService(store, history_store, object(), store.save_history, lambda: set())
    original = path.read_text()
    assert service.delete_item("draft", 1, confirmed=True)["ok"]
    backup.write_text(original, encoding="utf-8")
    assert service.delete_item("draft", 1, confirmed=True)["already_absent"]
    assert_scrubbed(backup)


def test_library_idempotent_scrub_failure_reports_failure(legacy_drafts, monkeypatch):
    from backend.stores import draft_artifacts
    store, path, _, backup = legacy_drafts
    service = LibraryService(store, history_store, object(), store.save_history, lambda: set())
    original = path.read_text()
    assert service.delete_item("draft", 1, confirmed=True)["ok"]
    backup.write_text(original, encoding="utf-8")
    monkeypatch.setattr(draft_artifacts, "write_atomic", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    result = service.delete_item("draft", 1, confirmed=True)
    assert not result["ok"]
    assert (result["error"], result["http_status"]) == ("write_failed", 500)
    assert CANARY in backup.read_text()


def test_library_archive_absent_queue_only_delete_cannot_resurrect(legacy_drafts):
    store, path, migrated, backup = legacy_drafts
    assert history_store.delete_draft(1)
    service = LibraryService(store, history_store, object(), store.save_history, lambda: set())
    assert service.delete_item("history_entry", 1, confirmed=True)["ok"]
    store.save_history()
    assert store.get_draft_by_id(1) is None
    assert history_store.get(1) is None
    for artifact in (path, migrated, backup):
        assert_scrubbed(artifact)


@pytest.mark.parametrize("confirmed,in_flight", [(True, {1}), (False, set())])
def test_library_queue_only_delete_preserves_confirmation_and_inflight(legacy_drafts, confirmed, in_flight):
    store, _, _, _ = legacy_drafts
    assert history_store.delete_draft(1)
    service = LibraryService(store, history_store, object(), store.save_history, lambda: in_flight)
    assert not service.delete_item("history_entry", 1, confirmed=confirmed)["ok"]
    assert store.get_draft_by_id(1) is not None


def test_library_scrub_failure_reports_failure_without_removing_queue(legacy_drafts, monkeypatch):
    from backend.stores import draft_artifacts
    store, _, _, _ = legacy_drafts
    service = LibraryService(store, history_store, object(), store.save_history, lambda: set())
    monkeypatch.setattr(draft_artifacts, "write_atomic", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    result = service.delete_item("draft", 1, confirmed=True)
    assert not result["ok"]
    assert result["http_status"] == 500
    assert store.get_draft_by_id(1) is not None


# --- Custom LLM personas (personas.yaml, YAML not JSON) -----------------------


@pytest.fixture
def v1_personas(tmp_path, monkeypatch):
    """A real v1 personas.yaml (flat {name: prompt}); not loaded yet, so the
    test decides when the real loader writes the natural .bak-v1."""
    path = tmp_path / "personas.yaml"
    monkeypatch.setattr(llm_engine, "_get_personas_path", lambda: str(path))
    monkeypatch.setattr(llm_engine, "_personas_cache", None)
    monkeypatch.setattr(llm_engine, "_personas_v2_cache", None)
    path.write_text(yaml.safe_dump({"Secret Coach": CANARY, "Keeper": SURVIVOR}), encoding="utf-8")
    return path


def test_custom_persona_delete_scrubs_natural_migration_backup(v1_personas):
    path = v1_personas
    llm_engine.load_personas_v2(force_reload=True)  # the loader writes personas.yaml.bak-v1
    backup = Path(str(path) + ".bak-v1")
    assert CANARY in backup.read_text(encoding="utf-8")
    assert llm_engine.delete_persona("Secret Coach")[0]
    assert_scrubbed(path)
    assert_scrubbed(backup)
    # Still a usable recovery copy: the survivor loads from it as schema v2.
    recovery = yaml.safe_load(backup.read_text(encoding="utf-8"))
    assert recovery["schema_version"] == llm_engine.PERSONA_SCHEMA_VERSION
    assert recovery["personas"]["Keeper"]["prompt"] == SURVIVOR


def test_custom_persona_delete_scrubs_existing_version_backup(tmp_path, monkeypatch):
    path = tmp_path / "personas.yaml"
    monkeypatch.setattr(llm_engine, "_get_personas_path", lambda: str(path))
    monkeypatch.setattr(llm_engine, "_personas_cache", None)
    monkeypatch.setattr(llm_engine, "_personas_v2_cache", None)
    assert llm_engine.upsert_persona("Secret Coach", CANARY)[0]
    assert llm_engine.upsert_persona("Keeper", SURVIVOR)[0]
    backup = backup_before_migration(path, 1)
    assert llm_engine.delete_persona("Secret Coach")[0]
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_failed_persona_backup_scrub_leaves_live_persona_retryable(v1_personas, monkeypatch):
    from backend.config import store_migration
    path = v1_personas
    llm_engine.load_personas_v2(force_reload=True)
    backup = Path(str(path) + ".bak-v1")
    original = path.read_bytes()
    real_write = store_migration.write_atomic

    def fail(*args, **kwargs):
        raise OSError("backup locked")

    monkeypatch.setattr(store_migration, "write_atomic", fail)
    assert not llm_engine.delete_persona("Secret Coach")[0]
    assert path.read_bytes() == original
    assert CANARY in backup.read_text(encoding="utf-8")
    assert llm_engine.get_persona("Secret Coach")["prompt"] == CANARY
    monkeypatch.setattr(store_migration, "write_atomic", real_write)
    assert llm_engine.delete_persona("Secret Coach")[0]
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_idempotent_custom_persona_delete_repairs_old_backup(v1_personas):
    path = v1_personas
    llm_engine.load_personas_v2(force_reload=True)
    backup = Path(str(path) + ".bak-v1")
    original = backup.read_text(encoding="utf-8")
    assert llm_engine.delete_persona("Secret Coach")[0]
    backup.write_text(original, encoding="utf-8")
    assert not llm_engine.delete_persona("Secret Coach")[0]  # already gone, recovery still repaired
    assert_scrubbed(backup)


@pytest.mark.parametrize("bad", ["future_payload", "future_suffix", "corrupt", "not_a_mapping"])
def test_custom_persona_delete_refuses_future_or_corrupt_backups_untouched(v1_personas, bad):
    path = v1_personas
    backup = Path(str(path) + ".bak-v1")
    if bad == "future_payload":
        backup.write_text(yaml.safe_dump({"schema_version": 999, "personas": {"Future": SURVIVOR}}), encoding="utf-8")
    elif bad == "future_suffix":
        backup = path.with_name(path.name + ".bak-v999")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    elif bad == "corrupt":
        backup.write_text("personas: [unterminated\n  - broken: yaml: :::", encoding="utf-8")
    else:
        backup.write_text("just a string, not a persona mapping", encoding="utf-8")
    original_live, original_backup = path.read_bytes(), backup.read_bytes()
    # The v1 live file also makes the loader write .bak-v1; delete must validate
    # first so that write cannot replace a future/unreadable recovery copy.
    assert not llm_engine.delete_persona("Secret Coach")[0]
    assert path.read_bytes() == original_live
    assert backup.read_bytes() == original_backup


def test_custom_persona_delete_leaves_unrelated_suffix_files_untouched(v1_personas):
    path = v1_personas
    llm_engine.load_personas_v2(force_reload=True)
    unrelated = path.with_name(path.name + ".bak-v1.notes")
    unrelated.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    original = unrelated.read_bytes()
    assert llm_engine.delete_persona("Secret Coach")[0]
    assert unrelated.read_bytes() == original


# --- Voice presets (voice_presets.json) ---------------------------------------


@pytest.fixture
def v1_voice_presets(tmp_path, monkeypatch):
    """A real v1 voice_presets.json (no schema_version); not loaded yet."""
    monkeypatch.setattr(voice_presets, "get_user_data_path", lambda: str(tmp_path))
    path = tmp_path / "voice_presets.json"
    path.write_text(json.dumps({"presets": [
        {"name": CANARY, "base": "af_heart"},
        {"name": SURVIVOR, "base": "am_puck"},
    ], "default": CANARY}), encoding="utf-8")
    return path


def test_voice_preset_delete_scrubs_natural_migration_backup(v1_voice_presets):
    path = v1_voice_presets
    voice_presets.get_presets()  # the loader writes voice_presets.json.bak-v1
    backup = Path(str(path) + ".bak-v1")
    assert CANARY in backup.read_text(encoding="utf-8")
    assert [p["name"] for p in voice_presets.delete_preset(CANARY)] == [SURVIVOR]
    assert_scrubbed(path)
    assert_scrubbed(backup)
    recovery = json.loads(backup.read_text(encoding="utf-8"))
    assert recovery["schema_version"] == voice_presets._SCHEMA_VERSION
    assert [p["name"] for p in recovery["presets"]] == [SURVIVOR]
    assert recovery["default"] is None  # the deleted preset was the default


def test_voice_preset_delete_scrubs_existing_version_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(voice_presets, "get_user_data_path", lambda: str(tmp_path))
    path = tmp_path / "voice_presets.json"
    voice_presets.save_preset(CANARY, base="af_heart")
    voice_presets.save_preset(SURVIVOR, base="am_puck")
    backup = backup_before_migration(path, 1)
    voice_presets.delete_preset(CANARY)
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_failed_voice_preset_backup_scrub_leaves_live_preset_retryable(v1_voice_presets, monkeypatch):
    from backend.config import store_migration
    path = v1_voice_presets
    voice_presets.get_presets()
    backup = Path(str(path) + ".bak-v1")
    original = path.read_bytes()
    real_write = store_migration.write_atomic

    def fail(*args, **kwargs):
        raise OSError("backup locked")

    monkeypatch.setattr(store_migration, "write_atomic", fail)
    with pytest.raises(OSError, match="locked"):
        voice_presets.delete_preset(CANARY)
    assert path.read_bytes() == original
    assert CANARY in backup.read_text(encoding="utf-8")
    monkeypatch.setattr(store_migration, "write_atomic", real_write)
    assert [p["name"] for p in voice_presets.delete_preset(CANARY)] == [SURVIVOR]
    assert_scrubbed(path)
    assert_scrubbed(backup)


def test_idempotent_voice_preset_delete_repairs_old_backup(v1_voice_presets):
    path = v1_voice_presets
    voice_presets.get_presets()
    backup = Path(str(path) + ".bak-v1")
    original = backup.read_text(encoding="utf-8")
    voice_presets.delete_preset(CANARY)
    backup.write_text(original, encoding="utf-8")
    voice_presets.delete_preset(CANARY)  # already gone, recovery still repaired
    assert_scrubbed(backup)


@pytest.mark.parametrize("bad", ["future_payload", "future_suffix", "corrupt"])
def test_voice_preset_delete_refuses_future_or_corrupt_backups_untouched(v1_voice_presets, bad):
    path = v1_voice_presets
    backup = Path(str(path) + ".bak-v1")
    if bad == "future_payload":
        backup.write_text(json.dumps({"schema_version": 999, "presets": [{"name": SURVIVOR}]}), encoding="utf-8")
    elif bad == "future_suffix":
        backup = path.with_name(path.name + ".bak-v999")
        backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        backup.write_text("{not json", encoding="utf-8")
    original_live, original_backup = path.read_bytes(), backup.read_bytes()
    # The v1 live file also makes the loader write .bak-v1; delete must validate
    # first so that write cannot replace a future/unreadable recovery copy.
    with pytest.raises(OSError):
        voice_presets.delete_preset(CANARY)
    assert path.read_bytes() == original_live
    assert backup.read_bytes() == original_backup


def test_voice_preset_delete_leaves_unrelated_suffix_files_untouched(v1_voice_presets):
    path = v1_voice_presets
    voice_presets.get_presets()
    unrelated = path.with_name(path.name + ".bak-v1.notes")
    unrelated.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    original = unrelated.read_bytes()
    voice_presets.delete_preset(CANARY)
    assert unrelated.read_bytes() == original
