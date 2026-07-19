"""Tests for backend.lan_playground.qr (board task #40).

The vendored matrix encoder (backend/lan_playground/_vendor/qrenc, copied
unmodified from segno 1.6.6) was cross-checked once during development
against OpenCV's QRCodeDetector on a directly-rasterized bitmap using the
exact same border/scale geometry this module uses -- confirming both the
vendored encode() output and the rect layout are scannable. These tests
cover the parts owned by this module: input validation, SVG structural
correctness, and content-safety (no logging).
"""

import re
import unittest

from backend.lan_playground.qr import render_qr_svg


class ValidationTests(unittest.TestCase):
    def test_empty_data_rejected(self):
        with self.assertRaises(ValueError):
            render_qr_svg("")

    def test_zero_scale_rejected(self):
        with self.assertRaises(ValueError):
            render_qr_svg("http://x", scale=0)

    def test_negative_border_rejected(self):
        with self.assertRaises(ValueError):
            render_qr_svg("http://x", border=-1)


class SvgStructureTests(unittest.TestCase):
    def test_produces_well_formed_svg_root(self):
        svg = render_qr_svg("http://192.168.1.5:8850/join?r=ABCDEF&a=code123")
        self.assertTrue(svg.startswith("<svg "))
        self.assertTrue(svg.endswith("</svg>"))
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)

    def test_contains_dark_rects(self):
        svg = render_qr_svg("http://192.168.1.5:8850/join?r=ABCDEF&a=code123")
        self.assertIn("<rect", svg)
        self.assertGreater(svg.count("<rect"), 5)

    def test_larger_scale_yields_larger_canvas(self):
        small = render_qr_svg("hello", scale=2)
        large = render_qr_svg("hello", scale=10)

        def _viewbox_size(svg: str) -> int:
            m = re.search(r'width="(\d+)"', svg)
            return int(m.group(1))

        self.assertLess(_viewbox_size(small), _viewbox_size(large))

    def test_longer_payload_yields_more_modules(self):
        short_svg = render_qr_svg("a")
        long_svg = render_qr_svg("http://192.168.1.5:8850/join?" + "r=" + "X" * 200)

        def _viewbox_size(svg: str) -> int:
            m = re.search(r'width="(\d+)"', svg)
            return int(m.group(1))

        self.assertLess(_viewbox_size(short_svg), _viewbox_size(long_svg))

    def test_custom_colors_applied(self):
        svg = render_qr_svg("hello", dark="#ff0000", light="#00ff00")
        self.assertIn('fill="#00ff00"', svg)
        self.assertIn('fill="#ff0000"', svg)

    def test_no_xss_breakout_via_colors(self):
        # Colors are attribute-injected via xml.sax.saxutils.quoteattr, so
        # even a hostile/malformed value cannot break out of the attribute.
        svg = render_qr_svg("hello", dark='"/><script>alert(1)</script>')
        self.assertNotIn("<script>", svg)


class NoLoggingTests(unittest.TestCase):
    def test_module_never_calls_logging(self):
        import backend.lan_playground.qr as mod

        with open(mod.__file__, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("import logging", source)
        self.assertIsNone(re.search(r"\blogging\.\w+\(", source))


if __name__ == "__main__":
    unittest.main()
