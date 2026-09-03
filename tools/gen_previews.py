#!/usr/bin/env python3
"""Render FruitBench's store previews from the host harness.

The harness links the *same* fb_ui.c / fb_video.c / fb_text.c / fb_gen.c the
watch runs, so a preview is the real screen, pixel for pixel -- and the values
on it come from the real generator, not from a mockup. What the harness fakes
is only the two things a laptop does not have: the kernel's frame tick with its
button queue, and the recorder process (the FIT writing has its own host test,
tools/host_test.sh).

Each shot is a scripted key sequence (`frame:code` pairs at 10 Hz, kernel codes
-- press q/e/w/r, release a/d/s/f) that parks the screen in the wanted state;
the harness dumps the last frame and this script masks it to the round panel
and scales it up.

    python3 tools/gen_previews.py [--out DIR] [--scale N]
"""

import argparse
import os
import struct
import subprocess
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.path.join(ROOT, "host", "fb_host")
PANEL = 240
RADIUS = 120.0          # the panel is round; the corners are not visible

# A fixed seed for every shot, so the previews are reproducible even though the
# app itself rolls a new one on every start.
SEED = "0x51ED27A3"

# name, frames to run, key script, caption (logged, not drawn)
SHOTS = [
    ("01-home", 3, "",
     "the rate and the span, and a seed that changes on every start"),
    ("02-recording", 90, "3:e,4:d",
     "live recording: four measures at a time, each with its own sparkline"),
    # Turbo, so several laps have actually closed by the time the shot is
    # taken: an additive measure reads zero until its first lap boundary, and
    # a preview should show it doing its job rather than waiting to start.
    ("03-lap-measures", 24, "3:w,4:s,6:w,7:s,9:e,10:d,20:w,21:s",
     "the marked measures do not go on every record: LAP reaches the file "
     "once per lap as that lap's increment, SES once for the whole activity"),
    ("04-turbo", 26, "3:w,4:s,6:w,7:s,9:e,10:d",
     "turbo: 60 activity seconds per real second, so an hour of 1 Hz data "
     "takes a minute"),
    ("05-saved", 44, "3:w,4:s,6:w,7:s,9:e,10:d",
     "the summary after a 30 minute span finished on its own"),
]


def run_shot(frames, script, ppm):
    cmd = [HOST, "--seed", SEED, "--frames", str(frames), "--dump", ppm]
    if script:
        cmd += ["--script", script]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def read_ppm(path):
    with open(path, "rb") as f:
        data = f.read()
    magic, dims, maxval, px = data.split(b"\n", 3)
    if magic != b"P6" or maxval != b"255":
        raise SystemExit("%s: not the 8-bit P6 the harness writes" % path)
    w, h = (int(v) for v in dims.split())
    if (w, h) != (PANEL, PANEL) or len(px) < w * h * 3:
        raise SystemExit("%s: expected a %dx%d frame" % (path, PANEL, PANEL))
    return px


def write_png(path, px, scale):
    """Mask the frame to the round panel, scale it up, write a PNG.

    Nearest-neighbour on purpose: these are 3x5-glyph pixels and any smoothing
    would make the render look softer than the panel does.
    """
    c = (PANEL - 1) / 2.0
    rows = []
    for y in range(PANEL):
        row = bytearray()
        for x in range(PANEL):
            if (x - c) ** 2 + (y - c) ** 2 > RADIUS ** 2:
                row += b"\x00\x00\x00" * scale        # outside the glass
            else:
                i = (y * PANEL + x) * 3
                row += px[i:i + 3] * scale
        rows.append(bytes(row))

    raw = b"".join((b"\x00" + r) * scale for r in rows)
    side = PANEL * scale

    def chunk(tag, body):
        payload = tag + body
        return (struct.pack(">I", len(body)) + payload
                + struct.pack(">I", zlib.crc32(payload)))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(ROOT, "release", "package",
                                                  "assets", "previews"))
    ap.add_argument("--scale", type=int, default=2,
                    help="integer upscale of the 240x240 panel (default 2)")
    args = ap.parse_args()

    if not os.path.exists(HOST):
        sys.exit("%s not built -- run: make -C host" % HOST)

    os.makedirs(args.out, exist_ok=True)
    tmp = os.path.join(args.out, ".shot.ppm")
    try:
        for name, frames, script, caption in SHOTS:
            run_shot(frames, script, tmp)
            out = os.path.join(args.out, name + ".png")
            write_png(out, read_ppm(tmp), args.scale)
            print("%s  --  %s" % (os.path.relpath(out, ROOT), caption))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    main()
