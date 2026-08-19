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
from tools import parity_evidence as evidence  # noqa: E402


def test_coverage_paths_are_platform_independent():
    coverage = evidence.Coverage.build()
    paths = [path for path, _ in (*coverage.qa_files, *coverage.unit_files)]
    assert paths
    assert all("\\" not in path for path in paths)


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


def test_the_generator_is_deterministic_across_hash_seeds(tmp_path):
    """Two runs in separate interpreters must produce identical bytes.

    Not a formality: `_legacy_aliases` returned a SET, and `resolve_id` stops
    at the first alias that resolves -- so the anchor the ledger cited for a
    row depended on the interpreter's hash seed. `#onboardingTitle` printed
    `#sdOnboardingTitle` in one process and `#sdHeaderTitle` in the next, from
    identical sources, which made the staleness test above a coin flip and the
    ledger unauditable. Subprocesses with explicit PYTHONHASHSEED values are
    the only way to catch it: within a single interpreter the order is stable
    and everything looks fine.
    """
    import os
    import subprocess
    import sys

    digests = set()
    for seed in ("0", "2"):
        out = tmp_path / f"ledger-{seed}.md"
        env = {**os.environ, "PYTHONHASHSEED": seed}
        script = (
            "import sys;"
            f"sys.path.insert(0, {str(ROOT)!r});"
            "from tools import parity_ledger_build as b;"
            f"b.LEDGER = __import__('pathlib').Path({str(out)!r});"
            "raise SystemExit(b.main())"
        )
        assert subprocess.run([sys.executable, "-c", script], env=env,
                              capture_output=True).returncode == 0
        digests.add(out.read_bytes())

    assert len(digests) == 1, (
        "the ledger generator is not deterministic across interpreters: the same "
        "sources produced different bytes under different PYTHONHASHSEED values. "
        "Something iterates a set or dict whose order is not pinned."
    )
