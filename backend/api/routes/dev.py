"""Dev/prototype routes lifted out of server.py (R2): MCP, LLM fast-lane and plan
generation, graph, intent, project export/generate, and OCR.

These are the prototype surfaces the Electron renderer's ROUTE_ALLOWLIST never
grants. Eleven of the twelve are gated off unless BETTERFINGERS_DEV_ROUTES=1
(QA-SEC-002 / C-2, D-0042); ``/ocr/extract`` was never gated and still is not.
The gate is ``_require_dev_routes`` below, a per-route FastAPI dependency that
defers to ``server._require_dev_routes`` so it is evaluated at REQUEST time (a
test can flip the env var and see both outcomes without reloading anything).

Same strangler shape as wake.py and personas.py: ``server`` stays the owner of
all state and helpers and is imported lazily inside each handler (``import
server as s``), because server.py imports this module near the end of its own
load and a top-level ``import server`` here would be a partially-initialized
circular import. Every server name is read as ``s.<name>`` at call time, so
``patch.object(server, ...)`` in tests still lands. Registered via
``app.include_router`` at the end of server.py.
"""
import logging
import os
import re
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from backend.api.models import ApprovalTicketModel

router = APIRouter()


def _require_dev_routes():
    # Resolved through ``server`` on every request, never captured at import time.
    import server as s

    return s._require_dev_routes()


@router.get("/mcp/status", dependencies=[Depends(_require_dev_routes)])
async def mcp_status():
    import server as s

    return s.mcp_client.status()


@router.get("/mcp/servers", dependencies=[Depends(_require_dev_routes)])
async def mcp_servers():
    import server as s

    return {"ok": True, "servers": s.mcp_client.list_servers()}


@router.get("/mcp/servers/{server_name}/tools", dependencies=[Depends(_require_dev_routes)])
async def mcp_server_tools(server_name: str):
    import server as s

    try:
        return await run_in_threadpool(s.mcp_client.list_tools, server_name)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' is not configured.")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


class McpTrustRequest(BaseModel):
    approval: Optional[ApprovalTicketModel] = None


@router.get("/mcp/servers/{server_name}/trust", dependencies=[Depends(_require_dev_routes)])
async def mcp_server_trust_info(server_name: str):
    """What the "trust on this machine" dialog shows, and the configuration digest its ticket
    must bind (round 3, item 4). Arguments are shown masked."""
    import server as s

    try:
        return s.mcp_client.trust_info(server_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' is not configured.")


@router.post("/mcp/servers/{server_name}/trust", dependencies=[Depends(_require_dev_routes)])
async def mcp_server_trust(server_name: str, request: McpTrustRequest):
    """Mark a server trusted on this machine. Needs an ``mcp.trust`` ticket minted by main after
    the native dialog, bound to the server's CURRENT configuration digest."""
    import server as s
    from backend.services import approvals

    try:
        info = s.mcp_client.trust_info(server_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"MCP server '{server_name}' is not configured.")
    try:
        proof = approvals.verify(
            request.approval.model_dump() if request.approval else None,
            purpose=approvals.PURPOSE_MCP_TRUST,
            subject=server_name,
            bind=approvals.mcp_trust_bind(info["config_sha256"]),
        )
    except approvals.ApprovalError as exc:
        raise HTTPException(status_code=approvals.http_status_for(exc.code), detail=exc.message)
    try:
        return s.mcp_client.trust(server_name, info["config_sha256"], proof)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.delete("/mcp/servers/{server_name}/trust", dependencies=[Depends(_require_dev_routes)])
async def mcp_server_revoke_trust(server_name: str):
    """Withdraw trust. Needs no approval: it only makes things stricter."""
    import server as s

    return s.mcp_client.revoke_trust(server_name)


class LLMRequest(BaseModel):
    text: str
    preset: str = "True Janitor"
    true_gen: bool = False

@router.post("/llm/process", dependencies=[Depends(_require_dev_routes)])
async def process_llm(request: LLMRequest):
    import server as s

    try:
        # Read lease: a concurrent LLM unload/reload/select waits or 409s
        # rather than dropping the runtime mid-completion.
        with s.model_runtime.read_lease("llm"):
            engine = s.get_selected_llm_engine()
            result = await run_in_threadpool(
                engine.process_fast_lane,
                request.text,
                request.preset,
                true_gen=request.true_gen,
            )
        return {"text": result}
    except s.RuntimeBusyError:
        raise HTTPException(status_code=409, detail="LLM runtime is being reconfigured; retry shortly.")
    except Exception as e:
        logging.error(f"LLM Process Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ocr/extract")
async def ocr_extract(file: UploadFile = File(...)):
    import server as s

    # Validate the upload before touching optional OCR dependencies — a
    # malformed/oversized image is rejected even if Tesseract isn't installed.
    # The temp file is always cleaned up in the outer finally.
    tmp_ocr = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
    temp_filename = tmp_ocr.name
    tmp_ocr.close()
    try:
        try:
            s.upload_safety.stream_to_file(file.file, temp_filename, s.upload_safety.MAX_IMAGE_BYTES)
            s.upload_safety.validate_signature(temp_filename, "image")
            s.upload_safety.validate_image(temp_filename)
        except s.upload_safety.UploadTooLarge as exc:
            raise HTTPException(status_code=413, detail=f"Image too large (max {exc.limit} bytes).")
        except s.upload_safety.UploadRejected as exc:
            raise HTTPException(status_code=400, detail=f"Invalid image: {exc}")

        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return {"text": "[Error: pytesseract library not installed on backend.]"}
        try:
            text = pytesseract.image_to_string(Image.open(temp_filename))
            return {"text": text.strip()}
        except Exception as e:
            logging.error(f"Tesseract Error: {e}")
            return {"text": "[Error: Tesseract not found or failed. Please ensure Tesseract-OCR is installed.]"}
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"OCR Endpoint Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        try:
            os.remove(temp_filename)
        except OSError:
            pass

class GraphRequest(BaseModel):
    nodes: list
    edges: list

@router.post("/graph/save", dependencies=[Depends(_require_dev_routes)])
async def save_graph(data: GraphRequest):
    import server as s

    graph_path = s.get_graph_path()
    try:
        graph_path.parent.mkdir(parents=True, exist_ok=True)
        with open(graph_path, "w") as f:
            import json
            json.dump(data.model_dump(), f)
        return {"status": "success"}
    except Exception as e:
        logging.error(f"Graph Save Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/graph/load", dependencies=[Depends(_require_dev_routes)])
async def load_graph():
    import server as s

    graph_path = s.get_graph_path()
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

@router.post("/llm/generate_plan", dependencies=[Depends(_require_dev_routes)])
async def generate_plan(request: PlanRequest):
    import server as s

    engine = s.get_selected_llm_engine()
    prompt = f"Goal: {request.goal}"

    # Generate text
    json_text = await run_in_threadpool(
        engine.process_fast_lane, prompt, preset_name="Plan Generator", true_gen=False, context_rules=False
    )

    # Attempt to clean potential markdown code blocks if the LLM ignores instructions
    clean_text = json_text.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]

    import json
    try:
        plan = json.loads(clean_text.strip())
        return plan
    except json.JSONDecodeError:
        # Do not log model output verbatim — it can contain the user's prompt
        # content. Length + error class is enough to diagnose.
        logging.error(f"LLM produced invalid JSON ({len(clean_text)} chars).")
        return {"title": "Generation Failed", "phases": [{"name": "Error", "tasks": ["The LLM did not return valid JSON.", "Please try again."]}]}
    except Exception as e:
        logging.error(f"Plan Gen Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class ExportRequest(BaseModel):
    title: str
    content: str
    plan: dict

@router.post("/project/export", dependencies=[Depends(_require_dev_routes)])
async def export_project(request: ExportRequest):
    import server as s
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

        # Save under the user's Downloads dir (cross-platform), falling back to
        # the home directory if Downloads doesn't exist.
        export_dir = s._get_downloads_dir()
        safe_title = re.sub(r"[^\w\-]", "_", request.title)[:60] or "export"
        export_path = os.path.join(export_dir, f"{safe_title}_Export.zip")
        with open(export_path, "wb") as f:
            f.write(zip_buffer.getvalue())

        return {"status": "success", "path": export_path}

    except Exception as e:
        logging.error(f"Export Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/intent/state", dependencies=[Depends(_require_dev_routes)])
async def get_intent_state():
    import server as s

    return {"state": s.intent_engine.get_state()}

@router.post("/intent/state", dependencies=[Depends(_require_dev_routes)])
async def set_intent_state(data: dict):
    import server as s

    # expect {"state": "planning"}
    new_state = data.get("state")
    if new_state == "planning":
        s.intent_engine.set_state(s.IntentState.PLANNING)
    elif new_state == "executing":
        s.intent_engine.set_state(s.IntentState.EXECUTING)
    elif new_state == "idle":
        s.intent_engine.set_state(s.IntentState.IDLE)
    return {"state": s.intent_engine.get_state()}

@router.post("/project/generate", dependencies=[Depends(_require_dev_routes)])
async def generate_project(data: dict):
    import server as s

    # expect {"plan": {...}, "path": "..."}
    plan = data.get("plan")
    path = data.get("path")
    if not plan or not path:
        raise HTTPException(status_code=400, detail="Missing plan or path")

    success, msg = await run_in_threadpool(s.project_generator.generate_project, plan, path)
    return {"status": "success" if success else "error", "message": msg}
