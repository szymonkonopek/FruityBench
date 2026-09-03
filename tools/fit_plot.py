#!/usr/bin/env python3
"""fit_plot.py -- draw every measure in a FruitBench .fit as a small chart.

The point of the app is what a companion app will show, and the fastest way to
know whether a recording is worth charting is to chart it here first. This
reads the file with the decoder from fit_check.py and lays the 32 measures out
as a contact sheet: the time-based ones as lines over the session, the
additive ones as one bar per lap increment, one panel each, labelled with the
manifest's title and unit.

Two things the platform rule makes worth drawing rather than reading:

  * a lap value describes that lap alone -- the increment for that segment,
    never a running total -- so the bars are the increments, and a staircase
    of bars climbing to the session value is the bug, not the shape
  * a Session value, where one is present, is what the companion app shows
    instead of folding the records, so it is annotated on every panel that
    has one (and drawn across the plot when it fits the series)

Panels fit_check would call a problem are drawn in red, so the sheet and the
checker never disagree about what is wrong.

    python3 tools/fit_plot.py build/host/fruitbench_host.fit -o charts.png
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_check import (FitFile, MESG_FIELD_DESCRIPTION, MESG_LAP,  # noqa: E402
                       MESG_RECORD, MESG_SESSION, check, decode_value,
                       load_catalogue)

COLS = 4
PANEL_W = 300
PANEL_H = 150
PAD = 12
BG = (16, 18, 22)
INK = (232, 234, 238)
DIM = (120, 128, 140)
GRID = (44, 48, 56)
BAD = (240, 90, 90)
SES = (255, 160, 90)

# One colour per visualisation, so the sheet also shows how the manifest asked
# for each measure to be drawn.
VIS_COLOUR = {
    "line-chart": (250, 205, 70),
    "number": (120, 200, 255),
    "gauge": (140, 230, 150),
}


def series(path):
    """{measure id: [values]} per message kind, from one file.

    The kinds are kept apart on purpose: which message a value arrived on is
    exactly what the rule constrains, so merging them would hide it.
    """
    fit = FitFile(path)
    descs = {}
    for values, _ in fit.of(MESG_FIELD_DESCRIPTION):
        descs[values.get(1)] = (values.get(3), values.get(2))

    out = {"rec": {}, "lap": {}, "ses": {}}
    for kind, global_num in (("rec", MESG_RECORD), ("lap", MESG_LAP),
                             ("ses", MESG_SESSION)):
        for _, devs in fit.of(global_num):
            for (_, fnum), raw in devs.items():
                name, base = descs.get(fnum, (None, None))
                if name is None:
                    continue
                val = decode_value(raw, base, 0)
                if val is not None:
                    out[kind].setdefault(name, []).append(val)
    return out, fit


def label_right(d, right, y, text, fill):
    """Right-aligned text, so a wide value cannot run off the panel."""
    d.text((right - 6 * len(text), y), text, fill=fill)


def draw_panel(img, x, y, m, rec, lap, ses, bad):
    d = ImageDraw.Draw(img)
    colour = BAD if bad else VIS_COLOUR.get(m["visualisation"], INK)
    plot = (x + 8, y + 34, x + PANEL_W - 10, y + PANEL_H - 20)
    w = plot[2] - plot[0]
    h = plot[3] - plot[1]

    d.rectangle([x, y, x + PANEL_W - 2, y + PANEL_H - 2],
                outline=BAD if bad else GRID)
    d.text((x + 8, y + 6), "%s" % m["title"][:28], fill=BAD if bad else INK)
    if ses is not None:
        label_right(d, x + PANEL_W - 10, y + 6, "ses %.4g" % ses, SES)
    d.text((x + 8, y + 19),
           "%s  |  %s  |  %s%s" % (
               m["unitMetric"],
               m["visualisation"],
               m["dest"],
               "" if m["previewAggregation"] is None
               else " / " + m["previewAggregation"]),
           fill=DIM)

    # The time-based measures are a series over the records; everything else
    # is a per-lap increment, or -- for the ones the catalogue puts on the
    # session alone -- the single value for the whole activity.
    vals = rec if m["isTimeBased"] else lap
    if not vals and ses is not None:
        vals = [ses]
    if not vals:
        d.text((x + 8, y + PANEL_H // 2), "no values", fill=BAD)
        return

    lo, hi = min(vals), max(vals)
    if hi - lo < 1e-9:
        lo, hi = lo - 1.0, hi + 1.0
    d.rectangle(plot, outline=GRID)
    d.text((plot[0] + 2, plot[1] - 1), "%.4g" % hi, fill=DIM)
    d.text((plot[0] + 2, plot[3] - 11), "%.4g" % lo, fill=DIM)

    def sx(i):
        return plot[0] + (w * i / max(1, len(vals) - 1))

    def sy(v):
        return plot[3] - (v - lo) / (hi - lo) * h

    if m["isTimeBased"]:
        # Down-sample to the pixel grid: an hour of 1 Hz data is 3600 points
        # into 280 pixels, and drawing all of them just thickens the line.
        step = max(1, len(vals) // w)
        pts = [(sx(i), sy(vals[i])) for i in range(0, len(vals), step)]
        if len(pts) > 1:
            d.line(pts, fill=colour, width=1)
    else:
        # One slot per lap, bars centred in their slot: a session-only
        # measure is a single value, and a bar hung off sx(0) would then be
        # centred on the panel's left edge and spill into its neighbour.
        slot = w / float(len(vals))
        bw = max(2.0, min(slot * 0.62, PANEL_W / 6.0))
        for i, v in enumerate(vals):
            cx = plot[0] + slot * (i + 0.5)
            d.rectangle([cx - bw / 2, sy(v), cx + bw / 2, plot[3]], fill=colour)

    # A summary that lands inside the series is worth seeing against it: an
    # average sits through the middle of the line, a min or a max on its edge.
    # The sum of a set of lap increments does not fit its own bars, so there
    # the annotation above is the whole story.
    if ses is not None and lo <= ses <= hi:
        yy = sy(ses)
        for xx in range(int(plot[0]), int(plot[2]), 6):
            d.line([xx, yy, xx + 3, yy], fill=SES)

    d.text((plot[0] + 2, y + PANEL_H - 16), "n=%d" % len(vals), fill=DIM)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fit")
    ap.add_argument("-o", "--out", default="charts.png")
    ap.add_argument("--manifest", help="passed to fit_check")
    args = ap.parse_args()

    cat = load_catalogue()
    data, fit = series(args.fit)
    # The checker owns the verdict; the sheet only paints it, so a panel can
    # never look fine while fit_check calls it a problem.
    verdict = check(args.fit, quiet=True, manifest=args.manifest)

    rows = (len(cat["measures"]) + COLS - 1) // COLS
    img = Image.new("RGB", (COLS * PANEL_W + PAD * 2,
                            rows * PANEL_H + PAD * 2 + 26), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD),
           "FruitBench -- %s: %d records, %d laps, %d bytes, %d problems"
           % (os.path.basename(args.fit), len(fit.of(MESG_RECORD)),
              len(fit.of(MESG_LAP)), len(fit.blob),
              len(verdict["problems"])),
           fill=BAD if verdict["problems"] else INK)

    for i, m in enumerate(cat["measures"]):
        info = verdict["measures"].get(m["id"], {})
        draw_panel(img, PAD + (i % COLS) * PANEL_W,
                   PAD + 26 + (i // COLS) * PANEL_H, m,
                   data["rec"].get(m["id"], []),
                   data["lap"].get(m["id"], []),
                   info.get("session"),
                   bool(info.get("problems")))

    img.save(args.out)
    print("%s  (%d measures, %d with problems)"
          % (args.out, len(cat["measures"]),
             len([1 for v in verdict["measures"].values() if v["problems"]])))


if __name__ == "__main__":
    main()
