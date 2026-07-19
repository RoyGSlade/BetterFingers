"""Phase 2.1 (remediation) — the unified data-lifecycle registry.

Every persistent data category BetterFingers owns is declared here exactly
once. The privacy report, the wipe modes, exports, and their tests are all
meant to be *generated* from this single source, so adding a new persistent
store becomes a registration — not a hand-edit in five places.

This module is intentionally dependency-light (stdlib only) so routes, domain
code, and tests can import it without pulling in FastAPI. It lives at the top
level for now to match the current flat layout; Phase 6 moves it to
``domain/privacy/registry.py``.

This first chunk defines the types, the controlled vocabularies, the
completeness/consistency validation, and an empty ``REGISTRY``. Subsequent
chunks register the concrete categories and wire their
``size``/``paths``/``wipe``/``verify`` callables.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# --- Controlled vocabularies -------------------------------------------------

OWNERS = frozenset({"python", "electron", "external-runtime"})
SENSITIVITIES = frozenset({"public", "configuration", "personal", "sensitive"})

# The three explicit wipe modes (Phase 2.2). A category names every mode that
# includes it; the UI previews exactly which categories a mode touches.
WIPE_MODE_CONVERSATIONS = "clear_conversations"
WIPE_MODE_PERSONAL = "clear_personal_data"
WIPE_MODE_FACTORY_RESET = "factory_reset"
WIPE_MODES = frozenset(
    {WIPE_MODE_CONVERSATIONS, WIPE_MODE_PERSONAL, WIPE_MODE_FACTORY_RESET}
)

# The modes nest: clearing personal data includes conversations; a factory
# reset includes personal data. A category present in an inner mode must also
# be present in every outer mode that contains it.
_MODE_IMPLIES = {
    WIPE_MODE_CONVERSATIONS: frozenset({WIPE_MODE_PERSONAL, WIPE_MODE_FACTORY_RESET}),
    WIPE_MODE_PERSONAL: frozenset({WIPE_MODE_FACTORY_RESET}),
    WIPE_MODE_FACTORY_RESET: frozenset(),
}


# --- Result types ------------------------------------------------------------


@dataclass(frozen=True)
class WipeResult:
    """Outcome of wiping one category."""

    ok: bool
    removed: list[str] = field(default_factory=list)
    error: Optional[str] = None
    message: str = ""


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of verifying one category is gone / in its expected state."""

    ok: bool
    remaining: list[str] = field(default_factory=list)
    detail: str = ""


@dataclass(frozen=True)
class DataCategory:
    """A single persistent data category and its full lifecycle metadata."""

    id: str
    label: str
    owner: str                       # one of OWNERS
    sensitivity: str                 # one of SENSITIVITIES
    paths: Callable[[], list[Path]]  # every filesystem path this category owns
    retention: str                   # plain-English retention behavior
    wipe_modes: frozenset            # subset of WIPE_MODES that include this
    included_in_report: bool
    included_in_export: bool
    may_contain_user_text: bool
    size: Callable[[], int]          # bytes on disk right now
    wipe: Callable[[], WipeResult]
    verify: Callable[[], VerificationResult]


# --- Validation --------------------------------------------------------------


def validate_category(category: DataCategory) -> None:
    """Raise ``ValueError`` if a category's lifecycle metadata is incomplete or
    inconsistent.

    This is the enforcement point behind Phase 2's definition of done: adding a
    persistent store requires complete registration, and tests fail otherwise.
    """
    cid = category.id
    if not isinstance(cid, str) or not cid.strip():
        raise ValueError("DataCategory.id must be a non-empty string")
    if not isinstance(category.label, str) or not category.label.strip():
        raise ValueError(f"{cid}: label must be a non-empty string")
    if category.owner not in OWNERS:
        raise ValueError(
            f"{cid}: owner {category.owner!r} not in {sorted(OWNERS)}"
        )
    if category.sensitivity not in SENSITIVITIES:
        raise ValueError(
            f"{cid}: sensitivity {category.sensitivity!r} not in {sorted(SENSITIVITIES)}"
        )
    if not isinstance(category.retention, str) or not category.retention.strip():
        raise ValueError(f"{cid}: retention must describe how long the data lives")
    if not isinstance(category.wipe_modes, frozenset):
        raise ValueError(f"{cid}: wipe_modes must be a frozenset")
    unknown = category.wipe_modes - WIPE_MODES
    if unknown:
        raise ValueError(f"{cid}: unknown wipe modes {sorted(unknown)}")
    # Enforce the nesting invariant so a category can't be in an inner mode but
    # silently excluded from the outer mode that is meant to contain it.
    for mode in category.wipe_modes:
        missing = _MODE_IMPLIES[mode] - category.wipe_modes
        if missing:
            raise ValueError(
                f"{cid}: in wipe mode {mode!r} but missing implied modes "
                f"{sorted(missing)} (modes nest: conversations ⊆ personal ⊆ factory)"
            )
    for name in ("paths", "size", "wipe", "verify"):
        if not callable(getattr(category, name)):
            raise ValueError(f"{cid}: {name} must be callable")
    for flag in ("included_in_report", "included_in_export", "may_contain_user_text"):
        if not isinstance(getattr(category, flag), bool):
            raise ValueError(f"{cid}: {flag} must be a bool")


# --- Registry ----------------------------------------------------------------


class DataRegistry:
    """An ordered, id-keyed collection of validated data categories."""

    def __init__(self) -> None:
        self._by_id: dict[str, DataCategory] = {}

    def register(self, category: DataCategory) -> DataCategory:
        validate_category(category)
        if category.id in self._by_id:
            raise ValueError(f"Duplicate data category id: {category.id!r}")
        self._by_id[category.id] = category
        return category

    def get(self, category_id: str) -> DataCategory:
        return self._by_id[category_id]

    def all(self) -> list[DataCategory]:
        return list(self._by_id.values())

    def ids(self) -> list[str]:
        return list(self._by_id)

    def in_mode(self, mode: str) -> list[DataCategory]:
        if mode not in WIPE_MODES:
            raise ValueError(f"Unknown wipe mode: {mode!r}")
        return [c for c in self._by_id.values() if mode in c.wipe_modes]

    def __len__(self) -> int:
        return len(self._by_id)


# The process-wide registry. Concrete categories are registered in a later
# chunk (2.1b); this file only establishes the mechanism.
REGISTRY = DataRegistry()
