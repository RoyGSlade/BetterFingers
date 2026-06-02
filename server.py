import os
import shutil
import logging
import threading
from datetime import datetime, timezone
from fastapi import FastAPI, UploadFile, File, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from llm_engine import get_engine, get_engine_if_initialized
from transcriber import Transcriber
from hotkey_manager import HotkeyManager
from user_profile_manager import profile_manager
from intent_engine import intent_engine, IntentState
from project_generator import project_generator
from platform_capabilities import get_capabilities
from platform_paths import ensure_app_dirs, get_app_data_dir, get_config_dir
# Configure Logging
from utils import setup_logging
# Will be initialized in __main__ or implicitly if imported (logging lib handles singleton)
# But let's verify we don't double init.
if __name__ != "__main__":
    # If imported by uvicorn (e.g. uvicorn server:app), we need to setup logging.
    setup_logging(level="INFO")

app = FastAPI(title="BetterFingers Sidecar")

# CORS - Allow Electron to communicate
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Instances
transcriber = None
hotkey_manager = None
hotkey_recorder = None
hotkey_manager_started = False
active_websockets = []
draft_queue = []
next_draft_id = 1
draft_lock = threading.Lock()
MAX_DRAFT_HISTORY = 20


def get_voices_dir():
    ensure_app_dirs()
    voices_dir = get_app_data_dir() / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    return voices_dir


def get_graph_path():
    ensure_app_dirs()
    return get_config_dir() / "graph.json"


def is_lazy_startup_enabled():
    return os.getenv("BETTERFINGERS_LAZY_STARTUP") == "1"


def ensure_transcriber_initialized(preload=False):
    global transcriber
    if transcriber is None:
        transcriber = Transcriber(preload=preload)
    elif preload:
        transcriber.ensure_loaded()
    return transcriber


def get_runtime_status_snapshot():
    engine = get_engine_if_initialized()
    engine_ready = False
    if engine is not None:
        try:
            engine_ready = bool(getattr(engine, "_ready", False))
        except Exception:
            engine_ready = False

    return {
        "transcriber_initialized": transcriber is not None,
        "llm_initialized": engine is not None,
        "hotkey_manager_started": hotkey_manager_started,
        "transcriber_loaded": bool(getattr(transcriber, "model", None)),
        "llm_ready": engine_ready,
    }


def start_hotkey_manager():
    global hotkey_manager, hotkey_manager_started, hotkey_recorder

    if hotkey_manager_started and hotkey_manager is not None:
        return hotkey_manager

    if hotkey_manager is not None:
        try:
            hotkey_manager.stop()
        except Exception as exc:
            logging.warning(f"Hotkey Manager stop before restart failed: {exc}")

    from recorder import AudioRecorder

    recorder = AudioRecorder()
    manager = HotkeyManager(
        recorder=recorder,
        on_recording_complete_callback=on_recording_complete,
        on_recording_start_callback=on_recording_start
    )
    manager.start()
    hotkey_manager = manager
    hotkey_recorder = recorder
    hotkey_manager_started = True
    return manager


def stop_hotkey_manager():
    global hotkey_manager, hotkey_manager_started, hotkey_recorder

    if hotkey_manager:
        try:
            hotkey_manager.stop()
        except Exception as exc:
            logging.warning(f"Hotkey Manager stop failed: {exc}")

    hotkey_manager = None
    hotkey_recorder = None
    hotkey_manager_started = False

# Status Broadcaster
async def broadcast_status(status: str, data: dict = None):
    """
    Status: 'listening', 'thinking', 'speaking', 'idle'
    """
    message = {"status": status}
    if data:
        message.update(data)
    
    to_remove = []
    for ws in active_websockets:
        try:
            await ws.send_json(message)
        except Exception:
            to_remove.append(ws)
    
    for ws in to_remove:
        active_websockets.remove(ws)


def broadcast_status_threadsafe(status: str, data: dict = None):
    if loop:
        asyncio.run_coroutine_threadsafe(broadcast_status(status, data), loop)
    else:
        logging.warning("Loop not ready for broadcast")


def create_draft(raw_text, final_text, preset="True Janitor"):
    global next_draft_id

    with draft_lock:
        draft = {
            "id": next_draft_id,
            "raw_text": raw_text or "",
            "final_text": final_text or "",
            "preset": preset,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        next_draft_id += 1
        draft_queue.append(draft)

        if len(draft_queue) > MAX_DRAFT_HISTORY:
            del draft_queue[: len(draft_queue) - MAX_DRAFT_HISTORY]

        return dict(draft)


def get_draft_by_id(draft_id):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                return draft
    return None


def process_recording_result(recording_result):
    preset = "True Janitor"
    try:
        broadcast_status_threadsafe("transcribing")
        trans = ensure_transcriber_initialized(preload=False)
        audio_data = getattr(recording_result, "audio_data", recording_result)
        raw_text = trans.transcribe(audio_data)

        broadcast_status_threadsafe("rewriting")
        engine = get_engine()
        final_text = engine.process_fast_lane(raw_text, preset)

        draft = create_draft(raw_text, final_text, preset=preset)
        broadcast_status_threadsafe(
            "preview_ready",
            {
                "draft_id": draft["id"],
                "raw_text": draft["raw_text"],
                "final_text": draft["final_text"],
            },
        )
        return draft
    except Exception as exc:
        logging.error(f"Recording processing failed: {exc}")
        broadcast_status_threadsafe("error", {"message": str(exc)})
        raise
    finally:
        broadcast_status_threadsafe("idle")


# Hotkey Callbacks
import asyncio
loop = None

def on_recording_start():
    broadcast_status_threadsafe("listening")

def on_recording_complete(recording_result):
    try:
        size = len(recording_result.audio_data)
    except Exception:
        size = len(recording_result) if recording_result is not None else 0
    logging.info(f"CALLBACK: Recording Complete ({size} samples)")

    def _worker():
        try:
            process_recording_result(recording_result)
        except Exception:
            logging.exception("Recording worker failed")

    threading.Thread(target=_worker, daemon=True, name="betterfingers-recording-worker").start()

@app.on_event("startup")
async def startup_event():
    global loop
    loop = asyncio.get_event_loop()
    lazy_startup = is_lazy_startup_enabled()

    try:
        logging.info("Initializing Transcriber...")
        ensure_transcriber_initialized(preload=not lazy_startup)
        logging.info("Transcriber initialized successfully.")
    except Exception as e:
        logging.error(f"Transcriber startup failure: {e}")

    if lazy_startup:
        logging.info("Lazy startup enabled; deferring LLM warmup and Hotkey Manager startup.")
        return

    try:
        logging.info("Warming up LLM Engine...")
        get_engine()
        logging.info("LLM Engine ready.")
    except Exception as e:
        logging.error(f"LLM Engine startup failure: {e}")

    try:
        start_hotkey_manager()
        logging.info("Hotkey Manager started.")
    except Exception as e:
        logging.error(f"Hotkey Manager startup failure: {e}")

@app.on_event("shutdown")
def shutdown_event():
    stop_hotkey_manager()

@app.websocket("/ws/voice_status")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_websockets.append(websocket)
    try:
        while True:
            # Keep alive / listen for client commands (like 'cancel')
            data = await websocket.receive_text()
            # Handle client commands if needed
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception as e:
        logging.error(f"WebSocket Error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)

@app.get("/health")
async def health_check():
    engine_ready = False
    try:
        if is_lazy_startup_enabled():
            engine = get_engine_if_initialized()
            engine_ready = bool(getattr(engine, "_ready", False)) if engine else False
        else:
            engine_ready = get_engine()._ready
    except Exception:
        pass
        
    return {
        "status": "active", 
        "transcriber": transcriber is not None,
        "llm_engine": engine_ready
    }


class RuntimeWarmupRequest(BaseModel):
    stt: bool = False
    llm: bool = False
    hotkeys: bool = False


@app.get("/runtime/status")
async def runtime_status():
    return get_runtime_status_snapshot()


@app.get("/capabilities")
async def capabilities():
    return get_capabilities()


@app.get("/drafts")
async def list_drafts():
    with draft_lock:
        return {"drafts": [dict(draft) for draft in draft_queue]}


@app.get("/drafts/latest")
async def latest_draft():
    with draft_lock:
        if not draft_queue:
            return {"draft": None}
        return {"draft": dict(draft_queue[-1])}


@app.post("/drafts/{draft_id}/accept")
async def accept_draft(draft_id: int):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "accepted"
                return dict(draft)
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/drafts/{draft_id}/decline")
async def decline_draft(draft_id: int):
    with draft_lock:
        for draft in draft_queue:
            if draft["id"] == draft_id:
                draft["status"] = "declined"
                return dict(draft)
    raise HTTPException(status_code=404, detail="Draft not found")


@app.post("/runtime/warmup")
async def runtime_warmup(request: RuntimeWarmupRequest):
    result = {"requested": request.dict()}

    if request.stt:
        try:
            trans = ensure_transcriber_initialized(preload=False)
            result["stt"] = {
                "initialized": trans is not None,
                "loaded": bool(trans and trans.ensure_loaded()),
            }
        except Exception as e:
            logging.error(f"Transcriber warmup failure: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    if request.llm:
        try:
            engine = get_engine()
            result["llm"] = {
                "initialized": engine is not None,
                "ready": bool(getattr(engine, "_ready", False)),
            }
        except Exception as e:
            logging.error(f"LLM warmup failure: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    if request.hotkeys:
        try:
            manager = start_hotkey_manager()
            result["hotkeys"] = {
                "started": manager is not None and hotkey_manager_started,
            }
        except Exception as e:
            logging.error(f"Hotkey warmup failure: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    result.update(get_runtime_status_snapshot())
    return result

class LLMRequest(BaseModel):
    text: str
    preset: str = "True Janitor"
    true_gen: bool = False

@app.post("/llm/process")
async def process_llm(request: LLMRequest):
    try:
        engine = get_engine()
        result = engine.process_fast_lane(
            request.text,
            request.preset,
            true_gen=request.true_gen,
        )
        return {"text": result}
    except Exception as e:
        logging.error(f"LLM Process Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    global transcriber
    if not transcriber:
        raise HTTPException(status_code=503, detail="Transcriber not initialized")
    
    # Save Upload to Temp
    temp_filename = f"temp_{file.filename}"
    try:
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        # Transcribe (pass filename string, supported by faster-whisper wrapper)
        text = transcriber.transcribe(temp_filename)
        return {"text": text}
        
    except Exception as e:
        logging.error(f"Transcription Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Cleanup
        if os.path.exists(temp_filename):
            try:
                os.remove(temp_filename)
            except Exception:
                pass

class TTSRequest(BaseModel):
    text: str
    voice_id: str = "standard_female"
    speed: float = 1.0
    pitch: float = 1.0

@app.post("/tts/speak")
async def tts_speak(request: TTSRequest):
    logging.info(f"TTS Request: '{request.text[:20]}...' | Voice: {request.voice_id} | Speed: {request.speed}x")
    
    # MOCK: Return a static placeholder audio or just verify flow
    # In real impl, we would run Lux inference here
    
    # Verify voice exists
    voice_path = get_voices_dir() / f"{request.voice_id}.npy"
    if request.voice_id.startswith("cloned_") and not os.path.exists(voice_path):
        logging.warning(f"Voice {request.voice_id} not found, using default.")
        
    return {"status": "success", "message": "Audio generated", "mock_url": "/audio/placeholder.wav"}

@app.post("/tts/clone")
async def tts_clone(file: UploadFile = File(...), name: str = "My Voice"):
    # Ensure directory exists
    voices_dir = get_voices_dir()
    
    safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '_', '-')]).strip().replace(" ", "_")
    target_path = voices_dir / f"cloned_{safe_name}.wav" # Saving wav for now, real impl extracts embedding
    
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        logging.info(f"Voice cloned: {safe_name} saved to {target_path}")
        return {"status": "success", "voice_id": f"cloned_{safe_name}", "path": str(target_path)}
    except Exception as e:
        logging.error(f"Cloning failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tts/voices")
async def list_voices():
    voices_dir = get_voices_dir()
    
    cloned = []
    if os.path.exists(voices_dir):
        for f in os.listdir(voices_dir):
            if f.endswith(".wav") or f.endswith(".npy"):
                cloned.append({"id": f.split('.')[0], "name": f.split('.')[0].replace("cloned_", "").replace("_", " ")})
                
    defaults = [
        {"id": "standard_female", "name": "Standard Female (Lux)"},
        {"id": "standard_male", "name": "Standard Male (Lux)"}
    ]
    
    return {"defaults": defaults, "cloned": cloned}

@app.post("/ocr/extract")
async def ocr_extract(file: UploadFile = File(...)):
    try:
        import pytesseract
        from PIL import Image
        
        # Save temp file
        temp_filename = f"temp_ocr_{file.filename}"
        with open(temp_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        try:
            # Attempt OCR
            # Requires Tesseract installed on system and in PATH
            # If on Windows, you might need: pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            text = pytesseract.image_to_string(Image.open(temp_filename))
            return {"text": text.strip()}
        except Exception as e:
            logging.error(f"Tesseract Error: {e}")
            return {"text": "[Error: Tesseract not found or failed. Please ensure Tesseract-OCR is installed.]"}
        finally:
            if os.path.exists(temp_filename):
                os.remove(temp_filename)
                
    except ImportError:
         return {"text": "[Error: pytesseract library not installed on backend.]"}
    except Exception as e:
        logging.error(f"OCR Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class GraphRequest(BaseModel):
    nodes: list
    edges: list

@app.post("/graph/save")
async def save_graph(data: GraphRequest):
    graph_path = get_graph_path()
    try:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(graph_path, "w") as f:
            import json
            json.dump(data.dict(), f)
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Graph Save Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/graph/load")
async def load_graph():
    graph_path = get_graph_path()
    if os.path.exists(graph_path):
        try:
            with open(graph_path, "r") as f:
                import json
                return json.load(f)
        except Exception as e:
             logging.error(f"Graph Load Error: {e}")
             return {"nodes": [], "edges": []}
    return {"nodes": [], "edges": []}

class PlanRequest(BaseModel):
    goal: str

@app.post("/llm/generate_plan")
async def generate_plan(request: PlanRequest):
    engine = get_engine()
    prompt = f"Goal: {request.goal}"
    
    # Generate text
    json_text = engine.process_fast_lane(prompt, preset_name="Plan Generator", true_gen=False, context_rules=False)
    
    # Attempt to clean potential markdown code blocks if the LLM ignores instructions
    clean_text = json_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    
    try:
        import json
        plan = json.loads(clean_text.strip())
        return plan
    except json.JSONDecodeError:
        logging.error(f"LLM produced invalid JSON: {clean_text}")
        return {"title": "Generation Failed", "phases": [{"name": "Error", "tasks": ["The LLM did not return valid JSON.", "Please try again."]}]}
    except Exception as e:
        logging.error(f"Plan Gen Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ExportRequest(BaseModel):
    title: str
    content: str
    plan: dict

@app.post("/project/export")
async def export_project(request: ExportRequest):
    import zipfile
    import io
    from fastapi.responses import StreamingResponse
    
    try:
        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # Add README
            zip_file.writestr("README.md", f"# {request.title}\n\nExported from BetterFingers.")
            
            # Add Content
            zip_file.writestr("document.md", request.content)
            
            # Add Plan
            import json
            zip_file.writestr("plan.json", json.dumps(request.plan, indent=2))
            
        zip_buffer.seek(0)
        
        # In a real app we might return a file download response directly
        # But since we are calling this from fetch in Electron, we might want to save it to a temp path 
        # or return base64. For simplicity, let's return the path to a saved temp file that Electron can "download" or move.
        # Actually, let's stick to the "server saves to desktop" or "downloads folder" approach for this local app.
        
        # For this specific task constraints, let's save to the Desktop for easy verification.
        export_path = os.path.join(os.path.expanduser("~"), "Desktop", f"{request.title.replace(' ', '_')}_Export.zip")
        with open(export_path, "wb") as f:
            f.write(zip_buffer.getvalue())
            
        return {"status": "success", "path": export_path}

    except Exception as e:
        logging.error(f"Export Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/profile")
async def get_profile():
    return profile_manager.get_profile()

@app.post("/profile")
async def save_profile(data: dict):
    success = profile_manager.save_profile(data)
    return {"status": "success" if success else "error"}

@app.get("/intent/state")
async def get_intent_state():
    return {"state": intent_engine.get_state()}

@app.post("/intent/state")
async def set_intent_state(data: dict):
    # expect {"state": "planning"}
    new_state = data.get("state")
    if new_state == "planning":
        intent_engine.set_state(IntentState.PLANNING)
    elif new_state == "executing":
        intent_engine.set_state(IntentState.EXECUTING)
    elif new_state == "idle":
        intent_engine.set_state(IntentState.IDLE)
    return {"state": intent_engine.get_state()}

@app.post("/project/generate")
async def generate_project(data: dict):
    # expect {"plan": {...}, "path": "..."}
    plan = data.get("plan")
    path = data.get("path")
    if not plan or not path:
        raise HTTPException(status_code=400, detail="Missing plan or path")
    
    success, msg = project_generator.generate_project(plan, path)
    return {"status": "success" if success else "error", "message": msg}

if __name__ == "__main__":
    import argparse
    import uvicorn
    
    parser = argparse.ArgumentParser(description="BetterFingers Sidecar Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host IP")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    parser.add_argument("--log-level", type=str, default="INFO", help="Logging level")
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    uvicorn.run(app, host=args.host, port=args.port)
