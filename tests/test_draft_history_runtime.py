import json
import os
import tempfile
import time
import unittest

from main import App
from utils import get_draft_history_path


class DraftHistoryRuntimeTests(unittest.TestCase):
    def test_finalize_draft_archives_and_bounds_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                app = App()
                app.active_profile = "Default"
                app.draft_history_limit = 10

                for draft_id in range(1, 13):
                    draft = {
                        "id": draft_id,
                        "status": "sent",
                        "created_at": time.time(),
                        "final_text": f"final {draft_id}",
                        "raw_text": f"raw {draft_id}",
                        "stop_reason": "manual",
                        "part_index": 1,
                        "part_total": 1,
                        "token_count": 2,
                        "token_limit": 1100,
                    }
                    app.draft_queue.append(draft)
                    app.pending_manual_send_ids.append(draft_id)
                    app._finalize_draft(draft)

                self.assertEqual(app.draft_queue, [])
                self.assertEqual(app.pending_manual_send_ids, [])

                history_path = get_draft_history_path()
                self.assertTrue(os.path.exists(history_path))
                with open(history_path, "r", encoding="utf-8") as handle:
                    rows = json.load(handle)

                self.assertEqual(len(rows), 10)
                self.assertEqual([int(row["id"]) for row in rows], list(range(3, 13)))
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
