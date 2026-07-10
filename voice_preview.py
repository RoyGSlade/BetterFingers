"""Combined "what would this utterance do" preview — the pure logic behind
the Voice Control settings test panel (docs/VOICE_CONTROL_PLAN.md scope 4):
run text through both the app-command and editing-command parsers and report
back what would happen, without executing anything.
"""
from voice_commands import parse_command
from voice_edit_commands import parse_edit_command


def preview(text, context=None):
    """Classify `text` against both the app-command and editing-command
    vocabularies without executing either. Returns a dict describing what
    (if anything) would happen, for the settings test panel."""
    return {
        "text": text,
        "app_command": _describe_app_command(parse_command(text, context)),
        "edit_command": _describe_edit_command(parse_edit_command(text)),
    }


def _describe_app_command(intent):
    if intent is None:
        return None
    return {
        "kind": intent.kind,
        "action": intent.action,
        "confidence": intent.confidence,
        "requires_confirmation": intent.requires_confirmation,
        "target": intent.target,
    }


def _describe_edit_command(cmd):
    if cmd is None:
        return None
    return {"action": cmd.action, "args": dict(cmd.args)}
