"""Flip and rollback lose nothing (Wave 11 / Gate 11, deliverable 4).

The Wave 11 default flip makes ``signal-desk.html`` the page a user gets with
``BF_UI`` unset, and keeps ``index.html`` reachable via ``BF_UI=legacy`` as the
revert path. That revert is only safe if the two pages read and write the SAME
durable state -- a user who flips forward, dictates for a week, then rolls back
must find their profiles, drafts, contacts, personas and history intact.

The mechanism that makes it safe is structural, not incidental: neither page
owns any storage. Both render into the same Electron main process, call the
same backend over the same proxy, and the backend has no idea which page is
loaded. These tests assert exactly that structure, because it is the property
that would silently break -- someone adding a UI-conditioned path is the only
realistic way to lose data across a flip.

The one documented divergence is onboarding consent, and it is shared by
construction since Wave 1 (D-0018): the durable record lives under the unified
user-data root, and the legacy ``localStorage`` flag is migrated into it
one-shot rather than being a second source of truth.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "app/src/renderer"
MAIN = ROOT / "app/src/main"

# Every Python module that resolves a durable path or serves a route. If the
# backend ever learns which UI is loaded, that is where it would show up.
BACKEND_SOURCES = sorted(
    [path for path in ROOT.glob("*.py") if path.name != "conftest.py"]
    + list((ROOT / "backend").rglob("*.py"))
)


def test_the_backend_cannot_tell_which_ui_is_loaded():
    """No Python source may branch on BF_UI.

    This is the whole rollback guarantee in one assertion: a backend that
    cannot observe the UI cannot store anything differently for it, so the
    stores a flip writes are byte-for-byte the stores a rollback reads.
    """
    offenders = []
    for path in BACKEND_SOURCES:
        text = path.read_text(encoding="utf-8", errors="replace")
        if "BF_UI" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "the Python backend must never branch on the renderer page; these files "
        f"reference BF_UI: {offenders}"
    )


def test_no_renderer_page_gets_its_own_storage_root():
    """Neither page may define a page-specific data directory."""
    offenders = []
    for path in list(RENDERER.rglob("*.js")) + list(RENDERER.rglob("*.mjs")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"BETTERFINGERS_DATA_DIR|userData\s*[,)]", text):
            offenders.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
    assert not offenders, (
        "renderer code must not resolve storage roots itself -- all durable state "
        f"goes through the main process / backend: {offenders}"
    )


def test_both_pages_share_one_backend_client():
    """Legacy and Signal Desk call the same api/backend.js, not two clients."""
    backend_client = RENDERER / "api/backend.js"
    assert backend_client.exists()

    legacy = (RENDERER / "main.js").read_text(encoding="utf-8", errors="replace")
    production = (RENDERER / "bootstrap/signalDeskApp.js").read_text(
        encoding="utf-8", errors="replace"
    )
    for name, text in (("index.html/main.js", legacy), ("signal-desk.html", production)):
        assert re.search(r"""from\s+['"][^'"]*api/backend\.js['"]""", text), (
            f"{name} must reach the backend through api/backend.js, not its own client"
        )

    # And exactly one origin is defined, in that shared client.
    origins = []
    for path in list(RENDERER.rglob("*.js")) + list(RENDERER.rglob("*.mjs")):
        text = path.read_text(encoding="utf-8", errors="replace")
        origins += [
            f"{path.relative_to(ROOT)}: {match}"
            for match in re.findall(r"http://127\.0\.0\.1:\d+|http://localhost:\d+", text)
        ]
    non_client = [entry for entry in origins if "api/backend.js" not in entry]
    assert not non_client, f"backend origin defined outside the shared client: {non_client}"


def test_onboarding_consent_is_durable_and_shared():
    """The one divergence, and why it does not lose anything.

    Legacy onboarding recorded completion in ``localStorage``, which is
    per-page. Signal Desk records it in a durable file under the unified user
    data root. If those were two independent sources of truth, a rollback
    would re-prompt for consent (annoying but safe) and a flip forward could
    lose an acceptance record (not safe). Wave 1 resolved that by MIGRATING
    the legacy flag into the durable record, one-shot.
    """
    store = (MAIN / "onboardingStore.js").read_text(encoding="utf-8")
    assert "resolveUserDataRoot" in store, (
        "the consent record must live under the unified user data root, not a page-local path"
    )
    assert "migrateLegacyCompletion" in store, (
        "the legacy localStorage flag must be migrated into the durable record, "
        "otherwise a flip forward silently drops an existing acceptance"
    )
    assert "bf_onboarding_complete" in store, (
        "the migration must name the exact legacy flag it consumes"
    )
    # Factory reset clears it too -- a store that survives a factory reset
    # would be a privacy defect, not a rollback feature (D-0028).
    assert "clearForFactoryReset" in store


def test_the_flip_is_reversible_by_environment_alone():
    """Rolling back must not require a rebuild, a migration or a data edit."""
    windows = (MAIN / "windows.js").read_text(encoding="utf-8")
    assert "process.env.BF_UI" in windows, "the page choice must remain an environment switch"
    assert "'legacy'" in windows or '"legacy"' in windows, (
        "BF_UI=legacy must be the documented rollback route (Wave 11 deliverable 3)"
    )
    # Both pages must still be in the trusted-page set, or the rolled-back page
    # loads with every IPC call rejected -- a silently dead UI, which is the
    # worst possible rollback outcome.
    sender = (MAIN / "senderValidation.js").read_text(encoding="utf-8")
    for page in ("index.html", "signal-desk.html"):
        assert f"'{page}'" in sender, (
            f"{page} must stay in RENDERER_PAGES or its IPC bridge is dead after a flip/rollback"
        )


@pytest.mark.parametrize("page", ["index.html", "signal-desk.html"])
def test_both_pages_are_still_built_and_shipped(page):
    """A rollback target that is not in the build is not a rollback target."""
    config = (ROOT / "app/electron.vite.config.js").read_text(encoding="utf-8")
    assert page in config, f"{page} must remain a renderer build input for the flip to be reversible"


def test_qa_covers_both_sides_of_the_flip():
    """Evidence, not just structure: a scenario per side, on the right target."""
    scenarios = (ROOT / "app/tests/qa/scenarios/default-flip.mjs").read_text(encoding="utf-8")
    assert "ui: 'signal-desk-prod'" in scenarios, "no default-target (production) flip scenario"
    assert "ui: 'legacy'" in scenarios, "no legacy-target rollback scenario"

    harness = (ROOT / "app/tests/qa/harness.mjs").read_text(encoding="utf-8")
    assert re.search(r"DEFAULT_UI\s*=\s*'signal-desk-prod'", harness), (
        "the QA default target must be the production page after the flip"
    )
    assert re.search(r"legacy:\s*\{", harness), "the QA harness must keep a legacy rollback target"


def test_privacy_registry_is_page_agnostic():
    """Wipe/export cover the same stores whichever page is loaded."""
    categories = (ROOT / "data_categories.py").read_text(encoding="utf-8")
    assert "BF_UI" not in categories
    assert "signal-desk" not in categories and "index.html" not in categories, (
        "the privacy registry must describe stores, never renderer pages"
    )
