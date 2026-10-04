"""Build-only staging implementation. Runtime imports never acquire models."""
import os
from pathlib import Path
import shutil
import tempfile

from backend.stt.bundled_models import load_manifest, verify_bundled_model


class StagingError(ValueError):
    pass


def _download_snapshot(metadata, cache_dir):
    # Import only after the caller explicitly authorizes network acquisition.
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(
        repo_id=metadata["model_id"], revision=metadata["revision"],
        allow_patterns=[row["path"] for row in metadata["files"]],
        cache_dir=str(cache_dir), local_files_only=False,
    ))


def _require_verified(directory, metadata):
    result = verify_bundled_model(directory, manifest=metadata)
    if not result.ok:
        raise StagingError(f"{result.code}: {result.path or 'manifest'}")


def stage_bundled_model(output_dir, *, source_dir=None, allow_download=False, manifest=None):
    """Publish one fully verified directory with a same-filesystem rename.

    output_dir is the exact model directory (normally ROOT/base.en). Existing
    valid output is a no-op; invalid output is refused without replacing it.
    Explicit source errors never fall back to a download. No writes to HF's
    default cache: opted-in acquisition uses a temporary build-owned cache.
    """
    metadata = load_manifest(manifest)
    output = Path(output_dir).absolute()
    if output.exists():
        _require_verified(output, metadata)
        return output
    if source_dir is None and not allow_download:
        raise StagingError("An explicit --from directory or --allow-download is required")
    source = Path(source_dir).absolute() if source_dir is not None else None
    if source is not None:
        _require_verified(source, metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-stage-", dir=output.parent) as temp:
        work = Path(temp)
        if source is None:
            source = _download_snapshot(metadata, work / "download-cache")
            _require_verified(source, metadata)
        payload = work / "payload"
        payload.mkdir()
        for row in metadata["files"]:
            shutil.copyfile(source / row["path"], payload / row["path"])
        _require_verified(payload, metadata)
        # Another builder may have published while copying: never overwrite it.
        if output.exists():
            _require_verified(output, metadata)
        else:
            os.rename(payload, output)
    return output
