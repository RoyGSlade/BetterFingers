# v1.1.0-alpha.1 prerelease rehearsal

Audit refreshed: 2026-08-04. The validated release-candidate baseline is
`acdad4e1d6aa4ad610ec7e8b5906980d00f2d92a`; draft PR
[#94](https://github.com/RoyGSlade/BetterFingers/pull/94) tracks subsequent
workflow and evidence-only changes before qualification.

## Rehearsal result

**HOLD / DO NOT TAG OR PUBLISH.** The release branch and draft source PR now
exist, but no tag or GitHub Release has been created. The validated candidate
has the intended version and parity `410 / 28 / 0 / 438`; GitHub platform
checks and exact Windows/Linux artifact qualification remain mandatory. The
untracked X11 directory and local AppImage describe `0.2.0-alpha.1` and remain
explicitly outside this PR and release evidence.

## Exact release inputs from the current workflow

| Input | Observed current contract |
|---|---|
| Repository | `RoyGSlade/BetterFingers` |
| Intended tag | `v1.1.0-alpha.1` (`VERSION` is `1.1.0-alpha.1`; `version.py` derives `RELEASE_TAG` by prefixing `v`) |
| Trigger | `.github/workflows/build-installer.yml` runs on `push.tags: ["v*"]` or manual dispatch |
| Validated candidate commit | `acdad4e1d6aa4ad610ec7e8b5906980d00f2d92a` (`Prepare v1.1.0-alpha.1 release candidate`) |
| Remote tag | **ABSENT**: `git ls-remote --tags origin refs/tags/v1.1.0-alpha.1` returned no line |
| Release title | Explicit: `BetterFingers ${{ github.ref_name }}`; for the intended tag this is `BetterFingers v1.1.0-alpha.1`. |
| Release body | Explicit workflow body names the draft public-alpha status, retained artifacts, unsigned/SmartScreen boundary, and qualification requirements. Generated notes are disabled. |
| Draft/prerelease flags | Explicit `draft: true`, `prerelease: true`, and `make_latest: false`. |
| Publish condition | `publish-release` runs only for a tag after Windows, Linux, and SBOM jobs, and is bound to the protected `release` environment. Manual branch dispatch cannot publish. |
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
'; draft: true; prerelease: true; make_latest: false; explicit name/body: true}
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
| X11 selected-text rewrite is qualified for this release. | **NOT PROVEN** | The excluded untracked evidence says 8/8 PASS, but records AppImage `0.2.0-alpha.1`, commit `ef1ed0ded80aede0ab97838acc138283f8378376`, and the old AppImage hash. It is not evidence for candidate `acdad4e` or version `1.1.0-alpha.1`. |
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
| Full Python/Node suites | **PASS at `acdad4e`** — Python `3177 passed / 4 skipped / 26 subtests`; renderer `1772/1772`. |
| Production Electron QA | **PASS at `acdad4e`** — fresh build and isolated data roots, `100/100`. |
| Windows build/install/upgrade/uninstall | **NOT RUN** — no Windows host or CI run was available to this worker. |

## Tag publication safety contract

The tag path is now fail-closed into a draft prerelease. A `v*` tag must finish
the Windows installer, Linux AppImage, and SBOM jobs, verify exact-one asset
sets, and wait for approval in the `release` environment before the publication
job may create `draft: true`, `prerelease: true`, `make_latest: false`. The
workflow supplies an explicit title and body and disables generated notes.
Manual dispatch on a branch retains all build artifacts but cannot enter the
publication job. No manual `gh release create` fallback is approved for this
candidate.

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
6. Merge and tag only the exact accepted commit after final CI and platform
   qualification; inspect the workflow-created draft and tag provenance before
   any human changes its draft state.
