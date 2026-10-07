# BetterFingers v1.1.0-alpha.4 owner release checklist

Prepared 2026-10-07 on branch `codex/i2-release-prep` (worktree
`BetterFingers-wt/i2-release-prep`), fast-forwarded to `arc/assistant` at `13c4e09`, plus
the uncommitted release-prep edits listed at the end. **Nothing has been committed,
pushed, tagged, built by CI, signed, published or deployed.** Modeled on how Alpha 3
shipped (`ALPHA3_RELEASE_HANDOFF.md`, local-only, and `.github/workflows/build-installer.yml`).

Every claim below is labeled **V** (verified by reading code or running something in the
prep session), **I** (inferred) or **U** (unknown, needs a check). Measured numbers name
their machine.

## Authority legend

| Mark | Meaning |
|---|---|
| **[OWNER]** | Needs your explicit go-ahead in that moment (commit, push, tag, start CI, approve an environment, publish, install, deploy, change repo, cloud or Azure settings). Prior approval of one step is not approval of the next. |
| **[CI]** | Runs by itself once triggered. Read the result; do not edit around it. |
| **[CHECK]** | Read-only verification. Anyone, any time. |

## 0. Pending before tag (do not tag until every row is closed)

These were still open when this checklist was written. The notes, README and website copy
deliberately do **not** claim them. The director refreshes this file when each lands.

| # | What is still open | Why it blocks the tag | What closes it | Copy to refresh when it lands |
|---|---|---|---|---|
| P1 | ~~BF-H2 local-only loads + offline bundled `base.en`~~ **CLOSED** by `e2536a1` (director, 2026-10-07): verified bundle loads local-only, corrupt bundle is `verification_failed` with no network, a real offline load/transcription had zero socket attempts. Follow-ups done in the refresh commit: release-notes headline bullet, `SUPPORTED_PLATFORMS.md` Whisper row, the workflow's draft release body, and `tools/smoke_installer.ps1` now asserts the bundled model files, their MIT notices and `GET /models/whisper` reporting base.en installed+bundled. Still open: `website/page.md` setup wording (held out of the first merge with the rest of `website/**`). | | | |
| P2 | Director refresh **done** after P1 (2026-10-07). Re-run the section 2 gates on the final tip, and delete the DRAFT block and "Commit trace" from the notes when pasting the release body. | | | |
| P3 | **Packaged zero-network probe for update checks.** `344fdc6` says it is "still owed" (**V**). The unit tests prove the controller refuses; they do not prove the installed app is silent before consent. | The notes and README say nothing contacts the update server before consent. | Section 5, item 3. | none if it passes |

**BF-F2 (Windows signing) is no longer pending in code**: `13c4e09` is on `arc/assistant`.
It does, however, change what a tag needs from you: **the owner signing setup in section
3.1 must be finished before you tag, or the tag build fails by design.**

## 1. Facts to know before you start

1.1 **Scope.** Alpha 4 = everything on `arc/assistant` since `v1.1.0-alpha.3` (71
non-merge commits including `13c4e09`; `git log --no-merges v1.1.0-alpha.3..arc/assistant`)
**except** the optional Natural Voices / TTS pack, modes, the first-run mic meter, and
end-user GPU acceleration. It includes the stabilization work captured by snapshot
`7d92006`, which was never in Alpha 3 (**V**: Alpha 3 shipped from tag `7e03d09`, the
snapshot came after).

1.2 **Branch state (V, read-only `git`).** `origin/main` is `dce880f`; local `main` is
`782c9ea`; `arc/assistant` is a descendant of both, so merging to `main` is a
fast-forward.

1.3 **Where things live.** Release notes: `docs/release/notes/1.1.0-alpha.4.md`.
`KNOWN_LIMITATIONS.md`, `RELEASE_BOARD.md` and `ALPHA3_RELEASE_HANDOFF.md` are
**gitignored internal files** (`.gitignore`, "Internal plans"): they exist only in the
main checkout. Updated copies of the first two were left in this worktree's
`docs/release/` (also ignored) for you or the director to copy over; they are not part
of any commit. This checklist is **not** ignored, so it will be committed unless you add
`/docs/release/ALPHA4_RELEASE_CHECKLIST.md` to `.gitignore` (your call; it contains no
secrets, account IDs or personal data).

1.4 **Signing (V, `13c4e09`, `.github/workflows/build-installer.yml`,
[WINDOWS_SIGNING.md](WINDOWS_SIGNING.md)).** Every tag must be signed through Azure
Artifact Signing with environment-scoped OIDC; there is no client-secret or PFX fallback
in CI. The whole `windows-installer` job runs in the GitHub environment `release-signing`
and reads three secrets (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `AZURE_SUBSCRIPTION_ID`) and
two variables (`AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE`,
`AZURE_TRUSTED_SIGNING_PUBLISHER_NAME`). A tag with none of them fails ("Every Windows tag
must be signed"); a partial set fails; a manual `workflow_dispatch` with none of them builds
unsigned. **The publisher variable must equal Alpha 3's full signer name exactly** (your
local `ALPHA3_RELEASE_HANDOFF.md`, "Signer", and `WINDOWS_SIGNING.md`, "Before the next
tag"): installed Alpha 3 pins the full name (CN, O, L, S, C), and a certificate that does
not contain every pinned key makes it reject the in-app update (users then install over the
top by hand). Alpha 4's own update metadata pins only CN, O and C, so Alpha 4 to later is
not coupled to city and state. **Unverified until you provision it (U):** the OIDC login,
the pinned `TrustedSigning 0.5.8` bootstrap, and any real signed run; `13c4e09` says so
itself. Contract tests passed in the prep session (section 8); they are not a signed run.

1.5 **Website hazard (V, `.github/workflows/website-content.yml`).** A push to `main` that
touches `website/**` dispatches a content update to the DonavenCrenshaw site when
`DONAVEN_SITE_TOKEN` is configured. The prep edits to `website/page.md` and
`website/project.json` link to the Alpha 4 release and installer, which 404 until the
release is public. **Keep `website/**` out of the commit that goes to `main` first**
(three files; commit them separately and merge after step 7.1). `website/updates.json`
carries the new Alpha 4 entry as `"state": "draft"`, the same pattern Alpha 3 used.
`README.md` links the Alpha 4 release page as well; a short 404 window between merge and
publish is harmless, but tag soon after merging, or hold README with the website commit.

1.6 **The workflow does not use the notes file.** The draft release body is boilerplate
in `build-installer.yml` (**V**). You paste the notes in yourself (step 4.5).

## 2. Pre-merge gates [CHECK]

Run from the repo root of the branch you are about to merge, Windows, using the repo
venv. Numbers from the prep session are in section 8; re-run on the final tip.

```powershell
.venv\Scripts\python.exe -m pytest -q tests/test_version_source.py tests/test_release_workflow_contract.py tests/test_azure_artifact_signing_contract.py tests/test_supply_chain_existing_verify.py
.venv\Scripts\python.exe -m pytest -q -m smoke
.venv\Scripts\python.exe -m pytest -q -n 8 --dist loadfile -m "not slow" -k "not transcriber and not tts_engine"
.venv\Scripts\python.exe -m pytest -q tests/test_parity_evidence.py tests/test_parity_evidence_binding.py tests/test_parity_evidence_rules.py tests/test_parity_inventory.py tests/test_parity_regen.py
cd app; npm run test:unit
```

The STT/TTS suites the fast loop excludes (they use fakes, no real models) are listed in
`docs/DEVELOPMENT.md`, Tests; run them as well if the tree touched speech code.

Version identity (**V**, the workflow enforces it on a tag): `VERSION`, `app/package.json`
and the tag name must all be `1.1.0-alpha.4` / `v1.1.0-alpha.4`.

The parity ledger (`docs/release/PARITY_INVENTORY.md`) was stale on `arc/assistant` when
prep started (`tests/test_parity_regen.py` failed from `4ffd1cc` on; eight lines cite
`collectionDeleteConfirmation.test.mjs`). The prep regenerated it with
`python tools/parity_ledger_build.py`; totals unchanged. If anything that the ledger
cites lands after this, regenerate again.

## 3. Owner signing setup, merge, rehearse, tag

| Step | Action | Authority |
|---|---|---|
| 3.1 | **Finish "Before the next tag" in [WINDOWS_SIGNING.md](WINDOWS_SIGNING.md)** (follow that document; it is not repeated here): the `release-signing` GitHub environment with required reviewers, the Entra federated credential for that exact repository and environment, the signer role on the `better-fingers` profile, the 3 secrets and 2 variables above, with `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME` equal to Alpha 3's full signer name, and one approved **OIDC-signed manual qualification run** on the protected ref (3.4). Only after that run succeeds, delete the old `AZURE_CLIENT_SECRET` and `WIN_CERTIFICATE_*` secrets and revoke their credentials. | **[OWNER]** (GitHub and Azure settings) |
| 3.2 | Commit the prep edits (version bump, docs, notes, this file, regenerated parity ledger) on `codex/i2-release-prep`; commit `website/**` **separately** (see 1.5). | **[OWNER]** |
| 3.3 | Open a pull request (or fast-forward) `arc/assistant` + prep into `main`, **without** the website commit. Required CI on a PR (`ci.yml`): `python-tests (ubuntu-latest / py3.12)`, `python-tests (windows-latest / py3.13)`, `node`, `electron-smoke`, `qa (production board)`, `electron-smoke-crossplatform`, `bandit (medium/high required)`, `npm audit (required)`; CodeQL; `lock-freshness` if requirements changed. `ruff` is report-only. Branch protection is **U** (not inspected). All required jobs green before merging. | push/PR/merge: **[OWNER]** |
| 3.4 | **Qualification run (strongly recommended, and required by 3.1):** run `build-installer` with `workflow_dispatch` on the merged `main`; the `windows-installer` job waits on `release-signing` approval if reviewers are set. Before the environment values exist it builds **unsigned** (allowed for manual runs only) and never publishes (the draft and publish jobs require a tag); once they exist the same dispatch is the **signed** run. It is the **first end-to-end run** of the bundled-model download path (`BETTERFINGERS_ALLOW_MODEL_DOWNLOAD=1`; `090e6e6` says it "has not run end to end yet"), of the 2500 MB payload-size budget, and of the new signing path. If the first dispatch is unsigned, run a second after provisioning. Retain the `BetterFingers-Windows-signing-evidence` artifact (signing report and installed-native verification). | start CI + approve environment: **[OWNER]** |
| 3.5 | Confirm P1 to P3 are closed (section 0), 3.1 is complete, and the DRAFT banner is gone from the notes. | **[CHECK]** |
| 3.6 | Create the **annotated** tag `v1.1.0-alpha.4` on the exact merge commit and push it. Do not upload any local build by hand. | tag + push: **[OWNER]** |

## 4. Tag workflow, then inspect the private draft

`build-installer` on the tag runs: `windows-python-tests` (8 chunks), `windows-installer`
(in `release-signing`: unit tests, smoke suite, payload prepared before Azure login, signed
build through the local wrapper, payload budget, installer smoke with an upgrade leg from
the previous release and `-ExerciseCleanupCategories`, checksum, provenance attestation),
`linux-appimage`, `sbom`, then `draft-release` (private draft, assets re-downloaded and
re-verified), then `publish-release` (waits for the `release` environment). Windows tags
fail closed if signing is missing or the signer is wrong. **[CI]** (approving
`release-signing` and `release` is **[OWNER]**.)

Inspect the draft before approving (**[CHECK]**; use the CI draft's assets, not a local
build; hashes legitimately differ per signed build):

1. Exactly one of each: `BetterFingers-Setup-1.1.0-alpha.4-x64.exe`, `.sha256`,
   `.signature.txt`, `.authenticode.json`, `.blockmap`, `alpha.yml`, `*.AppImage`,
   `*.AppImage.sha256`, `*.cdx.json`.
2. `Get-AuthenticodeSignature` = `Valid`, Microsoft timestamp present, signer subject equals
   Alpha 3's full signer name (compare against
   `(Get-AuthenticodeSignature <alpha.3 exe>).SignerCertificate.Subject`), SHA-256 matches
   the sidecar, `alpha.yml` names the exact installer and its size and SHA-512 match.
3. Installer size: record the real number. Expect it to be larger than Alpha 3's by roughly
   the bundled model; the only measured figure is the frozen backend growing by
   147,769,510 bytes (425.04 MB to 572.81 MB, on a backend build, not a signed installer).
   No installer total has been measured.
4. Installed-tree inventory (from the smoke run's install directory): the four files of
   `bundled_models/base.en` under the backend's `_internal` folder, and
   `bundled-base.en-NOTICE.txt` next to `LICENSES-MODELS.md`. `LICENSES-MODELS.md` still lists
   the signed-installer file inventory as open (**V**).
5. Set the draft body to the notes (draft only, before publication):
   `gh release edit v1.1.0-alpha.4 --notes-file docs/release/notes/1.1.0-alpha.4.md`
   after cutting the DRAFT block and the "Commit trace" section. **[OWNER]**

## 5. Local qualification on the signed installer

Use a clean Windows 11 user or VM. `tools/smoke_installer.ps1` refuses its destructive
cleanup leg if `%APPDATA%\BetterFingers` already exists; never point manual tests at real
user data. For hand tests set `BETTERFINGERS_DATA_DIR` to a throwaway folder.

```powershell
powershell -ExecutionPolicy Bypass -File tools\smoke_installer.ps1 `
  -InstallerPath <draft installer> -ExpectedVersion 1.1.0-alpha.4 `
  -ExpectedSignatureStatus Valid -ExpectedSignerSubject '<exact signer subject>' `
  -PreviousInstallerPath <public alpha.3 installer>
```

Installing, running and uninstalling are **[OWNER]** actions on your machine. Then:

1. **Upgrade over Alpha 3 (by hand).** Install the public Alpha 3, create a persona, a
   draft, a history entry and a setting, run Alpha 4's installer over it: version reads
   `1.1.0-alpha.4`, data intact, one uninstall entry. (The in-app update can only be
   tested after publication, section 7, because the updater cannot see a private draft.)
2. **F9 in a real target** (Notepad, a browser text box, a chat field): dictate in review
   mode, press F9 to place the draft; double press places once; edit the draft without
   saving, F9 refuses; overlay closed, F9 reads a selection aloud; a game or gaming
   profile gets a clipboard copy only. Not yet exercised against any real application
   (**V**, `697b259`).
3. **Update consent (P3).** Fresh profile, firewall or capture running: no update traffic
   before accepting the privacy notice; after consent, automatic check stays off until
   ticked; **Check for updates** works by hand; an upgraded Alpha 3 profile that was
   already checking keeps checking.
4. **Delete hygiene.** In a throwaway data dir, delete a persona example, a contact and a
   draft; confirm no `.bak-v*`, `.migrated` or `.corrupt` file still holds the text.
5. **Uninstall.** Default uninstall keeps data; **remove my data** also removes `.bak-v*`,
   `.corrupt`, `.<timestamp>.corrupt` and `draft_history.json.migrated` siblings and the
   data folder. A real packaged uninstall of the U4 fix has not been run (**V**, `bdf5cc2`).
6. **Report a Bug** (Utilities, Diagnostics): preview matches what is shared; confirm copies
   the report and opens the mail client or Discord invite; no network call.
7. **First read-aloud** downloads the Kokoro voice files (about 354 MB; network needed) and
   verifies them; interrupt the download once and confirm a truncated file is refetched
   (`9ae04f9`). This is an implicit download with no explicit step (planned with the
   optional voice pack after Alpha 4); the notes list it under Known limitations.
8. Clipboard with an image on it: reading a selection leaves the clipboard intact and does
   not crash (`7d92006`).

Do **not** publish if any of these fail; fix forward as `alpha.5`, never re-tag.

## 6. Publish

| Step | Action | Authority |
|---|---|---|
| 6.1 | Confirm every upstream job and `draft-release` is green. | **[CHECK]** |
| 6.2 | Approve the `release` environment in Actions. `publish-release` re-downloads and re-verifies the private draft, then sets `draft=false`, `prerelease=true`, `latest=false`. (At Alpha 3 the environment listed you as required reviewer with self-review allowed and admin bypass, so this was the manual gate, not two-person control; **V** per Alpha 3's handoff, re-check in repo settings.) | approve + publish: **[OWNER]** |
| 6.3 | Re-download the **public** assets once more: signature, SHA-256, `alpha.yml` size and SHA-512, one registered installation after install. | **[CHECK]** |

## 7. After publication

1. **In-app update from a real Alpha 3 install** (the gate Alpha 3's handoff set for the
   next release): on a machine with the public Alpha 3, accept consent, Settings, check,
   **Download update**, **Restart and install**; version becomes `1.1.0-alpha.4`, data
   intact. If the publisher check rejects it, that is the signing-name mismatch (1.4):
   record it and tell testers to install over the top. **[OWNER]** (installs software)
2. **Record the evidence** in `SUPPORTED_PLATFORMS.md` (tag commit, installer SHA-256,
   signer, workflow run URL) and in your local `RELEASE_BOARD.md` and
   `KNOWN_LIMITATIONS.md` (copies are in this worktree). Move the LHC cards for this
   release to done only with that evidence.
3. **Website promotion**, only after 6.3 and 7.1: commit the held `website/**` changes
   separately, flip the Alpha 4 entry in `website/updates.json` from `"draft"` to
   `"published"` (and, as Alpha 3 did, change its title from "prepared" to "published",
   rewrite "What is prepared" as "What is available" and drop the "Publication gate"
   paragraph), refresh `updatedAt` in `website/project.json` (the prep value is a
   placeholder date), push to `main` (this triggers the site notification if
   `DONAVEN_SITE_TOKEN` is set), then run the DonavenCrenshaw import/deploy, and confirm
   the live page no longer presents Alpha 3 as current and that both Alpha 4 links
   resolve to the public release and installer. **[OWNER]** (commit, push, deploy)
4. Keep Alpha 3 and Alpha 4 downloadable. If public verification fails, set the release
   back to draft (`gh release edit v1.1.0-alpha.4 --draft=true`) and fix forward; do not
   delete or move the tag. **[OWNER]**

## 8. Measured at prep time (not a substitute for re-running on the final tip)

Windows 11 laptop (Ryzen AI 9 HX 370, RTX 5070), main checkout's repo venv, 2026-10-07,
worktree at `13c4e09` plus the uncommitted prep edits; other agents were running tests on the
same machine, so timings are indicative only.

| Gate | Result |
|---|---|
| Fast loop (`-n 8 --dist loadfile -m "not slow" -k "not transcriber and not tts_engine"`) | 4928 passed, 17 skipped (32.7 s) |
| `pytest -m smoke` | 178 passed, 8 skipped (4892 deselected) |
| `tests/test_parity*.py` (5 files, slow regeneration included) | 34 passed (66.6 s), after regenerating the stale ledger |
| `test_version_source`, `test_release_workflow_contract`, `test_azure_artifact_signing_contract`, `test_supply_chain_existing_verify`, `test_installer_cleanup_contract` | 74 passed (of which `test_version_source.py`: 8) |
| Full Node suite (`npm run test:unit`) | 1958 tests: 1951 passed, 0 failed, 7 skipped (6 Windows/POSIX-permission skips and 1 "no repo-local .venv" skip that only applies to a worktree without its own venv) |
| `versionSource`, `packageResourceContract`, `bugReportIntegration`, `updateIpcContract` (Node) | 30 passed |

**Not run in the prep session:** the STT/TTS suites the fast loop excludes, Playwright
end-to-end, any CI workflow, any signed or unsigned installer build, any packaged-app run.
Before the ledger was regenerated, `tests/test_parity_regen.py` failed on `arc/assistant`
itself (see section 2).

## Hard stops

Do not publish if any of these is true:

- `VERSION`, `app/package.json` and `v1.1.0-alpha.4` disagree.
- Section 0 has an open row, or the notes still carry the DRAFT block.
- The `release-signing` environment is not provisioned (3.1), the tag build was not signed,
  the signer name does not match Alpha 3's full name, or the Microsoft timestamp is missing.
- The old `AZURE_CLIENT_SECRET` / `WIN_CERTIFICATE_*` secrets were deleted before one
  successful OIDC-signed run.
- Any required draft asset is missing, duplicated, or changed between qualification and
  promotion; a sidecar hash or `alpha.yml` size/SHA-512 does not match.
- The installer smoke (install, upgrade over Alpha 3, health, uninstall, cleanup matrix)
  failed, or the installed tree lacks the bundled model files and notice (once P1 lands).
- `draft-release` or `publish-release` is red. A release with uploaded assets and a failed
  workflow is a failed release.
- `website/project.json` or `website/page.md` reached `main` before the release is public.
- A website or CDN hosts a second copy of the installer. GitHub Releases stays the single
  binary host and updater feed.

## Files changed by the prep (uncommitted, in this worktree)

Version bump: `VERSION`, `app/package.json`, `app/package-lock.json`,
`tests/test_version_source.py`, `app/tests/versionSource.test.mjs`,
`app/tests/packageResourceContract.test.mjs`, `tools/smoke_installer.ps1`.
Docs: `README.md`, `SECURITY.md`, `docs/FEATURE_DESIGN.md`,
`docs/release/SUPPORTED_PLATFORMS.md`, `docs/release/PARITY_INVENTORY.md` (regenerated),
`docs/release/notes/1.1.0-alpha.4.md`, this file.
Website (hold; see 1.5): `website/page.md`, `website/project.json`, `website/updates.json`.
Ignored copies for you to move into the main checkout: `docs/release/KNOWN_LIMITATIONS.md`,
`docs/release/RELEASE_BOARD.md`.
