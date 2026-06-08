#!/usr/bin/env python3
"""Generate a score cue with ACE-Step 1.5.

Run through the isolated ACE-Step tool environment. The script points ACE-Step
at the already-downloaded BetterFingers model snapshot by symlinking it as the
tool repo's ``checkpoints`` directory when needed.
"""

from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def _ensure_checkpoints(project_root: Path, checkpoint_dir: Path) -> None:
    target = project_root / "checkpoints"
    if target.exists():
        return
    try:
        target.symlink_to(checkpoint_dir, target_is_directory=True)
    except OSError:
        shutil.copytree(checkpoint_dir, target)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool-root", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--seed", type=int, default=-1)
    parser.add_argument("--steps", type=int, default=8)
    parser.add_argument("--guidance-scale", type=float, default=7.0)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--lm-backend", default="pt")
    parser.add_argument("--config-path", default="acestep-v15-turbo")
    parser.add_argument("--lm-model-path", default="acestep-5Hz-lm-1.7B")
    args = parser.parse_args()

    from acestep.handler import AceStepHandler
    from acestep.inference import GenerationConfig, GenerationParams, generate_music
    from acestep.llm_inference import LLMHandler

    tool_root = Path(args.tool_root).resolve()
    checkpoint_dir = Path(args.checkpoint_dir).resolve()
    _ensure_checkpoints(tool_root, checkpoint_dir)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    dit_handler = AceStepHandler()
    dit_handler.initialize_service(
        project_root=str(tool_root),
        config_path=args.config_path,
        device=args.device,
    )

    llm_handler = LLMHandler()
    llm_handler.initialize(
        checkpoint_dir=str(checkpoint_dir),
        lm_model_path=args.lm_model_path,
        backend=args.lm_backend,
        device=args.device,
    )

    params = GenerationParams(
        caption=args.prompt,
        lyrics="",
        instrumental=True,
        duration=float(args.duration),
        inference_steps=max(1, int(args.steps)),
        guidance_scale=float(args.guidance_scale),
        seed=int(args.seed),
    )
    config = GenerationConfig(batch_size=1, audio_format="wav")
    result = generate_music(dit_handler, llm_handler, params, config, save_dir=str(out_dir))
    if not result.success or not result.audios:
        raise RuntimeError(result.error or "ACE-Step did not return an audio file.")

    src = Path(result.audios[0]["path"])
    final = out_dir / "music.wav"
    if src.resolve() != final.resolve():
        shutil.copy2(src, final)
    return 0 if final.is_file() and os.path.getsize(final) > 44 else 1


if __name__ == "__main__":
    raise SystemExit(main())
