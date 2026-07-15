"""Model resource ledger route (DESIGN.md M6): GET /models/resources.

A thin read-only view over model_runtime_coordinator's ledger + current RAM
headroom, for the Diagnostics UI. Registered on the app via
``app.include_router`` in server.py, alongside routes_foundry/routes_user_config.
"""

from fastapi import APIRouter

# NOTE: `server` is imported lazily inside the handler, not at module top —
# server.py imports this module at the end of its own load, so a top-level
# `import server` here would be a partially-initialized circular import (same
# convention as routes_foundry.py).

router = APIRouter()


@router.get("/models/resources")
async def get_model_resources():
    import server

    return {"ok": True, **server.model_runtime.resources_snapshot()}
