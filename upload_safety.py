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

# Per-kind caps (bytes). Generous for real use, ruinous for abuse.
# (Wake classifier imports are capped by wake_models.MAX_IMPORT_BYTES, the
# existing single source of truth for that limit -- not duplicated here.)
MAX_AUDIO_BYTES = 50 * 1024 * 1024      # ~50 MB WAV
MAX_IMAGE_BYTES = 25 * 1024 * 1024      # ~25 MB image
MAX_AUDIO_SECONDS = 15 * 60             # 15 minutes
MAX_IMAGE_PIXELS = 40_000_000          # 40 MP (decompression-bomb guard)

_STREAM_CHUNK = 1024 * 1024

_WAV_FORMAT_PCM = 0x0001
_WAV_FORMAT_IEEE_FLOAT = 0x0003
_SUPPORTED_WAV_BITS = {
    _WAV_FORMAT_PCM: {8, 16, 24, 32},
    _WAV_FORMAT_IEEE_FLOAT: {32, 64},
}

# Content signatures (magic bytes) keyed by kind. A file is accepted only if it
# starts with one of these — the extension is not trusted.
_SIGNATURES = {
    "audio": [b"RIFF"],                       # RIFF/WAVE (WAVE checked below)
    "image": [b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"BM", b"II*\x00", b"MM\x00*"],
}

# ONNX is a protobuf message with no format-mandated magic byte (unlike
# RIFF/PNG), so it is validated as a DENYLIST rather than an allowlist
# (D-0040): reject known non-model container formats by their real
# signatures; anything else passes through to wake_models' own sha256 +
# onnxruntime-loadability checks. An allowlist here would risk rejecting a
# genuinely valid user model over an unenforced protobuf field-ordering
# convention.
_DENY_SIGNATURES = {
    "onnx": [
        (b"\x89PNG", "PNG image"),
        (b"\xff\xd8\xff", "JPEG image"),
        (b"GIF8", "GIF image"),
        (b"%PDF", "PDF document"),
        (b"PK\x03\x04", "ZIP/Office document"),
        (b"\x7fELF", "ELF executable"),
        (b"MZ", "Windows PE executable"),
        (b"RIFF", "RIFF/WAV container"),
        (b"\x1f\x8b", "gzip archive"),
        (b"<", "HTML/XML content"),
    ],
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
    """Raise UploadRejected unless the file's leading bytes match ``kind``.

    Most kinds are an allowlist (must match a known-good signature). Kinds in
    ``_DENY_SIGNATURES`` are the opposite -- a denylist that only rejects
    known-bad containers, for formats (like ONNX/protobuf) with no
    format-mandated magic byte of their own.
    """
    with open(path, "rb") as fh:
        head = fh.read(16)
    if kind == "audio":
        # RIFF container whose form type is WAVE.
        if not (head.startswith(b"RIFF") and head[8:12] == b"WAVE"):
            raise UploadRejected("not a WAVE audio file")
        return
    deny = _DENY_SIGNATURES.get(kind)
    if deny is not None:
        for sig, label in deny:
            if head.startswith(sig):
                raise UploadRejected(f"{label} detected")
        return
    if not _matches_signature(head, kind):
        raise UploadRejected(f"unrecognized {kind} signature")


def _read_wav_duration(path):
    """Read bounded RIFF metadata without decoding or allocating audio.

    ``wave`` only accepts PCM and rejects the IEEE-float WAV files that
    BetterFingers itself persists through scipy.  This parser intentionally
    supports only the two uncompressed formats the product owns: PCM (1) and
    IEEE float (3). Compressed/unknown codecs remain fail-closed.
    """
    try:
        file_size = os.path.getsize(path)
        with open(path, "rb") as wav:
            header = wav.read(12)
            if len(header) != 12 or header[:4] != b"RIFF" or header[8:12] != b"WAVE":
                raise UploadRejected("malformed WAV: invalid RIFF/WAVE header")

            riff_size = struct.unpack("<I", header[4:8])[0]
            riff_end = riff_size + 8
            if riff_end < 12 or riff_end > file_size:
                raise UploadRejected("malformed WAV: truncated RIFF container")

            format_info = None
            data_size = None
            while wav.tell() + 8 <= riff_end:
                chunk_header = wav.read(8)
                if len(chunk_header) != 8:
                    raise UploadRejected("malformed WAV: truncated chunk header")
                chunk_id = chunk_header[:4]
                chunk_size = struct.unpack("<I", chunk_header[4:8])[0]
                chunk_start = wav.tell()
                chunk_end = chunk_start + chunk_size
                padded_end = chunk_end + (chunk_size & 1)
                if padded_end > riff_end or padded_end > file_size:
                    raise UploadRejected("malformed WAV: truncated chunk data")

                if chunk_id == b"fmt ":
                    if format_info is not None:
                        raise UploadRejected("malformed WAV: duplicate fmt chunk")
                    if chunk_size < 16:
                        raise UploadRejected("malformed WAV: short fmt chunk")
                    raw_format = wav.read(16)
                    if len(raw_format) != 16:
                        raise UploadRejected("malformed WAV: truncated fmt chunk")
                    format_info = struct.unpack("<HHIIHH", raw_format)
                elif chunk_id == b"data":
                    if data_size is not None:
                        raise UploadRejected("malformed WAV: duplicate data chunk")
                    data_size = chunk_size

                wav.seek(padded_end)

            if format_info is None or data_size is None:
                raise UploadRejected("malformed WAV: missing fmt or data chunk")

            format_tag, channels, rate, byte_rate, block_align, bits_per_sample = format_info
            supported_bits = _SUPPORTED_WAV_BITS.get(format_tag)
            if supported_bits is None:
                raise UploadRejected(f"unsupported WAV format: {format_tag}")
            if bits_per_sample not in supported_bits:
                raise UploadRejected(
                    f"unsupported WAV sample width: {bits_per_sample} bits for format {format_tag}"
                )
            if channels <= 0 or rate <= 0 or block_align <= 0 or byte_rate <= 0:
                raise UploadRejected("malformed WAV: invalid stream geometry")

            expected_block_align = channels * (bits_per_sample // 8)
            if block_align != expected_block_align or byte_rate != rate * block_align:
                raise UploadRejected("malformed WAV: inconsistent stream geometry")
            if data_size % block_align:
                raise UploadRejected("malformed WAV: partial audio frame")

            frames = data_size // block_align
            return frames / float(rate)
    except UploadRejected:
        raise
    except (OSError, struct.error) as exc:
        raise UploadRejected(f"malformed WAV: {exc}")


def validate_wav_duration(path, max_seconds=MAX_AUDIO_SECONDS):
    """Raise UploadRejected if the WAV is unreadable or too long."""
    seconds = _read_wav_duration(path)
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
