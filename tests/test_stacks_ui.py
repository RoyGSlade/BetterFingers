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

# Wave 5 (board task #17): character-builder screen + hand/inventory panel.
WAVE5_SCREEN_FILES = ["character-builder.js", "hero-panel.js"]
WAVE5_SCREEN_SOURCE = {name: (SRC_DIR / "screens" / name).read_text(encoding="utf-8") for name in WAVE5_SCREEN_FILES}
DIE_JS = (SRC_DIR / "components" / "die.js").read_text(encoding="utf-8")
COMMANDS_JS = (SRC_DIR / "core" / "commands.js").read_text(encoding="utf-8")
API_JS = (SRC_DIR / "core" / "api.js").read_text(encoding="utf-8")

# Wave 6 (board task #19, docs/PLAYTEST_FINDINGS_2026-07-19.md): entirely new
# component/screen files this wave, plus the existing files that changed
# significantly (map.js/room-tile.js/hero.js are still covered by
# test_stacks_static.py's wave-1 lists; hero-panel.js/character-builder.js
# by Wave5* above -- both re-read fresh from disk, so edits there are
# already exercised without needing a new list here).
WAVE6_COMPONENT_FILES = ["token.js", "confirm-dialog.js", "rules-overlay.js"]
WAVE6_SCREEN_FILES = ["character-panel.js"]
WAVE6_COMPONENT_SOURCE = {name: (SRC_DIR / "components" / name).read_text(encoding="utf-8") for name in WAVE6_COMPONENT_FILES}
WAVE6_SCREEN_SOURCE = {name: (SRC_DIR / "screens" / name).read_text(encoding="utf-8") for name in WAVE6_SCREEN_FILES}
ALL_WAVE6_JS = {**WAVE6_COMPONENT_SOURCE, **WAVE6_SCREEN_SOURCE}
ROOM_TILE_JS = (SRC_DIR / "components" / "room-tile.js").read_text(encoding="utf-8")
HERO_JS = (SRC_DIR / "components" / "hero.js").read_text(encoding="utf-8")
MAP_JS = (SRC_DIR / "screens" / "map.js").read_text(encoding="utf-8")
HERO_PANEL_JS = WAVE5_SCREEN_SOURCE["hero-panel.js"]
CHARACTER_BUILDER_JS = WAVE5_SCREEN_SOURCE["character-builder.js"]


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
        for field in ("enteredRoom: null", "puzzles: {}", "conflicts: {}"):
            with self.subTest(field=field):
                self.assertIn(field, STORE_JS)

    def test_selectors_read_puzzles_by_room_not_a_singular_slot(self):
        # Wave 3: state.puzzles is keyed by room_id (the real wire shape),
        # replacing the wave-2 provisional singular state.puzzle.
        self.assertIn("state.puzzles[roomId]", SELECTORS_JS)
        code_lines = [line for line in SELECTORS_JS.splitlines() if not line.strip().startswith("//")]
        self.assertNotIn("state.puzzle;", "\n".join(code_lines))
        self.assertNotIn("state.puzzle ", "\n".join(code_lines))

    def test_selectors_hero_danger_tier_covers_downed_stable_dead(self):
        # infinite_stacks.md S24.1 "hero portraits show ... health danger" +
        # S16: Downed -> Stable -> (revived) or permanent Dead.
        for tier in ("downed", "stable", "dead"):
            with self.subTest(tier=tier):
                self.assertIn('"%s"' % tier, SELECTORS_JS)
        self.assertIn("life_state", SELECTORS_JS)
        self.assertIn("heroInCombat", SELECTORS_JS)

    def test_store_exports_client_local_puzzle_note_actions(self):
        # Clue Share + shared notes are client-side only this wave (task #10
        # constraint: no server share command exists) -- these are plain
        # state -> state functions, not sendCommand wrappers.
        for fn in ("export function shareClue", "export function addManualNote", "export function reorderManualNote", "export function linkManualNotes", "export function toggleManualNoteContradiction"):
            with self.subTest(fn=fn):
                self.assertIn(fn, STORE_JS)

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
            "onSubmitSolution",
            "onAttack",
            "onDeclareManeuver",
            "onReact",
        ):
            with self.subTest(handler=handler):
                self.assertIn(handler, MAIN_JS)

    def test_main_js_puzzle_commands_match_domain_vocabulary(self):
        # docs/INFINITE_STACKS_CONTRACTS.md S2: inspect_object/submit_solution/
        # request_hint are the only wave-2 puzzle commands; submit_solution's
        # payload key is "solution" (an ordered list), never "answer", and
        # there is no separate force_progress command.
        self.assertIn("inspectObjectCommand", MAIN_JS)
        self.assertIn("submitSolutionCommand", MAIN_JS)
        self.assertIn("requestHintCommand", MAIN_JS)
        self.assertNotIn("force_progress", MAIN_JS)
        self.assertNotIn('buildCommand("share_clue"', MAIN_JS)

    def test_commands_js_submit_solution_uses_solution_key(self):
        commands_js = (SRC_DIR / "core" / "commands.js").read_text(encoding="utf-8")
        self.assertIn('"submit_solution", { solution }', commands_js)
        self.assertIn('"inspect_object", { object_id: objectId }', commands_js)
        self.assertIn('"request_hint", {}', commands_js)

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
        # Sharing must be its own explicit button, gated on clue.shared being
        # false -- never an automatic broadcast. A hero can hold multiple
        # private clues (yourPrivateClues) plus object-discovered clues
        # (discoveredClues), each with its own independent share control.
        self.assertIn("clue.shared", source)
        self.assertIn("puzzle.yourPrivateClues", source)
        self.assertIn("puzzle.discoveredClues", source)
        self.assertIn("onShareClue", source)

    def test_puzzle_hint_route_is_visible(self):
        source = NEW_SCREEN_SOURCE["puzzle.js"]
        self.assertIn("hintsRevealed", source)
        self.assertIn("onRequestHint", source)

    def test_puzzle_submission_picks_real_item_ids_with_freeform_fallback(self):
        # Wave-3 close: submit_solution must send canonical wire item_ids when
        # puzzles[room_id].items is present (real solves are impossible with
        # prose-only entries), keeping the freeform text path only as the
        # no-items fallback.
        source = NEW_SCREEN_SOURCE["puzzle.js"]
        self.assertIn("stacks-puzzle-submission-picker", source)
        self.assertIn("stacks-puzzle-submission-item-add", source)
        self.assertIn("wireItem.itemId", source)
        self.assertIn("entry.itemId !== null ? entry.itemId : entry.label", source)
        # Freeform fallback stays for snapshots without an items list.
        self.assertIn("stacks-puzzle-submission-add-input", source)
        self.assertIn("itemId: item.item_id", SELECTORS_JS)

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
        # Real StacksEngineAdapter.project() shape, docs/INFINITE_STACKS_CONTRACTS.md
        # S5.2: snapshot.puzzles[room_id] = {instance_id, template_id,
        # difficulty, objects, solved, forced, attempts_used, attempt_limit,
        # hints_revealed, your_private_clues}. No private_clue (singular),
        # hints.tiers, or submission.slots -- those were the provisional
        # wave-2 shape this fixture replaces.
        fixture = load_fixture("puzzle_mystery_chamber.json")
        for field in (
            "instance_id",
            "template_id",
            "difficulty",
            "objects",
            "solved",
            "forced",
            "attempts_used",
            "attempt_limit",
            "hints_revealed",
            "your_private_clues",
            "items",
        ):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        for object_ in fixture["objects"]:
            for field in ("id", "role", "fallback", "accessible"):
                with self.subTest(object_id=object_["id"], field=field):
                    self.assertIn(field, object_)
        # Orderable solution items (wave-3 close): canonical wire ids the
        # submission picker sends in submit_solution, emitted lexicographic-
        # by-item_id so the projection order can never leak the answer.
        item_ids = [item["item_id"] for item in fixture["items"]]
        self.assertGreaterEqual(len(item_ids), 2)
        self.assertEqual(item_ids, sorted(item_ids), "fixture items must be lexicographic-by-item_id like the real wire")
        for item in fixture["items"]:
            for field in ("item_id", "fallback", "accessible"):
                with self.subTest(item_id=item["item_id"], field=field):
                    self.assertIn(field, item)
        for hint in fixture["hints_revealed"]:
            for field in ("fallback", "accessible"):
                with self.subTest(field=field):
                    self.assertIn(field, hint)
        self.assertGreaterEqual(
            len(fixture["your_private_clues"]), 2, "fixture should exercise MULTIPLE private clues assigned to one hero (S10.3 #8)"
        )
        for clue in fixture["your_private_clues"]:
            for field in ("clue_id", "fallback", "accessible"):
                with self.subTest(clue_id=clue["clue_id"], field=field):
                    self.assertIn(field, clue)

    def test_combat_fixture_has_required_wire_fields(self):
        # Real "conflict" per-room shape, per stacks-conflict's 17:15 wave-3
        # vocabulary post (board task #9, EARLY DRAFT): no legal_actions or
        # last_check_receipt on the wire itself -- those are folded
        # client-side from embedded combat/events.py event dicts
        # (core/store.js's applyConflictEvent), so this fixture only needs to
        # cover the projection fields, not the folded scratch.
        fixture = load_fixture("combat_encounter.json")
        for field in ("encounter_id", "status", "combat_round", "heroes", "enemies", "initiative_order", "current_turn"):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        for hero_id, hero in fixture["heroes"].items():
            for field in ("hp", "max_hp", "life_state", "position", "reaction_available"):
                with self.subTest(hero_id=hero_id, field=field):
                    self.assertIn(field, hero)
        for enemy_id, enemy in fixture["enemies"].items():
            for field in ("name", "hp", "max_hp", "alive", "position"):
                with self.subTest(enemy_id=enemy_id, field=field):
                    self.assertIn(field, enemy)
        self.assertIn(fixture["current_turn"], fixture["initiative_order"])

    def test_combat_fixture_intent_telegraph_matches_shipped_combat_package_payload(self):
        # combat/intents.py's telegraph_intent (accepted wave-2 code) emits
        # intent_id/telegraph_text/accessible_text/counterplay -- the
        # projection's own last_intent_telegraph fallback should carry the
        # same field names plus enemy_id so a client can attribute it.
        fixture = load_fixture("combat_encounter.json")
        telegraph = fixture["last_intent_telegraph"]
        for field in ("enemy_id", "intent_id", "telegraph_text", "accessible_text", "counterplay"):
            with self.subTest(field=field):
                self.assertIn(field, telegraph)
        self.assertIn(telegraph["enemy_id"], fixture["enemies"])

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


class Wave5ModuleShapeTests(unittest.TestCase):
    def test_character_builder_and_hero_panel_export_render_functions(self):
        self.assertIn("export function renderCharacterBuilderScreen", WAVE5_SCREEN_SOURCE["character-builder.js"])
        # Wave 6 (playtest A1/D2): hero-panel.js split renderHeroPanel into
        # renderHandDock (center-bottom hand dock) and renderInventoryPanel
        # (mounted inside the persistent character panel) -- see
        # Wave6ModuleShapeTests below for the full wave-6 contract.
        self.assertIn("export function renderHandDock", WAVE5_SCREEN_SOURCE["hero-panel.js"])
        self.assertIn("export function renderInventoryPanel", WAVE5_SCREEN_SOURCE["hero-panel.js"])

    def test_die_component_exports_attribute_die_and_never_generates_randomness(self):
        self.assertIn("export function renderAttributeDie", DIE_JS)
        for forbidden in ("Math.random", "crypto.getRandomValues"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, DIE_JS)

    def test_commands_js_exports_wave5_hero_commands(self):
        for fn in (
            "export function rollAttributeDiceCommand",
            "export function createHeroCommand",
            "export function drawCardsCommand",
            "export function playCardCommand",
            "export function safeRestCommand",
            "export function pickupItemCommand",
            "export function dropItemCommand",
            "export function tradeItemCommand",
            "export function recoverBodyLootCommand",
            "export function resolveReactionCommand",
        ):
            with self.subTest(fn=fn):
                self.assertIn(fn, COMMANDS_JS)

    def test_create_hero_command_sends_no_raw_numeric_modifier_fields(self):
        # infinite_stacks.md S24.2/S24.3: the client never determines
        # authoritative randomness or supplies a raw combat/check modifier.
        # attribute_assignment sends server-supplied DIE VALUES (already
        # public via attribute_dice_rolled), not an invented score.
        self.assertIn('background_id: backgroundId', COMMANDS_JS)
        self.assertIn("attribute_assignment: attributeAssignment", COMMANDS_JS)
        self.assertNotIn("accuracy_bonus", COMMANDS_JS)
        self.assertNotIn("damage_bonus", COMMANDS_JS)

    def test_resolve_reaction_command_carries_no_raw_numeric_modifier(self):
        # Replaces the wave-3 freeform combat_reaction command (which took
        # client-supplied incoming_attack_total/incoming_damage) with the
        # interrupt-window shape: only a reaction_id + reaction name. Comment
        # lines are allowed to name the fields being avoided; only code lines
        # are checked.
        self.assertIn('"resolve_reaction", { reaction_id: reactionId, reaction }', COMMANDS_JS)
        self.assertNotIn("combatReactionCommand", COMMANDS_JS)
        code_lines = [line for line in COMMANDS_JS.splitlines() if not line.strip().startswith("//")]
        code_only = "\n".join(code_lines)
        self.assertNotIn("incoming_attack_total", code_only)
        self.assertNotIn("incoming_damage", code_only)

    def test_api_js_exports_fetch_content_catalog(self):
        self.assertIn("export async function fetchContentCatalog", API_JS)

    def test_selectors_export_wave5_view_functions(self):
        for name in (
            "selectContentCatalog",
            "selectCharacterBuilderView",
            "computeDerivedStatsPreview",
            "selectHandView",
            "selectInventoryView",
        ):
            with self.subTest(selector=name):
                self.assertIn("export function %s" % name, SELECTORS_JS)

    def test_select_active_screen_routes_character_builder_before_a_sheet_exists(self):
        self.assertIn('return "character-builder"', SELECTORS_JS)

    def test_store_exports_content_catalog_and_character_draft_actions(self):
        for fn in ("export function setContentCatalog", "export function updateCharacterDraft"):
            with self.subTest(fn=fn):
                self.assertIn(fn, STORE_JS)
        self.assertIn("characterDraft:", STORE_JS)
        self.assertIn("contentCatalog: null", STORE_JS)

    def test_wave5_screens_never_call_network_or_store_apis_directly(self):
        forbidden_patterns = ["fetch(", "new WebSocket", "createStore(", "setTimeout(", "setInterval("]
        for name, source in WAVE5_SCREEN_SOURCE.items():
            for pattern in forbidden_patterns:
                with self.subTest(file=name, pattern=pattern):
                    self.assertNotIn(pattern, source)

    def test_wave5_screens_never_generate_randomness(self):
        for name, source in WAVE5_SCREEN_SOURCE.items():
            with self.subTest(file=name):
                self.assertNotIn("Math.random", source)
                self.assertNotIn("crypto.getRandomValues", source)

    def test_wave5_screens_never_set_inline_style_properties(self):
        for name, source in WAVE5_SCREEN_SOURCE.items():
            with self.subTest(file=name):
                self.assertNotRegex(source, r"\.style\.\w+\s*=", "%s sets an inline style property" % name)


class Wave5WiringTests(unittest.TestCase):
    def test_main_js_imports_character_builder_screen(self):
        self.assertIn('from "./screens/character-builder.js"', MAIN_JS)

    def test_main_js_has_character_builder_screen_container(self):
        self.assertIn('getElementById("character-builder-screen")', MAIN_JS)

    def test_main_js_wires_wave5_handlers(self):
        for handler in (
            "onRollAttributeDice",
            "onCreateHero",
            "onUpdateCharacterDraft",
            "onDrawCards",
            # Wave 6 (playtest A4): onPlayCard was replaced by the two-step
            # inspect/confirm flow (onInspectCard stages, onRequestPlayCard
            # stages a pendingAction, onConfirmPendingAction actually plays)
            # -- see Wave6WiringTests below.
            "onRequestPlayCard",
            "onSafeRest",
            "onPickupItem",
            "onDropItem",
            "onTradeItem",
            "onRecoverBodyLoot",
        ):
            with self.subTest(handler=handler):
                self.assertIn(handler, MAIN_JS)

    def test_main_js_fetches_content_catalog_on_entering_a_run(self):
        self.assertIn("fetchContentCatalog", MAIN_JS)
        self.assertIn("setContentCatalog", MAIN_JS)

    def test_html_declares_character_builder_screen_hidden(self):
        self.assertRegex(STACKS_HTML, r'<section id="character-builder-screen"[^>]*\bhidden\b')


class Wave5AccessibilityTests(unittest.TestCase):
    def test_character_builder_dice_assignment_uses_keyboard_navigable_selects(self):
        source = WAVE5_SCREEN_SOURCE["character-builder.js"]
        self.assertIn('document.createElement("select")', source)
        self.assertIn("aria-label", DIE_JS)

    def test_character_builder_background_shows_ability_text(self):
        source = WAVE5_SCREEN_SOURCE["character-builder.js"]
        self.assertIn("signature_ability", source)

    def test_character_builder_never_submits_until_selections_complete(self):
        source = WAVE5_SCREEN_SOURCE["character-builder.js"]
        self.assertIn("button.disabled = !canSubmit", source)

    def test_hand_cards_show_accessible_text_via_shared_card_component(self):
        source = WAVE5_SCREEN_SOURCE["hero-panel.js"]
        self.assertIn("renderCard(card", source)

    def test_reaction_prompt_gated_on_defender_or_protector_hero_id(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        self.assertIn("pending.defenderId === combat.yourHeroId", source)
        self.assertIn("pending.protectorIds.includes(combat.yourHeroId)", source)

    def test_reaction_prompt_surfaces_timeout_as_text(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        self.assertIn("stacks-combat-reaction-timer", source)

    def test_attack_buttons_show_expected_effect_facts_before_confirmation(self):
        source = NEW_SCREEN_SOURCE["combat.js"]
        self.assertIn("stacks-combat-attack-target-facts", source)
        self.assertIn("attack.weaponDieFaces", source)


class CssWave5ContractTests(unittest.TestCase):
    def test_new_screen_and_panel_ids_have_styling_hooks(self):
        for selector in ("#character-builder-screen", ".stacks-hand-panel", ".stacks-inventory-panel"):
            with self.subTest(selector=selector):
                self.assertIn(selector, STACKS_CSS)


class Wave5FixtureContractTests(unittest.TestCase):
    """content_catalog.json and hero_sheet.json document the wire shapes
    stacks_engine.py's content_catalog()/_neutral_hero_creation_snapshot()
    produce (docs/INFINITE_STACKS_CONTRACTS.md S5.4) -- these fail loudly if
    a fixture drifts from that shape, same discipline as the wave-2/3
    fixtures above."""

    def test_content_catalog_fixture_has_required_wire_fields(self):
        fixture = load_fixture("content_catalog.json")
        for background in fixture["backgrounds"].values():
            for field in ("id", "name", "fallback", "accessible", "attribute_bonus", "skill_ranks", "starting_item_ids", "signature_ability"):
                with self.subTest(background=background["id"], field=field):
                    self.assertIn(field, background)
            for field in ("id", "name", "fallback", "accessible", "frequency"):
                with self.subTest(background=background["id"], field=field):
                    self.assertIn(field, background["signature_ability"])
        for card in fixture["cards"].values():
            for field in ("id", "name", "fallback", "accessible", "accessible_text", "timing", "range", "legal_targets", "source", "live_at_creation"):
                with self.subTest(card=card["id"], field=field):
                    self.assertIn(field, card)
        for item in fixture["items"].values():
            for field in ("id", "name", "fallback", "accessible", "slot_cost", "tags"):
                with self.subTest(item=item["id"], field=field):
                    self.assertIn(field, item)

    def test_hero_sheet_fixture_has_required_wire_fields(self):
        fixture = load_fixture("hero_sheet.json")
        for field in ("pending_dice", "sheet", "deck", "hand", "inventory", "signature_charge"):
            with self.subTest(field=field):
                self.assertIn(field, fixture)
        sheet = fixture["sheet"]
        for field in ("hero_id", "name", "background_id", "dice", "attributes", "skills", "starting_item_ids", "derived"):
            with self.subTest(field=field):
                self.assertIn(field, sheet)
        for field in ("max_hp", "defense", "initiative_modifier", "carry_slots"):
            with self.subTest(field=field):
                self.assertIn(field, sheet["derived"])
        deck = fixture["deck"]
        for field in ("card_ids", "deck_count", "hand_count", "discard", "exhausted"):
            with self.subTest(field=field):
                self.assertIn(field, deck)
        # Hand contents only ever appear for the hero's OWN viewer -- proven
        # live over the wire by tests/test_stacks_api.py's
        # HeroCreationTests.test_hand_and_pending_dice_never_leak_to_another_viewer;
        # this fixture documents the own-viewer shape those tests exercise.
        self.assertIsInstance(fixture["hand"], list)
        self.assertGreater(len(fixture["hand"]), 0)
        self.assertEqual(fixture["deck"]["hand_count"], len(fixture["hand"]))

    def test_hero_sheet_fixture_has_wave6_token_ability_and_effect_fields(self):
        # Fixture-first per docs/PLAYTEST_FINDINGS_2026-07-19.md task #19 and
        # the room-chat contract with stacks-abilities (04:30): avatar_id/
        # color/abilities/active_effects/statuses on the hero wire.
        fixture = load_fixture("hero_sheet.json")
        self.assertIn(fixture["avatar_id"], range(1, 7))
        self.assertIn(fixture["color"], ("crimson", "azure", "gold", "violet", "emerald", "slate", "coral", "ivory"))
        for ability in fixture["abilities"]:
            for field in ("id", "name", "fallback", "accessible", "trigger", "frequency", "available"):
                with self.subTest(ability=ability["id"], field=field):
                    self.assertIn(field, ability)
        for effect in fixture["active_effects"]:
            for field in ("id", "name", "fallback", "accessible", "rounds_remaining", "source"):
                with self.subTest(effect=effect["id"], field=field):
                    self.assertIn(field, effect)
        for status in fixture["statuses"]:
            for field in ("id", "rounds_remaining"):
                with self.subTest(status=status["id"], field=field):
                    self.assertIn(field, status)


# ================================================================
# Wave 6 (board task #19): full client facelift per
# docs/PLAYTEST_FINDINGS_2026-07-19.md. Item letters (A1-G1) below refer to
# that document's requirement IDs.
# ================================================================


class Wave6ModuleShapeTests(unittest.TestCase):
    def test_new_components_and_screens_export_render_functions(self):
        self.assertIn("export function renderToken", WAVE6_COMPONENT_SOURCE["token.js"])
        self.assertIn("export function renderConfirmBar", WAVE6_COMPONENT_SOURCE["confirm-dialog.js"])
        self.assertIn("export function renderRulesOverlay", WAVE6_COMPONENT_SOURCE["rules-overlay.js"])
        self.assertIn("export function renderHelpButton", WAVE6_COMPONENT_SOURCE["rules-overlay.js"])
        self.assertIn("export function renderHintBar", WAVE6_COMPONENT_SOURCE["rules-overlay.js"])
        self.assertIn("export function renderCharacterPanel", WAVE6_SCREEN_SOURCE["character-panel.js"])

    def test_selectors_export_wave6_view_functions(self):
        for name in (
            "selectHeroToken",
            "selectHintText",
            "selectMoveCost",
            "selectBreachCost",
            "selectAbilitiesView",
            "selectActiveEffectsView",
            "selectCharacterPanelView",
            "cardFrameKind",
        ):
            with self.subTest(selector=name):
                self.assertIn("export function %s" % name, SELECTORS_JS)
        self.assertIn("export const AVATAR_COUNT", SELECTORS_JS)
        self.assertIn("export const TOKEN_COLORS", SELECTORS_JS)

    def test_token_colors_match_confirmed_create_hero_palette(self):
        # CONFIRMED contract, stacks-abilities 04:30 -- server validates
        # create_hero's `color` against exactly these 8 names.
        for color in ("crimson", "azure", "gold", "violet", "emerald", "slate", "coral", "ivory"):
            with self.subTest(color=color):
                self.assertIn('"%s"' % color, SELECTORS_JS)

    def test_store_exports_wave6_ui_actions_and_initial_state(self):
        for fn in ("export function openHelp", "export function closeHelp", "export function setPendingAction", "export function clearPendingAction", "export function inspectCard", "export function clearInspectedCard"):
            with self.subTest(fn=fn):
                self.assertIn(fn, STORE_JS)
        for field in ("helpOpen: true", "pendingAction: null", "inspectedCardId: null"):
            with self.subTest(field=field):
                self.assertIn(field, STORE_JS)

    def test_wave6_modules_do_not_call_network_or_store_apis(self):
        forbidden_patterns = ["fetch(", "new WebSocket", "createStore(", "setTimeout(", "setInterval("]
        for name, source in ALL_WAVE6_JS.items():
            for pattern in forbidden_patterns:
                with self.subTest(file=name, pattern=pattern):
                    self.assertNotIn(pattern, source)

    def test_wave6_modules_never_generate_randomness(self):
        for name, source in ALL_WAVE6_JS.items():
            with self.subTest(file=name):
                self.assertNotIn("Math.random", source)
                self.assertNotIn("crypto.getRandomValues", source)

    def test_wave6_modules_never_set_inline_style_properties(self):
        for name, source in ALL_WAVE6_JS.items():
            with self.subTest(file=name):
                self.assertNotRegex(source, r"\.style\.\w+\s*=", "%s sets an inline style property" % name)
                self.assertNotIn(".style.cssText", source)

    def test_card_view_computes_frame_kind_preferring_art_ref(self):
        # A2/E3 + room-chat 04:28 with stacks-carddesign: content-authored
        # art_ref (one of the 3 real copied asset paths) wins over the
        # tag/target heuristic once a pack sets it.
        self.assertIn("card.art_ref", SELECTORS_JS)
        self.assertIn("charm|scheme|bonk", SELECTORS_JS)


class Wave6WiringTests(unittest.TestCase):
    def test_main_js_imports_wave6_modules(self):
        self.assertIn('from "./screens/character-panel.js"', MAIN_JS)
        self.assertIn('from "./components/confirm-dialog.js"', MAIN_JS)
        self.assertIn('from "./components/rules-overlay.js"', MAIN_JS)
        self.assertIn("renderHandDock", MAIN_JS)

    def test_main_js_has_wave6_containers(self):
        for element_id in ("character-panel", "hand-dock", "stacks-chrome"):
            with self.subTest(element_id=element_id):
                self.assertIn('getElementById("%s")' % element_id, MAIN_JS)

    def test_main_js_wires_wave6_handlers(self):
        for handler in (
            "onOpenHelp",
            "onCloseHelp",
            "onInspectCard",
            "onRequestPlayCard",
            "onConfirmPendingAction",
            "onCancelPendingAction",
            "onRequestMove",
            "onRequestBreach",
        ):
            with self.subTest(handler=handler):
                self.assertIn(handler, MAIN_JS)

    def test_a4_confirming_a_pending_action_is_the_only_path_that_sends_move_breach_or_play_card(self):
        # A4/C1: onRequestMove/onRequestBreach/onRequestPlayCard only ever
        # stage a pendingAction (setPendingAction); moveCommand/breachCommand/
        # playCardCommand are only ever invoked from onConfirmPendingAction.
        request_move_body = MAIN_JS.split("onRequestMove:")[1].split("onRequestBreach:")[0]
        self.assertNotIn("sendCommand(", request_move_body)
        self.assertIn("setPendingAction", request_move_body)
        confirm_body = MAIN_JS.split("onConfirmPendingAction:")[1].split("onCancelPendingAction:")[0]
        self.assertIn("moveCommand", confirm_body)
        self.assertIn("breachCommand", confirm_body)
        self.assertIn("playCardCommand", confirm_body)

    def test_html_declares_wave6_containers_hidden_by_default(self):
        for element_id in ("character-panel", "hand-dock"):
            with self.subTest(element_id=element_id):
                self.assertRegex(STACKS_HTML, r'id="%s"[^>]*\bhidden\b' % re.escape(element_id))

    def test_create_hero_command_sends_token_fields(self):
        self.assertIn("avatar_id: avatarId", COMMANDS_JS)
        self.assertIn("color: color", COMMANDS_JS)


class Wave6AccessibilityTests(unittest.TestCase):
    def test_a1_hand_dock_is_positioned_center_bottom(self):
        self.assertIn("#hand-dock {", STACKS_CSS)
        hand_dock_block = STACKS_CSS.split("#hand-dock {")[1].split("}")[0]
        self.assertIn("bottom: 0", hand_dock_block)
        self.assertIn("left: 50%", hand_dock_block)
        self.assertIn("translateX(-50%)", hand_dock_block)

    def test_a2_card_anatomy_is_title_then_art_then_keywords_then_description_then_effect(self):
        source = (SRC_DIR / "components" / "card.js").read_text(encoding="utf-8")
        title_pos = source.index("stacks-card-title")
        art_pos = source.index("stacks-card-art")
        keywords_pos = source.index("stacks-card-keywords")
        description_pos = source.index("stacks-card-description")
        effect_pos = source.index('effect.className = "stacks-card-effect"')
        self.assertLess(title_pos, art_pos)
        self.assertLess(art_pos, keywords_pos)
        self.assertLess(keywords_pos, description_pos)
        self.assertLess(description_pos, effect_pos)

    def test_a3_card_shows_playable_vs_inert_as_text_not_color_only(self):
        source = (SRC_DIR / "components" / "card.js").read_text(encoding="utf-8")
        self.assertIn("is-playable", source)
        self.assertIn("is-inert", source)
        self.assertIn('"Playable now"', source)
        self.assertIn('"Not playable right now"', source)

    def test_a4_card_click_only_inspects_never_plays(self):
        source = (SRC_DIR / "components" / "card.js").read_text(encoding="utf-8")
        self.assertIn("onInspect(card.id)", source)
        self.assertNotIn("onPlay(", source)
        # The Play control only appears once a card is inspected/expanded,
        # and lives in hero-panel.js's renderExpandedPlayControls, not here.
        self.assertIn("expandedContent", source)

    def test_a4_expanded_play_controls_require_a_target_when_the_card_needs_one(self):
        source = HERO_PANEL_JS
        self.assertIn("needsAllyTarget", source)
        self.assertIn("needsEnemyTarget", source)
        self.assertIn("missingRequiredTarget", source)
        self.assertIn("onRequestPlayCard", source)

    def test_a5_active_effects_tray_renders_statuses_and_effects_with_duration_text(self):
        source = WAVE6_SCREEN_SOURCE["character-panel.js"]
        self.assertIn("renderActiveEffectsTray", source)
        self.assertIn("roundsRemaining", source)

    def test_b1_rules_overlay_covers_move_breach_energy_cards_combat_reactions(self):
        source = WAVE6_COMPONENT_SOURCE["rules-overlay.js"]
        for topic in ("Moving and breaching", "Energy", "Cards", "Combat", "Reactions"):
            with self.subTest(topic=topic):
                self.assertIn(topic, source)

    def test_b2_hint_bar_and_help_button_are_accessible(self):
        source = WAVE6_COMPONENT_SOURCE["rules-overlay.js"]
        self.assertIn('role", "status"', source)
        self.assertIn('aria-live", "polite"', source)
        self.assertIn("aria-label", source)

    def test_b2_hint_text_is_state_driven_not_static(self):
        self.assertIn("export function selectHintText", SELECTORS_JS)
        self.assertIn("you.energy", SELECTORS_JS)

    def test_c1_room_tile_shows_move_and_breach_cost_before_confirm(self):
        self.assertIn("moveEnergyCost", ROOM_TILE_JS)
        self.assertIn("breachCostFor", ROOM_TILE_JS)
        self.assertIn("onRequestMove", ROOM_TILE_JS)
        self.assertIn("onRequestBreach", ROOM_TILE_JS)

    def test_d1_character_panel_shows_hp_numbers_and_bar_attributes_skills_energy_abilities(self):
        source = WAVE6_SCREEN_SOURCE["character-panel.js"]
        self.assertIn("stacks-character-hp-numbers", source)
        self.assertIn("stacks-character-hp-bar", source)
        self.assertIn("renderEnergyPips", source)
        self.assertIn("view.attributes", source)
        self.assertIn("view.skills", source)
        self.assertIn("renderAbilities", source)

    def test_d1_character_panel_ability_shows_both_flavor_and_full_rules_text_visibly(self):
        # Director's ruling 04:39: content authors fallback=flavor,
        # accessible=full rules text -- both must be visible, not aria-only.
        source = WAVE6_SCREEN_SOURCE["character-panel.js"]
        self.assertIn("ability.fallback", source)
        self.assertIn("ability.accessible", source)

    def test_d2_inventory_is_a_visual_slot_grid(self):
        source = HERO_PANEL_JS
        self.assertIn("stacks-inventory-grid", source)
        self.assertIn("stacks-inventory-slot--filled", source)
        self.assertIn("stacks-inventory-slot--empty", source)

    def test_f1_room_tiles_and_roster_render_tokens_not_name_only(self):
        self.assertIn("renderToken(hero.token", ROOM_TILE_JS)
        self.assertIn("renderToken(heroCard.token", HERO_JS)

    def test_f1_token_never_identifies_a_hero_by_color_alone(self):
        source = WAVE6_COMPONENT_SOURCE["token.js"]
        self.assertIn('alt = ""', source)
        self.assertIn('aria-hidden", "true"', source)

    def test_f1_character_builder_lets_the_player_choose_avatar_and_color(self):
        self.assertIn("renderTokenChoice", CHARACTER_BUILDER_JS)
        self.assertIn("AVATAR_COUNT", CHARACTER_BUILDER_JS)
        self.assertIn("TOKEN_COLORS", CHARACTER_BUILDER_JS)

    def test_g1_join_screen_shows_key_art(self):
        self.assertIn("stacks-key-art", STACKS_HTML)
        self.assertIn('src="/src/assets/key-art.jpg"', STACKS_HTML)


class Wave6CssContractTests(unittest.TestCase):
    def test_new_container_ids_have_styling_hooks(self):
        for selector in ("#character-panel", "#hand-dock", "#stacks-chrome", ".stacks-confirm-bar", ".stacks-rules-overlay", ".stacks-help-button", ".stacks-hint-bar"):
            with self.subTest(selector=selector):
                self.assertIn(selector, STACKS_CSS)

    def test_card_art_frame_classes_use_css_background_image_not_inline_style(self):
        for kind in ("charm", "scheme", "bonk"):
            with self.subTest(kind=kind):
                self.assertIn(".stacks-card-art--%s {" % kind, STACKS_CSS)
                self.assertIn("/src/assets/cards/%s.png" % kind, STACKS_CSS)

    def test_all_eight_token_hue_classes_present(self):
        for color in ("crimson", "azure", "gold", "violet", "emerald", "slate", "coral", "ivory"):
            with self.subTest(color=color):
                self.assertIn(".stacks-token-hue-%s {" % color, STACKS_CSS)

    def test_hp_bar_fill_width_utility_classes_cover_0_to_100(self):
        for n in (0, 50, 100):
            with self.subTest(n=n):
                self.assertIn(".stacks-fill-%d {" % n, STACKS_CSS)


# ================================================================
# Wave 6A (wavebasedgame.md S3.1 stop-ship gate): J8 name-input focus loss,
# the pre-join rules modal blocking "Kindle a New Run", and J1's join/
# creation split. Static-analysis style, same mold as the rest of this file.
# ================================================================


class Wave6AJ8NameInputFocusTests(unittest.TestCase):
    """J8: the hero-name field must keep a stable element identity across
    renders instead of being torn down and rebuilt on every keystroke (which
    silently drops keyboard focus after exactly one character)."""

    def test_name_input_is_cached_not_recreated_every_render(self):
        source = CHARACTER_BUILDER_JS
        # A module-scope cache so the exact same DOM node is reused across
        # calls to renderCharacterBuilderScreen, instead of a fresh
        # document.createElement("input") every render.
        self.assertIn("cachedNameInput", source)
        self.assertIn('document.createElement("input")', source)
        # The cached node must be reused (not replaced) when a value hasn't
        # actually changed, so an unrelated re-render can't steal focus.
        self.assertIn("if (!cachedNameInput)", source)

    def test_rerender_while_name_input_focused_does_not_rebuild_the_screen(self):
        # The real fix isn't just node reuse -- container.replaceChildren()
        # detaches the whole subtree (including whatever has focus) before
        # any node, cached or not, gets reattached, which still drops focus.
        # renderCharacterBuilderScreen must special-case a render pass that
        # fires while the name input itself is focused and refresh only the
        # parts that can change (canSubmit/hint text) in place, leaving the
        # focused input untouched in the live DOM.
        source = CHARACTER_BUILDER_JS
        self.assertIn("document.activeElement === cachedNameInput", source)
        self.assertIn("refreshSubmitSectionInPlace", source)

    def test_name_field_listener_writes_through_the_cached_node_not_a_stale_closure(self):
        source = CHARACTER_BUILDER_JS
        self.assertIn('cachedNameInput.addEventListener("input"', source)
        self.assertIn("onUpdateCharacterDraft({ name: cachedNameInput.value })", source)


class Wave6APreJoinRulesModalTests(unittest.TestCase):
    """The rules overlay (rules-overlay.js, reused from wave 6's B1/B2 work)
    must never gate the pre-join "Kindle a New Run" / "Answer the Summons"
    CTAs -- onboarding lives in the persistent help overlay, shown only once
    a hero exists, never as a blocking pre-join dialog."""

    def test_render_chrome_gates_rules_overlay_on_a_hero_existing(self):
        # Before this fix, renderRulesOverlay(state.helpOpen, ...) was called
        # unconditionally in renderChrome, and helpOpen defaults to true
        # (store.js's createInitialState), so the overlay covered the join
        # screen on first page load, before any hero/room existed.
        match = re.search(r"function renderChrome\(state\)\s*{.*?\n}\n", MAIN_JS, re.DOTALL)
        self.assertIsNotNone(match, "renderChrome function not found in main.js")
        body = match.group(0)
        overlay_call = body.index("renderRulesOverlay(")
        guard_call = body.index("selectYouHero(state)")
        self.assertLess(guard_call, overlay_call, "renderRulesOverlay must be called inside the selectYouHero(state) guard")

    def test_help_open_still_defaults_true_for_the_post_join_first_run_experience(self):
        # The overlay must still greet a brand-new hero automatically once
        # join/creation puts them in the run -- only the pre-join gating
        # changed, not the first-run-onboarding intent itself.
        self.assertIn("helpOpen: true", STORE_JS)


class Wave6AJ1JoinCreationSplitTests(unittest.TestCase):
    """J1: joining a room must not collect hero identity; that belongs to
    the character-builder (creation) screen, which already has its own name
    field."""

    def test_join_panel_has_no_display_name_field(self):
        self.assertNotIn("display-name-input", STACKS_HTML)

    def test_join_panel_retains_access_code_and_room_code_only(self):
        self.assertIn('id="access-code-input"', STACKS_HTML)
        self.assertIn('id="room-code-input"', STACKS_HTML)
        self.assertIn('id="create-room-button"', STACKS_HTML)
        self.assertIn('id="join-room-button"', STACKS_HTML)

    def test_main_js_join_panel_wiring_does_not_read_a_display_name_input(self):
        self.assertNotIn('getElementById("display-name-input")', MAIN_JS)

    def test_main_js_create_and_join_no_longer_require_a_name_before_calling_the_api(self):
        # Both handlers must still require an access code (join additionally
        # requires a room code) -- but neither may gate on a display name.
        match = re.search(r"function wireJoinPanel\(\)\s*{.*?\n}\n", MAIN_JS, re.DOTALL)
        self.assertIsNotNone(match, "wireJoinPanel function not found in main.js")
        body = match.group(0)
        self.assertNotIn("displayNameInput", body)
        self.assertIn("createRoom({ accessCode, seed: null })", body)
        self.assertIn("joinRoom({ accessCode, roomCode })", body)

    def test_api_js_host_name_and_display_name_are_optional_on_the_wire(self):
        source = API_JS
        self.assertIn("if (hostName) body.host_name = hostName;", source)
        self.assertIn("if (displayName) body.display_name = displayName;", source)

    def test_character_builder_screen_is_still_the_identity_step(self):
        # The name field lives on the creation screen, not the join screen.
        self.assertIn("stacks-builder-name-input", CHARACTER_BUILDER_JS)
        self.assertIn("Hero name", CHARACTER_BUILDER_JS)


if __name__ == "__main__":
    unittest.main()
