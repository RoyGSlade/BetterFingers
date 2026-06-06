import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
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
