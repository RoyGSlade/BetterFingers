"""C-1: /wake/models/import must go through upload_safety like every other
upload route (dictation, TTS clone, OCR) -- bounded, streamed write instead of
a raw, unbounded `handle.write(await file.read())` straight to disk.

The magic-byte check for this kind is a DENYLIST, not an allowlist (D-0040):
ONNX/protobuf has no format-mandated leading byte, so requiring one could
reject a genuinely valid user model. Only known-wrong containers (PNG, ZIP,
ELF, ...) are rejected; anything else passes through to wake_models' own
sha256 + onnxruntime-loadability checks.
"""

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import server
import upload_safety as us
import wake_models


class _TrackingSource:
    """A file-like source that records how it was read. Proves
    ``stream_to_file`` reads in bounded chunks and aborts partway through an
    oversized payload, instead of buffering the whole thing in one call (the
    old ``await file.read()`` behavior it replaces)."""

    def __init__(self, total_size):
        self._remaining = total_size
        self.max_single_read = 0
        self.total_read = 0

    def read(self, n=-1):
        if n is None or n < 0:
            raise AssertionError("must request a bounded chunk size, not an unbounded read()")
        self.max_single_read = max(self.max_single_read, n)
        chunk_len = min(n, self._remaining)
        self._remaining -= chunk_len
        self.total_read += chunk_len
        return b"\x08" * chunk_len


class StreamToFileBoundedReadTests(unittest.TestCase):
    def test_aborts_without_buffering_the_whole_oversized_payload(self):
        # A payload several streaming chunks long, capped well below even one
        # chunk -- proves the abort happens after the first chunk, not after
        # the source has handed over its whole (much larger) payload.
        total_size = us._STREAM_CHUNK * 5
        cap = 2000
        source = _TrackingSource(total_size=total_size)
        with tempfile.TemporaryDirectory() as d:
            dest = os.path.join(d, "model.onnx")
            with self.assertRaises(us.UploadTooLarge):
                us.stream_to_file(source, dest, max_bytes=cap)
            self.assertFalse(os.path.exists(dest))
        self.assertLessEqual(source.max_single_read, us._STREAM_CHUNK)
        self.assertLessEqual(source.total_read, us._STREAM_CHUNK)
        self.assertLess(source.total_read, total_size)


class WakeModelImportRouteTests(unittest.TestCase):
    def _client(self):
        return TestClient(server.app)

    def test_rejects_oversized_file(self):
        payload = b"\x08" * (wake_models.MAX_IMPORT_BYTES + 1)
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "Too Big"},
                files={"file": ("classifier.onnx", payload, "application/octet-stream")},
            )
        self.assertEqual(r.status_code, 413, r.text)

    def test_rejects_wrong_magic_png(self):
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "Not Onnx"},
                files={"file": ("classifier.onnx", png_header, "application/octet-stream")},
            )
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("PNG", r.json()["detail"])

    def test_rejects_wrong_magic_zip(self):
        zip_header = b"PK\x03\x04" + b"\x00" * 32
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "Not Onnx Either"},
                files={"file": ("classifier.onnx", zip_header, "application/octet-stream")},
            )
        self.assertEqual(r.status_code, 400, r.text)

    def test_accepts_non_container_payload_denylist_regression_guard(self):
        # Pins the denylist decision (D-0040): a plain, non-container byte
        # string -- no leading 0x08, no known-bad signature either -- must
        # still be ACCEPTED. If a later change "tightens" this into an
        # allowlist, this test catches it.
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "Plain Bytes"},
                files={"file": ("classifier.onnx", b"tiny classifier bytes", "application/octet-stream")},
            )
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            client.delete(f"/wake/models/{body['id']}")


if __name__ == "__main__":
    unittest.main()
