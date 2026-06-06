import unittest
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import os
import json
from fastapi.testclient import TestClient

import studio_memory as memory
from studio_workflow import StudioWorkflowRunner
import server


class TestStudioWorkflowAndMemory(unittest.TestCase):
    def setUp(self):
        # Create a temp directory to sandbox SQLite database files
        self.test_dir = tempfile.mkdtemp()
        
        # Patch the get_user_data_path in studio_memory to write databases into our temp directory
        self.patcher_mem_path = patch("studio_memory.get_user_data_path", return_value=self.test_dir)
        self.patcher_mem_path.start()
        
        # Also patch get_user_data_path in utils just in case
        self.patcher_utils_path = patch("utils.get_user_data_path", return_value=self.test_dir)
        self.patcher_utils_path.start()

        self.project_name = "Test Comic Project"

    def tearDown(self):
        self.patcher_mem_path.stop()
        self.patcher_utils_path.stop()
        
        # Clean up temp directory
        shutil.rmtree(self.test_dir)

    def test_database_initialization_and_schema(self):
        # Initialize project
        project_id = memory.init_project_db(self.project_name)
        self.assertIsNotNone(project_id)
        self.assertGreater(project_id, 0)
        
        # Verify db file is created
        db_path, project_dir = memory.get_project_db_path(self.project_name)
        self.assertTrue(os.path.exists(db_path))
        
        # Verify query project by name/id
        proj = memory.get_project_by_name(self.project_name)
        self.assertEqual(proj["id"], project_id)
        self.assertEqual(proj["name"], self.project_name)

        proj_by_id = memory.get_project_by_id(self.project_name, project_id)
        self.assertEqual(proj_by_id["name"], self.project_name)

    def test_database_crud_operations(self):
        project_id = memory.init_project_db(self.project_name)
        
        # 1. Bibles CRUD
        bible_content = {"premise": "Test premise content", "theme": "Cozy Magic"}
        memory.save_bible(self.project_name, project_id, bible_content)
        retrieved_bible = memory.get_bible(self.project_name, project_id)
        self.assertEqual(retrieved_bible["theme"], "Cozy Magic")
        
        # 2. Characters CRUD
        char_id = memory.add_character(self.project_name, project_id, "Test Bob", "A friendly test dummy", "Protagonist", "The Fool")
        self.assertGreater(char_id, 0)
        chars = memory.get_characters(self.project_name, project_id)
        self.assertEqual(len(chars), 1)
        self.assertEqual(chars[0]["name"], "Test Bob")
        
        # 3. Locations CRUD
        loc_id = memory.add_location(self.project_name, project_id, "Magic Kitchen", "Where tests are baked")
        self.assertGreater(loc_id, 0)
        locs = memory.get_locations(self.project_name, project_id)
        self.assertEqual(len(locs), 1)
        self.assertEqual(locs[0]["name"], "Magic Kitchen")

        # 4. Episodes & Minutes CRUD
        ep_id = memory.add_episode(self.project_name, project_id, "Episode One", "First test episode")
        self.assertGreater(ep_id, 0)
        eps = memory.get_episodes(self.project_name, project_id)
        self.assertEqual(len(eps), 1)
        
        min_id = memory.add_minute(self.project_name, project_id, ep_id, 1, "Minute summary text")
        self.assertGreater(min_id, 0)
        mins = memory.get_minutes(self.project_name, project_id)
        self.assertEqual(len(mins), 1)

        # 5. Panels & Dialogue CRUD
        panel_id = memory.add_panel(self.project_name, project_id, min_id, 1, "A white room", "Clean style")
        self.assertGreater(panel_id, 0)
        panels = memory.get_panels(self.project_name, project_id)
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["style_prompt"], "Clean style")

        line_id = memory.add_dialogue_line(self.project_name, project_id, panel_id, "Test Bob", "Hello test universe!")
        self.assertGreater(line_id, 0)
        lines = memory.get_dialogue_lines(self.project_name, project_id)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["text"], "Hello test universe!")

        # 6. Continuity warnings CRUD
        warn_id = memory.add_continuity_warning(self.project_name, project_id, "character", char_id, "high", "Bob missing hat")
        self.assertGreater(warn_id, 0)
        warnings = memory.get_continuity_warnings(self.project_name, project_id)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["resolved"], 0)
        
        memory.resolve_continuity_warning(self.project_name, warn_id)
        warnings = memory.get_continuity_warnings(self.project_name, project_id)
        self.assertEqual(warnings[0]["resolved"], 1)

        # 7. Approvals
        memory.record_approval(self.project_name, project_id, "panel", panel_id, True)
        panels = memory.get_panels(self.project_name, project_id)
        self.assertEqual(panels[0]["approved"], 1)

        # 8. Export JSON
        exported = memory.export_project_json(self.project_name, project_id)
        self.assertEqual(exported["project"]["name"], self.project_name)
        self.assertEqual(len(exported["characters"]), 1)
        self.assertEqual(exported["characters"][0]["name"], "Test Bob")

    def test_json_extraction_and_repair(self):
        runner = StudioWorkflowRunner(self.project_name)
        
        # Valid JSON
        self.assertEqual(runner._extract_and_parse_json('{"key": "value"}'), {"key": "value"})
        
        # JSON wrapped in markdown
        self.assertEqual(runner._extract_and_parse_json('```json\n{"key": "value"}\n```'), {"key": "value"})
        
        # Malformed but extractable
        self.assertEqual(runner._extract_and_parse_json('Here is your response: {"a": 123} Hope you like it.'), {"a": 123})
        
        # List extractable
        self.assertEqual(runner._extract_and_parse_json('Some text [{"id": 1}] other text'), [{"id": 1}])
        
        # Unrecoverable
        self.assertIsNone(runner._extract_and_parse_json('not json at all'))

    def test_workflow_orchestrator_mocks_fallback(self):
        # Test full pipeline with mocked LLMEngine (ensuring it triggers fallback callbacks)
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            
            runner = StudioWorkflowRunner(self.project_name)
            result = runner.run_full_pipeline("Find the magic key in the kitchen")
            
            self.assertTrue(result["ok"])
            self.assertEqual(runner.state, "complete")
            
            # Verify data stored in memory
            premise = memory.get_bible(self.project_name, runner.project_id).get("premise")
            self.assertIsNotNone(premise)
            self.assertIn("magic key", premise["premise"].lower() or premise["title"].lower())
            
            chars = memory.get_characters(self.project_name, runner.project_id)
            self.assertEqual(len(chars), 2)
            
            panels = memory.get_panels(self.project_name, runner.project_id)
            self.assertEqual(len(panels), 12)
            
            warnings = memory.get_continuity_warnings(self.project_name, runner.project_id)
            self.assertGreater(len(warnings), 0)

    def test_workflow_stages_independently(self):
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            
            runner = StudioWorkflowRunner(self.project_name)
            
            # Stage 1: Intake
            premise = runner.run_intake("Infiltrate the high vaults")
            self.assertEqual(runner.state, "intake")
            self.assertIsNotNone(premise)
            
            # Stage 2: World Building
            world = runner.run_world_building(premise)
            self.assertEqual(runner.state, "world_building")
            
            # Stage 3: Character Building
            chars = runner.run_character_building(premise, world)
            self.assertEqual(runner.state, "character_building")
            
            # Stage 4: Story Planning
            story_plan, ep_id = runner.run_story_planning(premise, world, chars)
            self.assertEqual(runner.state, "story_planning")
            
            # Stage 5 & 6: Panel & Dialogue Generation
            panels = runner.run_dialogue_and_panels(premise, world, chars, story_plan, ep_id)
            self.assertEqual(runner.state, "panel_planning")
            
            # Stage 7: Continuity warnings
            warnings = runner.run_continuity_audit(premise, world, chars, panels)
            self.assertEqual(runner.state, "approval_ready")

    def test_fastapi_endpoints(self):
        # Patching inside the test client scope so endpoint database functions write to self.test_dir
        with patch("studio_memory.get_user_data_path", return_value=self.test_dir), \
             patch("studio_workflow.get_engine", return_value=None), \
             patch("studio_workflow.get_engine_if_initialized", return_value=None):
             
            with TestClient(server.app) as client:
                # 1. Create project
                res = client.post("/studio/project/create", json={"project_name": self.project_name})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "success")
                project_id = res.json()["project_id"]
                
                # 2. Run workflow stage intake
                res = client.post("/studio/workflow/stage", json={
                    "project_name": self.project_name,
                    "stage": "intake",
                    "seed_text": "A clockwork key is stolen"
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["stage"], "intake")
                
                # 3. Run entire pipeline
                res = client.post("/studio/workflow/run", json={
                    "project_name": self.project_name,
                    "seed_text": "A clockwork key is stolen"
                })
                self.assertEqual(res.status_code, 200)
                self.assertTrue(res.json()["ok"])
                
                # 4. Get panels
                res = client.get(f"/studio/project/{self.project_name}/{project_id}/panels")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(len(res.json()["panels"]), 12)
                panel = res.json()["panels"][0]
                self.assertIn("dialogue", panel)
                self.assertIsNotNone(panel["dialogue"]["text"])

                # 5. Resolve warning
                warnings = memory.get_continuity_warnings(self.project_name, project_id)
                self.assertGreater(len(warnings), 0)
                warn_id = warnings[0]["id"]
                
                res = client.post("/studio/project/warning/resolve", json={
                    "project_name": self.project_name,
                    "warning_id": warn_id
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["warning_id"], warn_id)
                self.assertEqual(memory.get_continuity_warnings(self.project_name, project_id)[0]["resolved"], 1)

                # 6. Approve panel
                panel_id = panel["id"]
                res = client.post("/studio/project/approve", json={
                    "project_name": self.project_name,
                    "project_id": project_id,
                    "item_type": "panel",
                    "item_id": panel_id,
                    "approved": True
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["approved"], True)
                
                # 7. Load project
                res = client.post("/studio/project/load", json={"project_name": self.project_name})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "success")
                self.assertEqual(res.json()["project"]["id"], project_id)
                self.assertIsNotNone(res.json()["data"])


if __name__ == "__main__":
    unittest.main()
