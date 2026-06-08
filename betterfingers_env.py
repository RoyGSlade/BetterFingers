"""Small local env-file loader for machine-specific secrets.

The app intentionally avoids requiring python-dotenv. This only loads simple
KEY=value lines from ignored local files and never overwrites existing env vars.
"""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_ENV_FILES = (".env.local", ".env")


def load_local_env(root: str | os.PathLike | None = None, filenames=DEFAULT_ENV_FILES) -> dict[str, str]:
    base = Path(root) if root else Path(__file__).resolve().parent
    loaded: dict[str, str] = {}
    for name in filenames:
        path = base / name
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if not key or key in os.environ:
                continue
            os.environ[key] = value
            loaded[key] = value
    return loaded
