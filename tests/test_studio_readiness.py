import studio_readiness


def test_readiness_audit_has_required_shape(monkeypatch):
    monkeypatch.setattr(
        studio_readiness.model_manager,
        "get_model_file_status",
        lambda model_id: {
            "model_id": model_id,
            "path": f"/models/{model_id}.gguf",
            "ok": True,
            "complete": True,
            "readable": True,
            "writable": True,
            "attention": [],
        },
    )
    monkeypatch.setattr(studio_readiness.studio_image_backend, "image_model_installed", lambda: True)
    monkeypatch.setattr(studio_readiness.studio_image_backend, "diffusers_available", lambda: True)
    monkeypatch.setattr(studio_readiness.studio_media_models, "model_installed", lambda _key: True)
    monkeypatch.setattr(studio_readiness.studio_ambience, "stable_audio_tools_installed", lambda: True)
    monkeypatch.setattr(studio_readiness.studio_ambience, "make_ambience_backend", lambda: object())
    monkeypatch.setattr(studio_readiness.studio_music, "ace_tools_installed", lambda: True)
    monkeypatch.setattr(studio_readiness.studio_music, "make_music_backend", lambda: object())

    result = studio_readiness.audit_studio_readiness()

    assert result["ok"] is True
    assert result["ready_for_first_run"] is True
    assert result["errors"] == 0
    ids = {check["id"] for check in result["checks"]}
    assert "llm:gemma-4-12b-q4" in ids
    assert "tools:stable-audio" in ids
    assert "tools:ace-step" in ids


def test_readiness_endpoint(monkeypatch):
    import server
    from fastapi.testclient import TestClient

    monkeypatch.setattr(
        studio_readiness,
        "audit_studio_readiness",
        lambda: {"ok": True, "ready_for_first_run": True, "warnings": 0, "errors": 0, "checks": []},
    )

    response = TestClient(server.app).get("/studio/readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["ready_for_first_run"] is True
