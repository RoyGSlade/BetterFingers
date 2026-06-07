import logging

from guided_tour import TAB_KEY_TO_INDEX, mark_guided_tour_complete

try:
    import flet as ft
except Exception:
    ft = None


if ft is None:
    raise ImportError("Flet is required for BetterFingers settings. Please install with: pip install flet")


class SettingsTourMixin:
    def _ensure_tour_bar(self):
        """Build the bottom-docked tutorial bar (replaces modal dialog)."""
        if self._tour_bar and self._tour_page_ref is self._page:
            return self._tour_bar
        self._tour_page_ref = self._page
        self._tour_title = ft.Text("", size=16, weight=ft.FontWeight.W_600, color=self._palette["text"])
        self._tour_body = ft.Text("", size=13, color=self._palette["text"], max_lines=4)
        self._tour_progress = ft.Text("", size=11, color=self._palette["muted"])
        self._tour_start_btn = ft.Button("Start", on_click=self._tour_start)
        self._tour_skip_btn = ft.OutlinedButton("Skip", on_click=self._tour_skip)
        self._tour_back_btn = ft.TextButton("Back", on_click=self._tour_back)
        self._tour_next_btn = ft.Button("Next", on_click=self._tour_next)
        self._tour_play_btn = ft.OutlinedButton("Play", on_click=self._tour_play_current)
        self._tour_close_btn = ft.TextButton("Close", on_click=self._tour_close)

        # The bar container - initially hidden
        self._tour_bar = ft.Container(
            visible=False,
            bgcolor=self._palette["surface"],
            border=ft.border.only(top=ft.BorderSide(2, self._palette["accent"])),
            padding=ft.Padding.symmetric(horizontal=16, vertical=12),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Column(
                                [self._tour_title, self._tour_progress],
                                spacing=2,
                                tight=True,
                            ),
                            ft.Row(
                                [
                                    self._tour_start_btn,
                                    self._tour_skip_btn,
                                    self._tour_back_btn,
                                    self._tour_play_btn,
                                    self._tour_next_btn,
                                    self._tour_close_btn,
                                ],
                                spacing=8,
                                wrap=True,
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    ),
                    ft.Container(
                        content=self._tour_body,
                        padding=ft.Padding.only(top=8),
                    ),
                ],
                spacing=4,
                tight=True,
            ),
        )
        return self._tour_bar

    def _ensure_tour_dialog(self):
        """Compatibility wrapper - now uses bottom bar instead of dialog."""
        self._ensure_tour_bar()

    def _sync_tour_intro(self):
        self._tour_in_intro = True
        self._tour_title.value = "Guided Tour"
        self._tour_progress.value = "Ready to begin"
        self._tour_body.value = (
            "Press Start to begin the walkthrough. Use Skip to close it now, "
            "or Play Narration on each step once the tour begins."
        )
        self._tour_start_btn.disabled = False
        self._tour_back_btn.disabled = True
        self._tour_next_btn.text = "Next"
        self._tour_next_btn.disabled = True
        self._tour_play_btn.disabled = True
        self._highlight_tour_target("")

    def _show_tour_intro_dialog(self):
        if not self._page:
            return

        if self._tour_intro_dialog is not None:
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None

        def _close(_):
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None

        def _start(_):
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None
            self._tour_start(_)

        def _skip(_):
            mark_guided_tour_complete()
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None
            self._tour_close(_)

        def _on_dismiss(_):
            self._tour_intro_dialog = None

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Guided Tour"),
            content=ft.Text(
                "Walk through the key sections now, or skip and return anytime with Start Guided Tour."
            ),
            actions=[
                ft.TextButton("Close", on_click=_close),
                ft.OutlinedButton("Skip", on_click=_skip),
                ft.Button("Start", on_click=_start),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=_on_dismiss,
        )
        self._tour_intro_dialog = dialog
        self._show_dialog(dialog, key=self.MODAL_KEY_TOUR_INTRO)

    def _open_guided_tour(self, auto_narrate=False, start_immediately=False):
        del auto_narrate, start_immediately
        if self._tour_intro_dialog is not None:
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None
        if self._tour_bar is not None:
            self._tour_bar.visible = False
        self._highlight_tour_target("")
        self._safe_update()
        self._toast("Guided tour is disabled. Use the ? help buttons beside each setting.")

    def _sync_tour_step(self, auto_narrate=False):
        if not self._tour_steps:
            return
        self._tour_in_intro = False
        self._tour_index = max(0, min(self._tour_index, len(self._tour_steps) - 1))
        step = self._tour_steps[self._tour_index]
        self._tour_title.value = step.title
        body_text = step.narration
        action_hint = str(getattr(step, "action_hint", "") or "").strip()
        if action_hint:
            body_text = f"{body_text}\n\nTry this: {action_hint}"
        self._tour_body.value = body_text
        self._tour_progress.value = f"Step {self._tour_index + 1} of {len(self._tour_steps)}"
        self._tour_back_btn.disabled = self._tour_index == 0
        self._tour_next_btn.text = "Finish" if self._tour_index == len(self._tour_steps) - 1 else "Next"
        self._tour_next_btn.disabled = False
        self._tour_start_btn.disabled = self._tour_started
        self._tour_play_btn.disabled = False

        tab_index = TAB_KEY_TO_INDEX.get(step.tab_key, -1)
        self._select_tour_tab(tab_index)
        self._highlight_tour_target(step.target)
        self._ensure_tour_target_visible(step.target)

        if auto_narrate and self._tour_started:
            self._play_tour_step(step)

    def _select_tour_tab(self, tab_index):
        if tab_index < 0:
            return
        self._set_active_tab(tab_index, refresh=False)

    def _ensure_tour_target_visible(self, target_name: str):
        target = str(target_name or "").strip()
        if not target:
            return
        tab_key = self._tour_target_tabs.get(target)
        scroll_key = self._tour_target_scroll_keys.get(target)
        host = self._tour_tab_scrollers.get(tab_key)
        if not host or not scroll_key:
            return
        try:
            host.scroll_to(scroll_key=scroll_key, duration=320)
        except Exception:
            pass

    def _highlight_tour_target(self, target_name: str):
        for panel in self._tour_targets.values():
            panel.bgcolor = self._palette["card"]
            panel.border = ft.Border.all(1, self._palette["card_border"])
            panel.shadow = None

        target_panel = self._tour_targets.get(str(target_name or "").strip())
        if target_panel is not None:
            target_panel.bgcolor = "#27364f"
            target_panel.border = ft.Border.all(3, self._palette["accent"])
            target_panel.shadow = ft.BoxShadow(
                spread_radius=0.7,
                blur_radius=22,
                color="#5514b8a6",
            )

    def _tour_start(self, _event):
        self._tour_started = True
        self._sync_tour_step(auto_narrate=True)
        self._safe_update()

    def _tour_skip(self, _event):
        mark_guided_tour_complete()
        self._tour_close(_event)

    def _tour_back(self, _event):
        self._tour_index -= 1
        self._sync_tour_step(auto_narrate=self._tour_started)
        self._safe_update()

    def _tour_next(self, _event):
        if self._tour_in_intro:
            self._tour_start(_event)
            return
        if self._tour_index >= len(self._tour_steps) - 1:
            mark_guided_tour_complete()
            self._tour_close(_event)
            return
        self._tour_index += 1
        self._sync_tour_step(auto_narrate=self._tour_started)
        self._safe_update()

    def _tour_play_current(self, _event):
        if self._tour_in_intro or not self._tour_steps:
            return
        self._play_tour_step(self._tour_steps[self._tour_index])

    def _play_tour_step(self, step):
        if not callable(self.on_tts_preview):
            return
        speed = self._safe_float(self._controls["review_tts_speed"].value, 1.5, minimum=0.5, maximum=3.0)
        voice = (self._controls["review_tts_voice_hint"].value or "english").strip() or "english"
        quant = (self._controls.get("kokoro_quantization", ft.Control()).value or "fp32").strip()
        narration = step.narration
        action_hint = str(getattr(step, "action_hint", "") or "").strip()
        if action_hint:
            narration = f"{narration} Try this: {action_hint}."
        try:
            self.on_tts_preview(narration, speed, voice, quant)
        except Exception as exc:
            logging.error("Tutorial TTS playback failed: %s", exc)

    def _tour_close(self, _event):
        if self._tour_intro_dialog is not None:
            self._close_dialog(key=self.MODAL_KEY_TOUR_INTRO)
            self._tour_intro_dialog = None
        if self._tour_bar:
            self._tour_bar.visible = False
        self._tour_in_intro = False
        self._highlight_tour_target("")
        if callable(self.on_tts_stop):
            try:
                self.on_tts_stop()
            except Exception:
                pass
        self._safe_update()

