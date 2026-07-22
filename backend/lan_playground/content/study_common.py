"""Shared strict-YAML loader helpers for the wave-6B study-content family.

Small deliberately: `_prose`/`_effects`/`_viewer_scope` are the same three
tiny helpers `loader.py` already defines privately for the core pack. They
are duplicated here (not imported from `loader.py`'s underscored names)
rather than made cross-module-private-API, so `loader.py` stays free to
change its own internals without coordinating with this wave's modules --
same "duplicate the values, not the import" choice `heroes.cards.
LIVE_EFFECT_OPS` and `content.schemas.ABILITY_EXECUTABLE_OPS` already make
elsewhere in this codebase.
"""

from __future__ import annotations

from typing import Any

from .loader import LoaderError
from .loader import require_keys as require_keys  # re-export for sibling loader modules
from . import schemas as S

__all__ = ["require_keys", "prose", "effects", "viewer_scope"]


def prose(raw: Any, *, where: str) -> S.Prose:
    raw = require_keys(raw, {"fallback", "accessible"}, where=f"{where}.prose")
    fallback = raw.get("fallback", "")
    accessible = raw.get("accessible", fallback)
    return S.Prose(fallback=fallback, accessible=accessible)


def effects(raw: Any, *, where: str) -> tuple[S.Effect, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise LoaderError(f"{where}: expected a list of effect ops")
    out = []
    for i, item in enumerate(raw):
        item = require_keys(item, {"op", "args"}, where=f"{where}[{i}]")
        try:
            out.append(S.Effect(op=item["op"], args=item.get("args", {}) or {}))
        except S.ContentError as exc:
            raise LoaderError(f"{where}[{i}]: {exc}") from exc
    return tuple(out)


def viewer_scope(raw: str, *, where: str) -> S.ViewerScope:
    try:
        return S.ViewerScope(raw)
    except ValueError as exc:
        raise LoaderError(f"{where}: invalid viewer_scope {raw!r}") from exc
