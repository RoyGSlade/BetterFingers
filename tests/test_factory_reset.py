"""Wave 6 — THE FACTORY-RESET EXECUTOR (the Wave 1 backlog item).

``data_registry`` has declared ``WIPE_MODE_FACTORY_RESET`` since phase 2.1 and
nothing performed it. These tests cover the executor that closes that gap, and
they are written around the three claims a factory reset makes that an ordinary
privacy wipe does not:

1. **It crosses the Python/Electron boundary.** The onboarding consent record,
   the overlay position/appearance, the sidecar raw log and the confirmed
   application registry are written by the Electron main process. Three of them
   live under Electron's own userData root, not ours. A reset that swept only
   the Python root would leave the consent record behind and the next launch
   would skip onboarding — visibly not a fresh install.
2. **It proves itself.** ``ok`` is the AND of per-category verifications that
   re-read the disk, plus a residual sweep for files no category declared. A
   reset that finishes with unaccounted files has not produced a fresh install
   whatever the per-category results say.
3. **It cannot happen by accident.** The route requires an exact confirmation
   phrase, and the verification endpoint has no deletion path at all.
"""

import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import data_categories as dc
import data_lifecycle as dl
import data_registry as dr
import server


class _ResetRootMixin(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._electron = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self.electron_root = pathlib.Path(self._electron.name) / "BetterFingers"
        self.electron_root.mkdir(parents=True, exist_ok=True)
        patchers = [
            patch("app_paths.resolve_base", return_value=self.root),
            patch("utils.get_user_data_path", return_value=str(self.root)),
            patch("history_store.get_user_data_path", return_value=str(self.root)),
            patch("recordings.get_user_data_path", return_value=str(self.root)),
            patch("server.get_user_data_path", return_value=str(self.root)),
            # Electron's userData root is a genuinely different directory from
            # ours on every platform, so it is pinned separately rather than
            # folded into the unified root — otherwise the cross-boundary claim
            # would be tested against a setup that has no boundary in it.
            patch("data_paths.electron_user_data_candidates",
                  return_value=[self.electron_root]),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(self._electron.cleanup)
        self.registry = dc.build_registry()

    # draft_history.json is deliberately absent from this list. The server
    # owns it and rewrites it during startup, so a TestClient created after
    # the fixture wrote it would legitimately replace the file — an assertion
    # about it would be testing the startup path, not the reset.
    STATE_FILES = ("contacts.json", "personas.yaml", "dictionary.json",
                   "macros.json", "voice_presets.json", "app_state.yaml",
                   "onboarding.json", "app_profiles.json",
                   "launcher_workflows.json", "application_registry.json",
                   "mcp_servers.json", "graph.json", "debug.log",
                   "controller_bindings.json", "stream_deck_config.json",
                   "persona_learning.json")

    def write_python_state(self):
        files = {}
        for name in self.STATE_FILES:
            path = self.root / name
            path.write_text("{}", encoding="utf-8")
            files[name] = path
        (self.root / "profiles").mkdir(exist_ok=True)
        (self.root / "profiles" / "Default.yaml").write_text("a: 1", encoding="utf-8")
        files["profiles"] = self.root / "profiles"
        return files

    def write_electron_state(self):
        files = {}
        for name in ("overlay-position.json", "overlay-appearance.json",
                     "sidecar_backend_raw.log"):
            path = self.electron_root / name
            path.write_text("{}", encoding="utf-8")
            files[name] = path
        return files


class FactoryResetExecutorTests(_ResetRootMixin):
    def test_reset_clears_python_state_and_verifies(self):
        files = self.write_python_state()
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["ok"], result)
        for name, path in files.items():
            self.assertFalse(path.exists(), f"{name} survived the factory reset")

    def test_reset_clears_electron_owned_state(self):
        """The point of the cross-boundary claim: these files are written by
        the Electron main process and three of them do not live under our
        root at all."""
        electron = self.write_electron_state()
        self.write_python_state()
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["ok"], result)
        for name, path in electron.items():
            self.assertFalse(path.exists(), f"Electron-owned {name} survived")

    def test_onboarding_record_is_cleared_so_the_next_launch_is_first_run(self):
        onboarding = self.root / "onboarding.json"
        onboarding.write_text(json.dumps({"consentVersion": 3,
                                          "acceptedAt": "2026-01-01T00:00:00Z"}),
                              encoding="utf-8")
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["categories"]["onboarding_consent"]["verified"])
        self.assertFalse(onboarding.exists(),
                         "a reset that keeps the consent record skips onboarding "
                         "on next launch, which is not a fresh install")

    def test_app_profiles_are_cleared(self):
        profiles = self.root / "app_profiles.json"
        profiles.write_text('{"pinned": {"code": "Focus"}}', encoding="utf-8")
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["categories"]["app_profiles"]["verified"])
        self.assertFalse(profiles.exists())

    def test_models_are_retained_unless_explicitly_requested(self):
        models = self.root / "models"
        models.mkdir()
        blob = models / "big.gguf"
        blob.write_text("weights", encoding="utf-8")
        result = dl.factory_reset(self.registry)
        self.assertTrue(result["ok"], result)
        self.assertTrue(blob.exists(), "a reset deleted an opt-in model download")
        self.assertFalse(result["models"]["requested"])

    def test_models_are_deleted_when_requested(self):
        models = self.root / "models"
        models.mkdir()
        blob = models / "big.gguf"
        blob.write_text("weights", encoding="utf-8")
        result = dl.factory_reset(self.registry, include_models=True)
        self.assertTrue(result["ok"], result)
        self.assertFalse(blob.exists())
        self.assertTrue(result["models"]["requested"])

    def test_an_undeclared_leftover_makes_the_reset_report_failure(self):
        """A reset is a claim about the whole directory, not only about the
        categories it knows. An unaccounted file means either an undeclared
        store or a failed deletion, and both are reasons not to claim a fresh
        install."""
        self.write_python_state()
        rogue = self.root / "mystery_store.json"
        rogue.write_text('{"x": 1}', encoding="utf-8")
        result = dl.factory_reset(self.registry)
        self.assertFalse(result["ok"])
        self.assertIn(str(rogue.resolve()), result["residual_files"])

    def test_verification_is_read_only(self):
        files = self.write_python_state()
        before = sorted(os.listdir(self.root))
        verified = dl.verify_factory_reset(self.registry)
        self.assertFalse(verified["ok"], "state is still present, so this must fail")
        self.assertEqual(sorted(os.listdir(self.root)), before,
                         "verify_factory_reset deleted something")
        for path in files.values():
            self.assertTrue(path.exists())

    def test_verification_passes_after_a_real_reset(self):
        self.write_python_state()
        self.write_electron_state()
        self.assertTrue(dl.factory_reset(self.registry)["ok"])
        self.assertTrue(dl.verify_factory_reset(self.registry)["ok"])

    def test_reset_is_idempotent(self):
        self.write_python_state()
        self.assertTrue(dl.factory_reset(self.registry)["ok"])
        self.assertTrue(dl.factory_reset(self.registry)["ok"])


class FactoryResetRouteTests(_ResetRootMixin):
    def setUp(self):
        super().setUp()
        self._env = patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"},
                               clear=False)
        self._env.start()
        self.addCleanup(self._env.stop)

    def _client(self):
        return TestClient(server.app)

    def test_reset_without_the_confirmation_phrase_deletes_nothing(self):
        files = self.write_python_state()
        with self._client() as client:
            resp = client.post("/privacy/factory-reset", json={})
        self.assertEqual(resp.status_code, 400, resp.text)
        self.assertEqual(resp.json()["error"], "confirmation_required")
        for name, path in files.items():
            self.assertTrue(path.exists(), f"{name} was deleted without confirmation")

    def test_a_boolean_style_confirmation_is_not_accepted(self):
        """The gate is an exact phrase precisely so that a client sending a
        truthy value cannot erase an install."""
        files = self.write_python_state()
        for bad in ("true", "yes", "1", "delete everything", "DELETE  EVERYTHING"):
            with self._client() as client:
                resp = client.post("/privacy/factory-reset", json={"confirm": bad})
            self.assertEqual(resp.status_code, 400, bad)
        for path in files.values():
            self.assertTrue(path.exists())

    def test_reset_with_the_confirmation_phrase_runs_and_verifies(self):
        files = self.write_python_state()
        self.write_electron_state()
        with self._client() as client:
            resp = client.post("/privacy/factory-reset",
                               json={"confirm": server.FACTORY_RESET_CONFIRMATION})
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["verified"])
        self.assertEqual(body["residual_files"], [])
        for name, path in files.items():
            self.assertFalse(path.exists(), f"{name} survived")

    def test_verify_endpoint_has_no_deletion_path(self):
        files = self.write_python_state()
        with self._client() as client:
            resp = client.get("/privacy/factory-reset/verify")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertFalse(resp.json()["ok"])
        for name, path in files.items():
            self.assertTrue(path.exists(), f"the verify endpoint deleted {name}")

    def test_modes_endpoint_previews_without_deleting(self):
        files = self.write_python_state()
        with self._client() as client:
            resp = client.get("/privacy/modes")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertEqual(set(body["modes"]), set(dr.WIPE_MODES))
        self.assertEqual(body["factory_reset_confirmation"],
                         server.FACTORY_RESET_CONFIRMATION)
        factory = body["modes"][dr.WIPE_MODE_FACTORY_RESET]
        self.assertGreater(factory["present_count"], 0)
        for path in files.values():
            self.assertTrue(path.exists(), "previewing a mode deleted something")


if __name__ == "__main__":
    unittest.main()
