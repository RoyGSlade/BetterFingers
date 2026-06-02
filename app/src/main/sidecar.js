const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app } = require('electron');

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHealthy(url, timeoutMs = 30000) {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await fetch(url, { cache: 'no-store' });
      if (response.ok) {
        return await response.json();
      }
    } catch (error) {
      // The backend is still booting. Keep polling.
    }

    await sleep(500);
  }

  throw new Error(`Timed out waiting for backend health at ${url}`);
}

function resolveBackendExecutable() {
  const backendDir = path.join(process.resourcesPath, 'backend');
  const preferredNames = [
    'betterfingers-backend.exe',
    'betterfingers-backend',
    'server.exe',
    'server',
  ];

  for (const candidate of preferredNames) {
    const candidatePath = path.join(backendDir, candidate);
    if (fs.existsSync(candidatePath)) {
      return candidatePath;
    }
  }

  if (!fs.existsSync(backendDir)) {
    throw new Error(`Backend directory not found: ${backendDir}`);
  }

  const fallback = fs
    .readdirSync(backendDir)
    .filter((name) => !name.startsWith('.'))
    .map((name) => path.join(backendDir, name))
    .find((candidatePath) => fs.statSync(candidatePath).isFile());

  if (!fallback) {
    throw new Error(`No backend executable found in ${backendDir}`);
  }

  return fallback;
}

function killChildProcess(child) {
  return new Promise((resolve) => {
    if (!child || child.killed) {
      resolve();
      return;
    }

    let settled = false;
    const finish = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };

    child.once('exit', finish);

    if (process.platform === 'win32') {
      const killer = spawn('taskkill', ['/pid', String(child.pid), '/t', '/f'], {
        stdio: 'ignore',
        windowsHide: true,
      });

      killer.once('exit', finish);
      killer.once('error', finish);
      return;
    }

    child.kill('SIGTERM');
    const forceTimer = setTimeout(() => {
      try {
        child.kill('SIGKILL');
      } catch (error) {
        // Ignore kill errors on shutdown.
      }
      finish();
    }, 5000);

    child.once('exit', () => {
      clearTimeout(forceTimer);
      finish();
    });
  });
}

function createSidecar({
  host = '127.0.0.1',
  port = 8000,
  devCommand = 'python',
  devArgs = [],
} = {}) {
  const healthUrl = `http://${host}:${port}/health`;
  const isPackaged = app.isPackaged;
  const backendEnv = {
    ...process.env,
    BETTERFINGERS_LAZY_STARTUP: '1',
  };
  let childProcess = null;
  let startPromise = null;

  async function start() {
    if (startPromise) {
      return startPromise;
    }

    startPromise = (async () => {
      let exitListener = null;
      let exitPromise = null;

      if (!childProcess) {
        if (isPackaged) {
          const executablePath = resolveBackendExecutable();
          childProcess = spawn(executablePath, ['--host', host, '--port', String(port)], {
            cwd: path.dirname(executablePath),
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
            env: backendEnv,
          });
        } else {
          childProcess = spawn(devCommand, devArgs, {
            cwd: path.resolve(__dirname, '../../../'),
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
            env: backendEnv,
          });
        }

        childProcess.stdout?.on('data', (chunk) => {
          process.stdout.write(`[backend] ${chunk}`);
        });

        childProcess.stderr?.on('data', (chunk) => {
          process.stderr.write(`[backend] ${chunk}`);
        });

        exitPromise = new Promise((resolve, reject) => {
          exitListener = (code, signal) => {
            const descriptor = signal ? `signal ${signal}` : `code ${code}`;
            childProcess = null;
            reject(new Error(`BetterFingers backend exited before readiness (${descriptor})`));
          };

          childProcess.once('error', (error) => {
            childProcess = null;
            reject(error);
          });
          childProcess.once('exit', exitListener);
        });
      }

      try {
        const result = await Promise.race([
          waitForHealthy(healthUrl),
          exitPromise,
        ].filter(Boolean));

        return {
          url: healthUrl,
          packaged: isPackaged,
          health: result,
        };
      } catch (error) {
        await stop();
        throw error;
      } finally {
        if (childProcess && exitListener) {
          childProcess.removeListener('exit', exitListener);
        }
        startPromise = null;
      }
    })();

    return startPromise;
  }

  async function stop() {
    const processRef = childProcess;
    childProcess = null;
    startPromise = null;

    if (!processRef) {
      return;
    }

    await killChildProcess(processRef);
  }

  function getPid() {
    return childProcess?.pid ?? null;
  }

  function isRunning() {
    return Boolean(childProcess && !childProcess.killed);
  }

  return {
    start,
    stop,
    getPid,
    isRunning,
    healthUrl,
  };
}

module.exports = {
  createSidecar,
  waitForHealthy,
};
