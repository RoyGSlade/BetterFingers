# BetterFingers Hardware Guidance

## Minimum Tier
- CPU: 6 cores / 12 threads
- RAM: 16 GB
- GPU: Optional (CPU-only supported)
- Recommended models: Gemma 4B Q4, Whisper `base.en`

## Recommended Tier
- CPU: 8 cores / 16 threads
- RAM: 32 GB
- GPU: NVIDIA RTX 3060 12 GB or better
- Recommended models: Gemma 4B Q6/Q8, Whisper `small.en` or `medium.en`

## High-Performance Tier
- CPU: 12+ cores
- RAM: 64 GB
- GPU: NVIDIA RTX 4080/4090 class
- Recommended models: Gemma 12B variants, Whisper `large-v3`

## Notes
- Disable model keep-loaded settings on low-memory systems to reduce baseline RAM/VRAM use.
- Use `tools/performance_benchmark.py` to produce machine-local measurements before selecting larger models.
