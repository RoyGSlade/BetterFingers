# BetterFingers v1.1.0-alpha.3 release handoff

## Current state

- Release lane: main
- Local HEAD: faa75ab6d11309586daa942404cc3d0d3752f2be
- origin/main: faa75ab6d11309586daa942404cc3d0d3752f2be
- Product version: 1.1.0-alpha.3
- Existing public bootstrap release: [v1.1.0-alpha.2](https://github.com/RoyGSlade/BetterFingers/releases/tag/v1.1.0-alpha.2), tag commit 21a56f9510ea8a5b0c4dd416be5ba7a1279e2687
- Separate signing lane, intentionally not merged here: handoff/windows-signing-alpha2-20260818 at d628b0c8674cc1e835a7730f9525892f8f43bdac
- All Alpha 3 product work is still uncommitted. No Alpha 3 tag, draft, or public release has been created.

Alpha 3 is the updater bootstrap. Alpha 2 users must install Alpha 3 manually over the existing installation. The first real previous-updater-version to current-version in-app update gate is Alpha 3 to a later release.

## Release-workflow blocker fixed

GitHub Actions run 32134646773 for Alpha 2 built, tested, uploaded, and created the draft assets, then failed in publish-release with:

    failed to run git: fatal: not a git repository (or any of the parent directories): .git

The release job intentionally had no checkout, but gh release download had no repository context. Alpha 3's draft-release and publish-release jobs now both set:

    env:
      GH_REPO: ${{ github.repository }}

This covers every gh release view, download, and edit invocation without adding a checkout. tests/test_release_workflow_contract.py locks the requirement; the focused contract suite passes 20/20.

Do not tag or publish from a commit that omits this fix.

## Product staging scope

Stage only the product paths below. Review the final staged diff before committing.

    .github/workflows/build-installer.yml
    VERSION
    app/electron-builder.config.cjs
    app/electron.vite.config.js
    app/package.json
    app/package-lock.json
    app/build/installer.nsh
    app/scripts/azure-artifact-signing.cjs
    app/src/main/hotkeys.js
    app/src/main/ipc.js
    app/src/main/main.js
    app/src/main/updateController.js
    app/src/main/windows.js
    app/src/preload/preload.js
    app/src/renderer/bootstrap/signalDeskApp.js
    app/src/renderer/features/firstRun.js
    app/src/renderer/features/quickSetupTour.js
    app/src/renderer/features/settingsWorkspace.js
    app/src/renderer/features/utilitiesWorkspace.js
    app/src/renderer/signal-desk.html
    app/src/renderer/styles/signal-desk.css
    app/tests/firstRun.test.mjs
    app/tests/hotkeys.test.mjs
    app/tests/navStructure.test.mjs
    app/tests/packageResourceContract.test.mjs
    app/tests/quickSetupTour.test.mjs
    app/tests/settingsWorkspace.test.mjs
    app/tests/updateController.test.mjs
    app/tests/updateIpcContract.test.mjs
    app/tests/utilitiesWorkspace.test.mjs
    app/tests/versionSource.test.mjs
    server.py
    tests/test_azure_artifact_signing_contract.py
    tests/test_installer_cleanup_contract.py
    tests/test_parity_regen.py
    tests/test_release_workflow_contract.py
    tests/test_server_settings_models.py
    tests/test_version_source.py
    tools/build_and_sign_windows.ps1
    tools/parity_evidence.py
    tools/sign_windows_artifacts.ps1
    tools/smoke_installer.ps1
    docs/release/WINDOWS_SIGNING.md
    docs/release/ALPHA3_RELEASE_HANDOFF.md
    website/project.json
    website/page.md
    website/updates.json

Partially stage .gitignore: include !app/build/installer.nsh, but keep the .codex/luna-state/ hunk with the Luna infrastructure unless that infrastructure is deliberately reviewed as a separate commit.

Explicitly exclude from the product commit:

    .codex/config.toml
    .codex/hooks.json
    .codex/agents/**
    .codex/luna-mcp/**
    AGENTS.md                 # current delta is Luna-only infrastructure guidance
    app/release/**            # generated/ignored release output
    .codex/luna-state/**      # private runtime state

Do not merge the separate signing lane just to ship this work. Its boundaries remain intentional.

## Locally qualified signed build

These files are ignored build output and reference evidence, not source to commit:

| File | Size | Evidence |
|---|---:|---|
| BetterFingers-Setup-1.1.0-alpha.3-x64.exe | 271,764,632 bytes | SHA-256 96165a4f09e3306330180c2d0662a8884889480a5f8077b46fa90fe151eeff0b |
| BetterFingers-Setup-1.1.0-alpha.3-x64.exe.blockmap | 284,744 bytes | Present and matched to the build |
| alpha.yml | 387 bytes | Names the exact installer; size and SHA-512 match |
| BetterFingers-Setup-1.1.0-alpha.3-x64.exe.sha256 | 109 bytes | Matches the installer |
| BetterFingers-Windows-signing-report.json | 7,624 bytes | Records installer, app, backend, and uninstaller verification |

Signer:

    CN=Donaven Crenshaw, O=Donaven Crenshaw, L=Kingfisher, S=ok, C=US

The installer is Authenticode Valid and carries a Microsoft RFC3161 timestamp. The local reference build passed install, launch, authenticated backend health, unauthenticated rejection, a real verified wake-model download/load, and signed uninstall. Program files and uninstall registration were removed; canonical user data remained.

The tag workflow rebuilds and re-signs. Its installer hash may legitimately differ because signatures and timestamps are not reproducible. Treat the CI draft's downloaded assets as authoritative: re-hash and re-verify them instead of requiring the local reference SHA-256.

The protected draft must contain exactly one matching instance of each required pattern:

    BetterFingers-Setup-1.1.0-alpha.3-x64.exe
    BetterFingers-Setup-1.1.0-alpha.3-x64.exe.sha256
    BetterFingers-Setup-1.1.0-alpha.3-x64.exe.signature.txt
    BetterFingers-Setup-1.1.0-alpha.3-x64.exe.authenticode.json
    BetterFingers-Setup-1.1.0-alpha.3-x64.exe.blockmap
    alpha.yml
    *.AppImage
    *.AppImage.sha256
    *.cdx.json

BetterFingers-Windows-signing-report.json is the detailed local qualification report. The CI publication contract uses the per-installer .authenticode.json report listed above.

## Verification already completed

- Full Electron/Node suite: 1851 passed, 6 skipped, 0 failed.
- Focused updater/UI Node suite: 116 passed.
- Final updater-install/recovery regression: 28/28 passed.
- Focused Python server suite: 7 passed.
- Release Python contract suite: 53 passed.
- Release workflow contract after the repository-context fix: 20/20 passed.
- Production npm audit: 0 vulnerabilities.
- Workflow YAML parses; focused diff check has no whitespace errors.
- Final independent updater review found no remaining P0/P1/P2 in the runtime, IPC, shutdown, or hotkey-recovery fixes.

The destructive uninstall category matrix was not run against this developer profile because %APPDATA%\BetterFingers already existed and the smoke script correctly refused to risk real user data. The tag workflow passes -ExerciseCleanupCategories on a clean hosted runner; that job must pass before publication. The local default-uninstall preservation path did pass.

## Coordinator-only release sequence

1. Review and stage only the product scope above. Use partial staging for .gitignore; inspect the staged diff for infrastructure or generated-file leakage.
2. Create the reviewed Alpha 3 product commit. Do not fold in the signing lane or Luna machine configuration.
3. From that exact commit, re-run the cheap local contract gates, including tests/test_release_workflow_contract.py.
4. Create and push annotated tag v1.1.0-alpha.3. Do not manually upload the local reference assets.
5. Let build-installer.yml build, sign, smoke-test, and create/update the private draft. The Windows tag leg must use configured Azure Artifact Signing and fail closed if signing is unavailable.
6. Inspect the private draft and downloaded assets. Confirm one complete asset set, Authenticode Valid, the expected signer and timestamp, matching SHA-256 sidecar, and alpha.yml exact filename/size/SHA-512.
7. Confirm every upstream job and draft-release is green. The old Alpha 2 failure mode must not recur.
8. Approve the existing release environment only after those checks. publish-release will download and reverify the private draft again before setting draft=false, prerelease=true, and latest=false.
9. Verify the public prerelease page and download the published Windows assets once more. Confirm signature, checksums, channel metadata, startup health, and one registered BetterFingers installation.
10. Only after that public verification, change the new Alpha 3 entry in website/updates.json from draft to published. Confirm website/project.json and website/page.md still point to the exact public Alpha 3 release and installer asset.
11. Commit the website promotion separately, then run the DonavenCrenshaw site import/deploy workflow. GitHub Releases remains the sole binary host and updater feed; the website only links to the verified public installer and release page.
12. Verify the live BetterFingers project page no longer advertises Alpha 2 as current or claims that automatic updates are unavailable. Follow both Alpha 3 links and confirm the installer URL resolves to the signed public asset.

The release environment currently requires reviewer RoyGSlade, but self-review is allowed and administrators can bypass it. That meets the existing manual gate, not strict two-person separation. Tighten prevent_self_review/admin bypass later if independent release approval is required.

## Hard publication stops

Do not publish if any of these is true:

- Product commit contains .codex/Luna runtime state, generated app/release output, or the unrelated AGENTS.md infrastructure delta.
- VERSION, app/package.json, and v1.1.0-alpha.3 disagree.
- Either no-checkout release job lacks GH_REPO: ${{ github.repository }} or the workflow contract fails.
- Windows tag signing is absent, invalid, has the wrong signer, or lacks the Microsoft timestamp.
- Any required draft asset is missing, duplicated, or changed between draft qualification and promotion.
- The SHA-256 sidecar fails, or alpha.yml names the wrong installer or has a mismatched size/SHA-512.
- Installer upgrade/startup/backend health, real model download, uninstall preservation, cleanup-category matrix, or single-install/uninstall-record assertions fail.
- draft-release or protected publish-release is red. A release with uploaded assets but a failed workflow is still failed.
- The Alpha 3 GitHub prerelease and its exact installer asset are not yet public and verified. Do not deploy website/project.json or website/page.md early; their Alpha 3 links would be broken.
- The new Alpha 3 website update entry is not draft before GitHub verification, or remains draft when the DonavenCrenshaw site promotion begins. Flip it to published only during the post-release website promotion.
- The imported site still contains stale Alpha 2, unsigned-installer, or no-integrated-updater copy after promotion.
- A website or CDN is configured to host a separate installer copy. GitHub Releases must remain the single public artifact source used by the updater and website.

## After Alpha 3

- Keep Alpha 2 and Alpha 3 downloadable for manual recovery.
- Before the next promotion, prove a real public Alpha 3 installation discovers, downloads, and explicitly installs the next signed alpha through Settings while preserving user data.
- Automatic rollback, percentage rollout, runtime channel switching, Linux AppImage updating, telemetry, and arbitrary portable-copy cleanup remain deferred.
- Detached Luna workers remain a tooling-only blocker on this Windows desktop: the packaged codex.exe still returns WinError 5: Access is denied when the runner attempts process creation. Native/in-process review remains usable and this does not affect BetterFingers runtime or release artifacts.
