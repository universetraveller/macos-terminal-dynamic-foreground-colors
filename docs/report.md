# Dynamic foreground colors in Terminal.app 2.15 (488.9)

## What the feature actually does

Dynamic foreground colors is a per-profile rule for deriving a **drawing
color** from a configured named ANSI foreground and a reference background.
Requesting the profile's blue need not draw the RGB numbers stored in the
profile. The palette remains distinct from the color returned for drawing.

The ordinary lookup obtains the view's `_currentBackgroundColor`. The named
palette branch checks `DynamicANSIForegroundColors` and, when enabled, passes
the configured color and reference background to the adjustment wrapper with
`force=false`. A missing reference background bypasses the adjustment. Disabling
the switch bypasses this adjustment in that branch; ordinary color management
still applies.

The indexed-color and direct-RGB branches of the inspected lookup return before
that setting check. This does not establish the behavior of every escape
sequence or drawing situation. The reference is a color object supplied to the
method, not a sample of the final composited wallpaper or glyph-edge pixels.

The mechanism remaps lightness whenever the ordinary path is enabled. It does
not calculate a WCAG contrast ratio, wait for low contrast, or iterate toward
a target threshold. Preserving Lab chromatic components does not preserve RGB
channels: changing lightness and converting back can make an initially zero
red or green channel nonzero. Gamut clipping can further change RGB results.

OSC queries report configured Device RGB components rather than the adjusted
glyph color. This explains why importing an ANSI palette into another terminal
can produce a different appearance even with the same numeric palette entries.

## Target and provenance

The findings concern the supplied **Terminal.app 2.15 (488.9)** executable.
The formula and conversion sequence were identified by local static inspection
of both ARM64 slices. This repository contains an original explanation and
reimplementation, factual build identifiers, and numeric static-check results.
It does not contain the application, disassembly, or copied instruction sequences.
Development was informed by binary inspection; a clean-room origin is not claimed.

| Field | Value |
|---|---|
| Application version | 2.15 |
| Application build | 488.9 |
| Minimum OS in Info.plist | 27.2 |
| SDK version in Info.plist | 27.2 |
| SDK build in Info.plist | `26B106` |
| Executable size | 2,470,176 bytes |
| Executable SHA-256 | `abcdb6863771b0c6768d81aa7ce20e6e161c905cbc8665db9b8441380ff6805a` |
| ARM64 slices inspected | 2 |

Minimum OS and SDK values do not establish an actual runtime OS version.
Application UUIDs, CPU subtypes, file offsets, and slice hashes are retained in
[build_check.json](../evidence/build_check.json). These identifiers describe
application slices; no hardware UUID, local profile, or user account is recorded.
The separate real-device verification below omits hardware details and exact
runtime OS and Python versions.

## Formula

Normalize the foreground and reference-background Lab lightness:

```math
f = \frac{L^*_{\mathrm{foreground}}}{100},\qquad
b = \frac{L^*_{\mathrm{background}}}{100}.
```

The ordinary path computes

```math
t = 0.2 + 0.8 f,\qquad
f' =
\begin{cases}
b\,t & \text{if } f < b, \\
b + (1-b)t & \text{if } f \ge b.
\end{cases}
```

Equality takes the second branch. The two foreground Lab chromatic components
remain unchanged, and Terminal preserves input alpha when constructing the
result. The additional `force` branch is outside this formula.

For a completely white or black reference background, the expression reduces
to:

```math
f' = 0.2 + 0.8f.
```

An intermediate background produces a different result.
These remapping operations are in Terminal; ColorSync performs the conversions.

## Conversion sequence and precision

The implementation uses `kColorSyncSRGBProfile`, `kColorSyncGenericLabProfile`,
`kColorSyncRenderingIntentPerceptual`, and 32-bit float buffers. It converts
foreground and background separately, changes foreground lightness, and
converts the adjusted foreground back to RGB.

The NSColor wrapper obtains Device RGB components before their numeric values
enter the sRGB-profile transform. It constructs Device RGB output. A reproduction
must distinguish these numeric components from color-managed screen readings.
The first ColorSync Lab buffer component is normalized lightness; the other two
are encoded chromatic components, not conventional unnormalized a*/b* numbers.

The scalar block performs double-precision arithmetic, including fused
multiply-add operations, after promoting float32 lightness inputs. Its result
is converted back to float32. The local checker models these operations.

OSC replies extract Device RGB components and round channels to sixteen bits.
The portable parser accepts `RRRR/GGGG/BBBB` inputs to retain that precision.
Reducing an input to eight bits first can change the final RGB rounding.

## Static validation

The checker reads the scalar block from a locally supplied executable at run
time. No application instruction bytes or disassembly text are embedded in the
checker or its archived result.

| Slice | Core method address | Core size | Instructions | Pairs checked | Mismatches |
|---|---|---|---|---|---|
| 0 | `0x100024D9C` | 1,132 bytes | 283 | 10,005 | 0 |
| 1 | `0x1000242A8` | 1,132 bytes | 283 | 10,005 | 0 |

Each slice uses five endpoint/equality cases and 10,000 deterministic random
pairs, seed 0. The interpreted final float32 result is compared with the
mathematical implementation. Across the two slices this gives **20,010 scalar
checks with zero mismatches**. The disassembler used for these checks was
LLVM 19.1.7. This is sampled verification, not a proof for every possible input.

The relevant callers and conversion setup were also inspected: the profile
switch, current-background reference, ordinary `force=false` argument, separate
indexed/direct-RGB routes, Device RGB wrapper, and sixteen-bit OSC formatting.

These static checks do not run Terminal, AppKit, or ColorSync and do not sample
glyph pixels. Native ColorSync was exercised separately on the real device
described below. See [validation.json](../evidence/validation.json).

## Real-device verification

Verification ran on a local Mac. Hardware details and exact runtime OS and
Python versions are omitted. The installed **Terminal 2.15 (488.9)** executable
matched the SHA-256 listed above.

Both `python3 verify.py` and `python3 verify.py --engine native` checked all three
reference inputs with **zero mismatches**. The native run called the installed
public ColorSync APIs and returned `#5230E1` on white and black, and `#6A42F6` on
`#1E1E1E`, for foreground `#0000B2`. These are native model-calculation results,
not sampled Terminal pixels or direct calls to its private adjustment method.

The full unittest suite passed **all 12 tests**, with none skipped, after the
restoration assertions were adjusted to allow only macOS's managed `PENDIN` bit
in the local flags. Every other terminal setting is still compared. The initial
run had 9 passes and 3 failures from strict PTY restoration comparisons: macOS
set `PENDIN` (`0x20000000`) after the saved settings were reapplied. A standalone
`tty.setraw()`/`termios.tcsetattr()` experiment reproduced that difference without
using the probe. The native ColorSync test passed in both runs.

The live probe could not open `/dev/tty` in the automation session because it
had no controlling terminal. The maintainer ran `python3 terminal_color_probe.py`
in a local Terminal.app session and used a digital color picker set to
**Display in sRGB** to verify the rendered named-ANSI foreground swatches in
**section D**. **All sixteen swatches
(slots 0–15) matched** their corresponding **on CURRENT** predictions in section B.
This is a maintainer-reported rendering check, separate from the automated native
ColorSync calculations. Individual RGB readings were not supplied; the
repository records the method, sRGB display setting, and match results
without a raw measurement transcript, live palette dump, or screenshot.

The [local verification notes](local-verification.md#recorded-local-mac-verification)
and [device results](../evidence/device-verification.json) record the scope,
commands, outputs, and limits. Agreement on these three cases does not establish
universal equivalence between the portable converter and ColorSync.

## Reference predictions and reproduction

The portable converter uses analytical sRGB/D50 Lab conversion and channel
clipping. It predicts the following illustrative cases:

| Input | Reference background | Predicted RGB |
|---|---|---|
| `#0000B2` | `#FFFFFF` | `#5230E1` |
| `#0000B2` | `#000000` | `#5230E1` |
| `#0000B2` | `#1E1E1E` | `#6A42F6` |

The examples are explicit model reference cases. They do not record anyone's
live palette or profile and are not presented as target-build pixel readings.
Universal bit-for-bit equivalence to ColorSync is not asserted.

Run `python3 verify.py` for the portable cases. On macOS,
`python3 verify.py --engine native` compares them with installed public ColorSync
APIs without TTY queries or private Terminal method calls. The live probe queries
colors and displays named-ANSI swatches for a separate, independent rendering
check. [Local verification](local-verification.md) explains both procedures.

The findings cover the ordinary path in the identified application build.
They do not establish behavior for the extra `force` branch, every SGR encoding,
selection/reverse video, transparency, or future builds. No user-session data
or previous-build comparisons are included in this single-commit distribution.

## References and distribution

- [Static build check](../evidence/build_check.json).
- [Model reference cases](../data/examples.json).
- [Apple: ColorSyncTransformCreate](https://developer.apple.com/documentation/colorsync/colorsynctransformcreate(_:_:)).
- [Apple: ColorSync pixel format](https://developer.apple.com/documentation/colorsync/pixel-format).
- [Privacy and publishing](privacy-and-publishing.md).
- [Copyright and local verification](rights-and-reproduction.md).

Apple API references describe conversion interfaces, not the Terminal-specific
formula. That formula was identified from the supplied executable; only the
original mathematical description and reimplementation are distributed.
