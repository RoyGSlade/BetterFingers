"""Enforce the strict release-parity ledger (D-0015, Wave 11 / Gate 11).

The validator itself lives in ``tools/parity_validator.py`` so the release
director can run it standalone (``python3 tools/parity_validator.py``). This
module is the enforced version: it fails the suite the moment the ledger
drifts from ``docs/ui/CURRENT_UI_INVENTORY.md`` or contradicts its own
totals.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_validator as pv  # noqa: E402


@pytest.fixture(scope="module")
def report():
    return pv.validate(ROOT)


def test_source_inventory_has_exactly_438_rows(report):
    assert len(report.source_rows) == 438


def test_every_source_row_has_exactly_one_ledger_row(report):
    ledger_ids = [row.stable_id for row in report.ledger_rows]
    source_ids = [row.stable_id for row in report.source_rows]
    assert len(ledger_ids) == len(set(ledger_ids)), "duplicate stable ids in the ledger"
    assert sorted(ledger_ids) == sorted(source_ids)


def test_statuses_use_only_the_release_vocabulary(report):
    bad = sorted({row.status for row in report.ledger_rows} - set(pv.VALID_STATUSES))
    assert not bad, f"release-forbidden statuses present (D-0015): {bad}"


def test_ledger_is_internally_consistent(report):
    assert report.ok, "\n".join(report.errors)


def test_totals_are_reported_for_the_handoff(report):
    totals = report.totals
    print(
        f"\nPARITY TOTALS: {totals['wired']} wired / "
        f"{totals['intentional_cut']} intentional_cut / "
        f"{totals['blocked']} blocked / {totals['total']} total"
    )
    assert totals["total"] == 438
