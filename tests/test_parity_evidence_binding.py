"""The `_evidenced_by_test` binding must actually fail when its evidence goes away.

Wave 12, director Ruling A. Two inventory rows assert a NEGATIVE property
("no backend calls", "no donation prompt anywhere"), which has no production
anchor by construction, so they could only ever be reported `blocked` however
well evidenced they were. `parity_ledger_build._evidenced_by_test()` is the
auditable handle they lacked.

The whole point of that mechanism is that it is NOT a hand-claimed status. So
the thing worth testing is not that it produces `wired` -- it is that it STOPS
producing `wired` the moment the evidence stops existing. A binding that cannot
fail is a hand-claim wearing a checker's clothes, which is exactly what the
strict ledger exists to prevent.
"""
from __future__ import annotations

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_ledger_build as plb  # noqa: E402


def test_the_declared_bindings_hold_right_now():
    """The real, shipping declarations pass their own check."""
    plb.verify_test_evidence()  # must not raise
    assert plb.EVIDENCED_BY_TEST, "the mechanism is declared but unused -- did a binding get dropped?"


def test_every_binding_names_a_real_file_that_names_the_row():
    for stable_id, (test_path, subjects, why) in plb.EVIDENCED_BY_TEST.items():
        path = ROOT / test_path
        assert path.is_file(), f"{stable_id} points at a missing file: {test_path}"
        assert stable_id in path.read_text(encoding="utf-8"), (
            f"{test_path} must name {stable_id} -- the binding is what makes the claim auditable"
        )
        assert why.strip(), f"{stable_id} must say what the test actually proves"
        assert subjects, f"{stable_id} must name the production files its property is about"
        for subject in subjects:
            assert (ROOT / subject).is_file(), f"{stable_id} asserts over a missing file: {subject}"
            # parity_validator requires a production-file pointer on every
            # `wired` row; these subjects are what satisfy it honestly.
            assert subject.startswith("app/src/"), (
                f"{stable_id}: {subject} is not production source"
            )


def test_a_missing_evidence_file_fails_the_build(monkeypatch):
    monkeypatch.setitem(
        plb.EVIDENCED_BY_TEST,
        "UI-99-999",
        (
            "app/tests/thisTestWasDeleted.test.mjs",
            ("app/src/renderer/signal-desk.html",),
            "a row resting on evidence someone removed",
        ),
    )
    with pytest.raises(plb.EvidenceBindingError, match="does not exist"):
        plb.verify_test_evidence()


def test_a_test_that_stops_naming_the_row_fails_the_build(monkeypatch):
    """The subtler failure: the file survives, but the assertion is renamed away.

    This is the realistic decay path -- nobody deletes the test, someone just
    rewrites its name during an unrelated refactor and the row quietly keeps a
    `wired` that nothing is checking any more.
    """
    # Deliberately NOT this file: writing the invented id into a monkeypatch
    # call here would put the string in the very file being checked, and the
    # binding would hold for the silliest of reasons. (It did, first time.)
    # tools/parity_churn.py is real, tracked, and contains no stable ids.
    fake_id = "UI-99-" + "998"
    monkeypatch.setitem(
        plb.EVIDENCED_BY_TEST,
        fake_id,
        (
            "tools/parity_churn.py",
            ("app/src/renderer/signal-desk.html",),
            "bound to a real file that never names the row",
        ),
    )
    with pytest.raises(plb.EvidenceBindingError, match="no longer mentions"):
        plb.verify_test_evidence()


def test_a_property_proved_about_a_deleted_file_fails_the_build(monkeypatch):
    """The third decay path: the test survives and still names the row, but the
    file it was proving something ABOUT is gone. "No donation prompt in X" is
    trivially true once X no longer exists, so the row would keep a `wired` that
    means nothing."""
    monkeypatch.setitem(
        plb.EVIDENCED_BY_TEST,
        "UI-12-008",
        (
            "app/tests/negativeProperties.test.mjs",
            ("app/src/renderer/aPageThatWasDeleted.html",),
            "asserted over a page that no longer ships",
        ),
    )
    with pytest.raises(plb.EvidenceBindingError, match="does not exist"):
        plb.verify_test_evidence()


def test_a_bound_row_classifies_as_wired_only_through_the_checked_path():
    """Sanity: the binding is what promotes the row, not an unconditional pass."""
    assert "UI-12-008" in plb.EVIDENCED_BY_TEST
    assert "UI-15-007" in plb.EVIDENCED_BY_TEST
    # An id with no binding and no override must not be swept along.
    assert "UI-99-997" not in plb.EVIDENCED_BY_TEST
