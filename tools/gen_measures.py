#!/usr/bin/env python3
"""gen_measures.py -- the single source of truth for FruitBench's custom measures.

FruitBench is a benchmark for the *activity* app pipeline: manifest -> watch ->
FIT -> companion charts. To benchmark that pipeline you need one measure per
interesting combination of the manifest's customMeasures attributes, and you
need the on-watch recorder to agree with the manifest exactly -- an id typo
would silently produce a chart that never appears.

So every artifact comes from the catalogue below:

  app-manifest.json      <- the 32 customMeasures entries (store / companion side)
  src/fb_measures.c/.h   <- the same table as C, used by the recorder and the
                            FIT encoder (developer field name == manifest id),
                            plus the braced developer-field lists that
                            defineMessage() can only take as literals
  docs/measures.md       <- the coverage matrix, so the benchmark is readable
  docs/measures.json     <- the same, for tools/fit_check.py

## Where a measure's value goes in the FIT file

The platform rule, which this app exists to exercise:

  isTimeBased: true   value on EVERY record message. A value on session or lap
                      is optional; when present the companion app uses it as
                      the summary instead of folding the records itself, and
                      previewAggregation says how that fold would have gone.

  previewAggregation  time-based measures ONLY. Note that the annotated
                      example manifest in Docs/app-config-json.md contradicts
                      this by declaring it on non-time-based entries; the rule
                      is what this catalogue follows.

  isTimeBased: false  value for the whole activity on the session message --
                      REQUIRED. A per-lap value is optional and, when written,
                      describes that lap alone: the increment for the segment,
                      never a running total. With no session value the
                      companion falls back to the sum of the lap values, and an
                      app should not rely on that.

The `dest` column encodes exactly that, and drives which developer fields end
up on which message:

  record           time-based, records only -- the companion folds them
  record+session   time-based, plus an explicit summary folded per
                   previewAggregation (the override path)
  session          not time-based, one value for the activity, no laps
  session+lap      not time-based, plus per-lap increments that sum to it

Run:  python3 tools/gen_measures.py           (writes all five artifacts)
      python3 tools/gen_measures.py --check    (fails if anything is stale)
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --------------------------------------------------------------------------- #
# app identity
# --------------------------------------------------------------------------- #

# The display name, and the stem the packer builds the .uapp name from
# (app_merging.py is passed -name ${APP_USER_NAME}).
APP_NAME = "FruitBench"
APP_VERSION = "0.2.0"

# Issued by the apps.unawatch.com portal. It is embedded in the .uapp by CMake
# (APP_ID) and must match the manifest, so it lives in ONE place --
# tools/app_id.txt -- and a change needs a rebuild, not a manifest edit.
APP_ID_FILE = os.path.join(HERE, "app_id.txt")
APP_ID_FALLBACK = "B39E2FC2545D41D0"

DESCRIPTION = (
    "FruitBench is a test instrument, not a fitness tracker. It records a "
    "synthetic activity whose only purpose is to exercise every documented "
    "shape of activity data at once, so that a watch build, a companion app "
    "or a FIT importer can be checked against the whole surface in a single "
    "recording.\n\n"
    "It declares 32 custom measures, laid out as a coverage matrix: every "
    "combination of visualisation (line-chart, number, gauge), isTimeBased, "
    "preview and previewAggregation, plus deliberate probes for unit scaling "
    "factors, differing metric and imperial units, non-ASCII unit strings, "
    "very long and very short titles, signed and large-magnitude values, flat "
    "lines, monotonic counters and sparse step-shaped series. Every measure "
    "is themed as fruit or as an everyday object -- bananas, anvils, rubber "
    "ducks -- because the values mean nothing and a fruit is easier to "
    "recognise on a chart than a fake physiological metric. Two titles look "
    "wrong on purpose -- one is 40 characters long and one is a single letter "
    "-- because title length is one of the things being tested.\n\n"
    "The recording covers both halves of the rule about where a custom "
    "measure is written: time-based measures land on every record, half of "
    "them additionally carrying an explicit summary so that the aggregating "
    "path and the overriding path are both exercised, while measures that are "
    "not time-based always carry a value for the whole activity and, where "
    "the quantity is additive, per-lap increments that sum to it.\n\n"
    "All data is generated on the watch from a random seed drawn at start, so "
    "no sensor and no movement is required and every recording looks "
    "different: each measure has its own waveform (sine, random walk, spikes, "
    "decay, staircase, counter) with a randomised period, phase and "
    "amplitude. The predefined metrics -- laps, distance, speed, heart rate, "
    "elevation, steps and a GPS track -- are synthesised too, so the standard "
    "part of the pipeline is covered alongside the custom part. The seed is "
    "stored in the file, so any recording can be reproduced from it.\n\n"
    "Buttons: R1 starts and pauses, a tap of L1 marks a lap, L2 pages through "
    "the live measures, holding R2 finishes and writes the activity. The "
    "recorder can run in real time or fast-forward, so a full hour of "
    "1 Hz data can be produced in a minute of wall clock."
)

# --------------------------------------------------------------------------- #
# waveforms, FIT base types, destinations (mirrored into the generated header)
# --------------------------------------------------------------------------- #

WAVES = [
    "SINE",       # smooth periodic
    "TRIANGLE",   # linear up/down
    "SAW",        # ramp with hard reset
    "SQUARE",     # two-level
    "WALK",       # bounded random walk
    "SPIKES",     # quiet baseline, rare tall spikes
    "DECAY",      # exponential decay, re-triggered
    "STAIRS",     # staircase, holds then steps
    "RAMP",       # single ramp across the whole session
    "NOISE",      # uniform noise
    "PULSE",      # narrow pulse train
    "COUNTER",    # monotonic, never decreases
    "DRIFT",      # sine plus slow drift
    "BURST",      # alternating calm and agitated stretches
    "FLAT",       # constant (with a randomised level)
    "SPARSE",     # holds a value for tens of seconds, then jumps
]

TYPES = ["U8", "U16", "U32", "S16", "S32", "F32"]

AGGS = [None, "average", "min", "max"]

DESTS = ["record", "record+session", "session", "session+lap"]

# --------------------------------------------------------------------------- #
# the catalogue
#
# Columns:
#   id                manifest id  == FIT developer field name  (ASCII, stable)
#   title             what the user sees
#   unit_m / unit_i   unitMetric / unitImperial
#   scale             unitScalingFactor (metric -> imperial)
#   timed             isTimeBased
#   vis               visualisation
#   preview           preview
#   agg               previewAggregation (None -> key omitted). Time-based
#                     only: the rule says it does not apply otherwise.
#   dest              which FIT messages carry the value (see the docstring)
#   type              FIT base type of the developer field
#   wave              generator waveform
#   lo / hi           value envelope. For `record*` and `session` rows this is
#                     the range of the value itself; for `session+lap` rows it
#                     is the range of ONE LAP's increment, and the session
#                     value is the sum of those.
#   period            nominal waveform period in activity seconds (a
#                     `session+lap` row is sampled once per lap, so 240 means
#                     roughly a four-lap cycle)
#   probe             what this row exists to test (documentation only)
#
# Rows 0-17 are the exhaustive core matrix: 3 visualisations x
# {time-based: preview x (average|min|max), no preview} x {not time-based:
# preview, no preview}. Rows 18-31 are single-axis probes on everything else.
# --------------------------------------------------------------------------- #

C = [
    # ---- core matrix: line-chart ------------------------------------------ #
    ("banana_flex", "Banana Flex", "bananas", "plantains", 1.0,
     True, "line-chart", True, "average", "record+session",
     "U16", "SINE", 0, 240, 180,
     "core: line-chart / time-based / preview / average, with an explicit summary"),
    ("apple_crunch", "Apple Crunch", "apples", "apples", 1.0,
     True, "line-chart", True, "min", "record",
     "U16", "WALK", 0, 500, 300,
     "core: line-chart / time-based / preview / min, folded from the records"),
    ("cherry_pop", "Cherry Pop", "cherries", "cherries", 1.0,
     True, "line-chart", True, "max", "record+session",
     "U16", "SPIKES", 0, 900, 120,
     "core: line-chart / time-based / preview / max; a spiky series makes a "
     "wrong fold obvious"),
    ("grape_stream", "Grape Stream", "grapes/min", "grapes/min", 1.0,
     True, "line-chart", False, None, "record",
     "U16", "DRIFT", 20, 400, 240,
     "core: line-chart / time-based / no preview"),
    ("melon_score", "Melon Score", "melons", "melons", 1.0,
     False, "line-chart", True, None, "session+lap",
     "U16", "WALK", 0, 60, 240,
     "core: line-chart / not time-based / preview; per-lap increments that "
     "sum to the session value"),
    ("fig_index", "Fig Index", "figs", "figs", 1.0,
     False, "line-chart", False, None, "session",
     "U16", "RAMP", 0, 100, 0,
     "core: line-chart / not time-based / no preview; session only, no laps"),

    # ---- core matrix: number ---------------------------------------------- #
    ("peach_count", "Peach Count", "peaches", "peaches", 1.0,
     True, "number", True, "average", "record",
     "U16", "TRIANGLE", 0, 300, 150,
     "core: number / time-based / preview / average"),
    ("plum_drop", "Plum Drop", "plums", "plums", 1.0,
     True, "number", True, "min", "record+session",
     "U16", "DECAY", 0, 700, 90,
     "core: number / time-based / preview / min, with an explicit summary"),
    ("pear_press", "Pear Press", "pears", "pears", 1.0,
     True, "number", True, "max", "record",
     "U16", "BURST", 0, 800, 200,
     "core: number / time-based / preview / max"),
    ("kiwi_flux", "Kiwi Flux", "kiwis/s", "kiwis/s", 1.0,
     True, "number", False, None, "record+session",
     "U8", "SQUARE", 0, 200, 60,
     "probe: an explicit summary on a measure the manifest keeps out of the "
     "preview"),
    ("mango_total", "Mango Total", "mangoes", "mangoes", 1.0,
     False, "number", True, None, "session+lap",
     "U32", "COUNTER", 0, 500, 300,
     "core: number / not time-based / preview; the name is a total, so the lap "
     "value must be the increment and the session value the sum"),
    ("papaya_tally", "Papaya Tally", "papayas", "papayas", 1.0,
     False, "number", False, None, "session+lap",
     "U16", "NOISE", 0, 250, 0,
     "core: number / not time-based / no preview"),

    # ---- core matrix: gauge ----------------------------------------------- #
    ("coconut_gauge", "Coconut Fill", "%", "%", 1.0,
     True, "gauge", True, "average", "record+session",
     "U8", "SINE", 0, 100, 210,
     "core: gauge / time-based / preview / average, with an explicit summary"),
    ("lemon_zest", "Lemon Zest", "%", "%", 1.0,
     True, "gauge", True, "min", "record",
     "U8", "WALK", 0, 100, 330,
     "core: gauge / time-based / preview / min"),
    ("lime_twist", "Lime Twist", "%", "%", 1.0,
     True, "gauge", True, "max", "record+session",
     "U8", "STAIRS", 0, 100, 400,
     "core: gauge / time-based / preview / max, with an explicit summary"),
    ("olive_level", "Olive Level", "%", "%", 1.0,
     True, "gauge", False, None, "record",
     "U8", "SAW", 0, 100, 150,
     "core: gauge / time-based / no preview"),
    ("avocado_ripeness", "Avocado Ripeness", "%", "%", 1.0,
     False, "gauge", True, None, "session",
     "U8", "RAMP", 0, 100, 0,
     "core: gauge / not time-based / preview; a percentage does not add up, "
     "so it is session only -- the case where lap values must be absent"),
    ("pomegranate_seeds", "Pomegranate Seeds", "seeds", "seeds", 1.0,
     False, "gauge", False, None, "session+lap",
     "U16", "NOISE", 200, 1400, 0,
     "core: gauge / not time-based / no preview, with lap increments"),

    # ---- probes ----------------------------------------------------------- #
    ("brick_mass", "Brick Mass", "kg", "lb", 2.20462,
     True, "line-chart", True, "average", "record+session",
     "F32", "DRIFT", 0.5, 42.0, 260,
     "probe: real metric->imperial scaling factor (kg -> lb), float field"),
    ("anvil_haul", "Anvil Haul", "km", "mi", 0.621371,
     False, "number", True, None, "session+lap",
     "F32", "COUNTER", 0.0, 2.0, 300,
     "probe: scaling factor on an additive per-lap quantity (km -> mi)"),
    ("feather_lift", "Feather Lift", "kN", "N", 1000.0,
     True, "line-chart", True, "average", "record",
     "F32", "SINE", 0.0, 3.5, 140,
     "probe: large scaling factor (x1000)"),
    ("teacup_spill", "Teacup Spill", "L", "kL", 0.001,
     True, "number", True, "min", "record+session",
     "F32", "PULSE", 0.0, 0.9, 70,
     "probe: tiny scaling factor (x0.001); a pulse train's minimum is zero"),
    ("duck_bob", "Duck Bob", "ducks", "ducks", 1.0,
     True, "gauge", True, "max", "record",
     "U8", "TRIANGLE", 0, 12, 45,
     "probe: identical metric and imperial units, very small range"),
    ("paperclip_chain_span", "Paperclip Chain Span Measured End To End",
     "clips", "clips", 1.0,
     True, "line-chart", True, "average", "record+session",
     "U32", "COUNTER", 0, 90000, 0,
     "probe: 40-character title, monotonic uint32, and an average summary of "
     "a series that only ever rises"),
    ("sock", "S", "pr", "pr", 1.0,
     False, "number", True, None, "session",
     "U8", "NOISE", 0, 9, 0,
     "probe: 1-character title, 2-character unit, session only"),
    ("wrench_torque", "Wrench Torque", "N·m", "lbf·ft", 0.737562,
     True, "line-chart", True, "average", "record",
     "F32", "BURST", 0.0, 95.0, 110,
     "probe: non-ASCII (UTF-8 middle dot) in both unit strings"),
    ("pebble_delta", "Pebble Delta", "pebbles", "pebbles", 1.0,
     True, "line-chart", True, "min", "record+session",
     "S16", "SINE", -800, 800, 190,
     "probe: signed values crossing zero (sint16), so the summary is negative"),
    ("acorn_swarm", "Acorn Swarm", "acorns", "acorns", 1.0,
     True, "number", True, "max", "record+session",
     "U32", "SPIKES", 0, 1500000, 100,
     "probe: large magnitude values (up to 1.5e6, uint32)"),
    ("balloon_drift", "Balloon Drift", "m/s", "ft/s", 3.28084,
     True, "line-chart", True, "average", "record",
     "F32", "WALK", 0.001, 0.05, 280,
     "probe: very small floating point values"),
    ("lightbulb_hum", "Lightbulb Hum", "lm", "lm", 1.0,
     True, "line-chart", True, "average", "record+session",
     "U16", "FLAT", 400, 400, 0,
     "probe: perfectly flat series, where min == average == max"),
    ("pinecone_total", "Pinecone Total", "cones", "cones", 1.0,
     True, "number", True, "max", "record+session",
     "U32", "COUNTER", 0, 20000, 0,
     "probe: a monotonic counter that IS time-based, so its value belongs on "
     "every record and its summary is the last sample"),
    ("umbrella_state", "Umbrella State", "state", "state", 1.0,
     True, "line-chart", True, "average", "record",
     "U8", "SPARSE", 0, 4, 0,
     "probe: sparse step series (a value holds for tens of seconds)"),
]

# icon drawing recipe per measure -- consumed by tools/gen_icons.py.
# shape: how the glyph is drawn; rgb: its colour.
ICONS = {
    "banana_flex":          ("crescent", (245, 205, 60)),
    "apple_crunch":         ("apple", (214, 60, 60)),
    "cherry_pop":           ("cherries", (196, 40, 74)),
    "grape_stream":         ("cluster", (140, 90, 200)),
    "melon_score":          ("melon", (90, 180, 90)),
    "fig_index":            ("drop", (120, 70, 130)),
    "peach_count":          ("round", (250, 160, 120)),
    "plum_drop":            ("round", (120, 60, 150)),
    "pear_press":           ("pear", (190, 210, 90)),
    "kiwi_flux":            ("kiwi", (150, 175, 70)),
    "mango_total":          ("oval", (250, 175, 60)),
    "papaya_tally":         ("oval", (240, 130, 80)),
    "coconut_gauge":        ("coconut", (150, 110, 80)),
    "lemon_zest":           ("oval", (245, 225, 70)),
    "lime_twist":           ("oval", (140, 200, 70)),
    "olive_level":          ("oval", (110, 140, 60)),
    "avocado_ripeness":     ("avocado", (100, 150, 70)),
    "pomegranate_seeds":    ("seeds", (200, 50, 70)),
    "brick_mass":           ("brick", (185, 95, 70)),
    "anvil_haul":           ("anvil", (120, 128, 140)),
    "feather_lift":         ("feather", (150, 200, 240)),
    "teacup_spill":         ("cup", (235, 235, 240)),
    "duck_bob":             ("duck", (250, 205, 70)),
    "paperclip_chain_span": ("clip", (170, 180, 195)),
    "sock":                 ("sock", (230, 120, 160)),
    "wrench_torque":        ("wrench", (140, 150, 165)),
    "pebble_delta":         ("pebble", (150, 150, 155)),
    "acorn_swarm":          ("acorn", (180, 130, 70)),
    "balloon_drift":        ("balloon", (240, 90, 120)),
    "lightbulb_hum":        ("bulb", (250, 230, 140)),
    "pinecone_total":       ("pinecone", (150, 110, 65)),
    "umbrella_state":       ("umbrella", (80, 160, 210)),
}

# column indices, so the helpers below read as names rather than numbers
(I_ID, I_TITLE, I_UM, I_UI, I_SCALE, I_TIMED, I_VIS, I_PREV, I_AGG, I_DEST,
 I_TYPE, I_WAVE, I_LO, I_HI, I_PERIOD, I_PROBE) = range(16)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def app_id():
    if os.path.exists(APP_ID_FILE):
        with open(APP_ID_FILE) as fh:
            for line in fh:
                line = line.split("#", 1)[0].strip()
                if line:
                    return line
    return APP_ID_FALLBACK


def on_record(row):
    return row[I_DEST].startswith("record")


def on_session(row):
    return "session" in row[I_DEST]


def on_lap(row):
    return row[I_DEST].endswith("lap")


def validate():
    """Catch the mistakes that would otherwise show up as a missing chart."""
    ids = [row[I_ID] for row in C]
    assert len(ids) == len(set(ids)), "duplicate measure id"
    # 32 is this app's own ceiling, chosen to match the documented cap on
    # configFields; Docs/app-config-json.md sets no limit on customMeasures.
    assert len(C) <= 32, "FruitBench keeps itself to 32 customMeasures"

    for row in C:
        mid = row[I_ID]
        assert mid.replace("_", "").isalnum() and mid.islower(), mid
        assert row[I_VIS] in ("line-chart", "number", "gauge"), mid
        assert row[I_AGG] in AGGS, mid
        assert row[I_TYPE] in TYPES, mid
        assert row[I_WAVE] in WAVES, mid
        assert row[I_DEST] in DESTS, mid
        assert row[I_HI] >= row[I_LO], mid
        assert mid in ICONS, "no icon recipe for " + mid
        if row[I_TYPE].startswith("U"):
            assert row[I_LO] >= 0, mid + ": unsigned field, negative envelope"

        # The platform rule, enforced where it is still cheap to fix.
        if row[I_TIMED]:
            assert on_record(row), mid + ": time-based must be on the record"
            assert not on_lap(row), \
                mid + ": this app writes no time-based lap values"
            if row[I_PREV]:
                assert row[I_AGG] is not None, \
                    mid + ": a previewed time-based measure needs an aggregation"
        else:
            assert on_session(row) and not on_record(row), \
                mid + ": a measure that is not time-based needs a session value"
            # Settled deliberately, because the documentation disagrees with
            # itself here: the rule says previewAggregation applies to
            # time-based measures only, while the annotated example manifest in
            # Docs/app-config-json.md pairs it with "isTimeBased": false on two
            # of its three non-time-based entries (distance_to_goal,
            # speed_max). The rule wins -- and omitting an optional key is the
            # safer half of the disagreement anyway, since an absent key
            # cannot be rejected on upload. tools/fit_check.py enforces the
            # same thing against the manifest.
            assert row[I_AGG] is None, \
                mid + ": previewAggregation applies to time-based measures only"

    # the core matrix must actually be exhaustive
    core = {(r[I_VIS], r[I_TIMED], r[I_PREV], r[I_AGG]) for r in C}
    for vis in ("line-chart", "number", "gauge"):
        for agg in ("average", "min", "max"):
            assert (vis, True, True, agg) in core, (vis, agg)
        assert (vis, True, False, None) in core, vis
        assert (vis, False, True, None) in core, vis
        assert (vis, False, False, None) in core, vis

    # and every destination rule must be represented
    dests = {r[I_DEST] for r in C}
    for d in DESTS:
        assert d in dests, "no measure exercises dest=%s" % d


def manifest():
    measures = []
    for row in C:
        m = {
            "id": row[I_ID],
            "title": row[I_TITLE],
            "icon": "assets/icons/measures/%s.png" % row[I_ID],
            "unitMetric": row[I_UM],
            "unitImperial": row[I_UI],
            "unitScalingFactor": row[I_SCALE],
            "isTimeBased": row[I_TIMED],
            "visualisation": row[I_VIS],
            "preview": row[I_PREV],
        }
        if row[I_AGG] is not None:
            m["previewAggregation"] = row[I_AGG]
        measures.append(m)

    return {
        "manifest_version": 1,
        "type": ["activity"],
        "name": APP_NAME,
        "icon": "icon.png",
        # No "previews" key. The screenshots ride along in assets/previews/
        # either way; the evidence on the key itself is contradictory (of two
        # packages accepted before this one, one carried it and one did not,
        # and the one without it records an upload rejected over it), so
        # omitting it is the option that cannot block a release. See README.md.
        "binary": "%s_%s.uapp" % (APP_NAME, APP_VERSION),
        "appVersion": APP_VERSION,
        # Stamped by Utilities/Scripts/app_packer/min_kernel_version.py; the
        # value here is only a placeholder floor until tools/make_release.sh
        # runs the resolver.
        "minKernelVersion": "1.4.0",
        "requiredHardware": [],
        "description": DESCRIPTION,
        "id": app_id(),
        "stravaExport": False,
        "supportsLaps": True,
        "supportsDistance": True,
        "supportsTrack": True,
        "supportsHeartbeat": True,
        "supportsElevation": True,
        "supportsStep": True,
        "supportsSpeed": "speed",
        "customMeasures": measures,
    }


def short_tag(mid, title):
    """<=6 chars, uppercase -- the 3x5 panel font is uppercase only."""
    base = "".join(ch for ch in title.upper() if ch.isalnum() or ch == " ")
    words = base.split() or [mid.upper()]
    return (words[0][:6] if len(words) == 1
            else (words[0][:3] + words[1][:3]))[:6]


def tags():
    out = {}
    for row in C:
        tag = short_tag(row[I_ID], row[I_TITLE])
        n = 2
        while tag in out.values():                     # keep tags unique
            tag = (tag[:5] + str(n))[:6]
            n += 1
        out[row[I_ID]] = tag
    return out


def _dev_list(name, idx):
    """A wrapped `#define FB_<name>_DEV_LIST FB_DEV(i), ...` block."""
    out = ["#define FB_%s_DEV_LIST \\" % name]
    line = "    "
    for k, i in enumerate(idx):
        piece = "FB_DEV(%d)%s" % (i, "" if k == len(idx) - 1 else ", ")
        if len(line) + len(piece) > 72:
            out.append(line + "\\")
            line = "    "
        line += piece
    out.append(line)
    out.append("")
    return out


def c_header():
    rec = [i for i, r in enumerate(C) if on_record(r)]
    lap = [i for i, r in enumerate(C) if on_lap(r)]
    ses = [i for i, r in enumerate(C) if on_session(r)]

    out = []
    w = out.append
    w("/* fb_measures.h -- GENERATED by tools/gen_measures.py. Do not edit.")
    w(" *")
    w(" * The manifest's customMeasures and this table are the same catalogue:")
    w(" * `id` here is the manifest id and the FIT developer field name, and")
    w(" * `unit` is the manifest unitMetric and the FIT units string.")
    w(" */")
    w("#ifndef FB_MEASURES_H")
    w("#define FB_MEASURES_H")
    w("")
    w("#include <stdint.h>")
    w("")
    w("#ifdef __cplusplus")
    w('extern "C" {')
    w("#endif")
    w("")
    w("#define FB_MEASURE_COUNT %d" % len(C))
    w("#define FB_RECORD_COUNT  %d   /* developer fields on the record message  */"
      % len(rec))
    w("#define FB_LAP_COUNT     %d   /* developer fields on the lap message     */"
      % len(lap))
    w("#define FB_SESSION_COUNT %d   /* developer fields on the session message */"
      % len(ses))
    w("")
    w("/* Which FIT messages carry a measure's value. The platform rule:")
    w(" * time-based -> every record, session optional (and authoritative when")
    w(" * present); not time-based -> session required, lap optional and always")
    w(" * the increment for that lap alone, never a running total. */")
    w("#define FB_ON_RECORD  0x01u")
    w("#define FB_ON_SESSION 0x02u")
    w("#define FB_ON_LAP     0x04u")
    w("")
    w("/* Waveform of one measure's synthetic series. */")
    w("typedef enum {")
    for i, name in enumerate(WAVES):
        w("    FB_WAVE_%-9s = %2d," % (name, i))
    w("    FB_WAVE_COUNT")
    w("} fb_wave_t;")
    w("")
    w("/* FIT base type of the developer field carrying the measure. */")
    w("typedef enum {")
    for i, name in enumerate(TYPES):
        w("    FB_T_%-4s = %d," % (name, i))
    w("    FB_T_COUNT")
    w("} fb_type_t;")
    w("")
    w("/* previewAggregation: how a time-based measure folds into one number. */")
    w("typedef enum {")
    w("    FB_AGG_NONE = 0,")
    w("    FB_AGG_AVERAGE,")
    w("    FB_AGG_MIN,")
    w("    FB_AGG_MAX")
    w("} fb_agg_t;")
    w("")
    w("typedef struct {")
    w("    const char *id;        /* manifest id == FIT developer field name */")
    w("    const char *title;     /* manifest title, shown on the watch too   */")
    w("    const char *unit;      /* manifest unitMetric == FIT units string  */")
    w("    const char *short_tag; /* <=6 uppercase chars, for the 240px panel */")
    w("    uint8_t     field_num; /* FIT developer field number (unique)      */")
    w("    uint8_t     type;      /* fb_type_t                                */")
    w("    uint8_t     wave;      /* fb_wave_t                                */")
    w("    uint8_t     agg;       /* fb_agg_t                                 */")
    w("    uint8_t     where;     /* FB_ON_* bitmask                          */")
    w("    float       lo;        /* envelope; for an FB_ON_LAP measure this  */")
    w("    float       hi;        /* is the range of one lap's increment      */")
    w("    float       period_s;  /* nominal waveform period, activity secs   */")
    w("} fb_measure_t;")
    w("")
    w("#define FB_IS_TIMED(m)    (((m)->where & FB_ON_RECORD) != 0u)")
    w("#define FB_HAS_LAP(m)     (((m)->where & FB_ON_LAP) != 0u)")
    w("#define FB_HAS_SESSION(m) (((m)->where & FB_ON_SESSION) != 0u)")
    w("")
    w("extern const fb_measure_t fb_measures[FB_MEASURE_COUNT];")
    w("")
    w("/* Indices into fb_measures[], one list per destination message. Each is")
    w(" * also the order the developer fields appear in that message. */")
    w("extern const uint8_t fb_record_idx[FB_RECORD_COUNT];")
    w("extern const uint8_t fb_lap_idx[FB_LAP_COUNT];")
    w("extern const uint8_t fb_session_idx[FB_SESSION_COUNT];")
    w("")
    w("/* FitWriter::defineMessage takes an initializer_list, which cannot be")
    w(" * built from an array at run time, so the developer field lists are")
    w(" * generated as literals. FB_DEV(i) is defined by the caller (see")
    w(" * src/fb_fit.cpp) and expands to one FitWriter::DevField. */")
    for name, idx in (("RECORD", rec), ("LAP", lap), ("SESSION", ses)):
        out.extend(_dev_list(name, idx))
    w("#ifdef __cplusplus")
    w("}")
    w("#endif")
    w("")
    w("#endif /* FB_MEASURES_H */")
    return "\n".join(out) + "\n"


def c_source():
    tag = tags()
    agg_name = {None: "NONE", "average": "AVERAGE", "min": "MIN", "max": "MAX"}

    out = []
    w = out.append
    w("/* fb_measures.c -- GENERATED by tools/gen_measures.py. Do not edit. */")
    w("")
    w('#include "fb_measures.h"')
    w("")
    w("const fb_measure_t fb_measures[FB_MEASURE_COUNT] = {")
    for i, row in enumerate(C):
        where = []
        if on_record(row):
            where.append("FB_ON_RECORD")
        if on_session(row):
            where.append("FB_ON_SESSION")
        if on_lap(row):
            where.append("FB_ON_LAP")
        w("    /* %2d */ {" % i)
        w('        %-30s /* id        */' % ('"%s",' % row[I_ID]))
        w('        %-30s /* title     */' % ('"%s",' % row[I_TITLE]))
        w('        %-30s /* unit      */'
          % ('"%s",' % row[I_UM].replace("·", "\\xc2\\xb7")))
        w('        %-30s /* short_tag */' % ('"%s",' % tag[row[I_ID]]))
        w("        %-30s /* field_num */" % ("%d," % i))
        w("        %-30s /* type      */" % ("FB_T_%s," % row[I_TYPE]))
        w("        %-30s /* wave      */" % ("FB_WAVE_%s," % row[I_WAVE]))
        w("        %-30s /* agg       */"
          % ("FB_AGG_%s," % agg_name[row[I_AGG]]))
        w("        %-30s /* where     */" % (" | ".join(where) + ","))
        w("        %-30s /* lo, hi    */"
          % ("%sf, %sf," % (repr(float(row[I_LO])), repr(float(row[I_HI])))))
        w("        %-30s /* period_s  */" % ("%sf" % repr(float(row[I_PERIOD]))))
        w("    },")
    w("};")
    w("")
    for name, pred in (("record", on_record), ("lap", on_lap),
                       ("session", on_session)):
        idx = [str(i) for i, r in enumerate(C) if pred(r)]
        w("const uint8_t fb_%s_idx[FB_%s_COUNT] = { %s };"
          % (name, name.upper(), ", ".join(idx)))
    return "\n".join(out) + "\n"


def measures_md():
    dest_cell = {"record": "record",
                 "record+session": "record + session",
                 "session": "session",
                 "session+lap": "session + lap"}

    out = ["# FruitBench measure catalogue",
           "",
           "Generated by `tools/gen_measures.py`; the manifest, the on-watch",
           "table, the FIT developer field lists and this page all come from",
           "that one catalogue.",
           "",
           "The `#` column is both the catalogue index and the FIT developer",
           "field number. **where** is the platform rule made concrete:",
           "",
           "| where | meaning |",
           "|---|---|",
           "| `record` | time-based: a value on every record, and the companion folds them itself using `previewAggregation` |",
           "| `record + session` | the same, plus an explicit summary already folded that way -- the path where a session value overrides the aggregation |",
           "| `session` | not time-based: one value for the whole activity and no lap values, because the quantity does not add up |",
           "| `session + lap` | not time-based and additive: every lap carries its own increment and the session value is their sum |",
           "",
           "For a `session + lap` row the **envelope** is the range of *one",
           "lap's increment*, not of the session value.",
           "",
           "| # | id | title | unit (m / i) | scale | time-based | where | vis | preview | agg | FIT type | wave | envelope | probe |",
           "|--:|----|-------|--------------|------:|:----------:|-------|-----|:-------:|-----|----------|------|----------|-------|"]
    for i, row in enumerate(C):
        out.append("| %d | `%s` | %s | %s / %s | %g | %s | %s | %s | %s | %s | %s | %s | %g..%g | %s |" % (
            i, row[I_ID], row[I_TITLE], row[I_UM], row[I_UI], row[I_SCALE],
            "yes" if row[I_TIMED] else "no", dest_cell[row[I_DEST]],
            row[I_VIS], "yes" if row[I_PREV] else "no", row[I_AGG] or "-",
            row[I_TYPE].lower(), row[I_WAVE].lower(),
            row[I_LO], row[I_HI], row[I_PROBE]))

    n_rec = sum(1 for r in C if on_record(r))
    n_lap = sum(1 for r in C if on_lap(r))
    n_ses = sum(1 for r in C if on_session(r))
    out += ["",
            "## Coverage",
            "",
            "Rows 0-17 are the exhaustive core matrix: 3 visualisations x",
            "{time-based: preview x (average|min|max), no preview} x",
            "{not time-based: preview, no preview}. Rows 18-31 each move one",
            "axis away from the ordinary case: scaling factors, unit strings,",
            "title lengths, field types, value magnitudes and series shapes.",
            "",
            "Developer fields per message: **%d on record**, **%d on lap**, "
            "**%d on session**." % (n_rec, n_lap, n_ses),
            "",
            "`previewAggregation` is declared only on time-based measures, as",
            "the rule requires, and every row that is not time-based carries a",
            "session value, which the rule makes mandatory.",
            ""]
    return "\n".join(out)


def measures_json():
    """The catalogue as data, for tools/fit_check.py.

    The checker needs more than the manifest carries -- the FIT base type each
    measure is written in, which messages must carry it, and the envelope its
    values must stay inside -- and it must not have to parse the generated C.
    """
    rows = []
    for i, row in enumerate(C):
        rows.append({
            "index": i,
            "field_num": i,
            "id": row[I_ID],
            "title": row[I_TITLE],
            "unitMetric": row[I_UM],
            "unitImperial": row[I_UI],
            "unitScalingFactor": row[I_SCALE],
            "isTimeBased": row[I_TIMED],
            "visualisation": row[I_VIS],
            "preview": row[I_PREV],
            "previewAggregation": row[I_AGG],
            "dest": row[I_DEST],
            "onRecord": on_record(row),
            "onSession": on_session(row),
            "onLap": on_lap(row),
            "fitType": row[I_TYPE],
            "wave": row[I_WAVE],
            "lo": row[I_LO],
            "hi": row[I_HI],
            "period": row[I_PERIOD],
            "probe": row[I_PROBE],
        })
    return json.dumps({"appId": app_id(), "appVersion": APP_VERSION,
                       "measures": rows}, indent=2, ensure_ascii=False) + "\n"


ARTIFACTS = [
    # ensure_ascii: "N·m" is the same JSON string as the raw UTF-8 form,
    # but no accepted package has ever put a non-ASCII byte in a manifest, so
    # the probe stays in the value and out of the file's encoding.
    ("app-manifest.json", lambda: json.dumps(manifest(), indent=2,
                                             ensure_ascii=True) + "\n"),
    ("src/fb_measures.h", c_header),
    ("src/fb_measures.c", c_source),
    ("docs/measures.md", measures_md),
    ("docs/measures.json", measures_json),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any generated file is stale")
    args = ap.parse_args()

    validate()

    stale = []
    for rel, fn in ARTIFACTS:
        path = os.path.join(ROOT, rel)
        text = fn()
        if args.check:
            old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if old != text:
                stale.append(rel)
            continue
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        print("wrote %s" % rel)

    if args.check:
        if stale:
            print("stale: %s" % ", ".join(stale), file=sys.stderr)
            return 1
        print("all generated files up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
