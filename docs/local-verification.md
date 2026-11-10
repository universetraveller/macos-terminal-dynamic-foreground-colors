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

For the rendering check, use a local Terminal.app session with Dynamic
foreground colors enabled. Compare each **section D** swatch, labeled 0 through
15, with the same slot's **on CURRENT** prediction in section B. Sample a solid
interior region of each block, and record the picker's color-space setting and
the expected and observed RGB values. If an automated session cannot access
Terminal, a person can run this step locally and report the results. A shared
summary can contain slot numbers, match results, and measurement method without
including machine details or a full probe transcript.

## Recorded local Mac verification

The following checks ran on a local Mac. The installed Terminal
executable's SHA-256 matched the target in
[build_check.json](../evidence/build_check.json). Only verification scope and
verification results are recorded in
[device-verification.json](../evidence/device-verification.json); no live palette
or session transcript is included.

| Environment | Value |
|---|---|
| Platform | macOS; hardware and exact runtime versions omitted |
| Terminal | 2.15 (488.9) |

| Command | Observed result |
|---|---|
| `python3 verify.py` | 3 reference cases, 0 mismatches |
| `python3 verify.py --engine native` | 3 reference cases, 0 mismatches; installed public ColorSync APIs executed |
| `python3 -m unittest discover -s tests -v` | After the macOS assertion adjustment: 12 tests run, all passed, none skipped |
| `python3 terminal_color_probe.py` (automation) | Could not open `/dev/tty`: no controlling terminal was configured for the automation session |
| `python3 terminal_color_probe.py` (maintainer's local Terminal.app session) | All 16 section D swatches checked with a digital color picker set to **Display in sRGB**; all matched section B's corresponding **on CURRENT** predictions |

The native ColorSync calculations returned these eight-bit RGB values:

| Foreground | Reference background | Portable prediction | Native ColorSync result |
|---|---|---|---|
| `#0000B2` | `#FFFFFF` | `#5230E1` | `#5230E1` |
| `#0000B2` | `#000000` | `#5230E1` | `#5230E1` |
| `#0000B2` | `#1E1E1E` | `#6A42F6` | `#6A42F6` |

Before the assertion adjustment, 9 tests passed and 3 failed. The failures were
the PTY cleanup assertions after a successful query, a timeout, and a simulated
read error. In each case the restored local flags
differed by `PENDIN` (`0x20000000`). A separate PTY experiment using only
`tty.setraw()` and `termios.tcsetattr()` reproduced that flag change. These
initial failures are retained in the evidence; the native ColorSync test passed.

[Apple's tty implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/tty.c#L1313-L1345)
sets `PENDIN` when canonical input mode is restored. The test assertions now
ignore only that bit in the local flags on macOS and continue comparing every
other terminal setting. No machine settings or probe behavior changed. The
rerun passed all 12 tests. Separate checks that deliberately changed `ECHO` and
`ICANON` confirmed that the restoration assertion still rejects those changes.

The maintainer completed the rendering check in a local Terminal.app session
using a digital color picker set to **Display in sRGB** on **section D** of
`python3 terminal_color_probe.py`.
All sixteen swatches (slots 0–15) matched the corresponding **on CURRENT**
predictions in section B. This is a maintainer-reported check of the rendered
colors, with picker readings displayed in sRGB, separate from the automated
native ColorSync calculations. Individual RGB readings were not supplied, so the repository
records the method, color-space setting, and match results without a numeric
measurement transcript.

The automated native check validates the modeled conversion path for the three
reference inputs above; it does not invoke Terminal's private adjustment method
or measure its rendering. The automation session's lack of a controlling
terminal did not prevent the maintainer from completing the live swatch check.

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
