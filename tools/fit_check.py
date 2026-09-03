#!/usr/bin/env python3
"""fit_check.py -- read a FruitBench .fit back and hold it against the catalogue.

This is the benchmark's own verdict on its output. It decodes the file with no
third-party dependency (the FIT container is small enough to parse honestly)
and then checks the things that would otherwise only show up as a missing chart
on a phone:

  * both CRCs, and that the header's data size matches the bytes present
  * one field_description per declared measure, with the manifest's `id` as
    field_name, `unitMetric` as units, and the catalogue's FIT base type
  * every time-based measure present as a developer field on `record`, every
    measure that is not time-based summarised on `session` (the rule makes
    that value mandatory), every additive one on `lap` -- and nothing extra
  * the lap increments adding up to the session value, which is what catches
    a lap value written as a running total instead of an increment
  * an explicit summary on a time-based measure agreeing with the
    previewAggregation fold of that measure's own records
  * previewAggregation declared only on time-based measures (in the manifest)
  * every value inside the envelope its catalogue row declares -- per lap,
    for the additive measures, whose session value is the sum of the laps
  * timestamps monotonic, the session and activity messages present, the lap
    count consistent

It also prints min/avg/max per measure -- and, where the file carries one, the
session summary beside the fold of the records it claims to summarise -- which
is the quickest way to see that a session is varied rather than 32 flat lines.

    python3 tools/fit_check.py Output/test.fit [--quiet] [--json]
    python3 tools/fit_check.py Output/test.fit --manifest app-manifest.json
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
    if invalid is None:
        # A float field spells "invalid" as all bits set, which reads back as
        # a NaN -- and no measure can hold a NaN, so it means the same thing
        # as absent. Integer types with no invalid pattern are unaffected,
        # since v != v is only ever true of a NaN.
        vals = [None if v != v else v for v in vals]
    else:
        vals = [None if v == invalid else v for v in vals]
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
# the platform rule every check below enforces one clause of
# --------------------------------------------------------------------------- #
#
#   Each custom measure declared in customMeasures is written to the activity
#   FIT file as a developer field. Declare it once with a FieldDescription
#   message whose field_name is exactly the measure id from
#   app-manifest.json. Use developer_data_index as described in the SDK
#   (currently always 0) and set units to the measure's unitMetric.
#
#   Where the value is written depends on isTimeBased:
#   - isTimeBased: true -- write the value on every Record message. Values on
#     Session or Lap messages are optional; when present, the companion app
#     uses them as the summary instead of aggregating the records.
#   - isTimeBased: false -- write the value for the whole activity on the
#     Session message. This is required. Optionally, also write a value on
#     each Lap message. A lap value always describes that lap only (the
#     increment for that segment), never a running total.
#
#   previewAggregation applies to time-based measures only. It tells the
#   companion app how to fold the per-record values into a single number for
#   the activity preview (average, min or max).
#
#   If a non-time-based measure has no Session value, the companion app falls
#   back to the sum of its Lap values. Apps should not rely on this fallback.
#
# The catalogue says where each measure is meant to land (`dest`, and the
# `onRecord` / `onSession` / `onLap` flags it expands to), so the checks are
# the file against the catalogue against the rule -- not against a guess.

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


def fold_records(kind, vals):
    """The single number a companion app folds a record series down to.

    previewAggregation is the only thing that says how, and it applies to
    time-based measures only, so this is deliberately the whole vocabulary.
    """
    if not vals:
        return None
    if kind == "average":
        return sum(vals) / float(len(vals))
    if kind == "min":
        return min(vals)
    if kind == "max":
        return max(vals)
    return None


def slack_for(m, magnitude, units=1.0):
    """How far two spellings of the same number may sit apart.

    An integer developer field is rounded on the way out, so a whole unit --
    or one per lap, where several are summed -- can legitimately vanish; a
    float32 keeps about seven digits, so there the only honest bound is
    relative to the magnitude involved.
    """
    rel = 1e-4 * abs(magnitude)
    if m["fitType"] == "F32":
        return max(1e-6, rel)
    return units + rel


def check_measure(m, found, nlaps, problems, notes):
    """Hold one measure against the rule; return where its values landed.

    `found` is the three {measure id: [values]} maps, one per message kind.
    Problems are recorded twice on purpose: globally, because they decide the
    exit code, and per measure, so fit_plot can paint exactly those panels.
    """
    mid = m["id"]
    rec = [v for v in found["rec"].get(mid, []) if v is not None]
    lap = [v for v in found["lap"].get(mid, []) if v is not None]
    ses = [v for v in found["ses"].get(mid, []) if v is not None]
    ses_val = ses[0] if ses else None

    where = [k for k, hit in (("rec", bool(rec)), ("lap", bool(lap)),
                              ("ses", ses_val is not None)) if hit]
    info = {
        "on": "+".join(where) or "-",
        "session": ses_val,
        "lap_values": lap,
        "fold": None,
        "fold_kind": None,
        "count": 0,
        "min": None,
        "avg": None,
        "max": None,
        "problems": [],
    }

    def flag(msg):
        problems.append(msg)
        info["problems"].append(msg)

    # -- is the value where the rule puts it? ----------------------------- #

    # "isTimeBased: true -- write the value on every Record message."
    if m["isTimeBased"] and not rec:
        flag("%s is time-based but carries no values on the record message"
             % mid)
    # "isTimeBased: false -- write the value for the whole activity on the
    # Session message. This is required." A companion app would fall back to
    # the sum of the lap values, but the rule says not to rely on that, so a
    # missing session value is a problem even when the laps are all there.
    if not m["isTimeBased"] and ses_val is None:
        flag("%s is not time-based and has no session value -- the rule "
             "makes that value required (the lap-sum fallback is explicitly "
             "not to be relied on)" % mid)
    # Nothing extra either: a measure that is not time-based has no
    # per-record value to write, and this app puts lap values only on the
    # additive measures the catalogue marks onLap.
    if not m["isTimeBased"] and rec:
        flag("%s is not time-based but appears on %d record messages"
             % (mid, len(rec)))
    if m["isTimeBased"] and lap:
        flag("%s is time-based but appears on %d lap messages, which this "
             "app does not write" % (mid, len(lap)))
    elif lap and not m["onLap"]:
        # The rule allows a lap value on any measure, but the catalogue puts
        # this one on the session alone because the quantity does not add up
        # -- a per-lap share of a percentage would mean nothing.
        flag("%s is declared as %s, with no lap values, but appears on %d "
             "lap messages" % (mid, m["dest"], len(lap)))
    if m["onLap"] and not lap:
        flag("%s is declared with per-lap increments but no lap message "
             "carries it" % mid)
    if m["onSession"] and m["isTimeBased"] and ses_val is None:
        flag("%s is declared with an explicit summary but the session "
             "message carries no value for it" % mid)
    if ses_val is not None and not m["onSession"]:
        # The rule allows a summary on any time-based measure, so a file that
        # carries one the catalogue never promised is odd, not wrong.
        notes.append("%s carries a session value the catalogue does not "
                     "declare" % mid)

    # -- envelopes -------------------------------------------------------- #

    def envelope(kind, vals, lo, hi):
        sl = slack_for(m, hi)
        if [v for v in vals if v < lo - sl or v > hi + sl]:
            flag("%s on %s ranged %g..%g, outside its declared %g..%g"
                 % (mid, kind, min(vals), max(vals), lo, hi))

    envelope("record", rec, m["lo"], m["hi"])
    envelope("lap", lap, m["lo"], m["hi"])
    if ses_val is not None:
        if m["dest"] == "session+lap":
            # For an additive measure the catalogue's envelope is the range
            # of ONE LAP'S INCREMENT, so the session value -- their sum --
            # legitimately exceeds `hi` and is held to 0..hi*nlaps instead.
            envelope("session", [ses_val], 0.0, m["hi"] * max(1, nlaps))
        else:
            envelope("session", [ses_val], m["lo"], m["hi"])

    # -- the laps against the summary ------------------------------------- #

    if lap and ses_val is not None:
        total = sum(lap)
        info["fold"] = total
        info["fold_kind"] = "sum"
        # "A lap value always describes that lap only (the increment for that
        # segment), never a running total" -- so the increments have to add
        # up to the session value. This is the check that catches a lap value
        # written as a running total: a rising total sums to a large multiple
        # of the session value (about n/2 times it for an even climb) rather
        # than to the value itself.
        tol = slack_for(m, ses_val, units=float(len(lap)))
        if abs(total - ses_val) > tol:
            flag("%s lap increments sum to %g but its session value is %g "
                 "(off by %g, tolerance %g)"
                 % (mid, total, ses_val, total - ses_val, tol))
            # A heuristic, so it is only reported once the sum above has
            # already failed: a genuine series of increments that happens to
            # rise every lap is also non-decreasing, and flagging that on its
            # own would cry wolf on honest data.
            rising = all(lap[i] <= lap[i + 1] for i in range(len(lap) - 1))
            near = abs(lap[-1] - ses_val) <= (slack_for(m, ses_val)
                                              + 0.01 * abs(ses_val))
            if len(lap) > 1 and rising and near:
                flag("%s lap values look like a running total: they never "
                     "fall and the last one (%g) is the session value (%g), "
                     "so each lap is repeating the total instead of its own "
                     "increment" % (mid, lap[-1], ses_val))

    # -- the summary against the records ---------------------------------- #

    agg = m["previewAggregation"]
    if m["isTimeBased"] and rec:
        # previewAggregation is optional: a measure the manifest keeps out of
        # the preview declares none, and the rule asks for no aggregation to
        # go with an optional session value. The recorder folds such a
        # measure as the average (fb_gen_session_value), which is the
        # documented default, so the fold is always defined for a time-based
        # measure -- only its name is sometimes implicit.
        kind = agg or "average"
        folded = fold_records(kind, rec)
        info["fold"] = folded
        info["fold_kind"] = kind if agg else kind + "*"
        if ses_val is not None:
            # "when present, [Session values] are used as the summary instead
            # of aggregating the records", so a summary that disagrees with
            # the records is the wrong number on the phone -- and the records
            # are still the honest answer, which is what makes this checkable.
            tol = slack_for(m, max(abs(folded), abs(ses_val)))
            if kind == "average":
                # An average is accumulated across every record, so float
                # drift grows with the count; a min or a max is one of the
                # samples handed back unchanged.
                tol += 1e-6 * len(rec) * abs(ses_val)
            if abs(folded - ses_val) > tol:
                flag("%s session summary is %g but the %s of its %d record "
                     "values is %g (tolerance %g)"
                     % (mid, ses_val, kind, len(rec), folded, tol))

    series = rec or lap or ([ses_val] if ses_val is not None else [])
    if series:
        info["count"] = len(series)
        info["min"] = min(series)
        info["max"] = max(series)
        info["avg"] = sum(series) / float(len(series))
    return info


def check_manifest(path, cat, problems, notes):
    """previewAggregation "applies to time-based measures only".

    It is the one clause that lives in app-manifest.json rather than in the
    file, so it is checked against the manifest the file was built from.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            man = json.load(fh)
    except (IOError, OSError, ValueError) as exc:
        problems.append("cannot read the manifest %s: %s" % (path, exc))
        return
    entries = man.get("customMeasures") or []
    if not entries:
        problems.append("%s declares no customMeasures" % path)
    # Without this the clause below could pass on a manifest that simply does
    # not mention the measures the file was written from.
    ids = set(e.get("id") for e in entries)
    missing = [m["id"] for m in cat["measures"] if m["id"] not in ids]
    if missing:
        problems.append("manifest declares no customMeasure for %s"
                        % ", ".join(missing))
    for e in entries:
        if not e.get("isTimeBased") and "previewAggregation" in e:
            problems.append("manifest: %s is not time-based but declares "
                            "previewAggregation %r -- the attribute applies "
                            "to time-based measures only"
                            % (e.get("id"), e["previewAggregation"]))
    notes.append("manifest: %d customMeasures, %d of them time-based"
                 % (len(entries),
                    len([e for e in entries if e.get("isTimeBased")])))


def check(path, quiet=False, manifest=None):
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
                if dev_idx != 0:
                    problems.append("field %s is written with "
                                    "developer_data_index %d, and the rule "
                                    "says to use the SDK's, currently 0"
                                    % (d["name"], dev_idx))
                val = decode_value(raw, d["base_type"], 0)
                out.setdefault(d["name"], []).append(val)
        return out, [v for v, _ in fit.of(global_num)]

    rec_vals, records = collect(MESG_RECORD)
    lap_vals, laps = collect(MESG_LAP)
    # The session message carries the summaries the rule requires, so it has
    # to be decoded like any other; collecting only record and lap developer
    # fields is what made those summaries unverifiable before.
    ses_vals, sessions = collect(MESG_SESSION)
    if len(sessions) > 1:
        problems.append("%d session messages, expected 1 -- a summary would "
                        "then have to be read per session" % len(sessions))

    found = {"rec": rec_vals, "lap": lap_vals, "ses": ses_vals}
    for name in sorted(set(rec_vals) | set(lap_vals) | set(ses_vals)):
        if name not in by_id:
            problems.append("developer field %r is not in the catalogue"
                            % name)

    measures = {}
    for m in cat["measures"]:
        measures[m["id"]] = check_measure(m, found, len(laps), problems,
                                          notes)

    # -- the one clause that lives in the manifest ------------------------ #
    check_manifest(manifest or os.path.join(ROOT, "app-manifest.json"),
                   cat, problems, notes)

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
        "measures": measures,
    }

    if not quiet:
        report(summary, cat)
    return summary


def as_number(v):
    """A cell in the table, for a value that is allowed to be absent."""
    if v is None:
        return "-"
    return v if isinstance(v, str) else "%.4g" % v


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
    # `on` is where the values actually are, not where they were meant to be:
    # reading it against the catalogue's `where` column is the fastest way to
    # see a measure that landed on the wrong message.
    print("on = messages the values were found on.  summary = the value on "
          "the session")
    print("message.  fold = the previewAggregation fold of the records "
          "(* = implicit average)")
    print("or, for an additive measure, the sum of its lap increments.  "
          "! = has a problem.")
    print()
    print(" %-23s %-11s %5s %11s %11s %11s %11s %11s %-9s %s"
          % ("measure", "on", "n", "min", "avg", "max", "summary", "fold",
             "via", "unit"))
    for m in cat["measures"]:
        st = s["measures"].get(m["id"], {})
        mark = "!" if st.get("problems") else " "
        if not st.get("count"):
            print("%s%-23s %-11s %5s" % (mark, m["id"], st.get("on", "-"),
                                         "MISSING"))
            continue
        print("%s%-23s %-11s %5d %11.4g %11.4g %11.4g %11s %11s %-9s %s"
              % (mark, m["id"], st["on"], st["count"], st["min"], st["avg"],
                 st["max"], as_number(st["session"]), as_number(st["fold"]),
                 st["fold_kind"] or "", m["unitMetric"]))
    print()
    if s["problems"]:
        print("PROBLEMS (%d):" % len(s["problems"]))
        for p in s["problems"]:
            print("  - %s" % p)
    else:
        print("RESULT          : VALID -- every declared measure present, "
              "typed, summarised where the rule requires it, and inside "
              "its envelope")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fit", help="the .fit file to check")
    ap.add_argument("--quiet", action="store_true", help="only the exit code")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    ap.add_argument("--manifest", help="app-manifest.json to hold the "
                                       "previewAggregation rule against")
    args = ap.parse_args()

    s = check(args.fit, quiet=args.quiet or args.json,
              manifest=args.manifest)
    if args.json:
        print(json.dumps(s, indent=2, default=str))
    return 1 if s["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
