# Reverse Engineering macOS Terminal.app's Dynamic Foreground Colors

## What this feature does

**Dynamic foreground colors** changes the color Terminal.app uses to draw text
from its named ANSI palette. A program can request the profile's blue while the
text is drawn with a different RGB value. Terminal derives that foreground from
the configured color and a reference background, without rewriting the palette.

For example, open Terminal.app with the **Basic** profile and Dynamic foreground
colors enabled, then run `ls -G` in a directory containing folders. The folder
names look slightly purple, even though the profile's ANSI blue is pure blue.

Other terminal apps offer a minimum-contrast adjustment; for example,
[iTerm2's Minimum Contrast](https://iterm2.com/documentation-preferences-profiles-colors.html)
shifts text colors toward black or white when they are too similar to the
background. Terminal's inspected path remaps lightness without testing a
minimum contrast threshold. That difference makes its mechanism worth
investigating and explains why copying a palette alone can miss its appearance.

The ordinary path converts foreground and background to Lab, remaps foreground
lightness, preserves the two Lab chromatic components, and converts back. This
produces background-dependent colors. The portable reproduction predicts:

| Configured foreground | Reference background | Predicted foreground |
|---|---|---|
| `#0000B2` | `#FFFFFF` | `#5230E1` |
| `#0000B2` | `#000000` | `#5230E1` |
| `#0000B2` | `#1E1E1E` | `#6A42F6` |

These are reference predictions, not recorded pixel measurements. OSC palette
queries return configured Device RGB components rather than sampled glyphs.
Copying the raw palette into another terminal therefore does not reproduce this
extra drawing calculation by itself. The inspected path does not first compute
a WCAG contrast ratio or test a minimum contrast threshold.

## Target and evidence

This single-commit repository concerns **Terminal.app 2.15 (488.9)** only.
Its Info.plist lists a minimum OS and SDK version of **27.2**; that is application
build metadata, not a disclosed runtime OS version.

Both ARM64 slices were inspected. Interpreting the ordinary lightness block on
**10,005 input pairs per slice** produced **20,010 checks with zero mismatches**.
The profile switch, reference-background handling, conversion setup, and OSC
reply path were also examined. See the [report](docs/report.md) and
[static check results](evidence/build_check.json).

On a local Mac, the installed executable matched the documented hash,
and portable and native ColorSync verification each passed all three reference
cases. The full suite passed all 12 tests after the PTY restoration assertions
were adjusted to allow macOS's managed `PENDIN` bit. The live palette probe could
not access a controlling terminal in the automation session.

In a local Terminal.app session, the maintainer used a digital color picker set
to **Display in sRGB** to verify all sixteen named-ANSI foreground swatches in
**section D** of
`python3 terminal_color_probe.py`. **All matched** the corresponding **on CURRENT**
predictions. Individual RGB readings were not supplied. See
the [device verification](docs/local-verification.md#recorded-local-mac-verification).
No captured user session, live palette, profile export, or previous-build history
is included.

## Formula

For normalized Lab lightness `f = foreground L*/100` and `b = background L*/100`:

```python
t = 0.2 + 0.8 * f
adjusted_f = b * t if f < b else b + (1 - b) * t
```

Terminal implements the remapping; ColorSync supplies the RGB/Lab conversions.
The two foreground Lab chromatic components and input alpha are preserved before
reverse conversion. This describes the ordinary `force=false` path.

## Reproduce

Python 3.9 or newer; the portable calculation needs no third-party packages:

```sh
python3 verify.py
python3 -m unittest discover -s tests -v
python3 terminal_dynamic_colors.py '#0000B2' '#1E1E1E'
# #6A42F6
```

The verifier checks three [illustrative reference cases](data/examples.json).
The portable converter uses analytical sRGB/D50 Lab conversion and per-channel
clipping; universal bit-for-bit agreement with ColorSync is not asserted.

On a Mac, compare those predictions with installed public ColorSync APIs:

```sh
python3 verify.py --engine native
```

To query a current palette and display all sixteen named-ANSI swatches, run
locally in Terminal.app outside SSH/tmux, with Dynamic foreground colors enabled:

```sh
python3 terminal_color_probe.py
```

The probe prints local color settings to stdout; it writes no report files and
uploads nothing. Independently measured swatches are the separate rendering
check. Review any live results before choosing to publish them.

[Local verification](docs/local-verification.md) also documents the optional
scalar checker, which reads a local executable and emits numeric facts without
bundling software extracts. The standard reproduction needs no binary inspection.

## Files

| Path | Purpose |
|---|---|
| `terminal_dynamic_colors.py` | Portable formula and RGB/Lab conversion |
| `terminal_color_probe.py` | Public ColorSync reproduction, local OSC queries, swatches |
| `verify.py` | Compare model reference cases with a selected conversion engine |
| `tools/check_terminal_build.py` | Optional local scalar instruction interpretation |
| `tools/inspect_terminal.py` | Optional local Mach-O inspection |
| `evidence/build_check.json` | Target-build identifiers and scalar check results |
| `evidence/validation.json` | Validation scope and counts |
| `evidence/device-verification.json` | Local Mac verification results |
| `docs/report.md` | Technical explanation, findings, and limitations |
| `docs/privacy-and-publishing.md` | Privacy audit scope and publishing instructions |

## Privacy and distribution

The archive has one new root commit, a generic author identity, and normalized
packaging timestamps. It contains no recorded local profiles, account names,
home paths, hostnames, IP addresses, credentials, remote URLs, or old Git objects.
The device verification records test results on macOS. Hardware details and
exact runtime OS and Python versions are omitted.
Build hashes and Mach-O UUIDs identify the application being studied; they are
not the Mac's hardware UUID. See [privacy and publishing](docs/privacy-and-publishing.md).

Original project code and prose use the [MIT license](LICENSE). Apple binaries,
frameworks, headers, disassembly dumps, decompiler output, and copied application
instruction sequences are excluded. The project is not affiliated with Apple
and does not claim a clean-room origin or legal clearance. See the
[rights description](docs/rights-and-reproduction.md).
