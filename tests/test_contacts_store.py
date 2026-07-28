"""Contact store tests (Stage 11a).

Pure-Python, no FastAPI/model/server involved. Every store is pointed at a
pytest tmp_path so nothing ever touches the real user profile.

The tests that matter most here are not the CRUD ones. They are the boundary
ones: that routing details cannot be stored, that a name is never turned into an
id, and that nothing about a contact reaches the model except the prose the user
wrote. Those encode ``ACCOMPLISH.md`` §3 rule 2 in a form that fails CI rather
than in a form somebody has to remember.
"""

import json

import pytest

from backend.services.contacts import (
    CONTACT_FIELDS,
    EDITABLE_FIELDS,
    ContactStore,
    audience_block,
    new_contact_id,
    sanitize_contact,
)
from store_migration import write_atomic


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "contacts.json")


@pytest.fixture
def store(store_path):
    return ContactStore(path=store_path)


# --- the rule-2 boundary -----------------------------------------------------


def test_routing_details_cannot_be_stored(store):
    """No phone, email, or handle. The app never sends anything anywhere on its
    own, so storing a way to reach someone would be collecting data it has no
    use for -- design doc section 3."""
    result = store.create({
        "name": "Sam",
        "email": "sam@example.com",
        "phone": "+1 555 0100",
        "discord": "sam#0001",
        "address": "12 Somewhere St",
    })
    assert result["ok"] is True
    contact = result["contact"]
    for banned in ("email", "phone", "discord", "address"):
        assert banned not in contact
    # Reported, not silently swallowed: a caller that tried gets told.
    assert result["dropped_fields"] == ["address", "discord", "email", "phone"]


def test_stored_record_has_exactly_the_documented_fields(store):
    result = store.create({"name": "Sam", "relationship": "manager"})
    assert set(result["contact"]) == set(CONTACT_FIELDS)


def test_id_is_never_derived_from_the_name(store):
    """Two people can share a name, and a name-derived id would leak the name
    into every log line and URL that carries it."""
    first = store.create({"name": "Sam"})["contact"]
    second = store.create({"name": "Sam"})["contact"]
    assert first["id"] != second["id"]
    assert "sam" not in first["id"].lower()


def test_new_contact_id_is_unique_per_call():
    assert len({new_contact_id() for _ in range(200)}) == 200


def test_audience_block_withholds_the_name_and_id(store):
    """A rewrite does not need to know WHO someone is to sound right for them,
    and a name in the prompt is a name in every log and cache the model layer
    keeps."""
    contact = store.create({
        "name": "Priya Raman",
        "relationship": "my manager",
        "tone_guidance": "Direct, no filler.",
        "notes": "Prefers numbers spelled out.",
    })["contact"]

    block = audience_block(contact)
    assert "Priya" not in block
    assert "Raman" not in block
    assert contact["id"] not in block
    assert "my manager" in block
    assert "Direct, no filler." in block
    assert "Prefers numbers spelled out." in block


def test_audience_block_is_empty_when_there_is_nothing_to_say(store):
    # So callers can treat "no contact" and "an empty contact" identically.
    contact = store.create({"name": "Sam"})["contact"]
    assert audience_block(contact) == ""
    assert audience_block(None) == ""
    assert audience_block({}) == ""


# --- sanitize ----------------------------------------------------------------


def test_sanitize_returns_only_editable_fields():
    fields, dropped = sanitize_contact({"name": " Sam ", "nonsense": 1})
    assert set(fields) == set(EDITABLE_FIELDS)
    assert fields["name"] == "Sam"
    assert dropped == ["nonsense"]


def test_sanitize_does_not_report_store_owned_fields_as_dropped():
    # id/created_at/updated_at are not the caller's to set, but they are also
    # not user data being thrown away -- reporting them would cry wolf.
    _fields, dropped = sanitize_contact({"name": "Sam", "id": "x", "created_at": "y"})
    assert dropped == []


def test_no_preferred_persona_is_null_not_empty_string():
    # One value for "none", not two that every consumer has to treat alike.
    fields, _ = sanitize_contact({"name": "Sam", "preferred_persona": "   "})
    assert fields["preferred_persona"] is None


def test_sanitize_tolerates_non_dict_input():
    assert sanitize_contact(None) == ({}, [])
    assert sanitize_contact("nope") == ({}, [])


def test_long_text_is_truncated_not_rejected():
    fields, _ = sanitize_contact({"name": "S" * 500, "notes": "n" * 10000})
    assert len(fields["name"]) == 120
    assert len(fields["notes"]) == 4000


# --- create / update / delete ------------------------------------------------


def test_a_name_alone_is_enough(store):
    """The friction budget turns on this: the interview is an offer to make a
    contact better, never a gate on having one (design doc section 10)."""
    result = store.create({"name": "Sam"})
    assert result["ok"] is True
    assert result["contact"]["relationship"] == ""
    assert result["contact"]["preferred_persona"] is None


def test_create_without_a_name_is_rejected(store):
    result = store.create({"relationship": "manager"})
    assert result["ok"] is False
    assert result["error"] == "name_required"
    assert store.list_contacts() == []


def test_update_patches_only_the_keys_present(store):
    """The correction flow sends one field at a time; omitting the others must
    not blank them."""
    contact = store.create({
        "name": "Sam", "relationship": "manager", "notes": "keep this",
    })["contact"]

    result = store.update(contact["id"], {"tone_guidance": "warmer"})
    assert result["ok"] is True
    updated = result["contact"]
    assert updated["tone_guidance"] == "warmer"
    assert updated["notes"] == "keep this"
    assert updated["relationship"] == "manager"


def test_update_cannot_blank_the_name(store):
    contact = store.create({"name": "Sam"})["contact"]
    result = store.update(contact["id"], {"name": "  "})
    assert result["ok"] is False
    assert result["error"] == "name_required"
    # ...and the stored record is untouched, because the guard runs before the write.
    assert store.get(contact["id"])["name"] == "Sam"


def test_update_touches_updated_at_but_not_created_at(store):
    contact = store.create({"name": "Sam"})["contact"]
    updated = store.update(contact["id"], {"notes": "new"})["contact"]
    assert updated["created_at"] == contact["created_at"]
    assert updated["updated_at"] >= contact["updated_at"]


def test_update_of_a_missing_contact_reports_not_found(store):
    assert store.update("nope", {"notes": "x"})["error"] == "not_found"


def test_delete_is_idempotent(store):
    contact = store.create({"name": "Sam"})["contact"]
    assert store.delete(contact["id"]) == {"ok": True, "deleted": True}
    assert store.delete(contact["id"]) == {"ok": True, "deleted": False}
    assert store.get(contact["id"]) is None


# --- cap ---------------------------------------------------------------------


def test_reaching_the_cap_is_an_error_not_an_eviction(store_path):
    """Contacts are authored, not derived. Deleting someone's record to make
    room for another is not a tradeoff this store gets to make on its own."""
    store = ContactStore(path=store_path, cap=2)
    first = store.create({"name": "A"})["contact"]
    store.create({"name": "B"})

    result = store.create({"name": "C"})
    assert result["ok"] is False
    assert result["error"] == "cap_reached"
    assert store.get(first["id"]) is not None
    assert [c["name"] for c in store.list_contacts()] == ["A", "B"]


# --- persistence -------------------------------------------------------------


def test_contacts_survive_a_new_store_instance(store_path):
    ContactStore(path=store_path).create({"name": "Sam", "notes": "hi"})
    assert [c["name"] for c in ContactStore(path=store_path).list_contacts()] == ["Sam"]


def test_list_is_sorted_case_insensitively(store):
    for name in ("zoe", "Alice", "bob"):
        store.create({"name": name})
    assert [c["name"] for c in store.list_contacts()] == ["Alice", "bob", "zoe"]


def test_a_missing_file_reads_as_empty(store):
    assert store.list_contacts() == []
    assert store.count() == 0


def test_unusable_records_are_dropped_rather_than_taking_the_store_down(store_path):
    """A record with no id cannot be addressed and one with no name cannot be
    chosen. A hand-edited file should degrade, not fail to load."""
    write_atomic(store_path, json.dumps({
        "schema_version": 1,
        "contacts": {
            "good": {"id": "good", "name": "Sam"},
            "no-name": {"id": "no-name", "name": ""},
            "no-id": {"name": "Ghost"},
            "not-a-dict": "nope",
        },
    }))
    contacts = ContactStore(path=store_path).list_contacts()
    assert [c["name"] for c in contacts] == ["Sam"]


def test_a_list_shaped_file_still_loads(store_path):
    write_atomic(store_path, json.dumps({
        "schema_version": 1,
        "contacts": [{"id": "a", "name": "Sam"}],
    }))
    assert [c["name"] for c in ContactStore(path=store_path).list_contacts()] == ["Sam"]


def test_reads_return_copies(store):
    contact = store.create({"name": "Sam"})["contact"]
    fetched = store.get(contact["id"])
    fetched["name"] = "Mutated"
    assert store.get(contact["id"])["name"] == "Sam"

    listed = store.list_contacts()
    listed[0]["notes"] = "mutated"
    assert store.list_contacts()[0]["notes"] == ""


# --- privacy -----------------------------------------------------------------


def test_clear_all_empties_the_store(store):
    """A contact list that survived "delete my data" would be a breach of the
    product's central promise."""
    store.create({"name": "Sam"})
    store.create({"name": "Priya", "notes": "sensitive"})

    assert store.clear_all() == {"ok": True}
    assert store.list_contacts() == []


def test_clear_all_leaves_no_user_text_on_disk(store, store_path):
    # The file is rewritten, not just logically emptied -- otherwise the wipe
    # would leave the notes readable to anyone with the profile directory.
    store.create({"name": "Priya", "notes": "distinctive-secret-string"})
    store.clear_all()
    assert "distinctive-secret-string" not in open(store_path, encoding="utf-8").read()
