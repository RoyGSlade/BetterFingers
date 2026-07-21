"""Static contract tests for The Lost Meaning game client (board #41, task #3).

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
    "your-hero-panel",
    "your-hero-name",
    "your-hero-persona",
    "your-hero-ability",
    "your-hero-cards",
    "start-button",
    "lobby-status",
    "round-screen",
    "spotlight-banner",
    "spotlight-round",
    "spotlight-name",
    "objective-art",
    "objective-name",
    "objective-description",
    "hearts-display",
    "players-roster",
    "private-panel",
    "private-clue",
    "your-hero-hand-panel",
    "your-hero-hand-cards",
    "declared-action-panel",
    "declared-action-summary",
    "declared-action-approved",
    "declared-action-approved-text",
    "declared-action-approved-intent",
    "action-builder-panel",
    "action-target-select",
    "action-outcome-input",
    "action-outcome-count",
    "action-submit",
    "action-status",
    "support-panel",
    "support-items-hint",
    "support-detail",
    "support-detail-count",
    "support-submit",
    "support-status",
    "draft-panel",
    "draft-rough-text",
    "draft-rough-count",
    "draft-voice-button",
    "draft-voice-status",
    "draft-generate-button",
    "draft-loading",
    "draft-error",
    "variant-list",
    "draft-approval",
    "draft-edit-text",
    "draft-intent-text",
    "draft-approve-button",
    "draft-status",
    "reaction-panel",
    "reaction-message",
    "reaction-intent",
    "reaction-move-select",
    "reaction-detail",
    "reaction-detail-count",
    "reaction-submit",
    "reaction-status",
    "reveal-panel",
    "die-roll-display",
    "modifier-breakdown",
    "reveal-outcome",
    "revealed-clues-wrap",
    "revealed-clues-list",
    "round-log-wrap",
    "round-log-list",
    "reveal-narration",
    "reveal-continue-button",
    "reveal-status",
    "round-waiting-panel",
    "round-waiting-text",
    "host-opendraft-button",
    "host-resolve-button",
    "finale-screen",
    "finale-heading",
    "finale-summary",
    "finale-recap",
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
        self.assertIn("The Lost Meaning", INDEX_HTML)

    def test_only_local_stylesheet_and_script(self):
        link_hrefs = re.findall(r'<link[^>]+href="([^"]+)"', INDEX_HTML)
        self.assertEqual(link_hrefs, ["/art/game-icon.png", "/style.css"])
        self.assertTrue(all(href.startswith("/") for href in link_hrefs))
        script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', INDEX_HTML)
        self.assertEqual(script_srcs, ["/app.js"])

    def test_support_kind_choices_present(self):
        for kind in ("clue", "item", "assist", "reaction"):
            with self.subTest(kind=kind):
                self.assertIn('value="%s"' % kind, INDEX_HTML)

    def test_reaction_verb_choices_present(self):
        for verb in ("interpret", "assist", "challenge", "protect"):
            with self.subTest(verb=verb):
                self.assertIn('value="%s"' % verb, INDEX_HTML)

    def test_no_audio_or_video_elements(self):
        self.assertNotIn("<audio", INDEX_HTML.lower())
        self.assertNotIn("<video", INDEX_HTML.lower())

    def test_every_form_input_has_a_label(self):
        input_ids = re.findall(r'<(?:input|select|textarea)[^>]+id="([^"]+)"', INDEX_HTML)
        label_fors = set(re.findall(r'<label[^>]+for="([^"]+)"', INDEX_HTML))
        # inputs that are visually part of a styled radio "card" (move
        # cards, support kinds, reaction verbs) don't need their own
        # <label for>; they're wrapped by a labelling <label> tag built
        # dynamically or statically around them.
        exempt = {"move-card", "support-kind", "reaction-verb"}
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


class LostMeaningLoopTests(unittest.TestCase):
    """Confirms the frozen spotlight loop replaced the old simultaneous
    Charm/Scheme/Bonk reveal loop, and that the redesign's required UX
    beats are all represented in the client, aligned to the engine's
    authoritative phase enum (lobby -> spotlight_action -> ally_support ->
    spotlight_draft -> ally_reaction -> reveal -> finished)."""

    def test_old_simultaneous_move_form_is_gone(self):
        for old_id in ("move-form", "move-persona", "move-card", "move-text", "waiting-panel", "reveal-list", "advance-button", "character-screen", "character-form"):
            with self.subTest(old_id=old_id):
                self.assertNotIn('id="%s"' % old_id, INDEX_HTML)

    def test_exactly_three_variant_slots_enforced_in_js(self):
        self.assertIn("VARIANT_SLOT_COUNT = 3", APP_JS)
        self.assertIn("slice(0, VARIANT_SLOT_COUNT)", APP_JS)

    def test_variant_provenance_rendered(self):
        self.assertIn("variant-provenance", APP_JS)
        self.assertIn("provenance", APP_JS)

    def test_message_and_intent_are_separate_fields(self):
        self.assertIn('id="draft-edit-text"', INDEX_HTML)
        self.assertIn('id="draft-intent-text"', INDEX_HTML)

    def test_private_clue_is_you_scoped_and_hand_is_not_mislabeled_private(self):
        self.assertIn("viewModel.you.private_clue", APP_JS)
        # the hand/deck is public character-sheet info per the engine
        # contract -- it must not live inside the "private" clue panel.
        private_panel = re.search(r'<div id="private-panel".*?</div>', INDEX_HTML, re.S)
        self.assertIsNotNone(private_panel)
        self.assertNotIn("move-card-list", private_panel.group(0))

    def test_spotlight_rotation_is_derived_from_state(self):
        self.assertIn("spotlight_hero_id", APP_JS)

    def test_fixed_hero_roster_not_player_built(self):
        # heroes are auto-bound by join order (HERO_ROSTER); there is no
        # player-facing character builder/select-character flow.
        self.assertNotIn("select-character", APP_JS)
        self.assertNotIn("FALLBACK_ARCHETYPES", APP_JS)

    def test_normalize_state_isolates_the_server_contract(self):
        self.assertIn("function normalizeState(raw)", APP_JS)
        # every render function should read the normalized view-model, not
        # the raw payload, so the real contract can land without touching
        # layout/render code (see collab-workspace coordination notes).
        self.assertIn("function renderRound(viewModel)", APP_JS)

    def test_model_free_draft_states_present(self):
        self.assertIn("draft-loading", APP_JS)
        self.assertIn("draft-error", APP_JS)

    def test_host_gated_phase_advances_present(self):
        # ally_support -> spotlight_draft and ally_reaction -> reveal are
        # both explicit host actions (open_draft/resolve), not automatic.
        self.assertIn("host-opendraft-button", APP_JS)
        self.assertIn("host-resolve-button", APP_JS)

    def test_voice_profile_is_bounded_metadata_only(self):
        self.assertIn("utterance_count", APP_JS)
        self.assertNotIn("getUserMedia", APP_JS)

    def test_action_routes_match_the_final_server_contract(self):
        for route in ("/spotlight", "/support", "/open-draft", "/draft", "/approve", "/react", "/voice-profile", "/resolve", "/advance", "/replay"):
            with self.subTest(route=route):
                self.assertIn('"%s"' % route, APP_JS)
        for obsolete_guess in ("/spotlight-action", "/ally-support", "/approve-message", "/ally-reaction"):
            with self.subTest(obsolete_guess=obsolete_guess):
                self.assertNotIn('"%s"' % obsolete_guess, APP_JS)

    def test_pending_steps_match_the_engine_contract(self):
        for step in ("declare_action", "submit_support", "submit_rough_text", "awaiting_variants", "approve_message", "submit_reaction"):
            with self.subTest(step=step):
                self.assertIn('"%s"' % step, APP_JS)


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
        self.assertIn("The Lost Meaning", resp.text)

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
        # game-icon.png is the one art key guaranteed stable across the
        # engine/server rewrite (used for the page favicon); this test is
        # about the fixed-allowlist serving mechanism, not any one
        # filename -- the exact encounter/card art keys are still being
        # finalized by lost-meaning-server.
        resp = self._client().get("/art/game-icon.png")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/png")
        self.assertEqual(resp.headers["cache-control"], "public, max-age=3600")
        self.assertGreater(len(resp.content), 1000)

    def test_unknown_art_name_is_not_exposed(self):
        resp = self._client().get("/art/secrets.png")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
