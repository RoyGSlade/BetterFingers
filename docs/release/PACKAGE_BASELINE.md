# BetterFingers Wave 0 Package Baseline

- **Task:** `W0-D1`
- **Snapshot:** 2026-07-28T08:11:19Z
- **Checkout:** `/home/donaven/Desktop/BetterFingers`
- **Branch:** `feat/signal-desk-ui`
- **Commit:** `093eaf2a2ae3e68c2671d8549d4b583c31558080`
- **Host:** Linux `x86_64`, kernel `7.0.0-28-generic`
- **Status:** Historical Wave 0 measurements remain below. A corrected local Linux
  AppImage build exists in current worker evidence, but package acceptance is not
  complete; Windows remains **ABSENT/UNBUILT**.
- **Intended release identity:** `v1.1.0-alpha.1`; the artifact observations below
  retain their historical `v0.2.0-alpha.1` filename and identity for traceability.

The final local AppImage observed on 2026-08-04 (historical `v0.2.0-alpha.1`
identity) is
`app/release/BetterFingers-0.2.0-alpha.1.AppImage`, 571,977,617 bytes, SHA-256
`efbdba4c0925b110c18c8d6cdd4fd56f24390169241dab116b2c36d494f67590`, built with
Electron 43.2.0. Extraction showed BetterFingers identity, one backend sidecar,
four indicator assets, and no broad `assets`/`images` payload. The desktop entry
was `Exec=AppRun %U` with no unconditional `--no-sandbox`. This is local
package/runtime evidence only; authenticated health/capabilities/runtime-version
and real renderer quit/natural cleanup passed on X11. It is not clean-machine install/upgrade/uninstall,
signing, public-release, Windows, audio, hardware, reliability, or packaged
selection/model-load qualification.

This is a size and dependency baseline, not package qualification. All byte
counts below are local snapshot measurements. Generated output was changing
elsewhere in the shared checkout, so the timestamp and commands are part of
the evidence.

## 1. Size classes

The following classes must not be conflated:

| Class | Local state | Exact measurement | Release interpretation |
|---|---|---:|---|
| Git-tracked checkout | Present | 525 files; 35,761,072 bytes | Source, tests, docs, and tracked assets; not an installer size. |
| Worktree excluding `.git` | Present | 58,537 regular files; 8,502,232,442 bytes | Includes dependency environments and caches; not an installer size. |
| Repo `.venv` | Present | `du -sb`: 7,874,320,574 bytes | Local Python dependency environment; not directly copied as a package. |
| `app/node_modules` | Present | `du -sb`: 474,877,068 bytes | Node development/install tree; electron-builder selects production dependencies rather than copying this tree wholesale. |
| `.betterfingers` | Present | `du -sb`: 86,696,771 bytes | Repo-local llama runtime cache; ignored by Git and outside the package include rules. |
| `app/out` | Present | 30 files; 1,288,162 bytes | Renderer/main/preload build output; **not** a distributable artifact. |
| `app/resources/backend` | Historical snapshot placeholder | 1 file; 1 byte (`.gitkeep`) | At the 2026-07-28 snapshot the PyInstaller sidecar was **unbuilt**. |
| `app/artifacts` | Present | 6 files; 1,483,486 bytes | QA screenshots; **not** a distributable artifact. |
| `app/release` | Historical snapshot **ABSENT** | 0 artifacts; 0 bytes | At the 2026-07-28 snapshot electron-builder output had not been produced. |

The tracked production Python set is 92 files / 1,205,278 bytes. The tracked
renderer/main/preload source under `app/src` is 51 files / 1,565,506 bytes.

## 2. Largest package-relevant source files and assets

These are the largest tracked files that are production code or are captured
by the current package-resource rules:

| Bytes | Path | Classification |
|---:|---|---|
| 11,453,987 | `assets/designhelp/uioverhaul.zip` | Design archive; broad-copy risk, no production reference found. |
| 2,492,805 | `images/BetterFingersshortcut.png` | Image; broad-copy risk, no production reference found. |
| 1,441,983 | `assets/designhelp/Sevencustomizablepolyhedraldice.zip` | Design archive; broad-copy risk, no production reference found. |
| 251,745 | `images/InactiveTray.png` | Tray fallback referenced by `app/src/main/tray.js`. |
| 248,725 | `images/activetray.png` | Tray fallback referenced by `app/src/main/tray.js`. |
| 246,318 | `app/src/renderer/signal-desk-preview.html` | Director preview source; currently compiles into `app/out`. |
| 216,839 | `server.py` | Python sidecar entry point. |
| 198,931 | `app/package-lock.json` | Renderer dependency lock. |
| 167,213 | `app/src/renderer/main.js` | Legacy renderer source. |
| 138,307 | `app/src/renderer/styles/signal-desk.css` | Signal Desk stylesheet. |
| 135,064 | `app/src/renderer/index.html` | Legacy renderer document. |
| 123,061 | `llm_engine.py` | Python runtime source. |

`assets` contains 10 files / 12,944,223 bytes and `images` contains 4 files /
2,997,561 bytes: **14 files / 15,941,784 bytes combined**. The two
`assets/designhelp` archives plus four `_pre_glitchring_backup` images account
for 6 files / 12,910,039 bytes that are likely non-runtime material and need
an explicit keep-or-exclude decision.

## 3. Renderer dependency graph

Authoritative inputs are
[`app/package.json`](../../app/package.json) and
[`app/package-lock.json`](../../app/package-lock.json).

| Fact | Result |
|---|---|
| Manifest size / SHA-256 | 2,145 bytes / `f10478ebb948d474a8ba462745d9ed584a9571891629c522d5f29a62f1924199` |
| Lock size / SHA-256 | 198,931 bytes / `221f4baca1eebbca17ed52603979d363237d3fe3211e9d6992e3a34bc46b09b3` |
| Lock format | npm lockfile version 3 |
| Lock entries | 416 package paths excluding the root; 340 distinct package names |
| Integrity coverage | 416/416 entries have `resolved` and `integrity` |
| Flags | 414 dev entries; 102 optional entries; 79 OS-constrained; 77 CPU-constrained |
| Installed graph | `npm ls --all`: exit 0, 342 paths including the app root |
| Installed production graph | exit 0, 3 paths including root: `uiohook-napi` and `node-gyp-build` |

Direct resolved versions are:

| Dependency | Role | Resolved |
|---|---|---:|
| `uiohook-napi` | Runtime | 1.5.5 |
| `@playwright/test` | Development/QA | 1.61.1 |
| `electron` | Development/build | 43.1.0 |
| `electron-builder` | Development/build | 26.15.3 |
| `electron-vite` | Development/build | 5.0.0 |

The installed graph is internally healthy. There is minor lock-root metadata
drift: `package.json` now specifies exact `electron` `43.1.0` and
`electron-builder` `26.15.3`, while the lock root still records
`^43.1.0` and `^26.15.3`. Both resolve to the intended concrete versions, but
Wave 12 should regenerate the lock so the direct specifications agree.

## 4. Committed Python dependency inputs

The human-edited runtime source is
[`requirements.in`](../../requirements.in) with 22 direct constraints.
[`requirements.txt`](../../requirements.txt) is explicitly
non-authoritative. The dev source
[`requirements-dev.in`](../../requirements-dev.in) has 3 constraints:
`pytest`, `pip-tools`, and `pyinstaller`. The Linux CPU source
[`requirements-linux-cpu.in`](../../requirements-linux-cpu.in) inherits the
runtime input and pins `torch==2.13.0+cpu`.

| Committed input | Bytes | Exact pins | SHA-256 hashes |
|---|---:|---:|---:|
| `requirements.in` | 2,411 | 0 (22 ranged direct constraints) | 0 |
| `requirements.txt` | 2,753 | 0 (22 unpinned compatibility entries) | 0 |
| `requirements-dev.in` | 1,113 | 0 (3 ranged direct constraints) | 0 |
| `requirements-linux-cpu.in` | 1,399 | 1 plus inherited runtime input | 0 |
| `requirements-linux.lock` | 178,706 | 134 | 2,010 |
| `requirements-linux-cpu.lock` | 171,983 | 115 | 1,943 |
| `requirements-win.lock` | 116,754 | 81 | 1,301 |
| `requirements-dev.lock` | 4,410 | 15 | 40 |
| `requirements-dev-win.lock` | 5,179 | 18 | 46 |

The release workflow uses the Python 3.12 CPU lock for Linux and the Python
3.13 Windows lock for Windows. The non-CPU Linux lock has 18 additional
GPU-stack package names, including NVIDIA libraries and `triton`, and must not
be substituted into the AppImage build. The workflow already selects
`requirements-linux-cpu.lock`.

## 5. Python and native toolchain availability

[`app/scripts/build-backend.js`](../../app/scripts/build-backend.js) selects
`BETTERFINGERS_PYTHON` when set and otherwise selects `python3` on Linux.
At this snapshot `BETTERFINGERS_PYTHON` is unset.

| Capability | System `/usr/bin/python3` | Repo `.venv/bin/python` |
|---|---|---|
| Python | 3.12.3 | 3.12.3 |
| pip | 24.0 | 26.1.2 |
| pytest | 9.1.1 | 9.1.1 |
| pip-tools | **ABSENT** | 7.5.3 |
| PyInstaller | **ABSENT** | 6.21.0 |
| FastAPI / uvicorn | **ABSENT** | 0.139.0 / 0.51.0 |
| faster-whisper / CTranslate2 | **ABSENT** | 1.2.1 / 4.8.1 |
| kokoro / kokoro-onnx | **ABSENT** | 0.9.4 / 0.5.0 |
| `pip check` | Exit 1; two unrelated system conflicts | Exit 0 |

Consequently, a local `npm run build:backend` with the current environment
selects system Python and cannot invoke PyInstaller. Pointing
`BETTERFINGERS_PYTHON` at the repo venv supplies the tool, but that venv is not
lock-faithful: against the active Linux CPU + dev locks it has 0 missing
packages, 6 version mismatches, and 40 extra distributions. Notably,
`torch` is 2.12.1 instead of locked 2.13.0+cpu and `pytest` is 9.1.1 instead
of locked 8.4.2. Its CUDA/NVIDIA directories dominate the 7.87 GB venv, so it
is not acceptable evidence for the intended CPU-only release payload.

The Node toolchain is available (`node` 24.16.0, npm 11.16.0, local
electron-builder 26.15.3). GCC 13.3, G++ 13.3, Make 4.3, and pkg-config 1.8.1
are available. Several native X11 pkg-config modules used by the CI build
recipe were absent locally, as were system `appimagetool`, `makensis`, and
`wine`; the release workflows install or obtain their platform-specific
requirements.

## 6. Package include graph and allowlist risks

[`app/package.json`](../../app/package.json) currently configures:

```text
ASAR application files:
  out/**/*
  package.json

ASAR unpack:
  **/node_modules/uiohook-napi/**

extraResources:
  app/resources/backend/**/* except .gitkeep -> resources/backend
  four named indicator PNGs                -> resources/assets
```

Current source uses a named four-indicator Electron resource allowlist and
excludes root `assets`/`images` from the sidecar data inputs. Source-level
payload narrowing and a package-resource contract test are present. The
remaining gate is a fresh accepted build proving the extracted payload,
sidecar provenance, licenses/notices, icon, and version contract; the local
AppImage observation above does not by itself close that gate.

The narrow `out/**/*` application-files rule does keep QA screenshots,
Playwright reports, development logs, dependency caches, and old installers
out of the ASAR. No old installer is present in this checkout.

## 7. Artifact ledger

### Windows x64 (unchanged from the Wave 0 snapshot)

| Target | Required artifact | State | Count | Exact bytes |
|---|---|---|---:|---:|
| Windows x64 | NSIS `.exe` | **ABSENT/UNBUILT** | 0 | 0 |

### Linux x64 — PACKAGE RESULT PENDING ACCEPTED REBUILD/OPERATOR

The Wave 0 snapshot recorded Linux at **ABSENT/UNBUILT, 0 artifacts / 0
bytes**. A local AppImage has since been observed (metadata is recorded at the
top of this document), but release artifact acceptance, provenance, and
operator qualification remain open. Keep the exact local measurements visible
without treating them as a release sign-off:

| Field | Value |
|---|---|
| AppImage path | `app/release/BetterFingers-0.2.0-alpha.1.AppImage` |
| Byte size | `571977617` (local observation; not acceptance) |
| SHA-256 | `efbdba4c0925b110c18c8d6cdd4fd56f24390169241dab116b2c36d494f67590` (local observation; not acceptance) |
| Build date (UTC) | `2026-08-04` (local observation; exact timestamp not recorded here) |
| Electron | `43.2.0` (local observation) |

**Do not treat this table as package acceptance.** The local build and runtime
checks are evidence that an artifact exists and launches on this host. They do
not establish clean-machine install/upgrade/uninstall, signing, Windows,
audio, hardware, reliability, or packaged selection/model-load qualification.

The local AppImage is present in ignored build output, but it is not accepted
release evidence. No accepted Windows artifact, clean-machine
install/upgrade/uninstall evidence, signing evidence, final package
provenance/SBOM, or accepted packaged selection hash is recorded here.

## 8. Gate conclusions

### Gate 0 package-baseline conclusion

`W0-D1` has reproducible historical source/build/cache measurements and an
updated local artifact ledger. Package qualification is **NOT PASSED**:
local Linux build/health/runtime evidence is not package acceptance. Windows,
clean-machine install, signing, audio/hardware, reliability, and packaged
selection/model-load gates remain open.

### Wave 12 blockers exposed by this baseline

- Build both Windows and Linux artifacts from one release tag and record exact
  installer, unpacked-payload, and sidecar sizes.
- Reconcile release identity before building: current identity is now
  `v1.1.0-alpha.1` / `com.betterfingers.desktop`; regenerate lock-faithful
  package provenance before release. A generated sidecar has existed in local
  build output, but final sidecar/payload provenance remains unqualified.
- Create a clean, lock-faithful per-platform Python build environment; do not
  rely on the current system interpreter or drifted CUDA-heavy repo venv.
- Build and smoke-test the PyInstaller sidecar from the intended lock-faithful
  environment; local sidecar health does not establish release provenance.
- Close the resource allowlist, preview-page, duplicate-resource, license, and
  missing-icon gaps above, then inspect the actual packaged file list.
- Add the package-content and version-consistency CI gates required by the
  release directive.
- Produce and verify checksums, provenance, SBOM, signing status, clean
  install/upgrade/uninstall evidence, AppImage clean-launch evidence, and the
  required Windows/Linux hardware matrix. These remain **OPEN**; the local
  AppImage hash and runtime smoke do not satisfy them.

## 9. Reproduction commands

Run from the repository root. These commands are read-only.

```bash
git branch --show-current
git rev-parse HEAD
git status --short

git ls-files -z | xargs -0 stat --printf='%s\n' |
  awk '{s+=$1;n++} END {printf "%d files, %.0f bytes\n", n, s}'
find . -path './.git' -prune -o -type f -printf '%s\n' |
  awk '{s+=$1;n++} END {printf "%d files, %.0f bytes\n", n, s}'

for p in .venv app/node_modules .betterfingers; do du -sb "$p"; done
for p in app/out app/resources/backend app/artifacts assets images; do
  printf '%s\t' "$p"
  find "$p" -type f -printf '%s\n' |
    awk '{s+=$1;n++} END {printf "%d files, %.0f bytes\n", n, s}'
done

find assets images -type f -printf '%s\t%p\n' | sort -nr
find app/out -type f -printf '%s\t%p\n' | sort -nr

cd app
npm ls --all --parseable
npm ls --all --omit=dev --parseable
cd ..

for f in requirements*.in requirements.txt requirements*.lock; do
  stat --printf='%n\t%s bytes\n' "$f"
  sha256sum "$f"
done

/usr/bin/python3 --version
/usr/bin/python3 -m pip --version
/usr/bin/python3 -m pytest --version
/usr/bin/python3 -m PyInstaller --version
.venv/bin/python --version
.venv/bin/python -m pip check
.venv/bin/pip-compile --version
.venv/bin/pyinstaller --version

if test -d app/release; then
  find app/release -maxdepth 1 -type f \
    \( -iname '*.AppImage' -o -iname '*.exe' -o -iname '*.msi' \) \
    -printf '%p\t%s bytes\n'
else
  echo 'app/release ABSENT; artifact count 0; artifact bytes 0'
fi
```
