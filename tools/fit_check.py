#!/usr/bin/env python3
"""fit_check.py -- read a FruitBench .fit back and hold it against the catalogue.

This is the benchmark's own verdict on its output. It decodes the file with no
third-party dependency (the FIT container is small enough to parse honestly)
and then checks the things that would otherwise only show up as a missing chart
on a phone:

  * both CRCs, and that the header's data size matches the bytes present
  * one field_description per declared measure, with the manifest's `id` as
    field_name, `unitMetric` as units, and the catalogue's FIT base type
  * every time-based measure present as a developer field on `record`, and
    every per-lap measure on `lap` -- and nothing extra
  * every value inside the envelope its catalogue row declares
  * timestamps monotonic, the session and activity messages present, the lap
    count consistent

It also prints min/avg/max per measure, which is the quickest way to see that
a session is varied rather than 32 flat lines.

    python3 tools/fit_check.py Output/test.fit [--quiet] [--json]
"""

import argparse
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# --------------------------------------------------------------------------- #
# FIT primitives
# --------------------------------------------------------------------------- #

CRC_TABLE = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
             0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]


def fit_crc(data, crc=0):
    for byte in data:
        for nibble in (byte & 0x0F, (byte >> 4) & 0x0F):
            tmp = CRC_TABLE[crc & 0x0F]
            crc = (crc >> 4) & 0x0FFF
            crc = crc ^ tmp ^ CRC_TABLE[nibble]
    return crc


# base type id -> (name, size, struct code, invalid value)
BASE_TYPES = {
    0x00: ("enum",    1, "B", 0xFF),
    0x01: ("sint8",   1, "b", 0x7F),
    0x02: ("uint8",   1, "B", 0xFF),
    0x83: ("sint16",  2, "h", 0x7FFF),
    0x84: ("uint16",  2, "H", 0xFFFF),
    0x85: ("sint32",  4, "i", 0x7FFFFFFF),
    0x86: ("uint32",  4, "I", 0xFFFFFFFF),
    0x07: ("string",  1, "s", 0x00),
    0x88: ("float32", 4, "f", None),
    0x89: ("float64", 8, "d", None),
    0x0A: ("uint8z",  1, "B", 0x00),
    0x8B: ("uint16z", 2, "H", 0x00),
    0x8C: ("uint32z", 4, "I", 0x00),
    0x0D: ("byte",    1, "B", 0xFF),
    0x8E: ("sint64",  8, "q", None),
    0x8F: ("uint64",  8, "Q", None),
    0x90: ("uint64z", 8, "Q", 0x00),
}

MESG_FILE_ID = 0
MESG_SESSION = 18
MESG_LAP = 19
MESG_RECORD = 20
MESG_EVENT = 21
MESG_ACTIVITY = 34
MESG_FIELD_DESCRIPTION = 206
MESG_DEVELOPER_DATA_ID = 207


def decode_value(raw, base_id, endian):
    name, size, code, invalid = BASE_TYPES[base_id]
    if name == "string":
        return raw.split(b"\x00")[0].decode("utf-8", "replace")
    if name == "byte":
        return raw
    count = len(raw) // size
    vals = struct.unpack(("<" if endian == 0 else ">") + code * count, raw)
    vals = [None if (invalid is not None and v == invalid) else v for v in vals]
    return vals[0] if count == 1 else vals


class FitFile:
    """Everything fit_check needs out of a FIT file, decoded once."""

    def __init__(self, path):
        with open(path, "rb") as fh:
            self.blob = fh.read()
        self.path = path
        self.errors = []
        self.messages = []          # (global_num, {field_num: value}, {dev_key: value})
        self._parse_header()
        self._parse_records()

    # -- header ---------------------------------------------------------- #

    def _parse_header(self):
        b = self.blob
        if len(b) < 14:
            raise SystemExit("%s: shorter than a FIT header" % self.path)
        (self.header_size, self.protocol, self.profile, self.data_size) = \
            struct.unpack("<BBHI", b[:8])
        self.data_type = b[8:12]
        (self.header_crc,) = struct.unpack("<H", b[12:14])

        if self.data_type != b".FIT":
            self.errors.append("header data type is %r, not '.FIT'"
                               % self.data_type)
        if self.header_size != 14:
            self.errors.append("header size %d, expected 14" % self.header_size)

        actual = len(b) - self.header_size - 2
        if actual != self.data_size:
            self.errors.append("header data size %d but %d bytes of records"
                               % (self.data_size, actual))

        # A zero header CRC is explicitly allowed by the spec (and is what the
        # SDK writes before finish() patches it), so only a non-zero one is
        # held to account.
        if self.header_crc != 0:
            want = fit_crc(b[:12])
            if want != self.header_crc:
                self.errors.append("header CRC %04X, computed %04X"
                                   % (self.header_crc, want))

        (self.file_crc,) = struct.unpack("<H", b[-2:])
        want = fit_crc(b[:-2])
        if want != self.file_crc:
            self.errors.append("file CRC %04X, computed %04X"
                               % (self.file_crc, want))

    # -- records --------------------------------------------------------- #

    def _parse_records(self):
        b = self.blob
        pos = self.header_size
        end = self.header_size + self.data_size
        defs = {}

        while pos < end:
            header = b[pos]
            pos += 1

            if header & 0x80:                        # compressed timestamp
                self.errors.append("compressed timestamp header at %d" % pos)
                return

            local = header & 0x0F

            if header & 0x40:                        # definition message
                endian = b[pos + 1]
                global_num = struct.unpack("<H" if endian == 0 else ">H",
                                           b[pos + 2:pos + 4])[0]
                nfields = b[pos + 4]
                pos += 5
                fields = []
                for _ in range(nfields):
                    fields.append((b[pos], b[pos + 1], b[pos + 2]))
                    pos += 3
                devs = []
                if header & 0x20:
                    ndev = b[pos]
                    pos += 1
                    for _ in range(ndev):
                        devs.append((b[pos], b[pos + 1], b[pos + 2]))
                        pos += 3
                defs[local] = (global_num, endian, fields, devs)
                continue

            if local not in defs:
                self.errors.append("data message for undefined local type %d"
                                   % local)
                return

            global_num, endian, fields, devs = defs[local]
            values = {}
            for fnum, size, base_id in fields:
                raw = b[pos:pos + size]
                pos += size
                if base_id in BASE_TYPES:
                    values[fnum] = decode_value(raw, base_id, endian)
                else:
                    values[fnum] = raw
            dev_values = {}
            for fnum, size, dev_idx in devs:
                raw = b[pos:pos + size]
                pos += size
                dev_values[(dev_idx, fnum)] = raw   # typed later, via the descriptions
            self.messages.append((global_num, values, dev_values))

    def of(self, global_num):
        return [(v, d) for g, v, d in self.messages if g == global_num]


# --------------------------------------------------------------------------- #
# the checks
# --------------------------------------------------------------------------- #

def load_catalogue():
    with open(os.path.join(ROOT, "docs", "measures.json"), encoding="utf-8") as fh:
        return json.load(fh)


FIT_TYPE_IDS = {
    "U8": 0x02, "U16": 0x84, "U32": 0x86,
    "S16": 0x83, "S32": 0x85, "F32": 0x88,
}


def check(path, quiet=False):
    cat = load_catalogue()
    by_id = {m["id"]: m for m in cat["measures"]}
    fit = FitFile(path)
    problems = list(fit.errors)
    notes = []

    # -- developer data id ------------------------------------------------ #
    dev_ids = fit.of(MESG_DEVELOPER_DATA_ID)
    if not dev_ids:
        problems.append("no developer_data_id message")
    else:
        app_bytes = dev_ids[0][0].get(1, b"")
        app_text = bytes(app_bytes).rstrip(b"\x00").decode("ascii", "replace")
        if app_text != cat["appId"]:
            problems.append("developer_data_id application_id is %r, "
                            "catalogue says %r" % (app_text, cat["appId"]))
        notes.append("application_id: %s" % app_text)

    # -- field descriptions ---------------------------------------------- #
    descs = {}
    for values, _ in fit.of(MESG_FIELD_DESCRIPTION):
        num = values.get(1)
        descs[num] = {
            "dev_index": values.get(0),
            "base_type": values.get(2),
            "name": values.get(3),
            "units": values.get(8),
        }

    if len(descs) != len(cat["measures"]):
        problems.append("%d field descriptions, catalogue declares %d"
                        % (len(descs), len(cat["measures"])))

    for m in cat["measures"]:
        d = descs.get(m["field_num"])
        if d is None:
            problems.append("no field_description for %s (field %d)"
                            % (m["id"], m["field_num"]))
            continue
        if d["name"] != m["id"]:
            problems.append("field %d is named %r, manifest id is %r"
                            % (m["field_num"], d["name"], m["id"]))
        if d["units"] != m["unitMetric"]:
            problems.append("field %s units %r, manifest unitMetric %r"
                            % (m["id"], d["units"], m["unitMetric"]))
        want = FIT_TYPE_IDS[m["fitType"]]
        if d["base_type"] != want:
            problems.append("field %s base type 0x%02X, catalogue says 0x%02X"
                            % (m["id"], d["base_type"] or 0, want))

    # -- where each measure actually landed ------------------------------- #
    def collect(global_num):
        out = {}
        for values, devs in fit.of(global_num):
            for (dev_idx, fnum), raw in devs.items():
                d = descs.get(fnum)
                if d is None:
                    problems.append("developer field %d has no description"
                                    % fnum)
                    continue
                val = decode_value(raw, d["base_type"], 0)
                out.setdefault(d["name"], []).append(val)
        return out, [v for v, _ in fit.of(global_num)]

    rec_vals, records = collect(MESG_RECORD)
    lap_vals, laps = collect(MESG_LAP)

    for m in cat["measures"]:
        where = rec_vals if m["isTimeBased"] else lap_vals
        other = lap_vals if m["isTimeBased"] else rec_vals
        kind = "record" if m["isTimeBased"] else "lap"

        if m["id"] not in where:
            problems.append("%s (isTimeBased=%s) carries no values on the %s "
                            "message" % (m["id"], m["isTimeBased"], kind))
        if m["id"] in other:
            problems.append("%s appears on the wrong message as well"
                            % m["id"])

    # -- envelopes -------------------------------------------------------- #
    stats = {}
    for name, vals in list(rec_vals.items()) + list(lap_vals.items()):
        m = by_id.get(name)
        clean = [v for v in vals if v is not None]
        if not clean:
            problems.append("%s has no valid values" % name)
            continue
        lo, hi = min(clean), max(clean)
        stats[name] = {
            "count": len(clean),
            "min": lo,
            "max": hi,
            "avg": sum(clean) / len(clean),
        }
        if m is None:
            problems.append("developer field %r is not in the catalogue" % name)
            continue
        # Integer fields are rounded on the way out, so allow a whole unit of
        # slack at each end rather than pretending the cast was exact.
        slack = 1.0 if m["fitType"] != "F32" else 1e-3
        if lo < m["lo"] - slack or hi > m["hi"] + slack:
            problems.append("%s ranged %g..%g, outside its declared %g..%g"
                            % (name, lo, hi, m["lo"], m["hi"]))

    # -- file identity ---------------------------------------------------- #
    file_ids = fit.of(MESG_FILE_ID)
    if not file_ids:
        problems.append("no file_id message")
    else:
        v = file_ids[0][0]
        if v.get(0) != 4:
            problems.append("file_id type is %s, expected 4 (activity)"
                            % v.get(0))
        if v.get(1) != 351:
            problems.append("file_id manufacturer is %s, expected 351 (Una)"
                            % v.get(1))
        if v.get(2) != 1:
            problems.append("file_id product is %s, expected 1 (UNA Watch)"
                            % v.get(2))
        # FruitBench puts the session seed here: a file that cannot name the
        # seed it came from is not reproducible, which is the point of it.
        if not v.get(3):
            problems.append("file_id serial_number is empty -- the session "
                            "seed did not reach the file")
        notes.append("device: manufacturer %s, product %s, %r"
                     % (v.get(1), v.get(2), v.get(8)))
        notes.append("seed (serial_number): %08X" % (v.get(3) or 0))

    # -- structure -------------------------------------------------------- #
    if not fit.of(MESG_SESSION):
        problems.append("no session message")
    if not fit.of(MESG_ACTIVITY):
        problems.append("no activity message")

    events = fit.of(MESG_EVENT)
    if len(events) < 2:
        problems.append("expected at least a start and a stop event, found %d"
                        % len(events))

    timestamps = [v.get(253) for v in records if v.get(253) is not None]
    if timestamps != sorted(timestamps):
        problems.append("record timestamps are not monotonic")
    if len(set(timestamps)) != len(timestamps):
        problems.append("duplicate record timestamps")

    session = fit.of(MESG_SESSION)
    if session:
        num_laps = session[0][0].get(26)
        if num_laps is not None and num_laps != len(laps):
            problems.append("session says %s laps, %d lap messages present"
                            % (num_laps, len(laps)))

    summary = {
        "file": path,
        "bytes": len(fit.blob),
        "records": len(records),
        "laps": len(laps),
        "descriptions": len(descs),
        "span_s": (timestamps[-1] - timestamps[0]) if len(timestamps) > 1 else 0,
        "bytes_per_record": (len(fit.blob) / len(records)) if records else 0,
        "problems": problems,
        "notes": notes,
        "stats": stats,
    }

    if not quiet:
        report(summary, cat)
    return summary


def report(s, cat):
    print("file            : %s" % s["file"])
    print("size            : %d bytes (%.1f KB)" % (s["bytes"], s["bytes"] / 1024))
    print("records         : %d over %d s (%.1f B/record)"
          % (s["records"], s["span_s"], s["bytes_per_record"]))
    print("laps            : %d" % s["laps"])
    print("descriptions    : %d" % s["descriptions"])
    for n in s["notes"]:
        print("%-16s: %s" % ("", n))
    print()
    print("%-24s %-6s %5s %12s %12s %12s  %s"
          % ("measure", "on", "n", "min", "avg", "max", "unit"))
    for m in cat["measures"]:
        st = s["stats"].get(m["id"])
        if not st:
            print("%-24s %-6s %5s" % (m["id"], "-", "MISSING"))
            continue
        print("%-24s %-6s %5d %12.4g %12.4g %12.4g  %s"
              % (m["id"], "rec" if m["isTimeBased"] else "lap", st["count"],
                 st["min"], st["avg"], st["max"], m["unitMetric"]))
    print()
    if s["problems"]:
        print("PROBLEMS (%d):" % len(s["problems"]))
        for p in s["problems"]:
            print("  - %s" % p)
    else:
        print("RESULT          : VALID -- every declared measure present, "
              "typed and inside its envelope")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fit", help="the .fit file to check")
    ap.add_argument("--quiet", action="store_true", help="only the exit code")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    args = ap.parse_args()

    s = check(args.fit, quiet=args.quiet or args.json)
    if args.json:
        print(json.dumps(s, indent=2, default=str))
    return 1 if s["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
