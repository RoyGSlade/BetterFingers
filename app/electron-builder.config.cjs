'use strict';

// Keep package.json as the readable package contract, then add cloud signing
// only when CI explicitly selects it. This preserves unsigned alpha/manual
// builds while making a partially configured Azure signing run fail closed.
const packageBuild = JSON.parse(JSON.stringify(require('./package.json').build));

if (process.env.BETTERFINGERS_SIGNING_MODE === 'azure') {
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
