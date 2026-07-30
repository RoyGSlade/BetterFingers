import os
import json
import logging

from fastapi import HTTPException

from log_redaction import redact_user_text


class ProjectPathRefused(Exception):
    """The requested target_dir failed the containment guard."""


def _allowed_project_root():
    """The root every generated project must resolve inside.

    ``BETTERFINGERS_PROJECTS_ROOT`` overrides the default (the user's home
    directory) for tests and alternate deployments. Fail closed: an override
    that does not resolve to a real directory yields ``None``, never a
    silent fallback to something wider.
    """
    override = os.environ.get("BETTERFINGERS_PROJECTS_ROOT")
    base = override if override else os.path.expanduser("~")
    try:
        resolved = os.path.realpath(base)
    except (OSError, ValueError):
        return None
    if not os.path.isdir(resolved):
        return None
    return resolved


def resolve_target_dir(target_dir, allowed_root=None):
    """Resolve ``target_dir`` and require it to live inside the allowed root.

    Resolve-first-compare-second: symlinks are followed via
    ``os.path.realpath`` before any comparison, so a symlink inside the
    allowed root that points outside it resolves to its real, outside
    location and is refused. Containment is checked with
    ``os.path.commonpath`` on the resolved paths, not a string prefix — a
    sibling directory that merely shares a prefix (``…/projects-evil`` vs
    ``…/projects``) has a different resolved-path component list and is
    refused. Every unresolvable or unset case fails closed.
    """
    if not target_dir or not isinstance(target_dir, str):
        raise ProjectPathRefused("No target directory was given.")

    root = allowed_root if allowed_root is not None else _allowed_project_root()
    if not root:
        raise ProjectPathRefused("No allowed project root is configured.")

    try:
        resolved_root = os.path.realpath(root)
        candidate = target_dir if os.path.isabs(target_dir) else os.path.join(resolved_root, target_dir)
        resolved_target = os.path.realpath(candidate)
    except (OSError, ValueError) as exc:
        raise ProjectPathRefused(f"Target directory could not be resolved: {exc}")

    if resolved_target != resolved_root:
        try:
            common = os.path.commonpath([resolved_target, resolved_root])
        except ValueError:
            raise ProjectPathRefused("Target directory is outside the allowed project root.")
        if common != resolved_root:
            raise ProjectPathRefused("Target directory is outside the allowed project root.")

    return resolved_target


class ProjectGenerator:
    def __init__(self):
        # We can store templates here if needed
        pass

    def generate_project(self, plan: dict, target_dir: str):
        """
        Generates the folder structure and basic files for the project based on the plan.
        """
        try:
            safe_target = resolve_target_dir(target_dir)
        except ProjectPathRefused as exc:
            logging.warning(f"Refused project target_dir {target_dir!r}: {exc}")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        logging.info(f"Generating project '{redact_user_text(plan.get('title'))}' in {safe_target}")

        try:
            # 1. Create Root Directory
            os.makedirs(safe_target, exist_ok=True)

            # 2. Create project.json
            project_file = os.path.join(safe_target, "project.json")
            if not os.path.exists(project_file):
                project_data = {
                    "name": plan.get("title", "New Project"),
                    "version": "0.1.0",
                    "phases": plan.get("phases", [])
                }
                with open(project_file, 'w') as f:
                    json.dump(project_data, f, indent=4)

            # 3. Create README.md
            readme_file = os.path.join(safe_target, "README.md")
            if not os.path.exists(readme_file):
                with open(readme_file, 'w') as f:
                    f.write(f"# {plan.get('title')}\n\n")
                    f.write("## Plan\n")
                    for phase in plan.get("phases", []):
                        f.write(f"### {phase.get('name')}\n")
                        for task in phase.get("tasks", []):
                            f.write(f"- [ ] {task}\n")

            # 4. Create Source Folders (scaffolding)
            # Standard scaffold for now
            folders = ["src", "docs", "assets"]
            for folder in folders:
                os.makedirs(os.path.join(safe_target, folder), exist_ok=True)

            return True, "Project generated successfully."

        except Exception as e:
            logging.error(f"Project generation failed: {e}")
            return False, str(e)

project_generator = ProjectGenerator()
