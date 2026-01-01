#!/usr/bin/env python3
"""Check a locally supplied Terminal build without distributing software extracts.

This deliberately limited helper supports the ARM64 layouts studied here. It
reads instructions from the supplied file at run time, interprets the ordinary
lightness block, and emits numeric results and build identifiers only. It does
not execute Terminal or test ColorSync, AppKit, or rendered pixels.
"""

import argparse
import bisect
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import plistlib
import random
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from terminal_dynamic_colors import adjust_lightness, float32
from inspect_terminal import MachO, split_slices

CORE = 'adjustedColorWithRed:green:blue:alpha:withBackgroundColor:force:'


def fused_multiply_add(a, b, c):
    """One binary64 rounding, including on Python versions without math.fma."""
    return float(Fraction(a) * Fraction(b) + Fraction(c))


def method_bounds(image, method):
    start = method['imp']
    index = bisect.bisect_right(image.starts, start)
    if index == len(image.starts):
        raise ValueError('No following function boundary for the selected method.')
    return start, image.starts[index]



class LightnessProgram:
    """A bounded interpreter for the scalar instructions encountered locally."""

    def __init__(self, image, method):
        self.image = image
        start, end = method_bounds(image, method)
        self.instructions = {pc: image.dis_one(pc) for pc in range(start, end, 4)}
        candidates = [pc for pc, text in self.instructions.items()
                      if re.fullmatch(r'fcmp\s+s\d+, s\d+', text)]
        if len(candidates) != 1:
            raise ValueError('Expected one scalar float32 lightness comparison.')
        self.start = candidates[0]
        self.source_registers = re.findall(r's\d+', self.instructions[self.start])
        self.double_registers = {}
        for pc in range(start, self.start, 4):
            match = re.fullmatch(r'fcvt\s+(d\d+), (s\d+)', self.instructions[pc])
            if match and match[2] in self.source_registers:
                self.double_registers[match[2]] = match[1]
        if set(self.double_registers) != set(self.source_registers):
            raise ValueError('Could not identify the initial double-precision operands.')

    def run(self, foreground, background):
        floating, general = {}, {}

        def put(register, value):
            width = register[0]
            floating[int(register[1:])] = struct.unpack(
                '<I' if width == 's' else '<Q',
                struct.pack('<f' if width == 's' else '<d', value))[0]

        def get(register):
            bits = floating[int(register[1:])]
            if register[0] == 's':
                return struct.unpack('<f', struct.pack('<I', bits & 0xffffffff))[0]
            return struct.unpack('<d', struct.pack('<Q', bits))[0]

        for source, value in zip(self.source_registers, (foreground, background)):
            put(source, value)
            put(self.double_registers[source], get(source))
        pc, comparison = self.start, None
        for _ in range(64):
            text = self.instructions.get(pc)
            if text is None:
                raise ValueError('Lightness execution left the selected method.')
            opcode, operands = text.split(None, 1)
            args = [part.strip() for part in operands.split(',')]
            following = pc + 4
            if opcode == 'fcmp':
                comparison = get(args[0]) - get(args[1])
            elif opcode in ('b', 'b.pl', 'b.mi'):
                if opcode == 'b' or (opcode == 'b.pl' and comparison >= 0) or (
                        opcode == 'b.mi' and comparison < 0):
                    following = pc + int(operands.lstrip('#'), 0)
            elif opcode == 'adrp':
                general[args[0]] = (pc & ~0xfff) + int(args[1].lstrip('#'), 0)
            elif opcode == 'ldr':
                match = re.fullmatch(r'(d\d+), \[(x\d+), #(-?\d+)\]', operands)
                if not match:
                    raise ValueError('Unsupported constant load in lightness block.')
                address = general[match[2]] + int(match[3])
                put(match[1], self.image.vunpack('<d', address)[0])
            elif opcode == 'fmov':
                put(args[0], float(args[1].lstrip('#')))
            elif opcode == 'fsub':
                put(args[0], get(args[1]) - get(args[2]))
            elif opcode == 'fmul':
                put(args[0], get(args[1]) * get(args[2]))
            elif opcode == 'fmadd':
                put(args[0], fused_multiply_add(get(args[1]), get(args[2]), get(args[3])))
            elif opcode == 'fcvt' and args[0].startswith('s'):
                put(args[0], get(args[1]))
                return get(args[0])
            else:
                raise ValueError('Unsupported instruction in lightness block: ' + opcode)
            pc = following
        raise ValueError('Lightness execution exceeded the instruction limit.')


def sample_pairs(count, seed):
    if count < 5:
        raise ValueError('At least five samples are required for the boundary cases.')
    yield from ((0, 0), (0, 1), (1, 0), (1, 1), (.5, .5))
    rng = random.Random(seed)
    for _ in range(count - 5):
        yield float32(rng.random()), float32(rng.random())


def inspect_build(binary, info_plist=None, llvm_library=None, samples=10005, seed=0):
    data = Path(binary).read_bytes()
    metadata = {'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                'image_base': '0x100000000', 'slices': []}
    if info_plist:
        info = plistlib.loads(Path(info_plist).read_bytes())
        for field, key in (
                ('terminal_short_version', 'CFBundleShortVersionString'),
                ('terminal_build', 'CFBundleVersion'),
                ('minimum_os_from_info_plist', 'LSMinimumSystemVersion'),
                ('sdk_version_from_info_plist', 'DTPlatformVersion'),
                ('sdk_build_from_info_plist', 'DTSDKBuild')):
            metadata[field] = info.get(key)
    checks = []
    for index, data_slice in enumerate(split_slices(data)):
        image = MachO(data_slice, llvm_library=llvm_library, disassembly=True)
        cpu, subtype = image.unpack('<II', 4)
        if cpu != 0x100000c:
            raise ValueError('Only ARM64 slices are supported by this checker.')
        methods = {method['name']: method for method in image.methods}
        core = methods[CORE]
        identity = {'index': index, 'cpu_type': hex(cpu), 'cpu_subtype': hex(subtype),
                    'size_bytes': len(data_slice),
                    'sha256': hashlib.sha256(data_slice).hexdigest(),
                    'uuid_hex': data_slice[image.cmds[0x1b]+8:image.cmds[0x1b]+24].hex(),
                    'adjustment_method_address': hex(core['imp'])}
        if data[:4] == b'\xca\xfe\xba\xbe':
            identity['file_offset'] = hex(struct.unpack_from('>I', data, 8+20*index+8)[0])
        metadata['slices'].append(identity)
        program = LightnessProgram(image, core)
        mismatch_count = 0
        for foreground, background in sample_pairs(samples, seed):
            expected = float32(adjust_lightness(foreground, background))
            mismatch_count += program.run(foreground, background) != expected
        start, end = method_bounds(image, core)
        checks.append({'slice_index': index,
                       'core': {'method_address': hex(start), 'size_bytes': end-start,
                                'instruction_count': (end-start)//4},
                       'ordinary_lightness': {
                           'entry_address': hex(program.start), 'sample_count': samples,
                           'random_seed': seed, 'mismatches': mismatch_count,
                           'scope': 'Interpreted scalar block; no ColorSync, AppKit, or pixel test.'}})
    return {'metadata': metadata, 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('--info-plist', type=Path)
    parser.add_argument('--llvm-library')
    parser.add_argument('--samples', type=int, default=10005)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        build = inspect_build(args.binary, args.info_plist, args.llvm_library,
                              args.samples, args.seed)
        result = {'schema_version': 1, 'build': build,
                  'limits': 'Sampled scalar interpretation; no live ColorSync, AppKit, or rendering measurement.'}
        output = json.dumps(result, indent=2) + '\n'
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output)
        else:
            print(output, end='')
        return int(any(check['ordinary_lightness']['mismatches']
                       for check in build['checks']))
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
