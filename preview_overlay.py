import threading
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class PreviewOverlay:
    PALETTE = {
        "bg": "#0d0d0d",
        "surface": "#161616",
        "text_bg": "#1a1a1a",
        "fg": "#f5f5f5",
        "muted": "#888888",
        "accent": "#14b8a6",
        "border": "#2a2a2a",
    }

    def __init__(
        self,
        root,
        on_accept: Optional[Callable[[int, str], None]] = None,
        on_decline: Optional[Callable[[int], None]] = None,
        on_tts: Optional[Callable[[int, str], None]] = None,
        on_rewrite: Optional[Callable[[int, str, str, str], dict]] = None,
        on_position_changed: Optional[Callable[[int, int], None]] = None,
    ):
        self.on_accept = on_accept
        self.on_decline = on_decline
        self.on_tts = on_tts
        self.on_rewrite = on_rewrite
        self.on_position_changed = on_position_changed

        self.enabled = True
        self.position = "Bottom-Right"
        self.custom_x = 120
        self.custom_y = 120
        self.current_draft_id = None
        self._drag = None
        self._rewrite_busy = False
        self._dual_mode = True

        self.root = tk.Toplevel(root)
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)

        self.container = tk.Frame(
            self.root,
            bg=self.PALETTE["bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=self.PALETTE["border"],
        )
        self.container.pack(fill=tk.BOTH, expand=True)

        self.title_bar = tk.Frame(self.container, bg=self.PALETTE["surface"], height=36)
        self.title_bar.pack(fill=tk.X)
        self.title_bar.pack_propagate(False)

        self.accent_line = tk.Frame(self.container, bg=self.PALETTE["accent"], height=2)
        self.accent_line.pack(fill=tk.X)

        self.title_var = tk.StringVar(value="Preview")
        self.meta_var = tk.StringVar(value="")
        self.title = tk.Label(
            self.title_bar,
            textvariable=self.title_var,
            bg=self.PALETTE["surface"],
            fg=self.PALETTE["fg"],
            anchor="w",
            padx=14,
            pady=8,
            font=("Segoe UI", 11, "bold"),
        )
        self.title.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.meta = tk.Label(
            self.title_bar,
            textvariable=self.meta_var,
            bg=self.PALETTE["surface"],
            fg=self.PALETTE["muted"],
            anchor="e",
            padx=12,
            pady=8,
            font=("Segoe UI", 9),
        )
        self.meta.pack(side=tk.RIGHT)

        self.content = tk.Frame(self.container, bg=self.PALETTE["bg"])
        self.content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.side_var = tk.StringVar(value="left")

        self.panes = tk.Frame(self.content, bg=self.PALETTE["bg"])
        self.panes.pack(fill=tk.BOTH, expand=True)

        self.left_panel = tk.Frame(self.panes, bg=self.PALETTE["bg"])
        self.left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        self.right_panel = tk.Frame(self.panes, bg=self.PALETTE["bg"])
        self.right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        self.left_header = tk.Frame(self.left_panel, bg=self.PALETTE["surface"])
        self.left_header.pack(fill=tk.X)
        self.right_header = tk.Frame(self.right_panel, bg=self.PALETTE["surface"])
        self.right_header.pack(fill=tk.X)

        self.left_radio = ttk.Radiobutton(
            self.left_header,
            text="Original",
            variable=self.side_var,
            value="left",
            command=self._on_side_changed,
        )
        self.left_radio.pack(side=tk.LEFT, padx=8, pady=4)
        self.right_radio = ttk.Radiobutton(
            self.right_header,
            text="Candidate",
            variable=self.side_var,
            value="right",
            command=self._on_side_changed,
        )
        self.right_radio.pack(side=tk.LEFT, padx=8, pady=4)

        self.left_text = tk.Text(
            self.left_panel,
            height=10,
            wrap=tk.WORD,
            bg=self.PALETTE["text_bg"],
            fg=self.PALETTE["fg"],
            insertbackground=self.PALETTE["fg"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=self.PALETTE["border"],
            selectbackground=self.PALETTE["accent"],
            selectforeground="#ffffff",
        )
        self.left_text.pack(fill=tk.BOTH, expand=True)

        self.right_text = tk.Text(
            self.right_panel,
            height=10,
            wrap=tk.WORD,
            bg=self.PALETTE["text_bg"],
            fg=self.PALETTE["fg"],
            insertbackground=self.PALETTE["fg"],
            relief="flat",
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
            highlightthickness=1,
            highlightbackground=self.PALETTE["border"],
            selectbackground=self.PALETTE["accent"],
            selectforeground="#ffffff",
        )
        self.right_text.pack(fill=tk.BOTH, expand=True)

        action_row = tk.Frame(self.container, bg=self.PALETTE["surface"])
        action_row.pack(fill=tk.X, padx=10, pady=(0, 6))

        self.accept_btn = ttk.Button(action_row, text="Accept", command=self._handle_accept)
        self.accept_btn.pack(side=tk.LEFT, padx=(4, 4), pady=6)

        self.decline_btn = ttk.Button(action_row, text="Decline", command=self._handle_decline)
        self.decline_btn.pack(side=tk.LEFT, padx=(0, 4), pady=6)

        self.read_left_btn = ttk.Button(action_row, text="Read Left", command=lambda: self._handle_tts_side("left"))
        self.read_left_btn.pack(side=tk.LEFT, padx=(0, 4), pady=6)

        self.read_right_btn = ttk.Button(action_row, text="Read Right", command=lambda: self._handle_tts_side("right"))
        self.read_right_btn.pack(side=tk.LEFT, padx=(0, 4), pady=6)

        rewrite_row = tk.Frame(self.container, bg=self.PALETTE["surface"])
        rewrite_row.pack(fill=tk.X, padx=10, pady=(0, 10))

        self.edit_menu_button = ttk.Menubutton(rewrite_row, text="Edit")
        self.edit_menu = tk.Menu(self.edit_menu_button, tearoff=0)
        self.edit_menu.add_command(label="Expand", command=lambda: self._request_rewrite("expand"))
        self.edit_menu.add_command(label="Rephrase", command=lambda: self._request_rewrite("rephrase"))
        self.edit_menu.add_command(label="Shorten", command=lambda: self._request_rewrite("shorten"))
        self.edit_menu.add_command(label="Format", command=lambda: self._request_rewrite("format"))
        self.edit_menu.add_separator()
        self.edit_menu.add_command(label="Custom Rewrite", command=lambda: self._request_rewrite("custom"))
        self.edit_menu_button["menu"] = self.edit_menu
        self.edit_menu_button.pack(side=tk.LEFT, padx=(4, 8), pady=6)

        self.custom_entry = ttk.Entry(rewrite_row)
        self.custom_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), pady=6)
        self.custom_entry.insert(0, "Custom rewrite instruction")

        self.custom_apply_btn = ttk.Button(rewrite_row, text="Apply Custom", command=lambda: self._request_rewrite("custom"))
        self.custom_apply_btn.pack(side=tk.LEFT, padx=(0, 4), pady=6)

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self.container,
            textvariable=self.status_var,
            bg=self.PALETTE["bg"],
            fg=self.PALETTE["muted"],
            anchor="w",
            padx=12,
            pady=4,
            font=("Segoe UI", 9),
        )
        self.status_label.pack(fill=tk.X, pady=(0, 6))

        self.root.withdraw()
        self._apply_side_style()
        self._set_dual_mode(False)

        for widget in (self.root, self.container, self.title_bar, self.title, self.meta):
            widget.bind("<ButtonPress-1>", self._on_drag_start)
            widget.bind("<B1-Motion>", self._on_drag_motion)
            widget.bind("<ButtonRelease-1>", self._on_drag_release)

    def apply_config(self, config):
        self.enabled = bool(config.get("preview_overlay_enabled", True))
        self.position = config.get("preview_overlay_position", "Bottom-Right")
        self.custom_x = int(config.get("preview_overlay_custom_x", self.custom_x))
        self.custom_y = int(config.get("preview_overlay_custom_y", self.custom_y))

        alpha = float(config.get("preview_overlay_alpha", 0.95))
        alpha = max(0.25, min(1.0, alpha))
        self.root.attributes("-alpha", alpha)

        bg = config.get("preview_overlay_bg", "#111111")
        fg = config.get("preview_overlay_fg", "#f2f2f2")
        text_bg = config.get("preview_overlay_text_bg", "#1d1d1d")

        self.container.configure(bg=bg)
        self.title.configure(bg=bg, fg=fg)
        self.meta.configure(bg=bg, fg=self.PALETTE["muted"])
        self.left_text.configure(bg=text_bg, fg=fg, insertbackground=fg)
        self.right_text.configure(bg=text_bg, fg=fg, insertbackground=fg)

        if not self.enabled:
            self.root.withdraw()

    def show_review(self, draft_id: int, text: str, token_count: int = 0, token_limit: int = 0):
        if not self.enabled:
            return
        self.current_draft_id = draft_id
        self.title_var.set(f"Review Draft #{draft_id}")
        meta = ""
        if int(token_count or 0) > 0 and int(token_limit or 0) > 0:
            meta = f"Tokens {int(token_count)}/{int(token_limit)}"
        self.meta_var.set(meta)
        clean_text = str(text or "")
        self._set_text(self.left_text, clean_text)
        self._set_text(self.right_text, clean_text)
        self.side_var.set("left")
        self._set_dual_mode(False)
        self._apply_side_style()
        self._set_buttons_visible(True)
        self.status_var.set("")
        self._position_window()
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        self.root.withdraw()
        self.current_draft_id = None
        self._rewrite_busy = False

    def get_current_text(self) -> str:
        return self.get_pane_text(self.side_var.get() or "left")

    def get_selected_or_full_text(self) -> str:
        target_widget = self.left_text if self.side_var.get() == "left" else self.right_text
        try:
            selected = target_widget.get("sel.first", "sel.last").strip()
            if selected:
                return selected
        except tk.TclError:
            pass
        return target_widget.get("1.0", tk.END).strip()

    def get_pane_text(self, side: str) -> str:
        widget = self.left_text if str(side or "").strip().lower() == "left" else self.right_text
        return widget.get("1.0", tk.END).strip()

    def is_review_active(self) -> bool:
        return bool(self.current_draft_id is not None) and bool(self.root.winfo_viewable())

    def _set_text(self, widget: tk.Text, value: str):
        widget.delete("1.0", tk.END)
        widget.insert("1.0", value or "")

    def _set_buttons_visible(self, visible: bool):
        state = tk.NORMAL if visible else tk.DISABLED
        for button in (
            self.accept_btn,
            self.decline_btn,
            self.read_left_btn,
            self.read_right_btn,
            self.edit_menu_button,
            self.custom_apply_btn,
        ):
            button.configure(state=state)
        self.custom_entry.configure(state=state)

    def _set_rewrite_busy(self, busy: bool):
        self._rewrite_busy = bool(busy)
        state = tk.DISABLED if busy else tk.NORMAL
        for button in (self.edit_menu_button, self.custom_apply_btn):
            button.configure(state=state)
        self.custom_entry.configure(state=state)
        if busy:
            self.status_var.set("Rewriting...")

    def _set_dual_mode(self, enabled: bool):
        self._dual_mode = bool(enabled)
        if self._dual_mode:
            if self.right_panel.winfo_manager() != "pack":
                self.right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))
            self.left_radio.configure(text="Original", state=tk.NORMAL)
            self.right_radio.configure(state=tk.NORMAL)
            if not self._rewrite_busy:
                self.read_right_btn.configure(state=tk.NORMAL)
        else:
            if self.right_panel.winfo_manager():
                self.right_panel.pack_forget()
            self.side_var.set("left")
            self.left_radio.configure(text="Draft", state=tk.DISABLED)
            self.right_radio.configure(state=tk.DISABLED)
            self.read_right_btn.configure(state=tk.DISABLED)
        self._apply_side_style()
        if self.current_draft_id is not None and self.root.winfo_viewable():
            self._position_window()

    def _on_side_changed(self):
        self._apply_side_style()

    def _apply_side_style(self):
        active = self.side_var.get()
        if active == "left":
            self.left_text.configure(highlightbackground=self.PALETTE["accent"])
            self.right_text.configure(highlightbackground=self.PALETTE["border"])
        else:
            self.left_text.configure(highlightbackground=self.PALETTE["border"])
            self.right_text.configure(highlightbackground=self.PALETTE["accent"])

    def _position_window(self):
        self.root.update_idletasks()
        min_width = 820 if self._dual_mode else 520
        width = max(min_width, self.root.winfo_reqwidth())
        height = max(360, self.root.winfo_reqheight())
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        pad = 24

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

        self.root.geometry(f"{int(width)}x{int(height)}+{int(x)}+{int(y)}")

    def _handle_accept(self):
        if self.current_draft_id is None:
            return
        text = self.get_current_text()
        if self.on_accept:
            self.on_accept(self.current_draft_id, text)

    def _handle_decline(self):
        if self.current_draft_id is None:
            return
        if self.on_decline:
            self.on_decline(self.current_draft_id)

    def _handle_tts_side(self, side):
        if self.current_draft_id is None:
            return
        if not self.on_tts:
            return
        if str(side).lower() == "left":
            phrase = self.left_text.get("1.0", tk.END).strip()
        else:
            phrase = self.right_text.get("1.0", tk.END).strip()
        self.on_tts(self.current_draft_id, phrase)

    def _request_rewrite(self, action):
        if self.current_draft_id is None:
            return
        if self._rewrite_busy:
            return
        if not callable(self.on_rewrite):
            self.status_var.set("Rewrite callback is unavailable.")
            return

        action_key = str(action or "").strip().lower()
        source_text = self.get_current_text()
        custom_instruction = ""
        if action_key == "custom":
            custom_instruction = (self.custom_entry.get() or "").strip()
            if not custom_instruction:
                self.status_var.set("Enter a custom instruction first.")
                return

        # Start in single-pane mode; expand to dual-pane once a rewrite action is requested.
        if not self._dual_mode:
            self._set_dual_mode(True)

        self._set_rewrite_busy(True)

        def worker():
            result = {"ok": False, "message": "Rewrite failed.", "text": source_text}
            try:
                payload = self.on_rewrite(
                    self.current_draft_id,
                    source_text,
                    action_key,
                    custom_instruction,
                )
                if isinstance(payload, dict):
                    result = payload
            except Exception as exc:
                result = {"ok": False, "message": f"Rewrite failed: {exc}", "text": source_text}

            def apply_result():
                self._set_rewrite_busy(False)
                message = str(result.get("message", "") or "").strip()
                if message:
                    self.status_var.set(message)
                if result.get("ok", False):
                    rewritten = str(result.get("text", "") or "").strip()
                    if rewritten:
                        self._set_text(self.right_text, rewritten)
                        self.side_var.set("right")
                        self._apply_side_style()

            try:
                self.root.after(0, apply_result)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

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
