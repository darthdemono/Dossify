"""Scrobbles fetched from the Last.fm API and cached.

Options: user, api_key_env or api_key_command, cache."""

import json, os
from collections import defaultdict
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact, UTC

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_lastfm():
    key = J.secret(_O)
    username = str(_O.get("user") or "")
    cache_file = J.lastfm_cache_path()
    if not username:
        return []
    import urllib.request, urllib.parse
    rows = []
    if os.path.exists(cache_file):
        try:
            rows = json.load(open(cache_file, encoding="utf-8"))
        except Exception:
            rows = []
    # older caches predate the album field; one full refetch upgrades them
    if rows and "album" not in rows[0]:
        rows = []
    if key:
        seen = {r["uts"] for r in rows}
        since = max(seen) if seen else 0

        def api(**kw):
            kw.update(api_key=key, format="json", user=username)
            u = "https://ws.audioscrobbler.com/2.0/?" + urllib.parse.urlencode(kw)
            return json.loads(urllib.request.urlopen(u, timeout=60).read().decode())

        page, pages, added = 1, 1, 0
        while page <= pages:
            try:
                r = api(method="user.getrecenttracks", limit=200, page=page,
                        **({"from": since + 1} if since else {}))["recenttracks"]
            except Exception:
                break
            pages = int(r.get("@attr", {}).get("totalPages", 1))
            tracks = r.get("track") or []
            if isinstance(tracks, dict):
                tracks = [tracks]
            for t in tracks:
                d = t.get("date")
                if not d:                       # the "now playing" row has no date
                    continue
                uts = int(d["uts"])
                if uts in seen:
                    continue
                seen.add(uts)
                rows.append({"uts": uts,
                             "artist": (t.get("artist") or {}).get("#text", "").strip(),
                             "album": (t.get("album") or {}).get("#text", "").strip(),
                             "track": (t.get("name") or "").strip()})
                added += 1
            page += 1
        if added:
            os.makedirs(os.path.dirname(cache_file), exist_ok=True)
            json.dump(rows, open(cache_file, "w", encoding="utf-8"))
    if not rows:
        return []

    byday = defaultdict(list)
    for r in rows:
        dt = datetime.fromtimestamp(r["uts"], UTC).astimezone(J.TZ_DEFAULT)
        byday[dt.strftime("%Y-%m-%d")].append((dt, r["artist"], r["album"], r["track"]))

    out = []
    for date, items in byday.items():
        items.sort(key=lambda x: x[0])
        # Collapse consecutive plays by the same artist into one entry. Listening
        # runs in stretches, and a bare count of tracks says nothing about what was
        # actually on; the run is the unit worth remembering.
        runs, cur = [], None
        for dt, artist, album, track in items:
            if cur and cur["artist"] == artist:
                cur["tracks"].append(track)
                if album:
                    cur["albums"].append(album)
            else:
                if cur:
                    runs.append(cur)
                cur = {"start": dt, "artist": artist,
                       "tracks": [track], "albums": [album] if album else []}
        if cur:
            runs.append(cur)

        lines = []
        for r in runs:
            when = r["start"].strftime("%H:%M")
            who = r["artist"] or "unknown artist"
            albums = list(dict.fromkeys(r["albums"]))
            n = len(r["tracks"])
            if n == 1:
                lines.append("%s - %s by %s" % (when, r["tracks"][0], who))
            elif len(albums) > 1:
                lines.append("%s - %d tracks across %d albums by %s" % (when, n, len(albums), who))
            elif albums:
                lines.append("%s - %d tracks from %s by %s" % (when, n, albums[0], who))
            else:
                lines.append("%s - %d tracks by %s" % (when, n, who))
        if len(lines) == 1:
            out.append(Fact(date, runs[0]["start"].strftime("%H:%M"),
                            lines[0].split(" - ", 1)[1], "lastfm"))
        else:
            kids = "\n".join("    - %s" % l for l in lines)
            out.append(Fact(date, None, "Tracks scrobbled:\n" + kids, "lastfm"))
    return out


READERS = {"lastfm": a_lastfm}
LABELS = {'lastfm': 'Listening history fetched from Last.fm.'}
