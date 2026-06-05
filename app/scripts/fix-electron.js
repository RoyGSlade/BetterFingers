const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { downloadArtifact } = require('@electron/get');

const appRoot = path.resolve(__dirname, '..');
const electronRoot = path.join(appRoot, 'node_modules', 'electron');
const electronPackagePath = path.join(electronRoot, 'package.json');
const electronDist = path.join(electronRoot, 'dist');
const electronPathFile = path.join(electronRoot, 'path.txt');

function platformExecutableName() {
  if (process.platform === 'win32') {
    return 'electron.exe';
  }

  if (process.platform === 'darwin') {
    return path.join('Electron.app', 'Contents', 'MacOS', 'Electron');
  }

  return 'electron';
}

function isElectronInstalled() {
  const executableName = platformExecutableName();
  const executablePath = path.join(electronDist, executableName);
  return fs.existsSync(electronPathFile) && fs.existsSync(executablePath);
}

function getInstalledElectronVersion() {
  if (!isElectronInstalled()) {
    return null;
  }

  const executablePath = path.join(electronDist, platformExecutableName());
  const env = { ...process.env };
  delete env.ELECTRON_RUN_AS_NODE;

  const result = spawnSync(executablePath, ['--version'], {
    cwd: appRoot,
    env,
    encoding: 'utf8',
  });

  if (result.status !== 0) {
    return null;
  }

  return String(result.stdout || '').trim().replace(/^v/, '');
}

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: appRoot,
    stdio: 'inherit',
  });

  if (result.status !== 0) {
    throw new Error(`${command} ${args.join(' ')} exited with code ${result.status}`);
  }
}

async function main() {
  if (!fs.existsSync(electronPackagePath)) {
    throw new Error('Electron is not installed. Run npm install first.');
  }

  const electronPackage = require(electronPackagePath);
  const installedVersion = getInstalledElectronVersion();
  if (installedVersion === electronPackage.version) {
    console.log(`Electron ${installedVersion} binary is already installed.`);
    return;
  }
  if (installedVersion) {
    console.log(`Electron binary version ${installedVersion} does not match package version ${electronPackage.version}; repairing.`);
  }

  const checksumsPath = path.join(electronRoot, 'checksums.json');
  const zipPath = await downloadArtifact({
    version: electronPackage.version,
    artifactName: 'electron',
    platform: process.env.ELECTRON_INSTALL_PLATFORM || process.platform,
    arch: process.env.ELECTRON_INSTALL_ARCH || process.arch,
    checksums: fs.existsSync(checksumsPath) ? require(checksumsPath) : undefined,
  });

  fs.rmSync(electronDist, { recursive: true, force: true });
  fs.mkdirSync(electronDist, { recursive: true });

  if (process.platform === 'win32') {
    throw new Error('fix:electron currently expects Linux/macOS unzip. Re-run npm install on Windows.');
  }

  run('unzip', ['-oq', zipPath, '-d', electronDist]);
  fs.writeFileSync(electronPathFile, platformExecutableName());

  if (!isElectronInstalled()) {
    throw new Error('Electron repair finished, but the executable is still missing.');
  }

  console.log(`Electron ${electronPackage.version} repaired at ${path.join(electronDist, platformExecutableName())}`);
  console.log(`Host: ${os.platform()} ${os.arch()}`);
}

main().catch((error) => {
  console.error(error.message || error);
  process.exit(1);
});
