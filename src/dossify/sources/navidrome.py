"""Plays from a Navidrome database that a scrobbler did not receive.

Options: db."""

import json, os, re, sqlite3
from collections import defaultdict

from dossify import journal as J
from dossify.journal import Fact, epoch_local

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_navidrome():
    """Navidrome plays that Last.fm never received, shaped like Last.fm's own
    facts so the renderer folds both into one "Listened to:" list. A play Last.fm
    already holds is dropped when it lands within two minutes AND shares the
    artist or the title, so a different track on another device is not lost."""
    db = os.path.expanduser(str(_O.get("db") or ""))
    if not db or not os.path.exists(db):
        return []

    def norm(x):
        return re.sub(r"\W+", "", (x or "").casefold())

    known = defaultdict(list)                  # minute -> [(artist, track)]
    try:
        blob = json.load(open(J.lastfm_cache_path(), encoding="utf-8"))
        for r in blob if isinstance(blob, list) else []:
            if r.get("uts"):
                known[int(r["uts"]) // 60].append((norm(r.get("artist")), norm(r.get("track"))))
    except Exception:
        pass
    try:
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        rows = con.execute(
            "select s.submission_time, m.title, m.artist from scrobbles s "
            "join media_file m on m.id = s.media_file_id").fetchall()
    except Exception:
        return []
    byday, seen = defaultdict(list), set()
    for ts, title, artist in rows:
        if not ts:
            continue
        minute = int(ts) // 60
        key = (minute, norm(title), norm(artist))
        if key in seen:                        # the same play written twice
            continue
        seen.add(key)
        if any(a == key[2] or t == key[1]
               for d in (-2, -1, 0, 1, 2) for a, t in known.get(minute + d, ())):
            continue                           # Last.fm already has this play
        date, time = epoch_local(ts)
        if date:
            byday[date].append((time, "%s by %s" % (title, artist or "unknown artist")))
    out = []
    for date, rows2 in byday.items():
        rows2.sort()
        if len(rows2) == 1:
            out.append(Fact(date, rows2[0][0], rows2[0][1], "navidrome"))
        else:
            kids = "\n".join("    - %s - %s" % r for r in rows2)
            out.append(Fact(date, None, "Tracks scrobbled:\n" + kids, "navidrome"))
    return out


READERS = {"navidrome": a_navidrome}
LABELS = {'navidrome': 'Plays read from a Navidrome database.'}
