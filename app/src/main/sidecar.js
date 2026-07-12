const fs = require('node:fs');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const { app } = require('electron');
const { EXPECTED_API_SCHEMA_VERSION } = require('./config');

// How the post-startup health monitor behaves once the backend is ready.
// A busy backend is not a dead backend: restarting on missed pings alone
// kills in-flight model work (review finding #2). The monitor distinguishes
// process death (restart promptly) from event-loop saturation (tolerate).
const HEALTH_POLL_INTERVAL_MS = 5000;
const HEALTH_FAILURES_BEFORE_UNHEALTHY = 3; // ~15s: surface "unhealthy" status
const HEALTH_FAILURES_BEFORE_RESTART_ALIVE = 24; // ~2min: process alive but silent
const HEALTH_FAILURES_BEFORE_RESTART_BUSY = 120; // ~10min: last health showed active jobs
const MAX_AUTO_RESTARTS = 3; // give up (and tell the user) after this many
const RESTART_COUNTER_RESET_MS = 5 * 60 * 1000; // a clean 5min resets the count

function isChildAlive(child) {
  return Boolean(child) && !child.killed && child.exitCode === null && child.signalCode === null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// The backend enforces BETTERFINGERS_AUTH_TOKEN on every non-/ws/ route,
// including /health and /runtime/version. The main process spawns the backend
// with that token, so its own health/version probes must present it too —
// otherwise every probe comes back 401, waitForHealthy() never sees an OK
// response, and startup times out and kills the backend it just launched.
function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function waitForHealthy(url, headers = {}, timeoutMs = 30000) {
  const startedAt = Date.now();

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const controller = new AbortController();
      const tid = setTimeout(() => controller.abort(), 3000);
      try {
        const response = await fetch(url, { cache: 'no-store', headers, signal: controller.signal });
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

async function tryReadHealth(url, headers = {}) {
  const controller = new AbortController();
  const tid = setTimeout(() => controller.abort(), 3000);
  try {
    const response = await fetch(url, { cache: 'no-store', headers, signal: controller.signal });
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
    if (!child || child.killed || child.exitCode !== null || child.signalCode !== null) {
      // Already gone (killed, or crashed on its own) — nothing to wait for.
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
  onStatusChange = null,
} = {}) {
  const healthUrl = `http://${host}:${port}/health`;
  const backendHeaders = authHeaders(authToken);
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
  let healthTimer = null;
  let consecutiveHealthFailures = 0;
  let autoRestartCount = 0;
  let lastRestartAt = 0;
  let restarting = false;
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
    if (typeof onStatusChange === 'function') {
      try {
        onStatusChange({ ...status });
      } catch (error) {
        // A status listener must never take down the main process.
      }
    }
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
        // Preserve prior sessions for diagnostics: append a separator instead of
        // wiping, and trim from the front if the file grows past ~2 MB.
        const maxLogFileBytes = 2 * 1024 * 1024;
        try {
          const stat = fs.statSync(logFilePath);
          if (stat.size > maxLogFileBytes) {
            const kept = fs.readFileSync(logFilePath).slice(-maxLogFileBytes);
            fs.writeFileSync(logFilePath, kept);
          }
        } catch (e) {
          // No existing log file yet — nothing to trim.
        }
        fs.appendFileSync(
          logFilePath,
          `\n===== session started ${new Date().toISOString()} =====\n`,
        );
      } catch (e) {
        console.error('Failed to prepare sidecar backend log file:', e);
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
          const existingHealth = await tryReadHealth(healthUrl, backendHeaders);
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
          waitForHealthy(healthUrl, backendHeaders),
          exitPromise,
        ].filter(Boolean));

        // Perform Version Handshake. Compatibility is gated on the API schema
        // version, not the marketing version — a 0.1.0 -> 0.2.0 app bump that
        // keeps the same contract must not trip the mismatch banner.
        const versionUrl = `http://${host}:${port}/runtime/version`;
        let versionPayload = null;
        try {
          const versionController = new AbortController();
          const versionTid = setTimeout(() => versionController.abort(), 3000);
          let res;
          try {
            res = await fetch(versionUrl, { cache: 'no-store', headers: backendHeaders, signal: versionController.signal });
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
          const backendSchema = versionPayload.schema_version;
          const backendVer = versionPayload.backend_version ?? 'unknown';
          appendLog(
            'electron',
            `Backend version ${backendVer}, API schema ${backendSchema} (expected schema ${EXPECTED_API_SCHEMA_VERSION}).`,
          );
          if (backendSchema !== EXPECTED_API_SCHEMA_VERSION) {
            versionMismatch = true;
            appendLog(
              'electron',
              `API schema mismatch! Backend schema ${backendSchema}, client expects ${EXPECTED_API_SCHEMA_VERSION}.`,
            );
          }
        } else {
          versionMismatch = true;
          appendLog('electron', `Could not verify backend version compatibility.`);
        }

        setStatus({
          state: versionMismatch ? 'version_mismatch' : 'ready',
          message: versionMismatch
            ? `Warning: this app speaks API schema ${EXPECTED_API_SCHEMA_VERSION}, but the backend reported schema ${versionPayload?.schema_version ?? 'unknown'}. Some features may not work.`
            : `Backend is ready at ${healthUrl}.`,
          health: result,
          backendVersion: versionPayload?.backend_version ?? null,
          schemaVersion: versionPayload?.schema_version ?? null,
          error: versionMismatch ? 'version_mismatch' : '',
        });

        appendLog('electron', `Backend handshake completed. State: ${status.state}`);

        // Only monitor liveness for a process we own and that came up cleanly.
        if (!versionMismatch && childProcess) {
          startHealthMonitor();
        }

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

  function stopHealthMonitor() {
    if (healthTimer) {
      clearInterval(healthTimer);
      healthTimer = null;
    }
    consecutiveHealthFailures = 0;
  }

  let lastHealthyPayload = null;

  function startHealthMonitor() {
    stopHealthMonitor();
    healthTimer = setInterval(async () => {
      // Skip while a (re)start is mid-flight or we don't own a process.
      if (restarting || !childProcess) {
        return;
      }

      const health = await tryReadHealth(healthUrl, backendHeaders);
      if (health) {
        consecutiveHealthFailures = 0;
        lastHealthyPayload = health;
        if (status.state === 'unhealthy') {
          setStatus({
            state: 'ready',
            message: `Backend recovered and is ready at ${healthUrl}.`,
            error: '',
          });
          appendLog('electron', 'Backend health recovered.');
        }
        return;
      }

      consecutiveHealthFailures += 1;

      // Process death is unambiguous — restart promptly.
      if (!isChildAlive(childProcess)) {
        appendLog('electron', 'Backend process has exited; restarting.');
        setStatus({
          state: 'unhealthy',
          message: 'Backend process exited. Attempting to recover…',
          error: 'unhealthy',
        });
        restartBackend('backend process exited');
        return;
      }

      // The process is alive but not answering: most likely saturated by
      // model work, not dead. Restarting now would destroy that work.
      const hadActiveJobs = Boolean(lastHealthyPayload && lastHealthyPayload.active_job_count > 0);
      const restartThreshold = hadActiveJobs
        ? HEALTH_FAILURES_BEFORE_RESTART_BUSY
        : HEALTH_FAILURES_BEFORE_RESTART_ALIVE;

      appendLog(
        'electron',
        `Backend health check missed (${consecutiveHealthFailures}/${restartThreshold}; process alive${hadActiveJobs ? ', jobs active' : ''}).`,
      );

      if (consecutiveHealthFailures === HEALTH_FAILURES_BEFORE_UNHEALTHY) {
        setStatus({
          state: 'unhealthy',
          message: 'Backend is not responding to health checks (process still running). Waiting for it to recover…',
          error: 'unhealthy',
        });
      }

      if (consecutiveHealthFailures >= restartThreshold) {
        setStatus({
          state: 'unhealthy',
          message: 'Backend stopped responding to health checks. Attempting to recover…',
          error: 'unhealthy',
        });
        restartBackend(
          hadActiveJobs
            ? 'health checks silent for 10min with jobs active'
            : 'health checks silent for 2min with no active jobs',
        );
      }
    }, HEALTH_POLL_INTERVAL_MS);

    if (typeof healthTimer.unref === 'function') {
      healthTimer.unref();
    }
  }

  async function restartBackend(reason) {
    if (restarting) {
      return;
    }
    restarting = true;
    stopHealthMonitor();

    const now = Date.now();
    if (now - lastRestartAt > RESTART_COUNTER_RESET_MS) {
      autoRestartCount = 0;
    }

    if (autoRestartCount >= MAX_AUTO_RESTARTS) {
      setStatus({
        state: 'crashed',
        message:
          'The backend stopped responding and could not be recovered automatically. Please restart BetterFingers.',
        error: 'crashed',
      });
      appendLog('electron', `Giving up after ${autoRestartCount} auto-restart attempts.`);
      restarting = false;
      return;
    }

    autoRestartCount += 1;
    lastRestartAt = now;
    appendLog(
      'electron',
      `Restarting backend (attempt ${autoRestartCount}/${MAX_AUTO_RESTARTS}): ${reason}`,
    );
    setStatus({
      state: 'restarting',
      message: `Backend stopped responding; restarting (attempt ${autoRestartCount})…`,
      error: '',
    });

    try {
      await stop();
    } catch (error) {
      appendLog('electron', `Error while stopping crashed backend: ${error.message}`);
    }

    restarting = false;
    try {
      await start();
    } catch (error) {
      appendLog('electron', `Auto-restart failed: ${error.message}`);
    }
  }

  async function stop() {
    stopHealthMonitor();
    const processRef = childProcess;
    childProcess = null;
    startPromise = null;

    if (!processRef) {
      const preserveStates = ['external', 'error', 'version_mismatch', 'crashed'];
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
