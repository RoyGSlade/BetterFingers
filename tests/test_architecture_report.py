"""Tests for tools/architecture_report.py (Build Week A1.8).

These assert shape and internal consistency, not brittle counts — the report
is expected to grow as backend/** and app/src/renderer/** grow, so this
suite must not need edits every time a file is added.
"""

import importlib.util
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOL_PATH = os.path.join(REPO_ROOT, "tools", "architecture_report.py")

_spec = importlib.util.spec_from_file_location("architecture_report", TOOL_PATH)
architecture_report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(architecture_report)


def test_report_covers_backend_and_renderer_domains():
    report = architecture_report.build_report()
    assert set(report["domains"]) == {"backend", "renderer"}
    for domain, data in report["domains"].items():
        assert data["file_count"] > 0, f"expected at least one file in {domain}"


def test_every_scanned_file_has_size_and_path():
    report = architecture_report.build_report()
    for domain, data in report["domains"].items():
        assert len(data["sizes"]) == data["file_count"]
        for name, info in data["sizes"].items():
            assert info["bytes"] > 0, f"{domain}/{name} reported 0 bytes"
            assert info["lines"] > 0, f"{domain}/{name} reported 0 lines"
            full_path = os.path.join(REPO_ROOT, info["path"])
            assert os.path.isfile(full_path), f"{domain}/{name} path does not exist: {info['path']}"


def test_composition_roots_are_in_degree_zero():
    """A composition root must not appear as a dependency of any other node."""
    report = architecture_report.build_report()
    for domain, data in report["domains"].items():
        imported = set()
        for deps in data["import_graph"].values():
            imported.update(deps)
        for root in data["composition_roots"]:
            assert root not in imported, f"{domain}/{root} is claimed as a root but is imported elsewhere"
            assert root in data["import_graph"], f"{domain}/{root} missing from its own import graph"


def test_known_renderer_composition_root_is_main_js():
    """main.js is documented (app/src/renderer/features/*.js headers) as the composition root."""
    report = architecture_report.build_report()
    roots = report["domains"]["renderer"]["composition_roots"]
    assert "app/src/renderer/main.js" in roots


def test_backend_features_are_reachable_from_domain_root():
    """backend.services.dictation_pipeline and backend.stores.drafts must be part of the graph."""
    report = architecture_report.build_report()
    graph = report["domains"]["backend"]["import_graph"]
    assert "backend.services.dictation_pipeline" in graph
    assert "backend.stores.drafts" in graph


def test_report_is_deterministic_across_runs():
    first = architecture_report.build_report()
    second = architecture_report.build_report()
    assert first == second


def test_cycles_are_reported_not_raised():
    """A genuine cycle must show up as data in the report, never raise/fail the run."""
    graph = {"a": ["b"], "b": ["a"]}
    cycles = architecture_report._find_cycles(graph)
    assert cycles, "expected the synthetic a<->b cycle to be detected"
    assert all(isinstance(c, str) for c in cycles)


def test_cli_runs_and_produces_text_and_json():
    import subprocess

    text_result = subprocess.run(
        [sys.executable, TOOL_PATH],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert text_result.returncode == 0
    assert "composition roots" in text_result.stdout

    json_result = subprocess.run(
        [sys.executable, TOOL_PATH, "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert json_result.returncode == 0
    import json

    parsed = json.loads(json_result.stdout)
    assert "domains" in parsed
