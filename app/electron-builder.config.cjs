'use strict';

// Keep package.json as the readable package contract, then add signing only
// when a release path explicitly selects it. The production workstation path
// uses Azure CLI through the Artifact Signing dlib/SignTool hook.
// CI uses the same CLI hook after a protected-environment OIDC login.
const packageMetadata = require('./package.json');
const packageBuild = JSON.parse(JSON.stringify(packageMetadata.build));
const signingMode = String(process.env.BETTERFINGERS_SIGNING_MODE || '').trim();
const releaseChannel = String(packageMetadata.version).includes('-') ? 'alpha' : 'latest';

// A configured provider is required for electron-builder to generate
// app-update.yml, the channel manifest, and the matching blockmap. Every build
// command still passes --publish never; upload happens only in the gated
// release workflow after the signed assets have been verified.
packageBuild.publish = [{
  provider: 'github',
  owner: 'RoyGSlade',
  repo: 'BetterFingers',
  channel: releaseChannel,
}];
packageBuild.generateUpdatesFilesForAllChannels = false;
// Pin identity even in an unsigned qualification build: an omitted publisher
// makes electron-updater skip publisher verification. Geography can change;
// CN/O/C identify the publisher without tying upgrades to a street address.
const publisherIdentity = 'CN=Donaven Crenshaw, O=Donaven Crenshaw, C=US';
packageBuild.win.signtoolOptions = { publisherName: publisherIdentity };
// This release is x64. Non-Windows .node files are not PE signing targets.
//
// electron-builder normalizes the ROOT `files` list into a file set, but keeps a
// platform `files` list as raw patterns that become the "default" matcher. A
// default matcher holding only negations is treated as "everything except":
// `**/*` is prepended, so all of app/ (src/, tests/, a second copy of
// resources/backend, ...) lands in app.asar (684 MB, installer 3x too large).
// The Windows list must therefore repeat the root positive patterns next to the
// negation. It stays Windows-scoped because the Linux AppImage needs the
// linux-* prebuilds.
const rootFilePatterns = packageBuild.files;
if (
  !Array.isArray(rootFilePatterns) ||
  !rootFilePatterns.every((pattern) => typeof pattern === 'string') ||
  !rootFilePatterns.some((pattern) => !pattern.startsWith('!'))
) {
  throw new Error('package.json build.files must be an array of strings that includes a positive pattern; the Windows files list is derived from it.');
}
packageBuild.win.files = [
  ...rootFilePatterns,
  '!node_modules/uiohook-napi/prebuilds/{darwin-*,linux-*,win32-arm64}/**/*',
];

if (signingMode === 'azure-cli') {
  packageBuild.forceCodeSigning = true;
  // Electron ships a mixture of unsigned runtime DLLs and Microsoft/vendor-
  // signed DLLs. Include every DLL in electron-builder's pre-installer signing
  // pass; the custom hook preserves valid upstream signatures and signs only
  // unsigned or invalid files with the BetterFingers publisher.
  packageBuild.win.signExts = ['.dll', '.pyd', '.node'];
  packageBuild.win.signtoolOptions = {
    sign: require('./scripts/azure-artifact-signing.cjs'),
    signingHashAlgorithms: ['sha256'],
    publisherName: publisherIdentity,
  };
}

if (signingMode === 'azure') {
  throw new Error('Legacy Azure signing is disabled; use the verified azure-cli wrapper.');
}

module.exports = packageBuild;
