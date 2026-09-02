# FruitBench

A benchmark for the UNA Watch **activity** pipeline: manifest → watch →
FIT / activity report → companion charts.

It is a test instrument, not a fitness tracker. One recording exercises every
documented shape of activity data at once, so a watch build, a companion app or
a FIT importer can be judged against the whole surface instead of one metric at
a time. The values are fruit and household objects — bananas, anvils, rubber
ducks — because they mean nothing and a fruit is easier to recognise on a chart
than a fake physiological metric.

![32 measures from one 15-minute session](docs/example-charts.png)

*Every chart above came out of `docs/example-session.fit`, which the desktop
test produced from seed `0x51ED27A3` — see [Verifying](#verifying).*

## What it measures

- **32 custom measures** — the platform documents no cap on them, so 32 is
  this app's own ceiling, borrowed from the documented limit on `configFields`.
  Rows 0–17 are an exhaustive
  matrix of every combination of `visualisation` (line-chart, number, gauge) ×
  `isTimeBased` × `preview` × `previewAggregation`. Rows 18–31 each move one
  axis away from the ordinary case: unit scaling factors (×1000 down to
  ×0.001), differing metric and imperial units, a non-ASCII unit string, a
  40-character title, a 1-character title, signed values crossing zero,
  magnitudes up to 1.5 × 10⁶, tiny floats, a perfectly flat series, monotonic
  counters and a sparse step series. The full table is
  [docs/measures.md](docs/measures.md).
- **All the predefined metrics too** — laps, distance, speed, heart rate,
  elevation, steps and a GPS track — so the standard half of the pipeline is
  covered by the same recording.
- **Six FIT base types** across the developer fields (uint8/16/32, sint16/32,
  float32), because a companion app that handles `uint16` need not handle a
  signed or floating-point field.

Nothing is sensed. Every value comes from a generator seeded at start, so the
app works in a drawer, needs no hardware (`requiredHardware: []`), and no two
recordings look alike: each measure has its own waveform (sine, triangle, saw,
square, random walk, spikes, decay, staircase, ramp, noise, pulse train,
counter, drift, burst, flat, sparse) with a randomised period, phase and
amplitude, clamped to the envelope its catalogue row declares.

## How the measures reach the file

| manifest | FIT | what the docs say it becomes |
|---|---|---|
| `isTimeBased: true` (24 of them) | developer field on `record`, 1 Hz | `[[t, value], …]` |
| `isTimeBased: false` (8 of them) | developer field on `lap`, one per lap | `[value_lap0, value_lap1, …]` |

A per-lap measure is not a different series — it is the same series read once
per lap, at the boundary. That matters for the counters: `mango_total`'s lap
value is its reading when the lap closed, not an average over it.

The developer field's `field_name` is the manifest's measure `id` **verbatim**
and its `units` is `unitMetric`. The file also carries the session seed as
`file_id.serial_number`, so any recording can be reproduced from the file
itself: `tools/host_test.sh --seconds N --seed 0x<that value>`.

That last sentence is an assertion, not a documented fact, and it is the single
most interesting thing this app can tell you. The SDK defines no mapping
between `customMeasures` and FIT developer fields — the shipped example apps
use developer field numbers that collide across apps (`4` is `hr_source` in
Running and `lap_resting_cal` in Workout) and names that match no manifest id
anywhere. So FruitBench asserts the obvious convention and lets the companion
app agree or disagree visibly: whatever appears (or fails to appear) as a chart
is the answer.

## Layout

```
app-manifest.json        generated -- the 32 customMeasures, the store metadata
CMakeLists.txt           the watch build (Activity app, two ELFs -> one .uapp)
src/
  fb_measures.h/.c       generated -- the catalogue as C
  fb_gen.h/.c            the generator: waveforms, predefined metrics, a seed
  fb_fmt.h/.c            how a value is written out, shared by screen and log
  fb_fit.hpp/.cpp        the recorder: 32 developer fields over SDK::Fit
  Service.hpp/.cpp       the recorder process (owns the clock and the file)
  fb_msg.hpp             the two app-private messages, GUI <-> Service
  fb_snap.h              what the recorder tells the screen
  FbMain.cpp             the GUI process entry point (no TouchGFX Designer)
  fb_una_platform.cpp    fb_plat for the watch
  fb_ui.h/.c             the screen: home, recording, summary
  fb_video.*, fb_text.*, fb_font.h   240x240 panel, 3x5 font
host/                    the same screen on a laptop, for layout and previews
tools/                   the generators, the build, the desktop test, the checks
docs/                    the measure matrix, an example session and its charts
```

The recorder is a **separate process** from the screen, as in the SDK's own
activity apps: the recording carries on while the GUI is suspended or closed,
and the screen is a client that sends commands and receives one snapshot a
second.

## Buttons

| | home | recording | summary |
|---|---|---|---|
| **R1** | start | pause / resume | record again |
| **L1** | span (open / 15 / 30 / 60 min) | mark a lap | — |
| **L2** | mode (live 1× / fast 10× / turbo 60×) | next page of measures | — |
| **R2** | exit | *hold* to finish and save | exit |

`L1+R2` leaves the screen without stopping the recording.

**Fast and turbo** run the activity clock faster than the wall clock: turbo
writes 60 activity seconds per real second, so a full hour of 1 Hz data takes a
minute. Such a recording is backdated by its span, so its timestamps end at
about the moment the file is closed rather than running into the future. Laps
are automatic — every five minutes when live, eight per span when fast — and
`L1` adds one by hand.

## Building for the watch

Needs STM32CubeCLT (for `arm-none-eabi-gcc`) and a `una-sdk` checkout beside
this directory.

```sh
tools/build.sh                      # -> Output/FruitBench_<version>.uapp
UNA_SDK=~/src/una-sdk tools/build.sh clean
```

The script regenerates the catalogue first, so `app-manifest.json` and the
table compiled into the watch cannot drift apart.

## Verifying

The 32 developer fields are the whole app, and they can be checked without a
watch. `tools/host_test.sh` compiles the **real** recorder (`fb_fit.cpp`,
`fb_gen.c`) against the SDK's FIT encoder with a stdio `IFile`, writes a full
session, and hands the result to a decoder that holds it against the catalogue:

```sh
tools/host_test.sh --seconds 3600           # an hour of data, random seed
tools/host_test.sh --seconds 900 --seed 0x51ED27A3
python3 tools/fit_check.py docs/example-session.fit
python3 tools/fit_plot.py  docs/example-session.fit -o charts.png
```

`fit_check.py` verifies both CRCs and the header's data size, that there is one
`field_description` per declared measure with the right name, units and base
type, that every time-based measure landed on `record` and every per-lap one on
`lap` (and neither on the other), that every value is inside its declared
envelope, that timestamps are monotonic, that `file_id` identifies the device
as Una / UNA Watch and carries a seed, and that the session's lap count matches
the lap messages. It prints min/avg/max per measure, which is the
quickest way to see a session is varied rather than 32 flat lines.

For the screen, `make -C host && ./host/fb_host --frames 90 --script "3:e,4:d"
--dump shot.ppm` runs the real UI code on the desktop; the store previews are
rendered that way (`tools/gen_previews.py`).

Measured on this machine: **85–89 bytes per record**, so a one-hour 1 Hz session
is about **300 KB** — 57 of those bytes are the 24 developer fields on the
record message, 18 more ride on each lap.

## Packaging for the store

```sh
tools/make_release.sh               # -> release/FruitBench_<version>.zip
```

The archive holds the `.uapp`, `app-manifest.json`, `icon.png`, the two app
icons and the 32 measure icons under `assets/icons/`, and five screenshots
under `assets/previews/`. Before zipping, the script fails the release if the
App ID in `tools/app_id.txt`, in the manifest and in the built image disagree,
if the manifest's measure ids and the compiled table differ, if a manifest icon
is missing from the package, or if `min_kernel_version.py --check` or
`validate_app_config.py --check` reject the manifest.

Two deliberate manifest decisions:

- **No `previews` key**, though the screenshots do ship under
  `assets/previews/`. The evidence here is contradictory: UOOM was accepted
  *with* the key, PEEK's release script records an upload rejected *over* it,
  and PEEK was then accepted without it while shipping the same folder. Since
  a rejected upload blocks a release and a listing that has to be pointed at
  its screenshots by hand does not, the key is left out. Putting it back is
  one line in `tools/gen_measures.py` if the portal accepts it.
- **No `configFields`.** They are documented and the SDK validates them, but a
  benchmark that cannot be uploaded is worth nothing; the rate and span are
  chosen on the watch instead.

## The App ID

`tools/app_id.txt` holds the App ID issued by <https://apps.unawatch.com>:

```
B39E2FC2545D41D0
```

Three artifacts have to agree on it and `tools/make_release.sh` fails the
release if they do not: this file, the manifest's `id`, and the little-endian
u64 at offset 0 of the built `.uapp`. Because the ID is stamped into the image,
changing it needs a rebuild, not a manifest edit. It also travels into every
FIT file as `developer_data_id.application_id`, which is how a reader ties a
developer field back to this app.

## Regenerating what is generated

```sh
python3 tools/gen_measures.py           # manifest, src/fb_measures.*, docs/
python3 tools/gen_measures.py --check   # fail if any of them is stale
python3 tools/gen_icons.py              # 32 measure icons + 3 app icons
```

To add or change a measure, edit the catalogue in `tools/gen_measures.py` and
run both. The generator refuses to emit a catalogue that is not exhaustive over
the core matrix, that repeats an id, that exceeds 32 measures, that gives an
unsigned FIT field a negative envelope, or that names an icon recipe it does
not have — the mistakes that would otherwise show up as one silently missing
chart on a phone. Note that `fb_fit.cpp` lists its developer fields explicitly,
with a `static_assert` on the counts: changing how many measures are
time-based means updating those two lists.

## Provenance

The panel buffer, the 3×5 font renderer and the no-Designer GUI arrangement
come from PEEK and UOOM. Two font glyphs are new: `M` and `N` were
byte-identical there, which turned BENCHMARK into BEHCHMARK on the panel.
