# Vendored QR matrix encoder

`consts.py` and `encoder.py` in this directory are copied **unmodified**
(only a provenance header comment was added) from
[segno](https://pypi.org/project/segno/) **1.6.6**, BSD-3-Clause, Copyright
(c) 2016-2024 Lars Heuer. Full license text: `./LICENSE`.

## Why vendored instead of a pip dependency

Task #40 needed a correct QR code generator so LAN room-join QR codes
actually scan, without touching `requirements.in`/the pinned/hashed
`requirements-*.lock` files (a repo-wide, cross-session-owned surface) for a
single small feature. Segno's `encoder.py`/`consts.py` have zero
dependencies beyond the Python standard library, so they vendor cleanly.

Only the matrix-generation core is vendored -- segno's `writers.py` (image
format output incl. PIL), `helpers.py`, and `cli.py` are intentionally
**not** included. `backend/lan_playground/qr.py` (hand-written, not
vendored) calls `encode(content, error="m", micro=False)` to get the boolean
module matrix and serializes it to a minimal inline SVG itself.

## Upgrading

Re-download segno's wheel, copy `consts.py`/`encoder.py` verbatim, and
re-add the provenance header comment at the top of each file. Do not
hand-edit the vendored files otherwise -- fix bugs upstream or wrap them
from `qr.py` instead, so a future re-vendor stays a clean diff.
