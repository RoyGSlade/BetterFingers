"""Settings-profile routes lifted out of server.py (R3): the ten ``/settings/profiles``
routes (list/get/save/create/activate/delete/rename/duplicate/export/import) and
the two legacy ``/profile`` routes (the user-profile manager, not a settings
profile).

Route order matters here. ``POST /settings/profiles/import`` is a literal path
that ``POST /settings/profiles/{profile_name}`` would also match, so it is
declared FIRST, exactly as it was in server.py, and the literal still wins
(``tests/test_route_table_snapshot.py`` pins every overlapping winner).

Same strangler shape as dev.py, wake.py and personas.py: ``server`` stays the
owner of all state and helpers and is imported lazily inside each handler
(``import server as s``), because server.py imports this module near the end of
its own load and a top-level ``import server`` here would be a partially
initialized circular import. Every server name is read as ``s.<name>`` at call
time, so ``patch.object(server, ...)`` in tests still lands. The five request
models are used only by these routes, so they live here. Registered via
``app.include_router`` at the end of server.py.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class ProfileSaveRequest(BaseModel):
    settings: dict


class ProfileCreateRequest(BaseModel):
    name: str
    settings: dict = {}


class ProfileRenameRequest(BaseModel):
    new_name: str


class ProfileDuplicateRequest(BaseModel):
    new_name: str


class ProfileImportRequest(BaseModel):
    kind: str = "betterfingers_profile"
    schema_version: int = 1
    name: str
    settings: dict


@router.post("/settings/profiles/import")
async def settings_import_profile(request: ProfileImportRequest):
    import server as s

    if request.kind != "betterfingers_profile":
        raise HTTPException(status_code=400, detail="Invalid profile format: missing 'betterfingers_profile' kind.")
    if request.schema_version != 1:
        raise HTTPException(status_code=400, detail=f"Unsupported profile schema version: {request.schema_version}")

    safe_name = s.sanitize_profile_name(request.name)
    if safe_name in s.list_profiles():
        raise HTTPException(status_code=409, detail="Profile name already exists")

    try:
        s.save_runtime_profile(safe_name, request.settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}")

    return s.get_active_profile_payload()


@router.get("/settings/profiles")
async def settings_profiles():
    import server as s

    return s.get_active_profile_payload()


@router.get("/settings/profiles/{profile_name}")
async def settings_profile(profile_name: str):
    import server as s

    safe_name = s.sanitize_profile_name(profile_name)
    return {
        "profile": safe_name,
        "active": safe_name == s.get_last_active_profile(),
        "settings": s.load_profile(safe_name),
    }


@router.post("/settings/profiles/{profile_name}")
async def settings_save_profile(profile_name: str, request: ProfileSaveRequest):
    import server as s

    safe_name = s.sanitize_profile_name(profile_name)
    try:
        s.save_runtime_profile(safe_name, request.settings)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Save failed: {e}")
    residency = None
    if safe_name == s.get_last_active_profile():
        residency = s.apply_active_profile_runtime(safe_name).get("residency")
    response = {
        "profile": safe_name,
        "active": safe_name == s.get_last_active_profile(),
        "settings": s.load_profile(safe_name),
    }
    if residency is not None:
        response["residency"] = residency
    return response


@router.post("/settings/profiles")
async def settings_create_profile(request: ProfileCreateRequest):
    import server as s

    safe_name = s.sanitize_profile_name(request.name)
    if safe_name in s.list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")
    base = s.load_profile(s.get_last_active_profile())
    base.update(request.settings or {})
    try:
        s.save_runtime_profile(safe_name, base)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Create failed: {e}")
    return {"profile": safe_name, "settings": s.load_profile(safe_name), "profiles": s.list_profiles()}


@router.post("/settings/profiles/{profile_name}/activate")
async def settings_activate_profile(profile_name: str):
    import server as s

    safe_name = s.sanitize_profile_name(profile_name)
    if safe_name not in s.list_profiles():
        raise HTTPException(status_code=404, detail="Profile not found")
    # Re-selecting the already-active profile is a no-op: skip the runtime
    # cascade (transcriber reload, hotkey rebind, injector + LLM reconfigure),
    # which costs 100-500 ms. Content edits to the active profile arrive via
    # settings_save_profile, which always re-applies — so this guard can only
    # suppress genuinely redundant switches, never a real settings change.
    if safe_name == s.get_last_active_profile():
        return s.get_active_profile_payload()
    return s.apply_active_profile_runtime(safe_name)


@router.delete("/settings/profiles/{profile_name}")
async def settings_delete_profile(profile_name: str):
    import server as s

    safe_name = s.sanitize_profile_name(profile_name)
    if safe_name == "Default":
        raise HTTPException(status_code=400, detail="Default profile cannot be deleted")
    profile_path = Path(s.get_profiles_dir()) / f"{safe_name}.yaml"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")

    # Check active status before unlinking the file
    was_active = (s.get_last_active_profile() == safe_name)
    profile_path.unlink()

    if was_active:
        s.apply_active_profile_runtime("Default")
    return s.get_active_profile_payload()


@router.post("/settings/profiles/{profile_name}/rename")
async def settings_rename_profile(profile_name: str, request: ProfileRenameRequest):
    import server as s

    safe_old = s.sanitize_profile_name(profile_name)
    safe_new = s.sanitize_profile_name(request.new_name)
    if safe_old == "Default":
        raise HTTPException(status_code=400, detail="Default profile cannot be renamed")
    if safe_new in s.list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")

    old_path = Path(s.get_profiles_dir()) / f"{safe_old}.yaml"
    if not old_path.exists():
        raise HTTPException(status_code=404, detail="Profile not found")

    # Load and save under new name
    data = s.load_profile(safe_old)
    try:
        s.save_runtime_profile(safe_new, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rename failed during save: {e}")

    # Check active status before unlinking the file
    was_active = (s.get_last_active_profile() == safe_old)
    old_path.unlink()

    # If old was active, activate new
    if was_active:
        s.apply_active_profile_runtime(safe_new)

    return s.get_active_profile_payload()


@router.post("/settings/profiles/{profile_name}/duplicate")
async def settings_duplicate_profile(profile_name: str, request: ProfileDuplicateRequest):
    import server as s

    safe_old = s.sanitize_profile_name(profile_name)
    safe_new = s.sanitize_profile_name(request.new_name)
    if safe_new in s.list_profiles():
        raise HTTPException(status_code=409, detail="Profile already exists")

    if safe_old not in s.list_profiles():
        raise HTTPException(status_code=404, detail="Source profile not found")

    data = s.load_profile(safe_old)
    try:
        s.save_runtime_profile(safe_new, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Duplication failed: {e}")

    return s.get_active_profile_payload()


@router.get("/settings/profiles/{profile_name}/export")
async def settings_export_profile(profile_name: str):
    import server as s

    safe_name = s.sanitize_profile_name(profile_name)
    if safe_name not in s.list_profiles():
        raise HTTPException(status_code=404, detail="Profile not found")
    return {
        "kind": "betterfingers_profile",
        "schema_version": 1,
        "name": safe_name,
        "settings": s.load_profile(safe_name),
    }


@router.get("/profile")
async def get_profile():
    import server as s

    return s.profile_manager.get_profile()

@router.post("/profile")
async def save_profile(data: dict):
    import server as s

    success = s.profile_manager.save_profile(data)
    return {"status": "success" if success else "error"}
