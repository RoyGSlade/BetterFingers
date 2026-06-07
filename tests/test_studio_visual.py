import unittest

import studio_visual


class StudioVisualTests(unittest.TestCase):
    def setUp(self):
        self.world = {
            "palette": "Sodium amber, rain-slick black",
            "lighting": "low-key practical lights",
            "materials": "wet asphalt, brushed brass",
            "locations": [
                {"name": "The Back Room", "visual_prompt": "windowless basement club, brass lamps", "mood": "smoky"},
            ],
        }
        self.characters = [
            {"name": "Mara", "visual": {"face": "sharp", "hair": "short black", "build": "lean",
                                         "outfit": "grey coat", "palette": "ash and red"}},
            {"name": "Rey", "metadata": {"visual": {"face": "round", "hair": "buzzed", "outfit": "denim"}}},
        ]

    def test_prompt_includes_structured_parts(self):
        by_name = studio_visual.index_characters(self.characters)
        panel = {
            "visual_description": "Mara confronts Rey",
            "visible_characters": ["Mara", "Rey"],
            "location_ref": "The Back Room",
            "camera": "close-up",
            "composition": "shallow depth",
            "continuity_state": {"props": "a key", "mood": "tense"},
        }
        prompt, negative = studio_visual.build_image_prompt(panel, self.world, by_name)
        # Character look is anchored (consistency across panels).
        self.assertIn("Mara: sharp, short black", prompt)
        # Rey's visual came from metadata.visual fallback.
        self.assertIn("Rey: round, buzzed", prompt)
        # Named location with its own visual prompt.
        self.assertIn("setting: The Back Room — windowless basement club", prompt)
        # World look + medium + camera grammar.
        self.assertIn("palette: Sodium amber", prompt)
        self.assertIn("lighting: low-key", prompt)
        self.assertIn("close-up", prompt)
        # Continuity cues.
        self.assertIn("continuity: a key, tense", prompt)
        # Real, non-empty negative prompt.
        self.assertIn("extra fingers", negative)
        self.assertTrue(negative)

    def test_missing_visual_blocks_degrade_gracefully(self):
        by_name = studio_visual.index_characters([{"name": "Ghost"}])
        panel = {"visual_description": "An empty room", "visible_characters": ["Ghost"],
                 "camera": "wide", "composition": "centered"}
        prompt, negative = studio_visual.build_image_prompt(panel, {}, by_name)
        self.assertIn("An empty room", prompt)
        self.assertIn("comic panel", prompt)
        self.assertTrue(negative)


if __name__ == "__main__":
    unittest.main()
