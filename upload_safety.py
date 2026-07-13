"""Bounded, signature-checked upload handling (P1 upload safety).

Uploads (voice samples, OCR images, transcription audio) were copied to temp
files with no size cap, no MIME/magic-byte validation, and no decode limits — a
large or malformed file could exhaust disk, or a decompression-bomb image could
exhaust memory. These helpers stream with a hard byte cap, verify the content
signature (not the filename), and expose limits the routes enforce.

Pure stdlib + optional Pillow; unit-tested in ``tests/test_upload_safety.py``.
"""

import logging
import os
import struct
import wave

# Per-kind caps (bytes). Generous for real use, ruinous for abuse.
MAX_AUDIO_BYTES = 50 * 1024 * 1024      # ~50 MB WAV
MAX_IMAGE_BYTES = 25 * 1024 * 1024      # ~25 MB image
MAX_AUDIO_SECONDS = 15 * 60             # 15 minutes
MAX_IMAGE_PIXELS = 40_000_000          # 40 MP (decompression-bomb guard)

_STREAM_CHUNK = 1024 * 1024

# Content signatures (magic bytes) keyed by kind. A file is accepted only if it
# starts with one of these — the extension is not trusted.
_SIGNATURES = {
    "audio": [b"RIFF"],                       # RIFF/WAVE (WAVE checked below)
    "image": [b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"BM", b"II*\x00", b"MM\x00*"],
}


class UploadTooLarge(Exception):
    def __init__(self, limit):
        super().__init__(f"upload exceeds {limit} bytes")
        self.limit = limit


class UploadRejected(Exception):
    """Wrong signature / malformed content."""


def stream_to_file(src, dest_path, max_bytes):
    """Copy a file-like ``src`` to ``dest_path``, aborting past ``max_bytes``.

    Deletes the partial file and raises UploadTooLarge on overflow. Returns the
    number of bytes written.
    """
    written = 0
    try:
        with open(dest_path, "wb") as out:
            while True:
                chunk = src.read(_STREAM_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise UploadTooLarge(max_bytes)
                out.write(chunk)
    except UploadTooLarge:
        _safe_remove(dest_path)
        raise
    return written


def _safe_remove(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _matches_signature(head, kind):
    sigs = _SIGNATURES.get(kind, [])
    return any(head.startswith(sig) for sig in sigs)


def validate_signature(path, kind):
    """Raise UploadRejected unless the file's leading bytes match ``kind``."""
    with open(path, "rb") as fh:
        head = fh.read(16)
    if kind == "audio":
        # RIFF container whose form type is WAVE.
        if not (head.startswith(b"RIFF") and head[8:12] == b"WAVE"):
            raise UploadRejected("not a WAVE audio file")
        return
    if not _matches_signature(head, kind):
        raise UploadRejected(f"unrecognized {kind} signature")


def validate_wav_duration(path, max_seconds=MAX_AUDIO_SECONDS):
    """Raise UploadRejected if the WAV is unreadable or too long."""
    try:
        with wave.open(path, "rb") as wav:
            frames = wav.getnframes()
            rate = wav.getframerate() or 1
            seconds = frames / float(rate)
    except (wave.Error, EOFError, struct.error, OSError) as exc:
        raise UploadRejected(f"malformed WAV: {exc}")
    if seconds > max_seconds:
        raise UploadRejected(f"audio too long: {seconds:.0f}s > {max_seconds}s")
    return seconds


def validate_image(path, max_pixels=MAX_IMAGE_PIXELS):
    """Verify an image decodes and is within the pixel budget (bomb guard).

    Uses Pillow when available; falls back to signature-only if not installed.
    """
    try:
        from PIL import Image
    except ImportError:
        logging.debug("Pillow not installed; skipping image pixel validation.")
        return None
    # Cap Pillow's own bomb threshold to ours so a huge header is refused
    # before full decode.
    prior = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        with Image.open(path) as img:
            img.verify()  # detects truncated/corrupt data without full decode
        with Image.open(path) as img:
            w, h = img.size
    except Image.DecompressionBombError as exc:
        raise UploadRejected(f"image too large (decompression bomb): {exc}")
    except Exception as exc:
        raise UploadRejected(f"malformed image: {exc}")
    finally:
        Image.MAX_IMAGE_PIXELS = prior
    if w * h > max_pixels:
        raise UploadRejected(f"image too large: {w}x{h} > {max_pixels}px")
    return (w, h)
