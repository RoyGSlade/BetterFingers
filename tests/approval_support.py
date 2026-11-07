"""Test-only helpers: sign approval tickets the way the Electron broker does.

Production code has no signer on the Python side (only the Electron main process
may mint approvals). The tests need one to prove the verifier accepts exactly
what the broker produces and nothing else, so it lives here, next to the tests,
and uses the same wire format as ``app/src/main/approvalBroker.js``.
"""
import base64
import hashlib
import hmac
import json
import os
import time

from backend.services import approvals

TEST_KEY = bytes(range(32))


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def sign_ticket(purpose, subject, bind, *, secret=TEST_KEY, now=None, ttl=60, nonce=None, version=1,
                extra=None):
    moment = int(time.time() if now is None else now)
    payload = {
        "v": version,
        "purpose": purpose,
        "subject": str(subject),
        "bind": {str(k): str(v) for k, v in bind.items()},
        "nonce": nonce or os.urandom(16).hex(),
        "iat": moment,
        "exp": moment + ttl,
    }
    payload.update(extra or {})
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return {"payload": payload_b64, "sig": sig}


def workflow_ticket(workflow_id, preview_lines, steps, **kw):
    return sign_ticket(approvals.PURPOSE_WORKFLOW_APPROVE, workflow_id,
                       approvals.workflow_bind(preview_lines, steps), **kw)


def persona_ticket(persona, raw, out, before=(), after=None, **kw):
    """A persona.example ticket. Round 4, item 5: it binds the complete learned list before and
    after too; by default, adding (raw, out) to an empty list."""
    after = [(raw.strip(), out.strip())] if after is None else after
    return sign_ticket(approvals.PURPOSE_PERSONA_EXAMPLE, persona,
                       approvals.learned_add_bind(persona, raw, out, list(before), list(after)), **kw)


def send_ticket(draft_id, action, text, open_chat=False, **kw):
    return sign_ticket(approvals.PURPOSE_DRAFT_SEND, draft_id,
                       approvals.draft_send_bind(action, text, open_chat), **kw)


def few_shot_ticket(persona, before, after, **kw):
    """A persona.few_shot ticket for changing ``before`` (the stored list) into ``after``."""
    return sign_ticket(approvals.PURPOSE_PERSONA_FEW_SHOT, persona,
                       approvals.persona_few_shot_bind(persona, before, after), **kw)
