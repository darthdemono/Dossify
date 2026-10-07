"""Travel either side of a shift, from calendar events named 'Travel ...'.

Options: work_pattern, home_pattern, psql (command prefix), nextcloud_user, nextcloud_calendars, ics (list of {url_env | url_command})."""

import os, re, subprocess
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact, UTC
from zoneinfo import ZoneInfo

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


ICS_ANY = re.compile(r"^([A-Z][A-Z0-9-]*(?:;[^:]*)?):(.*)$")


def _ics_events(raw):
    """VEVENTs out of an ICS blob, unfolded, as plain dicts."""
    raw = raw.replace("\r\n ", "").replace("\n ", "").replace("\r\n", "\n")
    cur, out = None, []
    for line in raw.split("\n"):
        line = line.rstrip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur:
                out.append(cur)
            cur = None
        elif cur is not None:
            # Deliberately not ICS_LINE, which knows only four properties. The
            # key keeps its parameters so a TZID survives to the time parser.
            m = ICS_ANY.match(line.strip())
            if m:
                cur[m.group(1)] = m.group(2)
    return out


def _ics_get(e, name, default=""):
    for k, v in e.items():
        if k == name or k.startswith(name + ";"):
            return v
    return default


def _ics_local(value, key):
    """(date, HH:MM) from a DTSTART/DTEND value, honouring Z and TZID."""
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?)?", value.strip())
    if not m:
        return None, None
    if not m.group(4):
        return "-".join(m.group(1, 2, 3)), None
    parts = [int(x) for x in m.group(1, 2, 3, 4, 5)]
    if value.strip().endswith("Z"):
        loc = datetime(*parts, tzinfo=UTC).astimezone(J.TZ_DEFAULT)
    elif "TZID=" in key:
        try:
            loc = datetime(*parts, tzinfo=ZoneInfo(key.split("TZID=", 1)[1].split(";")[0]))
            loc = loc.astimezone(J.TZ_DEFAULT)
        except Exception:
            loc = datetime(*parts)
    else:
        loc = datetime(*parts)
    return loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M")


def _pat(key):
    """A configured regex, or one that never matches."""
    return re.compile(str(_O.get(key) or r"(?!x)x"), re.I)


def _travel_label(summary, location):
    """Which way the journey went, said the way he says it."""
    dest = re.sub(r"^Travel (?:to|home from)\s*", "", summary).strip()
    if summary.lower().startswith("travel home from") or _pat("home_pattern").search(dest):
        return "Work to Home"
    if _pat("work_pattern").search(dest):
        return "Home to Work"
    return "%s to %s" % (location.strip() or "Home", dest) if dest else None


def a_commute():
    """The journey either side of a shift, from the calendars that hold it.

    Nothing plans a route here. `tc` plans journeys and logs none, so a travel
    line exists only because an event for it exists: the Nextcloud `work`
    calendar for anything written since 08-09-2026, and the two Google
    calendars for everything before that.
    """
    blobs = []
    psql = list(_O.get("psql") or [])
    if psql and _O.get("nextcloud_calendars"):
        user = str(_O.get("nextcloud_user") or "admin").replace("'", "''")
        uris = ", ".join("'%s'" % str(c).replace("'", "''") for c in _O["nextcloud_calendars"])
        try:
            r = subprocess.run(
                psql + ["-tAc", "select convert_from(o.calendardata,'UTF8') from oc_calendarobjects o "
                                "join oc_calendars c on c.id=o.calendarid "
                                "where c.principaluri='principals/users/%s' and c.uri in (%s)" % (user, uris)],
                capture_output=True, text=True, timeout=60)
            if r.returncode == 0:
                blobs.append(r.stdout)
        except Exception:
            pass
    for number, feed in enumerate(_O.get("ics", [])):
        url = J.secret(feed, "url")
        if not url:
            continue
        cache = os.path.join(J.CACHE, "commute-calendar-%d.ics" % number)
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=60) as resp:
                raw = resp.read().decode("utf-8", "replace")
            os.makedirs(J.CACHE, exist_ok=True)
            open(cache, "w", encoding="utf-8").write(raw)
            blobs.append(raw)
        except Exception:
            if os.path.exists(cache):
                blobs.append(open(cache, encoding="utf-8").read())

    seen, out, best = set(), [], []
    today = datetime.now().strftime("%Y-%m-%d")
    for blob in blobs:
        for e in _ics_events(blob):
            summary = re.sub(r"\s+", " ", _ics_get(e, "SUMMARY")).strip()
            if not summary.lower().startswith("travel "):
                continue
            skey = next((k for k in e if k.startswith("DTSTART")), "DTSTART")
            ekey = next((k for k in e if k.startswith("DTEND")), "DTEND")
            date, start = _ics_local(_ics_get(e, "DTSTART"), skey)
            _d2, end = _ics_local(_ics_get(e, "DTEND"), ekey)
            if not date or not start or date > today:
                continue
            label = _travel_label(summary, _ics_get(e, "LOCATION"))
            if not label:
                continue
            span = "%s - %s" % (start, end) if end else start
            key = (date, span, label)
            if key in seen:
                continue
            seen.add(key)
            best.append((date, label,
                         _ics_get(e, "LAST-MODIFIED") or _ics_get(e, "DTSTAMP"), span))
    # A commute event gets rewritten when the route changes, and the old one is
    # not always deleted: 21-08-2026 carries both the dorm plan and the rail
    # route actually taken. One journey each way per day, so the newest record
    # of a direction wins.
    keep = {}
    for date, label, stamp, span in best:
        if label in ("Home to Work", "Work to Home"):
            k = (date, label)
            if k not in keep or stamp > keep[k][0]:
                keep[k] = (stamp, span)
        else:
            out.append(Fact(date, None, "%s (%s)" % (span, label), "commute"))
    for (date, label), (_stamp, span) in keep.items():
        out.append(Fact(date, None, "%s (%s)" % (span, label), "commute"))
    return out


READERS = {"commute": a_commute}
LABELS = {'commute': 'Journeys read from calendar events.'}
