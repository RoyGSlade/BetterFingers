"""Target validation, exact previews, and partial-failure reporting for
restricted workflows (Wave 9, D-0011).

Three jobs, in the order a workflow meets them:

1. **Validation.** Every step is resolved against the *confirmed application
   registry* — the list of applications the user personally confirmed in the
   builder (``app/src/main/applicationRegistry.js``). A step naming an
   application that is not in that registry does not run; there is no other way
   for a workflow to say "this app", so a workflow cannot escape the registry.
   Folder steps are bounded to roots the caller declares, and link steps are
   limited to the three unconditional schemes plus any scheme a confirmed
   registry entry declares.

2. **Preview.** ``build_preview`` produces the exact ordered list of what will
   run, with its resolved target — not a paraphrase. "Approve" means nothing if
   the thing approved was a summary: the user has to be able to read
   ``flatpak run md.obsidian.Obsidian`` before it ever runs, and see it again
   afterwards in the same words.

3. **Partial-failure reporting.** ``summarize_run`` refuses to call a run a
   success because it started. Launching two of three applications is a
   *partial* result and is reported as one, per step, with a status code. Run
   history stores those codes and never a word the user said — see
   ``backend.services.workflow_store``.

WHY VALIDATION IS SEPARATE FROM THE SCHEMA. ``backend.domain.actions`` can say
a step is well-formed without any knowledge of this machine; this module cannot
answer anything without the registry, the profile list and the filesystem. Two
layers means the schema stays a pure, fast, testable contract and the
environment-dependent half is the only part that needs fixtures.

FAIL CLOSED. Every "I was not told what exists" path is a refusal, not a pass.
If the caller does not supply the persona list, a persona step is refused rather
than assumed valid — an unverifiable step that runs anyway is the failure this
whole wave exists to prevent.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Iterable, Optional

from backend.domain.actions import (
    ACTION_ACTIVATE_APPLICATION_PROFILE,
    ACTION_ACTIVATE_PERSONA,
    ACTION_ACTIVATE_WRITING_PRESET,
    ACTION_FOCUS_APP,
    ACTION_LAUNCH_APP,
    ACTION_OPEN_FOLDER,
    ACTION_OPEN_URI,
    ACTION_SHOW_NOTIFICATION,
    ACTION_SPEAK_CONFIRMATION,
    ACTION_WAIT_FOR_PROCESS,
    ALLOWED_URI_SCHEMES,
    Refusal,
    normalize_workflow_id,
    step_target,
)

# --- Run status codes --------------------------------------------------------
#
# The COMPLETE vocabulary a run history entry may contain for a step. Codes,
# never prose, and never anything the user said: history is a record of what the
# machine did, and one free-text field is all it takes to turn it into a
# transcript nobody consented to keeping.
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
STATUS_TIMEOUT = "timeout"
STATUS_SKIPPED = "skipped"
STATUS_REFUSED = "refused"
STATUS_UNAVAILABLE = "unavailable"

STEP_STATUS_CODES = (
    STATUS_OK,
    STATUS_FAILED,
    STATUS_NOT_FOUND,
    STATUS_TIMEOUT,
    STATUS_SKIPPED,
    STATUS_REFUSED,
    STATUS_UNAVAILABLE,
)

# A run as a whole. "partial" exists precisely so that two-of-three cannot be
# filed under either of the other two.
RUN_SUCCESS = "success"
RUN_PARTIAL = "partial"
RUN_FAILED = "failed"
RUN_BLOCKED = "blocked"

RUN_STATUS_CODES = (RUN_SUCCESS, RUN_PARTIAL, RUN_FAILED, RUN_BLOCKED)

# Launch methods a confirmed registry entry may declare, in the Linux priority
# order the launcher applies. Mirrored in app/src/main/applicationLauncher.js;
# both sides are tested against this tuple so they cannot drift apart silently.
LAUNCH_METHODS = ("desktop_entry", "flatpak", "uri", "executable", "steam")

# The registry field each method needs before it can launch anything.
LAUNCH_METHOD_FIELD = {
    "desktop_entry": "desktop_entry",
    "flatpak": "flatpak_id",
    "uri": "uri",
    "executable": "executable",
    "steam": "steam_uri",
}


@dataclass
class ValidationResult:
    ok: bool
    refusals: list = field(default_factory=list)
    preview: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "refusals": [r.to_dict() for r in self.refusals],
            "preview": list(self.preview),
        }


# --- Registry helpers --------------------------------------------------------


def index_registry(registry) -> dict:
    """``{app_id: entry}`` for **confirmed** entries only.

    Discovery results are deliberately excluded here rather than filtered by the
    caller: an unconfirmed candidate is something this machine happened to find
    on disk, and the whole point of the confirmation step is that the user, not
    a directory scan, decides what a workflow may open.
    """
    out = {}
    for entry in registry or []:
        if not isinstance(entry, dict):
            continue
        if not entry.get("confirmed"):
            continue
        app_id = normalize_workflow_id(entry.get("id"))
        if app_id:
            out[app_id] = entry
    return out


def registry_schemes(index: dict) -> set:
    """Every URI scheme a confirmed application declares, lowercased."""
    schemes = set()
    for entry in index.values():
        scheme = str(entry.get("uri_scheme") or "").strip().lower().rstrip(":")
        if scheme:
            schemes.add(scheme)
    return schemes


def describe_launch(entry) -> str:
    """The exact launch target, in the words the preview shows.

    Deliberately concrete. "Launch Obsidian" is a description of an intention;
    ``flatpak run md.obsidian.Obsidian`` is the thing that will happen, and only
    the second one can be checked by the person approving it.
    """
    method = str(entry.get("launch_method") or "").strip().lower()
    if method == "desktop_entry":
        return f"desktop entry {entry.get('desktop_entry')}"
    if method == "flatpak":
        return f"flatpak run {entry.get('flatpak_id')}"
    if method == "uri":
        return f"link {entry.get('uri')}"
    if method == "steam":
        return f"link {entry.get('steam_uri')}"
    if method == "executable":
        return f"program {entry.get('executable')}"
    return "no launch method"


def launch_is_usable(entry) -> bool:
    method = str(entry.get("launch_method") or "").strip().lower()
    field_name = LAUNCH_METHOD_FIELD.get(method)
    return bool(field_name and str(entry.get(field_name) or "").strip())


# --- Validation --------------------------------------------------------------


def _folder_is_allowed(path: str, allowed_roots: Iterable[str]) -> bool:
    """Containment by resolved path prefix, with a separator guard.

    The separator guard is the whole point: ``/home/dona`` starts with
    ``/home/don`` as a string and is a different person's folder as a path.
    """
    try:
        target = os.path.realpath(path)
    except OSError:  # pragma: no cover - realpath does not raise for plain strings
        return False
    for root in allowed_roots or ():
        try:
            resolved_root = os.path.realpath(str(root))
        except OSError:  # pragma: no cover
            continue
        if target == resolved_root:
            return True
        if target.startswith(resolved_root.rstrip(os.sep) + os.sep):
            return True
    return False


def validate_workflow(
    workflow,
    registry,
    *,
    known_profile_ids: Optional[Iterable[str]] = None,
    known_personas: Optional[Iterable[str]] = None,
    known_writing_presets: Optional[Iterable[str]] = None,
    allowed_folder_roots: Optional[Iterable[str]] = None,
    folder_exists=os.path.isdir,
) -> ValidationResult:
    """Resolve every step against this machine. Returns refusals and a preview.

    ``folder_exists`` is injectable so the folder rules are testable without
    creating directories; production callers get ``os.path.isdir``.
    """
    steps = (workflow or {}).get("steps") or []
    index = index_registry(registry)
    schemes = registry_schemes(index) | set(ALLOWED_URI_SCHEMES)

    profiles = {normalize_workflow_id(p) for p in (known_profile_ids or ())} - {""}
    personas = {str(p).strip().lower() for p in (known_personas or ())} - {""}
    presets = {str(p).strip().lower() for p in (known_writing_presets or ())} - {""}
    roots = list(allowed_folder_roots or [os.path.expanduser("~")])

    refusals: list = []
    preview: list = []

    for position, step in enumerate(steps):
        action = step.get("action")
        target = step_target(step)
        detail = ""
        summary = ""

        if action in (ACTION_LAUNCH_APP, ACTION_FOCUS_APP, ACTION_WAIT_FOR_PROCESS):
            entry = index.get(target)
            if entry is None:
                refusals.append(Refusal(
                    position, action,
                    f"“{target}” is not one of the applications you confirmed, so this "
                    "workflow cannot open it. Add it in the application list first.",
                    code="unknown_application",
                ))
                continue
            display = str(entry.get("display_name") or target)
            if action == ACTION_LAUNCH_APP:
                if not launch_is_usable(entry):
                    refusals.append(Refusal(
                        position, action,
                        f"“{display}” has no launch method recorded, so BetterFingers "
                        "does not know how to start it.",
                        code="no_launch_method",
                    ))
                    continue
                detail = describe_launch(entry)
                summary = f"Launch {display} ({detail})"
            elif action == ACTION_FOCUS_APP:
                detail = f"application {target}"
                summary = f"Bring {display} to the front"
            else:
                timeout = int(step.get("timeout_ms", 0))
                detail = f"application {target}, up to {timeout} ms"
                summary = f"Wait for {display} to be running (up to {timeout / 1000:g}s)"

        elif action == ACTION_OPEN_URI:
            scheme = target.split(":", 1)[0].lower()
            if scheme not in schemes:
                refusals.append(Refusal(
                    position, action,
                    f"Nothing you confirmed handles “{scheme}:” links, so this step has "
                    "no application to open it with.",
                    code="unregistered_scheme",
                ))
                continue
            detail = target
            summary = f"Open the link {target}"

        elif action == ACTION_OPEN_FOLDER:
            if not _folder_is_allowed(target, roots):
                refusals.append(Refusal(
                    position, action,
                    "That folder is outside the folders workflows may open.",
                    code="folder_out_of_bounds",
                ))
                continue
            if not folder_exists(target):
                refusals.append(Refusal(
                    position, action,
                    f"There is no folder at {target}.",
                    code="folder_not_found",
                ))
                continue
            detail = target
            summary = f"Open the folder {target}"

        elif action == ACTION_ACTIVATE_APPLICATION_PROFILE:
            if target not in profiles:
                refusals.append(Refusal(
                    position, action,
                    f"There is no application profile called “{target}”.",
                    code="unknown_profile",
                ))
                continue
            detail = target
            summary = f"Switch the application profile to {target}"

        elif action == ACTION_ACTIVATE_PERSONA:
            if target.strip().lower() not in personas:
                refusals.append(Refusal(
                    position, action,
                    f"There is no persona called “{target}”.",
                    code="unknown_persona",
                ))
                continue
            detail = target
            summary = f"Switch the persona to {target}"

        elif action == ACTION_ACTIVATE_WRITING_PRESET:
            if target.strip().lower() not in presets:
                refusals.append(Refusal(
                    position, action,
                    f"There is no writing preset called “{target}”.",
                    code="unknown_writing_preset",
                ))
                continue
            detail = target
            summary = f"Switch the writing preset to {target}"

        elif action == ACTION_SHOW_NOTIFICATION:
            detail = target
            summary = f"Show the notification “{target}”"

        elif action == ACTION_SPEAK_CONFIRMATION:
            detail = target
            summary = f"Say “{target}” out loud"

        else:  # pragma: no cover - compile_workflow cannot produce this
            refusals.append(Refusal(
                position, str(action or ""),
                "That is not one of the actions a workflow can perform.",
                code="unknown_action",
            ))
            continue

        preview.append({
            "position": position,
            "step_number": position + 1,
            "action": action,
            "target": target,
            "detail": detail,
            "summary": summary,
        })

    return ValidationResult(ok=not refusals, refusals=refusals, preview=preview)


def build_preview(workflow, registry, **kwargs) -> list:
    """Just the ordered preview rows. Empty when anything was refused, because a
    preview missing a step is worse than no preview: it is a promise that the
    workflow does less than it does."""
    result = validate_workflow(workflow, registry, **kwargs)
    return result.preview if result.ok else []


def preview_lines(preview) -> list:
    """``["1. Launch Obsidian (flatpak run …)", …]`` — the exact text the
    builder and the QA assertions share, so what is tested is what is shown."""
    return [f"{row['step_number']}. {row['summary']}" for row in preview or []]


# --- Partial-failure reporting ----------------------------------------------


def normalize_step_result(step, position: int, raw) -> dict:
    """One executed step, reduced to ``{position, action, target, status}``.

    An unrecognised status becomes ``failed`` rather than being passed through:
    a status code this module does not know is a code the UI cannot explain, and
    treating it as success is the one interpretation that is never safe.
    """
    status = str((raw or {}).get("status") or "").strip().lower()
    if status not in STEP_STATUS_CODES:
        status = STATUS_FAILED
    return {
        "position": position,
        "step_number": position + 1,
        "action": (step or {}).get("action", ""),
        "target": step_target(step),
        "status": status,
    }


def summarize_run(workflow, results) -> dict:
    """Fold per-step results into an honest run summary.

    THE RULE: launching two of three applications is not success. Steps that
    never ran are recorded as ``skipped`` rather than omitted, so the count of
    reported steps always equals the count of steps in the workflow and "it
    stopped after step 2" is visible rather than inferred from a short list.
    """
    steps = (workflow or {}).get("steps") or []
    raw_results = list(results or [])

    reported = []
    for position, step in enumerate(steps):
        raw = raw_results[position] if position < len(raw_results) else {"status": STATUS_SKIPPED}
        reported.append(normalize_step_result(step, position, raw))

    total = len(reported)
    completed = sum(1 for row in reported if row["status"] == STATUS_OK)
    failed = [row for row in reported if row["status"] not in (STATUS_OK, STATUS_SKIPPED)]
    skipped = [row for row in reported if row["status"] == STATUS_SKIPPED]

    if total == 0:
        status = RUN_FAILED
    elif completed == total:
        status = RUN_SUCCESS
    elif completed == 0 and not skipped:
        status = RUN_FAILED
    elif completed == 0 and skipped and not failed:
        status = RUN_BLOCKED
    else:
        status = RUN_PARTIAL

    return {
        "status": status,
        "ok": status == RUN_SUCCESS,
        "completed": completed,
        "total": total,
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "steps": reported,
    }


def describe_run(summary) -> str:
    """One sentence for the user. Never "done" unless every step is done."""
    status = (summary or {}).get("status")
    completed = (summary or {}).get("completed", 0)
    total = (summary or {}).get("total", 0)
    if status == RUN_SUCCESS:
        return f"All {total} steps finished."
    if status == RUN_BLOCKED:
        return "Nothing ran."
    if status == RUN_FAILED:
        return f"None of the {total} steps finished."
    return f"{completed} of {total} steps finished; the rest did not."
