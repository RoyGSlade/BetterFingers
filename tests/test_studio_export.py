import os
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import studio_export
from studio_workflow import StudioWorkflowRunner


STORY = """One last job, and then Goldstein would be happy. I saw Freddy Goldstein at the
Cabbaro Pulse in Grimstow City.

"You heard about the job, huh?" Goldstein said. "I want in," I said.

We crossed into Dockside. "I think I'm ready," Rodney said. Then Rodney pointed a gun.
"Boss said only one of us gets the promotion," Rodney added. Then CRACK.

Louis woke coughing. Louis lifted his shirt and found the scar. Father Time stood over
the flames. "Not everyone survives their first taste of smoke," Father Time said.
"Keep your scars closer," Father Time said to Louis. """


class TestStudioExport(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.p_mem = patch("studio_memory.get_user_data_path", return_value=self.test_dir)
        self.p_utils = patch("utils.get_user_data_path", return_value=self.test_dir)
        self.p_mem.start()
        self.p_utils.start()
        # Force the procedural (no-LLM) path so the test is deterministic and offline.
        self.p_engine = patch("studio_workflow.get_engine", return_value=None)
        self.p_engine2 = patch("studio_workflow.get_engine_if_initialized", return_value=None)
        self.p_engine.start()
        self.p_engine2.start()
        self.project = "Loss Of A Brother"

    def tearDown(self):
        for p in (self.p_mem, self.p_utils, self.p_engine, self.p_engine2):
            p.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _run_pipeline(self):
        runner = StudioWorkflowRunner(self.project)
        return runner.run_full_pipeline(STORY, mode="adapt")

    def test_faithful_pipeline_uses_real_names(self):
        out = self._run_pipeline()
        self.assertTrue(out["ok"])
        self.assertTrue(out["model_status"]["used_fallback"])
        names = [c["name"] for c in out["data"]["characters"]]
        self.assertIn("Louis", names)
        self.assertTrue(any("Goldstein" in n for n in names))
        # Real story locations are persisted alongside the cast region.
        places = [l["name"] for l in out["data"]["locations"]]
        self.assertTrue(any("Dockside" in p for p in places))

    def test_panels_carry_real_dialogue(self):
        out = self._run_pipeline()
        lines = out["data"]["dialogue_lines"]
        texts = " ".join(d["text"] for d in lines)
        self.assertIn("You heard about the job", texts)
        speakers = {d["speaker"] for d in lines}
        self.assertTrue(any("Goldstein" in s for s in speakers))

    def test_export_writes_full_package(self):
        out = self._run_pipeline()
        result = studio_export.export_project(self.project, model_status=out["model_status"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["panel_count"], 4)

        export_dir = result["export_dir"]
        for rel in ("project.json", "script.md", "subtitles.srt", "reel.html",
                    "export_report.md", "bibles/world_bible.md",
                    "bibles/character_bible.md", "bibles/style_bible.md"):
            self.assertTrue(os.path.exists(os.path.join(export_dir, rel)), f"missing {rel}")

        # The ZIP exists and contains the reel preview.
        self.assertTrue(os.path.exists(result["zip_path"]))
        with zipfile.ZipFile(result["zip_path"]) as zf:
            self.assertIn("reel.html", zf.namelist())

    def test_subtitles_are_timed_srt(self):
        out = self._run_pipeline()
        result = studio_export.export_project(self.project, model_status=out["model_status"])
        srt = open(os.path.join(result["export_dir"], "subtitles.srt")).read()
        self.assertIn("-->", srt)
        self.assertIn("00:00:00,000", srt)

    def test_reel_html_contains_real_dialogue(self):
        out = self._run_pipeline()
        result = studio_export.export_project(self.project, model_status=out["model_status"])
        html = open(os.path.join(result["export_dir"], "reel.html")).read()
        self.assertIn("You heard about the job", html)
        self.assertIn("Goldstein", html)

    def test_export_missing_project_raises(self):
        with self.assertRaises(ValueError):
            studio_export.export_project("No Such Project 9000")

    def test_export_endpoint_end_to_end(self):
        from fastapi.testclient import TestClient
        import server

        with TestClient(server.app) as client:
            client.post("/studio/project/create", json={"project_name": self.project})
            run = client.post("/studio/workflow/run", json={
                "project_name": self.project, "seed_text": STORY, "mode": "adapt",
            })
            self.assertEqual(run.status_code, 200)
            self.assertTrue(run.json()["ok"])

            exp = client.post("/studio/project/export-reel", json={"project_name": self.project})
            self.assertEqual(exp.status_code, 200)
            body = exp.json()
            self.assertEqual(body["status"], "success")
            self.assertEqual(body["panel_count"], 4)
            self.assertTrue(os.path.exists(body["reel_html"]))
            self.assertTrue(os.path.exists(body["zip_path"]))


if __name__ == "__main__":
    unittest.main()
