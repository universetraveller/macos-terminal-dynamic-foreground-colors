#!/usr/bin/env python3
"""Check illustrative model predictions, using portable math or native ColorSync.

Expected RGB values are reference predictions, not recorded rendering results.
The native engine checks the installed ColorSync; it does not call Terminal's
private adjustment method or measure glyph pixels.
"""

import argparse
import json
import platform
from pathlib import Path

from terminal_dynamic_colors import adjust_hex, parse_color


def load_examples():
    return json.loads((Path(__file__).parent/'data/examples.json').read_text())


def verify(examples, calculate):
    mismatches = []
    for case in examples['cases']:
        actual = calculate(case['foreground'], case['background'])
        if actual.upper() != case['expected'].upper():
            mismatches.append((case['foreground'], case['background'], case['expected'], actual))
    return len(examples['cases']), mismatches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('portable', 'native'), default='portable')
    args = parser.parse_args()
    engine = None
    if args.engine == 'native':
        if platform.system() != 'Darwin':
            parser.error('The native engine requires macOS.')
        from terminal_color_probe import NativeColorSync, rgb_hex
        engine = NativeColorSync()
        calculate = lambda fg, bg: rgb_hex(engine.adjusted(parse_color(fg), parse_color(bg)))
    else:
        calculate = adjust_hex
    try:
        checked, mismatches = verify(load_examples(), calculate)
    finally:
        if engine is not None:
            engine.close()
    print(f'Engine: {args.engine}')
    print('Expected RGB values are model predictions, not recorded measurements.')
    print(f'Reference cases checked: {checked}')
    for foreground, background, expected, actual in mismatches:
        print(f'{foreground} on {background}: expected {expected}, got {actual}')
    print(f'Mismatches: {len(mismatches)}')
    return int(bool(mismatches))


if __name__ == '__main__':
    raise SystemExit(main())
