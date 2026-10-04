"""Integrity/staging qualification with tiny fakes; no real model runtime."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from backend.stt import bundled_models as bundled
from backend.stt import bundle_staging as staging
from tools import bundle_models as cli

pytestmark = pytest.mark.smoke


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    manifest = bundled.load_manifest()
    for row in manifest["files"]:
        payload = f"fake-{row['path']}".encode()
        (source / row["path"]).write_bytes(payload)
        row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    return source, manifest


def test_happy_path(artifact):
    source, manifest = artifact
    assert bundled.verify_bundled_model(source, manifest=manifest) == bundled.VerifyResult(True)


@pytest.mark.parametrize("failure", ["missing_file", "size_mismatch", "hash_mismatch"])
def test_integrity_failure(artifact, failure):
    source, manifest = artifact
    target = source / "model.bin"
    if failure == "missing_file":
        target.unlink()
    elif failure == "size_mismatch":
        target.write_bytes(b"short")
    else:
        target.write_bytes(b"x" * target.stat().st_size)
    result = bundled.verify_bundled_model(source, manifest=manifest)
    assert (result.ok, result.code, result.path) == (False, failure, "model.bin")


@pytest.mark.parametrize("mutation", [
    lambda m: m.update(files=[]),
    lambda m: m.update(revision="main"),
    lambda m: m["files"][0].update(path="../config.json"),
    lambda m: m["files"][0].update(path="/config.json"),
    lambda m: m["files"][0].update(path="C:\\config.json"),
    lambda m: m["files"][0].update(sha256="not a hash"),
    lambda m: m["files"][0].update(size=True),
    lambda m: m["files"][0].update(path=m["files"][1]["path"]),
])
def test_corrupt_manifest(artifact, mutation):
    source, manifest = artifact
    mutation(manifest)
    assert bundled.verify_bundled_model(source, manifest=manifest).code == "manifest_invalid"


def test_unreadable_manifest(artifact, tmp_path):
    source, _ = artifact
    corrupt = tmp_path / "manifest.json"
    corrupt.write_text("{broken", encoding="utf-8")
    assert bundled.verify_bundled_model(source, manifest=corrupt).code == "manifest_invalid"
    assert bundled.verify_bundled_model(source, manifest=tmp_path / "absent.json").code == "manifest_invalid"


def test_cache_avoids_rehash_and_invalidates_on_file_or_manifest_change(artifact, monkeypatch):
    source, manifest = artifact
    real_hash = bundled._sha256
    calls = []

    def count(path):
        calls.append(path)
        return real_hash(path)

    monkeypatch.setattr(bundled, "_sha256", count)
    assert bundled.verify_bundled_model(source, manifest=manifest).ok
    assert bundled.verify_bundled_model(source, manifest=manifest).ok
    assert len(calls) == 4
    changed_manifest = copy.deepcopy(manifest)
    changed_manifest["files"][0]["sha256"] = "0" * 64
    assert bundled.verify_bundled_model(source, manifest=changed_manifest).code == "hash_mismatch"
    assert len(calls) == 4  # cached *bytes* are compared to the current manifest
    target = source / "model.bin"
    original = target.stat()
    target.write_bytes(b"x" * original.st_size)
    os.utime(target, ns=(original.st_atime_ns, original.st_mtime_ns + 1_000_000))
    assert bundled.verify_bundled_model(source, manifest=manifest).code == "hash_mismatch"
    assert len(calls) == 5


def test_change_during_hash_refused(artifact, monkeypatch):
    source, manifest = artifact
    real_hash = bundled._sha256

    def mutate(path):
        digest = real_hash(path)
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        return digest

    monkeypatch.setattr(bundled, "_sha256", mutate)
    assert bundled.verify_bundled_model(source, manifest=manifest).code == "hash_mismatch"


def test_idempotent_stage_preserves_existing_bytes(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    output = tmp_path / "output" / "base.en"
    assert staging.stage_bundled_model(output, source_dir=source, manifest=manifest) == output
    assert bundled.verify_bundled_model(output, manifest=manifest).ok
    times = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}

    def forbidden(*args, **kwargs):
        pytest.fail("idempotent staging must not copy/download")

    monkeypatch.setattr(staging.shutil, "copyfile", forbidden)
    monkeypatch.setattr(staging, "_download_snapshot", forbidden)
    assert staging.stage_bundled_model(output, manifest=manifest) == output
    assert times == {p.name: p.stat().st_mtime_ns for p in output.iterdir()}


def test_atomic_stage_failure_cleans_partial_output(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    output = tmp_path / "output" / "base.en"
    real_copy = staging.shutil.copyfile
    calls = 0

    def failing_copy(src, dest):
        nonlocal calls
        assert not output.exists()
        calls += 1
        if calls == 2:
            raise OSError("simulated disk full")
        return real_copy(src, dest)

    monkeypatch.setattr(staging.shutil, "copyfile", failing_copy)
    with pytest.raises(OSError, match="disk full"):
        staging.stage_bundled_model(output, source_dir=source, manifest=manifest)
    assert calls == 2
    assert not output.exists()
    assert list(output.parent.iterdir()) == []


def test_copied_bytes_reverified_before_publish(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    output = tmp_path / "base.en"
    real_copy = staging.shutil.copyfile

    def corrupt_copy(src, dest):
        real_copy(src, dest)
        Path(dest).write_bytes(b"x" * Path(dest).stat().st_size)

    monkeypatch.setattr(staging.shutil, "copyfile", corrupt_copy)
    with pytest.raises(staging.StagingError, match="hash_mismatch"):
        staging.stage_bundled_model(output, source_dir=source, manifest=manifest)
    assert not output.exists()


def test_invalid_existing_stage_refused_without_mutation(artifact, tmp_path):
    source, manifest = artifact
    output = tmp_path / "base.en"
    output.mkdir()
    (output / "sentinel").write_text("keep", encoding="utf-8")
    with pytest.raises(staging.StagingError, match="missing_file"):
        staging.stage_bundled_model(output, source_dir=source, manifest=manifest)
    assert (output / "sentinel").read_text() == "keep"
    assert len(list(output.iterdir())) == 1


def test_download_requires_explicit_permission(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    calls = []

    def fake_download(metadata, cache):
        calls.append((metadata["revision"], cache))
        return source

    monkeypatch.setattr(staging, "_download_snapshot", fake_download)
    with pytest.raises(staging.StagingError, match="allow-download"):
        staging.stage_bundled_model(tmp_path / "out", manifest=manifest)
    assert calls == []
    assert not (tmp_path / "out").exists()
    staging.stage_bundled_model(tmp_path / "out", allow_download=True, manifest=manifest)
    assert len(calls) == 1
    assert calls[0][0] == manifest["revision"]


def test_explicit_corrupt_source_never_downloads(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    (source / "model.bin").unlink()
    monkeypatch.setattr(staging, "_download_snapshot", lambda *a: pytest.fail("must not download"))
    with pytest.raises(staging.StagingError, match="missing_file"):
        staging.stage_bundled_model(tmp_path / "out", source_dir=source, allow_download=True, manifest=manifest)


def test_download_call_pins_revision_and_limits_files(artifact, tmp_path, monkeypatch):
    source, manifest = artifact
    calls = []

    def fake_snapshot(**kwargs):
        calls.append(kwargs)
        return str(source)

    import huggingface_hub
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot)
    assert staging._download_snapshot(manifest, tmp_path / "private-cache") == source
    assert calls == [{"repo_id": manifest["model_id"], "revision": manifest["revision"],
                      "allow_patterns": [r["path"] for r in manifest["files"]],
                      "cache_dir": str(tmp_path / "private-cache"), "local_files_only": False}]


def test_resolver_dev_override(artifact, monkeypatch):
    source, _ = artifact
    source.rename(source.parent / "base.en")
    monkeypatch.setenv("BETTERFINGERS_BUNDLED_MODELS_DIR", str(source.parent))
    assert bundled.bundled_model_dir("base.en") == source.parent / "base.en"
    assert bundled.bundled_model_dir("small.en") is None


@pytest.mark.parametrize("location", ["pyinstaller", "app_resources", "sidecar"])
def test_resolver_frozen_locations(tmp_path, monkeypatch, location):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    resource_root = tmp_path / "resources"
    sidecar = resource_root / "backend" / "betterfingers-backend"
    meipass = sidecar / "_internal"
    roots = {"pyinstaller": meipass, "app_resources": resource_root, "sidecar": sidecar}
    candidate = roots[location] / "bundled_models" / "base.en"
    candidate.mkdir(parents=True)
    monkeypatch.setattr(bundled.sys, "frozen", True, raising=False)
    monkeypatch.setattr(bundled.sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(bundled.sys, "executable", str(sidecar / "betterfingers-backend.exe"))
    assert bundled.bundled_model_dir("base.en") == candidate


def test_resolver_no_dev_implicit_cache(monkeypatch):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    monkeypatch.setattr(bundled.sys, "frozen", False, raising=False)
    assert bundled.bundled_model_dir("base.en") is None


def test_cli_failure_no_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(staging, "_download_snapshot", lambda *a: pytest.fail("network forbidden"))
    assert cli.main(["--output-dir", str(tmp_path / "out")]) == 1
    assert "--allow-download" in capsys.readouterr().err


def test_cli_passes_explicit_arguments(tmp_path, monkeypatch):
    calls = []

    def fake_stage(output, **kwargs):
        calls.append((output, kwargs))
        return Path(output)

    monkeypatch.setattr(cli, "stage_bundled_model", fake_stage)
    output = str(tmp_path / "base.en")
    assert cli.main(["--output-dir", output, "--from", "source", "--allow-download"]) == 0
    assert calls == [(output, {"source_dir": "source", "allow_download": True})]
