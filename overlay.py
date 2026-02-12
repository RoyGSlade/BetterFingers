import logging
import tkinter as tk
import ctypes
import platform
import threading
import time
import os

# Enable DPI awareness on Windows to prevent scaling issues
if platform.system() == "Windows":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

CHROMA_KEY = "#00ff00"


def _get_assets_dir():
    """Get path to assets directory."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


class Overlay:
    def __init__(self, root):
        self._is_windows = platform.system() == "Windows"
        self._supports_window_alpha = not self._is_windows
        self.flashing = False
        self.flash_direction = 1
        self.current_alpha = 1.0
        self.current_pulse = 0.0
        self.enabled = True
        self.flash_enabled = True
        self.state_colors = {
            "idle": "#808080",
            "listening": "#14b8a6",
            "recording": "#ff3b30",
            "processing": "#fbbf24",
        }
        self._recording_base_rgb = (255, 59, 48)
        self._images = {}
        
        # Transparency refresh for Flet compatibility
        self._refresh_transparency = False
        self._refresh_thread = None
        
        self._current_state = "idle"

        self.root = tk.Toplevel(root)
        self.root.overrideredirect(True)  # Frameless
        self.root.attributes("-topmost", True)
        self.root.configure(bg=CHROMA_KEY)

        # Size for display (sprites are 64x64, we scale to 32)
        self.size = 32
        self.root.geometry(f"{self.size}x{self.size}+0+0")

        if self._is_windows:
            # Ensure window is mapped before applying Windows-specific styles
            self.root.update_idletasks()
            self.root.wait_visibility(self.root)
            self._setup_windows_transparency()
        else:
            self.root.attributes("-alpha", 0.9)

        self.canvas = tk.Canvas(
            self.root,
            width=self.size,
            height=self.size,
            highlightthickness=0,
            bg=CHROMA_KEY,
            bd=0,
        )
        self.canvas.pack()
        self.indicator = self.canvas.create_oval(2, 2, self.size - 2, self.size - 2, fill="#808080", outline="", width=0)

        self.position = "Bottom-Right"
        self.set_state("idle")  # Start visible (Idle)

    def _root_alive(self):
        root = getattr(self, "root", None)
        if root is None:
            return False
        try:
            return bool(root.winfo_exists())
        except Exception:
            return False

    def _load_images(self):
        """Load indicator sprite images."""
        try:
            from PIL import Image, ImageTk
            
            assets_dir = _get_assets_dir()
            state_files = {
                "idle": "indicator_idle.png",
                "listening": "indicator_listening.png",
                "recording": "indicator_recording.png",
                "processing": "indicator_processing.png",
            }
            
            for state, filename in state_files.items():
                path = os.path.join(assets_dir, filename)
                if os.path.exists(path):
                    # Load and resize image
                    img = Image.open(path)
                    img = img.resize((self.size, self.size), Image.Resampling.LANCZOS)
                    self._images[state] = ImageTk.PhotoImage(img)
                    logging.debug(f"Loaded indicator sprite: {filename}")
                else:
                    logging.warning(f"Indicator sprite not found: {path}")
            
            self._use_fallback = len(self._images) == 0
            
        except ImportError:
            logging.warning("PIL not available, using fallback oval indicators")
            self._use_fallback = True
        except Exception as e:
            logging.error(f"Error loading indicator sprites: {e}")
            self._use_fallback = True

    def _setup_windows_transparency(self):
        """Apply Windows-specific transparency using direct Win32 API calls."""
        if not self._is_windows:
            return
        if not self._root_alive():
            logging.debug("Overlay: skipping transparency setup; window no longer exists.")
            return
        try:
            hwnd = self.root.winfo_id()
            logging.debug("Overlay: Window handle is %s", hwnd)
            
            # Get current extended style
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x80000
            WS_EX_TRANSPARENT = 0x20
            LWA_COLORKEY = 0x1
            
            # Set WS_EX_LAYERED and WS_EX_TRANSPARENT styles
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
            
            # Convert chroma key color to COLORREF (BGR format)
            # #00ff00 -> R=0, G=255, B=0 -> COLORREF = 0x0000FF00
            chroma_colorref = 0x0000FF00  # Green in BGR format
            
            # Apply color key transparency using SetLayeredWindowAttributes
            # Parameters: hwnd, crKey (color), bAlpha (not used with LWA_COLORKEY), dwFlags
            result = ctypes.windll.user32.SetLayeredWindowAttributes(
                hwnd, 
                chroma_colorref,
                0,  # alpha (not used with LWA_COLORKEY)
                LWA_COLORKEY
            )
            
            if result == 0:
                error = ctypes.get_last_error()
                logging.error("Overlay: SetLayeredWindowAttributes failed with error %d", error)
            else:
                logging.debug("Overlay: SetLayeredWindowAttributes succeeded")
            
            # Also set Tkinter's transparentcolor as a backup
            self.root.attributes("-transparentcolor", CHROMA_KEY)
            self.root.attributes("-topmost", True)
            
            # Verify styles
            final_style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            logging.debug("Overlay: Final extended style: 0x%X", final_style)
            
        except Exception as e:
            # Window can be destroyed during shutdown races; keep this non-fatal.
            logging.debug("Overlay setup skipped: %s", e)



    def start_transparency_refresh(self):
        """Start a background loop that periodically reapplies transparency.
        
        Call this when opening Flet UI to combat its interference with Win32 layered windows.
        """
        if not self._is_windows:
            return
            
        with threading.Lock():
            if self._refresh_transparency:
                return  # Already running
            self._refresh_transparency = True
            self._refresh_thread = threading.Thread(target=self._transparency_refresh_loop, daemon=True)
            self._refresh_thread.start()
            logging.debug("Overlay: Started transparency refresh loop")

    def stop_transparency_refresh(self):
        """Stop the transparency refresh loop."""
        self._refresh_transparency = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=0.5)
            self._refresh_thread = None
            logging.debug("Overlay: Stopped transparency refresh loop")

    def _transparency_refresh_loop(self):
        """Background loop that reapplies Win32 transparency settings periodically."""
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
        LWA_COLORKEY = 0x1
        chroma_colorref = 0x0000FF00  # Green in BGR format
        
        while self._refresh_transparency:
            try:
                if not self._root_alive():
                    break
                    
                hwnd = self.root.winfo_id()
                
                # Check if styles are still correct
                style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                
                # If WS_EX_LAYERED is missing, reapply everything
                if not (style & WS_EX_LAYERED):
                    logging.debug("Overlay: Reapplying layered style (was lost)")
                    new_style = style | WS_EX_LAYERED | WS_EX_TRANSPARENT
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                    ctypes.windll.user32.SetLayeredWindowAttributes(
                        hwnd, chroma_colorref, 0, LWA_COLORKEY
                    )
                elif not (style & WS_EX_TRANSPARENT):
                    # Just reapply transparent style
                    new_style = style | WS_EX_TRANSPARENT
                    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, new_style)
                    
            except Exception as e:
                logging.debug(f"Overlay refresh error: {e}")
                
            time.sleep(0.1)  # Check every 100ms

    def update_position(self, pos_name):
        if not self._root_alive():
            return
        self.position = pos_name
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        x = 0
        y = 0
        padding = 20

        if "Left" in pos_name:
            x = padding
        elif "Right" in pos_name:
            x = screen_w - self.size - padding
        elif "Center" in pos_name:
            x = (screen_w // 2) - (self.size // 2)

        if "Top" in pos_name:
            y = padding
        elif "Bottom" in pos_name:
            y = screen_h - self.size - padding
        elif "Mid" in pos_name:
            y = (screen_h // 2) - (self.size // 2)

        self.root.geometry(f"{self.size}x{self.size}+{x}+{y}")

    @staticmethod
    def _normalize_hex_color(value, fallback):
        color = str(value or "").strip()
        if len(color) == 7 and color.startswith("#"):
            valid = all(ch in "0123456789abcdefABCDEF" for ch in color[1:])
            if valid:
                return color.lower()
        return fallback.lower()

    @staticmethod
    def _hex_to_rgb(hex_color):
        value = str(hex_color or "#000000").strip().lstrip("#")
        return (
            int(value[0:2], 16),
            int(value[2:4], 16),
            int(value[4:6], 16),
        )

    @staticmethod
    def _rgb_to_hex(rgb):
        r, g, b = rgb
        return f"#{int(max(0, min(255, r))):02x}{int(max(0, min(255, g))):02x}{int(max(0, min(255, b))):02x}"

    def apply_config(self, config):
        if not self._root_alive():
            return
        cfg = config if isinstance(config, dict) else {}
        self.enabled = bool(cfg.get("status_indicator_enabled", True))
        self.flash_enabled = bool(cfg.get("status_indicator_flash_enabled", True))
        self.state_colors["idle"] = self._normalize_hex_color(cfg.get("status_indicator_color_idle"), "#808080")
        self.state_colors["listening"] = self._normalize_hex_color(cfg.get("status_indicator_color_listening"), "#14b8a6")
        self.state_colors["recording"] = self._normalize_hex_color(cfg.get("status_indicator_color_recording"), "#ff3b30")
        self.state_colors["processing"] = self._normalize_hex_color(cfg.get("status_indicator_color_processing"), "#fbbf24")

        self.update_position(cfg.get("overlay_position", self.position))
        if not self.enabled:
            self.flashing = False
            self.root.withdraw()
            return
        self.set_state(self._current_state or "idle")

    def set_state(self, state):
        if not self._root_alive():
            return
        normalized_state = str(state or "idle").strip().lower()
        if normalized_state not in {"idle", "recording", "processing", "listening"}:
            normalized_state = "idle"
        self._current_state = normalized_state
        self.flashing = False

        if not self.enabled:
            self.root.withdraw()
            return

        self.root.deiconify()
        base_color = self.state_colors.get(normalized_state, self.state_colors["idle"])
        self.canvas.itemconfig(self.indicator, fill=base_color, outline="", width=0)

        if self._supports_window_alpha:
            if normalized_state == "idle":
                self.root.attributes("-alpha", 0.72)
            else:
                self.root.attributes("-alpha", 0.95)

        if normalized_state == "recording":
            self._recording_base_rgb = self._hex_to_rgb(base_color)
            if self.flash_enabled:
                self.flashing = True
                self.flash_direction = 1
                self.current_pulse = 0.0
                self._flash_loop()

    def _flash_loop(self):
        if not self._root_alive():
            return
        if not self.flashing or not self.enabled or self._current_state != "recording":
            return

        step = 0.032
        if self.flash_direction == 1:
            self.current_pulse += step
            if self.current_pulse >= 1.0:
                self.current_pulse = 1.0
                self.flash_direction = -1
        else:
            self.current_pulse -= step
            if self.current_pulse <= 0.0:
                self.current_pulse = 0.0
                self.flash_direction = 1

        factor = 0.55 + (0.45 * self.current_pulse)
        flash_rgb = tuple(int(channel * factor) for channel in self._recording_base_rgb)
        self.canvas.itemconfig(self.indicator, fill=self._rgb_to_hex(flash_rgb), outline="", width=0)

        if self._supports_window_alpha:
            self.root.attributes("-alpha", 0.72 + (0.2 * self.current_pulse))

        # Run at ~60fps
        self.root.after(16, self._flash_loop)

    def destroy(self):
        self.flashing = False
        self.stop_transparency_refresh()
        root = getattr(self, "root", None)
        if root is None:
            return
        try:
            if root.winfo_exists():
                root.destroy()
        except Exception:
            pass
        finally:
            self.root = None
