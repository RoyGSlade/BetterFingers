"""Golden HTTP/WebSocket route table for the backend (reorganization guardrail).

The reorganization moves handlers out of server.py into backend/api/routes/*
routers. Two things must survive every move:

1. The public surface: the same (kind, methods, path) routes, none lost or
   added by accident. A deliberate API change updates the snapshot in the same
   commit:  BF_UPDATE_ROUTE_SNAPSHOT=1 pytest tests/test_route_table_snapshot.py
2. Who wins an overlap. Starlette dispatches to the first matching route, so
   when a parameterised path also matches another path (/drafts/{draft_id}
   against /drafts/latest), registration order decides. Order may change as
   routers move; the winner of every overlapping pair may not.
"""
import json
import os
from collections import Counter
from pathlib import Path

from fastapi.routing import iter_route_contexts
from starlette.routing import compile_path

import server

SNAPSHOT = Path(__file__).parent / "fixtures" / "route_table.json"


def _route_table():
    # FastAPI >= 0.140 keeps included routers as _IncludedRouter entries in
    # app.routes; iter_route_contexts expands them in place, in dispatch order,
    # with the effective (prefixed) path.
    return [
        {
            "kind": type(context.original_route).__name__,
            "methods": sorted(context.methods or []),
            "path": context.path,
        }
        for context in iter_route_contexts(server.app.routes)
    ]


def _key(row):
    return (row["kind"], tuple(row["methods"]), row["path"])


def _could_collide(first, later):
    if ("WebSocket" in first["kind"]) != ("WebSocket" in later["kind"]):
        return False
    if first["methods"] and later["methods"] and not set(first["methods"]) & set(later["methods"]):
        return False
    if first["path"] == later["path"]:
        return False  # identical path, disjoint methods were excluded above
    return bool(
        compile_path(first["path"])[0].match(later["path"])
        or compile_path(later["path"])[0].match(first["path"])
    )


def _precedence(rows):
    """{(earlier, later)} for every pair of routes that can match the same request."""
    return {
        (_key(first), _key(later))
        for index, first in enumerate(rows)
        for later in rows[index + 1:]
        if _could_collide(first, later)
    }


def _load_snapshot(current):
    if os.environ.get("BF_UPDATE_ROUTE_SNAPSHOT") == "1":
        SNAPSHOT.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_route_set_matches_snapshot():
    current = _route_table()
    expected = _load_snapshot(current)
    current_counts = Counter(map(_key, current))
    expected_counts = Counter(map(_key, expected))
    missing = sorted((expected_counts - current_counts).elements())
    added = sorted((current_counts - expected_counts).elements())
    assert not missing and not added, (
        f"Route table changed.\nmissing: {missing}\nadded: {added}\n"
        "If this is a deliberate API change, regenerate with "
        "BF_UPDATE_ROUTE_SNAPSHOT=1 pytest tests/test_route_table_snapshot.py"
    )


def test_overlapping_routes_keep_their_winner():
    current = _route_table()
    expected = _load_snapshot(current)
    flipped = sorted(_precedence(expected) - _precedence(current))
    assert not flipped, (
        "Registration order flipped for overlapping routes; the first of each pair "
        f"used to win and no longer does: {flipped}"
    )
