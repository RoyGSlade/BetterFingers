"""User text-config routes: custom dictionary, macros, and voice presets (M6).

Pure pass-throughs to the dictionary / macros / voice_presets modules — no
server state is touched, so (unlike routes_foundry) this needs no ``import
server`` at all. Registered on the app via ``app.include_router`` in server.py.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import dictionary
import macros
import voice_presets

router = APIRouter()


# --- Custom dictionary ---
class DictionaryTermRequest(BaseModel):
    term: str


@router.get("/dictionary")
async def get_dictionary():
    return {"ok": True, "terms": dictionary.get_terms()}


@router.post("/dictionary")
async def add_dictionary_term(request: DictionaryTermRequest):
    if not str(request.term or "").strip():
        raise HTTPException(status_code=400, detail="Term must not be empty.")
    return {"ok": True, "terms": dictionary.add_term(request.term)}


@router.delete("/dictionary/{term}")
async def delete_dictionary_term(term: str):
    return {"ok": True, "terms": dictionary.remove_term(term)}


class DictionarySuggestRequest(BaseModel):
    raw_text: str = ""
    edited_text: str = ""


@router.post("/dictionary/suggest")
async def suggest_dictionary_terms(request: DictionarySuggestRequest):
    suggestions = dictionary.suggest_from_edit(request.raw_text, request.edited_text)
    return {"ok": True, "suggestions": suggestions}


# --- Macros ---
class MacroRequest(BaseModel):
    trigger: str
    expansion: str


@router.get("/macros")
async def get_macros_endpoint():
    return {"ok": True, "macros": macros.get_macros()}


@router.post("/macros")
async def add_macro_endpoint(request: MacroRequest):
    if not str(request.trigger or "").strip() or not str(request.expansion or "").strip():
        raise HTTPException(status_code=400, detail="Both a trigger and an expansion are required.")
    return {"ok": True, "macros": macros.add_macro(request.trigger, request.expansion)}


@router.delete("/macros/{trigger}")
async def delete_macro_endpoint(trigger: str):
    return {"ok": True, "macros": macros.remove_macro(trigger)}


# --- Voice presets ---
class VoicePresetRequest(BaseModel):
    name: str
    base: Optional[str] = None
    blend: Optional[dict] = None
    speed: Optional[float] = None
    pitch: Optional[float] = None
    energy: Optional[float] = None
    warmth: Optional[float] = None
    brightness: Optional[float] = None
    pause_style: Optional[str] = None
    stability: Optional[float] = None
    source: Optional[str] = None


@router.get("/voice-presets")
async def get_voice_presets_endpoint():
    return {
        "ok": True,
        "presets": voice_presets.get_presets(),
        "default": voice_presets.get_default_preset(),
    }


@router.post("/voice-presets")
async def save_voice_preset_endpoint(request: VoicePresetRequest):
    if not str(request.name or "").strip():
        raise HTTPException(status_code=400, detail="A preset name is required.")
    fields = {
        key: value
        for key, value in request.model_dump(exclude={"name"}).items()
        if value is not None
    }
    return {"ok": True, "presets": voice_presets.save_preset(request.name, **fields)}


@router.post("/voice-presets/{name}/make-default")
async def make_default_voice_preset_endpoint(name: str):
    """Mark an existing preset as the one ordinary read-aloud falls back to
    when no preset_name/persona is explicit in the request (see server.py's
    _resolve_voice_and_modulation). 404 on an unknown name rather than
    silently no-op'ing, since a client-side typo here would otherwise look
    like it worked."""
    if not voice_presets.set_default_preset(name):
        raise HTTPException(status_code=404, detail=f"No voice preset named {name!r}.")
    return {"ok": True, "default": voice_presets.get_default_preset()}


# Deliberately NOT "/voice-presets/default": that path is indistinguishable
# from DELETE /voice-presets/{name} with name="default", and Starlette
# resolves path collisions by registration order — whichever route is added
# first would permanently shadow the other. A user is free to name a preset
# "default", and it must stay deletable via the route below regardless of
# registration order, so "clear the default pointer" gets its own, structurally
# distinct path (a different segment count/shape, not a nested literal) instead.
@router.delete("/voice-presets-default")
async def clear_default_voice_preset_endpoint():
    voice_presets.clear_default_preset()
    return {"ok": True, "default": None}


@router.delete("/voice-presets/{name}")
async def delete_voice_preset_endpoint(name: str):
    return {"ok": True, "presets": voice_presets.delete_preset(name)}
