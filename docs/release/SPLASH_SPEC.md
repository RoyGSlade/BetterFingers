# OR-02 · Startup screen — breakdown of the operator's prototype, and how it gets wired

Source: `betterfingers.zip` (2026-07-31), supplied by the operator. Extracted and
read in full by the director. This document is the **spec**; the zip is a
**design reference, not shippable code** — the reason is in §2.

---

## 1. What is actually in the zip

An **AI Studio applet export** — `package.json` name is `ai-studio-applet`, and it
still carries a `@google/genai` dependency it does not use.

| File | Size | Verdict |
|---|---|---|
| `types/startup.ts` | 740 B | **The most valuable file.** The whole state model. |
| `components/splash/BetterFingersSplash.tsx` | 16.6 KB | Main component — phase machine, timers, copy. Port the logic, not the code. |
| `components/splash/HorizonPulseSvg.tsx` | 6.9 KB | The animated visual. Pure SVG + CSS — **portable almost as-is.** |
| `components/splash/StatusDisplay.tsx` | 2.0 KB | Status line + activity dots + the "taking longer" counter. Trivial to port. |
| `components/splash/RecoveryCard.tsx` | 4.2 KB | Failure card: named error, "View details" disclosure, Retry. **Port this.** |
| `components/splash/SplashSimulatorPanel.tsx` | 6.4 KB | Dev harness to fake phases. Useful as a test idea, ships nowhere. |
| `components/main/MainAppView.tsx` | 11.6 KB | A mock of the main app. **Discard** — we have a real one. |
| `lib/tauri-bridge.ts` | 3.4 KB | Tauri event plumbing. Wrong transport (§2), but see §4 — one idea in here is worth keeping. |
| `docs/TAURI_SPLASH_SETUP.md` | 6.1 KB | Tauri wiring guide. Not applicable. |

## 2. Why it cannot be dropped in

The prototype is **Next.js 15 + React 19 + Tailwind + framer-motion +
lucide-react**, targeting **Tauri**.

BetterFingers is **Electron + a vanilla HTML/CSS/JS renderer** (`signal-desk.html`
plus `features/*.js`). There is no React anywhere in this codebase.

Importing it would mean adding React, a Tailwind build, an animation library and
an icon library **to ship one screen**, in a release whose entire stated goal is
to reduce risk and stop presenting broken states. That trade is not close.

**So: port the design. Do not import the code.** Every idea below survives the
port; only the framework is discarded.

## 3. The state model — keep this exactly

From `types/startup.ts`:

```
phase:    'booting' | 'loading-services' | 'preparing-voice'
        | 'almost-ready' | 'ready' | 'slow' | 'failed'
services: { name, status: 'pending'|'starting'|'online'|'failed', message? }[]
error:    { code, message, details?, timestamp } | null
elapsedMs, isReducedMotion
```

Three things here are genuinely good design and answer OR-02 directly:

1. **`slow` is a distinct phase, not a spinner that runs forever.** At 7 s the
   screen admits it is taking longer than expected and starts showing elapsed
   seconds. That is honesty, which is the entire point of OR-02.
2. **`services[]` is a list, not a single message.** This is what lets the screen
   tell the user about *their own machine* rather than a generic bar.
3. **`isReducedMotion`** is respected throughout. Keep that.

Copy, verbatim from the prototype — it is good, use it:

| Phase | Text |
|---|---|
| `booting` | Starting BetterFingers |
| `loading-services` | Initializing local services |
| `preparing-voice` | Preparing voice systems |
| `almost-ready` | Almost ready |
| `ready` | Ready |
| `slow` | Still preparing local services + `(Ns elapsed)` |
| `failed` | BetterFingers could not finish starting |

## 4. Wiring it to what the backend is ACTUALLY doing

Nothing here needs inventing. Every signal already exists.

| Source | What it gives us |
|---|---|
| `app/src/main/sidecar.js:46` `waitForHealthy()` | Backend up/down, with a **30 s** timeout and retry loop. Already runs on every boot. |
| `GET /health` (`server.py:2717`) | The readiness probe main already polls. |
| `GET /doctor` (`server.py:2527`) | **Eight real subsystems** — the services list, for free. |
| `GET /runtime/status` (`server.py:2761`) | Runtime detail. |
| `sidecar.js:13-15` failure thresholds | Existing notions of "unhealthy" vs "restart". |

**`/doctor`'s subsystems map 1:1 onto `services[]`** (`utilitiesWorkspace.js:421`):
`stt` · `llm` · `tts` · `hotkeys` · `models` · `audio` · `platform` · `hardware`

### Phase derivation — from real state only

| Phase | Derived from |
|---|---|
| `booting` | backend process spawned, `/health` not yet 200 |
| `loading-services` | `/health` 200; `/doctor` subsystems still `pending`/`starting` |
| `preparing-voice` | doctor reports `stt` and/or `tts` still loading |
| `almost-ready` | all subsystems resolved except non-blocking ones |
| `ready` | doctor green **and** the renderer has finished bootstrapping |
| `slow` | elapsed > 7 s and not yet ready |
| `failed` | **`waitForHealthy()` actually gave up** — not a splash-side timer |

### ⚠ The one real conflict, and the rule that resolves it

The prototype fails at **`timeoutMs: 16000`**. `waitForHealthy()` gives up at
**30 s**. If the splash declares failure at 16 s while the backend is still
starting and would have succeeded at 22 s, **the splash has lied** — which is the
exact bug OR-02 exists to fix, reintroduced by the fix.

**Rule: the main process owns `failed`. The splash never declares failure on its
own timer.** Keep `slow` at 7 s (it is an honest, reversible statement). Show
`failed` only when `waitForHealthy` rejects.

### Telling the user about their own PC

This is the operator's actual ask, and `/doctor` already carries it:

- `hardware` → the real tier. On this machine that is **integrated Intel Iris Xe,
  `igpu`** (D-0039) — so the screen can honestly say *"CPU + integrated GPU —
  4B-class models recommended"* instead of a meaningless bar.
- `models` → which model is loading and how big it is. This is the same gap
  QA-FR-002 was about: a user watching a silent 150 MB download.
- `audio` → ties directly into OR-06 below.

**Constraint: show a service only once there is a real signal for it.** A row
that says "starting" because a timer said so is the same lie in smaller type.

## 5. Transport

Discard Tauri. Keep **one** idea from `lib/tauri-bridge.ts`: it already falls back
to a **DOM `CustomEvent` channel** (`betterfingers-startup`). Electron can dispatch
exactly that from preload/IPC, so the *contract* ports even though the transport
does not. Main emits boot events → preload forwards → the splash listens. The
component never learns which framework it is inside, which is also what makes it
testable without booting anything.

## 6. What to build

1. A vanilla splash surface in the existing renderer idiom, with the phase machine
   and copy from §3.
2. Port `HorizonPulseSvg` (SVG/CSS, near-verbatim) and `StatusDisplay`.
3. Port `RecoveryCard`: named error + "View details" disclosure + **Retry** — this
   is §5.5 ("no error dead-ends") made concrete.
4. Main-process boot events over IPC, derived from `waitForHealthy` + `/doctor`.
5. The services list rendered from `/doctor`, never from a timer.
6. Respect `prefers-reduced-motion`.
7. Tests pinning: `failed` cannot appear before main gives up; a service row cannot
   render a status it has no signal for; `slow` appears at 7 s; reduced-motion
   suppresses animation.

**Explicitly not building:** `MainAppView` (we have a real app), the simulator
panel (its idea becomes a test), any Tauri code, React/Tailwind/framer-motion.
