#!/usr/bin/env python3
"""fit_plot.py -- draw every measure in a FruitBench .fit as a small chart.

The point of the app is what a companion app will show, and the fastest way to
know whether a recording is worth charting is to chart it here first. This
reads the file with the decoder from fit_check.py and lays the 32 measures out
as a contact sheet: the time-based ones as lines over the session, the per-lap
ones as bars, one panel each, labelled with the manifest's title and unit.

    python3 tools/fit_plot.py build/host/fruitbench_host.fit -o charts.png
"""

import argparse
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fit_check import (FitFile, MESG_FIELD_DESCRIPTION, MESG_LAP,  # noqa: E402
                       MESG_RECORD, decode_value, load_catalogue)

COLS = 4
PANEL_W = 300
PANEL_H = 150
PAD = 12
BG = (16, 18, 22)
INK = (232, 234, 238)
DIM = (120, 128, 140)
GRID = (44, 48, 56)

# One colour per visualisation, so the sheet also shows how the manifest asked
# for each measure to be drawn.
VIS_COLOUR = {
    "line-chart": (250, 205, 70),
    "number": (120, 200, 255),
    "gauge": (140, 230, 150),
}


def series(path):
    """{measure id: [values]} plus the catalogue, from one file."""
    fit = FitFile(path)
    descs = {}
    for values, _ in fit.of(MESG_FIELD_DESCRIPTION):
        descs[values.get(1)] = (values.get(3), values.get(2))

    out = {}
    for global_num in (MESG_RECORD, MESG_LAP):
        for _, devs in fit.of(global_num):
            for (_, fnum), raw in devs.items():
                name, base = descs.get(fnum, (None, None))
                if name is None:
                    continue
                val = decode_value(raw, base, 0)
                if val is not None:
                    out.setdefault(name, []).append(val)
    return out, fit


def draw_panel(img, x, y, m, vals):
    d = ImageDraw.Draw(img)
    colour = VIS_COLOUR.get(m["visualisation"], INK)
    plot = (x + 8, y + 34, x + PANEL_W - 10, y + PANEL_H - 20)
    w = plot[2] - plot[0]
    h = plot[3] - plot[1]

    d.rectangle([x, y, x + PANEL_W - 2, y + PANEL_H - 2], outline=GRID)
    d.text((x + 8, y + 6), "%s" % m["title"][:34], fill=INK)
    d.text((x + 8, y + 19),
           "%s  |  %s  |  %s%s" % (
               m["unitMetric"],
               m["visualisation"],
               "record" if m["isTimeBased"] else "lap",
               "" if m["previewAggregation"] is None
               else " / " + m["previewAggregation"]),
           fill=DIM)

    if not vals:
        d.text((x + 8, y + PANEL_H // 2), "no values", fill=(240, 90, 90))
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
        bw = max(2, int(w / (len(vals) * 1.6)))
        for i, v in enumerate(vals):
            cx = sx(i)
            d.rectangle([cx - bw / 2, sy(v), cx + bw / 2, plot[3]], fill=colour)

    d.text((plot[2] - 60, y + PANEL_H - 16), "n=%d" % len(vals), fill=DIM)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fit")
    ap.add_argument("-o", "--out", default="charts.png")
    args = ap.parse_args()

    cat = load_catalogue()
    data, fit = series(args.fit)

    rows = (len(cat["measures"]) + COLS - 1) // COLS
    img = Image.new("RGB", (COLS * PANEL_W + PAD * 2,
                            rows * PANEL_H + PAD * 2 + 26), BG)
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD),
           "FruitBench -- %s: %d records, %d laps, %d bytes"
           % (os.path.basename(args.fit), len(fit.of(MESG_RECORD)),
              len(fit.of(MESG_LAP)), len(fit.blob)),
           fill=INK)

    for i, m in enumerate(cat["measures"]):
        draw_panel(img, PAD + (i % COLS) * PANEL_W,
                   PAD + 26 + (i // COLS) * PANEL_H, m, data.get(m["id"], []))

    img.save(args.out)
    print("%s  (%d measures)" % (args.out, len(cat["measures"])))


if __name__ == "__main__":
    main()
