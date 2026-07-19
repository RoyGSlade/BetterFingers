"""Deterministic, information-only architecture report (Build Week A1.8).

Reports three things about the ``backend/**`` Python package and the
``app/src/renderer/**`` JS renderer tree, purely by static inspection (no
imports executed, no models loaded):

* composition roots — files nothing else in their own domain imports (i.e.
  in-degree 0 in the internal import graph). This is a structural signal,
  not a judgement: an unused/dead file also has in-degree 0.
* file sizes — byte size and line count for every scanned file.
* the internal import graph per domain, plus any cycles found in it.

This is a reporting tool, not a gate: it never fails a build, asserts a line
count, or asserts "no cycles". Cycles are surfaced in the report so a human
(or a separate, intentional gate) can decide what to do with them. Import
parsing reuses the same AST-walk approach as
``tests/test_architecture_smoke.py`` for Python, generalized to also resolve
relative imports and to run over ES module syntax for the renderer side, but
neither module imports the other to avoid coupling this tool's output to
that test's internals.

Usage:
    python3 tools/architecture_report.py          # human-readable text
    python3 tools/architecture_report.py --json    # machine-readable
"""

from __future__ import annotations

import ast
import json
import os
import posixpath
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DOMAINS = {
    "backend": {
        "root": os.path.join(REPO_ROOT, "backend"),
        "ext": ".py",
    },
    "renderer": {
        "root": os.path.join(REPO_ROOT, "app", "src", "renderer"),
        "ext": ".js",
    },
}


def _iter_files(root, ext):
    """Yield repo-relative paths (sorted, deterministic) for every *ext file under root."""
    found = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not filename.endswith(ext):
                continue
            full = os.path.join(dirpath, filename)
            found.append(os.path.relpath(full, REPO_ROOT).replace(os.sep, "/"))
    return sorted(found)


def _file_stats(rel_path):
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, "rb") as handle:
        data = handle.read()
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return {"bytes": len(data), "lines": lines}


def _py_module_name(rel_path):
    parts = rel_path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _py_imports(rel_path, known_modules):
    """AST-based import extraction (no exec). Mirrors test_architecture_smoke.py's approach."""
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=full)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                imported.add(node.module)
            else:
                pkg_parts = rel_path[: -len(".py")].split("/")
                if pkg_parts[-1] == "__init__":
                    pkg_parts = pkg_parts[:-1]
                base = pkg_parts[: -(node.level - 1)] if node.level > 1 else pkg_parts
                imported.add(".".join([*base, node.module]))

    hits = set()
    for name in imported:
        for known in known_modules:
            if name == known or name.startswith(known + "."):
                hits.add(known)
    return hits


_JS_IMPORT_RE = re.compile(
    r"""(?:from\s+|require\()\s*['"]([^'"]+)['"]"""
)


def _js_imports(rel_path, known_modules):
    """Regex-based ES-module/CommonJS import extraction, resolved against known files."""
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, "r", encoding="utf-8") as handle:
        text = handle.read()

    hits = set()
    file_dir = posixpath.dirname(rel_path)
    for spec in _JS_IMPORT_RE.findall(text):
        if not spec.startswith("."):
            continue  # external/node package, not part of the internal graph
        resolved = posixpath.normpath(posixpath.join(file_dir, spec))
        if resolved in known_modules:
            hits.add(resolved)
    return hits


def _build_graph(domain):
    root = DOMAINS[domain]["root"]
    ext = DOMAINS[domain]["ext"]
    files = _iter_files(root, ext)

    if domain == "backend":
        names = {_py_module_name(f): f for f in files}
        known = set(names)
        graph = {name: sorted(_py_imports(path, known) - {name}) for name, path in names.items()}
    else:
        names = {f: f for f in files}
        known = set(names)
        graph = {f: sorted(_js_imports(f, known) - {f}) for f in files}

    return names, graph


def _find_cycles(graph):
    """Return a sorted list of cycle strings, e.g. ['a -> b -> a']. Non-fatal, just data."""
    visiting, visited, stack = set(), set(), []
    cycles = []

    def visit(node):
        if node in visited:
            return
        if node in visiting:
            cycle = stack[stack.index(node):] + [node]
            cycles.append(" -> ".join(cycle))
            return
        visiting.add(node)
        stack.append(node)
        for dep in graph.get(node, ()):
            visit(dep)
        stack.pop()
        visiting.discard(node)
        visited.add(node)

    for node in sorted(graph):
        visit(node)

    return sorted(set(cycles))


def _composition_roots(graph):
    """Nodes with in-degree 0: nothing else in this domain imports them."""
    imported = set()
    for deps in graph.values():
        imported.update(deps)
    return sorted(n for n in graph if n not in imported)


def build_report():
    """Return the full deterministic report as a plain dict (JSON-serializable)."""
    report = {"domains": {}}

    for domain in sorted(DOMAINS):
        names, graph = _build_graph(domain)
        rel_paths = names if domain == "renderer" else {name: path for name, path in names.items()}

        sizes = {}
        for name, rel_path in sorted(names.items()):
            sizes[name] = {"path": rel_path, **_file_stats(rel_path)}

        report["domains"][domain] = {
            "file_count": len(names),
            "sizes": sizes,
            "import_graph": {k: graph[k] for k in sorted(graph)},
            "composition_roots": _composition_roots(graph),
            "cycles": _find_cycles(graph),
        }

    return report


def _format_text(report):
    lines = []
    for domain, data in sorted(report["domains"].items()):
        lines.append(f"== {domain} ({data['file_count']} files) ==")
        lines.append("composition roots:")
        for root in data["composition_roots"]:
            path = data["sizes"][root]["path"]
            lines.append(f"  - {root}  ({path})")
        lines.append("file sizes:")
        for name in sorted(data["sizes"]):
            info = data["sizes"][name]
            lines.append(f"  - {name}: {info['lines']} lines, {info['bytes']} bytes ({info['path']})")
        lines.append("import graph:")
        for name in sorted(data["import_graph"]):
            deps = data["import_graph"][name]
            arrow = ", ".join(deps) if deps else "(none)"
            lines.append(f"  - {name} -> {arrow}")
        if data["cycles"]:
            lines.append("cycles (reported, not failed):")
            for cycle in data["cycles"]:
                lines.append(f"  - {cycle}")
        else:
            lines.append("cycles: none")
        lines.append("")
    return "\n".join(lines)


def main(argv):
    report = build_report()
    if "--json" in argv:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
