# BetterFingers production Windows signing

BetterFingers production Windows builds use the Azure Artifact Signing account
and Public Trust certificate profile named `better-fingers` at the West US 2
endpoint `https://wus2.codesigning.azure.net`.

The signing path uses the Windows SDK `SignTool.exe` with Microsoft's
`Azure.CodeSigning.Dlib.dll`. It signs with SHA-256, requests an RFC 3161
timestamp from `http://timestamp.acs.microsoft.com/`, and immediately verifies
every signature with SignTool's Windows Authenticode policy. Authentication is
provided only by the current user's existing Azure CLI login. No certificate,
password, client secret, or access token is written to the repository or a
report. The account metadata file contains identifiers only, is created in a
unique temporary directory, and is deleted even when signing fails.

## Current Windows artifact inventory

The current electron-builder target is Windows x64 NSIS. The BetterFingers
publisher signs and re-verifies these product-owned final outputs:

- `app/resources/backend/betterfingers-backend.exe`, copied into the packaged
  application as `resources/backend/betterfingers-backend.exe`;
- the packaged `BetterFingers.exe` Electron application;
- electron-builder's generated NSIS uninstaller executable;
- the final `BetterFingers-Setup-<version>-x64.exe` NSIS installer.

Electron and Chromium also ship Microsoft- or vendor-signed DLLs. The builder
preserves those upstream signatures instead of appending the BetterFingers
publisher identity. The combined report records build-time signer subjects and
separately identifies any vendor-presigned artifact encountered by the signing
hook; only the BetterFingers-owned final outputs above are required to share the
issued BetterFingers signer subject.

The project does not currently produce MSI or MSIX packages. The reusable
signer recognizes EXE, DLL, MSI, and MSIX inputs, but the release wrapper
explicitly verifies the current product-owned NSIS outputs rather than claiming
that every third-party binary in `win-unpacked` belongs to the BetterFingers
publisher.

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
renderer and PyInstaller backend, signs payload files during electron-builder
packaging, produces the NSIS installer, and performs a second recursive
verification of the final output. Success ends with `SIGNED BUILD COMPLETE` and
prints these two release paths:

- `app/release/BetterFingers-Setup-<version>-x64.exe`
- `app/release/BetterFingers-Windows-signing-report.json`

For a machine whose `app/node_modules` was installed with the exact lockfile,
use `-SkipNodeInstall`. `-SkipUnitTests` is available only for troubleshooting,
not for a release candidate. If automatic tool discovery cannot find the x64
files, pass `-SignToolPath` and `-DlibPath` explicitly. After the first successful
build records the issued certificate subject, later builds can pin it exactly
with `-ExpectedSignerSubject '<subject from the report>'`.

Do not publish merely because the package command completed. Retain the JSON
verification report, run the installed-app smoke test on the signed installer,
and compare its SHA-256 hash with the release sidecar before approving a public
release.
