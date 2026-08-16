import os

from backend.services import persona_drafts


def test_draft_store_is_separate_versioned_and_discardable(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    structured = {"schema_version": "1.0", "metadata": {"id": "safe", "display_name": "Safe"}}
    first = persona_drafts.save_draft("safe", structured, base_version=3)
    second = persona_drafts.save_draft("safe", {**structured, "changed": True}, base_version=3)
    assert first["draft_version"] == 1
    assert second["draft_version"] == 2
    assert second["base_confirmed_version"] == 3
    assert persona_drafts.get_draft("safe")["structured"]["changed"] is True
    assert os.path.basename(persona_drafts._path()) == "persona_drafts.json"
    assert persona_drafts.delete_draft("safe") is True
    assert persona_drafts.get_draft("safe") is None
