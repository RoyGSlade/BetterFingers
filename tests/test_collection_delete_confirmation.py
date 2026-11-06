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
    def clear_persona(name, guard=None):
        if guard is not None:
            guard([("stored raw", "stored out")])  # the route verifies its ticket here, under the lock
        calls.append("examples")
        return {"ok": True, "cleared": True}

    monkeypatch.setattr(personas, "_learning_store", lambda: SimpleNamespace(clear_persona=clear_persona))
    app = FastAPI()
    app.include_router(history.router)
    app.include_router(drafts.router)
    app.include_router(personas.router)
    app.include_router(message_rescue.create_message_rescue_router(
        context_session=SimpleNamespace(clear=cleared("context", None)), call_fn=lambda _: ""))
    with TestClient(app, follow_redirects=True) as client:
        yield client, calls, queue


# Clearing a persona's learned examples is not a ?confirm=true collection any more (round 4, item 3):
# it needs a native-dialog ticket, covered by the enforced test at the end of this file.
COLLECTIONS = ["/recordings", "/history", "/drafts", "/message-rescue/context"]


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


@pytest.mark.approvals_enforced
@pytest.mark.parametrize("url", ["/personas/Coach/examples", "/personas/Coach/examples/", "/personas/Coach/examples/.",
                                 "/personas/Coach/examples?confirm=true"])
def test_a_persona_learned_clear_needs_a_ticket_whatever_the_url_shape(collection_client, url):
    client, calls, _ = collection_client
    assert client.delete(url).status_code in (400, 403, 404, 405)
    assert calls == []


@pytest.mark.approvals_enforced
def test_a_persona_learned_clear_with_a_ticket_for_the_stored_list_still_works(collection_client):
    from approval_support import sign_ticket

    from backend.services import approvals

    client, calls, _ = collection_client
    ticket = sign_ticket(approvals.PURPOSE_PERSONA_LEARNED_CLEAR, "Coach",
                         approvals.learned_clear_bind("Coach", [("stored raw", "stored out")]))
    assert client.request("DELETE", "/personas/Coach/examples", json={"approval": ticket}).status_code == 200
    assert calls == ["examples"]
