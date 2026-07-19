"""Architecture smoke gate for the ``backend`` package (Build Week A1.4).

Three checks, each deterministic and fast (no models, no network, no full
onefile PyInstaller build):

* the ``backend`` package imports cleanly in an isolated subprocess and pulls
  in none of the app's heavy runtime deps (fastapi/torch/faster_whisper/...);
* the module graph under ``backend/`` has no import cycles, computed
  generically over whatever files exist there rather than a hardcoded list;
* PyInstaller's dependency analysis actually walks into ``backend/**`` when
  something imports it, proving the packaging pipeline will bundle it once a
  real entry point (server.py) starts using it.

As of this writing ``server.py`` does not yet import ``backend`` at all
(A1.1 only landed the contract scaffold), so today's PyInstaller build of the
real backend does not bundle ``backend/**`` — that is expected, not a bug.
The third check below exercises Analysis() against a synthetic entry script
that imports the package, so the gate stays meaningful (and fast) both now
and once a later wave wires ``backend`` into ``server.py``.
"""

import ast
import os
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")

HEAVY_MODULES = (
    "fastapi",
    "starlette",
    "uvicorn",
    "torch",
    "faster_whisper",
    "ctranslate2",
    "kokoro_onnx",
    "sounddevice",
    "pygame",
    "server",
)


def _iter_backend_modules():
    """Yield (dotted_module_name, file_path) for every .py file under backend/."""
    for dirpath, _dirnames, filenames in os.walk(BACKEND_DIR):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            file_path = os.path.join(dirpath, filename)
            rel = os.path.relpath(file_path, REPO_ROOT)
            parts = rel[: -len(".py")].split(os.sep)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            yield ".".join(parts), file_path


def _module_imports(file_path, known_modules):
    """Return the subset of `known_modules` this file imports, via AST (no exec)."""
    with open(file_path, "r", encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=file_path)

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level == 0:
                imported.add(node.module)
            else:
                # Relative import: resolve against this file's own package.
                pkg_parts = os.path.relpath(file_path, REPO_ROOT)[: -len(".py")].split(os.sep)
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


def _ancestor_packages(dotted_name):
    """['a.b.c'] -> ['a', 'a.b'] (parent packages, implicitly imported by Python)."""
    parts = dotted_name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def test_backend_package_has_no_import_cycles():
    """Generic cycle detection over the backend/** module graph (grows with the package)."""
    modules = dict(_iter_backend_modules())
    assert modules, "expected at least one module under backend/"
    known = set(modules)

    graph = {name: _module_imports(path, known) - {name} for name, path in modules.items()}

    visiting, visited, stack = set(), set(), []

    def visit(node):
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join(stack[stack.index(node):] + [node])
            pytest.fail(f"circular import detected in backend/: {cycle}")
        visiting.add(node)
        stack.append(node)
        for dep in graph[node]:
            visit(dep)
        stack.pop()
        visiting.discard(node)
        visited.add(node)

    for name in graph:
        visit(name)


def test_backend_package_imports_in_isolated_subprocess():
    """`import backend.domain` must succeed standalone and stay dependency-free."""
    probe = (
        "import json, sys\n"
        "import backend.domain\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"

    import json as _json

    loaded = set(_json.loads(result.stdout))
    heavy_hits = {m for m in HEAVY_MODULES if m in loaded}
    assert not heavy_hits, f"backend.domain pulled in heavy/runtime modules: {heavy_hits}"


def test_pyinstaller_analysis_includes_backend_package_when_imported():
    """PyInstaller's Analysis pass must sweep in backend/** for any entry point that imports it.

    Uses a synthetic entry script rather than the real server.py: server.py
    pulls in the full model/audio/UI dependency stack, which would make this
    a slow, network-and-hardware-sensitive build rather than a smoke test.
    The synthetic script isolates the one thing this gate is responsible
    for — "does PyInstaller's import tracer actually find backend/** when
    something imports it" — from everything else server.py happens to need.
    """
    pytest.importorskip("PyInstaller")
    from PyInstaller.config import CONF
    from PyInstaller.building.build_main import Analysis

    entry_import = "backend.domain"

    # Expected set = whatever's actually reachable from entry_import's own
    # import graph, not every file under backend/** — sibling subpackages
    # (e.g. backend/api, a FastAPI adapter layer) are legitimately excluded
    # when nothing imports them, so asserting the whole tree would be wrong.
    modules = dict(_iter_backend_modules())
    known = set(modules)
    graph = {name: _module_imports(path, known) - {name} for name, path in modules.items()}
    expected = set()
    frontier = [entry_import, *_ancestor_packages(entry_import)]
    while frontier:
        node = frontier.pop()
        if node in expected or node not in graph:
            continue
        expected.add(node)
        frontier.extend(graph[node])

    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "entry.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(f"import {entry_import}\nprint({entry_import})\n")

        workpath = os.path.join(tmp, "build")
        os.makedirs(workpath, exist_ok=True)
        CONF["spec"] = os.path.join(tmp, "entry.spec")
        CONF["specpath"] = tmp
        CONF["specnm"] = "entry"
        CONF["workpath"] = workpath
        CONF["distpath"] = os.path.join(tmp, "dist")
        CONF["warnfile"] = os.path.join(workpath, "warn-entry.txt")
        CONF["dot-file"] = os.path.join(workpath, "graph-entry.dot")
        CONF["xref-file"] = os.path.join(workpath, "xref-entry.html")
        CONF["code_cache"] = {}
        CONF["noconfirm"] = True

        analysis = Analysis(
            [script],
            pathex=[REPO_ROOT],
            hiddenimports=[],
            hookspath=[],
            runtime_hooks=[],
            excludes=[],
            noarchive=False,
        )

    analyzed_names = {name for name, *_ in analysis.pure}
    missing = expected - analyzed_names
    assert not missing, (
        f"PyInstaller Analysis did not pick up backend modules: {missing} "
        f"(analyzed: {sorted(n for n in analyzed_names if n.startswith('backend'))})"
    )
