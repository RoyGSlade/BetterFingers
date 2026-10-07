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
packageBuild.win.files = ['!node_modules/uiohook-napi/prebuilds/{darwin-*,linux-*,win32-arm64}/**/*'];

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
