from unittest.mock import patch

from fastapi.testclient import TestClient

import server


def test_editor_route_migrates_without_overwriting_legacy_prompt():
    legacy = {"prompt": "Be concise and warm.", "confirmed_revision": 1}
    with patch("backend.api.routes.personas.persona_service.get_persona", return_value=legacy), patch(
        "backend.api.routes.personas.persona_drafts.get_draft", return_value=None
    ):
        response = TestClient(server.app).get("/personas/Legacy/editor")
    assert response.status_code == 200
    body = response.json()
    assert body["legacy_prompt"] == legacy["prompt"]
    assert body["migration"]["original_prompt"] == legacy["prompt"]
    assert legacy == {"prompt": "Be concise and warm.", "confirmed_revision": 1}


def test_delete_reports_active_profile_fallback():
    with patch("backend.api.routes.personas.persona_service.delete_persona", return_value=(True, "deleted")), patch.object(
        server, "reconcile_persona_profile_references", return_value=["Default"]
    ):
        response = TestClient(server.app).delete("/personas/Custom")
    assert response.status_code == 200
    assert response.json()["active_fallback"] is True
    assert response.json()["fallback_persona"] == "True Janitor"
