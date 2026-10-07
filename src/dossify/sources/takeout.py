"""Google Takeout activity (search, YouTube, Chrome, location, Play, Fit).

Options: export, search_text, browser_urls, known_places ([lat, lng, radius_km, name] rows)."""

import collections, csv, glob, html, os, re
from collections import defaultdict
from datetime import datetime, timedelta, timezone as _tz

from dossify import journal as J
from dossify.journal import Fact, cached, epoch_local, iso_local, jload, nest

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


def takeout_accounts():
    """(label, root) for every extracted Takeout named by `export`.

    An entry is either one account's extracted export (it holds a `Takeout` folder) or a
    folder of several such exports.
    """
    out, accounts = [], []
    for entry in J.listify(_O.get("export")):
        if not os.path.isdir(entry):
            continue
        children = sorted(d for d in glob.glob(os.path.join(entry, "*")) if os.path.isdir(d))
        accounts += [entry] if any(os.path.basename(c).lower() == "takeout" for c in children) else children
    for d in sorted(accounts):
        if not os.path.isdir(d):
            continue
        inner = [d] + sorted(glob.glob(os.path.join(d, "*")))
        for cand in inner:
            if os.path.isdir(cand) and os.path.basename(cand).lower() == "takeout":
                out.append((os.path.basename(d), cand))
                break
        else:
            out.append((os.path.basename(d), d))
    return out


def tfind(root, *names):
    """Find files by filename anywhere under an export.

    Product folder names are translated into the account's interface language,
    so matching on the folder is not safe. The file names inside are the
    stable part, and even those only when the export was requested in English.
    """
    hits = []
    for name in names:
        hits += glob.glob(os.path.join(root, "**", name), recursive=True)
    return sorted(set(hits))


def near_place(lat, lng):
    import math

    for plat, plng, km, name in _O.get("known_places", []):
        # a degree of latitude is 111 km; longitude is narrowed by the cosine of the latitude
        dy = (lat - plat) * 111.0
        dx = (lng - plng) * 111.0 * math.cos(math.radians(plat))
        if (dx * dx + dy * dy) ** 0.5 <= km:
            return name
    return None


# Takeout offers My Activity and the YouTube history as HTML only, so these
# read that markup back into the records the JSON form would have given.
_ACT_HEAD = re.compile(r'<p class="mdl-typography--title">(.*?)<', re.S)


_ACT_BODY = re.compile(
    r'<div class="content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1">(.*?)</div>',
    re.S)


_ACT_TAG = re.compile(r"<[^>]+>")


_ACT_BR = re.compile(r"<br\s*/?>")


_ACT_ZONE = re.compile(r"^(.*?)\s+(GMT[+-]\d{1,2}(?::\d{2})?|[A-Z]{2,5})$")


# Every row in the 2026 exports is stamped CEST, winter included. 67 winter
# plays line up with the Last.fm epochs at a fixed +02:00 and none line up with
# the real DST of that zone, so the label is read literally rather than resolved
# against a timezone.
_ACT_TZ = {"CEST": 120, "CET": 60, "GMT": 0, "UTC": 0}


_ACT_WHEN = ("%b %d, %Y, %I:%M:%S %p", "%b %d, %Y, %H:%M:%S",
             "%d %b %Y, %H:%M:%S", "%d %b %Y at %H:%M:%S")


def _act_when(text):
    """'Sep 8, 2026, 8:03:35 AM CEST' as an ISO string carrying its offset."""
    m = _ACT_ZONE.match(text)
    if not m:
        return None
    stamp, zone = m.group(1), m.group(2)
    if zone.startswith("GMT") and len(zone) > 3:
        bits = zone[4:].split(":")
        try:
            mins = int(bits[0]) * 60 + (int(bits[1]) if len(bits) > 1 else 0)
        except ValueError:
            return None
        mins = -mins if zone[3] == "-" else mins
    elif zone in _ACT_TZ:
        mins = _ACT_TZ[zone]
    else:
        return None
    for fmt in _ACT_WHEN:
        try:
            dt = datetime.strptime(stamp, fmt)
        except ValueError:
            continue
        return dt.replace(tzinfo=_tz(timedelta(minutes=mins))).isoformat()
    return None


def _act_html(path):
    """MyActivity.html or watch-history.html as {time, header, title, subtitles}."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
    except OSError:
        return []
    rows = []
    for cell in raw.split('<div class="outer-cell')[1:]:
        body = _ACT_BODY.search(cell)
        if not body:
            continue
        when, text = None, []
        for seg in _ACT_BR.split(body.group(1)):
            plain = html.unescape(_ACT_TAG.sub("", seg))
            plain = plain.replace("\xa0", " ").replace("\u202f", " ")
            plain = re.sub(r"\s+", " ", plain).strip()
            if not plain:
                continue
            iso = _act_when(plain)
            if iso:
                when = iso
            else:
                text.append(plain)
        if not when or not text:
            continue
        head = _ACT_HEAD.search(cell)
        rows.append({
            "time": when,
            "header": (html.unescape(_ACT_TAG.sub("", head.group(1))).strip()
                       if head else ""),
            "title": text[0],
            "subtitles": [{"name": t} for t in text[1:2]],
        })
    return rows


def _act_rows(path):
    """One activity export, whichever of the two formats Takeout handed over."""
    if path.lower().endswith(".html"):
        return _act_html(path)
    data = jload(path)
    return data if isinstance(data, list) else []


PRODUCT = {"Search": "Google", "Image Search": "Google Images",
           "Video Search": "Google Video", "Google Play Store": "Play Store"}


def _takeout_activity(paths, out, skip_youtube=False):
    """MyActivity.json, one per Google product."""
    watched = defaultdict(list)
    searched = defaultdict(list)
    for p in paths:
        data = _act_rows(p)
        for e in data:
            if not isinstance(e, dict):
                continue
            date, time = iso_local(e.get("time"))
            if not date:
                continue
            head = (e.get("header") or "").strip()
            title = re.sub(r"\s+", " ", (e.get("title") or "").strip())
            subs = e.get("subtitles") or []
            who = (subs[0].get("name") if subs and isinstance(subs[0], dict) else "") or ""
            # YouTube Music rows carry their own header, so matching the
            # product exactly would file 884 of the 2026 export's watch rows
            # as untitled Google activity instead.
            if head.startswith("YouTube") and title.startswith("Watched"):
                if skip_youtube:
                    continue          # watch-history.json carries the same rows
                name = title[len("Watched"):].strip()
                watched[date].append((time, "%s%s" % (name, " by " + who if who else "")))
            elif title.startswith("Searched for"):
                searched[date].append((time, head, title[len("Searched for"):].strip()))
            # An app launch and a bare product hit are counts of taps, not
            # things done. Dropped 09-09-2026: "47 app launches, mostly
            # com.miui.home (3)" is noise in a diary, where "played PUBG"
            # would not be. Nothing in this export records the second kind.
    for date, rows in watched.items():
        lines = ["%s · %s" % (t, n) for t, n in sorted(rows)]
        f = nest(date, "Watched on YouTube:", lines, "takeout")
        if f:
            out.append(f)
    for date, rows in searched.items():
        if _O.get("search_text", False):
            # The same query is logged once by Search and again by AI Mode or
            # Image Search in the same second, which doubled every line. One
            # query at one minute is one thing he looked up. The product is
            # only worth naming when it is not plain Google.
            def rank(where):
                # plain Google wins, then a product worth naming, then the
                # AI Mode echo, which is never the interesting copy
                return 0 if where in ("Google", "Search") else (2 if where == "AI Mode" else 1)
            pick = {}
            for t, h, q in rows:
                key = (t, q.lower())
                where = PRODUCT.get(h, h)
                if key not in pick or rank(where) < rank(pick[key][0]):
                    pick[key] = (where, q)
            lines = []
            for (t, _k), (where, q) in sorted(pick.items()):
                lines.append("%s · %s" % (t, q) if where in ("Google", "Search")
                             else "%s · %s: %s" % (t, where, q))
            f = nest(date, "Searched:", lines, "takeout")
            if f:
                out.append(f)
            continue
        # With search_text off there is only a number left, and a number is
        # not something he did. Say nothing rather than say "25 searches".
        continue


def _takeout_youtube(paths, out):
    """watch-history.json, the same shape as MyActivity but its own file."""
    for p in paths:
        data = _act_rows(p)
        byday = defaultdict(list)
        for e in data:
            if not isinstance(e, dict):
                continue
            date, time = iso_local(e.get("time"))
            title = re.sub(r"\s+", " ", (e.get("title") or "").strip())
            if not date or not title.startswith("Watched"):
                continue
            subs = e.get("subtitles") or []
            who = (subs[0].get("name") if subs and isinstance(subs[0], dict) else "") or ""
            byday[date].append((time, "%s%s" % (title[7:].strip(),
                                                " by " + who if who else "")))
        for date, rows in byday.items():
            f = nest(date, "Watched on YouTube:",
                     ["%s · %s" % (t, n) for t, n in sorted(rows)], "takeout")
            if f:
                out.append(f)


def _takeout_chrome(paths, out):
    for p in paths:
        data = jload(p)
        if not isinstance(data, dict):
            continue
        rows = data.get("Browser History") or []
        byday = defaultdict(collections.Counter)
        for e in rows:
            usec = e.get("time_usec")
            if not usec:
                continue
            date, _ = epoch_local(int(usec) / 1e6)
            if not date:
                continue
            host = re.sub(r"^www\.", "", (re.split(r"/+", str(e.get("url") or ""))[1:2] or [""])[0])
            byday[date][host or "unknown"] += 1
        for date, c in byday.items():
            if _O.get("browser_urls", False):
                lines = ["%s (%d)" % (k, v) for k, v in c.most_common(20)]
                f = nest(date, "Browsed:", lines, "takeout")
                if f:
                    out.append(f)


def _takeout_location(paths, out):
    """Both shapes: the old Semantic Location History and the newer Timeline."""
    for p in paths:
        data = jload(p)
        if data is None:
            continue
        segs = []
        if isinstance(data, dict) and "timelineObjects" in data:
            for o in data["timelineObjects"]:
                if "placeVisit" in o:
                    v = o["placeVisit"]
                    loc = v.get("location") or {}
                    dur = v.get("duration") or {}
                    segs.append(("visit", dur.get("startTimestamp"), dur.get("endTimestamp"),
                                 loc.get("name") or loc.get("address"),
                                 loc.get("latitudeE7"), loc.get("longitudeE7"), None, None))
                elif "activitySegment" in o:
                    a = o["activitySegment"]
                    dur = a.get("duration") or {}
                    segs.append(("move", dur.get("startTimestamp"), dur.get("endTimestamp"),
                                 None, None, None,
                                 a.get("activityType"), a.get("distance")))
        elif isinstance(data, dict) and "semanticSegments" in data:
            for s in data["semanticSegments"]:
                st, en = s.get("startTime"), s.get("endTime")
                if "visit" in s:
                    top = ((s["visit"] or {}).get("topCandidate") or {})
                    ll = ((top.get("placeLocation") or {}).get("latLng") or "")
                    m = re.findall(r"-?\d+\.\d+", str(ll))
                    lat = float(m[0]) if len(m) > 1 else None
                    lng = float(m[1]) if len(m) > 1 else None
                    segs.append(("visit", st, en, top.get("semanticType"),
                                 lat, lng, None, None))
                elif "activity" in s:
                    a = s["activity"] or {}
                    segs.append(("move", st, en, None, None, None,
                                 (a.get("topCandidate") or {}).get("type"),
                                 a.get("distanceMeters")))
        byday = defaultdict(list)
        for kind, st, en, name, lat, lng, act, dist in segs:
            date, time = iso_local(st)
            if not date:
                continue
            mins = None
            d2, _ = iso_local(en)
            try:
                a = datetime.fromisoformat(str(st).replace("Z", "+00:00"))
                b = datetime.fromisoformat(str(en).replace("Z", "+00:00"))
                mins = int((b - a).total_seconds() // 60)
            except (ValueError, TypeError):
                pass
            span = ""
            if mins and mins >= 5:
                span = " (%dh %02dm)" % (mins // 60, mins % 60) if mins >= 60 else " (%d min)" % mins
            if kind == "visit":
                if lat is not None and lng is not None:
                    if isinstance(lat, int) and abs(lat) > 1000:
                        lat, lng = lat / 1e7, lng / 1e7
                    place = near_place(lat, lng) or name
                    if not place:
                        place = "an unnamed place (%.4f, %.4f)" % (lat, lng)
                elif isinstance(lat, int):
                    place = name or "an unnamed place"
                else:
                    place = name or "an unnamed place"
                byday[date].append((time, "At %s%s" % (place, span)))
            else:
                km = ""
                try:
                    km = ", %.1f km" % (float(dist) / 1000.0) if dist else ""
                except (TypeError, ValueError):
                    km = ""
                how = MOVES.get(str(act or "").upper(),
                                str(act or "moved").replace("_", " ").lower())
                byday[date].append((time, "Travelled %s%s%s" % (how, km, span)))
        for date, rows in byday.items():
            f = nest(date, "Timeline:", ["%s · %s" % (t, s) for t, s in sorted(rows)],
                     "takeout")
            if f:
                out.append(f)


MOVES = {"IN_BUS": "by bus", "IN_TRAM": "by tram", "IN_SUBWAY": "by metro",
         "IN_TRAIN": "by train", "IN_PASSENGER_VEHICLE": "by car", "IN_TAXI": "by taxi",
         "WALKING": "on foot", "ON_FOOT": "on foot", "CYCLING": "by bike",
         "FLYING": "by air", "MOTORCYCLING": "by motorcycle",
         "IN_FERRY": "by ferry", "STILL": "not at all"}


def _takeout_play(paths, out):
    for p in paths:
        data = jload(p)
        if not isinstance(data, list):
            continue
        for e in data:
            doc = ((e or {}).get("install") or {}).get("doc") or {}
            when = ((e or {}).get("install") or {}).get("firstInstallationTime")
            if doc and when:
                date, time = iso_local(when)
                if date:
                    out.append(Fact(date, time, "Installed %s" % doc.get("title"), "takeout"))
                continue
            ph = (e or {}).get("purchaseHistory") or {}
            if ph:
                date, time = iso_local(ph.get("purchaseTime"))
                price = ((ph.get("invoicePrice") or "")).strip()
                if date:
                    out.append(Fact(date, time, "Google Play: %s%s" % (
                        ph.get("doc", {}).get("title", "purchase"),
                        ", " + price if price else ""), "takeout"))


def _takeout_fit(paths, out):
    for p in paths:
        try:
            rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
        except OSError:
            continue
        for r in rows:
            date = (r.get("Date") or "").strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                continue
            bits = []
            steps = r.get("Step count") or ""
            dist = r.get("Distance (m)") or ""
            try:
                if float(steps) > 0:
                    bits.append("{:,} steps".format(int(float(steps))))
            except ValueError:
                pass
            try:
                if float(dist) > 0:
                    bits.append("%.1f km walked" % (float(dist) / 1000.0))
            except ValueError:
                pass
            if bits:
                out.append(Fact(date, None, ", ".join(bits), "takeout"))


def _takeout_places(paths, out):
    for p in paths:
        data = jload(p)
        feats = (data or {}).get("features") if isinstance(data, dict) else None
        for f in feats or []:
            props = (f or {}).get("properties") or {}
            date, time = iso_local(props.get("date") or props.get("published"))
            name = ((props.get("location") or {}).get("name")
                    or props.get("Business Name") or props.get("name"))
            if date and name:
                out.append(Fact(date, time, "Saved %s in Maps" % name, "takeout"))


def _yt_watched(paths):
    """How many watch rows a copy of the history actually holds."""
    n = 0
    for p in paths:
        for e in _act_rows(p):
            if isinstance(e, dict) and str(e.get("title") or "").startswith("Watched"):
                n += 1
    return n


def a_takeout():
    accounts = takeout_accounts()
    if not accounts:
        return []
    all_facts = []
    for label, root in accounts:
        def build(_paths, root=root):
            out = []
            yt = tfind(root, "watch-history.json", "watch-history.html")
            act = tfind(root, "MyActivity.json", "MyActivity.html", "My Activity.html")
            # The watch history ships twice and neither copy is reliably the
            # fuller one: in the 2026 export watch-history.html holds 2,800
            # rows against My Activity's 6,956, so taking watch-history on
            # sight would lose most of them. Keep whichever has more.
            if yt and _yt_watched(yt) <= _yt_watched([p for p in act if "YouTube" in p]):
                yt = []
            _takeout_activity(act, out, skip_youtube=bool(yt))
            _takeout_youtube(yt, out)
            # Chrome ships its history as History.json, not the documented name.
            _takeout_chrome(tfind(root, "BrowserHistory.json", "History.json"), out)
            _takeout_location(tfind(root, "Timeline.json", "location-history.json",
                                    "20??_*.json"), out)
            _takeout_play(tfind(root, "Installs.json", "Purchase History.json",
                                "Order History.json"), out)
            _takeout_fit(tfind(root, "Daily activity metrics.csv"), out)
            _takeout_places(tfind(root, "Saved Places.json", "Reviews.json"), out)
            return out
        paths = tfind(root, "MyActivity.json", "MyActivity.html", "My Activity.html",
                      "watch-history.json", "watch-history.html",
                      "BrowserHistory.json", "History.json",
                      "Timeline.json", "location-history.json", "20??_*.json",
                      "Installs.json",
                      "Purchase History.json", "Order History.json",
                      "Daily activity metrics.csv", "Saved Places.json", "Reviews.json")
        all_facts += cached("takeout-" + re.sub(r"[^\w.@-]", "_", label), paths, build)
    return all_facts


READERS = {"takeout": a_takeout}
LABELS = {'takeout': 'Activity read from Google Takeout exports.'}
