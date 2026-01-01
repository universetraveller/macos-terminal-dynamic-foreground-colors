import platform
import unittest

from terminal_dynamic_colors import (
    adjust_hex, adjust_lightness, lab_to_rgb, parse_color, rgb_to_lab,
)
from verify import load_examples, verify


class ReferenceExamples(unittest.TestCase):
    def test_reference_blue_predictions(self):
        checked, mismatches = verify(load_examples(), adjust_hex)
        self.assertEqual(checked, 3)
        self.assertEqual(mismatches, [])

    def test_16bit_input_is_not_truncated_to_8bit(self):
        raw = parse_color('1234/5678/9ABC')
        self.assertEqual(raw, (0x1234/65535, 0x5678/65535, 0x9ABC/65535))
        self.assertNotEqual(raw, parse_color('#12569A'))


class ColorConversions(unittest.TestCase):
    def test_rgb_lab_round_trip_without_gamut_clipping(self):
        values = ((0, 0, 0), (1, 1, 1), (0, 0, 1), (1, 0, 0),
                  (0, 1, 0), (.125, .4, .8), (.5, .5, .5))
        for rgb in values:
            with self.subTest(rgb=rgb):
                recovered = lab_to_rgb(rgb_to_lab(rgb))
                for actual, expected in zip(recovered, rgb):
                    self.assertAlmostEqual(actual, expected, places=6)

    def test_white_and_black_reference_lightness(self):
        self.assertAlmostEqual(rgb_to_lab((0, 0, 0))[0], 0, places=6)
        self.assertAlmostEqual(rgb_to_lab((1, 1, 1))[0], 100, places=4)

    def test_background_extremes_and_equality_branch(self):
        self.assertAlmostEqual(adjust_lightness(.25, 0), .4)
        self.assertAlmostEqual(adjust_lightness(.25, 1), .4)
        self.assertAlmostEqual(adjust_lightness(.5, .5), .8)

    def test_osc_widths_and_invalid_input(self):
        self.assertEqual(parse_color('rgb:f/0/ffff'), (1, 0, 1))
        for value in ('', '#fff', '#GG0000', '00000/0/0', '12/34', 'rgb:a/b/c/d'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_color(value)


@unittest.skipUnless(platform.system() == 'Darwin', 'Native ColorSync requires macOS')
class NativeReferenceExamples(unittest.TestCase):
    def test_reference_predictions_through_installed_colorsync(self):
        from terminal_color_probe import NativeColorSync, rgb_hex
        engine = NativeColorSync()
        try:
            calculate = lambda fg, bg: rgb_hex(engine.adjusted(parse_color(fg), parse_color(bg)))
            checked, mismatches = verify(load_examples(), calculate)
        finally:
            engine.close()
        self.assertEqual(checked, 3)
        self.assertEqual(mismatches, [])


if __name__ == '__main__':
    unittest.main()
