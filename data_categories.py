"""Phase 2.1b (remediation) — the concrete persistent data-category inventory.

Read-only lifecycle metadata for every persistent store BetterFingers owns.
``paths``/``size``/``wipe``/``verify`` are intentionally **stubbed** here so this
chunk is reviewable as an *inventory* on its own:

* 2.1c wires real ``paths`` + ``size`` (from ``app_paths`` / ``server`` helpers).
* 2.1d wires real ``wipe`` + ``verify`` and backs ``_perform_privacy_wipe`` with
  the registry (and is where the ``cleared.history_db_wiped`` dict-normalization
  from review finding #3 lands).

Kept separate from ``data_registry.py`` (the mechanism) so the mechanism stays
dependency-free and the inventory can grow without touching it. Phase 6 moves
both under ``domain/privacy/``.
"""

from __future__ import annotations

from pathlib import Path

from data_registry import (
    DataCategory,
    DataRegistry,
    VerificationResult,
    WipeResult,
    WIPE_MODE_CONVERSATIONS as _CONV,
    WIPE_MODE_FACTORY_RESET as _FACT,
    WIPE_MODE_PERSONAL as _PERS,
)


# --- Stub callables (replaced in 2.1c / 2.1d) --------------------------------


def _no_paths() -> list[Path]:
    return []


def _no_size() -> int:
    return 0


def _unimpl_wipe() -> WipeResult:
    return WipeResult(ok=False, error="not_implemented",
                      message="wipe callable not yet wired (Phase 2.1d)")


def _unimpl_verify() -> VerificationResult:
    return VerificationResult(ok=False, detail="verify callable not yet wired (Phase 2.1d)")


# --- Wipe-mode membership (nesting-valid; see data_registry validation) -------

_CONVERSATIONS = frozenset({_CONV, _PERS, _FACT})  # cleared even by the lightest mode
_PERSONAL = frozenset({_PERS, _FACT})              # cleared by personal + factory
_FACTORY = frozenset({_FACT})                      # only a factory reset removes it
_OPT_IN = frozenset()                              # never auto-wiped (separate opt-in)


def _cat(cid, label, owner, sensitivity, retention, wipe_modes, *,
         in_report=True, in_export=False, user_text=False) -> DataCategory:
    return DataCategory(
        id=cid,
        label=label,
        owner=owner,
        sensitivity=sensitivity,
        paths=_no_paths,
        retention=retention,
        wipe_modes=wipe_modes,
        included_in_report=in_report,
        included_in_export=in_export,
        may_contain_user_text=user_text,
        size=_no_size,
        wipe=_unimpl_wipe,
        verify=_unimpl_verify,
    )


# --- The inventory -----------------------------------------------------------
# One entry per persistent store. Ordered roughly by wipe breadth (conversation
# data first, settings/electron state last). Sensitivity and may_contain_user_text
# are kept honest — under-claiming either would defeat the privacy report.

CATEGORIES: list[DataCategory] = [
    # Conversation data — removed by every wipe mode.
    _cat("raw_recordings", "Raw recordings", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS),
    _cat("drafts", "Draft JSON", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         in_export=True, user_text=True),
    _cat("history_db", "Transcription history (SQLite)", "python", "sensitive",
         "Kept until conversations are cleared.", _CONVERSATIONS,
         in_export=True, user_text=True),
    _cat("temp_audio", "Temporary audio & conversion artifacts", "python", "sensitive",
         "Ephemeral; swept on wipe and on restart.", _CONVERSATIONS),

    # Personal data — removed by personal + factory.
    _cat("cloned_voices", "Cloned voices & metadata", "python", "sensitive",
         "Kept until personal data is cleared.", _PERSONAL),
    _cat("personas", "Personas", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         in_export=True, user_text=True),
    _cat("dictionary", "Personal dictionary", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         in_export=True, user_text=True),
    _cat("macros", "Macros", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL,
         in_export=True, user_text=True),
    _cat("wake_models", "Wake models & training artifacts", "python", "sensitive",
         "Kept until personal data is cleared.", _PERSONAL),
    _cat("mcp_config", "MCP configuration", "python", "sensitive",
         "Kept until personal data is cleared; may contain credentials/tokens.", _PERSONAL),
    _cat("graph_data", "Graph data", "python", "personal",
         "Kept until personal data is cleared.", _PERSONAL, user_text=True),
    _cat("debug_log", "Debug log", "python", "personal",
         "Rolling; cleared with personal data.", _PERSONAL, user_text=True),
    _cat("sidecar_raw_log", "Sidecar backend raw log", "electron", "personal",
         "Rolling; cleared with personal data (Electron-owned).", _PERSONAL, user_text=True),
    _cat("support_report", "Support-report / diagnostic artifacts", "python", "personal",
         "Only if persisted; cleared with personal data.", _PERSONAL, user_text=True),

    # Settings / configuration — removed only by a factory reset.
    _cat("voice_presets", "Voice presets", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY, in_export=True),
    _cat("profiles", "Profiles & settings", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY, in_export=True),
    _cat("app_state", "App state & first-run marker", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY),
    _cat("overlay_position", "Overlay position", "electron", "configuration",
         "Settings; removed on factory reset (Electron-owned).", _FACTORY),
    _cat("overlay_appearance", "Overlay appearance", "electron", "configuration",
         "Settings; removed on factory reset (Electron-owned).", _FACTORY),
    _cat("model_runtime_metadata", "Model / runtime metadata", "python", "configuration",
         "Settings; removed on factory reset.", _FACTORY),

    # Opt-in — never removed by a standard wipe (separate 'also delete models').
    _cat("downloaded_models", "Downloaded models", "python", "public",
         "Opt-in only; removed via a separate 'also delete downloaded models' choice.",
         _OPT_IN),
]


def build_registry() -> DataRegistry:
    """A fresh registry populated with every category (each is validated)."""
    reg = DataRegistry()
    for category in CATEGORIES:
        reg.register(category)
    return reg
