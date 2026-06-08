import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import studio_memory


class StudioMemoryTests(unittest.TestCase):
    def test_studio_projects_dir_reports_permission_fix_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp), \
                 patch.object(studio_memory, "_handoff_path_to_user"), \
                 patch.object(studio_memory.os, "access", return_value=False), \
                 patch.dict(studio_memory.os.environ, {"USER": "donaven"}, clear=False):
                with self.assertRaises(PermissionError) as raised:
                    studio_memory.get_studio_projects_dir()

        message = str(raised.exception)
        self.assertIn("Studio projects folder is not writable", message)
        self.assertIn("sudo chown -R donaven:donaven", message)

    def test_handoff_path_to_user_chowns_project_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project_dir = Path(tmp) / "Project"
            asset_dir = project_dir / "assets"
            asset_dir.mkdir(parents=True)
            asset_file = asset_dir / "panel.png"
            asset_file.write_text("image bytes")

            chowned = []

            def record_chown(path, uid, gid):
                chowned.append((Path(path), uid, gid))

            with patch.object(studio_memory, "_target_user_ids_for_handoff", return_value=(1000, 1000)), \
                 patch.object(studio_memory, "_chown_path", side_effect=record_chown):
                studio_memory._handoff_path_to_user(project_dir, recursive=True)

        self.assertIn((project_dir, 1000, 1000), chowned)
        self.assertIn((asset_dir, 1000, 1000), chowned)
        self.assertIn((asset_file, 1000, 1000), chowned)

    def test_root_handoff_prefers_sudo_user_ids(self):
        with patch.object(studio_memory.os, "name", "posix"), \
             patch.object(studio_memory.os, "geteuid", return_value=0, create=True), \
             patch.dict(studio_memory.os.environ, {"SUDO_UID": "1000", "SUDO_GID": "1000"}, clear=True):
            self.assertEqual(studio_memory._target_user_ids_for_handoff(), (1000, 1000))

    def test_project_creation_hands_off_project_tree_on_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp), \
                 patch.object(studio_memory, "_handoff_path_to_user") as handoff:
                project = studio_memory.create_project("Ownership Handoff")

        recursive_paths = [
            Path(call.args[0])
            for call in handoff.call_args_list
            if call.kwargs.get("recursive")
        ]
        self.assertIn(Path(project["path"]), recursive_paths)

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
                    "pages",
                    "minutes",
                    "panels",
                    "dialogue_lines",
                    "assets",
                    "canon_events",
                    "continuity_warnings",
                    "approvals",
                    "tool_calls",
                    "gest_nodes",
                    "gest_edges",
                }
                self.assertTrue(expected_tables.issubset(tables))

                studio_memory.save_bible(project_name, project_id, {"world": {"rule": "canon matters"}})
                character_id = studio_memory.add_character(project_name, project_id, "Mara", "Archivist", "Lead", "Seeker")
                character = studio_memory.update_character(project_name, project_id, character_id, description="Lead archivist")
                episode_id = studio_memory.add_episode(project_name, project_id, "Minute One", "A hidden archive opens.")
                minute_id = studio_memory.add_minute(project_name, project_id, episode_id, 1, "Opening beat")
                page_id = studio_memory.add_page(project_name, project_id, episode_id, 1, "Page 1", "Opening page")
                panel_id = studio_memory.add_panel(project_name, project_id, minute_id, 1, "Mara finds the vault.", "ink noir", page_id=page_id)
                line_id = studio_memory.add_dialogue_line(project_name, project_id, panel_id, "Mara", "This was buried for a reason.")
                asset_id = studio_memory.add_asset(project_name, project_id, "image", "assets/images/panel-001.png", {"panel_id": panel_id})
                warning_id = studio_memory.add_continuity_warning(project_name, project_id, "panel", panel_id, "medium", "Lantern color changed")
                approval_id = studio_memory.record_approval(project_name, project_id, "panel", panel_id, True, approved_by="Tester")
                tool_call_id = studio_memory.log_tool_call(project_name, project_id, "mock_tool", {"a": 1}, {"ok": True})

                export = studio_memory.export_project_json(project_name, project_id)
                listed = studio_memory.list_projects()

                self.assertEqual(character["description"], "Lead archivist")
                self.assertEqual(listed[0]["name"], project_name)
                self.assertEqual(export["spec"], studio_memory.STUDIO_SPEC_TITLE)
                self.assertEqual(export["user_preferences"]["tone"], "noir")
                self.assertEqual(export["bible"]["world"]["rule"], "canon matters")
                self.assertEqual(export["characters"][0]["id"], character_id)
                self.assertEqual(export["pages"][0]["id"], page_id)
                self.assertEqual(export["panels"][0]["page_id"], page_id)
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
                page_id = studio_memory.add_page(project_name, project_id, episode_id, 1)

                with self.assertRaises(ValueError):
                    studio_memory.add_page(project_name, project_id, episode_id, 1)

                with self.assertRaises(ValueError):
                    studio_memory.add_minute(project_name, project_id, episode_id, 1)

                panel_id = studio_memory.add_panel(project_name, project_id, minute_id, 1, page_id=page_id)

                with self.assertRaises(ValueError):
                    studio_memory.add_panel(project_name, project_id, minute_id, 1, page_id=page_id)

                with self.assertRaises(ValueError):
                    studio_memory.add_continuity_warning(project_name, project_id, "panel", panel_id, "urgent", "Bad severity")

                with self.assertRaises(ValueError):
                    studio_memory.record_approval(project_name, project_id, "panel", 999, True)

    def test_gest_graph_nodes_edges_and_temporal_cycle_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                project = studio_memory.create_project("GEST Graph")
                project_name = project["name"]
                project_id = project["id"]

                a = studio_memory.add_gest_node(project_name, project_id, "event", "Mara enters the archive")
                b = studio_memory.add_gest_node(project_name, project_id, "event", "Mara opens the vault")
                c = studio_memory.add_gest_node(project_name, project_id, "event", "The rival arrives")

                # Invalid node type is rejected.
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_node(project_name, project_id, "teleport", "bad node")

                # Temporal ordering A before B, B before C.
                studio_memory.add_gest_edge(project_name, project_id, a, b, "before")
                studio_memory.add_gest_edge(project_name, project_id, b, c, "before")
                # A logical relation derives its class automatically.
                causal = studio_memory.add_gest_edge(project_name, project_id, b, c, "causes")
                self.assertGreater(causal, 0)

                # Unknown relation and self-loops are rejected.
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_edge(project_name, project_id, a, c, "teleports_to")
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_edge(project_name, project_id, a, a, "before")
                # Mismatched relation_class is rejected.
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_edge(project_name, project_id, a, c, "before", relation_class="logical")

                # Closing the loop (C before A) would create a temporal cycle -> rejected.
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_edge(project_name, project_id, c, a, "before")
                # The same cycle expressed via 'after' (A after C) is also rejected.
                with self.assertRaises(ValueError):
                    studio_memory.add_gest_edge(project_name, project_id, a, c, "after")

                graph = studio_memory.get_gest_graph(project_name, project_id)
                self.assertEqual(len(graph["nodes"]), 3)
                # before, before, causes committed; the cycle attempts did not.
                self.assertEqual(len(graph["edges"]), 3)
                relations = {edge["relation"] for edge in graph["edges"]}
                self.assertEqual(relations, {"before", "causes"})

                export = studio_memory.export_project_json(project_name, project_id)
                self.assertEqual(len(export["gest"]["nodes"]), 3)

                # The temporal timeline is a valid topological order: a before b before c.
                timeline = studio_memory.compute_gest_timeline(project_name, project_id)
                self.assertTrue(timeline["valid"])
                self.assertFalse(timeline["has_cycle"])
                self.assertEqual(timeline["node_count"], 3)
                order = timeline["order"]
                self.assertLess(order.index(a), order.index(b))
                self.assertLess(order.index(b), order.index(c))
