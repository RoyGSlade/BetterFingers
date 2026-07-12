"""Cryptographic verification of downloaded artifacts (review finding #11).

download_file must reject a completed transfer whose SHA-256 does not match
the pinned digest (delete it, raise), promote a matching one, and write a
sidecar digest for diagnostics. The catalog carries a digest for every model;
the runtime archive manifest covers every executable artifact URL.
"""

import hashlib
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import model_manager as mm


def _fake_response(payload: bytes):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-length": str(len(payload))}
    response.iter_content = lambda chunk_size: iter([payload])
    response.raise_for_status = lambda: None
    response.__enter__ = lambda self: self
    response.__exit__ = lambda self, *a: False
    return response


class DownloadVerificationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dest = os.path.join(self._tmp.name, "artifact.bin")
        self.payload = b"gguf bytes " * 1000
        self.good_sha = hashlib.sha256(self.payload).hexdigest()

    def _download(self, expected_sha256):
        with patch.object(mm.requests, "get", return_value=_fake_response(self.payload)):
            mm.download_file(
                "https://example.invalid/artifact.bin",
                self.dest,
                "Test artifact",
                resume=False,
                expected_sha256=expected_sha256,
            )

    def test_matching_digest_promotes_and_writes_sidecar(self):
        self._download(self.good_sha)
        self.assertTrue(os.path.exists(self.dest))
        sidecar = open(self.dest + ".sha256").read()
        self.assertIn(self.good_sha, sidecar)

    def test_mismatched_digest_deletes_and_raises(self):
        with self.assertRaises(IOError) as ctx:
            self._download("0" * 64)
        self.assertIn("checksum mismatch", str(ctx.exception))
        self.assertFalse(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_digest_comparison_is_case_insensitive(self):
        self._download(self.good_sha.upper())
        self.assertTrue(os.path.exists(self.dest))

    def test_no_digest_still_installs_with_warning(self):
        with self.assertLogs(level="WARNING") as logs:
            self._download(None)
        self.assertTrue(os.path.exists(self.dest))
        self.assertTrue(any("UNVERIFIED" in line for line in logs.output))


class ManifestCoverageTests(unittest.TestCase):
    def test_every_catalog_model_has_digest_and_exact_size(self):
        for model_id, meta in mm.AVAILABLE_MODELS.items():
            self.assertRegex(meta.get("sha256", ""), r"^[0-9a-f]{64}$", model_id)
            self.assertGreater(int(meta.get("size_bytes", 0)), 0, model_id)

    def test_runtime_archive_urls_are_covered(self):
        for url in (mm.SERVER_BIN_URL, mm.CUDA_LIB_URL):
            if url:
                self.assertRegex(mm.runtime_artifact_sha256(url) or "", r"^[0-9a-f]{64}$", url)

    def test_exact_size_check_rejects_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_id = mm.DEFAULT_MODEL
            path = os.path.join(tmp, mm.AVAILABLE_MODELS[model_id]["filename"])
            # >16MB so the fixture-file exemption doesn't apply, but not the
            # exact catalog size -> must be treated as incomplete.
            with open(path, "wb") as fh:
                fh.write(b"\0" * (20 * 1024 * 1024))
            with patch.object(mm, "get_model_path", return_value=path):
                self.assertFalse(mm.is_model_file_complete(model_id))


class Sha256FileTests(unittest.TestCase):
    def test_chunked_hash_matches_hashlib(self):
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(b"x" * (3 * 1024 * 1024 + 17))
            path = fh.name
        try:
            self.assertEqual(mm.sha256_file(path), hashlib.sha256(b"x" * (3 * 1024 * 1024 + 17)).hexdigest())
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
