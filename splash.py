import os
import sys
import tkinter as tk
import subprocess
import webbrowser
from tkinter import messagebox


def _get_policy_accepted_path():
    return os.path.join(os.getenv("APPDATA", ""), "BetterFingers", "policy_accepted.txt")


def is_policy_accepted():
    return os.path.exists(_get_policy_accepted_path())


def mark_policy_accepted():
    path = _get_policy_accepted_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("accepted\n")
    except Exception:
        pass


CONTENT_POLICY = """I agree to the following:

- I will NOT use Better Fingers for harassment, hate speech, or threats.
- I will NOT generate content targeting individuals with malicious intent.
- I will NOT use this tool to violate applicable laws.
- I take responsibility for all content I create and send.
"""


class SplashWindow:
    def __init__(
        self,
        root,
        on_open_settings=None,
        first_run=False,
        auto_close_ms=0,
        auto_open_settings_ms=0,
        show_donation_prompt=False,
        donation_url="https://ko-fi.com/democratizegm",
    ):
        self._on_open_settings = on_open_settings
        self._auto_close_job = None
        self._auto_open_settings_job = None
        self._opened_settings = False
        self._first_run = bool(first_run)
        self._show_donation_prompt = bool(show_donation_prompt)
        self._donation_url = donation_url or "https://ko-fi.com/democratizegm"
        self._policy_needs_acceptance = not is_policy_accepted()
        self._accepted = False
        self._donation_dialog = None

        self.root = tk.Toplevel(root)
        self.root.title("Better Fingers")
        self.root.resizable(False, False)
        self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_button)

        bg_color = "#111827"
        card_color = "#1f2937"
        accent_color = "#14b8a6"
        text_color = "#f9fafb"
        muted_color = "#9ca3af"
        warning_color = "#f59e0b"

        self.root.configure(bg=bg_color)

        width = 560 if self._policy_needs_acceptance else 500
        height = 500 if self._policy_needs_acceptance else 300
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width // 2) - (width // 2)
        y = (screen_height // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

        container = tk.Frame(self.root, bg=bg_color, padx=24, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="Better Fingers",
            font=("Segoe UI", 22, "bold"),
            fg=accent_color,
            bg=bg_color,
        ).pack(anchor="w")

        tk.Label(
            container,
            text=(
                "Designed by Donaven Crenshaw for private, local tools and "
                "democratizing intelligence."
            ),
            font=("Segoe UI", 10),
            fg=muted_color,
            bg=bg_color,
            justify="left",
            wraplength=500,
        ).pack(anchor="w", pady=(4, 16))

        if self._policy_needs_acceptance:
            policy_frame = tk.Frame(container, bg=card_color, padx=14, pady=12, highlightthickness=1, highlightbackground="#374151")
            policy_frame.pack(fill=tk.BOTH, expand=True)

            tk.Label(
                policy_frame,
                text="Content Policy Agreement",
                font=("Segoe UI", 12, "bold"),
                fg=warning_color,
                bg=card_color,
                anchor="w",
            ).pack(fill=tk.X, pady=(0, 8))

            tk.Label(
                policy_frame,
                text=CONTENT_POLICY,
                font=("Segoe UI", 10),
                fg=text_color,
                bg=card_color,
                justify="left",
                anchor="nw",
                wraplength=500,
            ).pack(fill=tk.BOTH, expand=True)

            btn_frame = tk.Frame(container, bg=bg_color)
            btn_frame.pack(fill=tk.X, pady=(14, 0))

            tk.Button(
                btn_frame,
                text="Decline and Exit",
                font=("Segoe UI", 10),
                fg=text_color,
                bg="#374151",
                activebackground="#1f2937",
                relief="flat",
                padx=16,
                pady=8,
                cursor="hand2",
                command=self._on_decline,
            ).pack(side=tk.LEFT)

            tk.Button(
                btn_frame,
                text="Accept and Continue",
                font=("Segoe UI", 10, "bold"),
                fg="#052e2b",
                bg=accent_color,
                activebackground="#0f9f92",
                relief="flat",
                padx=16,
                pady=8,
                cursor="hand2",
                command=self._on_accept,
            ).pack(side=tk.RIGHT)

            auto_close_ms = 0
            auto_open_settings_ms = 0
        else:
            status_text = (
                "First launch detected. Guided setup will open automatically."
                if self._first_run
                else "Better Fingers is running in the background."
            )
            tk.Label(
                container,
                text=status_text,
                font=("Segoe UI", 10),
                fg=text_color,
                bg=bg_color,
                justify="left",
                wraplength=500,
            ).pack(anchor="w", pady=(6, 14))

            buttons = tk.Frame(container, bg=bg_color)
            buttons.pack(fill=tk.X, side=tk.BOTTOM)

            settings_label = "Start Setup" if self._first_run else "Open Settings"
            tk.Button(
                buttons,
                text=settings_label,
                font=("Segoe UI", 10, "bold"),
                fg="#052e2b",
                bg=accent_color,
                activebackground="#0f9f92",
                relief="flat",
                padx=14,
                pady=6,
                cursor="hand2",
                command=self._open_settings,
            ).pack(side=tk.LEFT)

            tk.Button(
                buttons,
                text="Close",
                font=("Segoe UI", 10),
                fg=text_color,
                bg="#374151",
                activebackground="#1f2937",
                relief="flat",
                padx=14,
                pady=6,
                cursor="hand2",
                command=self.close,
            ).pack(side=tk.RIGHT)

            if self._show_donation_prompt:
                self.root.after(250, self._open_donation_dialog)

            if auto_close_ms and auto_close_ms > 0:
                self._auto_close_job = self.root.after(int(auto_close_ms), self.close)
            if auto_open_settings_ms and auto_open_settings_ms > 0:
                self._auto_open_settings_job = self.root.after(int(auto_open_settings_ms), self._open_settings)

    def _open_donation_dialog(self):
        if not self.root.winfo_exists() or self._donation_dialog:
            return
        self._donation_dialog = tk.Toplevel(self.root)
        self._donation_dialog.title("Support Better Fingers")
        self._donation_dialog.resizable(False, False)
        self._donation_dialog.attributes("-topmost", True)
        self._donation_dialog.transient(self.root)
        self._donation_dialog.grab_set()
        self._donation_dialog.geometry("520x240")

        bg = "#0f172a"
        card = "#1e293b"
        text = "#f8fafc"
        muted = "#94a3b8"
        accent = "#14b8a6"

        self._donation_dialog.configure(bg=bg)
        container = tk.Frame(self._donation_dialog, bg=bg, padx=16, pady=14)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="It seems like you really enjoy Better Fingers.",
            font=("Segoe UI", 12, "bold"),
            fg=text,
            bg=bg,
            justify="left",
            wraplength=480,
        ).pack(anchor="w")

        tk.Label(
            container,
            text=(
                "If you could donate a dollar, or any amount, it would really help the creator. "
                "Better Fingers is subscriptionless and local-first, built to improve productivity "
                "and help people create more."
            ),
            font=("Segoe UI", 10),
            fg=muted,
            bg=bg,
            justify="left",
            wraplength=480,
        ).pack(anchor="w", pady=(8, 12))

        card_frame = tk.Frame(container, bg=card, padx=12, pady=10, highlightthickness=1, highlightbackground="#334155")
        card_frame.pack(fill=tk.X)
        tk.Label(
            card_frame,
            text=f"Donation link: {self._donation_url}",
            font=("Segoe UI", 9),
            fg=text,
            bg=card,
            justify="left",
            wraplength=470,
        ).pack(anchor="w")

        actions = tk.Frame(container, bg=bg)
        actions.pack(fill=tk.X, pady=(12, 0))
        tk.Button(
            actions,
            text="Maybe Later",
            font=("Segoe UI", 10),
            fg=text,
            bg="#334155",
            activebackground="#1e293b",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._close_donation_dialog,
        ).pack(side=tk.LEFT)
        tk.Button(
            actions,
            text="Donate",
            font=("Segoe UI", 10, "bold"),
            fg="#052e2b",
            bg=accent,
            activebackground="#0f9f92",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._open_donation_link,
        ).pack(side=tk.RIGHT)

        self._donation_dialog.protocol("WM_DELETE_WINDOW", self._close_donation_dialog)

    def _open_donation_link(self):
        opened = False
        if hasattr(os, "startfile"):
            try:
                os.startfile(self._donation_url)  # type: ignore[attr-defined]
                opened = True
            except Exception:
                opened = False
        try:
            if not opened:
                opened = bool(webbrowser.open(self._donation_url, new=2))
        except Exception:
            pass
        if not opened and os.name == "nt":
            try:
                subprocess.Popen(
                    ["cmd", "/c", "start", "", self._donation_url],
                    shell=False,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                opened = True
            except Exception:
                pass
        if not opened:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(self._donation_url)
            except Exception:
                pass
        if not opened:
            try:
                messagebox.showinfo("Support Better Fingers", f"Open this link manually:\n{self._donation_url}")
            except Exception:
                pass
        self._close_donation_dialog()

    def _close_donation_dialog(self):
        if self._donation_dialog and self._donation_dialog.winfo_exists():
            try:
                self._donation_dialog.grab_release()
            except Exception:
                pass
            self._donation_dialog.destroy()
        self._donation_dialog = None

    def _open_settings(self):
        if self._opened_settings:
            return
        self._opened_settings = True
        if callable(self._on_open_settings):
            try:
                self._on_open_settings()
            except Exception:
                pass
        self.close()

    def _on_accept(self):
        mark_policy_accepted()
        self._accepted = True
        self._open_settings()

    def _on_decline(self):
        self.close()
        try:
            self.root.master.quit()
            self.root.master.destroy()
        except Exception:
            pass
        sys.exit(0)

    def _on_close_button(self):
        if self._policy_needs_acceptance and not self._accepted:
            self._on_decline()
        else:
            self.close()

    def close(self):
        if self._auto_close_job:
            try:
                self.root.after_cancel(self._auto_close_job)
            except Exception:
                pass
            self._auto_close_job = None
        if self._auto_open_settings_job:
            try:
                self.root.after_cancel(self._auto_open_settings_job)
            except Exception:
                pass
            self._auto_open_settings_job = None
        self._close_donation_dialog()
        if self.root.winfo_exists():
            self.root.destroy()
