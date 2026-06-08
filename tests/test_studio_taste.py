"""Tests for taste memory — learning the user's preferences from steers (§9.4)."""

import os
import tempfile

os.environ.setdefault("STUDIO_DATA_DIR", tempfile.mkdtemp())

import studio_memory as memory
import studio_taste as T


def _project():
    name = f"taste_{os.urandom(4).hex()}"
    pid = memory.init_project_db(name)
    return name, pid


def test_no_signals_yields_empty_clause():
    name, pid = _project()
    assert T.build_digest(name, pid) == ""
    assert T.digest_clause(name, pid) == ""


def test_refine_signal_is_quoted_in_digest():
    name, pid = _project()
    T.record_signal(name, pid, "refine", "make Louis colder and pettier", scene_id="s2")
    digest = T.build_digest(name, pid)
    assert "colder and pettier" in digest
    clause = T.digest_clause(name, pid)
    assert "USER TASTE" in clause and "colder and pettier" in clause


def test_accept_reject_balance_is_summarized():
    name, pid = _project()
    T.record_signal(name, pid, "accept")
    T.record_signal(name, pid, "accept")
    T.record_signal(name, pid, "reject", "too purple, trim the adjectives")
    digest = T.build_digest(name, pid)
    assert "2 kept" in digest and "1 rejected" in digest
    assert "purple" in digest  # reject notes carry texture to avoid


def test_signals_are_bounded_and_recent_first():
    name, pid = _project()
    for i in range(10):
        T.record_signal(name, pid, "refine", f"note number {i}")
    digest = T.build_digest(name, pid)
    # The most recent distinct directions lead; capped at 6 quoted notes.
    assert "note number 9" in digest
    assert digest.count('"') <= 12  # 6 quoted notes -> 12 quote chars max


def test_unknown_kind_is_coerced():
    name, pid = _project()
    T.record_signal(name, pid, "garbage", "do it darker")  # coerced to refine (has note)
    assert "darker" in T.build_digest(name, pid)
