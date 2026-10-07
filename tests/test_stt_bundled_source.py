"""The transcriber loads the installer-bundled base.en, never the network.

Fakes only: a tiny fake bundle with a manifest that matches it, a fake
WhisperModel, and every network entry point rigged to fail the test.
"""
import hashlib
import logging
import sys
from unittest.mock import Mock

import huggingface_hub
import pytest
import requests

from backend.stt import bundled_models
from backend.stt import transcriber as stt

BUNDLE_DIR_NAME = "bundle-root-private-xyz"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    denied = Mock(side_effect=AssertionError("Network is forbidden in bundled-source tests"))
    monkeypatch.setattr(huggingface_hub, "snapshot_download", denied)
    monkeypatch.setattr(huggingface_hub, "hf_hub_download", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    yield denied
    denied.assert_not_called()


@pytest.fixture
def fake_stt(monkeypatch, tmp_path):
    monkeypatch.setattr(stt, "HF_HUB_CACHE", str(tmp_path / "hub"))
    monkeypatch.setattr(stt, "load_profile", lambda name: {"model_size": "base.en", "use_gpu": False})
    monkeypatch.setattr(stt, "ensure_cuda_libraries_on_path", lambda: [])
    constructor = Mock(return_value=object())
    monkeypatch.setattr(stt, "WhisperModel", constructor)
    return constructor


def _write_fake_bundle(model_dir, monkeypatch, prefix="fake"):
    """Four tiny files plus a manifest that matches them; the REAL verifier then runs on them."""
    model_dir.mkdir(parents=True)
    manifest = bundled_models.load_manifest()
    for row in manifest["files"]:
        payload = f"{prefix}-{row['path']}".encode()
        (model_dir / row["path"]).write_bytes(payload)
        row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(bundled_models, "load_manifest", lambda *args, **kwargs: manifest)
    return manifest


@pytest.fixture
def bundle_parts(tmp_path, monkeypatch):
    """<tmp>/<root>/base.en, selected through the dev override env var."""
    root = tmp_path / BUNDLE_DIR_NAME
    model_dir = root / "base.en"
    manifest = _write_fake_bundle(model_dir, monkeypatch)
    monkeypatch.setenv("BETTERFINGERS_BUNDLED_MODELS_DIR", str(root))
    return model_dir, manifest


@pytest.fixture
def bundle(bundle_parts):
    return bundle_parts[0]


@pytest.fixture
def bundle_manifest(bundle_parts):
    return bundle_parts[1]


def _corrupt(model_dir, failure):
    target = model_dir / "model.bin"
    if failure == "missing_file":
        target.unlink()
    elif failure == "size_mismatch":
        target.write_bytes(b"short")
    else:
        target.write_bytes(b"x" * target.stat().st_size)


def _spy_published(trans):
    published = []
    real = trans._publish_runtime_status

    def spy(state=None):
        published.append(state)
        return real(state)

    trans._publish_runtime_status = spy
    return published


def test_verified_bundle_directory_is_passed_with_local_files_only(fake_stt, bundle):
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is True
    fake_stt.assert_called_once()
    assert fake_stt.call_args.args[0] == str(bundle)
    assert fake_stt.call_args.kwargs["local_files_only"] is True
    # No HF cache exists, yet the load succeeds: the bundle is the source.
    assert trans._is_model_cached("base.en") is False


def test_model_size_is_never_mutated_and_the_snapshot_stays_valid(fake_stt, bundle):
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is True
    assert trans.model_size == "base.en"
    status = trans.get_runtime_status()
    assert status["model_size"] == "base.en" and status["model_size"] in stt.SUPPORTED_MODEL_SIZES
    assert status["state"] == "ready" and status["error_code"] is None


def test_verified_bundle_wins_even_when_download_is_allowed(monkeypatch, fake_stt, bundle):
    progress = Mock()
    monkeypatch.setattr(stt, "_set_whisper_download_state", progress)
    trans = stt.Transcriber(preload=False)
    published = _spy_published(trans)
    assert trans.ensure_loaded(allow_download=True) is True
    assert fake_stt.call_args.args[0] == str(bundle)
    assert fake_stt.call_args.kwargs["local_files_only"] is True
    assert "downloading" not in published
    progress.assert_not_called()


@pytest.mark.parametrize("allow_download", [False, True])
@pytest.mark.parametrize("failure", ["missing_file", "size_mismatch", "hash_mismatch"])
def test_corrupt_bundle_is_verification_failed_with_no_network_and_no_download(
        monkeypatch, fake_stt, bundle, failure, allow_download):
    _corrupt(bundle, failure)
    progress = Mock()
    monkeypatch.setattr(stt, "_set_whisper_download_state", progress)
    trans = stt.Transcriber(preload=False)
    published = _spy_published(trans)
    assert trans.ensure_loaded(allow_download=allow_download) is False
    status = trans.get_runtime_status()
    assert status["error_code"] == "verification_failed"
    assert status["error_state"] == "verification_failed"
    assert status["state"] == "failed" and not status["downloading"]
    assert "downloading" not in published
    progress.assert_not_called()
    fake_stt.assert_not_called()  # nothing constructed, not even from the HF cache
    assert trans.model is None and trans.active_device is None


def test_corrupt_bundle_does_not_fall_back_to_a_cached_hf_copy(monkeypatch, fake_stt, bundle):
    _corrupt(bundle, "hash_mismatch")
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_code"] == "verification_failed"
    fake_stt.assert_not_called()


def test_direct_load_of_a_corrupt_bundle_raises_a_typed_error(fake_stt, bundle):
    _corrupt(bundle, "hash_mismatch")
    trans = stt.Transcriber(preload=False)
    with pytest.raises(stt.ModelUnavailableError) as raised:
        trans._load_model(allow_download=True)
    assert raised.value.code == "verification_failed"
    assert str(bundle) not in str(raised.value)
    fake_stt.assert_not_called()


def test_cpu_fallback_recovery_uses_the_bundle(fake_stt, bundle):
    trans = stt.Transcriber(preload=False)
    model = trans._load_cpu_fallback_model()
    assert model is fake_stt.return_value
    assert fake_stt.call_args.args[0] == str(bundle)
    assert fake_stt.call_args.kwargs["device"] == "cpu"
    assert fake_stt.call_args.kwargs["local_files_only"] is True
    assert trans.model_size == "base.en"
    assert trans.active_device == "cpu"


def test_cpu_fallback_recovery_refuses_a_corrupt_bundle(fake_stt, bundle):
    _corrupt(bundle, "size_mismatch")
    trans = stt.Transcriber(preload=False)
    with pytest.raises(stt.ModelUnavailableError) as raised:
        trans._load_cpu_fallback_model()
    assert raised.value.code == "verification_failed"
    fake_stt.assert_not_called()


def test_cuda_attempt_also_loads_the_bundle_directory(fake_stt, bundle):
    class SilentModel:
        def transcribe(self, *_args, **_kwargs):
            return iter(()), None

    fake_stt.return_value = SilentModel()
    trans = stt.Transcriber(preload=False)
    trans.prefer_gpu = True
    trans._load_model()
    devices = [(call.args[0], call.kwargs["device"], call.kwargs["local_files_only"])
               for call in fake_stt.call_args_list]
    assert devices == [(str(bundle), "cuda", True)]


def test_frozen_build_resolves_the_bundle_from_meipass(monkeypatch, tmp_path, fake_stt):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    meipass = tmp_path / "frozen" / "_internal"
    model_dir = meipass / "bundled_models" / "base.en"
    _write_fake_bundle(model_dir, monkeypatch, prefix="frozen")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "frozen" / "betterfingers-backend.exe"))
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is True
    assert fake_stt.call_args.args[0] == str(model_dir)
    assert fake_stt.call_args.kwargs["local_files_only"] is True


def test_the_absolute_bundle_path_is_never_logged(caplog, fake_stt, bundle):
    caplog.set_level(logging.DEBUG)
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is True
    _corrupt(bundle, "missing_file")
    other = stt.Transcriber(preload=False)
    assert other.ensure_loaded() is False
    assert BUNDLE_DIR_NAME not in caplog.text


def test_other_model_sizes_ignore_the_bundle(monkeypatch, fake_stt, bundle):
    monkeypatch.setattr(stt, "load_profile", lambda name: {"model_size": "small.en", "use_gpu": False})
    trans = stt.Transcriber(preload=False)
    assert trans.model_size == "small.en"
    # Not cached: still the plain local-only miss, never the base.en bundle.
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_code"] == "model_missing"
    fake_stt.assert_not_called()
    # Cached: the model NAME goes to faster-whisper, exactly as before.
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    assert trans.ensure_loaded() is True
    assert fake_stt.call_args.args[0] == "small.en"
    assert fake_stt.call_args.kwargs["local_files_only"] is True


def test_no_bundle_keeps_the_h2_behaviour(monkeypatch, fake_stt):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: False)
    trans = stt.Transcriber(preload=False)
    assert trans.ensure_loaded() is False
    assert trans.get_runtime_status()["error_code"] == "model_missing"
    fake_stt.assert_not_called()
    monkeypatch.setattr(stt.Transcriber, "_is_model_cached", lambda self, size: True)
    assert trans.ensure_loaded() is True
    assert fake_stt.call_args.args[0] == "base.en"


# --- inventory ---------------------------------------------------------------


def test_inventory_counts_a_verified_bundle_as_installed(tmp_path, bundle, bundle_manifest):
    rows = {row["model_size"]: row for row in stt.list_cached_models(download_root=str(tmp_path / "empty"))}
    assert rows["base.en"]["installed"] is True
    assert rows["base.en"]["bundled"] is True
    assert rows["base.en"]["size_bytes"] == sum(f["size"] for f in bundle_manifest["files"])
    assert str(bundle) not in repr(rows)
    assert all(not row["installed"] for name, row in rows.items() if name != "base.en")


def test_inventory_does_not_count_a_corrupt_bundle(tmp_path, bundle):
    _corrupt(bundle, "hash_mismatch")
    rows = {row["model_size"]: row for row in stt.list_cached_models(download_root=str(tmp_path / "empty"))}
    assert rows["base.en"]["installed"] is False
    assert not rows["base.en"].get("bundled")


def test_inventory_counts_the_bundle_even_when_the_hub_scan_fails(monkeypatch, tmp_path, bundle):
    monkeypatch.setattr(stt, "scan_cache_dir", Mock(side_effect=RuntimeError("scan exploded")))
    rows = {row["model_size"]: row for row in stt.list_cached_models(download_root=str(tmp_path / "x"))}
    assert rows["base.en"]["installed"] is True


def test_inventory_without_a_bundle_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.delenv("BETTERFINGERS_BUNDLED_MODELS_DIR", raising=False)
    rows = stt.list_cached_models(download_root=str(tmp_path / "empty"))
    assert [row["model_size"] for row in rows] == list(stt.SUPPORTED_MODEL_SIZES)
    assert all(not row["installed"] and not row.get("bundled") for row in rows)


def test_get_models_whisper_route_reports_the_bundle_as_installed(monkeypatch, tmp_path, bundle):
    import asyncio
    import server
    from backend.api.routes.models import list_whisper_models
    monkeypatch.setattr(server, "load_profile", lambda name: {"model_size": "base.en"})
    monkeypatch.setattr(server, "list_cached_models",
                        lambda: stt.list_cached_models(download_root=str(tmp_path / "empty")))
    payload = asyncio.run(list_whisper_models())
    row = next(item for item in payload["models"] if item["model_size"] == "base.en")
    assert payload["selected_model_size"] == "base.en" and row["installed"] is True


# --- explicit download / removal of the bundled model ---------------------------


def test_explicit_download_of_a_verified_bundle_is_already_installed(fake_stt, bundle):
    result = stt.download_whisper_model("base.en", prefer_gpu=False)
    assert result["ok"] is True
    assert stt.get_whisper_download_state("base.en")["status"] == "already_installed"
    fake_stt.assert_not_called()  # nothing to fetch, nothing worth constructing


def test_explicit_download_of_a_corrupt_bundle_fails_without_any_network(fake_stt, bundle):
    _corrupt(bundle, "hash_mismatch")
    result = stt.download_whisper_model("base.en", prefer_gpu=False)
    assert result["ok"] is False
    fake_stt.assert_not_called()


def test_the_bundle_cannot_be_removed_and_is_not_unloaded(monkeypatch, tmp_path, fake_stt, bundle):
    import asyncio
    import server
    from backend.api.routes.models import delete_whisper
    monkeypatch.setattr(stt, "HF_HUB_CACHE", str(tmp_path / "hub"))
    assert stt.remove_cached_model("base.en", download_root=str(tmp_path / "hub"))["ok"] is False
    live = stt.Transcriber(preload=False)
    assert live.ensure_loaded() is True
    monkeypatch.setattr(server, "transcriber", live)
    monkeypatch.setattr(server, "remove_cached_model",
                        lambda size: stt.remove_cached_model(size, download_root=str(tmp_path / "hub")))
    result = asyncio.run(delete_whisper("base.en"))
    assert result["ok"] is False and "ships with" in result["message"]
    assert live.model is not None, "a refused removal must not unload the live model"
    assert str(bundle) not in result["message"]
