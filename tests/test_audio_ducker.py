import unittest

from audio_ducker import AudioDucker


class AudioDuckerTests(unittest.TestCase):
    def test_unduck_requires_prior_duck(self):
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.64, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        ducker.unduck()
        self.assertEqual(set_calls, [])

        ducker.duck(target_level=0.2, fallback_restore_level=0.8)
        self.assertEqual(set_calls, [(0.2, None)])

        ducker.unduck()
        self.assertEqual(set_calls, [(0.2, None), (0.64, False)])

    def test_unduck_uses_fallback_level_when_read_fails(self):
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: None
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        ducker.duck(target_level=0.15, fallback_restore_level=0.7)
        ducker.unduck()

        self.assertEqual(set_calls, [(0.15, None), (0.7, None)])

    def test_duck_is_idempotent_until_unduck(self):
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.9, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        ducker.duck(target_level=0.18, fallback_restore_level=0.8)
        ducker.duck(target_level=0.1, fallback_restore_level=0.5)
        self.assertEqual(set_calls, [(0.18, None)])

        ducker.unduck()
        self.assertEqual(set_calls, [(0.18, None), (0.9, False)])

    def test_stale_duck_is_refused_after_intervening_unduck(self):
        # The stop/duck race: recording start captures a generation and hands
        # the duck to a thread; the stop's unduck lands first. The late duck
        # must refuse to commit — otherwise the system stays ducked with no
        # release path.
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.9, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        generation = ducker.generation()
        ducker.unduck()  # stop arrives before the duck thread runs
        ducker.duck(target_level=0.18, fallback_restore_level=0.8, generation=generation)

        self.assertEqual(set_calls, [])
        self.assertFalse(ducker._ducked)

    def test_current_generation_duck_commits_and_unducks_normally(self):
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.9, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        generation = ducker.generation()
        ducker.duck(target_level=0.18, fallback_restore_level=0.8, generation=generation)
        ducker.unduck()

        self.assertEqual(set_calls, [(0.18, None), (0.9, False)])
        self.assertFalse(ducker._ducked)

    def test_unduck_on_undocked_state_still_invalidates_pending_duck(self):
        # unduck() while nothing is ducked must not restore anything, but it
        # must still bump the generation so a pending duck is invalidated.
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.9, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        before = ducker.generation()
        ducker.unduck()
        self.assertEqual(set_calls, [])
        self.assertNotEqual(before, ducker.generation())

    def test_generationless_duck_keeps_legacy_behavior(self):
        ducker = AudioDucker()
        ducker.available = True

        set_calls = []
        ducker._read_audio_state = lambda: (0.9, False)
        ducker._set_audio_state = lambda level=None, muted=None: set_calls.append((level, muted)) or True

        ducker.unduck()
        ducker.duck(target_level=0.18, fallback_restore_level=0.8)
        self.assertEqual(set_calls, [(0.18, None)])
        self.assertTrue(ducker._ducked)


if __name__ == "__main__":
    unittest.main()
