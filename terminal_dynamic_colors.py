#!/usr/bin/env python3
"""Reproduce macOS Terminal.app's Dynamic Foreground Colors calculation.

Target: Terminal.app 2.15 (488.9). Static inspection of both ARM64 slices and
20,010 interpreted scalar checks support the ordinary force=False formula:

    t = 0.2 + 0.8 * foreground_L
    result_L = background_L * t                     if foreground_L < background_L
    result_L = background_L + (1-background_L) * t  otherwise

L is normalized Lab lightness, L*/100. The two Lab chromatic components and
input alpha are preserved before reverse conversion in Terminal. The profile
setting is DynamicANSIForegroundColors; a missing reference background bypasses
adjustment. The additional force=True path is outside this implementation.

This is newly written project code informed by static inspection, with no
application instructions or disassembly embedded. See docs/report.md and
evidence/build_check.json for the findings and their limits.

The portable converter approximates ColorSync using analytical sRGB/D50 Lab
conversion and channel clipping. Terminal obtains numeric Device RGB components,
passes them through its sRGB-profile transform, and constructs Device RGB output.
This model uses the same numeric inputs as sRGB. Example outputs are predictions,
not measured rendering on the target build. No user-session recordings are
included. Native conversion and rendering can be checked locally with the probe.

Usage:
  python3 terminal_dynamic_colors.py '#0000B2' '#1E1E1E'
  python3 terminal_dynamic_colors.py '1234/5678/9ABC' '#FFFFFF'
  python3 terminal_dynamic_colors.py --self-test
"""

import argparse
import math
import re
import struct

RGB_TO_XYZ_D65 = (
    (0.4124564, 0.3575761, 0.1804375),
    (0.2126729, 0.7151522, 0.0721750),
    (0.0193339, 0.1191920, 0.9503041),
)
BRADFORD_D65_TO_D50 = (
    (1.0478112, 0.0228866, -0.0501270),
    (0.0295424, 0.9904844, -0.0170491),
    (-0.0092345, 0.0150436, 0.7521316),
)
D50 = (0.96422, 1.0, 0.82521)


def matmul(matrix, vector):
    return tuple(sum(a*b for a, b in zip(row, vector)) for row in matrix)


def inverse(matrix):
    (a, b, c), (d, e, f), (g, h, i) = matrix
    determinant = a*(e*i-f*h) - b*(d*i-f*g) + c*(d*h-e*g)
    return tuple(tuple(v/determinant for v in row) for row in (
        (e*i-f*h, c*h-b*i, b*f-c*e),
        (f*g-d*i, a*i-c*g, c*d-a*f),
        (d*h-e*g, b*g-a*h, a*e-b*d),
    ))


def float32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def parse_hex(value):
    if not re.fullmatch(r'#?[0-9a-fA-F]{6}', value):
        raise ValueError('Expected six-digit RGB, e.g. #0000B2')
    value = value.removeprefix('#')
    return tuple(int(value[i:i+2], 16)/255 for i in (0, 2, 4))


def parse_color(value):
    """Accept six-digit hex or OSC RGB channels without losing 16-bit precision."""
    channels = value.removeprefix('rgb:').split('/')
    if len(channels) == 3 and all(re.fullmatch(r'[0-9a-fA-F]{1,4}', v) for v in channels):
        return tuple(int(v, 16)/(16**len(v)-1) for v in channels)
    return parse_hex(value)


def rgb_to_lab(rgb):
    linear = tuple(v/12.92 if v <= 0.04045 else ((v+0.055)/1.055)**2.4 for v in rgb)
    xyz = matmul(BRADFORD_D65_TO_D50, matmul(RGB_TO_XYZ_D65, linear))
    def f(v):
        return v**(1/3) if v > (6/29)**3 else v/(3*(6/29)**2)+4/29
    x, y, z = (f(v/w) for v, w in zip(xyz, D50))
    return (116*y-16, 500*(x-y), 200*(y-z))


def lab_to_rgb(lab):
    lightness, a, b = lab
    y = (lightness+16)/116
    f = (y+a/500, y, y-b/200)
    xyz = tuple((v**3 if v > 6/29 else 3*(6/29)**2*(v-4/29))*w
                for v, w in zip(f, D50))
    linear = matmul(inverse(RGB_TO_XYZ_D65), matmul(inverse(BRADFORD_D65_TO_D50), xyz))
    return tuple(12.92*v if v <= 0.0031308 else 1.055*v**(1/2.4)-0.055 for v in linear)


def adjust_lightness(foreground_l, background_l):
    """Ordinary path, normalized L values in [0, 1]."""
    t = 0.2 + 0.8 * foreground_l
    if foreground_l < background_l:
        return background_l * t
    return background_l + (1.0-background_l) * t


def adjust_rgb(foreground, background):
    """Return RGB floats from the analytical approximation; inputs are RGB tuples."""
    # The executable converts its RGB components and Lab buffers to float32.
    fg = rgb_to_lab(tuple(float32(v) for v in foreground))
    bg = rgb_to_lab(tuple(float32(v) for v in background))
    l = float32(fg[0]/100)
    bl = float32(bg[0]/100)
    new_l = float32(adjust_lightness(l, bl))
    return lab_to_rgb((new_l*100, fg[1], fg[2]))


def format_hex(rgb):
    channels = tuple(min(255, max(0, math.floor(float32(v)*255+0.5))) for v in rgb)
    return '#' + ''.join(f'{v:02X}' for v in channels)


def adjust_hex(foreground, background):
    """Accept hex/OSC RGB strings and return the predicted 8-bit output."""
    return format_hex(adjust_rgb(parse_color(foreground), parse_color(background)))


def self_test():
    cases = (
        ('#0000B2', '#FFFFFF', '#5230E1'),
        ('#0000B2', '#000000', '#5230E1'),
        ('#0000B2', '#1E1E1E', '#6A42F6'),
    )
    for fg, bg, expected in cases:
        got = adjust_hex(fg, bg)
        assert got == expected, (fg, bg, got, expected)
    # Exercise both branches and equality independently of the color conversion.
    for fg, bg, expected in ((0.25, 1.0, 0.4), (0.25, 0.0, 0.4),
                             (0.25, 0.1, 0.46), (0.5, 0.5, 0.8)):
        assert math.isclose(adjust_lightness(fg, bg), expected, abs_tol=1e-15)
    print('Passed: three exact 8-bit color examples and four lightness cases.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('foreground', nargs='?', help='RGB foreground: #RRGGBB or RRRR/GGGG/BBBB')
    parser.add_argument('background', nargs='?', help='RGB background: #RRGGBB or RRRR/GGGG/BBBB')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    if (args.foreground is None) != (args.background is None):
        parser.error('Supply both foreground and background, or neither.')
    if args.foreground is not None:
        try:
            print(adjust_hex(args.foreground, args.background))
        except ValueError as error:
            parser.error(str(error))
        return
    print('Foreground  Background  Adjusted')
    for bg in ('#FFFFFF', '#000000', '#1E1E1E'):
        print(f'#0000B2     {bg}     {adjust_hex("#0000B2", bg)}')


if __name__ == '__main__':
    main()
