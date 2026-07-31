import os

import pytest
from fastapi import HTTPException

from project_generator import ProjectGenerator, ProjectPathRefused, resolve_target_dir

_PLAN = {"title": "Demo", "phases": []}


def test_legitimate_path_inside_root_succeeds(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = root / "my-project"

    resolved = resolve_target_dir(str(target), allowed_root=str(root))

    assert resolved == os.path.realpath(str(target))


def test_traversal_escape_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    traversal_path = str(root / ".." / "outside" / "evil")

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir(traversal_path, allowed_root=str(root))


def test_absolute_system_path_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir("/etc", allowed_root=str(root))


def test_symlink_escape_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside-secret"
    outside.mkdir()

    link = root / "escape-link"
    link.symlink_to(outside, target_is_directory=True)
    target = link / "project"

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir(str(target), allowed_root=str(root))


def test_shared_prefix_sibling_is_refused(tmp_path):
    root = tmp_path / "projects"
    root.mkdir()
    sibling = tmp_path / "projects-evil"
    sibling.mkdir()
    target = sibling / "loot"

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir(str(target), allowed_root=str(root))


def test_unresolvable_root_fails_closed(tmp_path):
    missing_root = tmp_path / "does-not-exist"

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir(str(tmp_path / "anything"), allowed_root=str(missing_root))


def test_empty_target_dir_fails_closed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    with pytest.raises(ProjectPathRefused):
        resolve_target_dir("", allowed_root=str(root))


def test_generate_project_refuses_traversal_with_honest_http_error(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("BETTERFINGERS_PROJECTS_ROOT", str(root))

    generator = ProjectGenerator()
    escape_target = str(root / ".." / "evil")

    with pytest.raises(HTTPException) as excinfo:
        generator.generate_project(_PLAN, escape_target)

    assert excinfo.value.status_code == 400
    assert not (tmp_path / "evil").exists()


def test_generate_project_succeeds_for_legitimate_path(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("BETTERFINGERS_PROJECTS_ROOT", str(root))

    generator = ProjectGenerator()
    target = str(root / "my-project")

    success, message = generator.generate_project(_PLAN, target)

    assert success is True
    assert os.path.isfile(os.path.join(target, "project.json"))
    assert os.path.isfile(os.path.join(target, "README.md"))
