# Verify locally

## Portable reference cases

With Python 3.9 or newer:

```sh
python3 verify.py
python3 -m unittest discover -s tests -v
```

Expected RGB values are model reference predictions. They are not captured
native calculations or rendered measurements. These commands need no Apple
software extracts or binary inspection.

## Native ColorSync and rendering

On macOS, compare the reference inputs with the installed public ColorSync APIs:

```sh
python3 verify.py --engine native
```

This checks the conversion engine and modeled formula; it does not measure
Terminal's drawing or invoke its private adjustment method.

To query live configured colors and display all sixteen named-ANSI swatches,
run locally in Terminal.app outside SSH/tmux with Dynamic foreground colors enabled:

```sh
python3 terminal_color_probe.py
```

The probe prints OS/Terminal versions, default colors, live palette RGB, native
predictions, and swatches to stdout. It writes no files and uploads nothing.
Only its source is included in this repository; no live output is bundled.
If you want a local capture, keep it in the ignored directory:

```sh
mkdir -p local-evidence
python3 terminal_color_probe.py | tee local-evidence/live-probe.txt
```

Measure solid interior regions of swatches independently, recording the method,
measurement color space, exact configured input, and reference background.
Version information identifies which system performed a new reproduction.
Review the local palette/settings in any output before choosing what to publish.
A screenshot alone does not establish which color space or pipeline was sampled.

## Optional local executable inspection

The following is optional and subject to applicable software terms and law;
see the [rights description](rights-and-reproduction.md).

The local checker supports the studied ARM64 layout and reads instruction data
from your own executable. It emits build identifiers and sampled scalar results,
not disassembly. With libLLVM installed:

```sh
terminal_bin=/System/Applications/Utilities/Terminal.app/Contents/MacOS/Terminal
terminal_info=/System/Applications/Utilities/Terminal.app/Contents/Info.plist
python3 tools/check_terminal_build.py "$terminal_bin" \
  --info-plist "$terminal_info" \
  --llvm-library /path/to/libLLVM.dylib \
  --output local-evidence/build-check.json
```

Omit `--llvm-library` if libLLVM is automatically discoverable. The defaults are
10,005 pairs per slice and random seed 0. Compare the output with
[build_check.json](../evidence/build_check.json), including the executable hash.
The checked target is Terminal 2.15 (488.9); arbitrary future layouts are not
supported. Unrecognized scalar forms produce an error. These scalar checks
are not substitutes for native conversions or measured rendering.

For basic local Mach-O metadata and method identification:

```sh
python3 tools/inspect_terminal.py "$terminal_bin"
```

Optional disassembly produced by that helper should stay in `local-evidence/`.
Keep executables, profile exports, raw session dumps, and software extracts out
of published contributions. The included Git ignore rules help keep local work
separate; review staged files before committing your own changes.
