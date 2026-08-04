# Selected-text capture qualification

Run one command from the BetterFingers checkout on each desktop/session under
test. On Linux or macOS, use:

```text
python3 tools/selection_capture_qualification.py
```

On Windows, use the Python Launcher (or `python` if that is the installed
command):

```text
py tools/selection_capture_qualification.py
```

The command inspects the operating system, display session, and relevant tool
availability, then guides the operator through two representative applications.
It writes `selection-capture-qualification.json` and
`selection-capture-qualification.md` to `selection-qualification-evidence/`.
Use `--non-interactive` only for environment/preflight collection; desktop
workflow checks remain `UNTESTED` in that mode.

## What this qualifies

The workflow under test is:

1. Start BetterFingers with the selection-rewrite hotkey enabled (default
   `Ctrl+Alt+R`).
2. In each representative app, select the supplied sentinel sentence in full.
3. Press the hotkey and observe BetterFingers' selection-capture and review
   status.
4. Confirm a rewritten draft opens for review only. Do not Accept, Apply, Send,
   or otherwise deliver it.
5. Confirm privately that the clipboard value from before the action is restored.

Workflow prompts are recorded separately for exactly two listed representative
target applications. Record PASS only for the target where the expected result
was observed; the overall result can pass only when both targets contain
exactly one of each canonical check (`selected-text capture`, `rewrite opens
review-only draft`, `clipboard is restored`, and `no automatic send occurs`),
with every check observed PASS. Legacy aggregate checks, one target, empty
targets, duplicate or made-up check names, and missing checks remain UNTESTED;
an observed FAIL remains FAIL.

Ctrl+Alt+R modifier hold/release behavior remains an external operator risk.
This qualification does not infer a local defect from source inspection or
automated tests; record the observed result during a real desktop run.

The kit never reads or writes the clipboard, sends key presses, or records the
selected/re-written text. Evidence stores only a fixed sentinel hash and length,
operator statuses, capability metadata, and safe tool basenames. `PASS` means
the operator observed the expected result. Missing platforms, unavailable
hardware, no desktop session, and skipped checks are `UNTESTED`, not PASS.

## Platform and session prerequisites

### Windows desktop

- The Windows command above is the supported invocation for this section; use
  `py` or `python` rather than assuming `python3` is installed.
- Use an interactive Windows desktop session, not a service/session-0 process.
- BetterFingers must be running and its selection-rewrite hotkey must be enabled.
- The kit records the native clipboard and global-hotkey paths as available;
  the actual capture, review-only, restoration, and no-send checks still need
  operator observation.
- Use Notepad and a browser text area or rich editor as representative apps.

### Linux X11

- An actual `DISPLAY` is required for X11 capability discovery. A stale
  `XDG_SESSION_TYPE=x11` without `DISPLAY` cannot report clipboard,
  copy-trigger, global-hotkey, or typing capability PASS, even when the tools
  are installed; the workflow remains UNTESTED.
- Install `xclip` (preferred) or `xsel` for clipboard read/write, and install
  `xdotool` for the explicit, non-privileged Ctrl+C copy trigger. Both backend
  checks must pass before selection capture is supported.
- Use a GTK/Qt editor such as GNOME Text Editor, gedit, or Kate, then a browser
  text area. Do not use terminal primary-selection behavior as the only test.

### Linux Wayland

- An actual `WAYLAND_DISPLAY` is required for Wayland capability discovery. A
  stale `XDG_SESSION_TYPE=wayland` without `WAYLAND_DISPLAY` cannot report
  clipboard, copy-trigger, or typing capability PASS, even when the tools are
  installed; the workflow remains UNTESTED.
- `WAYLAND_DISPLAY` takes precedence over `XDG_SESSION_TYPE=x11`, matching the
  product adapter's `is_wayland` decision. A mixed environment is therefore
  qualified as Wayland, never as X11.
- Install both `wl-copy` and `wl-paste` from `wl-clipboard`.
- Install `wtype` or `ydotool` for the explicit Ctrl+C copy trigger. Install
  `wl-copy` and `wl-paste` for clipboard read/write; both backend checks must
  pass before selection capture is supported.
- Global hotkeys and cross-application selection access are compositor/tool
  dependent. The kit deliberately reports that capability as unknown until the
  operator observes the real workflow; `wl-clipboard` being installed is not a
  product PASS. A complete, real two-target workflow observation may still
  authorize overall PASS when every canonical check passes.
- Use a native Wayland editor such as GNOME Text Editor or KWrite, then Firefox
  or Chromium. If the hotkey cannot reach the app, record the workflow as
  `UNTESTED` and include the displayed capability details in the evidence.

## Safety and evidence rules

- Use only this fixed sentinel during qualification:
  `BetterFingers selection qualification sentinel: select this complete sentence.`
- Do not put private text in a terminal, screenshot, issue, JSON, or Markdown.
- Verify clipboard restoration privately; record only PASS/FAIL/UNTESTED.
- Do not press any delivery control. A review-only result is required, and an
  automatic send is a failure.
- Never change `UNTESTED` to PASS based on tool presence, source inspection, or
  an automated test. Only an observed desktop check can be PASS.

## Reading the result

The report has separate capability and per-target workflow rows. Missing Linux
clipboard or copy-trigger tools with a live display are explicit capability
failures; absent desktop access or an unexercised Wayland path leaves the
workflow `UNTESTED`. Overall `PASS` is emitted only for exactly the two
expected representative targets, with one of every canonical workflow check
and all checks observed PASS, with no capability row `FAIL`. Any observed
workflow failure yields overall `FAIL`. Capability presence never increments
observed workflow counts or authorizes PASS by itself.

Automated tests for the kit are hermetic and never invoke clipboard APIs or
synthetic input:

```text
python3 -m pytest -q tests/test_selection_capture_qualification.py
```

Optional release-evidence metadata can be supplied without putting private
application text in the report:

```text
python3 tools/selection_capture_qualification.py \
  --artifact path/to/BetterFingers.AppImage \
  --model-id llama-3.2-3b-instruct \
  --runtime-id llama.cpp-<observed-version>
```

The generated JSON/Markdown records the discovered OS build, Python version,
repository commit, and app version when available. An artifact records only
its basename, byte size, and SHA256. Model/runtime identifiers are recorded
only when the operator supplies them; absent or undiscoverable metadata stays
`UNTESTED` or is omitted, never guessed.
