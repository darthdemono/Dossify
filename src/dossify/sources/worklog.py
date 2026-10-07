"""Shifts from a markdown work-log table.

Options: path, label (a short employer name shown before the role)."""

import os, re

from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_worklog():
    """The shift itself. One line, the clock range and what it paid, with
    anything the table itself flags about the day nested under it."""
    p = os.path.expanduser(str(_O.get("path") or ""))
    if not p or not os.path.exists(p):
        return []
    out, cols = [], None
    for line in open(p, encoding="utf-8"):
        if not line.startswith("|"):
            cols = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if "Role" in cells and "Gross" in cells:          # the shift table's header
            cols = {name: i for i, name in enumerate(cells)}
            continue
        if not cols or set("".join(cells)) <= set("-: "):
            continue
        def get(name):
            i = cols.get(name)
            return re.sub(r"\*\*|`|\[\^\d+\]", "", cells[i]).strip() if i is not None and i < len(cells) else ""
        m = re.match(r"^(\d{2})-(\d{2})-(\d{4})$", get("Date"))
        if not m:
            continue
        date = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
        # "8:00–19:30" as written in the table, zero-padded so the day sorts
        span = get("Hours").replace("\u2013", " - ").replace("\u2014", " - ")
        span = re.sub(r"(?<!\d)(\d):", r"0\1:", span)
        span = re.sub(r"\s*-\s*", " - ", span).strip()
        pay = get("Net (85%)") or get("Net") or ""
        label = str(_O.get("label") or "")
        head = "%s - %s%s%s" % (
            span, label + " " if label else "", get("Role"),
            " (%s net)" % pay if pay else "")
        kids = []
        # Length carries its own remark when the day did not run its booked span
        length = get("Length")
        mm = re.match(r"^(.+?)\s*\((booked .+)\)$", length)
        if mm:
            kids.append("%s of a %s" % (mm.group(1).strip(), mm.group(2).strip()))
        thru = get("Avg throughput")
        items = get("Packages / items") or get("Sub-packages")
        if thru and thru.lower() not in ("n/a", "n/a (flat)", ""):
            kids.append("%s%s" % (thru, ", %s" % items if items and items.lower() != "n/a" else ""))
        if kids:
            out.append(Fact(date, None, head + "\n" + "\n".join("    - %s" % k for k in kids),
                            "worklog"))
        else:
            out.append(Fact(date, None, head, "worklog"))
    return out


READERS = {"worklog": a_worklog}
LABELS = {'worklog': 'Shifts read from a work-log table.'}
