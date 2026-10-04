"""Recordings and searchable-history routes lifted out of server.py (R4): the four
``/recordings`` routes (list, retranscribe, delete one, delete all) and the three
``/history`` routes (search, recent, clear).

Recordings are raw user audio. Every route that takes a recording id validates it
with ``recordings.is_valid_rec_id`` BEFORE touching disk (a recording id becomes a
filename, so anything path-shaped is refused with a 400); that guard moved
verbatim and must stay in front of ``load_recording_audio`` / ``delete_recording``.
None of these routes returns a file: the audio itself is never served over HTTP,
only listed, re-transcribed server-side, or deleted.

Same strangler shape as dev.py and settings.py: ``server`` stays the owner of all
state and helpers (the ``recordings`` and ``history_store`` modules, and
``process_recording_result``, which the dictation pipeline also uses) and is
imported lazily inside each handler (``import server as s``), because server.py
imports this module near the end of its own load and a top-level ``import
server`` here would be a partially initialized circular import. Every server name
is read as ``s.<name>`` at call time, so ``patch.object(server, ...)`` in tests
still lands. Registered via ``app.include_router`` at the end of server.py.
"""
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

router = APIRouter()


@router.get("/recordings")
async def list_recordings_endpoint():
    import server as s

    return {"ok": True, "recordings": s.recordings.list_recordings()}


@router.post("/recordings/{rec_id}/retranscribe")
async def retranscribe_recording(rec_id: str):
    import server as s

    # A recording id becomes a filename; reject anything path-shaped (§10).
    if not s.recordings.is_valid_rec_id(rec_id):
        raise HTTPException(status_code=400, detail="Invalid recording id.")
    import numpy as np
    from backend.audio.recorder import RecordingResult

    audio, sample_rate = s.recordings.load_recording_audio(rec_id)
    if audio is None:
        raise HTTPException(status_code=404, detail="Recording not found.")

    audio = np.asarray(audio, dtype=np.float32)
    rr = RecordingResult(
        audio_data=audio,
        sample_rate=int(sample_rate or 16000),
        duration_seconds=len(audio) / float(sample_rate or 16000),
        frame_count=0,
        sample_count=int(audio.size),
        max_amplitude=float(np.max(np.abs(audio))) if audio.size else 0.0,
        rms_amplitude=float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0,
        stop_reason="recovery",
    )
    draft = await run_in_threadpool(s.process_recording_result, rr)
    if draft is None:
        raise HTTPException(status_code=409, detail="A dictation is already processing; try again shortly.")
    return {"ok": True, "draft": draft}


@router.delete("/recordings/{rec_id}")
async def delete_recording_endpoint(rec_id: str):
    import server as s

    if not s.recordings.is_valid_rec_id(rec_id):
        raise HTTPException(status_code=400, detail="Invalid recording id.")
    removed = s.recordings.delete_recording(rec_id)
    return {"ok": True, "removed": removed}


@router.delete("/recordings")
async def clear_recordings_endpoint():
    import server as s

    count = s.recordings.clear_recordings()
    return {"ok": True, "cleared": count}


@router.get("/history/search")
async def history_search(q: str = "", limit: int = 50):
    import server as s

    limit = max(1, min(200, int(limit or 50)))
    results = s.history_store.search(q, limit=limit)
    return {"ok": True, "query": q, "count": len(results), "results": results}


@router.get("/history")
async def history_recent(limit: int = 50):
    import server as s

    limit = max(1, min(200, int(limit or 50)))
    results = s.history_store.recent(limit=limit)
    return {"ok": True, "count": len(results), "total": s.history_store.count(), "results": results}


@router.delete("/history")
async def history_clear():
    import server as s

    ok = s.history_store.clear()
    if not ok:
        raise HTTPException(status_code=500, detail="Could not clear history.")
    return {"ok": ok, "message": "Searchable history cleared." if ok else "Could not clear history."}
