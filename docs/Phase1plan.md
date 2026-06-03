# Phase 1 Implementation Plan - Core Runtime, Sidecar, and Diagnostics

This plan outlines the enhancements and fixes required to bring the core BetterFingers Electron sidecar startup, shutdown, diagnostics, and version verification up to production-grade reliability.

---

## Proposed Changes

We will introduce enhancements across both the Electron shell and the Python FastAPI backend, focusing on startup diagnostic logging, a centralized `/doctor` checkup, version compatibility handshakes, and test coverage.

### 1. Electron Main Process & Sidecar Management

#### [MODIFY] [sidecar.js](file:///home/roygslade/Desktop/BetterFingers/app/src/main/sidecar.js)
- **Stdout/Stderr Capturing**: Buffer stdout and stderr streams of the Python process (`childProcess`) in a rolling memory buffer (up to 200 lines). This will preserve Python stack traces or startup crash logs even if the FastAPI server fails to start.
- **Version Compatibility Handshake**: After the sidecar `/health` check succeeds, query `/runtime/version`. If a mismatch is detected, transition the sidecar state to `version_mismatch` and log a fatal warning.
- **Port Conflict Hardening**: Refactor port checking. If a port is occupied but does not respond to BetterFingers' `/health` endpoint, flag this as a critical third-party conflict (`state: 'error'`) with actionable advice.

#### [MODIFY] [ipc.js](file:///home/roygslade/Desktop/BetterFingers/app/src/main/ipc.js)
- **Log Exposure**: Add a new IPC handler `sidecar:get-logs` which allows the renderer to fetch the buffered stdout/stderr from the sidecar.
- **Doctor Diagnostics Exposure**: Add a handler to expose local sidecar diagnostic state including any version mismatches.

#### [MODIFY] [preload.js](file:///home/roygslade/Desktop/BetterFingers/app/src/preload/preload.js)
- Expose the new `getSidecarLogs` IPC method via the `betterFingers` global API bridge.

---

### 2. Python FastAPI Backend

#### [MODIFY] [server.py](file:///home/roygslade/Desktop/BetterFingers/server.py)
- **`/runtime/version` Endpoint**: Create a new GET endpoint returning JSON with backend version, expected API versions, and schema numbers:
  ```json
  {
    "backend_version": "0.1.0",
    "expected_electron_api_version": "0.1.0",
    "schema_version": 1,
    "config_version": 1
  }
  ```
- **`/doctor` Centralized Diagnostics**: Create a new GET endpoint compiling status from all subsystems:
  - `health`: active state
  - `stt`: model size, load state, and device
  - `llm`: engine status, model ID, path diagnostics, ready flags
  - `tts`: provider state, loaded voices, active playback devices
  - `hotkeys`: active/inactive, current key bindings
  - `audio`: list available microphones using `sounddevice` and default device name
  - `platform`: platform capacities, restrictions (e.g. Wayland type/paste injection issues)
  - `recovery`: recovery lookup guidelines for each common fault
- **Severity-Classified Errors**: Refactor `record_runtime_error` to accept a `severity` argument (`"info"`, `"warning"`, `"recoverable"`, `"fatal"`), recording this severity inside the history list.

---

### 3. Frontend / Renderer UI

#### [MODIFY] [main.js](file:///home/roygslade/Desktop/BetterFingers/app/src/renderer/main.js)
- **Startup Crash View**: If sidecar status returns `error` or `offline`, call `window.betterFingers.getSidecarLogs()` and show the raw captured backend process logs in a scrollable container in the diagnostics view.
- **Version Drift Alert**: Display a banner at the top of the UI if `version_mismatch` is flagged.
- **Doctor Card Rendering**: Design and update the Diagnostics pane to display structured cards highlighting details from the new `/doctor` endpoint.
- **Severity Icons**: Style the runtime error log table according to severity levels (`info` in blue, `warning` in orange, `recoverable` in red, `fatal` in deep crimson).

#### [MODIFY] [index.html](file:///home/roygslade/Desktop/BetterFingers/app/src/renderer/index.html)
- Add containers for displaying captured backend startup logs when the app is offline/crashed.
- Add structures for displaying doctor diagnostic cards and version mismatch warnings.

---

## Verification Plan

### Automated Tests
We will add new tests to our Python testing suite to verify the changes:
- Run `pytest tests/test_server_platform_runtime.py` to ensure:
  - `/runtime/version` endpoint returns correct version attributes.
  - `/doctor` returns status dictionaries for all subsystems.
  - `record_runtime_error` persists severity classifications correctly.

### Manual Verification
- **Quit Behavior Verification**: Start Electron dev stack, verify both processes. Exit Electron, verify via `ps aux | grep python` that the sidecar FastAPI process has been killed.
- **Startup Failure Test**: Intentionally introduce a syntax error in `server.py` and verify that the Electron UI detects the failure, enters the error state, fetches sidecar logs via IPC, and renders the python stack trace on the dashboard.
- **Version Mismatch Test**: Change the expected backend version in Electron and verify that a warning is displayed.

---

## Open-Ended Questions

Before starting work, please review and answer these questions:

1. **Version Drift Enforcement**: Should a version mismatch block user interaction entirely (fatal error state), or should it just display a warning banner while allowing the user to proceed at their own risk?
continue but be warned type beat
2. **Audio Query Blocking**: `sounddevice.query_devices()` performs hardware queries which can block for ~0.5 to 1.5 seconds on some configurations. Should we query and cache devices in a background thread upon backend boot/doctor refresh, or query them synchronously on each `/doctor` request?
maybe keep a list add a way to refresh if for some reason the sounddevice stops working or perhaps when they go to change playback or output device
3. **Buffer Log Strategy**: Is a 200-line rolling buffer in memory for stdout/stderr sufficient for debugging startup crashes? Would you like us to also write these captured logs to a separate file (e.g. `sidecar_backend_raw.log`) in the user data directory for persisted logging?
yes write both 
4. **UI Integration Preference**: Would you prefer the centralized "Doctor" status cards to reside in the main dashboard workspace, or within a dedicated diagnostics/troubleshooting tab in the Settings panel?
create a dedicated tab even the current page for the settings is overwhelming at the moment and needs a rework later.
