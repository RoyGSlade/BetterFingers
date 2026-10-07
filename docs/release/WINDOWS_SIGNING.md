# BetterFingers production Windows signing

## Before the next tag

The owner must complete this checklist before signed CI qualification. A tag
fails closed until all five environment values below exist; an environment
name alone does not protect signing.

- [ ] In `RoyGSlade/BetterFingers` **Settings → Environments**, create
  `release-signing`. Set required reviewers, prevent self-review and administrator
  bypass where supported, and restrict deployment refs to approved release tags
  plus the chosen protected branch for manual qualification. Verify that the
  repository's plan/visibility supports these protections before signing.
- [ ] In Microsoft Entra, select or create the CI application/service principal
  or user-assigned managed identity. Under **Federated credentials**, add issuer
  `https://token.actions.githubusercontent.com`, audience
  `api://AzureADTokenExchange`, and the exact repository/environment subject.
  For classic claims this is
  `repo:RoyGSlade/BetterFingers:environment:release-signing`; verify the actual
  repository OIDC settings first because immutable/custom claims use a different
  subject. Do not substitute a branch-wide wildcard.
- [ ] In Azure Artifact Signing access controls, grant that principal
  **Artifact Signing Certificate Profile Signer** scoped to the
  `better-fingers` certificate profile, with active Public Trust identity
  validation in the West US 2 account consumed by the wrapper.
- [ ] Under **release-signing**, create exactly these five values (the workflow
  reads nothing else; CI consumes no client secret or PFX fallback):
  - **Environment secrets:** `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
    `AZURE_SUBSCRIPTION_ID`.
  - **Environment variables:** `AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE` =
    `better-fingers`, and `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME` = the exact full
    subject of the certificate Azure issues (see the next item for what it must
    be for the first release after Alpha 3).
- [ ] Preserve Alpha 3 upgrade continuity. The installed Alpha 3 updater pins the
  full subject `CN=Donaven Crenshaw, O=Donaven Crenshaw, L=Kingfisher, S=ok, C=US`
  (every pinned key must match), and the new CN/O/C pin cannot loosen that
  installed check. So for the first release after Alpha 3, set
  `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME` to exactly that string: the signing
  wrapper and the workflow then fail the build if Azure issues a certificate
  with any other subject, instead of shipping an update Alpha 3 would reject.
  Change it only for a reviewed identity change with a bridge release (see
  *Updater identity and upgrade continuity*).
- [ ] Review the pinned `azure/login` action and `TrustedSigning 0.5.8` toolchain,
  then explicitly approve an OIDC-signed manual qualification run on the
  protected ref. Retain its signing reports and successful installed-app/native
  verification before approving a tag. This patch runs no external operation.
- [ ] **Only after one successful OIDC-signed run**, delete obsolete
  `AZURE_CLIENT_SECRET` and `WIN_CERTIFICATE_*` secrets from their old repository,
  organization or environment locations; revoke the corresponding Entra client
  secret and retire old PFX credentials. Leave their storage alone until the
  transition succeeds. The new workflow never falls back to them.

Setup references: [GitHub environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments),
[OIDC subject claims](https://docs.github.com/en/actions/reference/security/oidc),
[Azure federation](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure-openid-connect)
and [certificate-profile roles](https://learn.microsoft.com/en-us/azure/artifact-signing/tutorial-assign-roles).

BetterFingers production Windows builds use the Azure Artifact Signing account
and Public Trust certificate profile named `better-fingers` at the West US 2
endpoint `https://wus2.codesigning.azure.net`.

The signing path uses the Windows SDK `SignTool.exe` with Microsoft's
`Azure.CodeSigning.Dlib.dll`. It signs with SHA-256, requests an RFC 3161
timestamp from `http://timestamp.acs.microsoft.com/`, and immediately verifies
every signature with SignTool's Windows Authenticode policy. Authentication is
provided by the current user's Azure CLI login locally, or by an environment-
scoped OIDC Azure CLI session in CI. No certificate,
password, client secret, or access token is written to the repository or a
report. The account metadata file contains identifiers only, is created in a
unique temporary directory, and is deleted even when signing fails.

## Current Windows artifact inventory

The current electron-builder target is Windows x64 NSIS. The BetterFingers
publisher signs and re-verifies these product-owned final outputs:

- the PyInstaller onedir entry point at
  `app/resources/backend/betterfingers-backend/betterfingers-backend.exe`,
  copied into the packaged application at the same path beneath
  `resources/backend/`;
- the packaged `BetterFingers.exe` Electron application;
- electron-builder's generated NSIS uninstaller executable (required signed,
  timestamped build-hook evidence; independently rechecked after installation);
- the final `BetterFingers-Setup-<version>-x64.exe` NSIS installer.

PyInstaller onedir keeps native dependencies visible instead of extracting
unsigned modules into `%TEMP%\_MEI*` at launch. Before electron-builder runs,
the release wrapper recursively inventories every `.exe`, `.dll`, `.pyd`, and `.node`
in the backend bundle. Unsigned or invalid files are signed with the
BetterFingers profile; already-valid Microsoft or vendor signatures are
preserved. During electron-builder packaging, DLLs, PYDs and Windows `.node`
modules are included in the pre-installer signing pass.
Windows x64 packaging excludes non-Windows and ARM64 uiohook prebuilds through
Windows-only file filters; Linux packaging retains its native modules.
The custom hook preserves every already-valid
upstream signature and signs unsigned or invalid Electron runtime DLLs with the
BetterFingers profile before NSIS assembles the installer. The preverified
backend payload is preserved by the same rule rather than re-signed.

After packaging, the wrapper verifies every `.exe`, `.dll`, `.pyd`, and `.node` under
`win-unpacked`, then compares the backend bundle to its pre-package report by
relative path, SHA-256, signer subject/thumbprint, and timestamp
subject/thumbprint. A missing, added, changed, or re-signed backend file aborts
the build. The combined report records the mixed signer set and separately
identifies valid vendor-presigned artifacts; only BetterFingers-owned entry
points are required to share the issued BetterFingers signer subject.

The project does not currently produce MSI or MSIX packages. The reusable
signer recognizes EXE, DLL, PYD, NODE, MSI, and MSIX inputs. The release wrapper
requires every native file in `win-unpacked` to have a valid signature without
pretending that third-party binaries belong to the BetterFingers publisher.

## Signing-machine prerequisites

Use Windows 11 x64 with Node.js 24, Python 3.13, Azure CLI, and the repository's
locked dependencies. Install Microsoft's client bundle once from an elevated
terminal:

```powershell
winget install -e --id Microsoft.Azure.ArtifactSigningClientTools
```

The bundle supplies the compatible Artifact Signing dlib and prerequisites.
The script requires Windows SDK SignTool version `10.0.2261.755` or newer. The
Azure identity must have the `Artifact Signing Certificate Profile Signer` role
for the `better-fingers` profile.

Prepare the repo-local release environment if it is not already present:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-win.lock
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-dev-win.lock
az login
az account show
```

## Repeatable build-and-sign command

From the repository root on the signing machine:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build_and_sign_windows.ps1
```

The command installs the locked npm tree, runs the app unit tests, builds the
renderer and PyInstaller onedir backend, signs or preserves every native
backend payload before electron-builder packaging, then signs or preserves
Electron runtime DLLs before producing the NSIS installer. The final recursive
pass verifies the complete unpacked native tree without changing it and proves
that the backend payload did not change during packaging. Success ends with
`SIGNED BUILD COMPLETE` and prints these two release paths:

- `app/release/BetterFingers-Setup-<version>-x64.exe`
- `app/release/BetterFingers-Windows-signing-report.json`

The backend build inside this command refuses to run without a bundled
speech-model source. Before running it, set `BETTERFINGERS_ALLOW_MODEL_DOWNLOAD=1`
(pinned, hash-verified fetch) or `BETTERFINGERS_BUNDLED_MODEL_SOURCE=<snapshot dir>`
in the same shell; the wrapper inherits them. See *Building* in
[docs/DEVELOPMENT.md](../DEVELOPMENT.md). CI sets the download switch on its
pre-login payload-preparation step, because that step, not the wrapper, compiles
the backend there.

For a machine whose `app/node_modules` was installed with the exact lockfile,
use `-SkipNodeInstall`. `-SkipUnitTests` is available only for troubleshooting,
not for a release candidate. If automatic tool discovery cannot find the x64
files, pass `-SignToolPath` and `-DlibPath` explicitly. After the first successful
build, verify the current issued certificate subject. The wrapper defaults to
the previously verified full subject
`CN=Donaven Crenshaw, O=Donaven Crenshaw, L=Kingfisher, S=ok, C=US` and requires
it exactly on product-owned outputs. An empty expected subject is rejected;
use `-ExpectedSignerSubject '<verified current subject>'` for a reviewed change.

## Updater identity and upgrade continuity

Every configuration, including unsigned qualification builds, explicitly pins
`CN=Donaven Crenshaw, O=Donaven Crenshaw, C=US` in
`win.signtoolOptions.publisherName`. Electron-builder carries this as an array
in `resources/app-update.yml`; the signed wrapper refuses an absent or different
pin. CN/O/C are retained identity attributes; L/S are omitted because an address
change should not unnecessarily break future updates. Exact full-subject
verification during signing remains separate and stricter.

The currently installed public Alpha 3 pin includes L/S. Its next update must
still be signed with that full existing identity; narrowing the new build's
pin cannot bypass the old installed pin. Before any publisher identity change,
qualify a bridge release under the old identity. Do not rotate to a new CN/O/C
or change the old full subject before proving the upgrade path on a disposable
Windows machine. The pin is a publisher identity check, not a certificate-leaf
thumbprint pin; short-lived signing certificates rotate.

## Local developer builds: what changed

`npm run dist:win` still builds the renderer and backend, then runs the Windows
x64 NSIS target with `--publish never`. With `BETTERFINGERS_SIGNING_MODE` unset or
`unsigned`, these are the differences from the previous configuration:

- Generated `resources/app-update.yml` now contains the CN/O/C publisher pin.
  The app can run unsigned, but its updater rejects an unsigned incoming
  installer instead of skipping publisher verification. A correctly signed
  update matching the pin remains eligible for the normal update checks.
- Windows packaging excludes uiohook's Darwin, Linux and Windows ARM64 prebuilds;
  the Windows x64 native module is retained. The filter does not change Linux
  packaging.
- An inherited `BETTERFINGERS_SIGNING_MODE=azure` now aborts with the legacy-mode
  error rather than using electron-builder's separate Azure path. Use the
  reviewed `azure-cli` wrapper for signed releases.

Unset/`unsigned` still adds no custom signing hook and does not force signing.
It does **not** disable electron-builder's existing certificate discovery:
inherited `WIN_CSC_LINK`/`CSC_LINK` or available signing certificates may still
enable built-in signing. For a deliberately unsigned qualification build, use
a credential-free process/runner and verify the resulting signatures. The
publisher pin does not sign any binary or authorize publication. This command
still does not run the signed wrapper's recursive native verification. Script
names, output directory, NSIS target and build/publish order remain unchanged.

Signed local builds (`npm run dist:win:signed` or the wrapper) also changed:

- The wrapper's `-ExpectedSignerSubject` now defaults to the full Alpha 3 subject
  and an empty value is rejected; before, it defaulted to empty, which accepted
  whatever subject was observed.
- Running `BETTERFINGERS_SIGNING_MODE=azure-cli` directly, without the wrapper,
  now fails in the signing hook unless `BETTERFINGERS_EXPECTED_SIGNER_SUBJECT` is
  set. Use the wrapper, which sets it.
- `.node` modules are signed and verified like `.dll`/`.pyd`, a signed and
  timestamped hook record for the NSIS uninstaller is required, and the packaged
  `app-update.yml` must contain the exact publisher pin.

## Protected CI signing (owner setup required before the next tag)

The Windows installer job declares `environment: release-signing` and uses the
same `tools/build_and_sign_windows.ps1` authority as the laptop. Legacy built-in
electron-builder Azure signing is disabled, removing its unpinned module
installation and distinct payload coverage. PFX fallback is removed from CI.
All dependency installation, tests, renderer compilation, backend compilation,
and signing-tool acquisition run before Azure login. Packaging still executes
reviewed repository/dependency code inside the short-lived signing session;
OIDC does not make malicious build code safe. The session is logged out in an
`always()` step before installer smoke and upload.

`id-token: write` applies to the whole installer job. Pre-login dependency/build
steps, and steps after logout, can still request GitHub OIDC tokens. Ordering
limits exposure of the cached Azure CLI session; it is not an OIDC isolation
boundary. Trust and review all code/dependencies in this protected job. Stronger
isolation needs separate credential-free build and protected signing jobs;
this patch does not implement that separation. See
[GitHub OIDC permissions](https://docs.github.com/en/actions/reference/security/oidc#workflow-permissions-for-the-requesting-the-oidc-token).

The environment is declared on the whole `windows-installer` job, so every run of
it waits for the environment's approval and obeys its deployment-ref rules,
including a manual run that would only build unsigned. A tag or branch that the
environment does not allow cannot run the Windows installer job at all.

Configure these external controls; this patch neither creates nor verifies them:

1. Create `release-signing` with required reviewers, prevention of self-review
   where supported, and deployment ref rules limited to approved release tags
   and the chosen protected branch for manual qualification. Without those
   controls, an environment name alone supplies no approval protection.
2. Store `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, and `AZURE_SUBSCRIPTION_ID` as
   environment secrets. Store `AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE`
   (`better-fingers`) and `AZURE_TRUSTED_SIGNING_PUBLISHER_NAME` (the exact full
   issued subject) as environment variables. Only after a successful OIDC-signed
   qualification run, delete/revoke obsolete client-secret/PFX credentials as
   specified in the checklist above; this workflow never uses that fallback.
3. Configure Entra federation with issuer `https://token.actions.githubusercontent.com`,
   audience `api://AzureADTokenExchange`, and exact subject
   `repo:RoyGSlade/BetterFingers:environment:release-signing` for classic claims.
   Verify the actual subject first if immutable/custom claims are configured.
   Grant only the Certificate Profile Signer role on the required profile.
4. The workflow uses SHA-pinned `azure/login` v3.0.2 and installs
   `TrustedSigning -RequiredVersion 0.5.8`. Its dependency bootstrap pins Windows
   SDK BuildTools 10.0.26100.4188 and Microsoft.Trusted.Signing.Client 1.0.95;
   those explicit SignTool/dlib paths are passed to the wrapper. The module's
   signing command is not used. Version pinning does not constitute an audit of
   downloaded package bytes; review toolchain updates separately.
5. `-UsePreparedPayload` is CI-only reuse after the same checkout's tests and
   builds pass; it skips dependency/test/compilation work, not signature gates.
   Missing OIDC configuration aborts tag builds before signing. A fully absent
   configuration permits an explicitly unsigned manual qualification run;
   partial configuration always fails. Signed CI records hook, backend,
   packaged-native and final-output verification, including `.node`, with zero
   unsigned eligible Windows payloads allowed. Install smoke rechecks native
   files and the installed uninstaller on the disposable hosted runner.

Sources: [Azure OIDC setup](https://learn.microsoft.com/en-us/azure/developer/github/connect-from-azure),
[Azure Login](https://github.com/Azure/login), and
[pinned toolchain bootstrap](https://www.powershellgallery.com/packages/TrustedSigning/0.5.8/Content/NugetInstall%5CNugetInstall.psm1).

F2 validation is local contract/config evaluation only. No signing service,
GitHub workflow, installer build, or installed upgrade was exercised. Qualify
the exact signed artifact and environment controls before tagging.

Follow-up scope includes `app/tests/packageResourceContract.test.mjs`.
Its signing assertions cover the fixed publisher pin, DLL/PYD/NODE signing,
absence of a custom unsigned hook/forced signing, and rejection of legacy Azure
mode. Local contract success does not establish external environment/federation
or signed-artifact qualification; those remain separate release gates.

Receipt (2026-10-07, after rebasing onto `arc/assistant`): the signing,
release-workflow and supply-chain Python contract tests, the packaging/sidecar/
updater Node tests and the full Node unit suite passed, with the workflow's
bundled-model switch pinned for both the unsigned `dist:win` step and the signed
path's pre-login payload step. The three PowerShell scripts and every PowerShell
block in the workflow parsed. `sign_windows_artifacts.ps1 -VerifyOnly` (no Azure
call, no signing) recognised a real `.node` module as eligible and failed closed
on it for having no signature, and rejected a non-native file; the wrapper
rejected an empty expected subject before reaching any Azure CLI check. Reading
the electron-builder 26.15.3 and electron-updater 6.8.9 sources confirmed that
the pin is written to `app-update.yml` for unsigned builds and that the updater
matches a pinned DN key by key. No real build, signing, workflow run, installed upgrade,
environment provisioning or credential retirement was performed.

Do not publish merely because the package command completed. Retain the JSON
verification report, run the installed-app smoke test on the signed installer,
and compare its SHA-256 hash with the release sidecar before approving a public
release. The smoke test recursively verifies the complete installed native
tree and writes `<installer>.installed-native-verification.json`, then launches
the installed app and requires authenticated `/health` success. Enterprise
WDAC compatibility is release-qualified only after that installed smoke passes
under the actual target WDAC policy; a clean static or unsigned build is not
that proof.
