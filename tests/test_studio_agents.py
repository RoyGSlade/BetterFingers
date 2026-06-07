import tempfile
import unittest
from unittest.mock import patch

import studio_memory
import studio_workflow
import studio_blackboard as bb


class StudioAgentsTests(unittest.TestCase):
    def _run(self, tmp):
        # Force the LLM offline so the deterministic structured fallbacks drive the run.
        with patch.object(studio_memory, "get_user_data_path", return_value=tmp), \
             patch.object(studio_workflow, "get_engine", return_value=None), \
             patch.object(studio_workflow, "get_engine_if_initialized", return_value=None):
            runner = studio_workflow.StudioWorkflowRunner("AgentsTest")
            result = runner.run_full_pipeline("A dock crew's last job goes wrong.", mode="seed")
            # Read everything we assert on while the temp data path is still patched in.
            artifacts = bb.list_artifacts("AgentsTest", runner.project_id)
            posts = bb.get_posts("AgentsTest", runner.project_id)
            world = bb.get_artifact("AgentsTest", runner.project_id, "world")
            return runner, result, artifacts, posts, world

    def test_producer_publishes_all_artifacts_and_posts(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner, result, artifacts, posts, _world = self._run(tmp)

        self.assertTrue(result["ok"])
        self.assertEqual(runner.state, "complete")

        keys = {a["key"] for a in artifacts}
        # Every specialist published its artifact onto the blackboard.
        for expected in ("premise", "world", "characters", "treatment", "beats", "panels", "continuity"):
            self.assertIn(expected, keys)

        # Each agent posted a 'done' status, and the Producer signed off.
        done_agents = {p["agent"] for p in posts if p["status"] == "done"}
        for agent in ("intake", "world", "characters", "treatment", "planner", "panels"):
            self.assertIn(agent, done_agents)
        self.assertTrue(any(p["agent"] == "producer" and p["status"] == "complete" for p in posts))

    def test_get_artifact_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            _runner, _result, _artifacts, _posts, world = self._run(tmp)
        self.assertIsInstance(world, dict)
        # The structured world bible has the fields image prompts depend on.
        self.assertIn("palette", world)
        self.assertIn("locations", world)


if __name__ == "__main__":
    unittest.main()
