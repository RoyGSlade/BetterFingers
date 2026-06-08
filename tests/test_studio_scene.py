import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import studio_memory
import server
from studio_scene import SceneBuilder, SceneError
from studio_workflow import StudioWorkflowRunner


class StudioSceneBuilderTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(studio_memory, "get_user_data_path", return_value=self._tmp.name)
        self.patcher.start()
        project = studio_memory.create_project("Scene Lab")
        self.project_name = project["name"]
        self.project_id = project["id"]

    def tearDown(self):
        self.patcher.stop()
        self._tmp.cleanup()

    def _builder(self):
        return SceneBuilder(self.project_name, self.project_id)

    def test_valid_chain_commits_to_gest(self):
        builder = self._builder()
        builder.start_round("archive_hall", [
            {"id": "mara", "name": "Mara", "skin_id": "young_archivist", "start_poi": "archive_table"},
        ])
        builder.start_chain("mara")
        # stand_at -> inspect_object -> write_note is a registry-valid successor chain,
        # all supported by the archive_table POI.
        builder.add_action("stand_at")
        builder.add_action("inspect_object")
        builder.add_action("write_note")
        result = builder.end_round()

        self.assertTrue(result["committed"])
        graph = studio_memory.get_gest_graph(self.project_name, self.project_id)
        action_nodes = [n for n in graph["nodes"] if n["node_type"] == "action"]
        exists_nodes = [n for n in graph["nodes"] if n["node_type"] == "exists"]
        self.assertEqual(len(action_nodes), 3)
        self.assertEqual(len(exists_nodes), 1)  # one actor anchored once
        # Three sequential actions -> two temporal 'before' edges.
        before_edges = [e for e in graph["edges"] if e["relation"] == "before"]
        self.assertEqual(len(before_edges), 2)

    def test_rejects_action_not_supported_by_poi(self):
        builder = self._builder()
        builder.start_round("archive_hall", [{"id": "mara", "start_poi": "archive_table"}])
        builder.start_chain("mara")
        builder.add_action("stand_at")
        # 'hide' is a valid action but archive_table does not support it.
        with self.assertRaises(SceneError):
            builder.add_action("hide")

    def test_rejects_out_of_order_action_chain(self):
        builder = self._builder()
        builder.start_round("archive_hall", [{"id": "mara", "start_poi": "archive_table"}])
        builder.start_chain("mara")
        builder.add_action("stand_at")
        # write_note is not a permitted successor of stand_at.
        with self.assertRaises(SceneError):
            builder.add_action("write_note")

    def test_rejects_poi_over_capacity(self):
        builder = self._builder()
        # sealed_case has capacity 1; placing a second actor there must fail.
        with self.assertRaises(SceneError):
            builder.start_round("archive_hall", [
                {"id": "a", "start_poi": "sealed_case"},
                {"id": "b", "start_poi": "sealed_case"},
            ])

    def test_give_object_interaction_transfers_and_syncs(self):
        builder = self._builder()
        builder.start_round("rain_market", [
            {"id": "giver", "name": "Giver", "start_poi": "ramen_stall", "held": ["bowl"]},
            {"id": "receiver", "name": "Receiver", "start_poi": "ramen_stall"},
        ])
        builder.start_chain("giver")
        builder.add_action("sit_at")            # ramen_stall supports sit_at -> sitting
        builder.add_action("talk")              # sit_at -> talk is allowed
        builder.do_interaction("give_object", receiver_id="receiver", target_object="bowl")
        result = builder.end_round()

        self.assertTrue(result["committed"])
        # The bowl moved from giver to receiver in committed state.
        receiver = next(a for a in result["state"]["actors"] if a["id"] == "receiver")
        giver = next(a for a in result["state"]["actors"] if a["id"] == "giver")
        self.assertIn("bowl", receiver["held"])
        self.assertNotIn("bowl", giver["held"])
        # give_object produced an INV-give event synchronized with 'same_time'.
        graph = studio_memory.get_gest_graph(self.project_name, self.project_id)
        self.assertTrue(any(e["relation"] == "same_time" for e in graph["edges"]))
        self.assertTrue(any(n["metadata"].get("action_id") == "inv_give" for n in graph["nodes"]))

    def test_abort_chain_discards_without_commit(self):
        builder = self._builder()
        builder.start_round("archive_hall", [{"id": "mara", "start_poi": "archive_table"}])
        builder.start_chain("mara")
        builder.add_action("stand_at")
        builder.abort_chain()
        graph = studio_memory.get_gest_graph(self.project_name, self.project_id)
        self.assertEqual(len(graph["nodes"]), 0)
        self.assertEqual(len(graph["edges"]), 0)

    def test_runner_scene_round_builds_and_rejects(self):
        runner = StudioWorkflowRunner(self.project_name)
        spec = {
            "region_id": "archive_hall",
            "actors": [{"id": "mara", "name": "Mara", "start_poi": "archive_table"}],
            "chains": [{"actor": "mara", "actions": [
                {"action": "stand_at"},
                {"action": "inspect_object"},
                {"action": "write_note"},
            ]}],
        }
        ok = runner.run_scene_round(spec)
        self.assertTrue(ok["ok"])
        self.assertEqual(ok["phase"], "scene_planning")
        self.assertEqual(len(ok["data"]["nodes"]), 3)

        # An out-of-order chain is rejected cleanly (ok=False, no exception).
        bad = runner.run_scene_round({
            "region_id": "archive_hall",
            "actors": [{"id": "mara", "start_poi": "archive_table"}],
            "chains": [{"actor": "mara", "actions": [
                {"action": "stand_at"},
                {"action": "write_note"},  # not a permitted successor of stand_at
            ]}],
        })
        self.assertFalse(bad["ok"])
        self.assertIn("write_note", bad["error"])

    def test_finalization_links_scenes_into_timeline(self):
        runner = StudioWorkflowRunner(self.project_name)
        # Two independent scenes, each tagged with its own scene_id.
        s1 = runner.run_scene_round({
            "region_id": "archive_hall",
            "actors": [{"id": "mara", "name": "Mara", "start_poi": "archive_table"}],
            "chains": [{"actor": "mara", "actions": [{"action": "stand_at"}, {"action": "inspect_object"}]}],
        })
        s2 = runner.run_scene_round({
            "region_id": "rain_market",
            "actors": [{"id": "jin", "name": "Jin", "start_poi": "tram_stop"}],
            "chains": [{"actor": "jin", "actions": [{"action": "stand_at"}, {"action": "talk"}]}],
        })
        self.assertTrue(s1["ok"] and s2["ok"])
        self.assertNotEqual(s1["data"]["scene_id"], s2["data"]["scene_id"])

        final = runner.run_finalization()
        self.assertTrue(final["ok"])
        self.assertEqual(final["data"]["scenes"], [s1["data"]["scene_id"], s2["data"]["scene_id"]])
        self.assertEqual(len(final["data"]["edges_added"]), 1)  # one cross-scene link
        self.assertTrue(final["data"]["timeline"]["valid"])

        # Every scene-1 action/event precedes every scene-2 action/event in the timeline.
        order = final["data"]["timeline"]["order"]
        nodes = studio_memory.get_gest_nodes(self.project_name, self.project_id)
        def scene_event_ids(sid):
            return [n["id"] for n in nodes
                    if n["node_type"] in ("action", "event") and (n["metadata"] or {}).get("scene_id") == sid]
        s1_last = max(order.index(i) for i in scene_event_ids(s1["data"]["scene_id"]))
        s2_first = min(order.index(i) for i in scene_event_ids(s2["data"]["scene_id"]))
        self.assertLess(s1_last, s2_first)

        # Finalization is idempotent: a second pass adds no new cross-scene edges.
        again = runner.run_finalization()
        self.assertEqual(len(again["data"]["edges_added"]), 0)

    def test_finalize_endpoint(self):
        with TestClient(server.app) as client:
            client.post("/studio/project/create", json={"project_name": self.project_name})
            client.post("/studio/workflow/scene", json={
                "project_name": self.project_name,
                "scene": {
                    "region_id": "archive_hall",
                    "actors": [{"id": "mara", "start_poi": "archive_table"}],
                    "chains": [{"actor": "mara", "actions": [{"action": "stand_at"}, {"action": "inspect_object"}]}],
                },
            })
            res = client.post("/studio/workflow/finalize", json={"project_name": self.project_name})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["phase"], "finalization")
            self.assertTrue(res.json()["data"]["timeline"]["valid"])

    def test_scene_endpoint_commits_and_rejects(self):
        with TestClient(server.app) as client:
            client.post("/studio/project/create", json={"project_name": self.project_name})

            res = client.post("/studio/workflow/scene", json={
                "project_name": self.project_name,
                "scene": {
                    "region_id": "archive_hall",
                    "actors": [{"id": "mara", "name": "Mara", "start_poi": "archive_table"}],
                    "chains": [{"actor": "mara", "actions": [
                        {"action": "stand_at"},
                        {"action": "inspect_object"},
                    ]}],
                },
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["phase"], "scene_planning")
            self.assertEqual(len(res.json()["data"]["nodes"]), 2)

            # Invalid action chain -> returns 200 with status "rejected" containing repair report.
            res = client.post("/studio/workflow/scene", json={
                "project_name": self.project_name,
                "scene": {
                    "region_id": "archive_hall",
                    "actors": [{"id": "mara", "start_poi": "archive_table"}],
                    "chains": [{"actor": "mara", "actions": [
                        {"action": "stand_at"},
                        {"action": "hide"},  # not supported by archive_table
                    ]}],
                },
            })
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
