import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import studio_memory


class StudioMemoryTests(unittest.TestCase):
    def test_project_schema_structure_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                project = studio_memory.create_project("Arcanum Pilot", preferences={"tone": "noir"})
                project_name = project["name"]
                project_id = project["id"]

                project_dir = Path(project["path"])
                self.assertTrue((project_dir / "studio.db").exists())
                for relative in studio_memory.PROJECT_ASSET_DIRS:
                    self.assertTrue((project_dir / relative).is_dir())

                db_path, _ = studio_memory.get_project_db_path(project_name)
                with sqlite3.connect(db_path) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        ).fetchall()
                    }

                expected_tables = {
                    "projects",
                    "user_preferences",
                    "bibles",
                    "characters",
                    "locations",
                    "episodes",
                    "minutes",
                    "panels",
                    "dialogue_lines",
                    "assets",
                    "canon_events",
                    "continuity_warnings",
                    "approvals",
                    "tool_calls",
                }
                self.assertTrue(expected_tables.issubset(tables))

                studio_memory.save_bible(project_name, project_id, {"world": {"rule": "canon matters"}})
                character_id = studio_memory.add_character(project_name, project_id, "Mara", "Archivist", "Lead", "Seeker")
                character = studio_memory.update_character(project_name, project_id, character_id, description="Lead archivist")
                episode_id = studio_memory.add_episode(project_name, project_id, "Minute One", "A hidden archive opens.")
                minute_id = studio_memory.add_minute(project_name, project_id, episode_id, 1, "Opening beat")
                panel_id = studio_memory.add_panel(project_name, project_id, minute_id, 1, "Mara finds the vault.", "ink noir")
                line_id = studio_memory.add_dialogue_line(project_name, project_id, panel_id, "Mara", "This was buried for a reason.")
                asset_id = studio_memory.add_asset(project_name, project_id, "image", "assets/images/panel-001.png", {"panel_id": panel_id})
                warning_id = studio_memory.add_continuity_warning(project_name, project_id, "panel", panel_id, "medium", "Lantern color changed")
                approval_id = studio_memory.record_approval(project_name, project_id, "panel", panel_id, True, approved_by="Tester")
                tool_call_id = studio_memory.log_tool_call(project_name, project_id, "mock_tool", {"a": 1}, {"ok": True})

                export = studio_memory.export_project_json(project_name, project_id)

                self.assertEqual(character["description"], "Lead archivist")
                self.assertEqual(export["spec"], studio_memory.STUDIO_SPEC_TITLE)
                self.assertEqual(export["user_preferences"]["tone"], "noir")
                self.assertEqual(export["bible"]["world"]["rule"], "canon matters")
                self.assertEqual(export["characters"][0]["id"], character_id)
                self.assertEqual(export["dialogue_lines"][0]["id"], line_id)
                self.assertEqual(export["assets"][0]["id"], asset_id)
                self.assertEqual(export["continuity_warnings"][0]["id"], warning_id)
                self.assertEqual(export["approvals"][0]["id"], approval_id)
                self.assertEqual(export["tool_calls"][0]["id"], tool_call_id)
                self.assertTrue(export["panels"][0]["approved"])

    def test_assets_must_stay_inside_project_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                project = studio_memory.create_project("Asset Guard")
                outside = os.path.join(tmp, "outside.png")

                with self.assertRaises(ValueError):
                    studio_memory.add_asset(project["name"], project["id"], "image", outside)

    def test_rejects_invalid_studio_memory_edges(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                project = studio_memory.create_project("Guard Rails")
                project_name = project["name"]
                project_id = project["id"]

                with self.assertRaises(ValueError):
                    studio_memory.add_character(project_name, project_id, " ")

                with self.assertRaises(ValueError):
                    studio_memory.add_minute(project_name, project_id, 999, 1)

                episode_id = studio_memory.add_episode(project_name, project_id, "Episode")
                minute_id = studio_memory.add_minute(project_name, project_id, episode_id, 1)

                with self.assertRaises(ValueError):
                    studio_memory.add_minute(project_name, project_id, episode_id, 1)

                panel_id = studio_memory.add_panel(project_name, project_id, minute_id, 1)

                with self.assertRaises(ValueError):
                    studio_memory.add_panel(project_name, project_id, minute_id, 1)

                with self.assertRaises(ValueError):
                    studio_memory.add_continuity_warning(project_name, project_id, "panel", panel_id, "urgent", "Bad severity")

                with self.assertRaises(ValueError):
                    studio_memory.record_approval(project_name, project_id, "panel", 999, True)
