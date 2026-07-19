"""Static contract tests for the Spellcheck & Sorcery game client (board #41).

These are pure static-analysis checks over backend/lan_playground/static/
{index.html,app.js,style.css} -- no browser, no game-server/engine routes
are exercised (those are owned by other sessions and may not exist yet).
The only Python surface touched is the *existing, unmodified* static file
routes on backend.lan_playground.app.create_app (`/`, `/app.js`,
`/style.css`), used only to confirm they still serve exactly what's on disk.
"""

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend.lan_playground.app import create_app

STATIC_DIR = Path(__file__).resolve().parent.parent / "backend" / "lan_playground" / "static"
INDEX_HTML = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
APP_JS = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
STYLE_CSS = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
APP_JS_BYTES = (STATIC_DIR / "app.js").read_bytes()
STYLE_CSS_BYTES = (STATIC_DIR / "style.css").read_bytes()

REQUIRED_IDS = [
    "error-banner",
    "game-status",
    "fullscreen-toggle",
    "access-gate",
    "access-code-input",
    "access-code-submit",
    "access-gate-status",
    "home-screen",
    "create-form",
    "create-name",
    "join-form",
    "join-code-input",
    "join-name-input",
    "home-status",
    "lobby-screen",
    "lobby-code",
    "lobby-link",
    "copy-code-button",
    "copy-link-button",
    "lobby-qr",
    "lobby-players",
    "lobby-solo-hint",
    "start-button",
    "lobby-status",
    "board-screen",
    "board-canvas",
    "hearts-display",
    "players-roster",
    "move-form",
    "move-persona",
    "move-text",
    "move-text-count",
    "move-submit",
    "move-status",
    "waiting-panel",
    "waiting-count",
    "reveal-panel",
    "reveal-list",
    "round-summary",
    "advance-button",
    "finale-screen",
    "finale-heading",
    "finale-summary",
    "replay-button",
]


class RequiredElementsTests(unittest.TestCase):
    def test_every_required_id_present(self):
        for element_id in REQUIRED_IDS:
            with self.subTest(element_id=element_id):
                self.assertIn(
                    'id="%s"' % element_id,
                    INDEX_HTML,
                    "missing required element #%s" % element_id,
                )

    def test_title_names_the_game(self):
        self.assertIn("Spellcheck", INDEX_HTML)
        self.assertIn("Sorcery", INDEX_HTML)

    def test_only_local_stylesheet_and_script(self):
        link_hrefs = re.findall(r'<link[^>]+href="([^"]+)"', INDEX_HTML)
        self.assertEqual(link_hrefs, ["/art/game-icon.png", "/style.css"])
        self.assertTrue(all(href.startswith("/") for href in link_hrefs))
        script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', INDEX_HTML)
        self.assertEqual(script_srcs, ["/app.js"])

    def test_secret_card_choices_present(self):
        for card in ("charm", "scheme", "bonk"):
            with self.subTest(card=card):
                self.assertIn('value="%s"' % card, INDEX_HTML)

    def test_canvas_has_accessible_role(self):
        canvas_tag = re.search(r"<canvas[^>]*>", INDEX_HTML).group(0)
        self.assertIn('role="img"', canvas_tag)

    def test_no_audio_or_video_elements(self):
        self.assertNotIn("<audio", INDEX_HTML.lower())
        self.assertNotIn("<video", INDEX_HTML.lower())

    def test_every_form_input_has_a_label(self):
        input_ids = re.findall(r'<(?:input|select|textarea)[^>]+id="([^"]+)"', INDEX_HTML)
        label_fors = set(re.findall(r'<label[^>]+for="([^"]+)"', INDEX_HTML))
        # inputs that are visually part of a styled radio "card" don't need
        # their own <label for>; they're wrapped by a labelling <label> tag.
        exempt = {"move-card"}
        for input_id in input_ids:
            if input_id in exempt:
                continue
            with self.subTest(input_id=input_id):
                self.assertIn(input_id, label_fors, "input #%s has no associated <label>" % input_id)


class NoNetworkOrStorageTests(unittest.TestCase):
    def test_no_external_urls_anywhere(self):
        for name, text in (("index.html", INDEX_HTML), ("app.js", APP_JS), ("style.css", STYLE_CSS)):
            with self.subTest(file=name):
                self.assertNotIn("://", text, "%s references an absolute/external URL" % name)

    def test_no_web_storage_or_cookies(self):
        # matches actual usage (localStorage.setItem/[...]), not the word
        # appearing in an explanatory comment.
        for forbidden in (r"\blocalStorage\s*[.\[]", r"\bsessionStorage\s*[.\[]", r"document\.cookie\s*="):
            with self.subTest(forbidden=forbidden):
                self.assertNotRegex(APP_JS, forbidden)

    def test_no_microphone_or_speech_apis(self):
        for forbidden in ("getUserMedia", "SpeechSynthesis", "webkitSpeechRecognition", "MediaRecorder"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, APP_JS)

    def test_fetch_calls_are_relative_paths_only(self):
        fetch_targets = re.findall(r"fetch\(\s*([^,)]+)", APP_JS)
        self.assertTrue(fetch_targets, "expected at least one fetch() call in app.js")
        for target in fetch_targets:
            with self.subTest(target=target):
                # every call site passes a variable/template built from a
                # literal "/api/..." or "/app.js"-style relative path, never
                # a bare "http..." literal.
                self.assertNotRegex(target, r'^["\']https?://')


class UserTextRenderingTests(unittest.TestCase):
    def test_innerhtml_only_used_to_clear_not_to_insert(self):
        assignments = re.findall(r"\.innerHTML\s*=\s*([^;]+);", APP_JS)
        self.assertTrue(assignments, "expected at least one .innerHTML clearing assignment")
        for value in assignments:
            with self.subTest(value=value):
                self.assertEqual(
                    value.strip(),
                    '""',
                    "app.js must only ever clear innerHTML (set to \"\"), never insert content with it",
                )

    def test_no_insertadjacenthtml(self):
        self.assertNotIn("insertAdjacentHTML", APP_JS)

    def test_no_document_write(self):
        self.assertNotIn("document.write", APP_JS)


class TestHookTests(unittest.TestCase):
    def test_render_game_to_text_exposed(self):
        self.assertIn("window.render_game_to_text = render_game_to_text", APP_JS)

    def test_advance_time_exposed(self):
        self.assertIn("window.advanceTime = advanceTime", APP_JS)

    def test_fullscreen_key_handler_present(self):
        self.assertIn('event.key === "f"', APP_JS)

    def test_escape_key_handler_present(self):
        self.assertIn('event.key === "Escape"', APP_JS)


class AccessCodeAndTokenHygieneTests(unittest.TestCase):
    def test_access_code_never_assigned_a_literal_default(self):
        # the only initializer should be the empty string -- it must come
        # from user input or the one-time ?code= query param, never a
        # hardcoded value.
        match = re.search(r"let accessCode = ([^;]+);", APP_JS)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1).strip(), '""')

    def test_url_code_and_room_params_are_stripped(self):
        self.assertIn("history.replaceState", APP_JS)
        self.assertIn('params.delete("code")', APP_JS)
        self.assertIn('params.delete("room")', APP_JS)


class ReducedMotionTests(unittest.TestCase):
    def test_css_honors_prefers_reduced_motion(self):
        self.assertIn("prefers-reduced-motion: reduce", STYLE_CSS)

    def test_js_checks_reduced_motion_preference(self):
        self.assertIn("prefers-reduced-motion: reduce", APP_JS)


class StaticFileServingTests(unittest.TestCase):
    """Confirms the game shell and fixed-allowlist art routes."""

    def _client(self):
        app = create_app(
            access_code="unused-in-these-routes",
            allowed_hosts={"testserver"},
            allowed_origins={"http://testserver"},
            call_fn=lambda messages: "{}",
            persona_lookup=lambda name: None,
            persona_allowlist=lambda: [],
        )
        return TestClient(app)

    def test_index_route_serves_the_game_shell(self):
        client = self._client()
        resp = client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Spellcheck", resp.text)

    def test_app_js_route_serves_current_file(self):
        client = self._client()
        resp = client.get("/app.js")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, APP_JS_BYTES)

    def test_style_css_route_serves_current_file(self):
        client = self._client()
        resp = client.get("/style.css")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, STYLE_CSS_BYTES)

    def test_allowlisted_art_is_served_and_cached(self):
        resp = self._client().get("/art/map.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/png")
        self.assertEqual(resp.headers["cache-control"], "public, max-age=3600")
        self.assertGreater(len(resp.content), 1000)

    def test_unknown_art_name_is_not_exposed(self):
        resp = self._client().get("/art/secrets.png")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
