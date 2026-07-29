"""Regression guard for the Wave 11 production-evidence collector.

``tools/parity_evidence.py`` is what decided 438 status rulings, so its own
resolution rules need holding still. Two of them were bugs found during the
Wave 11 audit and are pinned here so they cannot silently come back:

* the production closure must include ``overlay.html`` and
  ``review-overlay.html`` -- they are separate always-on-top production
  windows, and omitting them reported 13 shipping surfaces as product gaps;
* untagged QA scenarios must NOT count as production coverage -- they belong
  to the ``legacy`` target and never touch ``signal-desk.html``.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import parity_evidence as pe  # noqa: E402


def test_production_closure_includes_the_overlay_windows():
    closure = pe.Closure.build(
        "production", pe.PROD_ENTRY_HTML, pe.PROD_ENTRY_JS, pe.PROD_EXTRA_PAGES
    )
    files = set(closure.rel_files())
    for page in (
        "app/src/renderer/signal-desk.html",
        "app/src/renderer/overlay.html",
        "app/src/renderer/review-overlay.html",
    ):
        assert page in files, f"{page} is a production surface and must be in the closure"
    # And the ids those pages own must therefore resolve.
    for element_id in ("statusRing", "rawText", "closeButton"):
        assert element_id in closure.element_ids


def test_production_closure_is_reachability_based_not_directory_based():
    """A feature module on disk but never imported is not in the product."""
    closure = pe.Closure.build(
        "production", pe.PROD_ENTRY_HTML, pe.PROD_ENTRY_JS, pe.PROD_EXTRA_PAGES
    )
    files = set(closure.rel_files())
    assert "app/src/renderer/main.js" not in files, (
        "the legacy renderer entry must never appear in the production closure"
    )
    assert "app/src/renderer/signal-desk-preview.html" not in files, (
        "the QA preview page is not production (D-0007)"
    )


def test_only_production_target_scenarios_count_as_production_qa():
    assert pe.PROD_QA_TARGETS == {"signal-desk-prod"}
    coverage = pe.Coverage.build()
    for path in coverage.prod_qa_files:
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "ui: 'signal-desk-prod'" in text, (
            f"{path} counted as production QA without tagging the production target"
        )
    # personas.mjs is the concrete case behind BLOCKER B-1: it drives the
    # Foundry, which ships in production, but runs against index.html. If it
    # is ever retargeted this assertion should be updated, not deleted -- and
    # 23 ledger rows become promotable.
    assert "app/tests/qa/scenarios/personas.mjs" not in coverage.prod_qa_files


def test_the_signal_desk_renaming_rule_resolves_a_known_pair():
    """`#settingRecordingMode` -> `#sdSetRecordingMode`, per settingsWorkspace.js."""
    closure = pe.Closure.build(
        "production", pe.PROD_ENTRY_HTML, pe.PROD_ENTRY_JS, pe.PROD_EXTRA_PAGES
    )
    index = pe.build_id_index(closure)
    assert pe.resolve_id("settingRecordingMode", closure, index) == "sdSetRecordingMode"
    assert pe.resolve_id("privacyWipeVoices", closure, index) == "sdSetPrivacyWipeVoices"
    assert pe.resolve_id("onboardingConsent", closure, index) == "sdOnboardConsent"
    # A name that exists nowhere must stay unresolved rather than fuzzy-match.
    assert pe.resolve_id("thisControlDoesNotExist", closure, index) is None
