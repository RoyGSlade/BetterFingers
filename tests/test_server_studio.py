import io
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
import studio_capabilities
import studio_memory


class ServerStudioTests(unittest.TestCase):
    def test_studio_project_endpoint_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                with TestClient(server.app) as client:
                    created = client.post("/studio/projects", json={"name": "Arcanum Pilot", "preferences": {"format": "comic reel"}})
                    self.assertEqual(created.status_code, 200)
                    project = created.json()["project"]
                    project_name = project["name"]
                    listed = client.get("/studio/projects")
                    legacy_listed = client.get("/studio/project/list")

                    bible = client.post(
                        f"/studio/projects/{project_name}/bible",
                        json={"content": {"premise": "A local-first story engine."}},
                    )
                    character = client.post(
                        f"/studio/projects/{project_name}/characters",
                        json={
                            "name": "Mara",
                            "description": "Archivist",
                            "role": "Lead",
                            "archetype": "Seeker",
                        },
                    )
                    character_id = character.json()["character"]["id"]
                    updated = client.put(
                        f"/studio/projects/{project_name}/characters/{character_id}",
                        json={
                            "name": "Mara Vale",
                            "description": "Lead archivist",
                            "role": "Lead",
                            "archetype": "Seeker",
                            "status": "approved",
                        },
                    )
                    episode = client.post(
                        f"/studio/projects/{project_name}/episodes",
                        json={"name": "Episode 1", "summary": "The archive opens."},
                    )
                    episode_id = episode.json()["episode_id"]
                    minute = client.post(
                        f"/studio/projects/{project_name}/minutes",
                        json={"episode_id": episode_id, "minute_number": 1, "summary": "Opening minute"},
                    )
                    minute_id = minute.json()["minute_id"]
                    page = client.post(
                        f"/studio/projects/{project_name}/pages",
                        json={"episode_id": episode_id, "page_number": 1, "title": "Page 1", "summary": "Opening page"},
                    )
                    page_id = page.json()["page_id"]
                    panel = client.post(
                        f"/studio/projects/{project_name}/panels",
                        json={
                            "minute_id": minute_id,
                            "page_id": page_id,
                            "panel_number": 1,
                            "visual_description": "Mara opens a glowing vault.",
                            "style_prompt": "comic noir",
                        },
                    )
                    panel_id = panel.json()["panel_id"]
                    panels = client.get(f"/studio/projects/{project_name}/panels")
                    warning = client.post(
                        f"/studio/projects/{project_name}/continuity-warnings",
                        json={
                            "target_type": "panel",
                            "target_id": panel_id,
                            "severity": "medium",
                            "message": "Vault symbol changed.",
                        },
                    )
                    approval = client.post(
                        f"/studio/projects/{project_name}/approvals",
                        json={"item_type": "panel", "item_id": panel_id, "approved": True, "approved_by": "Tester"},
                    )
                    image_upload = client.post(
                        "/studio/project/panel-image",
                        data={"project_name": project_name, "project_id": project["id"], "panel_id": panel_id},
                        files={"file": ("panel.png", io.BytesIO(b"\x89PNG\r\n\x1a\n"), "image/png")},
                    )
                    loaded = client.get(f"/studio/projects/{project_name}")
                    exported = client.get(f"/studio/projects/{project_name}/export")

        self.assertEqual(bible.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["projects"][0]["name"], "Arcanum Pilot")
        self.assertEqual(legacy_listed.status_code, 200)
        self.assertEqual(legacy_listed.json()["projects"][0]["name"], "Arcanum Pilot")
        self.assertEqual(character.status_code, 200)
        self.assertEqual(updated.json()["character"]["name"], "Mara Vale")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(panels.status_code, 200)
        self.assertEqual(panels.json()["panels"][0]["panel_number"], 1)
        self.assertEqual(warning.status_code, 200)
        self.assertEqual(approval.status_code, 200)
        self.assertEqual(image_upload.status_code, 200)
        self.assertTrue(approval.json()["approvals"][0]["approved"])
        self.assertEqual(loaded.json()["bible"]["premise"], "A local-first story engine.")
        self.assertEqual(exported.json()["pages"][0]["title"], "Page 1")
        self.assertEqual(exported.json()["panels"][0]["page_id"], page_id)
        self.assertEqual(exported.json()["panels"][0]["metadata"]["image_source"], "user_upload")
        self.assertEqual(exported.json()["assets"][0]["metadata"]["panel_id"], panel_id)
        self.assertEqual(exported.json()["spec"], studio_memory.STUDIO_SPEC_TITLE)

    def test_studio_project_endpoint_validation_errors_are_400(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                with TestClient(server.app) as client:
                    created = client.post("/studio/projects", json={"name": "Validation Project"})
                    self.assertEqual(created.status_code, 200)
                    project_name = created.json()["project"]["name"]

                    blank_character = client.post(
                        f"/studio/projects/{project_name}/characters",
                        json={"name": " "},
                    )
                    orphan_minute = client.post(
                        f"/studio/projects/{project_name}/minutes",
                        json={"episode_id": 999, "minute_number": 1},
                    )
                    bad_warning = client.post(
                        f"/studio/projects/{project_name}/continuity-warnings",
                        json={
                            "target_type": "panel",
                            "target_id": 1,
                            "severity": "urgent",
                            "message": "Bad severity.",
                        },
                    )

        self.assertEqual(blank_character.status_code, 400)
        self.assertEqual(orphan_minute.status_code, 400)
        self.assertEqual(bad_warning.status_code, 400)

    def test_studio_scene_rejection_returns_repair_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                with TestClient(server.app) as client:
                    created = client.post("/studio/projects", json={"name": "Repair Project"})
                    self.assertEqual(created.status_code, 200)
                    project_name = created.json()["project"]["name"]

                    # An invalid scene spec (unknown POI) must be rejected with a
                    # structured, grounded repair report rather than a bare error.
                    rejected = client.post(
                        "/studio/workflow/scene",
                        json={
                            "project_name": project_name,
                            "scene": {
                                "region_id": "forgotten_archive",
                                "actors": [{"id": "mara", "name": "Mara", "start_poi": "no_such_poi"}],
                                "chains": [{"actor": "mara", "actions": [{"action": "stand_at"}]}],
                            },
                        },
                    )
        self.assertEqual(rejected.status_code, 200)
        body = rejected.json()
        self.assertEqual(body["status"], "rejected")
        self.assertFalse(body["ok"])
        repair = body["repair"]
        self.assertEqual(repair["phase"], "scene_planning")
        self.assertIn(repair["category"], ("region", "poi"))
        self.assertTrue(repair["question"])
        self.assertTrue(repair["valid_options"])

    def test_studio_repair_propose_returns_grounded_proposals(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                with TestClient(server.app) as client:
                    created = client.post("/studio/projects", json={"name": "Propose Project"})
                    project_name = created.json()["project"]["name"]
                    report = {
                        "phase": "scene_planning",
                        "category": "poi",
                        "error": "Unknown POI 'rooftop'.",
                        "valid_options": [{"id": "archive_table", "name": "Archive Table", "description": ""}],
                        "valid_options_label": "Valid points of interest",
                    }
                    proposed = client.post(
                        "/studio/workflow/repair/propose",
                        json={"project_name": project_name, "report": report, "user_note": "I wanted them on a high ledge."},
                    )
        self.assertEqual(proposed.status_code, 200)
        payload = proposed.json()
        self.assertIn("proposals", payload)
        self.assertTrue(payload["proposals"])
        # The LLM sidecar is offline in tests, so we must get the deterministic
        # grounded fallback (set-to-valid-option plus a freeform escape hatch).
        types = {(p.get("resolution") or {}).get("type") for p in payload["proposals"]}
        self.assertIn("freeform", types)

    def test_studio_blackboard_endpoint_reports_artifacts_and_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(studio_memory, "get_user_data_path", return_value=tmp):
                with TestClient(server.app) as client:
                    client.post("/studio/projects", json={"name": "Board Project"})
                    # Seed a couple of blackboard rows directly (the Producer writes these live).
                    import studio_blackboard
                    proj = studio_memory.get_project_by_name("Board Project")
                    studio_blackboard.put_artifact("Board Project", proj["id"], "world", {"palette": "amber"}, produced_by="world")
                    studio_blackboard.post("Board Project", proj["id"], "world", "running", "World Builder", "Building the world")
                    board = client.get("/studio/projects/Board Project/blackboard")
        self.assertEqual(board.status_code, 200)
        payload = board.json()
        self.assertTrue(payload["ok"])
        self.assertIn("world", [a["key"] for a in payload["artifacts"]])
        self.assertTrue(any(p["agent"] == "world" for p in payload["posts"]))

    def test_studio_capability_exploration_endpoints_are_paginated_and_read_only(self):
        with TestClient(server.app) as client:
            categories = client.get("/studio/capabilities")
            self.assertEqual(categories.status_code, 200)
            self.assertEqual(categories.json()["registry_version"], studio_capabilities.REGISTRY_VERSION)
            self.assertIn("regions", [item["category"] for item in categories.json()["categories"]])

            regions = client.get("/studio/capabilities/regions?page=1&page_size=2")
            self.assertEqual(regions.status_code, 200)
            self.assertEqual(regions.json()["category"], "regions")
            self.assertEqual(len(regions.json()["items"]), 2)
            self.assertGreaterEqual(regions.json()["total"], 3)

            archive = client.get("/studio/capabilities/pois?query=archive")
            self.assertEqual(archive.status_code, 200)
            self.assertTrue(all("archive" in (item["id"] + item["name"]).lower() for item in archive.json()["items"]))

            action = client.get("/studio/capabilities/actions/stand_at")
            self.assertEqual(action.status_code, 200)
            self.assertEqual(action.json()["capability"]["id"], "stand_at")

            next_actions = client.get("/studio/capabilities/actions/stand_at/next")
            self.assertEqual(next_actions.status_code, 200)
            self.assertGreater(len(next_actions.json()["next_actions"]), 0)

            invalid = client.get("/studio/capabilities/vehicles")
            self.assertEqual(invalid.status_code, 400)
