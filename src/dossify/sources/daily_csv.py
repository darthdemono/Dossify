"""Daily totals from any CSV with one row per day (steps, distance, calories, minutes, anything numeric).

Point it at files and say which columns to show.  The first column listed leads the line with its
label; the rest follow in brackets.  A column entry may list alternatives (``columns = [...]``) for
exports whose headers differ between versions: the first alternative with a value wins.  Numbers are
scaled and formatted by the entry; text cells (``3km``, ``51m10s``, ``205 kcal``) are tidied and shown
as written.  When two files cover the same day the newest file wins.  The line leads its day.

A phone dashboard history exporter, a wearable's CSV export and a hand-kept spreadsheet all fit; none
of them is special.

Options: files (a file, a folder, a glob, or a list of them), title, date_column (default date),
date_format (default %Y-%m-%d), columns (a list of tables: column or columns, label, scale, format, kind = "distance" to space a unit like 3km).
"""

import csv
import glob
import os
import re
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact

TIER = "core"
_O: dict = {}   # this provider's options, set by the registry before each read

NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")


def _files(spec):
    found = set()
    for item in J.listify(spec):
        if os.path.isdir(item):
            found.update(glob.glob(os.path.join(item, "*.csv")))
        elif any(ch in item for ch in "*?["):
            found.update(glob.glob(item))
        elif os.path.isfile(item):
            found.add(item)
    return sorted(found)


def tidy(text, distance=False):
    """`205 KCAL` -> `205 kcal`, `51m10s` -> `51m 10s`; with distance=True also `3km` -> `3 km`."""
    text = text.strip().lower()
    if distance:
        text = re.sub(r"^(\d+(?:\.\d+)?)(km|m)$", r"\1 \2", text)
    return re.sub(r"(?<=[hms])(?=\d)", " ", text)


def _entry_text(entry, row, lead):
    names = entry.get("columns") or [entry.get("column")]
    for name in names:
        cell = (row.get(name) or "").strip()
        if not cell:
            continue
        if NUMBER.match(cell):
            value = float(cell) * float(entry.get("scale", 1))
            value = int(value) if value == int(value) and "scale" not in entry else value
            fmt = entry.get("format")
            body = fmt.format(value) if fmt else (format(value, ",") if lead else str(value))
        else:
            body = tidy(cell, distance=entry.get("kind") == "distance")
        return body
    return ""


def a_daily_csv():
    entries = list(_O.get("columns") or [])
    if not entries:
        return []
    date_col = str(_O.get("date_column") or "date")
    date_fmt = str(_O.get("date_format") or "%Y-%m-%d")
    best = {}                       # date -> (file mtime, lead text, detail texts)
    for path in _files(_O.get("files")):
        try:
            mtime = os.path.getmtime(path)
            with open(path, encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, UnicodeError, csv.Error):
            continue
        for row in rows:
            try:
                day = datetime.strptime((row.get(date_col) or "").strip(), date_fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
            lead = _entry_text(entries[0], row, True)
            if not lead:
                continue
            label = str(entries[0].get("label") or "")
            details = [t for t in (_entry_text(e, row, False) for e in entries[1:]) if t]
            candidate = (mtime, ("%s %s" % (lead, label)).strip(), details)
            if day not in best or candidate[0] > best[day][0]:
                best[day] = candidate
    title = str(_O.get("title") or "Daily metrics")
    out = []
    for day, (_mtime, lead, details) in sorted(best.items()):
        text = "%s: %s" % (title, lead) + (" (%s)" % "; ".join(details) if details else "")
        out.append(Fact(day, None, text, "daily_csv"))
    return out


READERS = {"daily_csv": a_daily_csv}
LABELS = {"daily_csv": "Daily totals read from CSV exports."}
