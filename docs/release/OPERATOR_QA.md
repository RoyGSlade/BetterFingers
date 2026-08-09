# OPERATOR QA — the hands-on pass before `v1.1.0-alpha.1` ships

**This is your script, Donaven.** Everything automatable has been automated and is
green; what's left is the part only a person can judge. Work top to bottom. Each
check is one action and one expected result — if what you see matches, tick it and
move on. If it doesn't, you don't need to diagnose anything: copy the four-line
report at the bottom and paste it into [`QA_NOTES.md`](QA_NOTES.md).

- **Time:** roughly 45–60 minutes for §1–§7. §8 needs the installers built first.
- **You do not need to be careful.** Try to break it. A crash you can reproduce is
  a better outcome than a clean run you didn't push on.
- **Nothing here is a trick question.** If a step feels ambiguous, that ambiguity
  is itself a finding — write it down.

---

## 0. Before you start — the one setup step that will otherwise waste your time

Running the automated board **without these two variables** produces **6 fake
failures** in `onboarding-prod` and reports 91/97 instead of 97/97. They are not
real. This has already burned two workers.

```bash
export BETTERFINGERS_DATA_DIR=/tmp/bf-qa-data
export BF_QA_USER_DATA_DIR=/tmp/bf-qa-user
mkdir -p "$BETTERFINGERS_DATA_DIR" "$BF_QA_USER_DATA_DIR"
```

And if you change **any** renderer file before testing, rebuild first — the QA
harness runs the **built** app out of `app/out/`, not your source:

```bash
cd app && npm run build
```

**A wiped data dir is what makes §1 a real first-run test.** To reset between
attempts, delete the two directories above and recreate them.

> ### ⚠ The two suites want OPPOSITE environments
>
> | Suite | Command | Env |
> |---|---|---|
> | QA board | `node app/tests/qa/run.mjs` | **needs** both variables set |
> | Python | `.venv/bin/python -m pytest -q` | **must NOT** have them set |
>
> Leaving the two QA variables exported and then running pytest produces
> **42 spurious failures**. They are not real — the same suite passes 3098/3098
> in a clean environment. This cost the director a false alarm; unset them first:
>
> ```bash
> env -u BETTERFINGERS_DATA_DIR -u BF_QA_USER_DATA_DIR .venv/bin/python -m pytest -q
> ```
>
> Use a separate terminal for each suite and this can't bite you.

---

## 1. First run — the highest-value 10 minutes in this document

Start from a **wiped** data dir. This is a brand-new user's entire first
impression, and it is where the wave's only RED bug was found.

| # | Do this | It should | ✓ |
|---|---|---|---|
| 1.1 | Launch with a wiped data dir | Onboarding opens by itself | ☐ |
| 1.2 | Read the Welcome step | Plain language, no jargon, obvious what to press | ☐ |
| 1.3 | Press **Tab** repeatedly on the consent step | Focus cycles **inside** the dialog and never escapes to the page behind | ☐ |
| 1.4 | Press **Escape** | Dialog **stays open** (it's a gate, not a dismissable popup) | ☐ |
| 1.5 | Read the consent copy | You can tell exactly what you're agreeing to | ☐ |
| 1.6 | Try **Decline** | Declining behaves honestly — it doesn't pretend to continue | ☐ |
| 1.7 | Accept, finish onboarding | You land on **Talk** | ☐ |
| 1.8 | **Count** the decisions you were forced to make after consent | Should be **3 or fewer** (mic OK, hotkey OK, go). Write the real number down even if it's higher | ☐ |
| 1.9 | Record your first dictation and stop it | See §1.10 before judging this one | ☐ |
| 1.10 | **Watch what happens while it processes** | If no speech model is cached yet, you should see an **explained** "downloading the speech model…" state — **not** a bare "Processing…" that sits there | ☐ |

> **1.10 is the one to be strict about.** This was `QA-FR-002`, a RED: the app
> silently downloaded ~150 MB with no indication, so the first thing a new user
> ever did looked like a freeze. It's fixed — your job is to confirm the fix reads
> clearly to a human. **"Technically there is a message" is not a pass.** If you
> can't tell what's happening or roughly how long it'll take, it fails.

**Also worth trying:** press Escape *during* onboarding while a button has focus.
There's a known rough edge (`QA-FR-001`) where focus gets dropped even though the
dialog correctly stays open. Confirm whether it bothers you in practice.

---

## 2. Talk

| # | Do this | It should | ✓ |
|---|---|---|---|
| 2.1 | Record → review → send, a few times | Feel immediate; no lag that makes you wonder if it heard you | ☐ |
| 2.2 | Watch the ring while you speak | States match reality — it isn't "listening" when it's finished | ☐ |
| 2.3 | Check the delivery control | Offers **Paste only**. Type and Copy are gone on purpose (D-0036) | ☐ |
| 2.4 | Force a failure (unplug mic mid-recording, or stop instantly) | It tells you honestly. **Nothing claims success that didn't happen** | ☐ |
| 2.5 | Retry after that failure | Retry actually works — you're not stuck | ☐ |
| 2.6 | Push-to-talk hotkey | Works on X11 | ☐ |
| 2.7 | On Wayland, if you use it | Degrades to toggle mode and **says so** rather than silently misbehaving | ☐ |
| 2.8 | Record long enough to trigger a watchdog warning, if you can | The warning is noticeable. It's now an inline status line, not a popup (`QA-TALK-003`) — tell us if that's too quiet | ☐ |

---

## 3. Library

| # | Do this | It should | ✓ |
|---|---|---|---|
| 3.1 | Open Library on a **fresh** profile with nothing captured | Explains what the screen is for **and** offers one obvious action ("Go to Talk") | ☐ |
| 3.2 | Apply a filter that matches nothing | Says so, and offers "Clear filters" | ☐ |
| 3.3 | Cause a fetch to fail (stop the backend, refresh) | Shows an error with "Try again" — it does **not** blank out and lose what was on screen | ☐ |

---

## 4. Studio / personas

| # | Do this | It should | ✓ |
|---|---|---|---|
| 4.1 | Open the persona wizard | Opens only because you asked — it never ambushes you | ☐ |
| 4.2 | Walk all four steps, then go **Back**, then forward | Navigation is clean; nothing is lost going back | ☐ |
| 4.3 | Try to finish with the name blank | Blocked, with a visible reason | ☐ |
| 4.4 | Finish properly | Lands somewhere sensible | ☐ |
| 4.5 | **Skip personas entirely and use the app** | Costs you nothing. No nag, no badge, no blocked feature | ☐ |

---

## 5. Utilities

| # | Do this | It should | ✓ |
|---|---|---|---|
| 5.1 | Open the **Wake Word** section | The backbone list actually **shows models**. (It was permanently empty until this wave — `QA-UTIL-001`) | ☐ |
| 5.2 | Look at the wake engine badge | Reads **"Ready"** when models are downloaded — not a permanent "Not installed" | ☐ |
| 5.3 | Import a wake model (`.onnx`) | Import works | ☐ |
| 5.4 | Delete the model you just imported | A **Delete** button exists on it, asks for confirmation, and actually removes it | ☐ |
| 5.5 | Look at a **built-in** model row | It has **NO** Delete button. This one matters — shipped models must not be deletable | ☐ |
| 5.6 | Try importing a non-model file (rename a PNG to `.onnx`) | Refused with an honest message naming what it detected | ☐ |
| 5.7 | Run Doctor, let something fail, run it again | Cards persist, the button re-enables, you're never stuck | ☐ |
| 5.8 | Download a model and watch progress | Status is honest; the log is readable | ☐ |

---

## 6. Settings / privacy

| # | Do this | It should | ✓ |
|---|---|---|---|
| 6.1 | Save a profile with a bad value | Save is blocked **with a visible reason** — not silently ignored | ☐ |
| 6.2 | Save a valid profile, reload | It persisted | ☐ |
| 6.3 | Preview **all three** privacy wipe modes | Each preview matches what it says it will do | ☐ |
| 6.4 | Run a wipe | Everything wiped is **listed honestly**, including the history database | ☐ |
| 6.5 | Try to use the app *during* a wipe | Writes are refused cleanly rather than racing | ☐ |
| 6.6 | Voice presets: apply one, delete one | Both work. Note: there is deliberately **no "make default"** — Apply is the whole story (D-0043) | ☐ |
| 6.7 | Voice blend + modulation chips | Clicking a chip visibly moves the sliders | ☐ |
| 6.8 | **Listen** to the default voice | Does it actually sound right? This is pure judgement and nobody else can make it | ☐ |

---

## 7. Overlays

| # | Do this | It should | ✓ |
|---|---|---|---|
| 7.1 | Watch the ring overlay through a full dictation | States track reality start to finish | ☐ |
| 7.2 | Review overlay: rewrite-instruct | Works | ☐ |
| 7.3 | Press **Read**, then press it again to **Stop** | Playback actually stops, and the button returns to "Read" — not a dead control | ☐ |
| 7.4 | Press Read a **third** time | Starts a new read. It's reusable, not one-shot | ☐ |

---

## 8. Package smoke — only after the installers exist

Not started yet; F-1/F-2 are the next work after this pass.

| # | Do this | It should | ✓ |
|---|---|---|---|
| 8.1 | Install on a machine with **no dev tooling** | Installs and launches | ☐ |
| 8.2 | First dictation on that clean machine | Works end to end | ☐ |
| 8.3 | Uninstall, then reinstall | Keeps or wipes your data **exactly as the UI promised** | ☐ |
| 8.4 | Controller / Stream Deck, if you have them | Per `archive/WAVE10_QA.md`. Skip if the hardware isn't at hand | ☐ |

---

## How to report anything you find

Don't diagnose it. Four lines is plenty — paste into the matching section of
[`QA_NOTES.md`](QA_NOTES.md):

```
### QA-<SCREEN>-<next number> · <what went wrong, in your words> · <RED|YEL|GRN> · OPEN
- Found by / date: Donaven / 2026-07-30
- Repro: <what you did, starting from what state>
- Expected vs actual: <what you thought would happen> / <what did>
```

**Severity — go with your gut, I'll re-triage:**

| | |
|---|---|
| **RED** | I would not ship this. Data loss, a lie, a dead end, or something that makes the app look broken |
| **YEL** | Annoying. Fix it if it's cheap |
| **GRN** | Just noting it |

Screen prefixes: `QA-FR` first-run · `QA-TALK` · `QA-LIB` · `QA-STU` studio ·
`QA-UTIL` · `QA-SET` settings/privacy · `QA-OVL` overlays · `QA-PKG` installer ·
`QA-SEC` security · `QA-DOC` docs · `QA-BL` ideas for later.

**When in doubt, file it.** A duplicate costs me a minute. A finding you talked
yourself out of costs a user.

---

## What's already been verified, so you don't re-test it

| Automated | Result |
|---|---|
| Production QA board | **97/97**, three consecutive green runs |
| Node suite | **1668 / 1668** |
| Python suite | see `DIRECTOR_LOG.md` for the run at release HEAD |
| Parity ledger | **411 wired / 27 intentional_cut / 0 blocked** |

**Known and deliberate — not bugs, don't file them:**

- Delivery offers **Paste only** (D-0036).
- There is **no "make default"** for voice presets (D-0043) — Apply does the job.
- The single Start/Stop toggle is gone; there's an explicit **Start** and **Stop**
  pair plus a never-disabled Emergency Stop (D-0037).
- The dev machine has **no discrete GPU** — integrated Intel Iris Xe, `igpu` tier
  (D-0039). CUDA paths exist but have never been exercised on this host.
- Dark theme only; installers are unsigned. Both are recorded limitations.

**Still open and honestly unknown:**

- `ruff` and `bandit` have **never been run** — neither is installed here, so
  their baselines could be clean or could be hundreds of findings. The CI jobs are
  in place but report-only and unproven.
- The CI gates need a push to GitHub before anyone can claim they're green.
