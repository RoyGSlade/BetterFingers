import tkinter as tk
from typing import Callable, Optional


class NotificationOverlay:
    def __init__(self, root, on_position_changed: Optional[Callable[[int, int], None]] = None):
        self.on_position_changed = on_position_changed
        self.root = tk.Toplevel(root)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.85)

        self.enabled = True
        self.position = "Bottom-Right"
        self.custom_x = 40
        self.custom_y = 40
        self._hide_job = None
        self._drag = None

        self.frame = tk.Frame(self.root, bg="#161616", bd=1, relief="solid")
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.message_var = tk.StringVar(value="")
        self.label = tk.Label(
            self.frame,
            textvariable=self.message_var,
            bg="#161616",
            fg="#f2f2f2",
            padx=12,
            pady=8,
            justify=tk.LEFT,
            font=("Segoe UI", 10, "bold"),
        )
        self.label.pack(fill=tk.BOTH, expand=True)

        for widget in (self.root, self.frame, self.label):
            widget.bind("<ButtonPress-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_release)

        self.root.withdraw()

    def apply_config(self, config):
        self.enabled = bool(config.get("notification_overlay_enabled", True))
        self.position = config.get("notification_overlay_position", "Bottom-Right")
        self.custom_x = int(config.get("notification_overlay_custom_x", self.custom_x))
        self.custom_y = int(config.get("notification_overlay_custom_y", self.custom_y))

        alpha = float(config.get("notification_overlay_alpha", 0.85))
        alpha = max(0.2, min(1.0, alpha))
        self.root.attributes("-alpha", alpha)

        self.default_bg = config.get("notification_overlay_bg", "#161616")
        self.default_fg = config.get("notification_overlay_fg", "#f2f2f2")
        self.frame.configure(bg=self.default_bg)
        self.label.configure(bg=self.default_bg, fg=self.default_fg)

        if not self.enabled:
            self.root.withdraw()

    def show_message(self, message: str, duration_ms: int = 2500, msg_type: str = "info"):
        if not self.enabled:
            return

        colors = {
            "info": (getattr(self, "default_bg", "#161616"), getattr(self, "default_fg", "#f2f2f2")),
            "success": ("#064e3b", "#ecfdf5"),
            "warning": ("#78350f", "#fffbeb"),
            "error": ("#7f1d1d", "#fef2f2"),
        }
        bg, fg = colors.get(msg_type, colors["info"])

        self.frame.configure(bg=bg)
        self.label.configure(bg=bg, fg=fg)
        self.message_var.set(message or "")
        self._position_window()
        self.root.deiconify()
        self.root.lift()

        if self._hide_job:
            self.root.after_cancel(self._hide_job)
        self._hide_job = self.root.after(max(500, int(duration_ms)), self.root.withdraw)

    def _position_window(self):
        self.root.update_idletasks()
        width = max(240, self.root.winfo_reqwidth())
        height = max(44, self.root.winfo_reqheight())
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        pad = 26

        if self.position == "Top-Left":
            x, y = pad, pad
        elif self.position == "Top-Right":
            x, y = sw - width - pad, pad
        elif self.position == "Bottom-Left":
            x, y = pad, sh - height - pad
        elif self.position == "Custom":
            x, y = self.custom_x, self.custom_y
        else:
            x, y = sw - width - pad, sh - height - pad

        self.root.geometry(f"{width}x{height}+{int(x)}+{int(y)}")

    def _on_drag_start(self, event):
        self._drag = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _on_drag_motion(self, event):
        if not self._drag:
            return
        sx, sy, wx, wy = self._drag
        nx = wx + (event.x_root - sx)
        ny = wy + (event.y_root - sy)
        self.root.geometry(f"+{int(nx)}+{int(ny)}")

    def _on_drag_release(self, event):
        del event
        if not self._drag:
            return
        self._drag = None
        self.position = "Custom"
        self.custom_x = self.root.winfo_x()
        self.custom_y = self.root.winfo_y()
        if self.on_position_changed:
            self.on_position_changed(self.custom_x, self.custom_y)

