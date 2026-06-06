import unittest

import studio_analyzer as sa


# A compact noir excerpt that mirrors the real manuscript's structure: first-person
# narrator, named cast (Louis, Rodney, Goldstein), real places, and quoted dialogue.
NOIR = """The smell of still smoke and old leather. Ritzy jazz crackled from the speakers.
One last job, and then Goldstein would be happy. I remember the first time I saw Freddy
Goldstein at the Cabbaro Pulse, a basement jazz club in Grimstow City.

"You heard about the job, huh?" Goldstein said, his voice ice with a fuse under it.
"I want in," I said. Goldstein stared at me.

We crossed the bridge into Dockside. Rodney reached for his gun.
"I think I'm ready," Rodney said. "I just want to get this over with."

Rodney turned and had a gun pointed straight at me. "Boss said only one of us gets
the promotion," he added. Then CRACK. I fell backward into the dark.

Louis woke coughing, lungs choked by smoke. Louis lifted his shirt and found the scar.
Father Time stood over the flames. "Not everyone survives their first taste of smoke,"
Father Time said. "Keep your scars closer. They'll remind you who you are." """


class TestStudioAnalyzer(unittest.TestCase):
    def setUp(self):
        self.analysis = sa.analyze(NOIR)

    def test_detects_real_characters_not_placeholders(self):
        names = [c["name"] for c in self.analysis["characters"]]
        self.assertIn("Louis", names)
        self.assertTrue(any("Goldstein" in n for n in names))
        self.assertTrue(any("Rodney" in n for n in names))
        # Multi-word recurring names should merge, not fragment.
        self.assertIn("Father Time", names)

    def test_rejects_sentence_initial_false_names(self):
        names = [c["name"] for c in self.analysis["characters"]]
        # "Then CRACK" / "We crossed" must not produce bogus characters.
        for junk in ("Then", "We", "One", "Crack", "Ritzy"):
            self.assertNotIn(junk, names)

    def test_extracts_locations(self):
        places = [p["name"] for p in self.analysis["locations"]]
        joined = " ".join(places)
        self.assertIn("Dockside", joined)
        self.assertIn("Grimstow", joined)

    def test_infers_noir_tone(self):
        self.assertEqual(self.analysis["tone"], "noir")
        self.assertIn("noir", self.analysis["aesthetic"].lower())

    def test_extracts_real_dialogue_with_attribution(self):
        dialogue = self.analysis["dialogue"]
        self.assertTrue(len(dialogue) >= 4)
        speakers = {d["speaker"] for d in dialogue}
        # Goldstein is attributed via "Goldstein said".
        self.assertIn("Goldstein", speakers)
        texts = " ".join(d["text"] for d in dialogue)
        self.assertIn("You heard about the job", texts)

    def test_pronoun_speakers_become_narrator(self):
        # Lines attributed only to "he"/"I" must not surface a pronoun as a speaker.
        for d in self.analysis["dialogue"]:
            self.assertNotIn(d["speaker"].lower(), {"he", "she", "i", "they", "it"})

    def test_segments_three_beats(self):
        beats = self.analysis["beats"]
        self.assertEqual(len(beats), 3)
        for beat in beats:
            self.assertTrue(beat["summary"])

    def test_empty_input_is_safe(self):
        empty = sa.analyze("")
        self.assertEqual(empty["characters"], [])
        self.assertEqual(empty["dialogue"], [])
        self.assertEqual(empty["tone"], "drama")

    def test_contractions_not_treated_as_names(self):
        names = [c["name"] for c in self.analysis["characters"]]
        for junk in ("I'd", "I'm", "I"):
            self.assertNotIn(junk, names)


if __name__ == "__main__":
    unittest.main()
