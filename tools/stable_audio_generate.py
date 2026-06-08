#!/usr/bin/env python3
"""Generate a short ambience/SFX clip with Stable Audio Open Small.

This script is run by BetterFingers through the isolated Stable Audio Tools
environment in ``.betterfingers/tools/stable-audio-tools/.venv``. Keeping it as
a subprocess avoids importing Stable Audio's Torch stack into the main app.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def _model_ckpt(model_dir: Path) -> Path:
    for name in ("model.safetensors", "model.ckpt"):
        p = model_dir / name
        if p.is_file():
            return p
    raise FileNotFoundError(f"No Stable Audio checkpoint found in {model_dir}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--seconds", type=float, default=11.0)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--cfg-scale", type=float, default=1.0)
    parser.add_argument("--sampler", default="pingpong")
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    import torch
    import torchaudio
    from einops import rearrange
    from stable_audio_tools.inference.generation import generate_diffusion_cond
    from stable_audio_tools.models.factory import create_model_from_config
    from stable_audio_tools.models.utils import load_ckpt_state_dict

    model_dir = Path(args.model_dir)
    config_path = model_dir / "model_config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing Stable Audio model_config.json in {model_dir}")

    with config_path.open("r", encoding="utf-8") as f:
        model_config = json.load(f)

    device = args.device
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if args.seed >= 0:
        torch.manual_seed(args.seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(args.seed)

    model = create_model_from_config(model_config)
    state = load_ckpt_state_dict(str(_model_ckpt(model_dir)))
    model.load_state_dict(state)
    model = model.to(device).eval()

    sample_rate = int(model_config["sample_rate"])
    # Stable Audio Open Small is trained for up to about 11 seconds. Generate
    # at the native sample size and trim shorter clips after decoding.
    sample_size = int(model_config["sample_size"])
    seconds = max(0.5, min(float(args.seconds), 11.0))
    conditioning = [{"prompt": args.prompt, "seconds_total": seconds}]

    with torch.inference_mode():
        output = generate_diffusion_cond(
            model,
            steps=max(1, int(args.steps)),
            cfg_scale=float(args.cfg_scale),
            conditioning=conditioning,
            sample_size=sample_size,
            sampler_type=args.sampler,
            device=device,
        )

    output = rearrange(output, "b d n -> d (b n)")
    target_samples = max(1, int(seconds * sample_rate))
    output = output[:, :target_samples]
    peak = torch.max(torch.abs(output)).clamp(min=1e-8)
    output = output.to(torch.float32).div(peak).clamp(-1, 1).cpu()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out_path), output, sample_rate)
    return 0 if out_path.is_file() and os.path.getsize(out_path) > 44 else 1


if __name__ == "__main__":
    raise SystemExit(main())
