#!/usr/bin/env python3
"""gen_icons.py -- draws every PNG the package needs, from code.

The manifest points at 34 images: the store icon, the two app icons the .uapp
embeds (60x60 and 30x30) and one icon per custom measure. Drawing them
procedurally keeps them in step with the catalogue -- add a measure to
tools/gen_measures.py and its icon appears here rather than being a missing
file discovered by the store uploader.

Everything is drawn at 4x and downscaled, which is the cheapest anti-aliasing
available and enough for flat shapes at 60 pixels.

Run:  python3 tools/gen_icons.py
"""

import math
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gen_measures import C, ICONS  # noqa: E402  (catalogue is the source of truth)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# The app icons must sit exactly here: una-app.cmake passes
# ${RESOURCES_PATH}/icon_60x60.png and icon_30x30.png to the packer.
OUT_ICONS = os.path.join(ROOT, "Resources")
OUT_MEASURES = os.path.join(ROOT, "Resources", "measures")

SS = 4                      # supersampling factor
LEAF = (95, 165, 85)
STEM = (110, 80, 50)
INK = (26, 24, 30)


def shade(rgb, f):
    return tuple(max(0, min(255, int(c * f))) for c in rgb)


# --------------------------------------------------------------------------- #
# shape primitives -- all take a draw context on a size x size canvas
# --------------------------------------------------------------------------- #

def _ell(d, cx, cy, rx, ry, fill, outline=None, w=2):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill,
              outline=outline, width=w)


def sh_round(d, s, col):
    _ell(d, s * .5, s * .55, s * .32, s * .32, col, shade(col, .7), s // 22)
    d.line([s * .5, s * .23, s * .5, s * .1], fill=STEM, width=int(s * .05))
    d.polygon([(s * .5, s * .16), (s * .68, s * .08), (s * .62, s * .2)], fill=LEAF)


def sh_oval(d, s, col):
    _ell(d, s * .5, s * .55, s * .26, s * .34, col, shade(col, .7), s // 22)
    d.line([s * .5, s * .21, s * .5, s * .1], fill=STEM, width=int(s * .05))


def sh_apple(d, s, col):
    _ell(d, s * .38, s * .58, s * .24, s * .28, col)
    _ell(d, s * .62, s * .58, s * .24, s * .28, col)
    _ell(d, s * .5, s * .5, s * .28, s * .26, col)
    d.line([s * .5, s * .3, s * .52, s * .12], fill=STEM, width=int(s * .05))
    d.polygon([(s * .53, s * .18), (s * .74, s * .1), (s * .66, s * .26)], fill=LEAF)


def sh_pear(d, s, col):
    _ell(d, s * .5, s * .66, s * .26, s * .24, col)
    _ell(d, s * .5, s * .42, s * .18, s * .2, col)
    d.line([s * .5, s * .26, s * .52, s * .1], fill=STEM, width=int(s * .05))
    d.polygon([(s * .53, s * .16), (s * .72, s * .1), (s * .64, s * .24)], fill=LEAF)


def sh_crescent(d, s, col):
    d.pieslice([s * .1, s * .1, s * .95, s * .95], 40, 170, fill=col)
    d.pieslice([s * .02, s * .0, s * .82, s * .8], 40, 175, fill=(0, 0, 0, 0))
    _ell(d, s * .18, s * .34, s * .05, s * .05, STEM)


def sh_cherries(d, s, col):
    d.line([s * .5, s * .16, s * .32, s * .5], fill=STEM, width=int(s * .045))
    d.line([s * .5, s * .16, s * .7, s * .52], fill=STEM, width=int(s * .045))
    _ell(d, s * .3, s * .66, s * .18, s * .18, col, shade(col, .7), s // 24)
    _ell(d, s * .7, s * .68, s * .17, s * .17, shade(col, .85))
    d.polygon([(s * .5, s * .16), (s * .78, s * .08), (s * .62, s * .24)], fill=LEAF)


def sh_cluster(d, s, col):
    for cx, cy in [(.5, .3), (.36, .45), (.64, .45), (.5, .52),
                   (.28, .62), (.72, .62), (.42, .7), (.58, .7), (.5, .84)]:
        _ell(d, s * cx, s * cy, s * .11, s * .11, col, shade(col, .65), s // 30)
    d.polygon([(s * .5, s * .2), (s * .76, s * .06), (s * .58, s * .24)], fill=LEAF)


def sh_melon(d, s, col):
    _ell(d, s * .5, s * .55, s * .34, s * .3, col, shade(col, .6), s // 20)
    for i in range(-2, 3):
        d.arc([s * (.5 + i * .07) - s * .1, s * .25, s * (.5 + i * .07) + s * .1,
               s * .85], 250, 290, fill=shade(col, .55), width=int(s * .035))


def sh_kiwi(d, s, col):
    _ell(d, s * .5, s * .55, s * .32, s * .3, shade(col, .7))
    _ell(d, s * .5, s * .55, s * .25, s * .23, (222, 236, 190))
    _ell(d, s * .5, s * .55, s * .06, s * .06, (245, 245, 225))
    for k in range(12):
        a = k * math.pi / 6
        _ell(d, s * .5 + math.cos(a) * s * .15, s * .55 + math.sin(a) * s * .14,
             s * .016, s * .016, INK)


def sh_coconut(d, s, col):
    _ell(d, s * .5, s * .55, s * .32, s * .32, col, shade(col, .6), s // 20)
    for cx, cy in [(.38, .45), (.62, .45), (.5, .64)]:
        _ell(d, s * cx, s * cy, s * .05, s * .05, shade(col, .5))


def sh_avocado(d, s, col):
    _ell(d, s * .5, s * .62, s * .27, s * .3, col)
    _ell(d, s * .5, s * .34, s * .18, s * .18, col)
    _ell(d, s * .5, s * .62, s * .17, s * .19, (226, 232, 180))
    _ell(d, s * .5, s * .62, s * .1, s * .11, (150, 105, 60))


def sh_drop(d, s, col):
    d.polygon([(s * .5, s * .12), (s * .78, s * .6), (s * .5, s * .88),
               (s * .22, s * .6)], fill=col)
    _ell(d, s * .5, s * .62, s * .28, s * .26, col)


def sh_seeds(d, s, col):
    _ell(d, s * .5, s * .55, s * .33, s * .31, shade(col, .5))
    for cx, cy in [(.4, .45), (.6, .45), (.5, .55), (.35, .62), (.65, .62),
                   (.45, .72), (.58, .72)]:
        _ell(d, s * cx, s * cy, s * .075, s * .075, col)
    d.polygon([(s * .44, s * .26), (s * .5, s * .1), (s * .56, s * .26)],
              fill=shade(col, .5))


def sh_brick(d, s, col):
    d.rounded_rectangle([s * .14, s * .34, s * .86, s * .74], s * .05, fill=col,
                        outline=shade(col, .65), width=int(s * .04))
    d.line([s * .5, s * .34, s * .5, s * .54], fill=shade(col, .65), width=int(s * .04))
    d.line([s * .14, s * .54, s * .86, s * .54], fill=shade(col, .65), width=int(s * .04))
    d.line([s * .32, s * .54, s * .32, s * .74], fill=shade(col, .65), width=int(s * .04))
    d.line([s * .68, s * .54, s * .68, s * .74], fill=shade(col, .65), width=int(s * .04))


def sh_anvil(d, s, col):
    d.polygon([(s * .12, s * .34), (s * .88, s * .34), (s * .76, s * .5),
               (s * .62, s * .5), (s * .62, s * .62), (s * .38, s * .62),
               (s * .38, s * .5), (s * .24, s * .5)], fill=col)
    d.rounded_rectangle([s * .26, s * .62, s * .74, s * .78], s * .03,
                        fill=shade(col, .8))
    d.polygon([(s * .88, s * .34), (s * .98, s * .4), (s * .86, s * .46)], fill=col)


def sh_feather(d, s, col):
    """A blade with a shaft: at 60 pixels a feather has to read as a leaf."""
    d.polygon([(s * .72, s * .16), (s * .84, s * .44), (s * .5, s * .74),
               (s * .3, s * .62), (s * .46, s * .3)], fill=col)
    d.line([s * .78, s * .14, s * .26, s * .86], fill=shade(col, .55),
           width=int(s * .045))
    for k in range(4):
        t = .2 + k * .16
        d.line([s * (.74 - t * .55), s * (.2 + t * .72),
                s * (.74 - t * .2), s * (.2 + t * .45)],
               fill=shade(col, .75), width=int(s * .02))


def sh_cup(d, s, col):
    d.polygon([(s * .22, s * .38), (s * .72, s * .38), (s * .62, s * .76),
               (s * .32, s * .76)], fill=col, outline=shade(col, .6),
              width=int(s * .035))
    d.arc([s * .64, s * .42, s * .9, s * .66], 300, 60, fill=shade(col, .6),
          width=int(s * .05))
    d.rounded_rectangle([s * .24, s * .78, s * .7, s * .84], s * .02,
                        fill=shade(col, .7))
    d.ellipse([s * .28, s * .34, s * .66, s * .44], fill=(190, 130, 90))


def sh_duck(d, s, col):
    _ell(d, s * .46, s * .64, s * .28, s * .2, col)
    _ell(d, s * .68, s * .38, s * .15, s * .15, col)
    d.polygon([(s * .8, s * .36), (s * .96, s * .42), (s * .8, s * .46)],
              fill=(240, 130, 50))
    _ell(d, s * .72, s * .34, s * .022, s * .022, INK)
    d.arc([s * .3, s * .5, s * .62, s * .78], 200, 340, fill=shade(col, .75),
          width=int(s * .04))


def sh_clip(d, s, col):
    """Two nested rounded loops: the clip reads at 60 pixels, the real
    open-ended wire silhouette does not."""
    w = max(2, int(s * .05))

    d.rounded_rectangle([s * .3, s * .08, s * .7, s * .92], s * .2,
                        outline=col, width=w)
    d.rounded_rectangle([s * .4, s * .22, s * .6, s * .74], s * .1,
                        outline=shade(col, 1.2), width=w)


def sh_sock(d, s, col):
    d.rounded_rectangle([s * .34, s * .16, s * .62, s * .62], s * .06, fill=col)
    d.polygon([(s * .34, s * .5), (s * .62, s * .5), (s * .62, s * .68),
               (s * .2, s * .78), (s * .2, s * .58)], fill=col)
    _ell(d, s * .24, s * .68, s * .1, s * .1, col)
    d.rounded_rectangle([s * .32, s * .14, s * .64, s * .24], s * .03,
                        fill=shade(col, 1.25))


def sh_wrench(d, s, col):
    d.line([s * .3, s * .74, s * .72, s * .3], fill=col, width=int(s * .13))
    for cx, cy in [(.26, .78), (.76, .26)]:
        _ell(d, s * cx, s * cy, s * .14, s * .14, col)
        _ell(d, s * cx, s * cy, s * .06, s * .06, (0, 0, 0, 0))


def sh_pebble(d, s, col):
    d.polygon([(s * .2, s * .58), (s * .34, s * .36), (s * .62, s * .32),
               (s * .82, s * .5), (s * .74, s * .72), (s * .38, s * .76)],
              fill=col)
    d.polygon([(s * .34, s * .5), (s * .5, s * .42), (s * .56, s * .54),
               (s * .4, s * .6)], fill=shade(col, 1.18))


def sh_acorn(d, s, col):
    _ell(d, s * .5, s * .64, s * .22, s * .24, col)
    d.rounded_rectangle([s * .26, s * .3, s * .74, s * .48], s * .08,
                        fill=shade(col, .65))
    d.line([s * .5, s * .3, s * .5, s * .16], fill=shade(col, .5),
           width=int(s * .05))


def sh_balloon(d, s, col):
    _ell(d, s * .5, s * .42, s * .26, s * .3, col)
    d.polygon([(s * .44, s * .7), (s * .56, s * .7), (s * .5, s * .78)], fill=col)
    d.line([s * .5, s * .78, s * .58, s * .94], fill=(120, 120, 130),
           width=int(s * .03))
    _ell(d, s * .4, s * .32, s * .06, s * .08, shade(col, 1.4))


def sh_bulb(d, s, col):
    _ell(d, s * .5, s * .42, s * .26, s * .28, col)
    d.rounded_rectangle([s * .38, s * .64, s * .62, s * .84], s * .04,
                        fill=(160, 160, 170))
    for y in (.7, .76, .82):
        d.line([s * .38, s * y, s * .62, s * y], fill=(110, 110, 120),
               width=int(s * .025))
    d.line([s * .43, s * .5, s * .5, s * .38], fill=(220, 150, 60), width=int(s * .03))
    d.line([s * .5, s * .38, s * .57, s * .5], fill=(220, 150, 60), width=int(s * .03))


def sh_pinecone(d, s, col):
    for row, (n, y, r) in enumerate([(3, .3, .09), (4, .45, .1), (3, .6, .095),
                                     (2, .74, .085)]):
        for k in range(n):
            x = .5 + (k - (n - 1) / 2.0) * .16
            d.polygon([(s * x, s * (y - r)), (s * (x + r), s * y),
                       (s * x, s * (y + r)), (s * (x - r), s * y)],
                      fill=shade(col, 1.0 - row * .08))
    d.line([s * .5, s * .3, s * .5, s * .16], fill=LEAF, width=int(s * .045))


def sh_umbrella(d, s, col):
    d.pieslice([s * .1, s * .18, s * .9, s * .86], 180, 360, fill=col)
    for k in range(4):
        x = .1 + .2 * (k + 1)
        d.arc([s * (x - .1), s * .44, s * (x + .1), s * .66], 0, 180,
              fill=shade(col, .7), width=int(s * .03))
    d.line([s * .5, s * .52, s * .5, s * .86], fill=(120, 100, 80), width=int(s * .04))
    d.arc([s * .5, s * .78, s * .66, s * .92], 90, 180, fill=(120, 100, 80),
          width=int(s * .04))


SHAPES = {
    "round": sh_round, "oval": sh_oval, "apple": sh_apple, "pear": sh_pear,
    "crescent": sh_crescent, "cherries": sh_cherries, "cluster": sh_cluster,
    "melon": sh_melon, "kiwi": sh_kiwi, "coconut": sh_coconut,
    "avocado": sh_avocado, "drop": sh_drop, "seeds": sh_seeds,
    "brick": sh_brick, "anvil": sh_anvil, "feather": sh_feather,
    "cup": sh_cup, "duck": sh_duck, "clip": sh_clip, "sock": sh_sock,
    "wrench": sh_wrench, "pebble": sh_pebble, "acorn": sh_acorn,
    "balloon": sh_balloon, "bulb": sh_bulb, "pinecone": sh_pinecone,
    "umbrella": sh_umbrella,
}


# --------------------------------------------------------------------------- #
# icon composition
# --------------------------------------------------------------------------- #

def measure_icon(shape, col, size=60, disc=True):
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if disc:
        d.ellipse([0, 0, s - 1, s - 1], fill=(24, 26, 32, 255))
        d.ellipse([0, 0, s - 1, s - 1], outline=shade(col, .9) + (255,),
                  width=max(1, s // 40))
    SHAPES[shape](d, s, col + (255,))
    return img.resize((size, size), Image.LANCZOS)


def app_icon(size=60):
    """A chart drawn out of fruit: what the app is, in one glyph."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.ellipse([0, 0, s - 1, s - 1], fill=(18, 20, 26, 255))
    d.ellipse([0, 0, s - 1, s - 1], outline=(248, 206, 70, 255),
              width=max(2, s // 30))

    # axes
    d.line([s * .16, s * .78, s * .86, s * .78], fill=(70, 74, 86), width=int(s * .022))
    d.line([s * .16, s * .2, s * .16, s * .78], fill=(70, 74, 86), width=int(s * .022))

    # the series
    pts = [(.16, .7), (.3, .52), (.44, .6), (.58, .36), (.72, .44), (.86, .24)]
    d.line([(s * x, s * y) for x, y in pts], fill=(248, 206, 70, 255),
           width=int(s * .05), joint="curve")

    # fruit as the data points
    cols = [(214, 60, 60), (140, 90, 200), (90, 180, 90), (196, 40, 74),
            (250, 175, 60), (245, 225, 70)]
    for (x, y), c in zip(pts, cols):
        _ell(d, s * x, s * y, s * .055, s * .055, c + (255,), (18, 20, 26, 255),
             max(1, int(s * .012)))

    return img.resize((size, size), Image.LANCZOS)


def store_icon(size=512):
    img = app_icon(size)
    flat = Image.new("RGB", (size, size), (18, 20, 26))
    flat.paste(img, (0, 0), img)
    return flat


def main():
    os.makedirs(OUT_MEASURES, exist_ok=True)
    os.makedirs(OUT_ICONS, exist_ok=True)

    for row in C:
        mid = row[0]
        shape, col = ICONS[mid]
        measure_icon(shape, col, 60).save(
            os.path.join(OUT_MEASURES, mid + ".png"))
    print("wrote %d measure icons -> Resources/measures/" % len(C))

    app_icon(60).save(os.path.join(OUT_ICONS, "icon_60x60.png"))
    app_icon(30).save(os.path.join(OUT_ICONS, "icon_30x30.png"))
    store_icon(512).save(os.path.join(OUT_ICONS, "icon_store.png"))
    print("wrote icon_60x60.png, icon_30x30.png, icon_store.png")


if __name__ == "__main__":
    main()
