"""Plays from a Jellyfin library database.

Options: user, db (path to jellyfin.db)."""

import os, sqlite3
from collections import defaultdict
from datetime import datetime

from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_jellyfin():
    username = str(_O.get("user") or "")
    db = os.path.expanduser(str(_O.get("db") or ""))
    if not username or not db or not os.path.exists(db):
        return []
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    rows = con.execute("""
        select distinct u.LastPlayedDate, b.Type, b.Name, b.SeriesName,
               b.ParentIndexNumber, b.IndexNumber, b.ProductionYear
        from UserData u
             join BaseItems b on b.Id = u.ItemId
             join Users usr on usr.Id = u.UserId
        where usr.Username = ?
          and u.Played = 1 and u.LastPlayedDate is not null
        group by u.ItemId, u.LastPlayedDate
          and b.Type in ('MediaBrowser.Controller.Entities.TV.Episode',
                         'MediaBrowser.Controller.Entities.Movies.Movie')
    """, (username,)).fetchall()
    con.close()
    # A minute holding many items is a bulk mark-played, not viewing. 31-08-2026
    # has 2,289 of them across two minutes. Those collapse to one honest line.
    BULK = 8
    buckets = defaultdict(list)
    for played, typ, name, series, season, ep, year in rows:
        try:
            dt = datetime.fromisoformat(played.replace("Z", "+00:00"))
        except Exception:
            continue
        if "Episode" in typ and series:
            tag = "S%02dE%02d" % (season or 0, ep or 0)
            text = 'Watched %s %s "%s"' % (series, tag, name)
        else:
            text = "Watched %s%s" % (name, " (%d)" % year if year else "")
        buckets[(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"))].append(text)
    out = []
    for (date, time), items in buckets.items():
        if len(items) >= BULK:
            out.append(Fact(date, time,
                "Jellyfin: %d items marked played in one minute — a bulk library "
                "operation, not viewing" % len(items), "jellyfin"))
        else:
            for text in items:
                out.append(Fact(date, time, text, "jellyfin"))
    return out


READERS = {"jellyfin": a_jellyfin}
LABELS = {'jellyfin': 'Watched items read from a Jellyfin database.'}
