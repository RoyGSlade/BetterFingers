"""The committed ledger must match what its generator produces.

``docs/release/PARITY_INVENTORY.md`` is generated, and a generated file that
has been hand-edited (or left stale after a code change) is worse than one
that was never generated: it looks authoritative and reproduces nothing. This
regenerates into a temp file and compares bytes, so drift fails here instead
of being discovered during a gate review.

If this fails, run ``python3 tools/parity_ledger_build.py`` and review the
diff -- a change in the totals is a real change in the audit, not a formatting
nit.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_ledger_build as build  # noqa: E402


def test_committed_ledger_matches_its_generator(tmp_path, monkeypatch):
    committed = build.LEDGER.read_text(encoding="utf-8")

    regenerated_path = tmp_path / "PARITY_INVENTORY.md"
    monkeypatch.setattr(build, "LEDGER", regenerated_path)
    assert build.main() == 0
    regenerated = regenerated_path.read_text(encoding="utf-8")

    if committed != regenerated:
        committed_lines = committed.split("\n")
        regenerated_lines = regenerated.split("\n")
        first = next(
            (
                index
                for index, (a, b) in enumerate(zip(committed_lines, regenerated_lines))
                if a != b
            ),
            min(len(committed_lines), len(regenerated_lines)),
        )
        raise AssertionError(
            "docs/release/PARITY_INVENTORY.md is stale or hand-edited; regenerate with "
            f"`python3 tools/parity_ledger_build.py`. First difference at line {first + 1}:\n"
            f"  committed:    {committed_lines[first: first + 1]}\n"
            f"  regenerated:  {regenerated_lines[first: first + 1]}"
        )
