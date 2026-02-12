import inspect
import logging
from typing import Callable, Optional


class SettingsModalManager:
    """
    Manages settings dialogs across multiple Flet API generations.

    Preferred backend order:
    1) page.show_dialog()/page.pop_dialog() - Flet 0.80.x
    2) page.open()/page.close() - newer Flet API
    3) page.overlay fallback
    """

    def __init__(
        self,
        page_getter: Callable[[], object],
        on_update: Optional[Callable[[], None]] = None,
    ):
        self._page_getter = page_getter
        self._on_update = on_update
        self._dialogs_by_key: dict[str, object] = {}
        self._keys_by_dialog_id: dict[int, str] = {}
        self._active_key: Optional[str] = None

    @staticmethod
    def _normalize_key(key: str) -> str:
        return str(key or "").strip()

    def _get_page(self):
        try:
            return self._page_getter()
        except Exception:
            return None

    def _update(self, page):
        if callable(self._on_update):
            try:
                self._on_update()
                return
            except Exception:
                pass
        if page and hasattr(page, "update"):
            try:
                page.update()
            except Exception:
                pass

    def _register(self, key: str, dialog):
        self._dialogs_by_key[key] = dialog
        self._keys_by_dialog_id[id(dialog)] = key
        self._active_key = key

    def _remove_key(self, key: str):
        dialog = self._dialogs_by_key.pop(key, None)
        if dialog is not None:
            self._keys_by_dialog_id.pop(id(dialog), None)
        if self._active_key == key:
            self._active_key = next(reversed(self._dialogs_by_key), None) if self._dialogs_by_key else None

    def _remove_dialog(self, dialog):
        key = self._keys_by_dialog_id.get(id(dialog))
        if key:
            self._remove_key(key)
        return key

    @staticmethod
    def _call_handler(handler, event):
        if not callable(handler):
            return
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                try:
                    import asyncio

                    asyncio.create_task(result)
                except Exception:
                    pass
        except Exception as exc:
            logging.debug("Dialog dismiss callback failed: %s", exc)

    def get_key_for_dialog(self, dialog) -> Optional[str]:
        if dialog is None:
            return None
        return self._keys_by_dialog_id.get(id(dialog))

    def is_open(self, key: str) -> bool:
        normalized = self._normalize_key(key)
        if not normalized:
            return False
        dialog = self._dialogs_by_key.get(normalized)
        return bool(dialog and getattr(dialog, "open", False))

    def show(self, key: str, dialog, replace_active: bool = True) -> None:
        normalized = self._normalize_key(key)
        if not normalized or dialog is None:
            return

        page = self._get_page()
        if not page:
            return

        existing = self._dialogs_by_key.get(normalized)
        if existing is not None and existing is not dialog:
            self.close(key=normalized)
        if replace_active and self._active_key and self._active_key != normalized:
            self.close(key=self._active_key)

        original_on_dismiss = getattr(dialog, "on_dismiss", None)

        def _wrapped_on_dismiss(event=None):
            self._remove_dialog(dialog)
            self._call_handler(original_on_dismiss, event)

        dialog.on_dismiss = _wrapped_on_dismiss
        self._register(normalized, dialog)

        try:
            if hasattr(page, "show_dialog"):
                page.show_dialog(dialog)
            elif hasattr(page, "open"):
                page.open(dialog)
            else:
                overlay = getattr(page, "overlay", None)
                if isinstance(overlay, list) and dialog not in overlay:
                    overlay.append(dialog)
                elif hasattr(page, "dialog"):
                    page.dialog = dialog
                dialog.open = True
                self._update(page)
        except Exception as exc:
            # Roll back registration if open failed.
            self._remove_key(normalized)
            logging.error("Failed to show dialog '%s': %s", normalized, exc)

    def close(self, key: str | None = None) -> bool:
        target_key = self._normalize_key(key) if key is not None else (self._active_key or "")
        if not target_key:
            return False

        dialog = self._dialogs_by_key.get(target_key)
        if dialog is None:
            return False

        page = self._get_page()
        closed = False

        try:
            if page and hasattr(page, "pop_dialog") and target_key == self._active_key:
                popped = page.pop_dialog()
                if popped is not None:
                    closed = True
                    # pop_dialog might return a different instance than target dialog
                    self._remove_dialog(popped)
            if not closed and page and hasattr(page, "close"):
                page.close(dialog)
                closed = True
            if not closed:
                try:
                    dialog.open = False
                    closed = True
                except Exception:
                    pass

            if page:
                try:
                    if getattr(page, "dialog", None) is dialog:
                        page.dialog = None
                except Exception:
                    pass
                try:
                    overlay = getattr(page, "overlay", None)
                    if isinstance(overlay, list) and dialog in overlay:
                        overlay.remove(dialog)
                except Exception:
                    pass
                self._update(page)
        except Exception as exc:
            logging.debug("Dialog close path failed for '%s': %s", target_key, exc)
        finally:
            self._remove_key(target_key)

        return closed

    def close_all(self) -> None:
        for key in list(self._dialogs_by_key.keys()):
            self.close(key=key)
