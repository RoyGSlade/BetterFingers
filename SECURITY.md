# Security Policy

BetterFingers is a local-first application: speech, transcripts, drafts, and recordings
are among the most sensitive data on a user's machine. We take reports seriously.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Report privately through one of:

- GitHub's **[private vulnerability reporting](https://github.com/RoyGSlade/BetterFingers/security/advisories/new)**
  (Security tab → "Report a vulnerability"), or
- email the maintainer at **donavencrenshaw@gmail.com** with `BetterFingers security` in
  the subject.

Please include: affected version/commit, platform, a description of the issue, and
reproduction steps or a proof of concept. If your report involves a captured recording or
transcript, redact any real personal content before sending it.

We aim to acknowledge reports within a few days. As a solo-maintained project, fix
timelines are best-effort; we will keep you updated and credit you in the release notes
unless you prefer to remain anonymous.

## Scope

In scope — issues in this repository, for example:
- Local privilege or sandbox-escape via the Electron shell, sidecar, or IPC boundary.
- Leakage of user speech/transcripts/recordings to disk, logs, diagnostics, or the network
  beyond what the privacy model documents.
- The privacy wipe failing to remove data it reports as removed.
- Auth-token handling on the local REST/WebSocket boundary.
- Unverified model/binary download or path-traversal in model management.

Out of scope:
- Vulnerabilities in third-party model weights or upstream runtimes (report those
  upstream), though we want to know if BetterFingers uses them unsafely.
- Attacks requiring an already-compromised machine or physical access.
- Missing hardening that is already tracked on the roadmap in [DESIGN.md](DESIGN.md)
  (e.g. at-rest encryption, code signing) — a heads-up is welcome, but these are known.

## Data & network posture

BetterFingers runs inference locally. Intended outbound traffic is limited to model/runtime
downloads the user initiates, update checks against the project's public GitHub Releases
channel (none before the user accepts the privacy notice; automatic checks are off on a fresh
install until the user turns them on; a manual "Check for updates" works after consent),
and a bug report the user explicitly prepares, reviews, consents to, and confirms through a
configured HTTPS support relay. Without that relay, bug reporting
only copies the reviewed report and opens the user's email client or Discord; the app does not
claim delivery. Any other outbound connection is a reportable issue. See [DESIGN.md §9](DESIGN.md)
for the data-lifecycle and supply-chain model, and [docs/BUG_REPORTING.md](docs/BUG_REPORTING.md)
for the bug-report privacy boundary and relay contract.

## Local trust boundaries

What the app enforces on the machine itself (details in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)):

- **A person's yes is a native dialog, not a request field.** Approving a workflow, changing a
  persona's examples and placing a draft into another application each need a short-lived,
  single-use ticket that only the Electron main process can sign, and only after a native dialog
  showed the exact, complete content and the person clicked the approving button. The signing key
  is held by the main process and the backend it spawns; renderers never see it, and the backend
  refuses approvals without it. A spoken phrase, a request flag or a model's text is never an
  approval. **Everything fails closed**: if the content cannot be fetched, verified or shown,
  nothing is approved.
- **A dialog that cannot show everything offers no way to approve.** Every approval dialog has a
  line budget (26 lines, fewer on a short screen) and a character budget (1600 characters), counted
  on exactly what the toolkit will draw. Every dynamic field (the title, the message, each detail
  line, persona names, application names, labels) goes through one display pipeline: a field meant
  to be one line has its newlines and tabs drawn as visible marks (`⏎`, `⇥`) and every other
  invisible or control character as `<U+XXXX>`, so untrusted text cannot add lines; multi-line
  content is split on its newlines and every resulting line is counted. The message is wrapped at
  its own (narrower) width and each of its lines counts twice, because it is drawn larger and bold.
  Lines are wrapped by their estimated rendered width so the toolkit never wraps them again; the
  budgets were measured by opening the real dialog under a virtual display at 1920x1080, 1366x768
  and 1280x720, including a name with 45 newlines (`app/tests/nativeDialogXvfb.test.mjs`). Anything
  over a budget gets a dialog with a single Close button that says it is too long to show in full
  and where to read it; nothing is signed. Long lines are wrapped, never cut.
- **Every workflow run is confirmed, and runs only what was shown.** Approving a workflow and
  running it are separate acts. Every run, whoever asks (a page, a Stream Deck key, a controller)
  and whatever it does, opens a native dialog first; there is no dialog-free run path. If the
  backend cannot describe the run, the preview does not verify, the workflow is not runnable right
  now (not approved, switched off, changed) or a target cannot be resolved, nothing is shown and
  nothing runs, and enabling it afterwards cannot rescue that answer. The click yields a
  single-use run authorization bound to the exact plan and to the launch targets resolved at that
  moment (the program and its argument list, each link, each folder), which the dialog names. The
  executor runs only those frozen targets and stops if a confirmed application changes before its
  step. Replacing a confirmed application's entry needs a native dialog showing before and after,
  and so does removing one. The registry keeps an identity history of removed entries, so adding a
  removed id again, or adding an id that a saved workflow already names, is shown as the
  replacement it is (if the saved workflows cannot be read, an add is treated as one). The send shortcut never places text by itself: a press opens the native dialog showing
  the draft main fetched from the backend, and only Ctrl/Alt/Meta chords or function keys are
  accepted as that shortcut.
- **Persona examples change only with a tap, and the whole list is what is approved.** Any change
  to a persona's few-shot list (an addition, an edit, a removal, a reordering, a repeated copy,
  emptying it) is shown as a before/after diff of the complete resulting list and signed against
  the list before and after. Learning an example binds the complete learned list it results in,
  so an example the cap evicts is shown in the dialog and covered by the ticket. Every DESTRUCTIVE
  example change needs a native dialog that shows its scope and a ticket bound to it: deleting one
  learned example, clearing one persona's learned examples (the persona and its list or count),
  clearing every persona's learned examples (the whole collection), deleting a custom persona with
  its few-shot list, every privacy wipe mode and the factory reset (what the mode deletes, from the
  backend's own inventory, and its options; the factory reset still needs its typed phrase too).
  None of these is reachable through the dashboard's generic proxy, and no request flag or
  renderer boolean counts as the tap. The backend verifies each ticket and commits the change in
  one step under the store's lock, against the list stored at that moment, so a list that changed
  after the dialog voids the ticket.
- **One persona identity.** A persona is stored under its canonical name (letters, digits, spaces,
  `_`, `-`, `.`, trimmed). Every persona route, and main before any lookup or dialog, refuses a
  name that is not already canonical with a 422 that names the canonical form, so the lookup, the
  ticket's subject, the before/after comparison and the write always name the same persona.
- **Voice only requests.** "Send it" opens the same native dialog as a click on Place; nothing
  spoken confirms anything, and there is no voice-confirmation flow. Spoken commands that would
  need a confirmation are refused.
- **Clipboard (policy): allowed, not harmless.** Copying a draft to the clipboard (`copy_only`) and
  the page's clipboard write channel need no dialog. That is a deliberate, stated exception, and it
  IS an authority given to untrusted text: whatever reaches the clipboard can be pasted somewhere
  the person did not intend, and other programs can read the clipboard. What it does not do is
  send, run, approve or change a persona's examples: it places nothing in another application and
  sends nothing over the network, and any onward use is a paste the person makes. A placement into
  another application (paste, type, open the chat and send) always needs the dialog.
- **The local API accepts only loopback Host headers and no foreign browser Origin**, and every
  call needs the bearer token. The token is never printed, never in a URL, and is masked in logs.
- **llama-server runs with a per-run API key**, no web UI, no slots endpoint, loopback only.
- **Each window has its own minimal preload and a strict CSP**; the overlay and the splash cannot
  call workflow, draft, privacy or file channels. Web permissions (camera, screen, clipboard,
  location) are denied; the microphone is allowed only for the dashboard's own recorder.
- **MCP servers run only inside the strict sandbox, or not at all.** The backend's own
  credentials are never in its environment (the shell hands them over a pipe), and on Linux the
  backend makes itself non-dumpable BEFORE it reads them; if it cannot, it exits rather than hold
  them. An MCP server runs only under bubblewrap on Linux: its own PID/IPC/UTS namespaces, no new
  privileges, no capabilities, and a filesystem made only of the system runtime (`/usr` and the
  `/lib*`, `/bin`, `/sbin` links, read-only), a few `/etc` files programs need to start, and the
  server's own install folder (read-only; `install_dir` in its entry, plus an absolute command's
  folder and absolute file arguments). Its home is an empty tmpfs; the host home, the app's data
  folder, all of `/run` (D-Bus, Wayland, PipeWire, keyrings, `$XDG_RUNTIME_DIR`) and the X11 sockets
  are not there. **The network is off** unless the entry says exactly `"network": true`, which the
  server listing shows. `bwrap` itself starts with a fixed, trusted environment; the server's own
  `env` block is installed inside the sandbox (`--clearenv`, `--setenv`), and loader and
  runtime-injection variables (`LD_*`, `GCONV_PATH` and the rest of glibc's unsecure list, `PATH`,
  `BETTERFINGERS_*`) are refused everywhere. The listing shows each server's full configuration
  (command, every argument, every environment value, the network flag, what is mounted) and why a
  server cannot start. **Where that sandbox cannot be established (Windows, macOS, no usable
  bubblewrap) MCP servers are disabled**, with a message that says why; a `"sandbox": "off"` entry
  is refused everywhere. There is no "trusted on this machine" exception: a one-time consent cannot
  make every later launch of an unconfined process harmless. **MCP on Windows and macOS waits for a
  real sandbox, in a later phase.** Known limit: with `"network": true` a server shares the host
  network namespace, so abstract-namespace sockets (such as an X server's `@/tmp/.X11-unix/X0`)
  stay reachable; no X authority file is mounted, which defeats cookie authentication, and leaving
  the network off closes it entirely. The backend's environment route for credentials (`python server.py` with
  `BETTERFINGERS_AUTH_TOKEN`) is for development only and is not hardened.
