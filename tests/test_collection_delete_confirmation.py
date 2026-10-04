"""A malformed item URL must not become an unconfirmed collection deletion."""
import sys
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api.routes import drafts, history, personas, message_rescue


@pytest.fixture
def collection_client(monkeypatch):
    calls = []

    def cleared(name, result):
        def run(*args, **kwargs):
            calls.append(name)
            return result
        return run

    queue = [{"id": 1, "raw_text": "keep this draft"}]
    fake = SimpleNamespace(
        recordings=SimpleNamespace(clear_recordings=cleared("recordings", 2),
                                   is_valid_rec_id=lambda value: value == "valid-id",
                                   delete_recording=cleared("recording_item", True)),
        history_store=SimpleNamespace(clear=cleared("history", True)),
        draft_lock=threading.RLock(), draft_queue=queue, draft_recordings={},
        pending_manual_send_ids=[], save_draft_history=cleared("drafts", None),
        broadcast_status_threadsafe=lambda *a: None,
    )
    monkeypatch.setitem(sys.modules, "server", fake)
    monkeypatch.setattr(personas, "_learning_store", lambda: SimpleNamespace(
        clear_persona=cleared("examples", {"ok": True, "cleared": True})))
    app = FastAPI()
    app.include_router(history.router)
    app.include_router(drafts.router)
    app.include_router(personas.router)
    app.include_router(message_rescue.create_message_rescue_router(
        context_session=SimpleNamespace(clear=cleared("context", None)), call_fn=lambda _: ""))
    with TestClient(app, follow_redirects=True) as client:
        yield client, calls, queue


COLLECTIONS = ["/recordings", "/history", "/drafts", "/personas/Coach/examples", "/message-rescue/context"]


@pytest.mark.parametrize("path", COLLECTIONS)
@pytest.mark.parametrize("suffix", ["/", "/."])
def test_malformed_item_url_cannot_clear_collection(collection_client, path, suffix):
    client, calls, queue = collection_client
    response = client.delete(path + suffix)
    assert response.status_code == 400
    assert calls == []
    assert queue == [{"id": 1, "raw_text": "keep this draft"}]


@pytest.mark.parametrize("path", COLLECTIONS)
def test_clear_requires_explicit_true_and_still_works(collection_client, path):
    client, calls, _ = collection_client
    assert client.delete(path).status_code == 400
    assert client.delete(path + "?confirm=false").status_code == 400
    assert calls == []
    assert client.delete(path + "?confirm=true").status_code == 200
    assert len(calls) == 1


def test_valid_per_recording_delete_needs_no_collection_grant(collection_client):
    client, calls, _ = collection_client
    assert client.delete("/recordings/valid-id").status_code == 200
    assert calls == ["recording_item"]
