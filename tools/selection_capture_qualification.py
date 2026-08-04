#!/usr/bin/env python3
"""Operator qualification for BetterFingers selected-text rewrite.

This tool deliberately does not read or write the clipboard and does not send
keyboard input. The operator performs the desktop actions while this command
records observed outcomes. Evidence contains no selected or rewritten text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as platform_module
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping


SENTINEL_TEXT = (
    "BetterFingers selection qualification sentinel: select this complete sentence."
)
DEFAULT_HOTKEY = "Ctrl+Alt+R"
STATUS_VALUES = ("PASS", "FAIL", "UNTESTED")
WORKFLOW_CHECK_NAMES = (
    "selected-text capture",
    "rewrite opens review-only draft",
    "clipboard is restored",
    "no automatic send occurs",
)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _discover_repo_commit(repo_root: Path | None = None) -> str | None:
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    commit = result.stdout.strip()
    return commit if result.returncode == 0 and commit else None


def _discover_app_version(repo_root: Path | None = None) -> str | None:
    root = repo_root or Path(__file__).resolve().parents[1]
    try:
        value = (root / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value or None


def _artifact_metadata(path: Path | None) -> dict | None:
    if path is None:
        return None
    try:
        size = path.stat().st_size
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return {"name": path.name, "status": "UNTESTED"}
    return {
        "name": path.name,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
        "status": "PASS",
    }


def collect_metadata(
    *,
    artifact: Path | None = None,
    model_identifier: str | None = None,
    runtime_identifier: str | None = None,
) -> dict:
    """Collect only discovered or operator-supplied run metadata."""
    root = Path(__file__).resolve().parents[1]
    metadata = {
        "os_build": platform_module.platform(aliased=True) or None,
        "python_version": platform_module.python_version() or None,
        "repo_commit": _discover_repo_commit(root),
        "app_version": _discover_app_version(root),
        "artifact": _artifact_metadata(artifact),
        "model_identifier": str(model_identifier).strip() if model_identifier else None,
        "runtime_identifier": str(runtime_identifier).strip() if runtime_identifier else None,
    }
    return {key: value for key, value in metadata.items() if value not in (None, "")}


def metadata_checks(metadata: dict) -> list[dict]:
    checks = []
    for name, key in (
        ("OS build recorded", "os_build"),
        ("Python version recorded", "python_version"),
        ("repository commit recorded", "repo_commit"),
        ("app version recorded", "app_version"),
        ("artifact metadata recorded", "artifact"),
        ("model identifier supplied", "model_identifier"),
        ("runtime identifier supplied", "runtime_identifier"),
    ):
        present = key in metadata and metadata[key]
        checks.append(_check(name, "PASS" if present else "UNTESTED", "recorded" if present else "not supplied or not discoverable"))
    return checks


def _session_type(environ: Mapping[str, str]) -> str:
    # Match platform_capabilities.py: a live Wayland display wins even when
    # the session type variable is stale or reports x11.
    if environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    explicit = str(environ.get("XDG_SESSION_TYPE", "")).strip().lower()
    if explicit in {"wayland", "x11"}:
        return explicit
    if environ.get("DISPLAY"):
        return "x11"
    return "unknown"


def detect_environment(
    *,
    system: str | None = None,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = _which,
) -> dict:
    """Return a privacy-safe live platform/session/tool snapshot.

    ``system``, ``environ`` and ``which`` are injectable so tests can model
    Windows, X11 and Wayland without touching the host clipboard or display.
    """
    env = dict(os.environ if environ is None else environ)
    system_name = (system or platform_module.system() or "unknown").strip().lower()
    if system_name == "windows" or (sys.platform == "win32" and system is None):
        family = "windows"
    elif system_name == "linux":
        family = "linux"
    elif system_name in {"darwin", "mac", "macos"}:
        family = "macos"
    else:
        family = system_name or "unknown"

    session = "windows-desktop" if family == "windows" else _session_type(env)
    display_name = {"x11": "DISPLAY", "wayland": "WAYLAND_DISPLAY"}.get(session)
    display_present = (
        True
        if family != "linux"
        else bool(env.get(display_name))
        if display_name is not None
        else bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))
    )
    candidates = (
        "xclip",
        "xsel",
        "wl-copy",
        "wl-paste",
        "xdotool",
        "wtype",
        "ydotool",
    )
    tools = {}
    for name in candidates:
        path = which(name)
        tools[name] = {"available": bool(path), "path": path}

    if family == "windows":
        clipboard_backend = {"name": "native", "available": True, "required": []}
        copy_trigger_backend = {"name": "native-keyboard", "available": True, "required": []}
        hotkey_backend = {
            "name": "native-global-hotkey",
            "available": True,
            "required": [],
        }
        typing_backend = {
            "name": "native-or-clipboard",
            "available": True,
            "required": [],
        }
    elif family == "linux" and session == "wayland":
        display_required = [] if display_present else ["WAYLAND_DISPLAY"]
        clipboard_tools = ["wl-copy", "wl-paste"]
        clipboard_backend = {
            "name": "wl-clipboard",
            "available": display_present and all(tools[name]["available"] for name in clipboard_tools),
            "required": display_required + clipboard_tools,
        }
        typing_name = "wtype" if tools["wtype"]["available"] else (
            "ydotool" if tools["ydotool"]["available"] else "none"
        )
        typing_backend = {
            "name": typing_name,
            "available": display_present and typing_name != "none",
            "required": display_required + (
                ["wtype or ydotool"] if typing_name == "none" else [typing_name]
            ),
        }
        copy_trigger_name = "wtype" if tools["wtype"]["available"] else (
            "ydotool" if tools["ydotool"]["available"] else "none"
        )
        copy_trigger_backend = {
            "name": copy_trigger_name,
            "available": display_present and copy_trigger_name != "none",
            "required": display_required + ([] if copy_trigger_name != "none" else ["wtype or ydotool"]),
        }
        # BetterFingers' global keyboard hook is not assumed to work on
        # Wayland. A compositor-specific permission or portal must be proven
        # by the operator, so this is recorded as unknown even with wl-clipboard.
        hotkey_backend = {
            "name": "global-hotkey-unknown-on-wayland",
            "available": False,
            "required": ["compositor/global-hotkey permission"],
        }
    elif family == "linux" and session == "x11":
        display_required = [] if display_present else ["DISPLAY"]
        clipboard_name = "xclip" if tools["xclip"]["available"] else (
            "xsel" if tools["xsel"]["available"] else "none"
        )
        clipboard_backend = {
            "name": clipboard_name,
            "available": display_present and clipboard_name != "none",
            "required": display_required + (
                ["xclip or xsel"] if clipboard_name == "none" else [clipboard_name]
            ),
        }
        hotkey_backend = {
            "name": "X11-global-hotkey",
            "available": display_present,
            "required": ["DISPLAY"],
        }
        typing_name = (
            "xdotool" if tools["xdotool"]["available"] else "clipboard-paste"
        )
        typing_backend = {
            "name": typing_name,
            "available": display_present and (clipboard_backend["available"] or tools["xdotool"]["available"]),
            "required": display_required + ([] if typing_name == "clipboard-paste" else [typing_name]),
        }
        copy_trigger_backend = {
            "name": "xdotool" if tools["xdotool"]["available"] else "none",
            "available": display_present and tools["xdotool"]["available"],
            "required": display_required + ([] if tools["xdotool"]["available"] else ["xdotool"]),
        }
    elif family == "macos":
        clipboard_backend = {"name": "native", "available": True, "required": []}
        hotkey_backend = {
            "name": "unsupported-on-macos",
            "available": False,
            "required": ["macOS selection capture support"],
        }
        typing_backend = {"name": "unsupported-on-macos", "available": False, "required": []}
        copy_trigger_backend = {
            "name": "unsupported-on-macos",
            "available": False,
            "required": ["macOS selection capture support"],
        }
    else:
        clipboard_backend = {"name": "unknown", "available": False, "required": []}
        hotkey_backend = {"name": "unknown", "available": False, "required": []}
        typing_backend = {"name": "unknown", "available": False, "required": []}
        copy_trigger_backend = {"name": "unknown", "available": False, "required": []}

    return {
        "platform": family,
        "platform_name": system_name,
        "session_type": session,
        "display_present": display_present,
        "clipboard_backend": clipboard_backend,
        "copy_trigger_backend": copy_trigger_backend,
        "hotkey_backend": hotkey_backend,
        "typing_backend": typing_backend,
        "tools": tools,
        "default_selection_rewrite_hotkey": DEFAULT_HOTKEY,
    }


def _check(name: str, status: str, detail: str, *, evidence: str | None = None) -> dict:
    if status not in STATUS_VALUES:
        raise ValueError(f"invalid status {status!r}")
    result = {"name": name, "status": status, "detail": detail}
    if evidence:
        result["evidence"] = evidence
    return result


def initial_checks(environment: dict) -> list[dict]:
    """Convert live introspection into checks; no product workflow is implied."""
    backend = environment["clipboard_backend"]
    desktop_required = (
        environment.get("platform") == "linux"
        and environment.get("session_type") in {"x11", "wayland"}
    )
    display_missing = desktop_required and not environment.get("display_present", False)
    backend_status = (
        "PASS"
        if backend["available"]
        else "UNTESTED"
        if display_missing
        else "FAIL"
    )
    backend_detail = (
        f"{backend['name']} detected"
        if backend["available"]
        else f"missing required clipboard backend: {', '.join(backend['required']) or 'native support'}"
    )
    if display_missing:
        backend_detail = (
            f"active {('DISPLAY' if environment['session_type'] == 'x11' else 'WAYLAND_DISPLAY')} "
            "is missing; desktop capability was not tested"
        )
    copy_trigger_available = environment["copy_trigger_backend"]["available"]
    copy_trigger_status = (
        "PASS"
        if copy_trigger_available
        else "UNTESTED"
        if display_missing
        else "FAIL"
    )
    copy_trigger_detail = (
        environment["copy_trigger_backend"]["name"]
        if copy_trigger_available
        else (
            f"active {('DISPLAY' if environment['session_type'] == 'x11' else 'WAYLAND_DISPLAY')} "
            "is missing; desktop capability was not tested"
            if display_missing
            else environment["copy_trigger_backend"]["name"]
        )
    )
    typing_available = environment["typing_backend"]["available"]
    typing_status = (
        "PASS"
        if typing_available
        else "UNTESTED"
    )
    typing_detail = (
        environment["typing_backend"]["name"]
        if typing_available
        else f"missing required clipboard backend: {', '.join(backend['required']) or 'native support'}"
    )
    if display_missing:
        typing_detail = (
            f"active {('DISPLAY' if environment['session_type'] == 'x11' else 'WAYLAND_DISPLAY')} "
            "is missing; desktop capability was not tested"
        )
    return [
        _check(
            "platform/session detected",
            "PASS",
            f"{environment['platform_name']} / {environment['session_type']}",
            evidence="local platform and environment inspection",
        ),
        _check("clipboard backend available", backend_status, backend_detail),
        _check(
            "copy trigger backend available",
            copy_trigger_status,
            copy_trigger_detail,
            evidence="argv-only Ctrl+C trigger capability; desktop copy still requires an observed workflow check",
        ),
        _check(
            "global hotkey path available",
            "PASS" if environment["hotkey_backend"]["available"] else "UNTESTED",
            environment["hotkey_backend"]["name"],
            evidence="capability discovery only; desktop hotkey still requires an observed workflow check",
        ),
        _check(
            "typing/injection path available",
            typing_status,
            typing_detail,
        ),
    ]


def _prompt_status(label: str, instruction: str, input_fn: Callable[[str], str] = input) -> dict:
    print(f"\n{label}\n{instruction}")
    print("Enter p=PASS (you observed it), f=FAIL, or u=UNTESTED:", end=" ")
    try:
        answer = input_fn("").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "u"
    status = {"p": "PASS", "f": "FAIL", "u": "UNTESTED"}.get(answer, "UNTESTED")
    detail = {
        "PASS": "operator observed the expected result",
        "FAIL": "operator observed the expected result did not occur",
        "UNTESTED": "no observed result recorded",
    }[status]
    return _check(label, status, detail)


def workflow_instructions(environment: dict) -> list[str]:
    platform_name = environment["platform"]
    if platform_name == "windows":
        apps = ["Notepad", "a browser text area or rich editor"]
        prerequisite = (
            "Use an interactive desktop session; BetterFingers must be running "
            "with selection rewrite hotkey enabled."
        )
    elif environment["session_type"] == "x11":
        apps = ["a GTK/Qt editor (for example Kate or gedit)", "a browser text area"]
        prerequisite = "X11 DISPLAY must be active; install xclip or xsel plus xdotool before launching BetterFingers."
    elif environment["session_type"] == "wayland":
        apps = ["a native Wayland editor (for example GNOME Text Editor or KWrite)", "Firefox/Chromium"]
        prerequisite = (
            "Install wl-clipboard (wl-copy and wl-paste) plus wtype or ydotool. "
            "Global hotkeys and injection remain compositor/tool dependent."
        )
    else:
        apps = [
            "the first representative desktop text application",
            "the second representative desktop text application",
        ]
        prerequisite = "The platform/session is not recognized; do not infer support from this run."
    environment["representative_apps"] = apps
    return [
        prerequisite,
        f"In {' and '.join(apps)}, create or locate this exact sentinel (do not use private text): {SENTINEL_TEXT!r}",
        f"Select the complete sentinel, then press BetterFingers' {DEFAULT_HOTKEY} selection-rewrite hotkey.",
        "Observe the BetterFingers status/review surface. It must show a "
        "selected-text capture and a rewritten draft for review.",
        "Do not press Accept, Send, Apply, or any delivery control during this qualification.",
        "After the review appears, verify the clipboard still contains the value "
        "you had before the action (compare privately; never paste it into evidence).",
        "Repeat the capture and review-only checks in the second representative "
        "application. Record each target's result separately and PASS only for "
        "results you actually observed.",
    ]


def run_operator_checks(environment: dict, *, interactive: bool = True) -> list[dict]:
    instructions = workflow_instructions(environment)
    targets = list(environment.get("representative_apps", []))
    if not interactive:
        return [
            {
                "target": target,
                "checks": [
                    _check(name, "UNTESTED", "interactive desktop observation not run")
                    for name in WORKFLOW_CHECK_NAMES
                ],
            }
            for target in targets
        ]
    print("\nOperator procedure")
    for number, instruction in enumerate(instructions, 1):
        print(f"{number}. {instruction}")
    outcomes = []
    for target in targets:
        print(f"\nTarget application: {target}")
        outcomes.append(
            {
                "target": target,
                "checks": [
                    _prompt_status(
                        "selected-text capture",
                        "Select the sentinel, trigger the hotkey, and confirm BetterFingers reports selection capture.",
                    ),
                    _prompt_status(
                        "rewrite opens review-only draft",
                        "Confirm the rewritten output is visible for review and the source text is not automatically delivered.",
                    ),
                    _prompt_status(
                        "clipboard is restored",
                        "Confirm your pre-existing clipboard value is unchanged after capture/injection.",
                    ),
                    _prompt_status(
                        "no automatic send occurs",
                        "Confirm no message/send/apply action happened without your explicit review action.",
                    ),
                ],
            }
        )
    return outcomes


def _privacy_safe_environment(environment: dict) -> dict:
    # Keep absolute executable paths out of portable evidence; availability and
    # basename are enough for diagnosis and avoid leaking local usernames.
    result = json.loads(json.dumps(environment))
    for tool in result.get("tools", {}).values():
        if tool.get("path"):
            tool["path"] = Path(tool["path"]).name
    return result


def _target_records(checks: object) -> list[Mapping] | None:
    if not isinstance(checks, list) or not checks:
        return None
    if not all(
        isinstance(target, Mapping) and "target" in target and "checks" in target
        for target in checks
    ):
        return None
    return checks


def _observed_workflow_checks(checks: object) -> list[Mapping]:
    if not isinstance(checks, list):
        return []
    records = _target_records(checks)
    if records is not None:
        flattened = []
        for target in records:
            if isinstance(target.get("checks"), list):
                flattened.extend(
                    check for check in target["checks"] if isinstance(check, Mapping)
                )
        return flattened
    return [check for check in checks if isinstance(check, Mapping)]


def _canonical_target_passes(target: Mapping) -> bool:
    target_checks = target.get("checks")
    if not isinstance(target_checks, list) or len(target_checks) != len(WORKFLOW_CHECK_NAMES):
        return False
    names = [
        check.get("name")
        for check in target_checks
        if isinstance(check, Mapping)
    ]
    return (
        len(names) == len(WORKFLOW_CHECK_NAMES)
        and set(names) == set(WORKFLOW_CHECK_NAMES)
        and all(
            isinstance(check, Mapping) and check.get("status") == "PASS"
            for check in target_checks
        )
    )


def _complete_workflow_observation(environment: dict, checks: object) -> bool:
    """Only a complete, canonical two-target observation can authorize PASS."""
    records = _target_records(checks)
    expected_targets = environment.get("representative_apps")
    target_names_valid = (
        all(isinstance(target.get("target"), str) and target["target"].strip() for target in records)
        if records is not None
        else False
    )
    expected_names_valid = (
        expected_targets is None
        or (
            isinstance(expected_targets, list)
            and len(expected_targets) == 2
            and all(isinstance(target, str) and target.strip() for target in expected_targets)
        )
    )
    if (
        records is None
        or len(records) != 2
        or not target_names_valid
        or not expected_names_valid
        or len({target["target"] for target in records}) != 2
        or (
            expected_targets is not None
            and sorted(target["target"] for target in records) != sorted(expected_targets)
        )
    ):
        return False
    for target in records:
        if not _canonical_target_passes(target):
            return False
    return (
        not any(check["status"] == "FAIL" for check in initial_checks(environment))
        and (
            environment.get("platform") != "linux"
            or bool(environment.get("display_present"))
        )
    )


def build_evidence(environment: dict, checks: list[dict]) -> dict:
    metadata = dict(environment.get("metadata") or {})
    if not metadata:
        metadata = collect_metadata()
    initial = initial_checks(environment)
    records = _target_records(checks)
    if records is not None:
        workflow_targets = [
            {
                **target,
                "checks": target["checks"] if isinstance(target["checks"], list) else [],
            }
            for target in records
        ]
    else:
        workflow_targets = [{
            "target": "representative applications (aggregate)",
            "checks": checks if isinstance(checks, list) else [],
        }]
    observed_checks = _observed_workflow_checks(checks)
    observed_statuses = [check.get("status") for check in observed_checks]
    if "FAIL" in observed_statuses:
        overall = "FAIL"
    elif _complete_workflow_observation(environment, checks):
        overall = "PASS"
    else:
        overall = "UNTESTED"
    return {
        "schema": "betterfingers.selection_capture_qualification.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "sentinel": {
            "sha256": hashlib.sha256(SENTINEL_TEXT.encode("utf-8")).hexdigest(),
            "char_count": len(SENTINEL_TEXT),
            "text_recorded": False,
        },
        "environment": _privacy_safe_environment(environment),
        "metadata": metadata,
        "metadata_checks": metadata_checks(metadata),
        "capability_checks": initial,
        "workflow_targets": workflow_targets,
        "workflow_checks": observed_checks,
        # Keep the old combined key for consumers while exposing separate
        # capability/workflow collections for release evidence.
        "checks": initial + observed_checks,
        "observed_check_count": sum(status == "PASS" for status in observed_statuses),
        "failed_check_count": sum(status == "FAIL" for status in observed_statuses),
        "untested_check_count": sum(status == "UNTESTED" for status in observed_statuses),
        "workflow_target_count": len(workflow_targets),
        "workflow_target_pass_count": sum(
            _canonical_target_passes(target)
            for target in workflow_targets
        ),
        "privacy": {
            "selected_text_recorded": False,
            "rewritten_text_recorded": False,
            "clipboard_contents_recorded": False,
            "absolute_paths_recorded": False,
        },
    }


def render_markdown(evidence: dict) -> str:
    env = evidence["environment"]
    lines = [
        "# BetterFingers selected-text qualification",
        "",
        f"- Overall: **{evidence['overall']}**",
        f"- Generated (UTC): `{evidence['generated_at_utc']}`",
        f"- Platform/session: `{env['platform_name']} / {env['session_type']}`",
        f"- Sentinel: `{evidence['sentinel']['char_count']} characters; sha256 {evidence['sentinel']['sha256']}`",
        f"- Observed workflow checks: `{evidence['observed_check_count']}` pass, `{evidence['failed_check_count']}` fail, `{evidence['untested_check_count']}` untested",
        "",
        "> PASS means the operator observed the expected result. UNTESTED is not a pass.",
        "> This report intentionally contains no selected text, rewritten text, or clipboard contents.",
        "",
        "## Capability snapshot",
        "",
        "| Capability | Backend | Available | Required |",
        "|---|---|---:|---|",
        f"| Clipboard | `{env['clipboard_backend']['name']}` | "
        f"`{env['clipboard_backend']['available']}` | "
        f"{', '.join(env['clipboard_backend']['required']) or 'native'} |",
        f"| Copy trigger | `{env['copy_trigger_backend']['name']}` | "
        f"`{env['copy_trigger_backend']['available']}` | "
        f"{', '.join(env['copy_trigger_backend']['required']) or 'native'} |",
        f"| Global hotkey | `{env['hotkey_backend']['name']}` | "
        f"`{env['hotkey_backend']['available']}` | "
        f"{', '.join(env['hotkey_backend']['required']) or 'none'} |",
        f"| Typing/injection | `{env['typing_backend']['name']}` | "
        f"`{env['typing_backend']['available']}` | "
        f"{', '.join(env['typing_backend']['required']) or 'none'} |",
        "",
        "## Checks",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for check in evidence["checks"]:
        detail = str(check.get("detail", "")).replace("|", "\\|")
        lines.append(f"| {check.get('name', 'UNTESTED')} | **{check.get('status', 'UNTESTED')}** | {detail} |")
    lines += [
        "",
        "## Run metadata",
        "",
        "| Field | Value | Status |",
        "|---|---|---|",
    ]
    metadata = evidence.get("metadata", {})
    for key, label in (
        ("os_build", "OS build"),
        ("python_version", "Python version"),
        ("repo_commit", "Repository commit"),
        ("app_version", "App version"),
        ("model_identifier", "Model identifier"),
        ("runtime_identifier", "Runtime identifier"),
    ):
        lines.append(f"| {label} | `{metadata.get(key, 'UNTESTED')}` | **{'PASS' if key in metadata else 'UNTESTED'}** |")
    artifact = metadata.get("artifact")
    if artifact:
        artifact_value = f"{artifact.get('name', 'UNTESTED')}; {artifact.get('size_bytes', 'UNTESTED')} bytes; sha256 {artifact.get('sha256', 'UNTESTED')}"
        lines.append(f"| Artifact | `{artifact_value}` | **{artifact.get('status', 'UNTESTED')}** |")
    else:
        lines.append("| Artifact | `UNTESTED` | **UNTESTED** |")
    lines += [
        "",
        "## Per-target workflow outcomes",
        "",
        "| Target application | Check | Status | Detail |",
        "|---|---|---|---|",
    ]
    for target in evidence.get("workflow_targets", []):
        for check in target.get("checks", []):
            detail = str(check.get("detail", "")).replace("|", "\\|")
            lines.append(
                f"| {target.get('target', 'UNTESTED')} | {check.get('name', 'UNTESTED')} | "
                f"**{check.get('status', 'UNTESTED')}** | {detail} |"
            )
    lines += [
        "",
        "## Operator safety",
        "",
        "- Keep private application text out of this report; use only the supplied sentinel.",
        "- Do not accept, apply, send, or otherwise deliver the rewritten draft during the check.",
        "- Verify clipboard restoration privately, without copying its contents into a terminal or report.",
        "- On Wayland, a missing compositor/global-hotkey path is UNTESTED for "
        "the product flow; do not convert it to PASS because wl-clipboard is "
        "installed.",
        "",
        "## Reproduction",
        "",
        "```text",
        "python3 tools/selection_capture_qualification.py",
        "```",
    ]
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("selection-qualification-evidence"),
        help="directory for privacy-safe JSON and Markdown evidence",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="record desktop workflow checks as UNTESTED without touching the desktop",
    )
    parser.add_argument("--artifact", type=Path, help="optional packaged artifact to hash")
    parser.add_argument("--model-id", help="operator-supplied model identifier")
    parser.add_argument("--runtime-id", help="operator-supplied runtime identifier")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    environment = detect_environment()
    environment["metadata"] = collect_metadata(
        artifact=args.artifact,
        model_identifier=args.model_id,
        runtime_identifier=args.runtime_id,
    )
    print("BetterFingers selected-text qualification")
    print(f"Detected: {environment['platform_name']} / {environment['session_type']}")
    print("No clipboard reads/writes or synthetic key presses are performed by this tool.")
    checks = run_operator_checks(environment, interactive=not args.non_interactive)
    evidence = build_evidence(environment, checks)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "selection-capture-qualification.json"
    markdown_path = args.output_dir / "selection-capture-qualification.md"
    json_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(evidence), encoding="utf-8")
    print(f"Overall: {evidence['overall']}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0 if evidence["overall"] in {"PASS", "UNTESTED"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
