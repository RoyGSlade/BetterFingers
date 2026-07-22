"""Static contract tests for the Infinite Stacks client (board task #3).

Pure static-analysis checks over backend/lan_playground/static/stacks.html
and static/src/** -- no browser, no engine routes exercised. Style in the
tests/test_lan_game_static.py mold: assert on required markup/JS shape
directly, not on behavior a browser would need to execute.
"""

import re
import unittest
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "backend" / "lan_playground" / "static"
SRC_DIR = STATIC_DIR / "src"

STACKS_HTML = (STATIC_DIR / "stacks.html").read_text(encoding="utf-8")

MAIN_JS = (SRC_DIR / "main.js").read_text(encoding="utf-8")
STACKS_CSS = (SRC_DIR / "stacks.css").read_text(encoding="utf-8")

CORE_FILES = ["api.js", "socket.js", "store.js", "commands.js", "selectors.js"]
COMPONENT_FILES = ["die.js", "room-tile.js", "hero.js"]
SCREEN_FILES = ["map.js"]

CORE_SOURCE = {name: (SRC_DIR / "core" / name).read_text(encoding="utf-8") for name in CORE_FILES}
COMPONENT_SOURCE = {name: (SRC_DIR / "components" / name).read_text(encoding="utf-8") for name in COMPONENT_FILES}
SCREEN_SOURCE = {name: (SRC_DIR / "screens" / name).read_text(encoding="utf-8") for name in SCREEN_FILES}


class HtmlContractTests(unittest.TestCase):
    def test_required_ids_present(self):
        required_ids = [
            "join-panel",
            "access-code-input",
            "room-code-input",
            "create-room-button",
            "join-room-button",
            "join-status",
            "map-screen",
        ]
        for element_id in required_ids:
            with self.subTest(element_id=element_id):
                self.assertIn('id="%s"' % element_id, STACKS_HTML, "missing required element #%s" % element_id)

    def test_j1_join_screen_does_not_collect_hero_identity(self):
        # wavebasedgame.md S3.1 "J1": joining must be minimal -- hero
        # identity (a name) belongs in the character-builder screen's own
        # name field (stacks-builder-name-input), not the join panel.
        self.assertNotIn("display-name-input", STACKS_HTML)
        self.assertNotIn("Your hero's name", STACKS_HTML)

    def test_title_names_the_game(self):
        self.assertIn("Infinite Stacks", STACKS_HTML)

    def test_only_local_stylesheet_and_module_script(self):
        link_hrefs = re.findall(r'<link[^>]+href="([^"]+)"', STACKS_HTML)
        self.assertTrue(all(href.startswith("/") for href in link_hrefs), link_hrefs)
        script_srcs = re.findall(r'<script[^>]+src="([^"]+)"', STACKS_HTML)
        self.assertEqual(script_srcs, ["/src/main.js"])
        self.assertIn('type="module"', STACKS_HTML)

    def test_no_inline_style_or_script_content(self):
        # The app's CSP (backend/lan_playground/security.py SECURITY_HEADERS)
        # is style-src 'self' / script-src 'self' with no 'unsafe-inline' --
        # an inline style="" attribute or a <script> body would be silently
        # dropped by the browser, so this is a real functional contract.
        self.assertNotIn("style=", STACKS_HTML)
        self.assertNotRegex(STACKS_HTML, r"<script(?![^>]*\bsrc=)[^>]*>\s*\S")

    def test_every_form_input_has_a_label(self):
        input_ids = re.findall(r'<(?:input|select|textarea)[^>]+id="([^"]+)"', STACKS_HTML)
        label_fors = set(re.findall(r'<label[^>]+for="([^"]+)"', STACKS_HTML))
        for input_id in input_ids:
            with self.subTest(input_id=input_id):
                self.assertIn(input_id, label_fors, "input #%s has no associated <label>" % input_id)

    def test_no_audio_or_video_elements(self):
        self.assertNotIn("<audio", STACKS_HTML.lower())
        self.assertNotIn("<video", STACKS_HTML.lower())

    def test_has_skip_link(self):
        self.assertIn('class="skip-link"', STACKS_HTML)

    def test_map_screen_starts_hidden(self):
        # Only the join flow should be visible before a run exists.
        self.assertRegex(STACKS_HTML, r'<section id="map-screen"[^>]*\bhidden\b')


class NoInlineStyleAssignmentTests(unittest.TestCase):
    """CSP style-src 'self' (no 'unsafe-inline') blocks `.style.` assignment
    the same as a literal style="" attribute -- every module must place
    elements via CSS classes instead (see screens/map.js's stacks-col-N /
    stacks-row-N utility classes)."""

    def test_no_module_sets_inline_style_properties(self):
        all_source = {**CORE_SOURCE, **COMPONENT_SOURCE, **SCREEN_SOURCE, "main.js": MAIN_JS}
        for name, source in all_source.items():
            with self.subTest(file=name):
                self.assertNotRegex(source, r"\.style\.\w+\s*=", "%s sets an inline style property" % name)
                self.assertNotIn(".style.cssText", source)


class ModuleShapeTests(unittest.TestCase):
    def test_core_modules_present_and_exported(self):
        self.assertIn("export function createStore", CORE_SOURCE["store.js"])
        self.assertIn("export function createInitialState", CORE_SOURCE["store.js"])
        self.assertIn("export function reduceServerMessage", CORE_SOURCE["store.js"])
        self.assertIn("export function createStacksSocket", CORE_SOURCE["socket.js"])
        self.assertIn("export async function createRoom", CORE_SOURCE["api.js"])
        self.assertIn("export async function fetchSnapshot", CORE_SOURCE["api.js"])
        self.assertIn("export async function submitCommandOverRest", CORE_SOURCE["api.js"])
        self.assertIn("export function moveCommand", CORE_SOURCE["commands.js"])
        self.assertIn("export function breachCommand", CORE_SOURCE["commands.js"])
        self.assertIn("export function selectTiles", CORE_SOURCE["selectors.js"])
        self.assertIn("export function selectHeroCards", CORE_SOURCE["selectors.js"])
        self.assertIn("export function energyPips", CORE_SOURCE["selectors.js"])
        self.assertIn("export function selectRoutePreview", CORE_SOURCE["selectors.js"])

    def test_component_modules_export_render_functions(self):
        self.assertIn("export function renderDie", COMPONENT_SOURCE["die.js"])
        self.assertIn("export function renderRoomTile", COMPONENT_SOURCE["room-tile.js"])
        self.assertIn("export function renderHeroCard", COMPONENT_SOURCE["hero.js"])

    def test_map_screen_exports_render_function(self):
        self.assertIn("export function renderMapScreen", SCREEN_SOURCE["map.js"])

    def test_die_component_supports_reduced_motion(self):
        self.assertIn("reducedMotion", COMPONENT_SOURCE["die.js"])
        self.assertIn("stacks-die--instant", COMPONENT_SOURCE["die.js"])

    def test_die_component_never_generates_randomness(self):
        # infinite_stacks.md S24.2: "the client never determines authoritative
        # randomness." The die component may only ever display a value it
        # was handed.
        for forbidden in ("Math.random", "crypto.getRandomValues"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, COMPONENT_SOURCE["die.js"])

    def test_no_client_module_generates_randomness_for_gameplay(self):
        # commands.js uses Math.random only as a UUID-fallback id generator
        # (network/dedupe concern, not a gameplay outcome), which is fine;
        # nothing gameplay-facing (selectors/components/screens/store) may.
        for name, source in {**COMPONENT_SOURCE, **SCREEN_SOURCE, "selectors.js": CORE_SOURCE["selectors.js"], "store.js": CORE_SOURCE["store.js"]}.items():
            with self.subTest(file=name):
                self.assertNotIn("Math.random", source)

    def test_room_tile_labels_every_connector_state_not_color_only(self):
        # S24.1/S25: connector state must never be color-only.
        source = COMPONENT_SOURCE["room-tile.js"]
        self.assertIn("connector.label", source)

    def test_hero_card_labels_energy_and_danger_not_color_only(self):
        source = COMPONENT_SOURCE["hero.js"]
        self.assertIn("aria-label", source)
        self.assertIn("danger.label", source)

    def test_components_do_not_call_network_or_store_apis(self):
        forbidden_patterns = ["fetch(", "new WebSocket", "createStore(", "setTimeout(", "setInterval("]
        for name, source in {**COMPONENT_SOURCE, **SCREEN_SOURCE}.items():
            for pattern in forbidden_patterns:
                with self.subTest(file=name, pattern=pattern):
                    self.assertNotIn(pattern, source)

    def test_core_transport_modules_never_touch_the_dom(self):
        forbidden_patterns = ["document.createElement", "document.getElementById", "document.querySelector"]
        for name in ("api.js", "socket.js", "store.js", "commands.js"):
            source = CORE_SOURCE[name]
            for pattern in forbidden_patterns:
                with self.subTest(file=name, pattern=pattern):
                    self.assertNotIn(pattern, source)

    def test_api_module_never_touches_cookies_or_local_storage(self):
        # Strip comment lines first -- the module's own header comment
        # names these APIs to describe the constraint, which isn't a usage.
        code_lines = [line for line in CORE_SOURCE["api.js"].splitlines() if not line.strip().startswith("//")]
        code_only = "\n".join(code_lines)
        for forbidden in ("document.cookie", "localStorage", "sessionStorage"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, code_only)


class WiringTests(unittest.TestCase):
    def test_main_js_is_the_only_module_touching_dom_and_network_together(self):
        self.assertIn("fetch", MAIN_JS + CORE_SOURCE["api.js"])  # sanity: fetch exists somewhere
        for name in COMPONENT_FILES:
            with self.subTest(file=name):
                self.assertNotIn("fetch(", COMPONENT_SOURCE[name])
        for name in SCREEN_FILES:
            with self.subTest(file=name):
                self.assertNotIn("fetch(", SCREEN_SOURCE[name])

    def test_main_js_imports_screen_and_core_modules(self):
        self.assertIn('from "./screens/map.js"', MAIN_JS)
        self.assertIn('from "./core/store.js"', MAIN_JS)
        self.assertIn('from "./core/socket.js"', MAIN_JS)
        self.assertIn('from "./core/api.js"', MAIN_JS)
        self.assertIn('from "./core/commands.js"', MAIN_JS)

    def test_main_js_falls_back_to_rest_when_socket_send_fails(self):
        self.assertIn("submitCommandOverRest", MAIN_JS)

    def test_main_js_watches_prefers_reduced_motion(self):
        self.assertIn("prefers-reduced-motion", MAIN_JS)


class CssContractTests(unittest.TestCase):
    def test_focus_visible_style_present_for_keyboard_navigation(self):
        self.assertIn(":focus-visible", STACKS_CSS)

    def test_grid_placement_utility_classes_cover_wave1_room_cap(self):
        # maximum_rooms = min(6 + floor_index, 12) + 3 <= 15 (infinite_stacks.md
        # S7.3); the generated utility classes must comfortably exceed that.
        for n in (1, 15, 24):
            with self.subTest(n=n):
                self.assertIn(".stacks-col-%d {" % n, STACKS_CSS)
                self.assertIn(".stacks-row-%d {" % n, STACKS_CSS)

    def test_reduced_motion_media_query_present(self):
        self.assertIn("prefers-reduced-motion", STACKS_CSS)


if __name__ == "__main__":
    unittest.main()
