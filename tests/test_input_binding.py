import unittest

from input_binding import InputBinding, parse_binding_expression


class InputBindingTests(unittest.TestCase):
    def test_parse_chord_expression(self):
        events = parse_binding_expression("chord", "button:4 + hat:0:up + axis:2:pos")
        self.assertEqual(events, ["button:4", "hat:0:up", "axis:2:pos"])

    def test_parse_sequence_expression(self):
        events = parse_binding_expression("sequence", "button:1 > button:2 > button:3")
        self.assertEqual(events, ["button:1", "button:2", "button:3"])

    def test_binding_from_legacy(self):
        binding = InputBinding.from_legacy(controller_button=8, sequence_window_ms=700, axis_threshold=0.8)
        self.assertEqual(binding.style, "single")
        self.assertEqual(binding.events, ["button:8"])
        self.assertEqual(binding.sequence_window_ms, 700)
        self.assertEqual(binding.axis_threshold, 0.8)

    def test_binding_validation_clamps_values(self):
        binding = InputBinding(style="sequence", events=["button:1"], sequence_window_ms=10, axis_threshold=2.0)
        binding.validate()
        self.assertEqual(binding.sequence_window_ms, 100)
        self.assertEqual(binding.axis_threshold, 1.0)


if __name__ == "__main__":
    unittest.main()

