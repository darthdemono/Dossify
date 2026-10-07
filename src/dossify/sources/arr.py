"""Grabbed and imported items from Sonarr and Radarr history databases.

Options: sonarr_db, radarr_db."""

import os, sqlite3

from dossify.journal import Fact, iso_local

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


# Sonarr and Radarr number their history events the same way. Only the two that
# mean something entered the library are kept; the rest of the table is renames
# and deletions from bulk maintenance.
ARR_EVENTS = {1: "grabbed", 3: "imported", 6: "imported"}


def a_arr():
    out = []
    for label, path, table in (
            ("Sonarr", os.path.expanduser(str(_O.get("sonarr_db") or "")), "History"),
            ("Radarr", os.path.expanduser(str(_O.get("radarr_db") or "")), "History")):
        if not path or not os.path.exists(path):
            continue
        try:
            con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
            rows = con.execute("select Date, SourceTitle, EventType from %s" % table).fetchall()
        except Exception:
            continue
        for stamp, title, ev in rows:
            verb = ARR_EVENTS.get(ev)
            if not verb or not title:
                continue
            date, time = iso_local(str(stamp).split(".")[0] + "+00:00")
            if not date:
                continue
            out.append(Fact(date, time, "%s %s %s" % (label, verb, title[:90]), "arr"))
    return list(dict.fromkeys(out))


READERS = {"arr": a_arr}
LABELS = {'arr': 'Library grabs and imports read from Sonarr and Radarr.'}
