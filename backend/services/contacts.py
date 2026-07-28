"""Contacts — user-authored records of *how to speak to someone* (Stage 11).

Design: ``docs/CONTACT_WIZARD_DESIGN.md``. Rule boundary: ``ACCOMPLISH.md`` §3
rule 2, "Audience clarification".

A contact is deliberately closer to a persona than to an address book entry. It
describes how to talk to a person, not how to reach them. There is no phone
number, no email, no handle — BetterFingers does not send anything anywhere on
its own, so routing details would be data the app collects and never uses. That
is not an oversight to be corrected later: ``sanitize_contact`` drops unknown
fields and *reports* what it dropped, so a caller that tries to stash an address
here gets told rather than quietly succeeding.

The other boundary that has to hold in code, not just in prose: **the app never
infers a recipient.** Everything in this module takes a contact the user named
and typed. Nothing here reads a window title, an OS address book, or message
history, and nothing should be added that does.

Storage mirrors ``PersonaLearningStore``: one versioned JSON file under the user
profile, loaded lazily, written atomically, every mutation re-reading from disk
first so a failed write leaves the next read seeing the last good state.

One deliberate difference from that store. Persona examples are *derived* data
and evict oldest-first when full; contacts are *authored* data, so hitting the
cap is an error the caller is told about rather than a silent deletion of
something a person wrote. Losing a learned example costs a little quality;
losing a contact someone spent an interview building is losing their work.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from store_migration import load_versioned_store, write_atomic

# Schema history:
#   v1 (current): {"schema_version": 1, "contacts": {id: {...}}}
SCHEMA_VERSION = 1

# Generous, but bounded: the file is read whole on every mutation. Reaching this
# is an error, never an eviction -- see the module docstring.
DEFAULT_CAP = 500

# The complete set of fields a contact carries. Anything else is dropped by
# sanitize_contact. Kept as an explicit tuple rather than inferred from a
# dataclass so that adding a field is a deliberate edit somebody reviews.
CONTACT_FIELDS = (
    "id",
    "name",
    "relationship",
    "notes",
    "tone_guidance",
    "preferred_persona",
    "created_at",
    "updated_at",
)

# Fields the caller may set. id/created_at/updated_at are ours.
EDITABLE_FIELDS = ("name", "relationship", "notes", "tone_guidance", "preferred_persona")

MAX_NAME_LEN = 120
MAX_TEXT_LEN = 4000


def _empty_store() -> dict:
    return {"contacts": {}}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_contact_id() -> str:
    """A fresh opaque id.

    Never derived from the name. Two people can be called "Sam", a person can be
    renamed, and a name-derived id would either collide or leak the name into
    every log line and URL that carries the id.
    """
    return uuid.uuid4().hex


def _clean_text(value, limit: int) -> str:
    text = str(value or "").strip()
    return text[:limit]


def sanitize_contact(payload) -> tuple[dict, list]:
    """Coerce arbitrary input into the editable subset of a contact.

    Returns ``(fields, dropped)``. ``dropped`` names every key that was thrown
    away, so a caller trying to store an email or a phone number finds out
    instead of believing it worked. Nothing is inferred and nothing is
    defaulted from another field.
    """
    if not isinstance(payload, dict):
        return {}, []

    fields = {}
    dropped = []
    for key, value in payload.items():
        if key in EDITABLE_FIELDS:
            continue
        # id/created_at/updated_at are store-owned: not "dropped user data",
        # just not the caller's to set.
        if key not in CONTACT_FIELDS:
            dropped.append(key)

    fields["name"] = _clean_text(payload.get("name"), MAX_NAME_LEN)
    fields["relationship"] = _clean_text(payload.get("relationship"), MAX_NAME_LEN)
    fields["notes"] = _clean_text(payload.get("notes"), MAX_TEXT_LEN)
    fields["tone_guidance"] = _clean_text(payload.get("tone_guidance"), MAX_TEXT_LEN)

    persona = payload.get("preferred_persona")
    persona_s = _clean_text(persona, MAX_NAME_LEN)
    # Explicitly null rather than "" so "no preferred persona" is one value, not
    # two that every consumer has to remember to treat alike.
    fields["preferred_persona"] = persona_s or None

    return fields, sorted(dropped)


def _coerce_contact(raw) -> Optional[dict]:
    """Defensively coerce one stored record, or None if it is unusable.

    A record with no id cannot be addressed and a record with no name cannot be
    chosen, so both are unusable rather than repairable. Anything else missing
    is filled with an empty value -- a hand-edited file should degrade, not
    take the whole store down with it.
    """
    if not isinstance(raw, dict):
        return None
    cid = str(raw.get("id") or "").strip()
    name = _clean_text(raw.get("name"), MAX_NAME_LEN)
    if not cid or not name:
        return None

    persona = _clean_text(raw.get("preferred_persona"), MAX_NAME_LEN)
    return {
        "id": cid,
        "name": name,
        "relationship": _clean_text(raw.get("relationship"), MAX_NAME_LEN),
        "notes": _clean_text(raw.get("notes"), MAX_TEXT_LEN),
        "tone_guidance": _clean_text(raw.get("tone_guidance"), MAX_TEXT_LEN),
        "preferred_persona": persona or None,
        "created_at": str(raw.get("created_at") or "") or _now_iso(),
        "updated_at": str(raw.get("updated_at") or "") or _now_iso(),
    }


def _normalize_store(data) -> dict:
    contacts = {}
    raw_contacts = (data or {}).get("contacts")
    if isinstance(raw_contacts, dict):
        items = raw_contacts.values()
    elif isinstance(raw_contacts, list):
        # Tolerate a list shape from a hand-edited file; keys come from the ids.
        items = raw_contacts
    else:
        items = []
    for item in items:
        contact = _coerce_contact(item)
        if contact:
            contacts[contact["id"]] = contact
    return {"schema_version": SCHEMA_VERSION, "contacts": contacts}


def audience_block(contact) -> str:
    """Render a contact as the prose an audience-aware prompt would carry.

    Lives here rather than in the prompt builder because it is the one place
    that decides what a contact *discloses to the model*, and that is a privacy
    decision. Only the two prose fields go: relationship gives the register,
    notes and tone_guidance give the instructions. The id is meaningless to a
    model, and the name is withheld deliberately -- a rewrite does not need to
    know who someone is to sound right for them, and a name in the prompt is a
    name in every log and cache the model layer keeps.

    Returns '' when there is nothing to say, so callers can treat "no contact"
    and "an empty contact" identically.
    """
    if not isinstance(contact, dict):
        return ""
    parts = []
    relationship = _clean_text(contact.get("relationship"), MAX_NAME_LEN)
    if relationship:
        parts.append(f"Relationship: {relationship}")
    tone = _clean_text(contact.get("tone_guidance"), MAX_TEXT_LEN)
    if tone:
        parts.append(f"How they are spoken to: {tone}")
    notes = _clean_text(contact.get("notes"), MAX_TEXT_LEN)
    if notes:
        parts.append(f"Worth knowing: {notes}")
    return "\n".join(parts)


class ContactStore:
    """User-authored contacts on disk.

    ``path`` should always be passed explicitly in tests -- the default touches
    the real user profile via ``utils.get_user_data_path()``, the
    cross-test-pollution trap this repo already learned to avoid (see
    tests/conftest.py).
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
            self._path = os.path.join(get_user_data_path(), "contacts.json")
        return self._path

    def _load(self) -> dict:
        data, _report = load_versioned_store(
            self.path, SCHEMA_VERSION, {},
            default_factory=_empty_store, parse=json.loads,
        )
        return _normalize_store(data)

    def _save(self, data: dict) -> None:
        write_atomic(self.path, json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False))

    # --- mutation -------------------------------------------------------

    def create(self, payload) -> dict:
        """Create a contact from user-supplied fields.

        A name alone is enough. The design's friction budget turns on that: the
        interview is an offer to make a contact better, never a gate on having
        one, so every other field is optional.
        """
        fields, dropped = sanitize_contact(payload)
        if not fields.get("name"):
            return {"ok": False, "error": "name_required",
                    "message": "A contact needs a name."}

        with self._lock:
            data = self._load()
            if len(data["contacts"]) >= self.cap:
                # Not an eviction: see the module docstring. Deleting someone's
                # authored record to make room for another is not a tradeoff
                # this store gets to make on its own.
                return {"ok": False, "error": "cap_reached",
                        "message": f"You already have {self.cap} contacts. Delete one to add another."}

            now = _now_iso()
            contact = {
                "id": new_contact_id(),
                **fields,
                "created_at": now,
                "updated_at": now,
            }
            data["contacts"][contact["id"]] = contact
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "contact": dict(contact), "dropped_fields": dropped}

    def update(self, contact_id, payload) -> dict:
        """Patch an existing contact.

        Only keys actually present in ``payload`` are touched, so a caller that
        wants to change the tone guidance cannot blank the notes by omission --
        the correction flow in design §9.3 sends one field at a time.
        """
        cid = str(contact_id or "").strip()
        if not cid:
            return {"ok": False, "error": "invalid_id"}
        if not isinstance(payload, dict):
            return {"ok": False, "error": "invalid_payload"}

        fields, dropped = sanitize_contact(payload)
        with self._lock:
            data = self._load()
            contact = data["contacts"].get(cid)
            if not contact:
                return {"ok": False, "error": "not_found"}

            for key in EDITABLE_FIELDS:
                if key in payload:
                    contact[key] = fields[key]

            if not contact["name"]:
                return {"ok": False, "error": "name_required",
                        "message": "A contact needs a name."}

            contact["updated_at"] = _now_iso()
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "contact": dict(contact), "dropped_fields": dropped}

    def delete(self, contact_id) -> dict:
        cid = str(contact_id or "").strip()
        with self._lock:
            data = self._load()
            if cid not in data["contacts"]:
                return {"ok": True, "deleted": False}
            data["contacts"].pop(cid, None)
            try:
                self._save(data)
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True, "deleted": True}

    def clear_all(self) -> dict:
        """Privacy clear. Contacts are user-authored personal data and go with
        the rest of it -- a contact list that survived "delete my data" would be
        a breach of the product's central promise."""
        with self._lock:
            try:
                self._save(_normalize_store(_empty_store()))
            except OSError as exc:
                return {"ok": False, "error": "write_failed", "message": str(exc)}
            return {"ok": True}

    # --- inspection -------------------------------------------------------

    def get(self, contact_id) -> Optional[dict]:
        cid = str(contact_id or "").strip()
        with self._lock:
            contact = self._load()["contacts"].get(cid)
            return dict(contact) if contact else None

    def list_contacts(self) -> list:
        """Every contact, sorted by name then id.

        Sorted rather than insertion-ordered because this is a picker list a
        person scans, and casefold so "alice" and "Alice" do not end up in
        different halves of it.
        """
        with self._lock:
            contacts = self._load()["contacts"].values()
            return sorted(
                (dict(c) for c in contacts),
                key=lambda c: (c["name"].casefold(), c["id"]),
            )

    def count(self) -> int:
        with self._lock:
            return len(self._load()["contacts"])
