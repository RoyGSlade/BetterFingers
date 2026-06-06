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
                    panel = client.post(
                        f"/studio/projects/{project_name}/panels",
                        json={
                            "minute_id": minute_id,
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
                    loaded = client.get(f"/studio/projects/{project_name}")
                    exported = client.get(f"/studio/projects/{project_name}/export")

        self.assertEqual(bible.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["projects"][0]["name"], "Arcanum Pilot")
        self.assertEqual(legacy_listed.status_code, 200)
        self.assertEqual(legacy_listed.json()["projects"][0]["name"], "Arcanum Pilot")
        self.assertEqual(character.status_code, 200)
        self.assertEqual(updated.json()["character"]["name"], "Mara Vale")
        self.assertEqual(panels.status_code, 200)
        self.assertEqual(panels.json()["panels"][0]["panel_number"], 1)
        self.assertEqual(warning.status_code, 200)
        self.assertEqual(approval.status_code, 200)
        self.assertTrue(approval.json()["approvals"][0]["approved"])
        self.assertEqual(loaded.json()["bible"]["premise"], "A local-first story engine.")
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
