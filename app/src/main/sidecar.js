const fs = require('node:fs');
const net = require('node:net');
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
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 3000);
      try {
        const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
        if (response.ok) {
          return await response.json();
        }
      } finally {
        clearTimeout(tid);
      }
    } catch (error) {
      // The backend is still booting. Keep polling.
    }

    await sleep(500);
  }

  throw new Error(`Timed out waiting for backend health at ${url}`);
}

function isTcpPortOpen(host, port, timeoutMs = 800) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;

    const finish = (isOpen) => {
      if (settled) {
        return;
      }
      settled = true;
      socket.destroy();
      resolve(isOpen);
    };

    socket.setTimeout(timeoutMs);
    socket.once('connect', () => finish(true));
    socket.once('timeout', () => finish(false));
    socket.once('error', () => finish(false));
    socket.connect(port, host);
  });
}

async function tryReadHealth(url) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
    if (!response.ok) {
      return null;
    }
    return await response.json();
  } catch (error) {
    return null;
  } finally {
    clearTimeout(tid);
  }
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
  authToken = '',
  devCommand = 'python',
  devArgs = [],
} = {}) {
  const healthUrl = `http://${host}:${port}/health`;
  const isPackaged = app.isPackaged;
  const backendEnv = {
    ...process.env,
    BETTERFINGERS_LAZY_STARTUP: '1',
    BETTERFINGERS_ENV: isPackaged ? 'production' : 'development',
    BETTERFINGERS_AUTH_TOKEN: authToken,
  };
  let childProcess = null;
  let startPromise = null;
  let logBuffer = [];
  const maxLogBufferLines = 200;
  let status = {
    state: 'stopped',
    message: 'Backend has not started yet.',
    pid: null,
    healthUrl,
    ownsProcess: false,
    packaged: isPackaged,
    error: '',
  };

  function setStatus(nextStatus) {
    status = {
      ...status,
      ...nextStatus,
      pid: childProcess?.pid ?? null,
      ownsProcess: Boolean(childProcess),
    };
  }

  function appendLog(streamName, data) {
    const text = String(data);
    const lines = text.split('\n');
    const timestamp = new Date().toISOString();
    
    let fileChunk = '';
    for (let line of lines) {
      if (line.endsWith('\r')) {
        line = line.slice(0, -1);
      }
      if (!line && line === lines[lines.length - 1]) {
        continue;
      }
      const logLine = `[${timestamp}] [${streamName}] ${line}`;
      logBuffer.push(logLine);
      fileChunk += logLine + '\n';
    }

    if (logBuffer.length > maxLogBufferLines) {
      logBuffer = logBuffer.slice(logBuffer.length - maxLogBufferLines);
    }

    try {
      const logFilePath = path.join(app.getPath('userData'), 'sidecar_backend_raw.log');
      fs.appendFileSync(logFilePath, fileChunk);
    } catch (e) {
      // Ignore write errors to prevent crashing the main process
    }
  }

  async function start() {
    if (startPromise) {
      return startPromise;
    }

    startPromise = (async () => {
      let exitListener = null;
      let exitPromise = null;

      try {
        const logFilePath = path.join(app.getPath('userData'), 'sidecar_backend_raw.log');
        fs.writeFileSync(logFilePath, '');
      } catch (e) {
        console.error('Failed to clear sidecar backend log file:', e);
      }
      logBuffer = [];

      if (!childProcess) {
        setStatus({
          state: 'starting',
          message: `Checking backend port ${host}:${port}...`,
          error: '',
        });
        appendLog('electron', `Checking backend port ${host}:${port}...`);

        const portOpen = await isTcpPortOpen(host, port);
        if (portOpen) {
          const existingHealth = await tryReadHealth(healthUrl);
          if (existingHealth?.status) {
            setStatus({
              state: 'external',
              message: `A BetterFingers backend is already responding on ${host}:${port}. Electron will use it but will not own or stop that process.`,
              health: existingHealth,
            });
            appendLog('electron', `External backend found responding on ${host}:${port}.`);
            return {
              url: healthUrl,
              packaged: isPackaged,
              external: true,
              health: existingHealth,
            };
          }

          const message = `Port ${port} is already in use, but it is not responding as BetterFingers. Stop the process using ${host}:${port} or choose a different backend port.`;
          setStatus({
            state: 'error',
            message,
            error: message,
          });
          appendLog('electron', `CRITICAL: Port conflict. ${message}`);
          throw new Error(message);
        }

        if (isPackaged) {
          const executablePath = resolveBackendExecutable();
          appendLog('electron', `Spawning packaged backend executable at: ${executablePath}`);
          childProcess = spawn(executablePath, ['--host', host, '--port', String(port)], {
            cwd: path.dirname(executablePath),
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
            env: backendEnv,
          });
        } else {
          appendLog('electron', `Spawning dev backend: ${devCommand} ${devArgs.join(' ')}`);
          childProcess = spawn(devCommand, devArgs, {
            cwd: path.resolve(__dirname, '../../../'),
            stdio: ['ignore', 'pipe', 'pipe'],
            windowsHide: true,
            env: backendEnv,
          });
        }

        setStatus({
          state: 'starting',
          message: `Started backend process and waiting for ${healthUrl}.`,
          error: '',
        });

        childProcess.stdout?.on('data', (chunk) => {
          process.stdout.write(`[backend] ${chunk}`);
          appendLog('stdout', chunk);
        });

        childProcess.stderr?.on('data', (chunk) => {
          process.stderr.write(`[backend] ${chunk}`);
          appendLog('stderr', chunk);
        });

        exitPromise = new Promise((resolve, reject) => {
          exitListener = (code, signal) => {
            const descriptor = signal ? `signal ${signal}` : `code ${code}`;
            childProcess = null;
            const message = `BetterFingers backend exited before readiness (${descriptor}). If port ${port} is occupied, stop the other process and restart Electron.`;
            setStatus({
              state: 'error',
              message,
              error: message,
              pid: null,
              ownsProcess: false,
            });
            appendLog('electron', `CRITICAL: Backend exited before readiness (${descriptor}).`);
            reject(new Error(message));
          };

          childProcess.once('error', (error) => {
            childProcess = null;
            setStatus({
              state: 'error',
              message: `Failed to start backend: ${error.message}`,
              error: error.message,
            });
            appendLog('electron', `CRITICAL: Failed to spawn child process: ${error.message}`);
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

        // Perform Version Handshake
        const versionUrl = `http://${host}:${port}/runtime/version`;
        const expectedVersion = '0.1.0';
        let versionPayload = null;
        try {
          const versionController = new AbortController();
          const versionTid = setTimeout(() => versionController.abort(), 3000);
          let res;
          try {
            res = await fetch(versionUrl, { cache: 'no-store', signal: versionController.signal });
          } finally {
            clearTimeout(versionTid);
          }
          if (res.ok) {
            versionPayload = await res.json();
          }
        } catch (e) {
          appendLog('electron', `Failed to fetch backend version: ${e.message}`);
        }

        let versionMismatch = false;
        if (versionPayload) {
          const backendVer = versionPayload.backend_version;
          appendLog('electron', `Backend version: ${backendVer} (expected: ${expectedVersion})`);
          if (backendVer !== expectedVersion) {
            versionMismatch = true;
            appendLog('electron', `Version mismatch detected! Backend is ${backendVer}, Frontend expects ${expectedVersion}`);
          }
        } else {
          versionMismatch = true;
          appendLog('electron', `Could not verify backend version compatibility.`);
        }

        setStatus({
          state: versionMismatch ? 'version_mismatch' : 'ready',
          message: versionMismatch
            ? `Warning: Frontend expects API version ${expectedVersion}, but backend reported version ${versionPayload?.backend_version ?? 'unknown'}.`
            : `Backend is ready at ${healthUrl}.`,
          health: result,
          error: versionMismatch ? 'version_mismatch' : '',
        });

        appendLog('electron', `Backend handshake completed. State: ${status.state}`);

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
      const preserveStates = ['external', 'error', 'version_mismatch'];
      setStatus({
        state: preserveStates.includes(status.state) ? status.state : 'stopped',
        message: preserveStates.includes(status.state) ? status.message : 'Backend is stopped.',
        pid: null,
        ownsProcess: false,
      });
      return;
    }

    appendLog('electron', `Stopping backend process (PID ${processRef.pid})...`);
    await killChildProcess(processRef);
    setStatus({
      state: 'stopped',
      message: 'Backend process stopped.',
      pid: null,
      ownsProcess: false,
    });
    appendLog('electron', `Backend process stopped.`);
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
    getStatus: () => ({ ...status, pid: childProcess?.pid ?? status.pid }),
    getLogs: () => [...logBuffer],
    healthUrl,
  };
}

module.exports = {
  createSidecar,
  waitForHealthy,
};
