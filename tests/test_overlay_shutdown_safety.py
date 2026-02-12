import tkinter as tk
import unittest

from overlay import Overlay


class _GoneRoot:
    def winfo_exists(self):
        raise tk.TclError("bad window path name")

    def winfo_id(self):
        raise tk.TclError("bad window path name")

    def destroy(self):
        raise tk.TclError("bad window path name")


class OverlayShutdownSafetyTests(unittest.TestCase):
    def test_setup_windows_transparency_noops_when_root_is_invalid(self):
        overlay = Overlay.__new__(Overlay)
        overlay._is_windows = True
        overlay.root = _GoneRoot()

        overlay._setup_windows_transparency()

    def test_destroy_tolerates_invalid_root(self):
        overlay = Overlay.__new__(Overlay)
        overlay.flashing = True
        overlay._refresh_transparency = False
        overlay._refresh_thread = None
        overlay.root = _GoneRoot()

        overlay.destroy()
        self.assertIsNone(overlay.root)


if __name__ == "__main__":
    unittest.main()
