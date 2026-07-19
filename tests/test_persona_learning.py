"""Persona example learning store tests (F2.6).

Pure-Python, no FastAPI/model/server involved. Every store is pointed at a
pytest tmp_path so nothing ever touches the real user profile.
"""

import json

import pytest

from backend.services.persona_learning import (
    DEFAULT_CAP,
    PersonaLearningStore,
    _compute_id,
)
from store_migration import write_atomic


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "persona_learning.json")


@pytest.fixture
def store(store_path):
    return PersonaLearningStore(path=store_path)


# --- consent gating ----------------------------------------------------------


def test_add_without_consent_is_rejected(store):
    result = store.add_example("Coach", "raw text", "polished text")
    assert result["ok"] is False
    assert result["error"] == "consent_required"
    assert store.list_examples("Coach") == []


def test_add_with_false_consent_is_rejected(store):
    result = store.add_example("Coach", "raw text", "polished text", consent=False)
    assert result["ok"] is False
    assert result["error"] == "consent_required"
    assert store.list_examples("Coach") == []


def test_add_with_true_consent_succeeds(store):
    result = store.add_example("Coach", "raw text", "polished text", consent=True)
    assert result["ok"] is True
    assert result["duplicate"] is False
    assert result["id"]


# --- add / list --------------------------------------------------------------


def test_add_then_list_returns_stored_example(store):
    store.add_example("Coach", "  hey can u send this  ", "Could you send this?", consent=True)
    examples = store.list_examples("Coach")
    assert len(examples) == 1
    assert examples[0]["raw"] == "hey can u send this"
    assert examples[0]["out"] == "Could you send this?"
    assert "id" in examples[0] and "created_at" in examples[0]


def test_list_examples_returns_copies_not_live_refs(store):
    store.add_example("Coach", "raw", "out", consent=True)
    examples = store.list_examples("Coach")
    examples[0]["raw"] = "tampered"
    assert store.list_examples("Coach")[0]["raw"] == "raw"


def test_list_examples_unknown_persona_is_empty(store):
    assert store.list_examples("Nobody") == []


def test_list_personas_only_names_with_examples(store):
    store.add_example("Coach", "raw", "out", consent=True)
    assert store.list_personas() == ["Coach"]
    store.clear_persona("Coach")
    assert store.list_personas() == []


def test_to_few_shot_matches_persona_schema_shape(store):
    store.add_example("Coach", "raw", "out", consent=True)
    assert store.to_few_shot("Coach") == [{"raw": "raw", "out": "out"}]


# --- duplicate / canonical dedupe --------------------------------------------


def test_duplicate_exact_content_is_recognized(store):
    first = store.add_example("Coach", "raw", "out", consent=True)
    second = store.add_example("Coach", "raw", "out", consent=True)
    assert second["ok"] is True
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(store.list_examples("Coach")) == 1


def test_duplicate_detection_is_whitespace_canonical(store):
    first = store.add_example("Coach", "hello   world", "Hello, world.", consent=True)
    second = store.add_example("Coach", "  hello world  ", "Hello, world.", consent=True)
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert len(store.list_examples("Coach")) == 1


def test_compute_id_is_deterministic_across_calls():
    assert _compute_id("raw", "out") == _compute_id("raw", "out")
    assert _compute_id("a  b", "out") == _compute_id("a b", "out")
    assert _compute_id("raw", "out") != _compute_id("raw", "different out")


# --- overflow / eviction ------------------------------------------------------


def test_overflow_evicts_oldest_first(store_path):
    store = PersonaLearningStore(path=store_path, cap=3)
    ids = []
    for i in range(3):
        result = store.add_example("Coach", f"raw {i}", f"out {i}", consent=True)
        ids.append(result["id"])
    assert [e["id"] for e in store.list_examples("Coach")] == ids

    fourth = store.add_example("Coach", "raw 3", "out 3", consent=True)
    assert fourth["evicted_id"] == ids[0]
    remaining_ids = [e["id"] for e in store.list_examples("Coach")]
    assert remaining_ids == ids[1:] + [fourth["id"]]
    assert len(remaining_ids) == 3


def test_cap_is_configurable(store_path):
    store = PersonaLearningStore(path=store_path, cap=1)
    store.add_example("Coach", "raw 0", "out 0", consent=True)
    second = store.add_example("Coach", "raw 1", "out 1", consent=True)
    assert second["evicted_id"] is not None
    assert len(store.list_examples("Coach")) == 1


def test_default_cap_matches_constant(store):
    assert store.cap == DEFAULT_CAP


# --- deletion / reload ---------------------------------------------------------


def test_delete_example_removes_it(store):
    added = store.add_example("Coach", "raw", "out", consent=True)
    result = store.delete_example("Coach", added["id"])
    assert result == {"ok": True, "deleted": True}
    assert store.list_examples("Coach") == []


def test_delete_unknown_example_is_a_no_op(store):
    store.add_example("Coach", "raw", "out", consent=True)
    result = store.delete_example("Coach", "does-not-exist")
    assert result == {"ok": True, "deleted": False}
    assert len(store.list_examples("Coach")) == 1


def test_deletion_persists_across_new_store_instance(store_path):
    store = PersonaLearningStore(path=store_path)
    added = store.add_example("Coach", "raw", "out", consent=True)
    store.delete_example("Coach", added["id"])

    reloaded = PersonaLearningStore(path=store_path)
    assert reloaded.list_examples("Coach") == []


def test_add_persists_across_new_store_instance(store_path):
    store = PersonaLearningStore(path=store_path)
    store.add_example("Coach", "raw", "out", consent=True)

    reloaded = PersonaLearningStore(path=store_path)
    assert len(reloaded.list_examples("Coach")) == 1


# --- atomic-write failure -----------------------------------------------------


def test_write_failure_leaves_prior_state_intact_and_reports_error(store, store_path, monkeypatch):
    store.add_example("Coach", "raw", "out", consent=True)
    before = json.loads(open(store_path, encoding="utf-8").read())

    def boom(path, text, encoding="utf-8"):
        raise OSError("disk full")

    monkeypatch.setattr("backend.services.persona_learning.write_atomic", boom)
    result = store.add_example("Coach", "second raw", "second out", consent=True)

    assert result["ok"] is False
    assert result["error"] == "write_failed"
    after = json.loads(open(store_path, encoding="utf-8").read())
    assert after == before


# --- legacy migration ----------------------------------------------------------


def test_legacy_v1_flat_list_migrates_on_load(store_path):
    legacy = {
        "schema_version": 1,
        "personas": {
            "Coach": [{"raw": "hey", "out": "Hello."}],
            "Ghost": [{"raw": "yo", "out": "Greetings."}],
        },
    }
    write_atomic(store_path, json.dumps(legacy))

    store = PersonaLearningStore(path=store_path)
    coach_examples = store.list_examples("Coach")
    assert len(coach_examples) == 1
    assert coach_examples[0]["raw"] == "hey"
    assert coach_examples[0]["out"] == "Hello."
    assert coach_examples[0]["id"] == _compute_id("hey", "Hello.")
    assert sorted(store.list_personas()) == ["Coach", "Ghost"]


def test_legacy_migration_still_requires_consent_for_new_adds(store_path):
    legacy = {
        "schema_version": 1,
        "personas": {"Coach": [{"raw": "hey", "out": "Hello."}]},
    }
    write_atomic(store_path, json.dumps(legacy))

    store = PersonaLearningStore(path=store_path)
    result = store.add_example("Coach", "new raw", "new out")
    assert result["ok"] is False
    assert result["error"] == "consent_required"
    assert len(store.list_examples("Coach")) == 1


def test_missing_file_starts_empty(store):
    assert store.list_personas() == []
    assert store.list_examples("Anyone") == []


# --- malformed data ------------------------------------------------------------


def test_malformed_examples_are_dropped_not_raised(store_path):
    malformed = {
        "schema_version": 2,
        "personas": {
            "Coach": {"examples": [
                {"raw": "good raw", "out": "good out"},
                {"raw": "", "out": "missing raw dropped"},
                {"raw": "missing out dropped", "out": ""},
                "not-a-dict",
            ]},
            "": {"examples": [{"raw": "a", "out": "b"}]},
            "BadShape": "not-a-dict-or-list",
            123: {"examples": [{"raw": "x", "out": "y"}]},
        },
    }
    write_atomic(store_path, json.dumps(malformed))

    store = PersonaLearningStore(path=store_path)
    coach_examples = store.list_examples("Coach")
    assert len(coach_examples) == 1
    assert coach_examples[0]["raw"] == "good raw"
    assert store.list_examples("BadShape") == []
    assert "" not in store.list_personas()


def test_corrupt_json_file_is_quarantined_not_crashed(store_path):
    with open(store_path, "w", encoding="utf-8") as fh:
        fh.write("{not valid json at all")

    store = PersonaLearningStore(path=store_path)
    assert store.list_personas() == []
    # Adding still works after quarantine-and-start-fresh.
    result = store.add_example("Coach", "raw", "out", consent=True)
    assert result["ok"] is True


def test_duplicate_ids_in_examples_list_are_deduped_on_load(store_path):
    data = {
        "schema_version": 2,
        "personas": {"Coach": {"examples": [
            {"id": "dup", "raw": "raw", "out": "out"},
            {"id": "dup", "raw": "raw", "out": "out"},
        ]}},
    }
    write_atomic(store_path, json.dumps(data))
    store = PersonaLearningStore(path=store_path)
    assert len(store.list_examples("Coach")) == 1


# --- privacy clear -------------------------------------------------------------


def test_clear_persona_removes_only_that_personas_examples(store):
    store.add_example("Coach", "raw", "out", consent=True)
    store.add_example("Ghost", "raw2", "out2", consent=True)

    result = store.clear_persona("Coach")
    assert result == {"ok": True, "cleared": True}
    assert store.list_examples("Coach") == []
    assert len(store.list_examples("Ghost")) == 1


def test_clear_persona_unknown_reports_not_cleared(store):
    result = store.clear_persona("Nobody")
    assert result == {"ok": True, "cleared": False}


def test_clear_persona_is_reversible_new_consent_recreates_entry(store):
    store.add_example("Coach", "raw", "out", consent=True)
    store.clear_persona("Coach")
    result = store.add_example("Coach", "new raw", "new out", consent=True)
    assert result["ok"] is True
    assert len(store.list_examples("Coach")) == 1


def test_clear_all_removes_every_persona(store):
    store.add_example("Coach", "raw", "out", consent=True)
    store.add_example("Ghost", "raw2", "out2", consent=True)

    result = store.clear_all()
    assert result == {"ok": True}
    assert store.list_personas() == []
    assert store.list_examples("Coach") == []
    assert store.list_examples("Ghost") == []


# --- deterministic ids / order --------------------------------------------------


def test_ids_are_stable_across_separate_store_instances(store_path):
    a = PersonaLearningStore(path=store_path)
    result = a.add_example("Coach", "raw", "out", consent=True)

    b = PersonaLearningStore(path=store_path)
    assert b.list_examples("Coach")[0]["id"] == result["id"]


def test_insertion_order_is_preserved(store):
    for i in range(5):
        store.add_example("Coach", f"raw {i}", f"out {i}", consent=True)
    raws = [e["raw"] for e in store.list_examples("Coach")]
    assert raws == [f"raw {i}" for i in range(5)]


def test_get_example_finds_by_id(store):
    added = store.add_example("Coach", "raw", "out", consent=True)
    found = store.get_example("Coach", added["id"])
    assert found is not None
    assert found["raw"] == "raw"
    assert store.get_example("Coach", "missing-id") is None


# --- invalid inputs --------------------------------------------------------------


def test_empty_persona_name_rejected(store):
    result = store.add_example("   ", "raw", "out", consent=True)
    assert result["ok"] is False
    assert result["error"] == "invalid_persona_name"


def test_empty_raw_or_out_rejected(store):
    assert store.add_example("Coach", "", "out", consent=True)["error"] == "empty_example"
    assert store.add_example("Coach", "raw", "  ", consent=True)["error"] == "empty_example"
