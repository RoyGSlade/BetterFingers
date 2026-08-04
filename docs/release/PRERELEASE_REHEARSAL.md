# v1.1.0-alpha.1 prerelease rehearsal

Audit timestamp: 2026-08-04 11:27:37 UTC (working tree at `69f85fde417b31bc5781b0274342e2c12986c58d`).

## Rehearsal result

**FAIL / DO NOT CREATE A DRAFT YET.** This is a non-publishing rehearsal only;
no tag, release, upload, or remote mutation was performed. The current checkout
has the intended version string, but it is not tagged, the current parity
ledger is now reconciled at `410 / 28 / 0 / 438`, the only local package is an
older `0.2.0-alpha.1` AppImage, Windows qualification is absent, and the
expected Pages URL is HTTP 404.

## Exact release inputs from the current workflow

| Input | Observed current contract |
|---|---|
| Repository | `RoyGSlade/BetterFingers` |
| Intended tag | `v1.1.0-alpha.1` (`VERSION` is `1.1.0-alpha.1`; `version.py` derives `RELEASE_TAG` by prefixing `v`) |
| Trigger | `.github/workflows/build-installer.yml` runs on `push.tags: ["v*"]` or manual dispatch |
| Current commit | `69f85fde417b31bc5781b0274342e2c12986c58d` (`Harden desktop capture and release qualification`) |
| Remote tag | **ABSENT**: `git ls-remote --tags origin refs/tags/v1.1.0-alpha.1` returned no line |
| Release title | Workflow does not set `name`; pinned `softprops/action-gh-release` metadata says the default is the tag name. Treat `v1.1.0-alpha.1` as the exact generated title unless a manual title is supplied. |
| Release body | Workflow does not set `body`, `body_path`, or `generate_release_notes`; no release notes body is supplied by the workflow. |
| Draft/prerelease flags | Workflow does not set either flag. The action metadata says both default to `false`; a tag push would therefore not be an explicit draft prerelease. |
| Publish condition | `publish-release` runs only when `startsWith(github.ref, 'refs/tags/')` and needs `windows-installer`, `linux-appimage`, and `sbom`. |
| Windows assets | Exactly one `*.exe`, matching `*.exe.sha256`, and `*.exe.signature.txt`; the workflow selects the first `.exe` and then verifies exact-one globs before upload. Filename is **PLACEHOLDER until the Windows job runs**. |
| Linux assets | Exactly one `*.AppImage` and matching `*.AppImage.sha256`; filename is **PLACEHOLDER until the Linux job runs**. |
| SBOM | Exactly one `*.cdx.json` CycloneDX file from the `betterfingers-sbom.cdx.json` artifact; final asset filename is **PLACEHOLDER until the job runs**. |
| Checksum format | Windows: lowercase SHA-256 followed by two spaces and the installer basename. Linux: `sha256sum` output naming the AppImage basename. Each is verified in its build job. |

The workflow's static asset contract was observed with this output:

```text
workflow_name= build-installer
push_tags= ['v*']
publish-release if= startsWith(github.ref, 'refs/tags/')
publish_needs= ['windows-installer', 'linux-appimage', 'sbom']
release_action_with= {'files': 'release-assets/windows/*.exe
release-assets/windows/*.exe.sha256
release-assets/windows/*.exe.signature.txt
release-assets/linux/*.AppImage
release-assets/linux/*.AppImage.sha256
release-assets/sbom/*.cdx.json
'}
verify_script_has_exact_one_checks= True True
```

## Claim audit for a future release body

Only claims in the **PASS** column below are currently observable, and several
are scoped evidence rather than release qualification. No claim should be
copied into public notes until it is re-run or reconciled at the final tagged
commit.

| Candidate claim | Result | Observable evidence / boundary |
|---|---|---|
| The source identity is `1.1.0-alpha.1` / `v1.1.0-alpha.1`. | **PASS, source only** | `VERSION`, `app/package.json`, and `app/package-lock.json` agree; Python version test passed and the two JS version/resource tests passed. This does not prove a package was built from this commit. |
| The current parity ledger is complete. | **PASS, current validator only** | `python3 tools/parity_validator.py` returned `410 wired / 28 intentional_cut / 0 blocked / 438 total` and exit 0. `RELEASE_BOARD.md` now records this as the current working-tree count while retaining `411 / 27 / 0` only as the historical Gate 11 baseline at `3d935c6`. |
| X11 selected-text rewrite is qualified for this release. | **NOT PROVEN** | `docs/release/evidence/x11-appimage-2026-08-04/` says 8/8 PASS, but records AppImage `0.2.0-alpha.1`, commit `ef1ed0ded80aede0ab97838acc138283f8378376`, and the old AppImage hash. It is not evidence for current commit `69f85fd` or version `1.1.0-alpha.1`. |
| A Linux AppImage is available for this release. | **FAIL** | Local ignored output is `app/release/BetterFingers-0.2.0-alpha.1.AppImage`, 571,977,617 bytes, SHA-256 `efbdba4c0925b110c18c8d6cdd4fd56f24390169241dab116b2c36d494f67590`; its filename and evidence identity are the prior version. |
| A Windows NSIS installer is available. | **FAIL / NOT OBSERVED** | No Windows `.exe` exists in the local checkout; no Windows CI run or install/upgrade/uninstall evidence was queried or observed. |
| Packages are clean-machine qualified, signed, and provenance-backed. | **FAIL** | Current release docs explicitly keep package qualification, signing, provenance/SBOM, clean install, and OS qualification open. The local AppImage is explicitly non-acceptance evidence. |
| A public release is available. | **FAIL** | The intended release URL returned HTTP 404; no tag or release exists. |
| A hosted showcase is available. | **FAIL** | The expected Pages URL returned HTTP 404. The current website workflow validates content and dispatches an external update; it is not a Pages deployment workflow. |
| Privacy behavior is publicly documented as a hosted page. | **NOT PRESENT** | README documents local `GET /privacy` and `POST /privacy/wipe` routes, but no public privacy URL is present. This is a local application API, not a public launch link. |

The current release-facing copy itself remains conservative: README says the
project is not yet tagged, package qualification and operator/hardware gates
remain, and source `Ctrl+Alt+R` qualification is X11-only. Keep those limits in
any future notes until current-tag evidence replaces them.

## Public launch-link audit

Checks ran on 2026-08-04 between 11:26 and 11:27 UTC with `curl` and a 20-second
timeout. Redirects were followed for the effective result.

| Link class | URL or status | HTTP result | Classification |
|---|---|---:|---|
| Repository | `https://github.com/RoyGSlade/BetterFingers` | 200, 0 redirects | **PASS / public** |
| Documentation (repository README) | `https://github.com/RoyGSlade/BetterFingers/blob/main/README.md` | 200, 0 redirects | **PASS / public** |
| Pages/showcase (expected URL in archived release plan) | `https://roygslade.github.io/BetterFingers/` | 404, 0 redirects | **FAIL / not found** |
| Intended prerelease page | `https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.1` | 404, 0 redirects | **FAIL / not found** |
| Demo | No URL present in current `README.md`, `website/project.json`, or `website/page.md`; README retains a demo TODO. | NOT RUN | **MISSING / no public link to check** |
| Privacy | README exposes local API routes only: `GET /privacy`, `POST /privacy/wipe`. | NOT RUN | **LOCAL-ONLY / no public URL** |
| Devpost | No Devpost URL or project identifier found in current public-source files. | NOT RUN | **MISSING / no public link to check** |

Observed HTTP output:

```text
URL https://github.com/RoyGSlade/BetterFingers
effective=https://github.com/RoyGSlade/BetterFingers status=200 redirects=0
URL https://github.com/RoyGSlade/BetterFingers/blob/main/README.md
effective=https://github.com/RoyGSlade/BetterFingers/blob/main/README.md status=200 redirects=0
URL https://roygslade.github.io/BetterFingers/
effective=https://roygslade.github.io/BetterFingers/ status=404 redirects=0
URL https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.1
effective=https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.1 status=404 redirects=0
```

The current `.github/workflows/` inventory contains no Pages deployment
workflow. `website/project.json` contains only the repository link; it has no
showcase, demo, privacy, release, or Devpost URL. The external
`website-content.yml` dispatch target is an API endpoint, not a public launch
page.

## Evidence and validator checklist

| Check | Result |
|---|---|
| Version source tests | **PASS** — `python3 -m pytest -q tests/test_version_source.py`: `8 passed in 0.06s`. |
| Electron version/package-resource tests | **PASS** — `node --test tests/versionSource.test.mjs tests/packageResourceContract.test.mjs`: `9 pass, 0 fail`. |
| Parity validator | **PASS** — exit 0; current output `410 / 28 / 0 / 438`, reconciled in the release board. |
| Local Markdown links in required release docs | **PASS** — read-only scan found `missing_local_links=[]` for README and all four required release docs. |
| Workflow YAML/static release assertions | **PASS** — PyYAML parsed the workflow and the exact-one asset/glob assertions returned `True`. |
| Whitespace check | **PASS** — `git diff --check` returned exit 0. |
| Full Python/Node suites | **NOT RUN** — heavyweight/shared resources and unrelated worker ownership; prior reports are scoped historical evidence only. |
| Production Electron QA | **NOT RUN** — no fresh display-backed run was required for this document. |
| Windows build/install/upgrade/uninstall | **NOT RUN** — no Windows host or CI run was available to this worker. |

## Exact safe later inputs (template only; not executed)

The existing tag workflow is not sufficient for an explicit draft prerelease:
it omits `name`, `body`, `draft`, `prerelease`, and `generate_release_notes`.
After the blockers above are closed and a director-approved commit is available,
use a manual draft API/CLI path with the placeholders below. Do not substitute
the current local AppImage or the old X11 evidence.

```bash
# TEMPLATE — NOT RUN. Replace every <PLACEHOLDER> after final CI/package review.
gh release create v1.1.0-alpha.1 \
  --repo RoyGSlade/BetterFingers \
  --target <APPROVED_CURRENT_COMMIT_SHA> \
  --title 'BetterFingers v1.1.0-alpha.1' \
  --notes-file <FINAL_RELEASE_NOTES_FILE> \
  --draft \
  --prerelease \
  <WINDOWS_EXE> <WINDOWS_EXE.sha256> <WINDOWS_EXE.signature.txt> \
  <LINUX_APPIMAGE> <LINUX_APPIMAGE.sha256> <BETTERFINGERS_SBOM.cdx.json>
```

Equivalent GitHub API request body (the `POST` itself is **NOT RUN**):

```json
{
  "tag_name": "v1.1.0-alpha.1",
  "target_commitish": "<APPROVED_CURRENT_COMMIT_SHA>",
  "name": "BetterFingers v1.1.0-alpha.1",
  "body": "<FINAL_RELEASE_NOTES_BODY_FROM_VERIFIED_CLAIMS>",
  "draft": true,
  "prerelease": true,
  "generate_release_notes": false
}
```

Before any later upload, require exactly these six asset classes from the
successful tagged workflow: one Windows `.exe` plus its `.sha256` and
`.signature.txt`, one Linux `.AppImage` plus its `.sha256`, and one CycloneDX
`.cdx.json` SBOM. Record each final filename, byte count, SHA-256, source
commit, signing status, provenance/attestation, and clean-machine qualification
in the release evidence. The public body must state **unsigned** if signing
was not configured and must not claim Windows/Linux or demo support beyond the
accepted matrix.

## Blockers to clear before rehearsal can become a real draft

1. Create or approve the final current-HEAD commit; the current `410/28/0`
   validator output is now distinguished from the historical `411/27/0`
   Gate 11 record.
2. Run the tagged workflow successfully and retain the exact Windows, Linux,
   checksum, signature-status, provenance, and SBOM outputs.
3. Perform clean-machine/package qualification on both target platforms,
   including the documented install/upgrade/uninstall and runtime checks.
4. Decide and record unsigned-alpha treatment; no signing claim is currently
   supported.
5. Publish or deliberately omit the Pages/showcase, demo, privacy, and
   Devpost links. Do not advertise the current Pages 404 or a nonexistent
   release URL.
6. If an explicit draft prerelease is required, use the manual template above
   or update the workflow with explicit metadata after director approval; do
   not rely on the current tag-push defaults to express draft/prerelease state.
