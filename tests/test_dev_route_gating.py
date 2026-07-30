"""C-2 / QA-SEC-002 (D-0042): graph/intent/project/mcp/llm dev routes must be
unreachable unless BETTERFINGERS_DEV_ROUTES=1. None of these 11 routes appear
in the Electron renderer's ROUTE_ALLOWLIST (app/src/main/backendProxy.js), so
anything that could reach this port directly was the only thing that could
ever reach them.

The gate is checked at request time (server._require_dev_routes, a FastAPI
dependency), not at import time, so a test can flip the env var and observe
both outcomes without reloading the module -- see D-0042's rationale for why
this was chosen over conditionally mounting a sub-router.

conftest.py sets BETTERFINGERS_DEV_ROUTES=1 by default for the whole test
session (same reasoning as its LAZY_STARTUP/ALLOW_TINY_MODELS setdefaults), so
the "off" tests below must monkeypatch.delenv it explicitly -- forgetting that
would make the "off" assertions pass for the wrong reason.
"""

import pytest
from fastapi.testclient import TestClient

import server

# (method, path) for all 11 gated dev routes. Kept in one place so the count
# in this file and the count reported in the C-2 handoff can't silently drift.
DEV_ROUTES = [
    ("GET", "/mcp/status"),
    ("GET", "/mcp/servers"),
    ("GET", "/mcp/servers/nope/tools"),
    ("POST", "/llm/process"),
    ("POST", "/graph/save"),
    ("GET", "/graph/load"),
    ("POST", "/llm/generate_plan"),
    ("POST", "/project/export"),
    ("GET", "/intent/state"),
    ("POST", "/intent/state"),
    ("POST", "/project/generate"),
]


def test_eleven_dev_routes_are_tracked():
    assert len(DEV_ROUTES) == 11


def test_gate_helper_is_off_by_default(monkeypatch):
    # The shipped default, independent of the conftest setdefault: if nobody
    # sets the env var at all, the gate must refuse.
    monkeypatch.delenv("BETTERFINGERS_DEV_ROUTES", raising=False)
    assert server._dev_routes_enabled() is False


def test_gate_helper_requires_the_exact_value_1(monkeypatch):
    monkeypatch.setenv("BETTERFINGERS_DEV_ROUTES", "1")
    assert server._dev_routes_enabled() is True
    monkeypatch.setenv("BETTERFINGERS_DEV_ROUTES", "true")
    assert server._dev_routes_enabled() is False


@pytest.fixture
def client():
    return TestClient(server.app)


def test_every_dev_route_404s_with_the_flag_off(client, monkeypatch):
    monkeypatch.delenv("BETTERFINGERS_DEV_ROUTES", raising=False)
    for method, path in DEV_ROUTES:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code == 404, f"{method} {path} was reachable with the flag off"


def test_every_dev_route_is_not_404_with_the_flag_on(client, monkeypatch):
    monkeypatch.setenv("BETTERFINGERS_DEV_ROUTES", "1")
    for method, path in DEV_ROUTES:
        response = client.request(method, path, json={} if method == "POST" else None)
        assert response.status_code != 404, f"{method} {path} was gated even with the flag on"
