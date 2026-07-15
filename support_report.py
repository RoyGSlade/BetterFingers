"""Build a copy-pasteable **support report** for alpha testers (backlog item 6).

BetterFingers ships with **no telemetry** — a tester who hits a problem has no
way to send us diagnostics. This module renders a single, human-readable
Markdown report the user can copy with one click and paste into an issue or
chat: version, hardware tier, loaded models, runtime validation, redacted
recent errors, and the relevant filesystem paths.

**Privacy is the whole point.** The report is assembled ONLY from diagnostic
sources — hardware specs, model ledger, the curated runtime-error feed, and
paths. It NEVER contains transcription content, dictated text, wake phrases, or
draft bodies. Error messages pass through :func:`redact_error_message`, which
is a defense-in-depth scrub (length-capped, single-line, control-chars
stripped) on top of the fact that the runtime-error feed is already
content-free by construction.

The renderer is a **pure function** of an already-gathered ``data`` dict so it
is unit-testable with no server, no models, and no hardware. ``server.py``
supplies the live data via :func:`server.gather_support_report`.
"""
from __future__ import annotations

# Header line every report carries, so a pasted report is self-labelling about
# what it does and does not contain.
PRIVACY_NOTE = "Contains no transcription content — hardware, versions, model state, redacted errors, and paths only."

_MAX_ERROR_MESSAGE_CHARS = 300
_MAX_ERRORS = 15


def redact_error_message(message) -> str:
    """Defense-in-depth scrub for an error string bound for a shareable report.

    The runtime-error feed is already content-free by construction, but a report
    the user pastes in public warrants belt-and-suspenders: collapse to a single
    line, strip control characters, and cap length so nothing large or
    multi-line can ride along unnoticed.
    """
    if message is None:
        return ""
    text = str(message)
    # Collapse any newlines/tabs/control chars to single spaces.
    text = "".join(" " if (ch < " " or ch == "\x7f") else ch for ch in text)
    text = " ".join(text.split())
    if len(text) > _MAX_ERROR_MESSAGE_CHARS:
        text = text[:_MAX_ERROR_MESSAGE_CHARS].rstrip() + "…"
    return text


def _fmt_mb(value) -> str:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return "unknown"
    return f"{n:,} MB"


def _bullet(label, value) -> str:
    return f"- **{label}:** {value}"


def _section(title, lines) -> str:
    body = "\n".join(lines) if lines else "- _(none)_"
    return f"## {title}\n{body}"


def _render_version(data) -> str:
    v = data.get("version") or {}
    lines = [
        _bullet("App / backend", v.get("backend_version", "unknown")),
        _bullet("Config schema", f"profile v{v.get('profile_schema_version', '?')} · app-state v{v.get('config_version', '?')}"),
    ]
    return _section("Version", lines)


def _render_platform(data) -> str:
    p = data.get("platform") or {}
    lines = [
        _bullet("OS", f"{p.get('system', 'unknown')} {p.get('release', '')}".strip()),
        _bullet("Python", p.get("python", "unknown")),
        _bullet("Hardware tier", data.get("hardware_tier", "unknown")),
    ]
    return _section("Platform", lines)


def _render_hardware(data) -> str:
    hw = data.get("hardware") or {}
    cpu = hw.get("cpu") or {}
    mem = hw.get("memory") or {}
    gpu = hw.get("gpu") or {}
    disk = hw.get("disk") or {}

    cores = cpu.get("physical_cores")
    threads = cpu.get("logical_threads")
    cpu_line = cpu.get("model", "unknown")
    if cores or threads:
        cpu_line = f"{cpu_line} — {cores or '?'} cores / {threads or '?'} threads"

    gpu_present = bool(
        gpu.get("accelerated")
        or gpu.get("available")
        or (gpu.get("kind") not in (None, "", "none"))
    )
    if gpu_present:
        parts = [gpu.get("name") or gpu.get("kind") or "GPU"]
        backend = gpu.get("backend")
        kind = gpu.get("kind")
        tag = "/".join(x for x in (backend, kind) if x)
        if tag:
            parts.append(f"({tag})")
        if gpu.get("vram_mb"):
            parts.append(f"{_fmt_mb(gpu['vram_mb'])} VRAM")
        gpu_line = " ".join(parts)
        gpu_line += f" — accelerated: {'yes' if gpu.get('accelerated') else 'no'}"
    else:
        gpu_line = "none detected (CPU only)"

    lines = [
        _bullet("CPU", cpu_line),
        _bullet("RAM", f"{_fmt_mb(mem.get('total_mb'))} total, {_fmt_mb(mem.get('available_mb'))} available"),
        _bullet("GPU", gpu_line),
        _bullet("Models disk free", _fmt_mb(disk.get("free_mb"))),
    ]
    return _section("Hardware", lines)


def _render_runtime(data) -> str:
    rt = data.get("runtime") or {}
    llm = rt.get("llm") or {}
    stt = rt.get("stt") or {}
    tts = rt.get("tts") or {}

    llm_line = llm.get("runtime_status", "unknown")
    if llm.get("runtime_build") is not None:
        req = llm.get("required_runtime_build")
        llm_line += f" — build {llm['runtime_build']}"
        if req:
            llm_line += f" (requires ≥ {req})"
    if llm.get("last_error"):
        llm_line += f" · last error: {redact_error_message(llm['last_error'])}"

    stt_line = "loaded" if stt.get("loaded") else ("initialized" if stt.get("initialized") else "not loaded")
    if stt.get("model_size"):
        stt_line += f" ({stt['model_size']}{', ' + stt['device'] if stt.get('device') else ''})"

    tts_line = tts.get("backend", "none")
    if tts.get("loaded"):
        tts_line += " (loaded)"
    elif tts.get("initialized"):
        tts_line += " (initialized)"
    else:
        tts_line += " (not loaded)"

    lines = [
        _bullet("LLM (llama-server)", llm_line),
        _bullet("STT (whisper)", stt_line),
        _bullet("TTS", tts_line),
    ]
    return _section("Runtime validation", lines)


def _render_loaded_models(data) -> str:
    res = data.get("resources") or {}
    ledger = res.get("ledger") or {}
    lines = []
    for component, entry in ledger.items():
        if not entry:
            continue
        model_id = entry.get("model_id") or "unknown"
        piece = f"- **{component}:** {model_id} (~{_fmt_mb(entry.get('estimated_mb'))}"
        if entry.get("pinned"):
            piece += ", pinned"
        piece += ")"
        lines.append(piece)
    if not lines:
        lines = ["- _(no models resident)_"]
    if res.get("available_mb") is not None:
        lines.append(_bullet("Available headroom", f"{_fmt_mb(res.get('available_mb'))} (floor {_fmt_mb(res.get('ram_floor_mb'))})"))
    return _section("Loaded models (resident)", lines)


def _render_errors(data) -> str:
    errors = data.get("recent_errors") or []
    lines = []
    for row in errors[-_MAX_ERRORS:]:
        sev = str(row.get("severity", "info"))
        comp = str(row.get("component", "runtime"))
        when = str(row.get("created_at", ""))
        msg = redact_error_message(row.get("message", ""))
        lines.append(f"- `[{sev}]` {when} · **{comp}**: {msg}")
    return _section("Recent errors (redacted)", lines)


def _render_paths(data) -> str:
    paths = data.get("paths") or {}
    def mark(key, exists_key=None):
        val = paths.get(key, "")
        if exists_key is not None:
            val = f"{val} {'✓' if paths.get(exists_key) else '✗ (missing)'}"
        return val
    lines = [
        _bullet("App data", paths.get("app_data_dir", "")),
        _bullet("Config", paths.get("config_dir", "")),
        _bullet("Models", paths.get("models_dir", "")),
        _bullet("Debug log", paths.get("debug_log_path", "")),
        _bullet("llama-server", mark("llama_server_path", "llama_server_exists")),
        _bullet("Default model", mark("default_model_path", "default_model_exists")),
    ]
    return _section("Paths", lines)


def render_support_report(data) -> str:
    """Render the full Markdown support report from an already-gathered ``data``
    dict (see :func:`server.gather_support_report` for the live producer)."""
    data = data or {}
    generated = data.get("generated_at", "")
    header = [
        "# BetterFingers Support Report",
        "",
        f"_{PRIVACY_NOTE}_",
    ]
    if generated:
        header.append(f"_Generated {generated}_")
    header.append("")

    sections = [
        _render_version(data),
        _render_platform(data),
        _render_hardware(data),
        _render_runtime(data),
        _render_loaded_models(data),
        _render_errors(data),
        _render_paths(data),
    ]
    return "\n".join(header) + "\n\n".join(sections) + "\n"
