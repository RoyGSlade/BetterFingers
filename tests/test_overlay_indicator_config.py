import tkinter as tk
import unittest

from overlay import Overlay


class OverlayIndicatorConfigTests(unittest.TestCase):
    def _create_overlay(self):
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        overlay = Overlay(root)
        return root, overlay

    def test_apply_config_updates_visibility_and_colors(self):
        root, overlay = self._create_overlay()
        try:
            overlay.apply_config(
                {
                    "overlay_position": "Bottom-Right",
                    "status_indicator_enabled": False,
                    "status_indicator_flash_enabled": False,
                    "status_indicator_color_idle": "#101010",
                    "status_indicator_color_listening": "#202020",
                    "status_indicator_color_recording": "#303030",
                    "status_indicator_color_processing": "#404040",
                }
            )
            self.assertFalse(overlay.enabled)

            overlay.apply_config(
                {
                    "overlay_position": "Top-Left",
                    "status_indicator_enabled": True,
                    "status_indicator_flash_enabled": False,
                    "status_indicator_color_idle": "#111111",
                    "status_indicator_color_listening": "#222222",
                    "status_indicator_color_recording": "#333333",
                    "status_indicator_color_processing": "#abcdef",
                }
            )
            overlay.set_state("processing")
            fill = str(overlay.canvas.itemcget(overlay.indicator, "fill")).lower()
            self.assertEqual(fill, "#abcdef")
            self.assertFalse(overlay.flashing)
        finally:
            overlay.destroy()
            if root.winfo_exists():
                root.destroy()

    def test_recording_flash_respects_toggle(self):
        root, overlay = self._create_overlay()
        try:
            overlay.apply_config(
                {
                    "status_indicator_enabled": True,
                    "status_indicator_flash_enabled": True,
                    "status_indicator_color_recording": "#ff0000",
                }
            )
            overlay.set_state("recording")
            self.assertTrue(overlay.flashing)

            overlay.apply_config(
                {
                    "status_indicator_enabled": True,
                    "status_indicator_flash_enabled": False,
                    "status_indicator_color_recording": "#ff0000",
                }
            )
            overlay.set_state("recording")
            self.assertFalse(overlay.flashing)
        finally:
            overlay.destroy()
            if root.winfo_exists():
                root.destroy()


if __name__ == "__main__":
    unittest.main()
