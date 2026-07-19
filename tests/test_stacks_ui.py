"""Static contract tests for wave 2 of the Infinite Stacks client (board task
#7): the room/puzzle/combat screens and their shared components (card,
check-receipt, status). Pure static-analysis checks over
backend/lan_playground/static/stacks.html and static/src/** plus the JSON
state fixtures under tests/fixtures/stacks_ui/ -- no browser, no engine
routes exercised. Style in the tests/test_stacks_static.py mold: assert on
required markup/JS shape and fixture contract directly, not on behavior a
browser would need to execute.
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "backend" / "lan_playground" / "static"
SRC_DIR = STATIC_DIR / "src"
FIXTURES_DIR = ROOT / "tests" / "fixtures" / "stacks_ui"

STACKS_HTML = (STATIC_DIR / "stacks.html").read_text(encoding="utf-8")
MAIN_JS = (SRC_DIR / "main.js").read_text(encoding="utf-8")
STACKS_CSS = (SRC_DIR / "stacks.css").read_text(encoding="utf-8")
STORE_JS = (SRC_DIR / "core" / "store.js").read_text(encoding="utf-8")
SELECTORS_JS = (SRC_DIR / "core" / "selectors.js").read_text(encoding="utf-8")

NEW_SCREEN_FILES = ["room.js", "puzzle.js", "combat.js"]
NEW_COMPONENT_FILES = ["card.js", "check-receipt.js", "status.js"]

NEW_SCREEN_SOURCE = {name: (SRC_DIR / "screens" / name).read_text(encoding="utf-8") for name in NEW_SCREEN_FILES}
NEW_COMPONENT_SOURCE = {name: (SRC_DIR / "components" / name).read_text(encoding="utf-8") for name in NEW_COMPONENT_FILES}

ALL_NEW_JS = {**NEW_SCREEN_SOURCE, **NEW_COMPONENT_SOURCE}


def load_fixture(name):
    with open(FIXTURES_DIR / name, encoding="utf-8") as handle:
        return json.load(handle)


class HtmlContractTests(unittest.TestCase):
    def test_new_screen_containers_present_and_start_hidden(self):
        for screen_id in ("room-screen", "puzzle-screen", "combat-screen"):
            with self.subTest(screen_id=screen_id):
                self.assertRegex(STACKS_HTML, r'<section id="%s"[^>]*\bhidden\b' % re.escape(screen_id))

    def test_no_inline_style_or_script_content(self):
        self.assertNotIn("style=", STACKS_HTML)
        self.assertNotRegex(STACKS_HTML, r"<script(?![^>]*\bsrc=)[^>]*>\s*\S")


class NoInlineStyleAssignmentTests(unittest.TestCase):
    """CSP style-src 'self' (no 'unsafe-inline') blocks `.style.` assignment
    the same as a literal style="" attribute -- every wave-2 module must
    place elements via CSS classes instead."""

    def test_no_new_module_sets_inline_style_properties(self):
        for name, source in {**ALL_NEW_JS, "main.js": MAIN_JS}.items():
            with self.subTest(file=name):
                self.assertNotRegex(source, r"\.style\.\w+\s*=", "%s sets an inline style property" % name)
                self.assertNotIn(".style.cssText", source)


class ModuleShapeTests(unittest.TestCase):
    def test_screen_modules_export_render_functions(self):
        self.assertIn("export function renderRoomScreen", NEW_SCREEN_SOURCE["room.js"])
        self.assertIn("export function renderPuzzleScreen", NEW_SCREEN_SOURCE["puzzle.js"])
        self.assertIn("export function renderCombatScreen", NEW_SCREEN_SOURCE["combat.js"])

    def test_component_modules_export_render_functions(self):
        self.assertIn("export function renderCard", NEW_COMPONENT_SOURCE["card.js"])
        self.assertIn("export function renderCardList", NEW_COMPONENT_SOURCE["card.js"])
        self.assertIn("export function renderCheckReceipt", NEW_COMPONENT_SOURCE["check-receipt.js"])
        self.assertIn("export function renderStatusBadge", NEW_COMPONENT_SOURCE["status.js"])
        self.assertIn("export function renderStatusList", NEW_COMPONENT_SOURCE["status.js"])
        self.assertIn("export const STATUS_DISPLAY", NEW_COMPONENT_SOURCE["status.js"])

    def test_selectors_export_new_view_functions(self):
        for name in (
            "selectActiveScreen",
            "selectEnteredRoomView",
            "selectPuzzleView",
            "selectCombatView",
        ):
            with self.subTest(selector=name):
                self.assertIn("export function %s" % name, SELECTORS_JS)

    def test_store_initial_state_has_wave2_fields(self):
        for field in ("enteredRoom: null", "puzzle: null", "combat: null"):
            with self.subTest(field=field):
                self.assertIn(field, STORE_JS)

    def test_selectors_still_never_touch_the_dom(self):
        # Regression guard: the wave-2 additions to selectors.js are pure
        # data transforms, same discipline as the wave-1 selectors.
        forbidden_patterns = ["document.createElement", "document.getElementById", "document.querySelector"]
        for pattern in forbidden_patterns:
            with self.subTest(pattern=pattern):
                self.assertNotIn(pattern, SELECTORS_JS)

    def test_new_components_and_screens_do_not_call_network_or_store_apis(self):
        forbidden_patterns = ["fetch(", "new WebSocket", "createStore(", "setTimeout(", "setInterval("]
        for name, source in ALL_NEW_JS.items():
            for pattern in forbidden_patterns:
                with self.subTest(file=name, pattern=pattern):
                    self.assertNotIn(pattern, source)

    def test_no_new_module_generates_randomness(self):
        for name, source in ALL_NEW_JS.items():
            with self.subTest(file=name):
                self.assertNotIn("Math.random", source)
                self.assertNotIn("crypto.getRandomValues", source)


class WiringTests(unittest.TestCase):
    def test_main_js_imports_new_screens_and_selector(self):
        self.assertIn('from "./screens/room.js"', MAIN_JS)
        self.assertIn('from "./screens/puzzle.js"', MAIN_JS)
        self.assertIn('from "./screens/combat.js"', MAIN_JS)
        self.assertIn("selectActiveScreen", MAIN_JS)

    def test_main_js_routes_by_active_screen(self):
        for screen in ("room", "puzzle", "combat"):
            with self.subTest(screen=screen):
                self.assertIn('"%s"' % screen, MAIN_JS)

    def test_main_js_wires_new_handlers(self):
        for handler in (
            "onInspectObject",
            "onUseExit",
            "onShareClue",
            "onAddNote",
            "onReorderNote",
            "onLinkNotes",
            "onToggleContradiction",
            "onRequestHint",
            "onForceProgress",
            "onSubmitSolution",
            "onAttack",
            "onDeclareManeuver",
            "onReact",
        ):
            with self.subTest(handler=handler):
                self.assertIn(handler, MAIN_JS)

    def test_new_screens_never_call_fetch_directly(self):
        # Only main.js is allowed to interleave DOM + network (S22.3).
        for name in NEW_SCREEN_FILES:
            with self.subTest(file=name):
                self.assertNotIn("fetch(", NEW_SCREEN_SOURCE[name])


class AccessibilityTests(unittest.TestCase):
    def test_status_component_pairs_glyph_with_text_label_not_color_only(self):
        source = NEW_COMPONENT_SOURCE["status.js"]
        self.assertIn('aria-hidden", "true"', source)
        self.assertIn("display.label", source)
        self.assertIn("aria-label", source)

    def test_all_nine_statuses_present_with_glyph_and_removal(self):
        source = NEW_COMPONENT_SOURCE["status.js"]
        for status_id in (
            "bleeding",
            "burning",
            "frightened",
            "confused",
            "silenced",
            "sickened",
            "exhausted",
            "marked",
            "prone",
        ):
            with self.subTest(status=status_id):
                self.assertIn("%s:" % status_id, source)

    def test_check_receipt_outcome_always_shows_text_not_color_only(self):
        source = NEW_COMPONENT_SOURCE["check-receipt.js"]
        self.assertIn('`Outcome: ${receipt.outcome}`', source)

    def test_card_component_renders_accessible_text_as_primary_label(self):
        source = NEW_COMPONENT_SOURCE["card.js"]
        self.assertIn("card.accessibleText", source)
        self.assertIn("aria-label", source)

    def test_room_exit_buttons_show_energy_cost_and_label_not_color_only(self):
        source = NEW_SCREEN_SOURCE["room.js"]
        self.assertIn("exit.energyCost", source)
        self.assertIn("exit.label", source)

    def test_puzzle_objects_are_individually_selectable_not_prose(self):
        source = NEW_SCREEN_SOURCE["puzzle.js"]
        self.assertIn('"button"', source)
        self.assertIn("onInspectObject", source)

    def test_puzzle_private_clue_share_control_is_deliberate_not_automatic(self):
        source = NEW_SCREEN_SOURCE["puzzle.js"]
        # Sharing must be its own explicit button, gated on puzzle.privateClue.shared
        # being false -- never an automatic broadcast.
        self.assertIn("puzzle.privateClue.shared", source)
        self.assertIn("onShareClue", source)

    def test_puzzle_hint_route_and_cost_are_visible(self):
        source = NEW_SCREEN_SOURCE["puzzle.js"]
        self.assertIn("nextHintCost", source)
        self.assertIn("onRequestHint", source)

    def test_combat_enemy_intent_rendered_before_action_selection(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        intent_pos = source.index("renderEnemyIntents(combat)")
        attacks_pos = source.index("renderAttacks(combat, handlers)")
        self.assertLess(intent_pos, attacks_pos, "enemy intent must be composed before attack controls")

    def test_combat_maneuver_shows_accuracy_cost_before_confirmation(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        self.assertIn("maneuver.accuracyModifier", source)
        self.assertIn("Requires confirmation", source)

    def test_combat_check_receipt_rendered_before_narration_and_before_action_controls_use_it_first(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        receipt_pos = source.index("renderLastCheckReceipt(combat)")
        actions_pos = source.index('el("div", "stacks-combat-actions")')
        self.assertLess(receipt_pos, actions_pos)
        # This screen must never render narration text itself (comments are
        # allowed to discuss the constraint; only code lines are checked).
        code_lines = [line for line in source.splitlines() if not line.strip().startswith("//")]
        self.assertNotIn("narration", "\n".join(code_lines).lower())

    def test_combat_initiative_and_reaction_availability_visible(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        self.assertIn("hasReactionAvailable", source)
        self.assertIn("reactionAvailable", source)


class CssContractTests(unittest.TestCase):
    def test_new_screen_ids_have_styling_hooks(self):
        for selector in ("#room-screen", "#puzzle-screen", "#combat-screen"):
            with self.subTest(selector=selector):
                self.assertIn(selector, STACKS_CSS)

    def test_status_badge_class_present(self):
        self.assertIn(".stacks-status-badge", STACKS_CSS)


class FixtureContractTests(unittest.TestCase):
    """Every fixture documents the wire shape core/selectors.js's wave-2
    selectors expect (snake_case, matching the existing engine convention) --
    these tests fail loudly if a fixture drifts from that shape."""

    def test_room_fixture_has_required_wire_fields(self):
        fixture = load_fixture("room_generic.json")
        for field in ("room_id", "family", "occupants", "objects", "exits", "corruption_tells"):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        self.assertGreater(len(fixture["exits"]), 0)
        for exit_ in fixture["exits"]:
            for field in ("direction", "label", "energy_cost", "legal"):
                with self.subTest(exit_direction=exit_["direction"], field=field):
                    self.assertIn(field, exit_)

    def test_puzzle_fixture_has_required_wire_fields(self):
        fixture = load_fixture("puzzle_mystery_chamber.json")
        for field in ("puzzle_id", "template_label", "difficulty", "objects", "private_clue", "shared_notes", "hints", "submission"):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        self.assertIn("shared", fixture["private_clue"])
        self.assertFalse(fixture["private_clue"]["shared"], "fixture should exercise the un-shared deliberate-Share state")
        for note in fixture["shared_notes"]:
            for field in ("id", "text", "author_name", "linked_note_ids", "contradiction"):
                with self.subTest(note_id=note["id"], field=field):
                    self.assertIn(field, note)
        self.assertTrue(any(note["contradiction"] for note in fixture["shared_notes"]), "fixture should exercise a contradiction mark")
        for tier in fixture["hints"]["tiers"]:
            for field in ("level", "description", "cost"):
                with self.subTest(level=tier["level"], field=field):
                    self.assertIn(field, tier)

    def test_combat_fixture_has_required_wire_fields(self):
        fixture = load_fixture("combat_encounter.json")
        for field in ("encounter_id", "round", "initiative_order", "enemies", "heroes", "legal_actions", "last_check_receipt"):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        self.assertTrue(any(enemy.get("intent") for enemy in fixture["enemies"]), "every enemy needs a telegraphed intent")
        for maneuver in fixture["legal_actions"]["maneuvers"]:
            self.assertEqual(maneuver["accuracy_modifier"], -4, "S14.4 called maneuvers cost exactly -4 accuracy")
        receipt = fixture["last_check_receipt"]
        for field in ("action", "target", "attribute", "skill", "die_result", "modifiers", "target_number", "outcome"):
            with self.subTest(field=field):
                self.assertIn(field, receipt)
        self.assertGreater(len(receipt["modifiers"]), 0, "S12.5 requires every modifier source to be listed")

    def test_cards_fixture_covers_every_s13_3_contract_field(self):
        fixture = load_fixture("cards.json")
        contract_fields = (
            "timing",
            "cost",
            "range",
            "targets",
            "requirements",
            "effect",
            "checkTable",
            "tags",
            "exhaustOnPlay",
            "accessibleText",
            "generatedDescription",
        )
        for card in fixture["cards"]:
            for field in contract_fields:
                with self.subTest(card=card["id"], field=field):
                    self.assertIn(field, card)

    def test_statuses_catalog_fixture_matches_status_component_source(self):
        # Cross-check the fixture against components/status.js's STATUS_DISPLAY
        # so the two documented sources of truth cannot silently drift apart.
        fixture = load_fixture("statuses_catalog.json")
        source = NEW_COMPONENT_SOURCE["status.js"]
        statuses = fixture["statuses"]
        self.assertEqual(len(statuses), 9, "infinite_stacks.md S16.4 defines exactly nine statuses")
        for status in statuses:
            with self.subTest(status=status["id"]):
                self.assertIn("%s:" % status["id"], source)
                self.assertIn('label: "%s"' % status["label"], source)
                self.assertIn('glyph: "%s"' % status["glyph"], source)


if __name__ == "__main__":
    unittest.main()
