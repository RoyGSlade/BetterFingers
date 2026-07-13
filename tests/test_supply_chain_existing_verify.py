"""Verification of already-installed artifacts and safe extraction (review finding #11).

download_file() proves NEW transfers. These tests cover the remaining supply-chain
items about files that are ALREADY on disk:

* an existing model/binary is never trusted by size alone — the SHA-256 must match;
* the verified verdict is cached by (path, size, mtime, digest) so multi-GB files
  are not rehashed on every call;
* a mismatched artifact is quarantined to ``<file>.corrupt`` and never used;
* deleting a model also drops its ``.sha256`` sidecar and cache entry;
* runtime archives extract through a validated staging dir that rejects absolute
  paths, ``..`` traversal and escaping symlinks, enforces an expected-member
  allowlist, and rolls back (keeping the old runtime) on any failure.
"""

import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch, MagicMock

import model_manager as mm


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class InstalledModelVerificationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.models_dir = self._tmp.name
        self.model_id = mm.DEFAULT_MODEL
        self.filename = mm.AVAILABLE_MODELS[self.model_id]["filename"]
        self.path = os.path.join(self.models_dir, self.filename)
        self.size = int(mm.AVAILABLE_MODELS[self.model_id]["size_bytes"])
        # Production must verify, so run these with the tiny-file allowance OFF.
        self._env = patch.dict(os.environ, {}, clear=True)
        self._env.start()
        self.addCleanup(self._env.stop)
        self._md = patch("model_manager.get_models_dir", return_value=self.models_dir)
        self._md.start()
        self.addCleanup(self._md.stop)

    def _write_model(self, data: bytes):
        with open(self.path, "wb") as handle:
            handle.write(data)

    def _patch_catalog(self, sha256, size_bytes):
        entry = dict(mm.AVAILABLE_MODELS[self.model_id])
        entry["sha256"] = sha256
        entry["size_bytes"] = size_bytes
        return patch.dict(mm.AVAILABLE_MODELS, {self.model_id: entry})

    def test_same_sized_corrupted_file_is_rejected(self):
        # Right size, wrong bytes: size passes but the digest must catch it.
        payload = b"A" * 4096
        self._write_model(payload)
        with self._patch_catalog(_sha(b"the real model" * 300), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            self.assertFalse(mm.is_model_file_complete(self.model_id))
            result = mm.verify_installed_model(self.model_id, quarantine=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "digest_mismatch")

    def test_matching_digest_is_complete(self):
        payload = b"good model bytes " * 300
        self._write_model(payload)
        with self._patch_catalog(_sha(payload), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            self.assertTrue(mm.is_model_file_complete(self.model_id))
            self.assertTrue(mm.verify_installed_model(self.model_id)["ok"])

    def test_verified_state_cache_hit_avoids_rehash(self):
        payload = b"cacheable model " * 500
        self._write_model(payload)
        with self._patch_catalog(_sha(payload), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            real_sha = mm.sha256_file
            with patch("model_manager.sha256_file", side_effect=real_sha) as spy:
                first = mm.verify_installed_model(self.model_id)
                second = mm.verify_installed_model(self.model_id)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertFalse(first["from_cache"])
        self.assertTrue(second["from_cache"])
        self.assertEqual(spy.call_count, 1)  # hashed once, second call served from cache

    def test_cache_invalidated_when_file_changes(self):
        payload = b"first bytes " * 500
        self._write_model(payload)
        with self._patch_catalog(_sha(payload), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            self.assertTrue(mm.verify_installed_model(self.model_id)["ok"])
        # Same length, different content, newer mtime -> cache must not be trusted.
        tampered = b"second byte " * 500 + b"!"
        tampered = tampered[: len(payload)]
        self._write_model(tampered)
        os.utime(self.path, (0, 0))  # force a distinct mtime
        with self._patch_catalog(_sha(payload), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            result = mm.verify_installed_model(self.model_id, quarantine=False)
        self.assertFalse(result["ok"])

    def test_mismatch_is_quarantined(self):
        payload = b"B" * 8192
        self._write_model(payload)
        with self._patch_catalog(_sha(b"expected"), len(payload)), patch(
            "model_manager.get_model_path", return_value=self.path
        ):
            result = mm.verify_installed_model(self.model_id, quarantine=True)
        self.assertFalse(result["ok"])
        self.assertFalse(os.path.exists(self.path))
        self.assertTrue(os.path.exists(self.path + ".corrupt"))
        self.assertEqual(result["quarantined"], self.path + ".corrupt")


class DeleteModelCleansSidecarTests(unittest.TestCase):
    def test_sidecar_and_cache_dropped_on_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "model.gguf")
            payload = b"model bytes " * 200
            with open(path, "wb") as handle:
                handle.write(payload)
            with open(path + ".sha256", "w", encoding="utf-8") as handle:
                handle.write(f"{_sha(payload)}  model.gguf\n")

            with patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.get_model_path", return_value=path
            ), patch("model_manager.get_partial_model_path", return_value=path + ".part"):
                # Seed a cache entry for this path.
                mm._cached_digest_ok(path, _sha(payload))
                self.assertIn(os.path.abspath(path), mm._load_verify_cache())

                ok, _msg = mm.delete_model("gemma-3-4b-q4")

                self.assertTrue(ok)
                self.assertFalse(os.path.exists(path))
                self.assertFalse(os.path.exists(path + ".sha256"))
                self.assertNotIn(os.path.abspath(path), mm._load_verify_cache())


class RuntimeBinaryVerificationTests(unittest.TestCase):
    def test_replaced_binary_with_unchanged_filename_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_path = os.path.join(tmp, "llama-server")
            with open(server_path, "wb") as handle:
                handle.write(b"#!/bin/sh\necho 'version: 9548'\n")

            with patch("model_manager.get_models_dir", return_value=tmp):
                mm.record_runtime_digest(server_path)
                self.assertTrue(os.path.exists(server_path + ".sha256"))
                self.assertTrue(mm.verify_installed_runtime(server_path)["ok"])

                # Swap the binary underneath us, keeping the same filename.
                with open(server_path, "wb") as handle:
                    handle.write(b"#!/bin/sh\necho 'pwned'\n")
                os.utime(server_path, (0, 0))

                result = mm.verify_installed_runtime(server_path, quarantine=True)

            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "digest_mismatch")
            self.assertFalse(os.path.exists(server_path))
            self.assertTrue(os.path.exists(server_path + ".corrupt"))

    def test_validate_refuses_to_execute_tampered_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            server_path = os.path.join(tmp, "llama-server")
            with open(server_path, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\necho 'version: 9548'\n")
            os.chmod(server_path, 0o755)

            with patch("model_manager.get_models_dir", return_value=tmp), patch(
                "model_manager.sys.platform", "linux"
            ):
                mm.record_runtime_digest(server_path)
                with open(server_path, "w", encoding="utf-8") as handle:
                    handle.write("#!/bin/sh\necho 'version: 9548'\ntouch pwned\n")
                os.utime(server_path, (0, 0))

                with patch("model_manager.subprocess.run") as run:
                    result = mm.validate_llama_server_runtime(server_path)

            self.assertFalse(result["ok"])
            self.assertIn("integrity", result)
            run.assert_not_called()  # the binary is never executed after tampering


class SafeExtractionTests(unittest.TestCase):
    def _tar_gz(self, path, members):
        """members: list of (name, data_or_None, linkname_or_None)."""
        with tarfile.open(path, "w:gz") as archive:
            for name, data, linkname in members:
                if linkname is not None:
                    info = tarfile.TarInfo(name)
                    info.type = tarfile.SYMTYPE
                    info.linkname = linkname
                    archive.addfile(info)
                else:
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    info.mode = 0o644
                    archive.addfile(info, io.BytesIO(data))

    def test_absolute_member_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            self._tar_gz(archive, [("/etc/evil", b"x", None), ("bin/llama-server", b"ok", None)])
            with self.assertRaises(mm.ArchiveValidationError):
                mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                required_members=["llama-server"])
            self.assertFalse(os.path.exists(os.path.join(dest, "llama-server")))
            self.assertFalse(os.path.exists("/etc/evil"))

    def test_dotdot_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            self._tar_gz(archive, [("../../escape.txt", b"x", None), ("bin/llama-server", b"ok", None)])
            with self.assertRaises(mm.ArchiveValidationError):
                mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                required_members=["llama-server"])
            self.assertFalse(os.path.exists(os.path.join(os.path.dirname(dest), "escape.txt")))

    def test_escaping_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            self._tar_gz(archive, [
                ("bin/evil-link", None, "/etc/passwd"),
                ("bin/llama-server", b"ok", None),
            ])
            with self.assertRaises(mm.ArchiveValidationError):
                mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                required_members=["llama-server"])
            self.assertFalse(os.path.islink(os.path.join(dest, "evil-link")))

    def test_internal_soname_symlink_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            self._tar_gz(archive, [
                ("bin/libggml.so.0.9.5", b"lib", None),
                ("bin/libggml.so.0", None, "libggml.so.0.9.5"),
                ("bin/llama-server", b"#!/bin/sh\n", None),
            ])
            result = mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                     required_members=["llama-server"])
            self.assertTrue(result["ok"])
            link = os.path.join(dest, "libggml.so.0")
            self.assertTrue(os.path.islink(link))
            self.assertEqual(os.readlink(link), "libggml.so.0.9.5")

    def test_expected_member_allowlist_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            # Archive has libs but not the required executable.
            self._tar_gz(archive, [("bin/libllama.so.0", b"lib", None)])
            with self.assertRaises(mm.ArchiveValidationError) as ctx:
                mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                required_members=["llama-server"])
            self.assertIn("llama-server", str(ctx.exception))
            self.assertFalse(os.path.exists(os.path.join(dest, "libllama.so.0")))

    def test_staging_rollback_keeps_old_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            old_server = os.path.join(dest, "llama-server")
            with open(old_server, "wb") as handle:
                handle.write(b"OLD-RUNTIME")
            os.chmod(old_server, 0o755)

            # New archive is missing the required member -> extraction fails.
            self._tar_gz(archive, [("bin/libllama.so.0", b"lib", None)])
            with self.assertRaises(mm.ArchiveValidationError):
                mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                required_members=["llama-server"])

            self.assertTrue(os.path.exists(old_server))
            with open(old_server, "rb") as handle:
                self.assertEqual(handle.read(), b"OLD-RUNTIME")
            # No staging/backup litter left behind.
            leftovers = [n for n in os.listdir(dest) if n.startswith((".staging-", ".backup-"))]
            self.assertEqual(leftovers, [])

    def test_valid_archive_promotes_and_chmods_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.tar.gz")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            old_server = os.path.join(dest, "llama-server")
            with open(old_server, "wb") as handle:
                handle.write(b"OLD")
            self._tar_gz(archive, [("bin/llama-server", b"#!/bin/sh\nexit 0\n", None)])

            result = mm.safe_extract_runtime_archive(archive, dest, "runtime.tar.gz",
                                                     required_members=["llama-server"])

            self.assertTrue(result["ok"])
            with open(old_server, "rb") as handle:
                self.assertEqual(handle.read(), b"#!/bin/sh\nexit 0\n")  # replaced
            self.assertTrue(os.access(old_server, os.X_OK))  # chmod +x after validation

    def test_zip_absolute_path_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "runtime.zip")
            dest = os.path.join(tmp, "dest")
            os.makedirs(dest)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("/abs/evil.dll", b"x")
                zf.writestr("llama-server.exe", b"ok")
            with self.assertRaises(mm.ArchiveValidationError):
                mm.safe_extract_runtime_archive(archive, dest, "runtime.zip",
                                                required_members=["llama-server.exe"])


if __name__ == "__main__":
    unittest.main()
