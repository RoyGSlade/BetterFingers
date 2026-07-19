"""Local, dependency-free QR-code SVG rendering for the room join link.

Wraps the vendored matrix encoder (``backend/lan_playground/_vendor/qrenc``,
copied unmodified from segno 1.6.6 -- see its NOTICE.md) with a small
hand-written SVG serializer. No network call, no external QR service: the
whole thing runs locally so QR join works with zero internet access, which
matters for a LAN-only game hosted from a laptop with no connectivity.

``render_qr_svg`` never logs or persists the data it encodes.
"""

from __future__ import annotations

import xml.sax.saxutils as _xml

from backend.lan_playground._vendor.qrenc import encode

DEFAULT_SCALE = 8
DEFAULT_BORDER = 4
DEFAULT_DARK = "#0b0f14"
DEFAULT_LIGHT = "#ffffff"

# segno's own encode() enforces this, but this is our documented contract:
# plain byte-mode QR (never Micro QR, which many camera scanners mishandle).
QR_MAX_BYTES = 2953  # version 40, error level L byte-mode capacity ceiling


def render_qr_svg(
    data: str,
    *,
    scale: int = DEFAULT_SCALE,
    border: int = DEFAULT_BORDER,
    dark: str = DEFAULT_DARK,
    light: str = DEFAULT_LIGHT,
) -> str:
    """Render ``data`` (e.g. a join URL) as a standalone, scannable SVG string.

    Uses error-correction level M and forces a regular (non-Micro) QR code
    so ordinary phone camera scanners can read it.
    """
    if not data:
        raise ValueError("data must be non-empty")
    if scale < 1:
        raise ValueError("scale must be >= 1")
    if border < 0:
        raise ValueError("border must be >= 0")

    code = encode(data, error="m", micro=False, boost_error=True)
    matrix = code.matrix
    modules = len(matrix)
    size = (modules + 2 * border) * scale

    dark_attr = _xml.quoteattr(dark)
    light_attr = _xml.quoteattr(light)

    rects: list[str] = []
    for row_idx, row in enumerate(matrix):
        run_start = None
        for col_idx in range(len(row) + 1):
            is_dark = col_idx < len(row) and bool(row[col_idx])
            if is_dark and run_start is None:
                run_start = col_idx
            elif not is_dark and run_start is not None:
                x = (run_start + border) * scale
                y = (row_idx + border) * scale
                w = (col_idx - run_start) * scale
                rects.append(f'<rect x="{x}" y="{y}" width="{w}" height="{scale}"/>')
                run_start = None

    body = "".join(rects)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'width="{size}" height="{size}" shape-rendering="crispEdges" role="img" '
        f'aria-label="QR code">'
        f'<rect x="0" y="0" width="{size}" height="{size}" fill={light_attr}/>'
        f'<g fill={dark_attr}>{body}</g>'
        f"</svg>"
    )
