'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const signingScript = path.resolve(__dirname, '..', '..', 'tools', 'sign_windows_artifacts.ps1');
let reportSequence = 0;

function appendValue(args, switchName, value) {
  const normalized = String(value || '').trim();
  if (normalized) {
    args.push(switchName, normalized);
  }
}

module.exports = async function azureArtifactSigning(configuration) {
  if (process.platform !== 'win32') {
    throw new Error('Azure Artifact Signing must run on Windows.');
  }
  if (String(configuration.hash).toLowerCase() !== 'sha256') {
    throw new Error(`BetterFingers permits only SHA-256 signing, not ${configuration.hash}.`);
  }
  if (!fs.existsSync(signingScript)) {
    throw new Error(`BetterFingers signing script is missing: ${signingScript}`);
  }

  const args = [
    '-NoProfile',
    '-NonInteractive',
    '-ExecutionPolicy',
    'Bypass',
    '-File',
    signingScript,
    '-Path',
    configuration.path,
  ];

  appendValue(args, '-SignToolPath', process.env.BETTERFINGERS_SIGNTOOL_PATH);
  appendValue(args, '-DlibPath', process.env.BETTERFINGERS_ARTIFACT_SIGNING_DLIB_PATH);
  appendValue(args, '-ExpectedSignerSubject', process.env.BETTERFINGERS_EXPECTED_SIGNER_SUBJECT);

  const buildCorrelation = String(process.env.BETTERFINGERS_SIGNING_CORRELATION_ID || '').trim();
  if (buildCorrelation) {
    appendValue(args, '-CorrelationId', `${buildCorrelation}/${path.basename(configuration.path)}`);
  }
  if (process.env.BETTERFINGERS_SKIP_AZURE_CLI_PREFLIGHT === '1') {
    args.push('-SkipAzureCliPreflight');
  }

  const reportDirectory = String(process.env.BETTERFINGERS_SIGNING_HOOK_REPORT_DIR || '').trim();
  if (reportDirectory) {
    fs.mkdirSync(reportDirectory, { recursive: true });
    reportSequence += 1;
    const safeName = path.basename(configuration.path).replace(/[^a-zA-Z0-9._-]/g, '_');
    const pathId = crypto.createHash('sha256')
      .update(path.resolve(configuration.path))
      .digest('hex')
      .slice(0, 16);
    appendValue(
      args,
      '-ReportPath',
      path.join(reportDirectory, `${String(reportSequence).padStart(3, '0')}-${safeName}-${pathId}.json`),
    );
  }

  const result = spawnSync('powershell.exe', args, {
    cwd: path.resolve(__dirname, '..', '..'),
    env: process.env,
    stdio: 'inherit',
    windowsHide: false,
  });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(
      `Azure Artifact Signing failed for ${configuration.path} with exit code ${result.status}.`,
    );
  }
};
