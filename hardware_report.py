"""
Hardware reporting and model-fit assessment.

Surfaces real machine specs (CPU / RAM / swap / disk / GPU) and evaluates
whether the currently selected LLM is a realistic fit for this hardware, so the
Diagnostics UI can warn the user *before* they sit through a slow or swapping run.
"""

import platform as platform_module
import shutil
import subprocess
import logging

try:
    import psutil
except Exception:  # pragma: no cover - psutil is a hard dependency in practice
    psutil = None

from model_manager import AVAILABLE_MODELS, DEFAULT_MODEL, get_models_dir


# Heuristics for estimating llama.cpp CPU runtime memory from the GGUF size.
# Loaded weights sit slightly above the file size, plus KV cache (~4k ctx) and
# server overhead. These are deliberately conservative round numbers.
_RUNTIME_OVERHEAD_MB = 750
_RUNTIME_WEIGHT_FACTOR = 1.15

# Stated minimum tier from DESIGN.md §12 (hardware tiers).
_MIN_LOGICAL_THREADS = 12
_MIN_PHYSICAL_CORES = 6


def _cpu_model_name():
    """Best-effort human-readable CPU name across platforms."""
    try:
        if platform_module.system().lower() == "linux":
            with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    if line.lower().startswith("model name"):
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform_module.processor() or platform_module.machine() or "Unknown CPU"


def _detect_gpu():
    """Best-effort GPU detection. Reports CUDA VRAM when nvidia-smi is present."""
    info = {"kind": "none", "name": None, "vram_mb": None, "accelerated": False}

    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            result = subprocess.run(
                [smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
            first = (result.stdout or "").strip().splitlines()
            if first:
                name, _, vram = first[0].partition(",")
                info.update(
                    kind="cuda",
                    name=name.strip() or "NVIDIA GPU",
                    vram_mb=int(float(vram.strip())) if vram.strip() else None,
                    accelerated=True,
                )
                return info
        except Exception as exc:  # pragma: no cover - environment dependent
            logging.debug("nvidia-smi probe failed: %s", exc)

    # No CUDA device. Note integrated graphics on Linux for context, but it does
    # not provide usable acceleration for the llama.cpp CPU build we ship.
    try:
        if platform_module.system().lower() == "linux" and shutil.which("lspci"):
            result = subprocess.run(
                ["lspci"], check=False, capture_output=True, text=True, timeout=5
            )
            for line in (result.stdout or "").splitlines():
                low = line.lower()
                if "vga compatible controller" in low or " 3d controller" in low:
                    # lspci lines look like "00:02.0 VGA compatible controller: <name>".
                    name = line.split("controller:", 1)[-1].strip() if "controller:" in low else line
                    info["name"] = name or line.strip()
                    info["kind"] = "integrated"
                    break
    except Exception as exc:  # pragma: no cover - environment dependent
        logging.debug("lspci probe failed: %s", exc)

    return info


def get_hardware_report():
    """Returns a snapshot of real machine specs for the Diagnostics UI."""
    report = {
        "available": psutil is not None,
        "cpu": {"model": _cpu_model_name()},
        "memory": {},
        "swap": {},
        "disk": {},
        "gpu": _detect_gpu(),
    }

    if psutil is None:
        report["error"] = "psutil is not installed; hardware metrics are unavailable."
        return report

    try:
        report["cpu"].update(
            physical_cores=psutil.cpu_count(logical=False) or 0,
            logical_threads=psutil.cpu_count(logical=True) or 0,
        )
    except Exception as exc:
        report["cpu"]["error"] = str(exc)

    try:
        vm = psutil.virtual_memory()
        report["memory"] = {
            "total_mb": round(vm.total / (1024 * 1024)),
            "available_mb": round(vm.available / (1024 * 1024)),
            "used_percent": vm.percent,
        }
    except Exception as exc:
        report["memory"]["error"] = str(exc)

    try:
        sw = psutil.swap_memory()
        report["swap"] = {
            "total_mb": round(sw.total / (1024 * 1024)),
            "used_mb": round(sw.used / (1024 * 1024)),
            "used_percent": sw.percent,
        }
    except Exception as exc:
        report["swap"]["error"] = str(exc)

    try:
        usage = shutil.disk_usage(get_models_dir())
        report["disk"] = {
            "models_dir": get_models_dir(),
            "free_mb": round(usage.free / (1024 * 1024)),
            "total_mb": round(usage.total / (1024 * 1024)),
        }
    except Exception as exc:
        report["disk"]["error"] = str(exc)

    return report


def _estimate_runtime_mb(size_mb):
    return round(size_mb * _RUNTIME_WEIGHT_FACTOR + _RUNTIME_OVERHEAD_MB)


def assess_model_fit(model_id=None, report=None):
    """
    Compares the selected model's memory footprint against this machine.

    Returns a dict with a coarse verdict (good / tight / insufficient / unknown),
    human-readable reasons, and a recommendation the UI can surface verbatim.
    """
    if report is None:
        report = get_hardware_report()

    key = model_id if model_id in AVAILABLE_MODELS else DEFAULT_MODEL
    meta = AVAILABLE_MODELS.get(key, {})
    size_mb = int(meta.get("size_mb", 0) or 0)
    need_mb = _estimate_runtime_mb(size_mb) if size_mb else 0

    fit = {
        "model_id": key,
        "model_name": meta.get("name", key),
        "model_size_mb": size_mb,
        "estimated_runtime_mb": need_mb,
        "verdict": "unknown",
        "reasons": [],
        "recommendation": "",
    }

    mem = report.get("memory") or {}
    total_mb = mem.get("total_mb")
    available_mb = mem.get("available_mb")
    cpu = report.get("cpu") or {}
    gpu = report.get("gpu") or {}
    disk = report.get("disk") or {}

    if not report.get("available") or total_mb is None or not need_mb:
        fit["recommendation"] = "Hardware metrics unavailable; cannot assess model fit."
        return fit

    reasons = []

    # --- Memory: the decisive factor for CPU inference. ---
    if need_mb > total_mb * 0.95:
        fit["verdict"] = "insufficient"
        reasons.append(
            f"Needs ~{need_mb} MB but the machine only has {total_mb} MB of RAM total."
        )
    elif available_mb is not None and need_mb > available_mb:
        fit["verdict"] = "tight"
        reasons.append(
            f"Needs ~{need_mb} MB; only {available_mb} MB is free right now "
            f"(of {total_mb} MB). Expect swapping unless other apps are closed."
        )
    else:
        fit["verdict"] = "good"
        reasons.append(f"Fits comfortably: ~{need_mb} MB needed of {total_mb} MB.")

    # --- Swap pressure. Informational always; only downgrades a "good" verdict
    # when loading the model would itself consume most of the free RAM, since a
    # small model that fits free RAM won't actually force more swapping.
    swap = report.get("swap") or {}
    if swap.get("used_percent", 0) >= 80 and swap.get("total_mb", 0) > 0:
        reasons.append(
            f"Swap is {swap['used_percent']:.0f}% full — the system is already under memory pressure."
        )
        if fit["verdict"] == "good" and available_mb and need_mb > available_mb * 0.85:
            fit["verdict"] = "tight"

    # --- CPU: below the stated minimum tier means slow, not broken. ---
    logical = cpu.get("logical_threads") or 0
    physical = cpu.get("physical_cores") or 0
    if logical and (logical < _MIN_LOGICAL_THREADS or physical < _MIN_PHYSICAL_CORES):
        reasons.append(
            f"CPU has {physical} cores / {logical} threads, under the recommended "
            f"{_MIN_PHYSICAL_CORES} cores / {_MIN_LOGICAL_THREADS} threads — generation will be slow."
        )

    # --- GPU acceleration availability. ---
    if not gpu.get("accelerated"):
        reasons.append(
            "No CUDA GPU detected; inference runs CPU-only (the --n-gpu-layers setting has no effect)."
        )

    # --- Disk headroom for the model download. ---
    free_mb = disk.get("free_mb")
    if free_mb is not None and size_mb and free_mb < size_mb * 1.1:
        reasons.append(f"Low disk: {free_mb} MB free for a {size_mb} MB model download.")

    fit["reasons"] = reasons

    # --- Recommendation text. ---
    if fit["verdict"] == "insufficient":
        smaller = _suggest_lighter_model(key, total_mb)
        fit["recommendation"] = (
            f"This model is too large for {total_mb} MB of RAM. "
            + (f"Try {smaller} instead." if smaller else "Choose a smaller quantized model.")
        )
    elif fit["verdict"] == "tight":
        smaller = _suggest_lighter_model(key, available_mb or total_mb)
        fit["recommendation"] = (
            "Workable but close to the limit. Close other apps before running, "
            + (f"or switch to a lighter model like {smaller} for more headroom."
               if smaller else "or pick a smaller quantization.")
        )
    else:
        fit["recommendation"] = "This model is a good fit for your hardware."

    return fit


def _suggest_lighter_model(current_id, budget_mb):
    """
    Pick the largest model that is both smaller than the current one and fits the
    given RAM budget — i.e. the most capable model that still frees up headroom.
    """
    if not budget_mb:
        return None
    current_size = int(AVAILABLE_MODELS.get(current_id, {}).get("size_mb", 0) or 0)
    fitting = []
    for mid, meta in AVAILABLE_MODELS.items():
        size = int(meta.get("size_mb", 0) or 0)
        if mid == current_id or not size:
            continue
        if current_size and size >= current_size:
            continue  # only suggest something genuinely lighter
        if _estimate_runtime_mb(size) <= budget_mb * 0.9:
            fitting.append((mid, size))
    if not fitting:
        return None
    best = max(fitting, key=lambda item: item[1])
    return AVAILABLE_MODELS[best[0]].get("name", best[0])


# --- Hardware capability tier (U2) ---

TIER_ORDER = ["cpu-only", "igpu", "dgpu-8g", "dgpu-12g+"]


def classify_tier(ram_mb=0, vram_mb=None, gpu_kind=None, cores=None):
    """Map hardware into a coarse capability tier with plain-language guidance.

    Pure function of primitives so it is unit-testable without any GPU present.
    """
    ram_mb = int(ram_mb or 0)
    vram = int(vram_mb) if vram_mb else 0
    kind = (gpu_kind or "none").lower()

    if kind == "discrete" and vram >= 12000:
        tier = "dgpu-12g+"
        label = "Dedicated GPU (12 GB+)"
        guidance = "You can run large local models (12B–31B) with GPU acceleration."
    elif kind == "discrete" and vram >= 8000:
        tier = "dgpu-8g"
        label = "Dedicated GPU (8 GB)"
        guidance = "Run up to ~12B models comfortably; larger ones with CPU offload."
    elif kind == "discrete":
        tier = "dgpu-8g"
        label = "Dedicated GPU"
        guidance = "A dedicated GPU is present; 4B–12B models should run well."
    elif kind == "integrated":
        tier = "igpu"
        label = "Integrated GPU"
        guidance = "Integrated graphics can modestly accelerate small models via Vulkan; a 4B Q4 model is the sweet spot."
    else:
        tier = "cpu-only"
        label = "CPU only"
        guidance = "No GPU acceleration detected. Stick to small models (4B Q4, Whisper base/small); expect a few seconds per utterance."

    warnings = []
    if ram_mb and ram_mb < 8000:
        warnings.append("Under 8 GB RAM — use the smallest models and keep other apps closed.")
    elif ram_mb and ram_mb < 16000 and tier in ("cpu-only", "igpu"):
        warnings.append("~8–16 GB RAM — a 4B Q4 model fits; avoid 12B+ on CPU.")

    return {
        "tier": tier,
        "label": label,
        "guidance": guidance,
        "warnings": warnings,
        "ram_mb": ram_mb or None,
        "vram_mb": vram or None,
        "gpu_kind": kind,
        "cores": int(cores) if cores else None,
    }


def get_hardware_tier(report=None):
    """Classify the current machine (or a supplied report) into a capability tier."""
    if report is None:
        report = get_hardware_report()
    mem = report.get("memory") or {}
    gpu = report.get("gpu") or {}
    cpu = report.get("cpu") or {}
    return classify_tier(
        ram_mb=mem.get("total_mb") or 0,
        vram_mb=gpu.get("vram_mb"),
        gpu_kind=gpu.get("kind"),
        cores=cpu.get("physical_cores"),
    )
