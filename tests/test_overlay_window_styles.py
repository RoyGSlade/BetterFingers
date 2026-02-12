"""Overlay window style verification (ported from verify_overlay_fix.py).

This test requires a Windows desktop with tkinter, so it will be skipped on
headless / non-Windows environments.
"""
import sys
import unittest

_SKIP = sys.platform != "win32"


@unittest.skipIf(_SKIP, "Windows-only: requires ctypes + tkinter windowing")
class OverlayWindowStyleTests(unittest.TestCase):
    """Verify that the Overlay's extended window styles include
    WS_EX_LAYERED and WS_EX_TRANSPARENT for proper click-through
    and transparency behaviour."""

    def test_overlay_has_layered_and_transparent_styles(self):
        import ctypes
        import tkinter as tk
        from overlay import Overlay

        root = tk.Tk()
        root.withdraw()

        try:
            overlay = Overlay(root)
            root.update()

            hwnd = overlay.root.winfo_id()
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)

            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20

            self.assertTrue(
                style & WS_EX_LAYERED,
                f"WS_EX_LAYERED not set (style=0x{style:X})",
            )
            self.assertTrue(
                style & WS_EX_TRANSPARENT,
                f"WS_EX_TRANSPARENT not set (style=0x{style:X})",
            )
        finally:
            try:
                overlay.destroy()
            except Exception:
                pass
            root.destroy()


if __name__ == "__main__":
    unittest.main()
