"""Vendored QR matrix encoder -- see NOTICE.md.

Only ``encode`` is re-exported; everything else is internal to the vendored
``encoder``/``consts`` modules copied unmodified from segno 1.6.6.
"""

from .encoder import encode

__all__ = ["encode"]
