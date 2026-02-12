import unittest
from unittest.mock import patch

from settings import SettingsWindow


class _FakeUrlLauncher:
    def __init__(self):
        self.calls = []

    async def launch_url(self, url):
        self.calls.append(url)


class _PageWithRunTaskLauncher:
    def __init__(self):
        self.url_launcher = _FakeUrlLauncher()
        self.calls = []

    def run_task(self, handler, *args, **kwargs):
        del kwargs
        self.calls.append((handler, args))
        return None


class _PageWithLegacyAsyncLaunch:
    def launch_url(self, _url):
        async def _coro():
            return None

        return _coro()


class SettingsExternalUrlTests(unittest.TestCase):
    def _window(self):
        return SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )

    def test_uses_page_run_task_url_launcher_when_available(self):
        window = self._window()
        page = _PageWithRunTaskLauncher()
        window._page = page

        opened = window._open_external_url("https://ko-fi.com/democratizegm")

        self.assertTrue(opened)
        self.assertEqual(len(page.calls), 1)
        handler, args = page.calls[0]
        self.assertEqual(handler, page.url_launcher.launch_url)
        self.assertEqual(args, ("https://ko-fi.com/democratizegm",))

    @patch("settings.webbrowser.open", return_value=True)
    @patch("settings.os.startfile", side_effect=OSError("blocked"))  # type: ignore[attr-defined]
    @patch("asyncio.run", side_effect=RuntimeError("loop unavailable"))
    def test_falls_back_to_webbrowser_when_legacy_async_launch_cannot_schedule(
        self,
        _asyncio_run,
        _startfile,
        web_open,
    ):
        window = self._window()
        window._page = _PageWithLegacyAsyncLaunch()

        opened = window._open_external_url("https://ko-fi.com/democratizegm")

        self.assertTrue(opened)
        web_open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
