import unittest
from unittest.mock import patch, MagicMock
import tempfile
import shutil
import os
import json
from fastapi.testclient import TestClient

import studio_memory as memory
import studio_capabilities
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

    def test_character_assets_and_profiles(self):
        project_id = memory.init_project_db(self.project_name)
        
        # Test creating a character with the new schema columns
        voice_profile = {"voice_id": "alloy", "pitch": 1.0}
        char_id = memory.add_character(
            self.project_name, project_id, "Voice Test Bob", 
            primary_image_path="/path/to/bob.png",
            voice_profile=voice_profile
        )
        self.assertGreater(char_id, 0)
        
        # Verify columns are returned
        char = memory.get_character(self.project_name, project_id, char_id)
        self.assertEqual(char["primary_image_path"], "/path/to/bob.png")
        self.assertEqual(char["voice_profile"], voice_profile)
        
        # Test character_assets table CRUD
        asset_id = memory.add_character_asset(
            self.project_name, project_id, char_id, 
            asset_type="reference_image", path="/path/to/bob_side.png", 
            metadata={"angle": "side"}
        )
        self.assertGreater(asset_id, 0)
        
        # Retrieve assets
        assets = memory.get_character_assets(self.project_name, project_id, char_id)
        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["asset_type"], "reference_image")
        self.assertEqual(assets[0]["path"], "/path/to/bob_side.png")
        self.assertEqual(assets[0]["metadata"]["angle"], "side")

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
            self.assertIn("casting", result)
            self.assertEqual(result["casting"]["region_id"], "archive_hall")
            self.assertIn("scene", result)
            self.assertTrue(result["scene"]["ok"])
            self.assertEqual(result["scene"]["phase"], "director_scene_planning")
            self.assertTrue(result["model_status"]["llm_attempted"])
            self.assertFalse(result["model_status"]["llm_ready"])
            self.assertTrue(result["model_status"]["used_fallback"])
            
            # Verify data stored in memory
            premise = memory.get_bible(self.project_name, runner.project_id).get("premise")
            self.assertIsNotNone(premise)
            self.assertIn("magic key", premise["premise"].lower() or premise["title"].lower())
            
            chars = memory.get_characters(self.project_name, runner.project_id)
            self.assertEqual(len(chars), 2)
            self.assertEqual(chars[0]["metadata"]["source"], "director_casting")
            self.assertEqual(chars[0]["metadata"]["skin_id"], "young_archivist")
            self.assertEqual(memory.get_bible(self.project_name, runner.project_id)["casting"]["region_id"], "archive_hall")
            self.assertIn("scene_spec", memory.get_bible(self.project_name, runner.project_id))
            graph = memory.get_gest_graph(self.project_name, runner.project_id)
            self.assertGreaterEqual(len(graph["nodes"]), 3)
            
            panels = memory.get_panels(self.project_name, runner.project_id)
            self.assertEqual(len(panels), 12)
            
            warnings = memory.get_continuity_warnings(self.project_name, runner.project_id)
            self.assertGreater(len(warnings), 0)

    def test_brief_review_runs_before_full_production(self):
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            runner = StudioWorkflowRunner(self.project_name)
            review = runner.run_brief_review(
                "A sister searches for her missing brother in a flooded city.",
                user_notes="Keep it emotional, not action-heavy.",
            )

        self.assertIn("guess", review)
        self.assertIn("open_questions", review)
        self.assertIn("small_fix_suggestions", review)
        self.assertTrue(review["model_status"]["llm_attempted"])
        self.assertTrue(review["model_status"]["used_fallback"])

    def test_workflow_can_rerun_on_same_project_without_panel_number_collision(self):
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            first = StudioWorkflowRunner(self.project_name)
            first_result = first.run_full_pipeline("Find the magic key in the kitchen")
            self.assertTrue(first_result["ok"])

            second = StudioWorkflowRunner(self.project_name)
            second_result = second.run_full_pipeline("Find the magic key in the kitchen again")
            self.assertTrue(second_result["ok"], second_result.get("error"))

            panels = memory.get_panels(self.project_name, second.project_id)
            self.assertGreaterEqual(len(panels), 12)

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

    def test_director_scene_planning_generates_scene_spec_and_commits_gest(self):
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            runner = StudioWorkflowRunner(self.project_name)
            premise = runner.run_intake("Find the magic key in the kitchen")
            runner.run_director_casting(premise_data=premise)
            world = runner.run_world_building(premise)
            chars = runner.run_character_building(premise, world)
            story_plan, _episode_id = runner.run_story_planning(premise, world, chars)
            result = runner.run_director_scene_planning(premise, world, chars, story_plan)

        self.assertTrue(result["ok"])
        self.assertEqual(result["phase"], "director_scene_planning")
        self.assertEqual(result["scene_spec"]["region_id"], "archive_hall")
        self.assertGreaterEqual(len(result["data"]["graph"]["nodes"]), 3)

        bible = memory.get_bible(self.project_name, runner.project_id)
        self.assertEqual(bible["scene_spec"]["region_id"], "archive_hall")

    def test_story_planning_falls_back_when_model_returns_list_shape(self):
        runner = StudioWorkflowRunner(self.project_name)
        premise = {"title": "Broken Shape", "premise": "A malformed model response should not crash."}
        world = {"setting": "Test", "aesthetic": "Test", "rules": []}
        characters = [{"id": 1, "name": "Mara"}]

        with patch.object(runner, "_call_llm_with_fallback", return_value=[{"bad": "shape"}]):
            story_plan, episode_id = runner.run_story_planning(premise, world, characters)

        self.assertIsInstance(story_plan, dict)
        self.assertIn("summary", story_plan)
        self.assertGreater(episode_id, 0)
        self.assertTrue(runner.model_status["used_fallback"])

    def test_adapt_mode_grounds_on_source_story(self):
        # "Start from" an existing story: source text should be persisted and threaded through stages.
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):

            story = (
                "Mara the lighthouse keeper found a drowned sailor still breathing. "
                "She nursed him back over three storm-lashed nights, and he told her the sea "
                "had a door at its bottom that only the lonely could open."
            )
            runner = StudioWorkflowRunner(self.project_name)
            result = runner.run_full_pipeline(story, mode="adapt")

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "adapt")

            # Mode + full source story are persisted for later stages / continuity.
            prefs = memory.get_user_preferences(self.project_name, runner.project_id)
            self.assertEqual(prefs.get("story_mode"), "adapt")
            self.assertEqual(prefs.get("source_story"), story)

            # Bible records the production mode.
            bible = memory.get_bible(self.project_name, runner.project_id)
            self.assertEqual(bible.get("mode"), "adapt")

            # Still produces a full 12-panel reel.
            panels = memory.get_panels(self.project_name, runner.project_id)
            self.assertEqual(len(panels), 12)

    def test_continue_mode_uses_seed_text_as_source(self):
        # "Continue from" with the story arriving via seed_text (no explicit source_story).
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):

            story = "The crew finally reached the floating city, only to find every lantern dark and every door open."
            runner = StudioWorkflowRunner(self.project_name)
            result = runner.run_full_pipeline(story, mode="continue")

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "continue")
            prefs = memory.get_user_preferences(self.project_name, runner.project_id)
            self.assertEqual(prefs.get("story_mode"), "continue")
            self.assertEqual(prefs.get("source_story"), story)

    def test_mode_normalization_aliases(self):
        runner = StudioWorkflowRunner(self.project_name)
        self.assertEqual(runner._normalize_mode("start_from"), "adapt")
        self.assertEqual(runner._normalize_mode("Start"), "adapt")
        self.assertEqual(runner._normalize_mode("continue_from"), "continue")
        self.assertEqual(runner._normalize_mode("sequel"), "continue")
        self.assertEqual(runner._normalize_mode("anything else"), "seed")
        self.assertEqual(runner._normalize_mode(None), "seed")

    def test_long_story_excerpt_is_bounded(self):
        runner = StudioWorkflowRunner(self.project_name)
        long_story = "A" * 5000 + "MIDDLE_MARKER" + "Z" * 5000
        excerpt = runner._story_excerpt(long_story)
        self.assertLessEqual(len(excerpt), 6200)  # bounded around STORY_CONTEXT_CHARS plus the elision notice
        self.assertIn("AAAA", excerpt)
        self.assertIn("ZZZZ", excerpt)
        self.assertIn("omitted", excerpt)

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

                # 1b. Run Director phase 1 exploration
                res = client.post("/studio/workflow/explore", json={"project_name": self.project_name})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["phase"], "exploration")
                self.assertIn("regions", res.json()["data"])

                # 1c. Run Director casting (anchors a registry region + skins)
                res = client.post("/studio/workflow/cast", json={"project_name": self.project_name})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["phase"], "casting")
                self.assertIn("cast", res.json()["data"])

                # 2. Run workflow stage intake
                res = client.post("/studio/workflow/stage", json={
                    "project_name": self.project_name,
                    "stage": "intake",
                    "seed_text": "A clockwork key is stolen"
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["stage"], "intake")

                # 2b. Run pre-production brief review
                res = client.post("/studio/workflow/brief", json={
                    "project_name": self.project_name,
                    "seed_text": "A clockwork key is stolen",
                    "user_notes": "Ask before committing to the plot."
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["status"], "success")
                self.assertIn("guess", res.json()["data"])

                # 2c. Run Director scene planning without hand-writing a scene spec.
                res = client.post("/studio/workflow/stage", json={
                    "project_name": self.project_name,
                    "stage": "scene_planning"
                })
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["stage"], "scene_planning")
                self.assertTrue(res.json()["data"]["ok"])
                
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

    def test_director_exploration_records_registry_snapshot(self):
        runner = StudioWorkflowRunner(self.project_name)
        result = runner.run_director_exploration(page_size=2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["phase"], "exploration")
        self.assertEqual(len(result["data"]["regions"]["items"]), 2)

        prefs = memory.get_user_preferences(self.project_name, runner.project_id)
        self.assertEqual(prefs.get("director_exploration_registry"), "studio-director-exploration-v1")

    def test_director_casting_grounds_in_registry(self):
        # With no live LLM, casting must fall back to a registry-valid default and anchor it.
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):

            runner = StudioWorkflowRunner(self.project_name)
            result = runner.run_director_casting()

            self.assertTrue(result["ok"])
            self.assertEqual(result["phase"], "casting")
            casting = result["data"]

            # Region and every cast skin must exist in the capability registry.
            self.assertIsNotNone(studio_capabilities.get_capability("regions", casting["region_id"]))
            self.assertGreaterEqual(len(casting["cast"]), 2)
            for member in casting["cast"]:
                self.assertIsNotNone(studio_capabilities.get_capability("skins", member["skin_id"]))
                self.assertTrue(member["character_name"])

            # Casting is persisted: region anchored as a location, selection saved to bible + prefs.
            locations = memory.get_locations(self.project_name, runner.project_id)
            self.assertIn(casting["region_name"], {loc["name"] for loc in locations})
            self.assertEqual(memory.get_bible(self.project_name, runner.project_id)["casting"]["region_id"], casting["region_id"])
            prefs = memory.get_user_preferences(self.project_name, runner.project_id)
            self.assertEqual(prefs.get("director_casting")["region_id"], casting["region_id"])

            # Re-running casting must not duplicate the anchored location.
            runner.run_director_casting()
            locations_after = memory.get_locations(self.project_name, runner.project_id)
            self.assertEqual(
                len([loc for loc in locations_after if loc["name"] == casting["region_name"]]),
                1,
            )

    def test_validate_casting_rejects_ungrounded_ids(self):
        # A region/skin not in the registry must be rejected deterministically.
        with self.assertRaises(ValueError):
            studio_capabilities.validate_casting({"region_id": "atlantis", "cast": [
                {"skin_id": "young_archivist", "character_name": "Mara", "role": "lead"},
                {"skin_id": "masked_rival", "character_name": "Rival", "role": "rival"},
            ]})
        with self.assertRaises(ValueError):
            studio_capabilities.validate_casting({"region_id": "archive_hall", "cast": [
                {"skin_id": "nonexistent_skin", "character_name": "Ghost", "role": "lead"},
                {"skin_id": "masked_rival", "character_name": "Rival", "role": "rival"},
            ]})
        # A registry-valid selection normalizes cleanly.
        clean = studio_capabilities.validate_casting({"region_id": "archive_hall", "cast": [
            {"skin_id": "young_archivist", "character_name": "Mara", "role": "lead"},
            {"skin_id": "masked_rival", "character_name": "Rival", "role": "rival"},
        ]})
        self.assertEqual(clean["region_id"], "archive_hall")
        self.assertEqual(clean["cast"][0]["skin_name"], "Young Archivist")

    def test_intake_interview_turn(self):
        from fastapi.testclient import TestClient
        from server import app
        
        with patch("studio_workflow.get_engine_if_initialized", return_value=None), \
             patch("studio_workflow.get_engine", return_value=None):
            
            client = TestClient(app)
            
            # Turn 1: Should trigger fallback and ask follow up
            res = client.post("/studio/workflow/intake/turn", json={
                "project_name": self.project_name,
                "chat_history": [{"role": "user", "content": "I want to make a story about a space pirate."}]
            })
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertFalse(data["is_complete"])
            self.assertIn("response_text", data)
            
            # Turn 2: Should trigger fallback completion
            res = client.post("/studio/workflow/intake/turn", json={
                "project_name": self.project_name,
                "chat_history": [
                    {"role": "user", "content": "I want to make a story about a space pirate."},
                    {"role": "assistant", "content": "That sounds like a great start!"},
                    {"role": "user", "content": "Gritty and fast-paced."}
                ]
            })
            self.assertEqual(res.status_code, 200)
            data = res.json()["data"]
            self.assertTrue(data["is_complete"])
            self.assertEqual(data["draft_premise"]["theme"], "Action")


if __name__ == "__main__":
    unittest.main()
