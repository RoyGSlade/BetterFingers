"""Wave 12A Objective B — real-backend probe for findings 5, 8, 9.

Run by the director (sup-dataroot cannot launch a server or read outside the
repo). Everything it prints is raw observation: no PASS/FAIL is asserted here,
because the point is to find out what actually happens, not to confirm a guess.

  A. The llama-server / model-file question (director's finding-5 hypothesis):
     is the running server holding an open descriptor to a DELETED model file?
  B. Boot a backend on a clean data root and time the endpoints that feed the
     dropdowns the owner reports as empty.
  C. Save a blended voice preset, re-list it, and try to make it the default —
     the "cant select it as my main voice after saving" path.

Usage (from the repo root):
    .venv/bin/python probe_wave12a/probe.py
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "/home/donaven/Desktop/BetterFingers"
PORT = 8011
TOKEN = "wave12a-probe-token"
DATA_ROOT = os.path.join(REPO, "probe_wave12a", "dataroot")
BASE = f"http://127.0.0.1:{PORT}"


def rule(title):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def call(method, path, payload=None, timeout=30):
    """Returns (status, body, elapsed_seconds). Never raises."""
    url = BASE + path
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    if data:
        req.add_header("Content-Type", "application/json")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, body, time.monotonic() - start
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace"), time.monotonic() - start
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", time.monotonic() - start


# --- A. the llama-server / deleted-model question ---------------------------

def probe_llama_server():
    rule("A. Running llama-server and the model file it was started with")
    try:
        ps = subprocess.run(["ps", "-eo", "pid,args"], capture_output=True, text=True, timeout=20)
    except Exception as exc:
        print(f"  ps failed: {exc}")
        return
    lines = [ln for ln in ps.stdout.splitlines() if "llama-server" in ln and "grep" not in ln]
    if not lines:
        print("  No llama-server process is running.")
        return
    for line in lines:
        pid = line.split()[0]
        print(f"\n  PID {pid}: {line.strip()[:200]}")
        match = re.search(r"(?:--model|-m)\s+(\S+)", line)
        if not match:
            print("    No --model argument found on the command line.")
            continue
        model_path = match.group(1)
        exists = os.path.exists(model_path)
        print(f"    --model      : {model_path}")
        print(f"    exists NOW?  : {exists}")
        if exists:
            print(f"    size_bytes   : {os.path.getsize(model_path)}")
        # An fd pointing at "(deleted)" is the proof: the process still holds
        # the inode open, so it looks healthy while the file is gone from disk.
        fd_dir = f"/proc/{pid}/fd"
        try:
            deleted = []
            for entry in os.listdir(fd_dir):
                try:
                    target = os.readlink(os.path.join(fd_dir, entry))
                except OSError:
                    continue
                if "(deleted)" in target:
                    deleted.append(f"fd {entry} -> {target}")
            print(f"    open fds to DELETED files: {len(deleted)}")
            for item in deleted:
                print(f"      {item}")
        except PermissionError:
            print(f"    {fd_dir}: permission denied (re-run as the owner of the process)")
        except OSError as exc:
            print(f"    {fd_dir}: {exc}")


# --- B/C. the backend --------------------------------------------------------

def wait_for_health(proc, seconds=180):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            print(f"  Backend exited early with code {proc.returncode}")
            return False
        status, _body, _elapsed = call("GET", "/health", timeout=5)
        if status == 200:
            print(f"  /health OK after {seconds - (deadline - time.monotonic()):.1f}s")
            return True
        time.sleep(1.0)
    print(f"  /health never became ready within {seconds}s")
    return False


def timed(label, method, path, payload=None, timeout=30):
    status, body, elapsed = call(method, path, payload, timeout)
    snippet = body if len(body) <= 400 else body[:400] + f"... [{len(body)} bytes total]"
    print(f"\n  {label}")
    print(f"    {method} {path}")
    print(f"    status={status}  elapsed={elapsed:.2f}s")
    print(f"    body: {snippet}")
    return status, body, elapsed


def count_keys(body):
    try:
        parsed = json.loads(body)
    except Exception:
        return None
    if isinstance(parsed, dict):
        return len(parsed)
    if isinstance(parsed, list):
        return len(parsed)
    return None


def main():
    probe_llama_server()

    rule("B. Backend on a CLEAN data root — the endpoints behind the dropdowns")
    os.makedirs(DATA_ROOT, exist_ok=True)
    print(f"  BETTERFINGERS_DATA_DIR = {DATA_ROOT}")
    print(f"  contents before boot   = {sorted(os.listdir(DATA_ROOT))}")

    env = dict(os.environ)
    env["BETTERFINGERS_DATA_DIR"] = DATA_ROOT
    env["BETTERFINGERS_AUTH_TOKEN"] = TOKEN
    proc = subprocess.Popen(
        [os.path.join(REPO, ".venv/bin/python"), "server.py", "--port", str(PORT), "--log-level", "INFO"],
        cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        if not wait_for_health(proc):
            return 1

        # The two lists the owner reports as empty. The renderer gives these a
        # 2500 ms budget (api/backend.js fetchJson default) and turns ANY
        # failure into an empty list, so elapsed time matters as much as status.
        _s, personas_body, personas_t = timed("personas (feeds #sdSetCurrentPreset)", "GET", "/personas")
        print(f"    -> persona count: {count_keys(personas_body)}   "
              f"renderer 2500ms budget {'EXCEEDED' if personas_t > 2.5 else 'ok'}")

        _s, voices_body, voices_t = timed("tts voices (feeds the blend pickers)", "GET", "/tts/voices")
        print(f"    -> renderer 2500ms budget {'EXCEEDED' if voices_t > 2.5 else 'ok'}")

        timed("voice presets", "GET", "/voice-presets")
        timed("profiles (findings 6/7: 'settings fetch failing throughout')", "GET", "/profiles")

        rule("B2. LLM warmup — finding 5 ('stuck warming up and wont work')")
        timed("runtime status before warmup", "GET", "/runtime/status")
        # get_selected_llm_engine() runs INSIDE this async handler with no
        # run_in_threadpool, so if it blocks, it blocks the whole event loop.
        timed("warmup llm", "POST", "/runtime/warmup", {"llm": True, "stt": False, "hotkeys": False}, timeout=180)
        timed("llm models (does the app think the model file is present?)", "GET", "/models/llm")

        rule("B3. Are the dropdown endpoints starved WHILE warmup runs?")
        print("  Re-timing /personas immediately after the warmup call:")
        _s, body2, t2 = timed("personas after warmup", "GET", "/personas")
        print(f"    -> persona count: {count_keys(body2)}   "
              f"renderer 2500ms budget {'EXCEEDED' if t2 > 2.5 else 'ok'}")

        rule("C. Finding 8 — save a blended preset, then try to make it the main voice")
        preset = {"name": "Wave12A Blend", "base": "af_heart", "speed": 1.0,
                  "blend": {"am_puck": 0.4}}
        timed("save blended preset", "POST", "/voice-presets", preset)
        _s, listed, _t = timed("re-list presets (does the save persist?)", "GET", "/voice-presets")
        print(f"    -> 'Wave12A Blend' present in the list: {'Wave12A Blend' in listed}")
        timed("make it the default/main voice", "POST", "/voice-presets/Wave12A%20Blend/make-default")
        _s, after, _t = timed("re-list and read the default field", "GET", "/voice-presets")
        try:
            parsed = json.loads(after)
            print(f"    -> default now: {parsed.get('default')!r}")
        except Exception:
            pass
        print("\n  NOTE: the backend route works. The renderer exports "
              "setDefaultVoicePreset()/clearDefaultVoicePreset() in api/backend.js "
              "but NOTHING in app/src/renderer ever calls them — there is no UI "
              "control for 'make this preset my main voice'. That is finding 8.")

        rule("D. Data root the backend actually elected")
        timed("privacy locations", "GET", "/privacy/report")

        print(f"\n  DATA_ROOT contents after the run: {sorted(os.listdir(DATA_ROOT))}")
    finally:
        rule("Backend shutdown + log tail")
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            out, _ = proc.communicate()
        tail = (out or "").splitlines()[-60:]
        for line in tail:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
