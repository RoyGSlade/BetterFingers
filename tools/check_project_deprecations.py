import re
import sys
from pathlib import Path


def _extract_path(line: str):
    absolute = re.search(r"([A-Za-z]:\\[^:]+\.py):\d+:\s+DeprecationWarning:", line)
    if absolute:
        return absolute.group(1)

    relative = re.search(r"((?:\./)?[A-Za-z0-9_./\\-]+\.py):\d+:\s+DeprecationWarning:", line)
    if relative:
        return relative.group(1)
    return ""


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/check_project_deprecations.py <pytest-log-path>")
        return 2

    log_path = Path(sys.argv[1]).resolve()
    if not log_path.exists():
        print(f"Log file not found: {log_path}")
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    content = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    findings = []

    for line in content:
        if "DeprecationWarning:" not in line:
            continue
        raw_path = _extract_path(line)
        if not raw_path:
            continue
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (repo_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        if repo_root == candidate or repo_root in candidate.parents:
            findings.append(line.strip())

    if findings:
        print("Project-owned deprecation warnings found:")
        for row in findings:
            print(f"- {row}")
        return 1

    print("No project-owned deprecation warnings found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
