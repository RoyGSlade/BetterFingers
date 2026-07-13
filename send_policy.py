"""Pure send/review-gating policy, split out of server.py (M6).

No I/O and no server state: given a draft's confidence, length, and the active
config, decide whether it may auto-send or must be reviewed first. The config
readers that load the active profile (get_active_*, update_draft_review_fields)
stay in server.py — tests patch server.load_profile and expect those to honor
it. server.py re-imports these so server.evaluate_confidence_send_policy /
server.count_draft_tokens keep resolving.
"""


def count_draft_tokens(text):
    return len(str(text or "").split())


def evaluate_confidence_send_policy(confidence, long_text, gate_reasons, config):
    """Decide whether a draft may auto-send or must be reviewed first (Phase 12).

    Pure — no I/O. Returns ``{"auto_send_ok": bool, "force_review": bool,
    "reason": str}``. Only active when ``confidence_force_review_enabled``:

    - a no-audio gate fired                    -> force review ("audio_gate")
    - the draft is long                        -> force review ("long_draft")
    - the ASR confidence score is missing       -> force review ("confidence_missing")
    - score < confidence_force_review_below      -> force review ("low_confidence")
    - score >= confidence_auto_send_above         -> auto-send eligible
    - anything in between                        -> neither ("confidence_moderate")

    ``auto_send_ok`` gates the auto-send-on-accept path in the review overlay, so
    a mumbled or long utterance never silently injects even in ``auto_send`` mode.
    """
    cfg = config if isinstance(config, dict) else {}
    enabled = bool(cfg.get("confidence_force_review_enabled", True))
    try:
        below = float(cfg.get("confidence_force_review_below", 0.55))
    except (TypeError, ValueError):
        below = 0.55
    try:
        above = float(cfg.get("confidence_auto_send_above", 0.85))
    except (TypeError, ValueError):
        above = 0.85

    score = confidence.get("score") if isinstance(confidence, dict) else None

    if not enabled:
        return {"auto_send_ok": True, "force_review": False, "reason": ""}
    if gate_reasons:
        return {"auto_send_ok": False, "force_review": True, "reason": "audio_gate"}
    if long_text:
        return {"auto_send_ok": False, "force_review": True, "reason": "long_draft"}
    if score is None:
        return {"auto_send_ok": False, "force_review": True, "reason": "confidence_missing"}
    try:
        score = float(score)
    except (TypeError, ValueError):
        return {"auto_send_ok": False, "force_review": True, "reason": "confidence_missing"}
    if score < below:
        return {"auto_send_ok": False, "force_review": True, "reason": "low_confidence"}
    if score >= above:
        return {"auto_send_ok": True, "force_review": False, "reason": ""}
    return {"auto_send_ok": False, "force_review": False, "reason": "confidence_moderate"}
