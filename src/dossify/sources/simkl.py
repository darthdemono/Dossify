"""Watch history from the Simkl API, or a CSV backup when the API is not set up.

Options: api_key_env or api_key_command, token_file, backup_csv."""

import csv, json, os, re
from collections import defaultdict
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_simkl():
    facts = _simkl_api()
    return facts if facts else _simkl_csv()


def _simkl_csv():
    p = os.path.expanduser(str(_O.get("backup_csv") or ""))
    if not p or not os.path.exists(p):
        return []
    out = []
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        m = re.match(r"^(\d{2})-(\d{2})-(\d{4}) (\d{2}:\d{2})", (r.get("WatchedDate") or "").strip())
        if not m:
            continue
        date = "%s-%s-%s" % (m.group(3), m.group(2), m.group(1))
        title = (r.get("Title") or "").strip()
        ep = (r.get("LastEpWatched") or "").strip()
        out.append(Fact(date, m.group(4), "Simkl: %s%s" % (
            title, " \u2014 " + ep.upper() if ep else ""), "simkl"))
    return out


def _simkl_api():
    cid = J.secret(_O)
    tokfile = os.path.expanduser(str(_O.get("token_file") or ""))
    if not cid or not tokfile or not os.path.exists(tokfile):
        return []
    try:
        tok = json.load(open(tokfile, encoding="utf-8"))["access_token"]
    except Exception:
        return []
    import urllib.request
    req = urllib.request.Request(
        "https://api.simkl.com/sync/all-items/?extended=full&episode_watched_at=yes",
        headers={"Authorization": "Bearer " + tok, "simkl-api-key": cid,
                 "Accept": "application/json", "User-Agent": "journal-auto/1.0"})
    try:
        d = json.loads(urllib.request.urlopen(req, timeout=120).read().decode())
    except Exception:
        return []

    def local(iso):
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(J.TZ_DEFAULT)
        except Exception:
            return None

    events = []
    for sec in ("shows", "anime"):
        for it in d.get(sec) or []:
            title = ((it.get("show") or {}).get("title") or "?").strip()
            for season in it.get("seasons") or []:
                for ep in season.get("episodes") or []:
                    dt = local(ep.get("watched_at") or "")
                    if dt:
                        events.append((dt, "Simkl: %s S%02dE%02d" % (
                            title, season.get("number") or 0, ep.get("number") or 0)))
    for mv in d.get("movies") or []:
        dt = local(mv.get("last_watched_at") or "")
        if dt:
            t = (mv.get("movie") or {}).get("title") or "?"
            y = (mv.get("movie") or {}).get("year")
            events.append((dt, "Simkl: %s%s (film)" % (t, " (%s)" % y if y else "")))

    # Simkl accepts a whole backlog in one go: 21-06-2025 carries 1,113 episodes.
    # That is an import, not an evening's viewing, and it collapses like Jellyfin's.
    perday = defaultdict(list)
    for dt, text in events:
        perday[dt.strftime("%Y-%m-%d")].append((dt.strftime("%H:%M"), text))
    out = []
    for date, items in perday.items():
        if len(items) >= 40:
            out.append(Fact(date, None,
                "Simkl: %d titles marked watched in one day \u2014 a bulk library import, "
                "not an evening's viewing" % len(items), "simkl"))
            continue
        perminute = defaultdict(list)
        for time, text in items:
            perminute[time].append(text)
        for time, texts in perminute.items():
            if len(texts) >= 8:
                out.append(Fact(date, time, "Simkl: %d titles marked watched in one "
                                "minute \u2014 a bulk operation" % len(texts), "simkl"))
            else:
                for text in texts:
                    out.append(Fact(date, time, text, "simkl"))
    return out


READERS = {"simkl": a_simkl}
LABELS = {'simkl': 'Watch history read from Simkl.'}
