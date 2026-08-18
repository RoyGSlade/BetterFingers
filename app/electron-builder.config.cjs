'use strict';

// Keep package.json as the readable package contract, then add signing only
// when a release path explicitly selects it. The production workstation path
// uses Azure CLI through the Artifact Signing dlib/SignTool hook. The legacy
// service-principal mode remains available to CI until its release workflow is
// migrated, but neither mode stores credentials in this configuration.
const packageBuild = JSON.parse(JSON.stringify(require('./package.json').build));
const signingMode = String(process.env.BETTERFINGERS_SIGNING_MODE || '').trim();

if (signingMode === 'azure-cli') {
  const expectedSignerSubject = String(
    process.env.BETTERFINGERS_EXPECTED_SIGNER_SUBJECT || '',
  ).trim();

  packageBuild.forceCodeSigning = true;
  packageBuild.win.signExts = ['.exe', '.dll', '.msi', '.msix'];
  packageBuild.win.signtoolOptions = {
    sign: require('./scripts/azure-artifact-signing.cjs'),
    signingHashAlgorithms: ['sha256'],
    ...(expectedSignerSubject ? { publisherName: expectedSignerSubject } : {}),
  };
}

if (signingMode === 'azure') {
  const certificateProfileName = String(
    process.env.AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE || '',
  ).trim();
  const publisherName = String(
    process.env.AZURE_TRUSTED_SIGNING_PUBLISHER_NAME || '',
  ).trim();
  if (!certificateProfileName || !publisherName) {
    throw new Error(
      'Azure signing requires AZURE_TRUSTED_SIGNING_CERTIFICATE_PROFILE and '
      + 'AZURE_TRUSTED_SIGNING_PUBLISHER_NAME (the exact issued certificate subject).',
    );
  }

  packageBuild.win.azureSignOptions = {
    endpoint: 'https://wus2.codesigning.azure.net/',
    codeSigningAccountName: 'better-fingers',
    certificateProfileName,
    publisherName,
    fileDigest: 'SHA256',
    timestampDigest: 'SHA256',
    timestampRfc3161: 'http://timestamp.acs.microsoft.com',
  };
}

module.exports = packageBuild;
