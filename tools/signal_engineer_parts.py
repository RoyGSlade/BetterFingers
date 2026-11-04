"""Cut Signal Engineer face parts out of a parts-atlas PNG.

Hybrid build: the metal of each part stays pixel-identical to the painted
atlas, and every light (cyan strips, amber arcs, brow bars) is redrawn as a
live vector by ``app/src/renderer/lib/signalEngineerFace.mjs``. This tool does
the raster half:

1. crop each part's ``box`` from the atlas;
2. give it an alpha channel from the traced ``mask`` (polygons with holes, or a
   circle), rasterised at 4x and downsampled so edges are antialiased;
3. scrub the baked lights under each ``leds`` entry: inside a widened stroke of
   that path, saturated (lit) pixels are pulled to the dark channel colour and
   their coloured glow is desaturated, so the vector LED drawn on top owns the
   colour and can change it.

Both halves read the same spec (``standard.parts.json``), so masks, scrubbed
areas and vector lights cannot drift apart.

Usage::

    .venv/Scripts/python.exe tools/signal_engineer_parts.py \
        --atlas "%USERPROFILE%/Downloads/Signal Engineer Robot Face Parts Atlas.png"

Defaults to the standard spec and writes ``<part>.png`` next to it. The atlas
is the owner's source art and is not stored in the repository.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SPEC = REPO / "app" / "src" / "renderer" / "assets" / "signal-engineer" / "standard.parts.json"

SUPERSAMPLE = 4
SCRUB_PAD = 7  # extra px of stroke width around an LED path that may hold its glow
CHANNEL_RGB = np.array([13.0, 15.0, 18.0])


def chaikin(points: list[list[float]], iterations: int) -> list[tuple[float, float]]:
    pts = [tuple(p) for p in points]
    for _ in range(iterations):
        out = []
        n = len(pts)
        for i in range(n):
            (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = out
    return pts


def part_mask(mask: dict, box: list[int]) -> Image.Image:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    s = SUPERSAMPLE
    img = Image.new("L", (w * s, h * s), 0)
    d = ImageDraw.Draw(img)

    def local(pts):
        return [((x - x0) * s, (y - y0) * s) for x, y in pts]

    smooth = int(mask.get("smooth", 0))
    if "circle" in mask:
        cx, cy, r = mask["circle"]
        d.ellipse([((cx - r) - x0) * s, ((cy - r) - y0) * s, ((cx + r) - x0) * s, ((cy + r) - y0) * s], fill=255)
    for poly in mask.get("polys", []):
        d.polygon(local(chaikin(poly, smooth) if smooth else poly), fill=255)
    for hole in mask.get("holes", []):
        d.polygon(local(chaikin(hole, smooth) if smooth else hole), fill=0)
    return img.resize((w, h), Image.LANCZOS)


def _box(arr: np.ndarray, r: int, axis: int) -> np.ndarray:
    pad = [(0, 0)] * arr.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(arr, pad, mode="edge"), axis=axis)
    hi = np.take(c, np.arange(2 * r + 1, c.shape[axis]), axis=axis)
    lo = np.take(c, np.arange(0, c.shape[axis] - 2 * r - 1), axis=axis)
    return (hi - lo) / (2 * r + 1)


def _blur(arr: np.ndarray, radius: float) -> np.ndarray:
    """Gaussian-ish blur (three box passes); Pillow cannot blur float images."""
    r = max(1, int(round(radius * 0.8)))
    out = arr.astype(np.float64)
    for _ in range(3):
        out = _box(_box(out, r, 0), r, 1)
    return out


def refine_alpha(rgb: np.ndarray, alpha: np.ndarray, band: int) -> np.ndarray:
    """Re-decide a hand-traced edge from the pixels themselves.

    Inside the traced shape minus ``band`` px is kept, outside plus ``band`` px
    is background; in the band between, a pixel stays only if its colour is
    far from the local background colour (estimated from nearby sure-background
    pixels). Lets a trace be a few px off on ragged art (rust, copper wire).
    """
    hard = Image.fromarray(((alpha > 0.5) * 255).astype(np.uint8), "L")
    size = 2 * band + 1
    sure_fg = np.asarray(hard.filter(ImageFilter.MinFilter(size)), dtype=np.float64) / 255.0
    near = np.asarray(hard.filter(ImageFilter.MaxFilter(size)), dtype=np.float64) / 255.0
    sure_bg = 1.0 - near
    radius = band * 2.0
    weight = _blur(sure_bg, radius)
    bg = np.stack([_blur(rgb[..., c] * sure_bg, radius) for c in range(3)], axis=2) / np.maximum(weight, 1e-6)[..., None]
    dist = np.sqrt(((rgb - bg) ** 2).sum(axis=2))
    fg_prob = np.clip((dist - 16.0) / 22.0, 0, 1)
    fg_prob[weight < 1e-3] = 1.0  # no background nearby to compare against: trust the trace
    band_mask = near * (1.0 - sure_fg)
    out = sure_fg + band_mask * fg_prob
    out = _blur(out, 0.6)
    return np.clip(out, 0, 1) * near


def led_zone(leds: list[dict], box: list[int]) -> Image.Image:
    """Where baked light may be: each LED path stroked wider than the LED."""
    x0, y0, x1, y1 = box
    img = Image.new("L", (x1 - x0, y1 - y0), 0)
    d = ImageDraw.Draw(img)
    for led in leds:
        width = int(round(led["w"] + 2 * led.get("pad", SCRUB_PAD)))
        if led["kind"] == "line":
            pts = [(x - x0, y - y0) for x, y in led["pts"]]
            d.line(pts, fill=255, width=width, joint="curve")
            for x, y in pts:  # round caps
                d.ellipse([x - width / 2, y - width / 2, x + width / 2, y + width / 2], fill=255)
        elif led["kind"] == "arc":
            cx, cy = led["c"]
            r = led["r"] + width / 2
            bbox = [cx - r - x0, cy - r - y0, cx + r - x0, cy + r - y0]
            a0, a1 = led["a0"], led["a1"]
            if (a1 - a0) % 360 == 0:
                d.ellipse(bbox, outline=255, width=width)
            else:
                d.arc(bbox, a0 - 6, a1 + 6, fill=255, width=width)
        else:
            raise ValueError(f"unknown led kind {led['kind']!r}")
    return img.filter(ImageFilter.GaussianBlur(1.5))


def scrub_lights(rgb: np.ndarray, zone: np.ndarray) -> np.ndarray:
    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0.0)
    lum = rgb @ np.array([0.2126, 0.7152, 0.0722])
    gray = np.repeat(lum[..., None], 3, axis=2)
    # The LED core is saturated: pull it to the dark channel. Its halo on the
    # metal is mildly tinted: keep its brightness, drop the colour.
    core = np.clip((sat - 0.28) / 0.3, 0, 1)[..., None]
    cleaned = gray * (1 - core) + CHANNEL_RGB * core
    halo_dim = np.clip((sat - 0.12) / 0.3, 0, 1)[..., None] * 0.35
    cleaned = cleaned * (1 - halo_dim) + CHANNEL_RGB * halo_dim
    z = zone[..., None]
    return rgb * (1 - z) + cleaned * z


def build(spec_path: Path, atlas_path: Path, out_dir: Path) -> list[Path]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    atlas = Image.open(atlas_path).convert("RGB")
    if list(atlas.size) != spec["atlasSize"]:
        raise SystemExit(f"atlas is {atlas.size}, spec expects {spec['atlasSize']}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, part in spec["parts"].items():
        box = part["box"]
        raw = np.asarray(atlas.crop(tuple(box)), dtype=np.float64)
        rgb = raw
        leds = part.get("leds", [])
        if leds:
            zone = np.asarray(led_zone(leds, box), dtype=np.float64) / 255.0
            rgb = scrub_lights(rgb, zone)
        alpha = part_mask(part["mask"], box)
        band = int(part["mask"].get("refine", 0))
        if band:
            a = refine_alpha(raw, np.asarray(alpha, dtype=np.float64) / 255.0, band)
            alpha = Image.fromarray((a * 255).astype(np.uint8), "L")
        img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
        img.putalpha(alpha)
        path = out_dir / f"{name}.png"
        img.save(path, optimize=True)
        written.append(path)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--atlas", required=True, type=Path, help="parts atlas PNG (1536x1024)")
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: next to the spec)")
    args = ap.parse_args()
    spec_dir = json.loads(args.spec.read_text(encoding="utf-8")).get("partsDir", ".")
    out = args.out or (args.spec.parent / spec_dir)
    for path in build(args.spec, args.atlas, out):
        print(f"{path.relative_to(REPO) if path.is_relative_to(REPO) else path}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
