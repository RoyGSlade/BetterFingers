"""Focused contracts for the searchable-history HTTP endpoint."""

from unittest.mock import patch

from fastapi import HTTPException

import server
from backend.api.routes import history as routes_history


def test_history_clear_failure_is_http_failure():
    with patch.object(server.history_store, "clear", return_value=False):
        try:
            server_result = __import__("asyncio").run(routes_history.history_clear())
        except HTTPException as exc:
            assert exc.status_code >= 400
            assert "clear history" in exc.detail.lower()
        else:
            raise AssertionError(f"history_clear unexpectedly succeeded: {server_result!r}")
