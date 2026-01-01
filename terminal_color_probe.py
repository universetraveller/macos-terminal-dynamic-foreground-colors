#!/usr/bin/env python3
"""Read a local Terminal palette and reproduce its foreground calculation.

Target: Terminal.app 2.15 (488.9), ordinary Dynamic Foreground Colors path.
Run locally in Terminal.app, outside SSH/tmux:
    python3 terminal_color_probe.py

Read-only OSC 4/10/11 queries temporarily change TTY input mode and restore it
in finally. Public ColorSync/CoreFoundation APIs calculate predictions. The
program does not change colors, profiles, or preferences, write report files,
or upload results. Its stdout contains local OS/Terminal versions and color
settings, so choose which numeric results to share.

OSC replies describe configured Device RGB, not sampled glyph pixels. The
named-ANSI swatches provide a separate rendering check. Independently measure
solid interior regions and record the measurement color space and method.

The project implements the normal lightness formula and conversion sequence;
it does not call Terminal's private adjustment method.
"""

import ctypes as C
import math
import os
import platform
import re
import select
import sys
import termios
import time
import tty

REPLY = re.compile(rb'\x1b\](?:4;(\d+)|(10|11));rgb:([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})/([0-9a-fA-F]{1,4})(?:\x07|\x1b\\)')


def parse_replies(data):
    result = {}
    for match in REPLY.finditer(data):
        index, special, *channels = match.groups()
        key = int(index) if index is not None else 'fg' if special == b'10' else 'bg'
        result[key] = tuple(int(v, 16)/(16**len(v)-1) for v in channels)
    return result


def query_palette(timeout=3.0):
    query = b''.join(f'\x1b]4;{i};?\x07'.encode() for i in range(16))
    query += b'\x1b]10;?\x07\x1b]11;?\x07'
    with open('/dev/tty', 'r+b', buffering=0) as terminal:
        fd = terminal.fileno()
        previous = termios.tcgetattr(fd)
        data = b''
        try:
            tty.setraw(fd)
            os.write(fd, query)
            deadline = time.monotonic()+timeout
            while time.monotonic() < deadline:
                remaining = deadline-time.monotonic()
                if select.select([fd], [], [], max(0, remaining))[0]:
                    part = os.read(fd, 16384)
                    if not part:
                        break
                    data += part
                    if len(parse_replies(data)) == 18:
                        break
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, previous)
    return parse_replies(data)


def rgb_hex(rgb):
    return '#' + ''.join(f'{min(255, max(0, math.floor(v*255+0.5))):02X}' for v in rgb)


def hex_rgb(value):
    return tuple(int(value[i:i+2], 16)/255 for i in (0, 2, 4))


def adjusted_lab(foreground, background):
    l, a, b = foreground
    bg_l = background[0]
    t = 0.2+0.8*l
    new_l = bg_l*t if l < bg_l else bg_l+(1-bg_l)*t
    return (new_l, a, b)


class NativeColorSync:
    def __init__(self):
        self.cf = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        self.cs = C.CDLL('/System/Library/Frameworks/ColorSync.framework/ColorSync')
        p = C.c_void_p
        self.cf.CFDictionaryCreate.argtypes = [p, C.POINTER(p), C.POINTER(p), C.c_long, p, p]
        self.cf.CFDictionaryCreate.restype = p
        self.cf.CFArrayCreate.argtypes = [p, C.POINTER(p), C.c_long, p]
        self.cf.CFArrayCreate.restype = p
        self.cf.CFRelease.argtypes = [p]
        self.cf.CFRelease.restype = None
        self.cs.ColorSyncProfileCreateWithName.argtypes = [p]
        self.cs.ColorSyncProfileCreateWithName.restype = p
        self.cs.ColorSyncTransformCreate.argtypes = [p, p]
        self.cs.ColorSyncTransformCreate.restype = p
        self.cs.ColorSyncTransformConvert.argtypes = [p, C.c_size_t, C.c_size_t, p, C.c_uint32, C.c_uint32, C.c_size_t, p, C.c_uint32, C.c_uint32, C.c_size_t, p]
        self.cs.ColorSyncTransformConvert.restype = C.c_bool
        srgb = self.cs.ColorSyncProfileCreateWithName(self.constant('kColorSyncSRGBProfile'))
        lab = self.cs.ColorSyncProfileCreateWithName(self.constant('kColorSyncGenericLabProfile'))
        if not srgb or not lab:
            raise RuntimeError('ColorSync could not load its sRGB/Generic Lab profiles.')
        try:
            self.forward = self.make_transform(srgb, lab)
            self.reverse = self.make_transform(lab, srgb)
        finally:
            self.cf.CFRelease(srgb)
            self.cf.CFRelease(lab)

    def constant(self, name):
        return C.c_void_p.in_dll(self.cs, name).value

    def callback_address(self, name):
        return C.addressof(C.c_byte.in_dll(self.cf, name))

    def make_transform(self, source, destination):
        p = C.c_void_p
        keys = (p*3)(*(self.constant(k) for k in ('kColorSyncProfile', 'kColorSyncRenderingIntent', 'kColorSyncTransformTag')))
        dictionaries = []
        sequence = None
        try:
            for profile, tag in ((source, 'kColorSyncTransformDeviceToPCS'), (destination, 'kColorSyncTransformPCSToDevice')):
                values = (p*3)(profile, self.constant('kColorSyncRenderingIntentPerceptual'), self.constant(tag))
                dictionary = self.cf.CFDictionaryCreate(None, keys, values, 3,
                    self.callback_address('kCFTypeDictionaryKeyCallBacks'),
                    self.callback_address('kCFTypeDictionaryValueCallBacks'))
                if not dictionary:
                    raise RuntimeError('Could not construct the ColorSync profile sequence.')
                dictionaries.append(dictionary)
            sequence = self.cf.CFArrayCreate(None, (p*2)(*dictionaries), 2,
                self.callback_address('kCFTypeArrayCallBacks'))
            transform = self.cs.ColorSyncTransformCreate(sequence, None)
            if not transform:
                raise RuntimeError('ColorSyncTransformCreate returned NULL.')
            return transform
        finally:
            if sequence:
                self.cf.CFRelease(sequence)
            for dictionary in dictionaries:
                self.cf.CFRelease(dictionary)

    def convert(self, transform, values):
        source = (C.c_float*3)(*values)
        destination = (C.c_float*3)()
        # 7 = kColorSync32BitFloat, 0 = no alpha/default byte order.
        ok = self.cs.ColorSyncTransformConvert(transform, 1, 1, destination, 7, 0, 12,
                                               source, 7, 0, 12, None)
        if not ok:
            raise RuntimeError('ColorSyncTransformConvert returned false.')
        return tuple(destination)

    def lab(self, rgb):
        return self.convert(self.forward, rgb)

    def adjusted(self, rgb, background):
        return self.convert(self.reverse, adjusted_lab(self.lab(rgb), self.lab(background)))

    def close(self):
        for name in ('forward', 'reverse'):
            transform = getattr(self, name, None)
            if transform:
                self.cf.CFRelease(transform)
                setattr(self, name, None)


def main():
    if platform.system() != 'Darwin':
        raise RuntimeError('Run this probe on your Mac, locally in Terminal.app.')
    if os.environ.get('TERM_PROGRAM') != 'Apple_Terminal' or os.environ.get('TMUX') or os.environ.get('SSH_CONNECTION'):
        raise RuntimeError('Open a local Terminal.app tab outside tmux/SSH and run again.')
    print('Reading the palette; this takes up to three seconds...', flush=True)
    colors = query_palette()
    missing = [str(i) for i in range(16) if i not in colors]
    print('Terminal color probe; macOS', platform.mac_ver()[0],
          '; TERM_PROGRAM_VERSION', os.environ.get('TERM_PROGRAM_VERSION', '?'))
    print('Configured default foreground:', rgb_hex(colors['fg']) if 'fg' in colors else 'no reply')
    print('Configured default background:', rgb_hex(colors['bg']) if 'bg' in colors else 'no reply')
    if missing:
        print('Palette entries without a reply:', ', '.join(missing))
    print('OSC values are configured Device RGB; predictions are modeled colors, not sampled pixels.')
    cs = NativeColorSync()
    try:
        print('\nA. Reference blue #0000B2 through native ColorSync')
        for name, background in [('WHITE', (1.,)*3), ('BLACK', (0.,)*3), ('#1E1E1E', (30/255,)*3)]:
            print(name + ':', rgb_hex(cs.adjusted(hex_rgb('0000b2'), background)))
        print('\nB. Live Terminal palette through native ColorSync')
        print('slot  configured RGB (16-bit)   on WHITE  on #1E1E1E  on CURRENT')
        for i in range(16):
            if i not in colors:
                continue
            rgb = colors[i]
            raw = '/'.join(f'{round(v*65535):04X}' for v in rgb)
            white = rgb_hex(cs.adjusted(rgb, (1.,)*3))
            dark = rgb_hex(cs.adjusted(rgb, (30/255,)*3))
            current = rgb_hex(cs.adjusted(rgb, colors['bg'])) if 'bg' in colors else 'unknown'
            print(f'{i:>2}    {raw}       {white}   {dark}     {current}')
        print('\nC. Reference blue Lab values (ColorSync encoding)')
        for value in ('0000b2', '0000ff'):
            print('#'+value.upper()+':', ' '.join(f'{v:.9g}' for v in cs.lab(hex_rgb(value))))
    finally:
        cs.close()
    print('\nD. Named-ANSI foreground swatches on the current background')
    print('Keep Dynamic foreground colors enabled for this rendering check.')
    for start in range(0, 16, 4):
        parts = []
        for i in range(start, start+4):
            sgr = 30+i if i < 8 else 90+i-8
            parts.append(f'{i:>2}: \033[0;{sgr};49m\u2588\u2588\u2588\u2588\u2588\u2588\033[0m')
        print('    '.join(parts))
    print('\nShare only the numeric results and measurement details you want to publish.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        print(f'Probe error: {error}', file=sys.stderr)
        sys.exit(1)
