"""Hours coded per day from the WakaTime API.

Options: api_key_env or api_key_command."""

import json, os
from datetime import datetime, timedelta

from dossify import journal as J
from dossify.journal import Fact, _hm

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_wakatime():
    """Hours actually coded. Git records the commit, not the afternoon."""
    key = J.secret(_O)
    if not key:
        return []
    import base64, urllib.request
    store = os.path.join(J.CACHE, "wakatime.json")
    days = {}
    try:
        days = json.load(open(store, encoding="utf-8"))
    except (OSError, ValueError):
        pass
    today = datetime.now().strftime("%Y-%m-%d")
    start = "2023-11-27"                      # the account's own first day
    if days:
        # everything before the last fortnight is settled; only refetch the tail
        cut = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        start = min(cut, max(days) if days else cut)
    auth = base64.b64encode(key.encode()).decode()
    cur = datetime.strptime(start, "%Y-%m-%d")
    end = datetime.strptime(today, "%Y-%m-%d")
    while cur <= end:
        chunk = min(cur + timedelta(days=59), end)
        url = ("https://wakatime.com/api/v1/users/current/summaries?start=%s&end=%s"
               % (cur.strftime("%Y-%m-%d"), chunk.strftime("%Y-%m-%d")))
        req = urllib.request.Request(url, headers={"Authorization": "Basic " + auth})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                blob = json.load(r)
        except Exception as ex:
            print("  wakatime: %s" % ex)
            break
        for d in blob.get("data", []):
            secs = (d.get("grand_total") or {}).get("total_seconds") or 0
            if secs < 60:                     # a stray minute is not a day's work
                continue
            # deliberately only the totals: the payload also carries AI prompt
            # counts, token usage and model spend, which are none of a journal's
            # business
            days[d["range"]["date"]] = {
                "s": secs,
                "p": [(p["name"], p["total_seconds"]) for p in (d.get("projects") or [])[:4]],
                "l": [p["name"] for p in (d.get("languages") or [])[:3]],
            }
        cur = chunk + timedelta(days=1)
    try:
        os.makedirs(J.CACHE, exist_ok=True)
        json.dump(days, open(store, "w", encoding="utf-8"))
    except OSError:
        pass
    out = []
    for date, d in days.items():
        projects = ", ".join("%s (%s)" % (n, _hm(s)) for n, s in d["p"]
                             if s >= 60 and n != "Unknown Project")
        text = "Coded %s%s" % (_hm(d["s"]), ": " + projects if projects else "")
        out.append(Fact(date, None, text, "wakatime"))
    return out


READERS = {"wakatime": a_wakatime}
LABELS = {'wakatime': 'Coding time fetched from WakaTime.'}
