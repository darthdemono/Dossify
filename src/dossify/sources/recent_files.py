"""Files opened, from the desktop's recently-used list.

Options: file (default ~/.local/share/recently-used.xbel)."""

import os, re
from collections import defaultdict

from dossify.journal import iso_local, nest

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


SKIP_FILES = re.compile(r"/\.|/tmp/|/Trash/|thumbnail|\.part$|/proc/", re.I)


def a_files():
    """Files opened, off the desktop's own recent list. One bullet a day: a
    flat list of forty opens would bury everything else in the block."""
    p = os.path.expanduser(str(_O.get("file") or "~/.local/share/recently-used.xbel"))
    if not os.path.exists(p):
        return []
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(p).getroot()
    except Exception:
        return []
    byday = defaultdict(list)
    for bm in root.iter("bookmark"):
        href = bm.get("href") or ""
        stamp = bm.get("visited") or bm.get("modified") or ""
        if not href.startswith("file://") or SKIP_FILES.search(href):
            continue
        date, time = iso_local(stamp)
        if not date:
            continue
        name = urllib_unquote(os.path.basename(href.rstrip("/")))
        if name:
            byday[date].append((time, name))
    out = []
    for date, rows in byday.items():
        rows.sort()
        lines = ["%s · %s" % (t, n) for t, n in rows[:12]]
        if len(rows) > 12:
            lines.append("and %d more" % (len(rows) - 12))
        f = nest(date, "Files opened:", lines, "files")
        if f:
            out.append(f)
    return out


def urllib_unquote(s):
    import urllib.parse
    return urllib.parse.unquote(s)


READERS = {"files": a_files}
LABELS = {'files': "Files opened, read from the desktop's recent-files list."}
