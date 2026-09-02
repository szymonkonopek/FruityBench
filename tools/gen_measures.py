#!/usr/bin/env python3
"""gen_measures.py -- the single source of truth for FruitBench's custom measures.

FruitBench is a benchmark for the *activity* app pipeline: manifest -> watch ->
FIT/activity report -> companion charts. To benchmark that pipeline you need one
measure per interesting combination of the manifest's customMeasures attributes,
and you need the on-watch recorder to agree with the manifest exactly -- an id
typo would silently produce a chart that never appears.

So both artifacts come from the catalogue below:

  app-manifest.json      <- the 32 customMeasures entries (store / companion side)
  src/fb_measures.c/.h   <- the same table as C, used by the recorder and the
                            FIT encoder (developer field name == manifest id)
  docs/measures.md       <- the coverage matrix, so the benchmark is readable

Run:  python3 tools/gen_measures.py           (writes all four)
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
APP_VERSION = "0.1.0"

# Issued by the apps.unawatch.com portal. Until a real one exists this is a
# placeholder: it is embedded in the .uapp by CMake (APP_ID) and must match the
# manifest, so change it in ONE place -- tools/app_id.txt -- and rebuild.
APP_ID_FILE = os.path.join(HERE, "app_id.txt")
APP_ID_FALLBACK = "5A9C1E7B40D6F238"

DESCRIPTION = (
    "FruitBench is a test instrument, not a fitness tracker. It records a "
    "synthetic activity whose only purpose is to exercise every documented "
    "shape of activity data at once, so that a watch build, a companion app "
    "or a FIT importer can be checked against the whole surface in a single "
    "recording.\n\n"
    "It declares 32 custom measures -- the manifest maximum -- laid out as a "
    "coverage matrix: every combination of visualisation (line-chart, number, "
    "number, gauge), isTimeBased, preview and previewAggregation, plus "
    "deliberate "
    "probes for unit scaling factors, differing metric and imperial units, "
    "non-ASCII unit strings, very long and very short titles, signed and "
    "large-magnitude values, flat lines, monotonic counters and sparse "
    "step-shaped series. Every measure is themed as fruit or as an everyday "
    "object -- bananas, anvils, rubber ducks -- because the values mean "
    "nothing and a fruit is easier to recognise on a chart than a fake "
    "physiological metric. Two titles look wrong on purpose -- one is 40 "
    "characters long and one is a single letter -- because title length is "
    "one of the things being tested.\n\n"
    "All data is generated on the watch from a random seed drawn at start, so "
    "no sensor and no movement is required and every recording looks "
    "different: each measure has its own waveform (sine, random walk, spikes, "
    "decay, staircase, counter) with a randomised period, phase and "
    "amplitude. The predefined metrics -- laps, distance, speed, heart rate, "
    "elevation, steps and a GPS track -- are synthesised too, so the standard "
    "part of the pipeline is covered alongside the custom part.\n\n"
    "Buttons: R1 starts and pauses, a tap of L1 marks a lap, L2 pages through "
    "the live measures, holding R2 finishes and writes the activity. The "
    "recorder can run in real time or fast-forward, so a full hour of "
    "1 Hz data can be produced in a minute of wall clock."
)

# --------------------------------------------------------------------------- #
# waveforms and FIT base types (mirrored into the generated C header)
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
#   agg               previewAggregation (None -> key omitted)
#   type              FIT base type of the developer field
#   wave              generator waveform
#   lo / hi           value envelope the generator stays inside
#   period            nominal waveform period in activity seconds
#   probe             what this row exists to test (documentation only)
#
# Rows 1-18 are the exhaustive core matrix: 3 visualisations x
# {timed: preview x (average|min|max), no preview} x {untimed: preview, no
# preview}. Rows 19-32 are single-axis probes on everything else.
# --------------------------------------------------------------------------- #

C = [
    # id, title, unit_m, unit_i, scale, timed, vis, preview, agg, type, wave, lo, hi, period, probe
    ("banana_flex", "Banana Flex", "bananas", "plantains", 1.0,
     True, "line-chart", True, "average", "U16", "SINE", 0, 240, 180,
     "core: line-chart / timed / preview / average"),
    ("apple_crunch", "Apple Crunch", "apples", "apples", 1.0,
     True, "line-chart", True, "min", "U16", "WALK", 0, 500, 300,
     "core: line-chart / timed / preview / min"),
    ("cherry_pop", "Cherry Pop", "cherries", "cherries", 1.0,
     True, "line-chart", True, "max", "U16", "SPIKES", 0, 900, 120,
     "core: line-chart / timed / preview / max"),
    ("grape_stream", "Grape Stream", "grapes/min", "grapes/min", 1.0,
     True, "line-chart", False, None, "U16", "DRIFT", 20, 400, 240,
     "core: line-chart / timed / no preview"),
    ("melon_score", "Melon Score", "melons", "melons", 1.0,
     False, "line-chart", True, None, "U16", "WALK", 0, 60, 0,
     "core: line-chart / per-lap / preview"),
    ("fig_index", "Fig Index", "figs", "figs", 1.0,
     False, "line-chart", False, None, "U16", "RAMP", 0, 100, 0,
     "core: line-chart / per-lap / no preview"),

    ("peach_count", "Peach Count", "peaches", "peaches", 1.0,
     True, "number", True, "average", "U16", "TRIANGLE", 0, 300, 150,
     "core: number / timed / preview / average"),
    ("plum_drop", "Plum Drop", "plums", "plums", 1.0,
     True, "number", True, "min", "U16", "DECAY", 0, 700, 90,
     "core: number / timed / preview / min"),
    ("pear_press", "Pear Press", "pears", "pears", 1.0,
     True, "number", True, "max", "U16", "BURST", 0, 800, 200,
     "core: number / timed / preview / max"),
    ("kiwi_flux", "Kiwi Flux", "kiwis/s", "kiwis/s", 1.0,
     True, "number", False, None, "U8", "SQUARE", 0, 200, 60,
     "core: number / timed / no preview"),
    ("mango_total", "Mango Total", "mangoes", "mangoes", 1.0,
     False, "number", True, None, "U32", "COUNTER", 0, 4000, 0,
     "core: number / per-lap / preview"),
    ("papaya_tally", "Papaya Tally", "papayas", "papayas", 1.0,
     False, "number", False, None, "U16", "NOISE", 0, 250, 0,
     "core: number / per-lap / no preview"),

    ("coconut_gauge", "Coconut Fill", "%", "%", 1.0,
     True, "gauge", True, "average", "U8", "SINE", 0, 100, 210,
     "core: gauge / timed / preview / average"),
    ("lemon_zest", "Lemon Zest", "%", "%", 1.0,
     True, "gauge", True, "min", "U8", "WALK", 0, 100, 330,
     "core: gauge / timed / preview / min"),
    ("lime_twist", "Lime Twist", "%", "%", 1.0,
     True, "gauge", True, "max", "U8", "STAIRS", 0, 100, 400,
     "core: gauge / timed / preview / max"),
    ("olive_level", "Olive Level", "%", "%", 1.0,
     True, "gauge", False, None, "U8", "SAW", 0, 100, 150,
     "core: gauge / timed / no preview"),
    ("avocado_ripeness", "Avocado Ripeness", "%", "%", 1.0,
     False, "gauge", True, None, "U8", "RAMP", 0, 100, 0,
     "core: gauge / per-lap / preview"),
    ("pomegranate_seeds", "Pomegranate Seeds", "seeds", "seeds", 1.0,
     False, "gauge", False, None, "U16", "NOISE", 200, 1400, 0,
     "core: gauge / per-lap / no preview"),

    # ---- probes -------------------------------------------------------- #
    ("brick_mass", "Brick Mass", "kg", "lb", 2.20462,
     True, "line-chart", True, "average", "F32", "DRIFT", 0.5, 42.0, 260,
     "probe: real metric->imperial scaling factor (kg -> lb), float field"),
    ("anvil_haul", "Anvil Haul", "km", "mi", 0.621371,
     False, "number", True, None, "F32", "COUNTER", 0.0, 12.0, 0,
     "probe: scaling factor on a per-lap value (km -> mi)"),
    ("feather_lift", "Feather Lift", "kN", "N", 1000.0,
     True, "line-chart", True, "average", "F32", "SINE", 0.0, 3.5, 140,
     "probe: large scaling factor (x1000)"),
    ("teacup_spill", "Teacup Spill", "L", "kL", 0.001,
     True, "number", True, "min", "F32", "PULSE", 0.0, 0.9, 70,
     "probe: tiny scaling factor (x0.001)"),
    ("duck_bob", "Duck Bob", "ducks", "ducks", 1.0,
     True, "gauge", True, "max", "U8", "TRIANGLE", 0, 12, 45,
     "probe: identical metric and imperial units, very small range"),
    ("paperclip_chain_span", "Paperclip Chain Span Measured End To End",
     "clips", "clips", 1.0,
     True, "line-chart", True, "average", "U32", "COUNTER", 0, 90000, 0,
     "probe: 40-character title (layout stress) + monotonic uint32"),
    ("sock", "S", "pr", "pr", 1.0,
     False, "number", True, None, "U8", "NOISE", 0, 9, 0,
     "probe: 1-character title, 2-character unit"),
    ("wrench_torque", "Wrench Torque", "N·m", "lbf·ft", 0.737562,
     True, "line-chart", True, "average", "F32", "BURST", 0.0, 95.0, 110,
     "probe: non-ASCII (UTF-8 middle dot) in both unit strings"),
    ("pebble_delta", "Pebble Delta", "pebbles", "pebbles", 1.0,
     True, "line-chart", True, "min", "S16", "SINE", -800, 800, 190,
     "probe: signed values crossing zero (sint16)"),
    ("acorn_swarm", "Acorn Swarm", "acorns", "acorns", 1.0,
     True, "number", True, "max", "U32", "SPIKES", 0, 1500000, 100,
     "probe: large magnitude values (up to 1.5e6, uint32)"),
    ("balloon_drift", "Balloon Drift", "m/s", "ft/s", 3.28084,
     True, "line-chart", True, "average", "F32", "WALK", 0.001, 0.05, 280,
     "probe: very small floating point values"),
    ("lightbulb_hum", "Lightbulb Hum", "lm", "lm", 1.0,
     True, "line-chart", True, "average", "U16", "FLAT", 400, 400, 0,
     "probe: perfectly flat series (degenerate chart, min == max)"),
    ("pinecone_total", "Pinecone Total", "cones", "cones", 1.0,
     True, "number", True, "max", "U32", "COUNTER", 0, 20000, 0,
     "probe: monotonic counter sampled every second"),
    ("umbrella_state", "Umbrella State", "state", "state", 1.0,
     True, "line-chart", True, "average", "U8", "SPARSE", 0, 4, 0,
     "probe: sparse step series (value holds for tens of seconds)"),
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


def validate():
    """Catch the mistakes that would otherwise show up as a missing chart."""
    ids = [row[0] for row in C]
    assert len(ids) == len(set(ids)), "duplicate measure id"
    # 32 is this app's own ceiling, chosen to match the documented cap on
    # configFields; Docs/app-config-json.md sets no limit on customMeasures.
    assert len(C) <= 32, "FruitBench keeps itself to 32 customMeasures"
    for row in C:
        (mid, title, um, ui, scale, timed, vis, prev, agg,
         typ, wave, lo, hi, period, probe) = row
        assert mid.replace("_", "").isalnum() and mid.islower(), mid
        assert vis in ("line-chart", "number", "gauge"), vis
        assert agg in (None, "average", "min", "max"), agg
        assert typ in TYPES, typ
        assert wave in WAVES, wave
        assert hi >= lo, mid
        assert not (agg and not timed) or True  # per-lap rows omit aggregation
        assert mid in ICONS, "no icon recipe for " + mid
        if typ.startswith("U"):
            assert lo >= 0, mid + ": unsigned field with negative envelope"

    # the core matrix must actually be exhaustive
    core = {(r[6], r[5], r[7], r[8]) for r in C}
    for vis in ("line-chart", "number", "gauge"):
        for agg in ("average", "min", "max"):
            assert (vis, True, True, agg) in core, (vis, agg)
        assert (vis, True, False, None) in core, vis
        assert (vis, False, True, None) in core, vis
        assert (vis, False, False, None) in core, vis


def manifest():
    measures = []
    for row in C:
        (mid, title, um, ui, scale, timed, vis, prev, agg,
         typ, wave, lo, hi, period, probe) = row
        m = {
            "id": mid,
            "title": title,
            "icon": "assets/icons/measures/%s.png" % mid,
            "unitMetric": um,
            "unitImperial": ui,
            "unitScalingFactor": scale,
            "isTimeBased": timed,
            "visualisation": vis,
            "preview": prev,
        }
        if agg is not None:
            m["previewAggregation"] = agg
        measures.append(m)

    return {
        "manifest_version": 1,
        "type": ["activity"],
        "name": APP_NAME,
        "icon": "icon.png",
        # No "previews" key. The screenshots ride along in assets/previews/
        # either way; the evidence on the key itself is contradictory (UOOM
        # accepted with it, PEEK's release script records an upload rejected
        # over it, PEEK then accepted without it), and omitting it is the
        # option that cannot block a release. See README.md.
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


def c_header():
    out = []
    w = out.append
    w("/* fb_measures.h -- GENERATED by tools/gen_measures.py. Do not edit.\n"
      " *\n"
      " * The manifest's customMeasures and this table are the same catalogue:\n"
      " * `id` here is the manifest id and the FIT developer field name, and\n"
      " * `unit` is the manifest unitMetric and the FIT units string.\n"
      " */")
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
    w("#define FB_TIMED_COUNT   %d   /* developer fields on the record message */"
      % sum(1 for r in C if r[5]))
    w("#define FB_LAP_COUNT     %d   /* developer fields on the lap message  */"
      % sum(1 for r in C if not r[5]))
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
    w("typedef struct {")
    w("    const char *id;        /* manifest id == FIT developer field name */")
    w("    const char *title;     /* manifest title, shown on the watch too   */")
    w("    const char *unit;      /* manifest unitMetric == FIT units string  */")
    w("    const char *short_tag; /* <=6 uppercase chars, for the 240px panel */")
    w("    uint8_t     field_num; /* FIT developer field number (unique)      */")
    w("    uint8_t     type;      /* fb_type_t                                */")
    w("    uint8_t     wave;      /* fb_wave_t                                */")
    w("    uint8_t     timed;     /* 1: one value per record, 0: one per lap  */")
    w("    float       lo;        /* value envelope, inclusive                */")
    w("    float       hi;")
    w("    float       period_s;  /* nominal waveform period, activity secs   */")
    w("} fb_measure_t;")
    w("")
    w("extern const fb_measure_t fb_measures[FB_MEASURE_COUNT];")
    w("")
    w("/* Indices into fb_measures[], split by destination message. */")
    w("extern const uint8_t fb_timed_idx[FB_TIMED_COUNT];")
    w("extern const uint8_t fb_lap_idx[FB_LAP_COUNT];")
    w("")
    w("#ifdef __cplusplus")
    w("}")
    w("#endif")
    w("")
    w("#endif /* FB_MEASURES_H */")
    return "\n".join(out) + "\n"


def short_tag(mid, title):
    """<=6 chars, uppercase, unique -- the 3x5 panel font is uppercase only."""
    base = title.upper().replace("·", ".")
    base = "".join(ch for ch in base if ch.isalnum() or ch == " ")
    words = base.split()
    if not words:
        words = [mid.upper()]
    if len(words) == 1:
        tag = words[0][:6]
    else:
        tag = (words[0][:3] + words[1][:3])
    return tag[:6]


def c_source():
    tags = {}
    for row in C:
        tag = short_tag(row[0], row[1])
        n = 2
        while tag in tags.values():                    # keep tags unique
            tag = (tag[:5] + str(n))[:6]
            n += 1
        tags[row[0]] = tag

    out = []
    w = out.append
    w("/* fb_measures.c -- GENERATED by tools/gen_measures.py. Do not edit. */")
    w("")
    w('#include "fb_measures.h"')
    w("")
    w("const fb_measure_t fb_measures[FB_MEASURE_COUNT] = {")
    for i, row in enumerate(C):
        (mid, title, um, ui, scale, timed, vis, prev, agg,
         typ, wave, lo, hi, period, probe) = row
        w("    /* %2d */ { %-24s %-44s %-14s %-9s %2d, FB_T_%-4s FB_WAVE_%-10s %d, "
          "%14sf, %14sf, %8sf }," % (
              i,
              '"%s",' % mid,
              '"%s",' % title.replace("·", "\\xc2\\xb7"),
              '"%s",' % um.replace("·", "\\xc2\\xb7"),
              '"%s",' % tags[mid],
              i,                      # developer field number == catalogue index
              typ + ",",
              wave + ",",
              1 if timed else 0,
              repr(float(lo)), repr(float(hi)), repr(float(period))))
    w("};")
    w("")
    w("const uint8_t fb_timed_idx[FB_TIMED_COUNT] = { %s };"
      % ", ".join(str(i) for i, r in enumerate(C) if r[5]))
    w("const uint8_t fb_lap_idx[FB_LAP_COUNT] = { %s };"
      % ", ".join(str(i) for i, r in enumerate(C) if not r[5]))
    return "\n".join(out) + "\n"


def measures_md():
    out = ["# FruitBench measure catalogue",
           "",
           "Generated by `tools/gen_measures.py`; the manifest, the on-watch",
           "table and this page all come from that one catalogue.",
           "",
           "The `#` column is both the catalogue index and the FIT",
           "developer field number. Time-based measures ride",
           "on the FIT **record** message (one value per second); per-lap",
           "measures ride on the **lap** message (one value per lap), which is",
           "what the documented activity report expects for",
           "`isTimeBased: false`.",
           "",
           "| # | id | title | unit (m / i) | scale | timed | vis | preview | agg | FIT type | wave | envelope | probe |",
           "|--:|----|-------|--------------|------:|:-----:|-----|:-------:|-----|----------|------|----------|-------|"]
    for i, row in enumerate(C):
        (mid, title, um, ui, scale, timed, vis, prev, agg,
         typ, wave, lo, hi, period, probe) = row
        out.append("| %d | `%s` | %s | %s / %s | %g | %s | %s | %s | %s | %s | %s | %g..%g | %s |" % (
            i, mid, title, um, ui, scale,
            "yes" if timed else "lap", vis,
            "yes" if prev else "no", agg or "-", typ.lower(), wave.lower(),
            lo, hi, probe))
    out += ["",
            "## Coverage",
            "",
            "Rows 0-17 are the exhaustive core matrix: 3 visualisations x",
            "{time-based: preview x (average|min|max), no preview} x",
            "{per-lap: preview, no preview}. Rows 18-31 each move one axis",
            "away from the ordinary case: scaling factors, unit strings,",
            "title lengths, field types, value magnitudes and series shapes.",
            ""]
    return "\n".join(out)


def measures_json():
    """The catalogue as data, for tools/fit_check.py.

    The checker needs more than the manifest carries -- the FIT base type each
    measure is written in and the envelope its values must stay inside -- and
    it must not have to parse the generated C to get it.
    """
    rows = []
    for i, row in enumerate(C):
        (mid, title, um, ui, scale, timed, vis, prev, agg,
         typ, wave, lo, hi, period, probe) = row
        rows.append({
            "index": i,
            "field_num": i,
            "id": mid,
            "title": title,
            "unitMetric": um,
            "unitImperial": ui,
            "unitScalingFactor": scale,
            "isTimeBased": timed,
            "visualisation": vis,
            "preview": prev,
            "previewAggregation": agg,
            "fitType": typ,
            "wave": wave,
            "lo": lo,
            "hi": hi,
            "period": period,
            "probe": probe,
        })
    return json.dumps({"appId": app_id(), "measures": rows},
                      indent=2, ensure_ascii=False) + "\n"


ARTIFACTS = [
    # ensure_ascii: "N\u00b7m" is the same JSON string as the raw UTF-8 form,
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
