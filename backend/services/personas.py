"""Persona persistence and preview service.

Thin wrappers around llm_engine's persona store, lifted out of server.py
(A1.2) so the FastAPI route handlers stay request/response only. Imports of
llm_engine are lazy per-function, matching the style of the original inline
route handlers.
"""

from typing import Any, Optional


def list_personas() -> dict:
    from llm_engine import load_personas
    return load_personas(force_reload=True)


def list_builtin_persona_names() -> list:
    from llm_engine import get_builtin_persona_names
    return get_builtin_persona_names()


def get_persona(name: str) -> Optional[dict]:
    from llm_engine import get_persona as _get_persona
    return _get_persona(name)


def save_persona(name: str, payload: dict) -> tuple:
    from llm_engine import upsert_persona
    return upsert_persona(name, payload)


def lint_persona(payload: dict) -> list:
    from llm_engine import lint_persona as _lint_persona
    return _lint_persona(payload)


def delete_persona(name: str) -> tuple:
    from llm_engine import delete_persona as _delete_persona
    return _delete_persona(name)


def run_persona_preview(engine: Any, persona: dict, sample: str, max_output_tokens: Optional[int] = None) -> Any:
    return engine.run_persona_preview(persona, sample, max_output_tokens=max_output_tokens)
