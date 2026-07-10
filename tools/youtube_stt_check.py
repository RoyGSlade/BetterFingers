"""End-to-end STT accuracy check against real YouTube audio (§6.1 / C9).

Uses a YouTube video as both the audio source *and* the ground truth: it fetches
the video's captions (preferring human-authored subtitles over auto-captions),
runs the audio through the same faster-whisper model BetterFingers uses, and
scores the result against the captions with the repo's `wer.py`. This finally
gives the golden-audio suite real audio to regress against.

The whole path is ffmpeg-free: PyAV (bundled with faster-whisper) decodes the
downloaded audio, and Whisper takes the numpy array directly.

Requires a current `yt-dlp` (distro packages are often too stale for YouTube's
API — grab the standalone binary if downloads fail with HTTP 400).

Usage:
    python3 tools/youtube_stt_check.py --url https://youtu.be/iG9CE55wbtY
    python3 tools/youtube_stt_check.py --url URL --window 120 --model small.en --json out.json
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import wer

_TS = re.compile(r"(\d\d):(\d\d):(\d\d)[.,](\d+)\s*-->")
_TAG = re.compile(r"<[^>]+>")
# Caption stage-directions that aren't spoken — (Laughter), [Music], ♪…♪ — so
# they don't unfairly count against the transcriber.
_ANNOTATION = re.compile(r"\([^)]*\)|\[[^\]]*\]|♪[^♪]*♪")


def _clean_caption_line(line: str) -> str:
    line = _TAG.sub("", line)
    line = _ANNOTATION.sub(" ", line)
    return line


def vtt_reference(path: str, max_start_s: float) -> str:
    """Flatten a WebVTT file to plain text for cues starting before max_start_s."""
    out, keep, prev = [], True, None
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        m = _TS.search(line)
        if m:
            h, mm, s, _frac = m.groups()
            keep = (int(h) * 3600 + int(mm) * 60 + int(s)) < max_start_s
            continue
        if not line or line.startswith(("WEBVTT", "Kind:", "Language:")) or line.strip().isdigit():
            continue
        if keep:
            cleaned = _clean_caption_line(line).strip()
            # Auto-captions repeat lines across cues; drop consecutive dupes.
            if cleaned and cleaned != prev:
                out.append(cleaned)
                prev = cleaned
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def fetch(url: str, workdir: str, ytdlp: str) -> tuple:
    """Download bestaudio + English captions (manual preferred, else auto).
    Returns (audio_path, vtt_path). Raises on failure."""
    audio_tmpl = os.path.join(workdir, "audio.%(ext)s")
    base = [ytdlp, "-f", "bestaudio", "-o", audio_tmpl, "--sub-lang", "en", "--sub-format", "vtt"]
    # Try human subtitles first, then automatic captions.
    for sub_flag in ("--write-sub", "--write-auto-sub"):
        for f in os.listdir(workdir):
            os.remove(os.path.join(workdir, f))
        subprocess.run(base + [sub_flag, url], check=False, capture_output=True, timeout=300)
        audio = next((os.path.join(workdir, f) for f in os.listdir(workdir) if f.startswith("audio.") and not f.endswith(".vtt")), None)
        vtt = next((os.path.join(workdir, f) for f in os.listdir(workdir) if f.endswith(".vtt")), None)
        if audio and vtt:
            return audio, vtt
    raise RuntimeError("could not fetch both audio and English captions (try a captioned video / newer yt-dlp)")


def run(url: str, window_s: float, model_name: str, ytdlp: str) -> dict:
    from faster_whisper import WhisperModel, decode_audio

    with tempfile.TemporaryDirectory() as workdir:
        audio_path, vtt_path = fetch(url, workdir, ytdlp)
        pcm = np.asarray(decode_audio(audio_path, sampling_rate=16000), dtype=np.float32)
        clip = pcm[: int(window_s * 16000)]
        reference = vtt_reference(vtt_path, window_s)

        t0 = time.time()
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _info = model.transcribe(clip, language="en", beam_size=1)
        hypothesis = " ".join(s.text.strip() for s in segments).strip()
        elapsed = time.time() - t0

    result = wer.compare_transcripts(reference, hypothesis)
    return {
        "url": url,
        "window_s": window_s,
        "model": model_name,
        "audio_seconds": round(len(clip) / 16000, 1),
        "transcribe_seconds": round(elapsed, 1),
        "wer": result["wer"],
        "substitutions": result["substitutions"],
        "deletions": result["deletions"],
        "insertions": result["insertions"],
        "ref_words": result["ref_words"],
        "reference": reference,
        "hypothesis": hypothesis,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="STT accuracy check against real YouTube audio (§6.1 / C9).")
    parser.add_argument("--url", required=True, help="YouTube URL (must have English captions).")
    parser.add_argument("--window", type=float, default=90.0, help="Seconds of audio to transcribe/compare.")
    parser.add_argument("--model", default="base.en", help="faster-whisper model (base.en, small.en, ...).")
    parser.add_argument("--ytdlp", default="yt-dlp", help="Path to a current yt-dlp binary.")
    parser.add_argument("--json", dest="json_path", default="")
    args = parser.parse_args(argv)

    report = run(args.url, args.window, args.model, args.ytdlp)
    print(f"\n--- REFERENCE (YouTube captions) ---\n{report['reference'][:800]}")
    print(f"\n--- HYPOTHESIS ({args.model}) ---\n{report['hypothesis'][:800]}")
    print(
        f"\n=== WER {report['wer'] * 100:.1f}%  "
        f"(sub {report['substitutions']} del {report['deletions']} ins {report['insertions']} "
        f"/ {report['ref_words']} words · {report['audio_seconds']}s audio in {report['transcribe_seconds']}s) ==="
    )
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"Wrote {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
