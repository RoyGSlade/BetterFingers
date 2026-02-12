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


if __name__ == "__main__":
    unittest.main()
