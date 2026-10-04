"""Remove exact draft IDs from JSON recovery copies before final deletion."""
import json
from pathlib import Path
import re
import threading

from backend.config.store_migration import write_atomic

# Shared by DraftStore writers and archive deletions; acquire before store locks.
snapshot_lock = threading.RLock()


def remove_draft_from_snapshots(live_path, draft_id):
    path = Path(live_path)
    candidates = [path, Path(str(path) + ".migrated")]
    candidates.extend(p for p in path.parent.glob(path.name + ".bak-v*")
                      if re.fullmatch(re.escape(path.name) + r"\.bak-v[0-9]+", p.name))
    with snapshot_lock:
        updates = []
        for candidate in candidates:
            if not candidate.exists() and not candidate.is_symlink():
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise OSError("Unsafe draft recovery snapshot")
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if not isinstance(data, list) or any(not isinstance(row, dict) or "id" not in row for row in data):
                    raise ValueError("Unsupported draft snapshot")
                if ".bak-v" in candidate.name and int(candidate.name.rsplit("bak-v", 1)[1]) > 1:
                    raise ValueError("Future draft recovery schema")
            except (ValueError, UnicodeError) as exc:
                raise OSError("Unsupported draft recovery snapshot") from exc
            remaining = [row for row in data if row["id"] != draft_id]
            if len(remaining) != len(data):
                updates.append((candidate, json.dumps(remaining, indent=2, ensure_ascii=False)))
        for candidate, text in updates:
            write_atomic(candidate, text)
