#!/usr/bin/env python3
"""Build the #### Auto generated blocks in Journal/YYYY-MM.md from every source
that records what I did. Dry run by default; --apply writes.

Contract: everything between <!-- auto:begin DATE --> and <!-- auto:end --> is
owned by this script and rebuilt wholesale. Everything outside is the user's and
is never touched. Same for <!-- autoref:begin/end -->.

Design and the blind spots of each source: Journal/Auto Journal - Spec and Method.md
"""
import collections, csv, glob, html, importlib, io, json, os, re, sqlite3, subprocess, sys, tarfile, tempfile, zipfile
from collections import Counter, defaultdict, namedtuple
from datetime import datetime, timedelta, timezone as _tz
from pathlib import Path

from dossify import oslog
from dossify.people import journal_identity, load_people, normalize_identifier

try:
    from zoneinfo import ZoneInfo
    BUDAPEST = ZoneInfo("Europe/Budapest")
except Exception:
    BUDAPEST = _tz.utc
UTC = _tz.utc

HOME = os.path.expanduser("~")
BASE = ""
ARCHIVE = ""
RULES: dict[str, object] = {}
ACCOUNTS: dict[str, object] = {}
_IDENTITY: dict[str, object] | None = None
canvas_api = None


def configure(config) -> None:
    """Bind this generic engine to one private Dossify configuration."""
    global ARCHIVE, BASE, CACHE, RULES, SOURCES, ACCOUNTS, _IDENTITY, canvas_api
    global BANK_NAMES, SAVE_FILES, MY_CAMERAS, ME_NAMES, NOT_MINE, ANIK_ALBUM
    global DERIVED_NAME, CAMERA_NAME, EXPORT_ROOTS, EXPORT_PARTS, DHAKA, MOVE, KNOWN_PLACES
    global IG_TITLE_RENAMES, META_COMMUNITIES, META_NOISE_CHATS, GC_ROSTER_MAX, GC_INLINE_MAX
    global NEPTUN_EN, XIAOMI_BACKUP_DIR, XIAOMI_DASHBOARD_DIR, OS_LOG_DIR, CRASH_IGNORE
    if not config.output_dir or not config.journal.workspace_root:
        raise ValueError("dossify.toml needs output_dir and [journal].workspace_root")
    if not config.people_file or not config.journal.rules_file:
        raise ValueError("dossify.toml needs people_file and [journal].rules_file")
    BASE = str(config.output_dir.resolve())
    ARCHIVE = str(config.journal.workspace_root.resolve())
    CACHE = str((config.journal.cache_dir or Path(HOME, ".cache", "dossify")).resolve())
    with config.journal.rules_file.open(encoding="utf-8") as handle:
        RULES = json.load(handle)
    SOURCES = dict(RULES.get("source_descriptions") or {})
    ACCOUNTS = dict(RULES.get("accounts") or {})
    _IDENTITY = journal_identity(load_people(config.people_file))
    BANK_NAMES = [tuple(row) for row in RULES.get("bank_names") or []]
    SAVE_FILES = list(RULES.get("save_files") or [])
    photo = RULES.get("photo_policy") or {}
    MY_CAMERAS = dict(photo.get("my_cameras") or {})
    ME_NAMES = set(photo.get("self_names") or [])
    NOT_MINE = set(photo.get("not_mine_names") or [])
    ANIK_ALBUM = str(photo.get("special_album") or "")
    DERIVED_NAME = str(photo.get("derived_name_pattern") or r"$^")
    CAMERA_NAME = str(photo.get("camera_name_pattern") or r"$^")
    exports = RULES.get("exports") or {}
    EXPORT_ROOTS = list(exports.get("roots") or [])
    EXPORT_PARTS = dict(exports.get("parts") or {})
    move_utc = exports.get("move_utc")
    MOVE = datetime.fromisoformat(move_utc) if move_utc else None
    try:
        DHAKA = ZoneInfo(str(exports.get("before_move_timezone") or "UTC"))
    except Exception:
        DHAKA = UTC
    KNOWN_PLACES = [tuple(place) for place in exports.get("known_places") or []]
    social = RULES.get("social") or {}
    IG_TITLE_RENAMES = dict(social.get("instagram_title_renames") or {})
    META_COMMUNITIES = dict(social.get("communities") or {})
    META_NOISE_CHATS = list(social.get("noise_chats") or [])
    GC_ROSTER_MAX = int(social.get("roster_max") or 200)
    GC_INLINE_MAX = int(social.get("inline_max") or 6)
    paths = RULES.get("paths") or {}
    NEPTUN_EN = str(paths.get("neptun_ics") or "")
    XIAOMI_BACKUP_DIR = str(paths.get("xiaomi_backup_dir") or "")
    XIAOMI_DASHBOARD_DIR = str(paths.get("xiaomi_dashboard_dir") or "")
    OS_LOG_DIR = str(paths.get("os_log_dir") or "")
    CRASH_IGNORE = list((RULES.get("os_log") or {}).get("crash_ignore") or [])
    if config.journal.elteportal_path:
        sys.path.insert(0, str(config.journal.elteportal_path))
        canvas_api = importlib.import_module("elteportal.canvas")

Fact = namedtuple("Fact", "date time text src")


def rule_path(name: str) -> str:
    """Return one optional absolute private path from Journal Rules.json."""
    return str((RULES.get("paths") or {}).get(name) or "")

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# --------------------------------------------------------------------------
# footnote definitions, keyed by source
# --------------------------------------------------------------------------
SOURCES: dict[str, str] = {}
OS_LOG_DIR = ""
CRASH_IGNORE: list[str] = []


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

def money(n, cur="HUF"):
    if abs(n - round(n)) < 0.005:
        return "{:,} {}".format(int(round(n)), cur)
    return "{:,.2f} {}".format(n, cur)


# Both banks write a counterparty the way a terminal does, not the way a person
# would: routing prefixes, store numbers, a truncated merchant string, and
# Hungarian accents spelled as ASCII digraphs because the statement charset has
# none. A diary wants the name of the shop. Added 09-09-2026.
_BANK_ACCENTS = [("A'", "\u00c1"), ("E'", "\u00c9"), ("I'", "\u00cd"), ("O'", "\u00d3"),
                 ("U'", "\u00da"), ("O:", "\u00d6"), ("U:", "\u00dc"),
                 ('O"', "\u0150"), ('U"', "\u0170")]

BANK_NAMES: list[tuple[str, str]] = []


_CONTACTS = None


def contact_name(raw):
    """A counterparty that is a person, under the name his address book uses.

    Statements print people surname-first and inconsistently: `Singha
    Mrityunjoy` one month, `mrityunjoy singha` the next, `Akbar Zeeshan` for a
    card in the book as Zeeshan Akber. Matching on the export means a new
    friend needs no code change, and nobody gets renamed on a guess: every
    token has to line up, so a single shared first name never matches.
    """
    global _CONTACTS
    if _CONTACTS is None:
        _CONTACTS = []
        for f in sorted(glob.glob(os.path.join(ARCHIVE, "Contacts",
                                               "Nextcloud - Contacts Export*.csv")))[-1:]:
            try:
                for row in csv.DictReader(open(f, encoding="utf-8")):
                    name = (row.get("File As") or "").strip()
                    if name:
                        _CONTACTS.append((name, {t for t in re.findall(r"[a-z]+", name.lower())
                                                 if len(t) > 2}))
            except (OSError, ValueError):
                pass
    want = {t for t in re.findall(r"[a-z]+", (raw or "").lower()) if len(t) > 2}
    if len(want) < 2:
        return None
    for name, toks in _CONTACTS:
        if len(toks) < 2:
            continue
        if all(any(t.startswith(w) or w.startswith(t) for t in toks) for w in want):
            return name
    # Transliterated names differ by a letter between the bank and the book:
    # Akbar against Akber, Naznin against Nazneen. Compare the whole sorted
    # name and demand a very close match, so only a spelling gap is bridged.
    import difflib
    mine = " ".join(sorted(want))
    best, score = None, 0.0
    for name, toks in _CONTACTS:
        if len(toks) < 2 or len(toks) != len(want):
            continue
        r = difflib.SequenceMatcher(None, mine, " ".join(sorted(toks))).ratio()
        if r > score:
            best, score = name, r
    return best if score >= 0.88 else None


def bank_name(raw):
    """A counterparty as a person would say it, not as the terminal wrote it."""
    t = re.sub(r"\s+", " ", raw or "").strip(" ./")
    t = re.sub(r"^(PRCR|TRTR|CRTR|FTR|IB|VAT ON)[/ ]+", "", t, flags=re.I)
    t = re.sub(r"/(FCY|NO REMARKS.*|NO)\s*[\d.]*$", "", t).strip(" /")
    # an account number is not a counterparty and does not belong in a diary
    t = re.sub(r"\b\d{9,}\b", "", t).strip(" :/-")
    for a, b in _BANK_ACCENTS:
        t = t.replace(a, b)
    up = t.upper()
    for pat, name in BANK_NAMES:
        if re.search(pat, up):
            return name
    # Banks can write a transfer as `SENDER/RECIPIENT`. Try the whole string,
    # then each half, so a configured contact still resolves when order varies.
    person = contact_name(t)
    if not person:
        for part in re.split(r"\s*/\s*", t):
            person = contact_name(part)
            if person:
                break
    if person:
        return person
    t = re.sub(r"\s*\b\d{3,6}\b\s*", " ", t).strip()          # store numbers
    t = re.sub(r"\s+(KFT|ZRT|BT|LTD|LIMITED)\.?$", "", t, flags=re.I).strip()
    if t and t == t.upper() and len(t) > 3:
        t = t.title()
    return t or "an unnamed counterparty"


def a_erste():
    path = rule_path("erste_transactions_csv")
    if not os.path.exists(path):
        return []
    raw = open(path, encoding="utf-16").read()
    out = []
    for r in csv.DictReader(io.StringIO(raw)):
        tdt = (r.get("Transaction Date Time") or "").strip()
        book = (r.get("Booking Date") or "").strip()
        stamp = tdt or book
        m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\.?(?:\s+(\d{2}:\d{2}))?", stamp)
        if not m:
            continue
        date = "%s-%s-%s" % (m.group(1), m.group(2), m.group(3))
        time = m.group(4)
        try:
            amt = float((r.get("Amount") or "0").replace(",", ""))
        except ValueError:
            continue
        cur = (r.get("Currency") or "HUF").strip()
        who = (r.get("Partner Name") or "").strip()
        if not who:
            info = re.sub(r"\s+", " ", (r.get("Booking Info") or "").strip())
            who = info[:60] or (r.get("Transaction Type") or "").strip() or "unnamed transaction"
        # Erste puts the merchant in Partner Name for card purchases too, so
        # the transaction type is the only honest signal for at-a-shop.
        at_a_shop = "card" in (r.get("Transaction Type") or "").lower()
        who = bank_name(who)
        note = re.sub(r"\s+", " ", (r.get("Narrative") or "").strip())
        if amt < 0:
            text = "Paid %s %s %s" % (money(-amt, cur),
                                      "at" if at_a_shop else "to", who)
        else:
            text = "Received %s from %s" % (money(amt, cur), who)
        if note and len(note) <= 90:
            text += " (%s)" % note
        if not tdt:
            text += " [booking date only]"
        out.append(Fact(date, time, text, "erste"))
    return out


def a_git():
    roots = sorted(glob.glob(os.path.join(HOME, "Code", "*"))) + \
            [os.path.join(HOME, "docker"), os.path.join(HOME, "vps")]
    out = []
    for d in roots:
        if not os.path.isdir(os.path.join(d, ".git")):
            continue
        name = os.path.basename(d.rstrip("/"))
        try:
            log = subprocess.run(
                ["git", "-C", d, "log", "--no-merges",
                 "--pretty=%h%x1f%aI%x1f%an%x1f%ae%x1f%s"],
                capture_output=True, text=True, timeout=60).stdout
        except Exception:
            continue
        for line in log.splitlines():
            parts = line.split("\x1f")
            if len(parts) != 5:
                continue
            sha, iso, an, ae, subj = parts
            blob = (an + " " + ae).lower()
            author_terms = [str(term).casefold() for term in ACCOUNTS.get("git_author_terms", [])]
            if author_terms and not any(term in blob for term in author_terms):
                continue
            out.append(Fact(iso[:10], iso[11:16], "%s %s: %s" % (name, sha, subj), "git"))
    return out


def a_jellyfin():
    username = str(ACCOUNTS.get("jellyfin_username") or "")
    if not username:
        return []
    db = os.path.join(HOME, "docker", "jellyfin", "config", "data", "data", "jellyfin.db")
    if not os.path.exists(db):
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


SAVE_FILES = ["fromsoftware_combined.md", "sekiro_playthrough(combined).md"]
NODE = re.compile(r'\["\^(\d+) · ([^"<]*)((?:<br/>[^"]*?)*)"\]')
REF = re.compile(r'^\^(\d+): \[\[([^\]]+)\]\] — _(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})_')


def a_saves():
    root = "/mnt/nobara-data/Temp/DS Save Data"
    out = []
    for fn in SAVE_FILES:
        p = os.path.join(root, fn)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8").read()
        refs, game_of, cur_game = {}, {}, "FromSoftware"
        for line in text.split("\n"):
            m = REF.match(line)
            if m:
                refs[int(m.group(1))] = (m.group(3), m.group(4))
        for line in text.split("\n"):
            h = re.match(r"^## (.+?)(?: — .*)?$", line)
            if h and h.group(1) not in ("The Journey", "References", "Save Tree"):
                cur_game = h.group(1)
            for m in NODE.finditer(line):
                idx = int(m.group(1))
                game_of[idx] = cur_game
        # Delta is measured against the PREVIOUS save of the same character,
        # even when that save was written the day before, so a session is not
        # truncated to its within-day span.
        seen = {}
        for m in NODE.finditer(text):
            idx = int(m.group(1))
            if idx not in refs:
                continue
            seen[idx] = (refs[idx][0], refs[idx][1], game_of.get(idx, "FromSoftware"),
                         m.group(2).strip(), m.group(3))
        day = defaultdict(lambda: {"sec": 0, "n": 0, "last": "", "ev": []})
        prev = {}
        for idx in sorted(seen):
            date, time, game, clock, body = seen[idx]
            key = (date, game)
            cur = clock_secs(clock)
            before = prev.get(game)
            if cur is not None and before is not None and 0 < cur - before <= 12 * 3600:
                day[key]["sec"] += cur - before
            if cur is not None:
                prev[game] = cur
            day[key]["n"] += 1
            day[key]["last"] = max(day[key]["last"], time)
            for seg in body.split("<br/>"):
                seg = seg.strip()
                if seg.startswith(("BOSS:", "MINIBOSS:")):
                    day[key]["ev"].append(seg)
        for (date, game), d in day.items():
            bits = []
            if d["sec"]:
                bits.append("%d h %02d min played" % (d["sec"] // 3600, (d["sec"] % 3600) // 60))
            bits.append("%d save%s" % (d["n"], "" if d["n"] == 1 else "s"))
            for ev in dict.fromkeys(d["ev"]):
                bits.append(ev.replace("MINIBOSS:", "miniboss").replace("BOSS:", "boss")
                            .replace(" \u00b7 ", ", "))
            out.append(Fact(date, d["last"], "%s: %s" % (game, "; ".join(bits)), "saves"))
    return out


def clock_secs(s):
    m = re.match(r"^(\d+):(\d\d):(\d\d)$", s.strip())
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)) if m else None


def play_span(a, b):
    def secs(s):
        p = [int(x) for x in s.split(":")] if re.match(r"^\d+:\d\d:\d\d$", s) else None
        return p[0] * 3600 + p[1] * 60 + p[2] if p else None
    x, y = secs(a), secs(b)
    if x is None or y is None or y <= x:
        return None
    d = y - x
    return "%d h %02d min played" % (d // 3600, (d % 3600) // 60)


def a_worklog():
    """The shift itself. One line, the clock range and what it paid, with
    anything the table itself flags about the day nested under it."""
    p = rule_path("work_log")
    if not os.path.exists(p):
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
        head = "%s%s - HGL %s%s" % (
            span, "" if not span else "", get("Role"),
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
        loc = datetime(*parts, tzinfo=UTC).astimezone(BUDAPEST)
    elif "TZID=" in key:
        try:
            loc = datetime(*parts, tzinfo=ZoneInfo(key.split("TZID=", 1)[1].split(";")[0]))
            loc = loc.astimezone(BUDAPEST)
        except Exception:
            loc = datetime(*parts)
    else:
        loc = datetime(*parts)
    return loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M")


WORK_PLACE = re.compile(r"HGL|Magl\u00f3d", re.I)
HOME_PLACE = re.compile(r"K\u0151r\u00f6si Csoma|Erd\u0151s P\u00e1l|dormitory|kollégium|home", re.I)


def _travel_label(summary, location):
    """Which way the journey went, said the way he says it."""
    dest = re.sub(r"^Travel (?:to|home from)\s*", "", summary).strip()
    if summary.lower().startswith("travel home from") or HOME_PLACE.search(dest):
        return "Work to Home"
    if WORK_PLACE.search(dest):
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
    try:
        r = subprocess.run(
            ["docker", "exec", "nextcloud-db", "psql", "-U", "nextcloud", "-d", "nextcloud",
             "-tAc", "select convert_from(o.calendardata,'UTF8') from oc_calendarobjects o "
                     "join oc_calendars c on c.id=o.calendarid "
                     "where c.principaluri='principals/users/admin' "
                     "and c.uri in ('work','travel','personal')"],
            capture_output=True, text=True, timeout=60)
        if r.returncode == 0:
            blobs.append(r.stdout)
    except Exception:
        pass
    for var in ACCOUNTS.get("calendar_ics_env_vars", []):
        url = vault(var)
        if not url:
            continue
        cache = os.path.join(CACHE, "%s.ics" % var.lower())
        try:
            import urllib.request
            with urllib.request.urlopen(url, timeout=60) as resp:
                raw = resp.read().decode("utf-8", "replace")
            os.makedirs(CACHE, exist_ok=True)
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


def a_claude():
    out = []
    for d in sorted(glob.glob(os.path.join(HOME, ".claude", "projects", "*"))):
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            first, last, n, proj = None, None, 0, None
            try:
                for line in open(f, encoding="utf-8", errors="replace"):
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    proj = proj or rec.get("cwd")
                    ts = rec.get("timestamp")
                    if not ts:
                        continue
                    n += 1
                    first = first or ts
                    last = ts
            except Exception:
                continue
            if not first:
                continue
            label = os.path.basename(proj.rstrip("/")) if proj else os.path.basename(d)
            try:
                dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
            except Exception:
                continue
            out.append(Fact(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"),
                            "Claude session: %s (%d messages)" % (label, n), "claude"))
    return out



def vault(var):
    """Read one value out of the EnvVault timeconnect project. Never logged."""
    envv = os.path.join(HOME, "Code", "EnvVault", "target", "release", "envv")
    if not os.path.exists(envv):
        return None
    env = dict(os.environ, ENVV_SERVER_URL=os.environ.get("ENVV_SERVER_URL", "http://localhost:8743"))
    if "ENVV_PASSWORD" not in env:
        try:
            for line in open(os.path.join(HOME, "docker", ".env"), encoding="utf-8"):
                if line.startswith("ENVV_PASSWORD="):
                    env["ENVV_PASSWORD"] = line.split("=", 1)[1].strip()
                    break
        except OSError:
            return None
    try:
        r = subprocess.run([envv, "exec", "--project", "timeconnect", "--", "printenv", var],
                           capture_output=True, text=True, timeout=60, env=env)
    except Exception:
        return None
    v = r.stdout.strip()
    return v or None


def vault_entry(spec, var):
    """Read one entry field out of EnvVault, e.g. vault_entry("Simkl", "api_key")."""
    envv = os.path.join(HOME, "Code", "EnvVault", "target", "release", "envv")
    if not os.path.exists(envv):
        return None
    env = dict(os.environ, ENVV_SERVER_URL=os.environ.get("ENVV_SERVER_URL", "http://localhost:8743"))
    if "ENVV_PASSWORD" not in env:
        try:
            for line in open(os.path.join(HOME, "docker", ".env"), encoding="utf-8"):
                if line.startswith("ENVV_PASSWORD="):
                    env["ENVV_PASSWORD"] = line.split("=", 1)[1].strip()
                    break
        except OSError:
            return None
    try:
        r = subprocess.run([envv, "exec", "--entry", "%s=SECRET:%s" % (spec, var),
                            "--", "printenv", "SECRET"],
                           capture_output=True, text=True, timeout=60, env=env)
    except Exception:
        return None
    return r.stdout.strip() or None


BRAC_DATE = re.compile(r"^\s*(\d{2})-([A-Za-z]{3})-(\d{4})\s+(.*)$")
MON = {m: i + 1 for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"])}


def a_brac():
    out = []
    statements_dir = rule_path("brac_statements_dir")
    if not statements_dir:
        return out
    for pdf in sorted(glob.glob(os.path.join(statements_dir, "*.pdf"))):
        try:
            txt = subprocess.run(["pdftotext", "-layout", pdf, "-"],
                                 capture_output=True, text=True, timeout=120).stdout
        except Exception:
            continue
        prev_bal, pending = None, None

        def flush(p):
            if not p:
                return
            date, desc, amt, bal, extra = p
            kind = "paid"
            if prev_bal is not None and bal is not None and bal > prev_bal:
                kind = "received"
            at_a_shop = bool(re.match(r"^PRCR[/ ]", desc.strip()))
            desc = bank_name(desc)
            if kind == "received":
                text = "Received %s BDT from %s" % ("{:,.0f}".format(amt), desc)
            else:
                text = "Paid %s BDT %s %s" % ("{:,.0f}".format(amt),
                                              "at" if at_a_shop else "to", desc)
            if extra:
                text += " (%s HUF as charged)" % "{:,.0f}".format(extra)
            out.append(Fact(date, None, text, "brac"))

        for line in txt.split("\n"):
            m = BRAC_DATE.match(line)
            if m:
                if prev_bal is None or pending:
                    pass
                nums = re.findall(r"(-?[\d,]+\.\d{2})", m.group(4))
                if len(nums) >= 2:
                    amt = abs(float(nums[-2].replace(",", "")))
                    bal = float(nums[-1].replace(",", ""))
                    desc = m.group(4)[:m.group(4).find(nums[-2])].strip()
                    date = "%s-%02d-%s" % (m.group(3), MON.get(m.group(2).title(), 1), m.group(1))
                    flush(pending)
                    prev_bal = pending[3] if pending else prev_bal
                    pending = (date, desc, amt, bal, None)
                continue
            v = re.match(r"^\s*([\d,]+\.\d{2})\s*$", line)
            if v and pending and pending[4] is None:
                pending = pending[:4] + (float(v.group(1).replace(",", "")),)
        flush(pending)
    # a re-downloaded statement overlaps the previous one
    return list(dict.fromkeys(out))


def a_docs():
    folders = ["Invoices & Receipts", "Email Receipts", "Contracts", "Travel & Tickets",
               "Bank Statements", "Medical", "Education/Courses", "Products",
               "Identity & Residency", "Financial & Sponsorship", "Employment"]
    seen, byday = set(), defaultdict(set)
    today = datetime.now().strftime("%Y-%m-%d")
    for rel in folders:
        for path in glob.glob(os.path.join(ARCHIVE, rel, "**", "*"), recursive=True):
            if not os.path.isfile(path):
                continue
            name = os.path.basename(path)
            if name.startswith(".") or "/backup/" in path:
                continue
            cands = []
            for mm in re.finditer(r"\b([0-3]\d)-([01]\d)-(20\d\d)\b", name):
                d = "%s-%s-%s" % (mm.group(3), mm.group(2), mm.group(1))
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    continue
                if d <= today:                      # a filed document is never future-dated
                    cands.append(d)
            if not cands:
                continue
            date = cands[-1]
            stem, ext = os.path.splitext(name)
            # Obsidian resolves a Markdown note without its extension; everything
            # else needs the real one to point at the actual file.
            link = stem if ext.lower() == ".md" else name
            if (date, link) in seen:
                continue
            seen.add((date, link))
            byday[date].add(link)
    out = []
    for date, links in byday.items():
        kids = "\n".join("    - [[%s]]" % l for l in sorted(links))
        out.append(Fact(date, None, "Today's documents:\n" + kids, "docs"))
    return out


def a_simkl():
    facts = _simkl_api()
    return facts if facts else _simkl_csv()


def _simkl_csv():
    p = rule_path("simkl_backup_csv")
    if not os.path.exists(p):
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
    cid = vault_entry("Simkl", "api_key")
    tokfile = os.path.join(HOME, ".config", "simkl-import", "token.json")
    if not cid or not os.path.exists(tokfile):
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
            return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(BUDAPEST)
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


# My own handsets, keyed by the EXIF model string. The value is the name I would
# actually say out loud, which is what goes in the journal line.
MY_CAMERAS: dict[str, str] = {}
ME_NAMES: set[str] = set()
NOT_MINE: set[str] = set()
ANIK_ALBUM = ""
DERIVED_NAME = r"$^"
CAMERA_NAME = r"$^"

def a_immich():
    """Photos that are actually mine: any picture of me whatever took it, plus
    anything shot on one of my own handsets. A bare per-day count of the whole
    library says nothing about whose photos they are, so it is not used."""
    sql = """
        select to_char(a."fileCreatedAt", 'YYYY-MM-DD'),
               coalesce(e.city, ''),
               coalesce(e.model, ''),
               (select count(*) from album_asset aa
                  join album al on al.id = aa."albumId"
                 where aa."assetId" = a.id and al."albumName" = $ANIK$),
               coalesce(string_agg(distinct p.name, '|')
                        filter (where coalesce(p.name,'') <> ''), '')
        from asset a
             left join asset_exif e on e."assetId" = a.id
             left join asset_face f on f."assetId" = a.id
             -- Immich 2.x associates faces and people through person groups,
             -- rather than the removed asset_face.personId / person.id pair.
             left join person p on p."personGroupId" = f."personGroupId"
        where a."deletedAt" is null
          -- ONLY ORIGINALS. Anything a messenger, a social app or an editor wrote to
          -- disk is either somebody else's picture or a second copy of one I already
          -- have. Two tests: the name must not look derived, and the file must carry
          -- a camera model or be named the way a camera names things, which keeps
          -- video, whose EXIF rarely records the model.
          and a."originalFileName" !~* $DERIVED$
          and (coalesce(e.model, '') <> '' or a."originalFileName" ~* $CAMNAME$)
        group by a.id, 1, 2, 3
    """
    for token, value in (("$ANIK$", ANIK_ALBUM), ("$DERIVED$", DERIVED_NAME),
                         ("$CAMNAME$", CAMERA_NAME)):
        sql = sql.replace(token, "'" + value.replace("'", "''") + "'")
    try:
        r = subprocess.run(["docker", "exec", "immich-db", "psql", "-U", "immich",
                            "-d", "immich", "-tAF", "\x1f", "-c", sql],
                           capture_output=True, text=True, timeout=300)
    except Exception:
        return []

    groups = defaultdict(int)
    for line in r.stdout.strip().split("\n"):
        parts = line.split("\x1f")
        if len(parts) < 5 or not re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]):
            continue
        date, city, model, anik, people = parts[0], parts[1].strip(), parts[2].strip(), parts[3], parts[4]
        names = [n for n in people.split("|") if n]
        if names and set(names) <= NOT_MINE:
            continue
        names = [n for n in names if n not in NOT_MINE]
        mine_by_camera = model in MY_CAMERAS
        has_me = bool(ME_NAMES.intersection(names))
        if not mine_by_camera and not has_me:
            continue
        if anik not in ("0", ""):
            # some EXIF model strings list every badge the body ever shipped under
            short = model.split(" / ")[0].strip()
            shot_by = "Anik (%s)" % (short or "camera not recorded")
        elif mine_by_camera:
            shot_by = "my %s" % MY_CAMERAS[model]
        else:
            shot_by = model or ""
        others = tuple(sorted(n for n in names if n not in ME_NAMES))
        groups[(date, others, city, shot_by, has_me)] += 1

    perday = defaultdict(list)
    for (date, others, city, shot_by, has_me), n in groups.items():
        if others and has_me:
            who = "with me and " + _and(others)
        elif others:
            who = "with " + _and(others)
        elif has_me:
            who = "of me"
        else:
            who = ""
        head = ("Picture %s" % who if n == 1 else "%d pictures %s" % (n, who)).strip()
        if city:
            head = ("%s in %s" % (head, city)) if not who else ("%s, in %s" % (head, city))
        perday[date].append("%s, taken by %s" % (head, shot_by) if shot_by else head)

    # A day can hold several distinct groups of photographs and none of them carries
    # a clock, so they would sit in a row looking like separate events. One parent
    # bullet with the groups nested under it reads as what it is: the day's pictures.
    out = []
    for date, lines in perday.items():
        if len(lines) == 1:
            out.append(Fact(date, None, lines[0], "immich"))
        else:
            kids = "\n".join("    - %s" % l for l in sorted(lines))
            out.append(Fact(date, None, "Pictures taken:\n" + kids, "immich"))
    return out


def _and(names):
    names = list(names)
    if len(names) == 1:
        return names[0]
    if len(names) <= 4:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names[:3]) + " and %d others" % (len(names) - 3)


ICS_LINE = re.compile(r"^(DTSTART|SUMMARY|LOCATION|DTEND)[^:]*:(.*)$")


# The raw Neptun feed is Hungarian. TimeConnect's tc-feeds timer rewrites it to
# ELTE's own English course names and drops the result here; read that, never the
# raw feed, or every lecture lands in the journal as "Egyetemi alapozo ...".
NEPTUN_EN = ""

def a_neptun():
    # No fallback to the raw feed on purpose. If the rewriter has not run, emit
    # nothing rather than fill the journal with Hungarian course titles that a
    # later run would have to undo.
    if not os.path.exists(NEPTUN_EN):
        print("  neptun: %s missing - run `python -m timeconnect.feeds neptun`" % NEPTUN_EN)
        return []
    raw = open(NEPTUN_EN, encoding="utf-8", errors="replace").read()
    raw = raw.replace("\r\n ", "").replace("\n ", "")
    out, cur = [], {}
    today = datetime.now().strftime("%Y-%m-%d")
    for line in raw.split("\n"):
        line = line.strip()
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            st, sm = cur.get("DTSTART", ""), cur.get("SUMMARY", "")
            m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", st)
            if m and sm:
                if m.group(4) and st.rstrip().endswith("Z"):
                    utc = datetime(*(int(x) for x in m.group(1, 2, 3, 4, 5)), tzinfo=UTC)
                    loc = utc.astimezone(BUDAPEST)
                    date, time = loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M")
                else:
                    date = "-".join(m.group(1, 2, 3))
                    time = "%s:%s" % (m.group(4), m.group(5)) if m.group(4) else None
                if date > today:
                    continue
                loc = cur.get("LOCATION", "").strip()
                out.append(Fact(date, time, "Scheduled: %s%s" % (
                    sm.strip(), " (%s)" % loc if loc else ""), "neptun"))
        else:
            m = ICS_LINE.match(line)
            if m:
                cur[m.group(1)] = m.group(2)
    return out


def _canvas_courses(key):
    """Active and finished both. Reading only the active ones loses every past
    semester, which is most of the record."""
    try:
        rows = canvas_api.courses(key, states=("active", "completed"))
    except canvas_api.CanvasError:
        return []
    return [(course["id"], (course.get("name") or "").strip()) for course in rows]


def _canvas_assignments(key, cid):
    try:
        return canvas_api.assignments_with_submission(key, cid)
    except canvas_api.CanvasError:
        return []


def a_canvas():
    key = vault("CANVAS_API_KEY")
    if not key:
        return []
    out = []
    for cid, cname in _canvas_courses(key):
        for a in _canvas_assignments(key, cid):
            sub = a.get("submission") or {}
            date, time = iso_local(sub.get("submitted_at"))
            if not date:
                continue
            out.append(Fact(date, time, "Submitted on Canvas: %s (%s)" % (
                a.get("name", "?"), cname), "canvas"))
    return list(dict.fromkeys(out))


def _num(v):
    """Canvas hands back 0.659047619047619. Nobody writes that in a diary."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if abs(f - round(f)) < 1e-9 else round(f, 2)


def a_grades():
    """What came back, as opposed to what was handed in. A grade landing is a
    dated event; the mark itself is not, which is why `graded_at` is used and
    not the assignment's due date."""
    key = vault("CANVAS_API_KEY")
    if not key:
        return []
    out = []
    for cid, cname in _canvas_courses(key):
        for a in _canvas_assignments(key, cid):
            sub = a.get("submission") or {}
            date, time = iso_local(sub.get("graded_at"))
            score = _num(sub.get("score"))
            if not date or score is None:
                continue
            top = _num(a.get("points_possible"))
            mark = "%s/%s" % (score, top) if top else str(score)
            out.append(Fact(date, time, "Canvas grade: %s, %s (%s)" % (
                a.get("name", "?"), mark, cname), "grades"))
    return list(dict.fromkeys(out))


LASTFM_CACHE = os.path.join(HOME, ".cache", "journal-auto", "lastfm.json")


def a_lastfm():
    key = vault_entry("Last.fm", "api_key")
    username = str(ACCOUNTS.get("lastfm_user") or "")
    if not username:
        return []
    import urllib.request, urllib.parse
    rows = []
    if os.path.exists(LASTFM_CACHE):
        try:
            rows = json.load(open(LASTFM_CACHE, encoding="utf-8"))
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
            os.makedirs(os.path.dirname(LASTFM_CACHE), exist_ok=True)
            json.dump(rows, open(LASTFM_CACHE, "w", encoding="utf-8"))
    if not rows:
        return []

    byday = defaultdict(list)
    for r in rows:
        dt = datetime.fromtimestamp(r["uts"], UTC).astimezone(BUDAPEST)
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


# --------------------------------------------------------------------------
# bulk exports: Google Takeout, Instagram, Facebook
#
# These read extracted archives sitting outside this repository, because a
# Takeout runs to tens of gigabytes and carries whole mailboxes. Nothing is
# copied into the archive. When no export is present every adapter returns
# nothing and says so. Layout, request options and blind spots:
# Journal/Export Ingest - Google Takeout and Meta.md
# --------------------------------------------------------------------------

EXPORT_ROOTS: list[str] = []
EXPORT_PARTS: dict[str, bool] = {}
try:
    DHAKA = ZoneInfo("Asia/Dhaka")
except Exception:
    DHAKA = UTC
MOVE: datetime | None = None
KNOWN_PLACES: list[tuple[float, float, float, str]] = []

def exports_roots():
    """Every export root that exists, in order of preference.

    More than one is normal and deliberate. The Facebook export and the Takeouts
    sit on the 12 TB disk; the Instagram export was put on the internal drive on
    11-09-2026 after that disk started resetting its SATA link mid-extraction. An
    adapter looks through all of them and goes quiet for whatever is missing, so
    a disk that is unplugged, unmounted or having a bad day costs exactly the
    lines it holds and nothing else.
    """
    seen, out = set(), []
    for r in EXPORT_ROOTS:
        if r and os.path.isdir(r) and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def exports_root():
    roots = exports_roots()
    return roots[0] if roots else None


def local_of(dt):
    """A UTC datetime as (date, HH:MM) in the timezone he was actually in."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    loc = dt.astimezone(BUDAPEST if MOVE is None or dt >= MOVE else DHAKA)
    return loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M")


def epoch_local(sec):
    try:
        return local_of(datetime.fromtimestamp(float(sec), UTC))
    except (ValueError, OverflowError, OSError, TypeError):
        return None, None


def iso_local(s):
    try:
        return local_of(datetime.fromisoformat(str(s).replace("Z", "+00:00")))
    except ValueError:
        return None, None


CACHE = os.path.join(HOME, ".cache", "journal-auto")
# The cache is keyed on the export files, so a change to the parsers would not
# invalidate it on its own. Bump this whenever an export adapter's output changes.
CACHE_VERSION = 25


def cached(tag, paths, build):
    """Memoise an adapter's facts against the size and mtime of its inputs.

    A single MyActivity.json runs to hundreds of megabytes, so a full run must
    not re-parse an export that has not changed since the last one.
    """
    paths = sorted(paths)
    if not paths:
        return []
    try:
        key = json.dumps([CACHE_VERSION] +
                         [[p, os.path.getsize(p), int(os.path.getmtime(p))] for p in paths])
    except OSError:
        return build(paths)
    store = os.path.join(CACHE, "export-%s.json" % tag)
    try:
        blob = json.load(open(store, encoding="utf-8"))
        if blob.get("key") == key:
            return [Fact(*row) for row in blob["facts"]]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    facts = build(paths)
    try:
        os.makedirs(CACHE, exist_ok=True)
        json.dump({"key": key, "facts": [list(f) for f in facts]},
                  open(store, "w", encoding="utf-8"))
    except OSError:
        pass
    return facts


def cached_obj(tag, paths, build):
    """Same memoisation as cached(), for an adapter whose result is a plain
    JSON structure rather than a flat list of facts. The Meta adapters need it
    because they carry group-chat rosters out alongside their facts, and a
    cache hit that dropped the rosters would empty the section at the bottom
    of every month file."""
    paths = sorted(paths)
    if not paths:
        return build(paths)
    try:
        key = json.dumps([CACHE_VERSION] +
                         [[p, os.path.getsize(p), int(os.path.getmtime(p))] for p in paths])
    except OSError:
        return build(paths)
    store = os.path.join(CACHE, "export-%s.json" % tag)
    try:
        blob = json.load(open(store, encoding="utf-8"))
        if blob.get("key") == key:
            return blob["data"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    data = build(paths)
    try:
        os.makedirs(CACHE, exist_ok=True)
        json.dump({"key": key, "data": data}, open(store, "w", encoding="utf-8"))
    except OSError:
        pass
    return data


def jload(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def plural(n, one, many=None):
    return "%d %s" % (n, one if n == 1 else (many or one + "s"))


def top_counts(counter, k=3):
    return ", ".join("%s (%d)" % (name, n) for name, n in counter.most_common(k))


def nest(date, head, lines, src, time=None):
    """One parent bullet with children, or a flat bullet when there is one."""
    if not lines:
        return None
    if len(lines) == 1:
        m = re.match(r"^(\d{2}:\d{2}) \u00b7 (.*)$", lines[0])
        if m:
            return Fact(date, time or m.group(1), "%s: %s" % (head.rstrip(":"), m.group(2)), src)
        return Fact(date, time, "%s: %s" % (head.rstrip(":"), lines[0]), src)
    kids = "\n".join("    - %s" % l for l in lines)
    return Fact(date, time, head + "\n" + kids, src)


# ---------------------------------------------------------------- Takeout ---

def takeout_accounts():
    """(label, root) for every extracted Takeout under any export root."""
    out = []
    for d in sorted(d for root in exports_roots()
                    for d in glob.glob(os.path.join(root, "google-takeout", "*"))):
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
    for plat, plng, km, name in KNOWN_PLACES:
        # a degree of latitude is 111 km; longitude is narrowed by the cosine
        # of the latitude, which at Budapest is close enough to 0.675
        dy = (lat - plat) * 111.0
        dx = (lng - plng) * 111.0 * 0.675
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
# Budapest's real DST, so the label is read literally rather than resolved
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
        if EXPORT_PARTS["search_text"]:
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
            if EXPORT_PARTS["browser_urls"]:
                lines = ["%s (%d)" % (k, v) for k, v in c.most_common(20)]
                f = nest(date, "Browsed:", lines, "takeout")
                if f:
                    out.append(f)
            # No line at all when only the count survives; see above.


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


# ------------------------------------------------------------------- Meta ---

def meta_text(s):
    """Meta writes UTF-8 bytes through latin-1, so every accent arrives broken."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def meta_root(kind):
    """The extracted Instagram or Facebook export, found by its marker folder.

    Searched across every export root, because the two exports do not have to
    live on the same disk.
    """
    marker = "your_%s_activity" % kind
    for root in exports_roots():
        cands = sorted(glob.glob(os.path.join(root, "meta", "*")))
        cands += sorted(glob.glob(os.path.join(root, "meta", "*", "*")))
        for d in cands:
            if not os.path.isdir(d):
                continue
            if os.path.isdir(os.path.join(d, marker)) or os.path.isdir(
                    os.path.join(d, "personal_information")) and kind in os.path.basename(d).lower():
                return d
    return None


TS_KEYS = ("timestamp", "creation_timestamp", "start_timestamp", "timestamp_ms",
           "verification_time", "date_added")


def meta_walk(node, depth=0):
    """Yield (epoch, label) for every dated record anywhere in a Meta JSON file.

    Meta reshuffles these files between exports, so nothing here matches on a
    path. It matches on the shape: a dict carrying one of the timestamp keys.
    """
    if depth > 12:
        return
    if isinstance(node, list):
        for x in node:
            for r in meta_walk(x, depth + 1):
                yield r
        return
    if not isinstance(node, dict):
        return
    ts = None
    for k in TS_KEYS:
        if isinstance(node.get(k), (int, float)) and node[k]:
            ts = node[k] / 1000.0 if k == "timestamp_ms" else node[k]
            break
    smd = node.get("string_map_data")
    if ts is None and isinstance(smd, dict):
        for v in smd.values():
            if isinstance(v, dict) and v.get("timestamp"):
                ts = v["timestamp"]
                break
    if ts:
        label = ""
        for k in ("title", "name", "value", "sender_name"):
            if isinstance(node.get(k), str) and node[k].strip():
                label = meta_text(node[k].strip())
                break
        if not label and isinstance(smd, dict):
            for k in ("Name", "Title", "Comment", "Search"):
                v = smd.get(k)
                if isinstance(v, dict) and isinstance(v.get("value"), str):
                    label = meta_text(v["value"])
                    break
        yield ts, label
        return
    for v in node.values():
        for r in meta_walk(v, depth + 1):
            yield r


def _meta_posts(path, service, out, verb="Posted on"):
    data = jload(path)
    rows = data if isinstance(data, list) else []
    if isinstance(data, dict):
        for k in ("ig_stories", "ig_reels_media", "ig_archived_post_media",
                  "ig_other_media", "photos", "videos"):
            if isinstance(data.get(k), list):
                rows = data[k]
                break
    for e in rows:
        if not isinstance(e, dict):
            continue
        ts = e.get("creation_timestamp") or e.get("timestamp")
        media = e.get("media") or []
        if not ts and media and isinstance(media[0], dict):
            ts = media[0].get("creation_timestamp")
        if not ts:
            continue
        date, time = epoch_local(ts)
        if not date:
            continue
        cap = meta_text(e.get("title") or "")
        if not cap and media and isinstance(media[0], dict):
            cap = meta_text(media[0].get("title") or "")
        for d in (e.get("data") or []):
            if isinstance(d, dict) and d.get("post"):
                cap = meta_text(d["post"])
        cap = re.sub(r"\s+", " ", cap).strip()
        if len(cap) > 90:
            cap = cap[:87].rstrip() + "..."
        n = len(media) if isinstance(media, list) else 0
        what = "%s %s" % (verb, service)
        if n > 1:
            what += " (%d items)" % n
        out.append(Fact(date, time, "%s%s" % (what, ": " + cap if cap else ""),
                        service.lower()))


def _meta_places(path, service, out):
    """Check-ins, which live inside Facebook posts as an attachment."""
    data = jload(path)
    for e in data if isinstance(data, list) else []:
        if not isinstance(e, dict):
            continue
        date, time = epoch_local(e.get("timestamp"))
        if not date:
            continue
        for att in (e.get("attachments") or []):
            for d in (att.get("data") or []) if isinstance(att, dict) else []:
                place = (d or {}).get("place")
                if isinstance(place, dict) and place.get("name"):
                    out.append(Fact(date, time, "Checked in at %s" % meta_text(place["name"]),
                                    service.lower()))


# Instagram is a handle-first place: the display name on a thread is whatever
# the person felt like that week, and @handle is the thing that identifies
# them. So every Instagram person in this journal is written as a handle where
# one can be resolved. Messenger has no handles, so Facebook keeps names.
# His rules, 11-09-2026.
IG_TITLE_RENAMES: dict[str, str] = {}
META_COMMUNITIES: dict[str, str] = {}
GC_ROSTER_MAX = 200
GC_INLINE_MAX = 6

# Filled by the Meta adapters, read by the month writer for the roster section.
# Keyed "<service>\t<title>" so the two services cannot collide on a title.
GC_ROSTERS = {}
GC_DAYS = defaultdict(set)


def meta_handles(root):
    """Display name -> Instagram handle.

    Built from every place the export happens to print the two together: notes
    and reposts, suggested profiles, the advertiser tables. There is no
    name-to-handle file in the download, and the thread folder name is the
    title with its punctuation stripped rather than a username, so this is the
    only route. A name resolving to more than one handle is dropped rather
    than guessed at.
    """
    pairs = defaultdict(set)

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, list):
            for x in node:
                walk(x, depth + 1)
            return
        if not isinstance(node, dict):
            return
        lv = node.get("dict")
        if isinstance(lv, list):
            d = {}
            for e in lv:
                if isinstance(e, dict) and "label" in e:
                    d[e["label"]] = e.get("value")
            if d.get("Name") and d.get("Username"):
                pairs[meta_text(d["Name"])].add(d["Username"])
        for v in node.values():
            walk(v, depth + 1)

    paths = [q for q in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
             if os.sep + "messages" + os.sep not in q]

    def build(ps):
        for q in ps:
            walk(jload(q))
        return dict((k, sorted(v)[0]) for k, v in pairs.items() if len(v) == 1)

    return cached_obj("ig-handles", paths, build)


def meta_self(root, kind):
    """His own name as this export writes it, so he is never listed among the
    members of his own group chats."""
    if kind == "instagram":
        for q in glob.glob(os.path.join(root, "**", "personal_information.json"),
                           recursive=True):
            for u in ((jload(q) or {}).get("profile_user") or []):
                v = ((u.get("string_map_data") or {}).get("Name") or {}).get("value")
                if v:
                    return meta_text(v)
    for q in glob.glob(os.path.join(root, "**", "profile_information.json"), recursive=True):
        n = ((jload(q) or {}).get("profile_v2") or {}).get("name") or {}
        if n.get("full_name"):
            return meta_text(n["full_name"])
    return ""


def identity():
    """The in-memory projection of the private People.json file."""
    if _IDENTITY is None:
        raise RuntimeError("journal engine has not been configured")
    return _IDENTITY


_HANDLE_BY_CARD = None


def handle_by_card():
    """Return only an unambiguous Instagram handle for a card.

    A card can legitimately own several accounts. Choosing the first JSON key
    made an unrelated alias appear in journal rows whose display name supplied
    no handle, so multi-account cards deliberately have no generic fallback.
    """
    global _HANDLE_BY_CARD
    if _HANDLE_BY_CARD is None:
        choices = defaultdict(set)
        for h, card in (identity().get("by_ig_handle") or {}).items():
            choices[card].add(h)
        _HANDLE_BY_CARD = {card: next(iter(handles)) for card, handles in choices.items()
                           if len(handles) == 1}
    return _HANDLE_BY_CARD


def handle_for_display(card, display):
    """Return the explicit account paired with this display name, if any."""
    choices = {
        row.get("handle")
        for person in (identity().get("people") or [])
        if person.get("name") == card
        for row in (person.get("instagram") or [])
        if row.get("display") and normalize_identifier(row["display"]) == normalize_identifier(display)
        and row.get("handle")
    }
    return next(iter(choices)) if len(choices) == 1 else None


def identity_match(key, value):
    """Look up a People.json identity without broadening the spelling match."""
    ident = identity()
    normalized = ident.get(key + "_normalized")
    if normalized is not None:
        return normalized.get(normalize_identifier(value))
    # Compatibility for an in-memory projection created by a pre-1.0.1 engine.
    return (ident.get(key) or {}).get(value)


def meta_person(name, handles, service="Instagram", full=True):
    """One person as a journal line should name them.

    `@handle (Real Name)` where both are known, and whichever one is known
    otherwise. Group-chat inline lists use the same `@handle (Real Name)`
    spelling.
    """
    ident = identity()
    key = "by_ig_display" if service == "Instagram" else "by_fb_name"
    card = identity_match(key, name)
    h = handles.get(name) if handles else None
    if card is None and service == "Instagram":
        # Some threads are titled with the username rather than a display name,
        # so the display lookup misses somebody the map does know by handle.
        probe = h or re.sub(r"^@", "", name.strip())
        card = identity_match("by_ig_handle", probe)
        if card and not h:
            h = probe
    if card and not h and service == "Instagram":
        # Prefer the handle explicitly paired with this display name. A card
        # with several Instagram accounts must not leak an arbitrary alias
        # into another account's thread; only a one-account card can fall back.
        h = handle_for_display(card, name) or handle_by_card().get(card)
    if h and card:
        return "@%s (%s)" % (h, card)
    if h:
        return "@" + h
    return card or name


def meta_title(title, service):
    """The chat as it should read: renamed where he has renamed it, and under
    its community where it belongs to one."""
    t = IG_TITLE_RENAMES.get(title, title) if service == "Instagram" else title
    com = META_COMMUNITIES.get(t)
    if not com or t.startswith(com):
        # `EPK - Kondi / Gym` already says which community it belongs to, and
        # `EPK/EPK - Kondi / Gym` says it twice.
        return t
    return "%s/%s" % (com, t)


# Broadcast groups he was added to rather than conversations he had. The web
# design course group alone put 94 lines across ten months, and its title
# carries a tick and a pair of pipes that break the Markdown around them.
META_NOISE_CHATS: list[str] = []

def meta_noise(title):
    return any(re.search(pat, title or "") for pat in META_NOISE_CHATS)


def _meta_messages(root, service, out, handles=None, rosters=None, gcdays=None):
    """Counts only. No text ever leaves these files, and the thread name only
    when message_threads is on, because the other half of a chat is not mine."""
    if rosters is None:
        rosters = {}
    if gcdays is None:
        gcdays = defaultdict(set)
    if not EXPORT_PARTS["message_threads"] and not EXPORT_PARTS["message_text"]:
        threads = glob.glob(os.path.join(root, "**", "messages", "**", "message_*.json"),
                            recursive=True)
        byday = defaultdict(lambda: [0, set()])
        for p in threads:
            data = jload(p)
            for m in ((data or {}).get("messages") or []):
                date, _ = epoch_local((m.get("timestamp_ms") or 0) / 1000.0)
                if date:
                    byday[date][0] += 1
                    byday[date][1].add(p)
        for date, (n, ps) in byday.items():
            out.append(Fact(date, None, "%s: %s across %s" % (
                service, plural(n, "message"), plural(len(ps), "chat")), service.lower()))
        return
    # Who he texted and when he started, not how many messages went back and
    # forth. "441 messages across 6 chats" is a tally; "texted Hanna at 09:15"
    # is a thing he did. The message count is deliberately not carried.
    where = "Messenger" if service == "Facebook" else service
    me = meta_self(root, "facebook" if service == "Facebook" else "instagram")
    byday = defaultdict(dict)
    calls = defaultdict(list)
    for p in glob.glob(os.path.join(root, "**", "messages", "**", "message_*.json"),
                       recursive=True):
        data = jload(p)
        raw = meta_text((data or {}).get("title") or os.path.basename(os.path.dirname(p)))
        if meta_noise(raw):
            continue
        # Participants are everyone still on the thread minus himself, so a
        # two-name chat is a conversation and anything above that is a group.
        members = [meta_text(x.get("name") or "")
                   for x in ((data or {}).get("participants") or [])]
        members = [x for x in members if x.strip() and x != me]
        group = len(members) > 1
        if not raw.strip():
            # A thread whose title is blank or invisible characters. The person
            # on the other end names it better than an empty bullet does.
            raw = members[0] if len(members) == 1 else os.path.basename(os.path.dirname(p))
        title = meta_title(raw, service)
        key = "%s\t%s" % (service, title)
        if group and len(members) < GC_ROSTER_MAX:
            roster = sorted(set(meta_person(x, handles, service) for x in members),
                            key=lambda v: v.lstrip("@").lower())
            # Threads split across message_1.json, message_2.json and so on
            # carry the same roster; a group he left and rejoined does not.
            rosters[key] = sorted(set(rosters.get(key, [])) | set(roster),
                                  key=lambda v: v.lstrip("@").lower())
        for m in ((data or {}).get("messages") or []):
            date, time = epoch_local((m.get("timestamp_ms") or 0) / 1000.0)
            if not date:
                continue
            # A call is a different thing from a chat and carries its own
            # duration: it says who he actually spoke to, and for how long.
            if "call_duration" in m:
                calls[date].append((time, title, m.get("call_duration") or 0))
                continue
            slot = byday[date].get(title)
            if slot is None:
                slot = byday[date][title] = [time, set(), group]
            if time < slot[0]:
                slot[0] = time
            who = meta_text(m.get("sender_name") or "")
            if who and who != me:
                slot[1].add(who)
            if group:
                gcdays[date].add(key)
    for date, chats in byday.items():
        lines = []
        for title, (t, senders, group) in sorted(chats.items(),
                                                 key=lambda kv: (kv[1][0], kv[0])):
            # A one-to-one thread is titled with the other person, so the title
            # itself becomes the handle. A group keeps its name and carries the
            # people who actually said something that day.
            label = title if group else meta_person(title, handles, service)
            if group:
                # Who spoke that day, then how many people were in the room and
                # did not. A group of forty showing one name said nothing about
                # the group; "+39" does.
                said = sorted(set(meta_person(x, handles, service, full=False)
                                  for x in senders),
                              key=lambda v: v.lstrip("@").lower())
                roster = rosters.get("%s\t%s" % (service, title)) or []
                quiet = max(0, len(roster) - len(said))
                if not said:
                    said, quiet = roster, 0
                shown = said[:GC_INLINE_MAX]
                rest = (len(said) - len(shown)) + quiet
                if shown:
                    label = "%s {%s%s}" % (label, ", ".join(shown),
                                           " +%d" % rest if rest else "")
            lines.append("%s \u00b7 %s" % (t, label))
        f = nest(date, "Texted on %s:" % where, lines, service.lower())
        if f:
            out.append(f)
    for date, rows in calls.items():
        # A zero duration is left bare rather than called "missed", which is
        # not something the file actually says.
        lines = ["%s \u00b7 %s%s" % (t, name, " (%s)" % _hm(d) if d else "")
                 for t, name, d in sorted(rows)]
        f = nest(date, "Called on %s:" % where, lines, service.lower())
        if f:
            out.append(f)


COUNT_LABELS = [
    # An uploaded phone book is other people's data and is not an event in his
    # day: the timestamps are when Facebook slurped the contacts, not when he
    # did anything. 1,925 of them were being counted as generic activity.
    (r"imported_contacts|contacts_uploaded|synced_contacts", None),
    (r"received_friend_requests", ("friend request received",
                                   "friend requests received")),
    (r"sent_friend_requests", ("friend request sent", "friend requests sent")),
    (r"your_friends|friends_added", ("friend added", "friends added")),
    (r"who_you.?ve_followed", ("account followed", "accounts followed")),
    (r"emails_we_sent_you", None),          # Meta's own mail out, not his day
    (r"profile_visits", ("profile visited", "profiles visited")),
    (r"items_viewed", ("item viewed", "items viewed")),
    (r"groups_and_events_you.?ve_visited", ("group or event visited",
                                            "groups and events visited")),
    (r"notifications", ("notification", "notifications")),
    (r"stickers_created", ("sticker created", "stickers created")),
    (r"liked_posts|likes_media_likes|likes_and_reactions|reactions", "like"),
    (r"liked_comments", "comment like"),
    (r"saved_posts|saved_collections", "save"),
    (r"post_comments|reels_comments|comments", "comment"),
    (r"followers", "new follower"),
    (r"following", "account followed"),
    (r"story_likes|polls|quizzes|emoji_sliders|countdowns|questions", "story interaction"),
    (r"your_search|search_history|searches", ("search", "searches")),
    (r"recently_viewed|ads_viewed|ads_clicked|ads_about", None),
    (r"login|logout|account_activity|session|device|ip_address|password", None),
]


def _meta_counts(root, service, out, skip):
    byday = defaultdict(collections.Counter)
    MANY = {}
    for p in glob.glob(os.path.join(root, "**", "*.json"), recursive=True):
        if p in skip or os.sep + "messages" + os.sep in p:
            continue
        rel = os.path.relpath(p, root).replace(os.sep, "/").lower()
        if rel.startswith(("ads_information/", "apps_and_websites_off_of_facebook/",
                           "security_and_login_information/")):
            continue          # ad targeting, off-site tracking and login records
        stem = os.path.basename(p).lower()
        label, many = "entry", "entries"
        drop = False
        for pat, lab in COUNT_LABELS:
            if re.search(pat, stem):
                if lab is None:
                    drop = True
                elif isinstance(lab, tuple):
                    label, many = lab
                else:
                    label, many = lab, None
                break
        if drop:
            continue
        MANY[label] = many or MANY.get(label)
        for ts, _label in meta_walk(jload(p)):
            date, _ = epoch_local(ts)
            if date:
                byday[date][label] += 1
    for date, c in byday.items():
        lines = [plural(v, k, MANY.get(k)) for k, v in sorted(c.items(), key=lambda kv: -kv[1])]
        f = nest(date, "%s:" % service, lines, service.lower())
        if f:
            out.append(f)


def _meta_adapter(kind, service):
    root = meta_root(kind)
    if not root:
        return []
    handles = meta_handles(root) if kind == "instagram" else {}

    def build(_paths):
        out, skip = [], set()
        rosters, gcdays = {}, defaultdict(set)
        for pat, verb in (("posts_*.json", "Posted on"),
                          ("your_posts*.json", "Posted on"),
                          ("stories.json", "Story on"),
                          ("reels.json", "Reel on"),
                          ("archived_posts.json", "Archived post on"),
                          ("profile_photos.json", "New profile photo on"),
                          ("other_content.json", "Posted on"),
                          ("your_uncategorized_photos.json", "Photo on")):
            for p in glob.glob(os.path.join(root, "**", pat), recursive=True):
                skip.add(p)
                _meta_posts(p, service, out, verb)
                if service == "Facebook":
                    _meta_places(p, service, out)
        _meta_messages(root, service, out, handles, rosters, gcdays)
        # _meta_counts is every tally Meta keeps: likes, searches, profile
        # visits, notifications. Dropped from the journal 09-09-2026 for the
        # same reason as the Google ones. The function stays because the
        # export inventory still uses its labels to say what a file is.
        return {"facts": [list(f) for f in out],
                "rosters": rosters,
                "gcdays": dict((d, sorted(v)) for d, v in gcdays.items())}
    paths = sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True))
    blob = cached_obj("meta-" + kind, paths, build)
    GC_ROSTERS.update(blob.get("rosters") or {})
    for date, keys in (blob.get("gcdays") or {}).items():
        GC_DAYS[date].update(keys)
    return [Fact(*row) for row in blob.get("facts") or []]


def a_instagram():
    return _meta_adapter("instagram", "Instagram")


def a_facebook():
    return _meta_adapter("facebook", "Facebook")


def export_dirs(kind):
    return [path for root in exports_roots()
            for path in [os.path.join(root, kind)] if os.path.isdir(path)]


def utc_stamp(value, pattern):
    try:
        return local_of(datetime.strptime(str(value), pattern).replace(tzinfo=UTC))
    except (TypeError, ValueError):
        return None, None


def export_label(value, fallback):
    label = re.sub(r"\s+", " ", str(value or "")).strip()[:100] or fallback
    return label.replace("[", r"\[").replace("]", r"\]")


def a_discord():
    """One per channel/day, from the package's own sent-message records only."""
    out = []
    for root in export_dirs("discord"):
        index = jload(os.path.join(root, "Messages", "index.json")) or {}
        paths = sorted(glob.glob(os.path.join(root, "Messages", "c*", "messages.json")))

        def build(_paths, root=root, index=index):
            byday = defaultdict(dict)
            for path in _paths:
                channel_id = os.path.basename(os.path.dirname(path))[1:]
                label = export_label(index.get(channel_id), "channel " + channel_id)
                for row in jload(path) or []:
                    date, time = utc_stamp(row.get("Timestamp"), "%Y-%m-%d %H:%M:%S")
                    if date and (label not in byday[date] or time < byday[date][label]):
                        byday[date][label] = time
            result = []
            for date, channels in byday.items():
                fact = nest(date, "Texted on Discord:",
                            ["%s · %s" % (time, label)
                             for label, time in sorted(channels.items(), key=lambda row: (row[1], row[0]))],
                            "discord")
                if fact:
                    result.append(fact)
            return result

        out += cached("discord-" + re.sub(r"\W+", "_", root), paths, build)
    return out


def a_snapchat():
    """Only outgoing chat rows: a conversation and time, never its contents."""
    out = []
    for root in export_dirs("snapchat"):
        path = os.path.join(root, "json", "chat_history.json")
        if not os.path.isfile(path):
            continue

        def build(_paths, path=path):
            byday = defaultdict(dict)
            for title, rows in (jload(path) or {}).items():
                label = export_label(title, "Snapchat conversation")
                for row in rows or []:
                    if str(row.get("IsSender", "")).lower() not in ("true", "1", "yes"):
                        continue
                    date, time = utc_stamp(row.get("Created"), "%Y-%m-%d %H:%M:%S UTC")
                    if date and (label not in byday[date] or time < byday[date][label]):
                        byday[date][label] = time
            result = []
            for date, chats in byday.items():
                fact = nest(date, "Texted on Snapchat:",
                            ["%s · %s" % (time, label)
                             for label, time in sorted(chats.items(), key=lambda row: (row[1], row[0]))],
                            "snapchat")
                if fact:
                    result.append(fact)
            return result

        out += cached("snapchat-" + re.sub(r"\W+", "_", root), [path], build)
    return out


XIAOMI_BACKUP_DIR = "/mnt/wd-blue/Backup/Xiaomi"
XIAOMI_DASHBOARD_DIR = "/mnt/wd-blue/Exports/Xiaomi"


def xiaomi_dashboard_rows(paths):
    """Newest Dashboard export wins for a daily aggregate."""
    best = {}
    for path in paths:
        try:
            rows = csv.DictReader(open(path, encoding="utf-8-sig"))
            for row in rows:
                date = (row.get("date") or "").strip()
                steps = int(row.get("steps") or "")
                if row.get("distance_m"):
                    distance = "%.2f km" % (int(row["distance_m"]) / 1000)
                    calories = "%s kcal" % int(row.get("calories") or 0)
                    duration = "%s min" % int(row.get("duration_min") or 0)
                else:
                    distance = re.sub(r"(?<=\d)(?:km|m)$", lambda match: " " + match.group(), row.get("distance", "").lower())
                    calories = row.get("calories", "").lower()
                    duration = re.sub(r"(?<=[hms])(?=\d)", " ", row.get("duration", "").lower())
                    if not (distance and calories and duration):
                        continue
                if re.match(r"^20\d\d-\d\d-\d\d$", date) and steps >= 0:
                    candidate = (os.path.getmtime(path), steps, distance, calories, duration)
                    if date not in best or candidate[0] > best[date][0]:
                        best[date] = candidate
        except (OSError, ValueError):
            continue
    return best


def a_xiaomi_dashboard():
    paths = sorted(glob.glob(os.path.join(XIAOMI_DASHBOARD_DIR, "*Dashboard*Steps*.csv")))

    def build(_paths):
        return [Fact(date, None, "Xiaomi Dashboard: %s steps (%s; %s; %s)" %
                     (format(row[1], ","), row[2], row[3], row[4]), "xiaomi_dashboard")
                for date, row in sorted(xiaomi_dashboard_rows(_paths).items())]

    return cached("xiaomi-dashboard", paths, build)


def a_xiaomi_fitness():
    """Daily Mi Fitness step summaries from Xiaomi's local-backup TAR stream."""
    paths = sorted(glob.glob(os.path.join(XIAOMI_BACKUP_DIR, "*.zip")))
    dashboard_paths = sorted(glob.glob(os.path.join(XIAOMI_DASHBOARD_DIR, "*Dashboard*Steps*.csv")))
    dashboard_dates = set(xiaomi_dashboard_rows(dashboard_paths))

    def build(_paths):
        best = {}
        for path in _paths:
            try:
                with zipfile.ZipFile(path) as outer:
                    info = next(i for i in outer.infolist()
                                if i.filename.endswith("Mi Fitness(com.xiaomi.wearable).bak"))
                    with outer.open(info) as raw:
                        if raw.readline() != b"MIUI BACKUP\n":
                            continue
                        for _ in range(12):
                            if raw.readline() == b"none\n":
                                break
                        else:
                            continue
                        payload = {}
                        with tarfile.open(fileobj=raw, mode="r|") as inner:
                            for member in inner:
                                name = os.path.basename(member.name)
                                if name in ("fitness_summary", "fitness_summary-wal"):
                                    item = inner.extractfile(member)
                                    if item:
                                        payload[name] = item.read()
                if "fitness_summary" not in payload:
                    continue
                with tempfile.TemporaryDirectory(prefix="journal-xiaomi-") as tmp:
                    database = os.path.join(tmp, "fitness_summary")
                    for name, data in payload.items():
                        with open(os.path.join(tmp, name), "wb") as fh:
                            fh.write(data)
                    con = sqlite3.connect(database)
                    try:
                        rows = con.execute("""
                            SELECT timeInZero, updateTime, value FROM daily_report
                            WHERE dataType = 'STEP' AND viewTag = 'days' AND isDeleted = 0
                        """).fetchall()
                    finally:
                        con.close()
            except (OSError, ValueError, sqlite3.Error, tarfile.TarError, zipfile.BadZipFile, StopIteration):
                continue
            for zero, updated, value in rows:
                try:
                    metric = json.loads(value)
                    steps = int(metric["steps"])
                    distance = int(metric.get("distance", 0))
                    calories = metric.get("calories", 0)
                    date, _ = epoch_local(int(zero))
                except (KeyError, TypeError, ValueError, OverflowError):
                    continue
                candidate = (int(updated or 0), os.path.getmtime(path), steps, distance, calories)
                if date and steps >= 0 and (date not in best or candidate[:2] > best[date][:2]):
                    best[date] = candidate
        return [Fact(date, None, "Mi Fitness: %s steps (%.2f km; %s kcal)" %
                     (format(row[2], ","), row[3] / 1000, row[4]), "xiaomi_fitness")
                for date, row in sorted(best.items()) if date not in dashboard_dates]

    return cached("xiaomi-fitness", paths + dashboard_paths, build)


# --------------------------------------------------------------------------
# The rest of what already records a day: coding time, the machine being on,
# Nextcloud, sent mail, files opened, the arr stack, Navidrome, MyAnimeList,
# GitHub, torrents and the game launchers. Surveyed and added 08-09-2026.
# --------------------------------------------------------------------------

def _hm(seconds):
    m = int(round(seconds / 60.0))
    return "%d h %02d min" % (m // 60, m % 60) if m >= 60 else "%d min" % m


def a_wakatime():
    """Hours actually coded. Git records the commit, not the afternoon."""
    key = vault_entry("WakaTime", "api_key")
    if not key:
        return []
    import base64, urllib.request
    store = os.path.join(CACHE, "wakatime.json")
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
        os.makedirs(CACHE, exist_ok=True)
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


def _hm(ts):
    return epoch_local(ts)[1]


def _span(on, off):
    """`HH:MM-HH:MM`, with the day offset when a session runs past midnight."""
    if off is None:
        return "%s-" % _hm(on)
    gap = (datetime.fromtimestamp(off, UTC).astimezone(BUDAPEST).date()
           - datetime.fromtimestamp(on, UTC).astimezone(BUDAPEST).date()).days
    return "%s-%s%s" % (_hm(on), _hm(off), " +%dd" % gap if gap else "")


def _hours(sec):
    sec = int(sec)
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm" % (sec // 60)


def a_boots():
    """When the machine was on, one line a day. Sessions come from the durable
    OS log (wtmp reaches back further than the journal) and short bursts of
    power cycling collapse to a count and a total instead of a line each."""
    rows = sorted(oslog.load(OS_LOG_DIR, "boots"), key=lambda r: r["on"])
    byday, prev = defaultdict(list), None
    for r in rows:
        date, _ = epoch_local(r["on"])
        if date:
            byday[date].append((r, prev))
        prev = r["kernel"]
    out = []
    for date, items in byday.items():
        sess = [r for r, _p in items]
        notes = []
        if items[0][1] and items[0][1] != items[0][0]["kernel"] or any(
                p and p != r["kernel"] for r, p in items[1:]):
            notes.append("new kernel %s" % sess[-1]["kernel"].split(".fc")[0])
        if any(r["end"] == "crash" for r in sess):
            notes.append("unclean shutdown")
        if len(sess) <= 3:
            text = "PC on " + ", ".join(_span(r["on"], r["off"]) for r in sess)
        else:
            up = sum(r["off"] - r["on"] for r in sess if r["off"])
            text = "PC on, %d sessions, %s up" % (len(sess), _hours(up))
        if notes:
            text += " (%s)" % ", ".join(notes)
        out.append(Fact(date, _hm(sess[0]["on"]), text, "boots"))
    return out


def a_logins():
    """Desktop logins by name; terminal tabs only as a count, because a tab is
    not an event worth a line."""
    byday = defaultdict(lambda: {"tabs": 0, "desktop": []})
    for r in oslog.load(OS_LOG_DIR, "logins"):
        date, _ = epoch_local(r["start"])
        if not date:
            continue
        if r["tty"].startswith("pts/"):
            byday[date]["tabs"] += 1
        else:
            byday[date]["desktop"].append(_span(r["start"], r["end"]))
    out = []
    for date, d in byday.items():
        parts = (["Desktop login " + ", ".join(d["desktop"])] if d["desktop"] else [])
        if d["tabs"]:
            parts.append("%d terminal tab%s" % (d["tabs"], "s" if d["tabs"] > 1 else ""))
        out.append(Fact(date, None, ", ".join(parts), "logins"))
    return out


def a_dnf():
    """Package changes I ran, merged into one line a day: updates are summed,
    installs and removals are named."""
    byday = defaultdict(list)
    for r in oslog.load(OS_LOG_DIR, "dnf"):
        date, time = epoch_local(r["ts"])
        if date:
            byday[date].append((time, r))
    out = []
    for date, rows in byday.items():
        rows.sort(key=lambda x: x[0])
        updated, parts = 0, []
        for _t, r in rows:
            words = r["cmd"].split()
            verb = words[1] if len(words) > 1 else ""
            names = [w for w in words[2:] if not w.startswith("-")]
            if verb == "group" and names:          # `group install X` is install X
                verb, names = names[0], names[1:]
            if verb in ("update", "upgrade", "distro-sync", "system-upgrade"):
                updated += r["n"]
            elif verb in ("install", "reinstall", "group", "swap"):
                parts.append("%s %s" % ("installed" if verb != "reinstall" else "reinstalled",
                                        " ".join(names) or "packages"))
            elif verb in ("remove", "erase", "autoremove"):
                parts.append("removed %s" % (" ".join(names) or "packages"))
            else:
                parts.append("dnf %s" % " ".join(words[1:])[:40])
        if updated:
            parts.insert(0, "updated %d packages" % updated)
        out.append(Fact(date, rows[0][0], "; ".join(parts), "dnf"))
    return out


def a_crashes():
    """Programs that crashed, by name. Services that crash on their own are
    filtered out in the rules file; this is what I was running."""
    byday = defaultdict(list)
    for r in oslog.load(OS_LOG_DIR, "crashes"):
        date, time = epoch_local(r["ts"])
        if date and not any(i in r["exe"] for i in CRASH_IGNORE):
            byday[date].append((time, os.path.basename(r["exe"]) or "unknown"))
    return [Fact(date, min(t for t, _n in rows), "Crashed: " + ", ".join(
        "%s x%d" % (n, c) if c > 1 else n
        for n, c in Counter(n for _t, n in rows).items()), "crashes")
        for date, rows in byday.items()]


def a_shell():
    """Commands I ran in a terminal, as command names with counts and nothing
    else. Dormant until bash history is timestamped (HISTTIMEFORMAT set)."""
    byday = defaultdict(Counter)
    for r in oslog.load(OS_LOG_DIR, "shell"):
        date, _ = epoch_local(r["ts"])
        if date:
            byday[date][r["cmd"]] += 1
    out = []
    for date, c in byday.items():
        top = c.most_common(6)
        text = "Shell: " + ", ".join("%s x%d" % kv for kv in top)
        if len(c) > 6:
            text += ", +%d more" % (len(c) - 6)
        out.append(Fact(date, None, text, "shell"))
    return out


NC_SUBJECTS = {
    "created_self": ("file uploaded", "files uploaded"),
    "deleted_self": ("file deleted", "files deleted"),
    "changed_self": ("file changed", "files changed"),
    "shared_link_self": ("link shared", "links shared"),
    "card_add_self": ("contact added", "contacts added"),
    "card_update_self": ("contact edited", "contacts edited"),
    "card_delete_self": ("contact deleted", "contacts deleted"),
    "calendar_add_self": ("calendar made", "calendars made"),
    "object_add_event_self": ("event added", "events added"),
    "object_update_event_self": ("event edited", "events edited"),
    "object_delete_event_self": ("event deleted", "events deleted"),
}


def a_ncloud():
    """What was done in Nextcloud. Counts, because a bulk import is one act."""
    try:
        r = subprocess.run(
            ["docker", "exec", "nextcloud-db", "psql", "-U", "nextcloud", "-d", "nextcloud",
             "-tAF", "\x1f", "-c",
             "select to_char(to_timestamp(timestamp) at time zone 'Europe/Budapest',"
             "'YYYY-MM-DD'), subject, count(*) from oc_activity "
             "where app <> 'files_sharing' and subject <> 'app_token_created' "
             "group by 1, 2"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    byday = defaultdict(list)
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        date, subject, n = parts[0], parts[1], int(parts[2])
        words = NC_SUBJECTS.get(subject)
        if not words:
            continue
        byday[date].append((n, plural(n, words[0], words[1])))
    out = []
    for date, items in byday.items():
        items.sort(key=lambda x: -x[0])
        out.append(Fact(date, None, "Nextcloud: " + ", ".join(t for _n, t in items), "ncloud"))
    return out


def a_mail():
    """Mail sent. What arrived is somebody else's action, and it is noise.

    Thunderbird stores these as maildir on this machine, one `.eml` per
    message under `cur/`, but the same folder is an mbox file in older
    profiles, so both shapes are handled.
    """
    out, boxes = [], []
    roots = glob.glob(os.path.join(HOME, ".thunderbird", "*", "ImapMail", "*", "*.sbd")) + \
            glob.glob(os.path.join(HOME, ".thunderbird", "*", "Mail", "*")) + \
            glob.glob(os.path.join(HOME, ".thunderbird", "*", "ImapMail", "*"))
    for root in roots:
        for name in ("Sent Mail", "Sent Items", "Sent", "Sent Messages"):
            p = os.path.join(root, name)
            if os.path.isdir(os.path.join(p, "cur")):
                boxes += sorted(glob.glob(os.path.join(p, "cur", "*")))
            elif os.path.isfile(p):
                boxes.append(p)
    for box in sorted(set(boxes)):
        try:
            raw = open(box, "rb").read()
        except OSError:
            continue
        chunks = re.split(rb"\r?\n(?=From )", raw) if raw.startswith(b"From ") else [raw]
        for chunk in chunks:
            head = re.split(rb"\r?\n\r?\n", chunk, maxsplit=1)[0].decode("utf-8", "replace")
            head = re.sub(r"\r?\n[ \t]+", " ", head)
            d = re.search(r"^Date:\s*(.+)$", head, re.M)
            if not d:
                continue
            sm = re.search(r"^Subject:\s*(.+)$", head, re.M)
            t = re.search(r"^To:\s*(.+)$", head, re.M)
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(d.group(1).strip())
            except Exception:
                continue
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            loc = dt.astimezone(BUDAPEST)
            subj = _mime_header(sm.group(1).strip()) if sm else "(no subject)"
            to = _mime_header(t.group(1).strip()) if t else ""
            to = re.sub(r"\s*<[^>]*>", "", to).strip(' "')
            to = to.split(",")[0].strip() or "someone"
            out.append(Fact(loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M"),
                            "Emailed %s: %s" % (to, subj[:80]), "mail"))
    return list(dict.fromkeys(out))


def _mime_header(v):
    try:
        from email.header import decode_header, make_header
        return str(make_header(decode_header(v)))
    except Exception:
        return v


SKIP_FILES = re.compile(r"/\.|/tmp/|/Trash/|thumbnail|\.part$|/proc/", re.I)


def a_files():
    """Files opened, off the desktop's own recent list. One bullet a day: a
    flat list of forty opens would bury everything else in the block."""
    p = os.path.join(HOME, ".local", "share", "recently-used.xbel")
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


# Sonarr and Radarr number their history events the same way. Only the two that
# mean something entered the library are kept; the rest of the table is renames
# and deletions from bulk maintenance.
ARR_EVENTS = {1: "grabbed", 3: "imported", 6: "imported"}


def a_arr():
    out = []
    for label, path, table in (
            ("Sonarr", os.path.join(HOME, "docker", "sonarr", "config", "sonarr.db"), "History"),
            ("Radarr", os.path.join(HOME, "docker", "radarr", "config", "radarr.db"), "History")):
        if not os.path.exists(path):
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


def a_navidrome():
    """Navidrome plays that Last.fm never received, shaped like Last.fm's own
    facts so the renderer folds both into one "Listened to:" list. A play Last.fm
    already holds is dropped when it lands within two minutes AND shares the
    artist or the title, so a different track on another device is not lost."""
    db = os.path.join(HOME, "docker", "navidrome", "data", "navidrome.db")
    if not os.path.exists(db):
        return []

    def norm(x):
        return re.sub(r"\W+", "", (x or "").casefold())

    known = defaultdict(list)                  # minute -> [(artist, track)]
    try:
        blob = json.load(open(LASTFM_CACHE, encoding="utf-8"))
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


MAL_VERB = {"completed": "finished", "watching": "was watching", "on_hold": "put on hold",
            "dropped": "dropped", "plan_to_watch": "added to the plan-to-watch"}


def a_mal():
    """One date per title, the last time the entry was touched, exactly the
    limitation Simkl's export has."""
    cid = vault_entry("MyAnimeList", "api_key")
    username = str(ACCOUNTS.get("mal_user") or "")
    if not cid or not username:
        return []
    import urllib.request
    out, url = [], (f"https://api.myanimelist.net/v2/users/{username}/animelist"
                    "?fields=list_status&limit=1000&nsfw=true")
    while url:
        req = urllib.request.Request(url, headers={"X-MAL-CLIENT-ID": cid})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = json.load(r)
        except Exception as ex:
            print("  mal: %s" % ex)
            break
        for row in blob.get("data", []):
            st = row.get("list_status") or {}
            title = (row.get("node") or {}).get("title") or ""
            date, time = iso_local(st.get("updated_at"))
            if not date or not title:
                continue
            verb = MAL_VERB.get(st.get("status"), "updated")
            eps = st.get("num_episodes_watched")
            score = st.get("score")
            bits = []
            if eps:
                bits.append(plural(eps, "episode"))
            if score:
                bits.append("scored %s" % score)
            out.append(Fact(date, time, "MyAnimeList: %s %s%s" % (
                verb, title, " (%s)" % ", ".join(bits) if bits else ""), "mal"))
        url = (blob.get("paging") or {}).get("next")
    return out


GH_EVENTS = {
    "WatchEvent": "starred", "ForkEvent": "forked", "CreateEvent": "created",
    "IssuesEvent": "opened an issue on", "PullRequestEvent": "opened a pull request on",
    "ReleaseEvent": "released", "PublicEvent": "made public",
    "IssueCommentEvent": "commented on",
}


def a_github():
    """What local git cannot see. Pushes are deliberately skipped, because the
    git adapter already reads the commits out of the working copies."""
    key = vault_entry("GitHub", "api_key")
    username = str(ACCOUNTS.get("github_user") or "")
    if not key or not username:
        return []
    import urllib.request
    out = []
    for page in range(1, 4):
        req = urllib.request.Request(
            f"https://api.github.com/users/{username}/events?per_page=100&page={page}",
            headers={"Authorization": "Bearer " + key,
                     "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = json.load(r)
        except Exception as ex:
            print("  github: %s" % ex)
            break
        if not rows:
            break
        for e in rows:
            verb = GH_EVENTS.get(e.get("type"))
            if not verb:
                continue
            date, time = iso_local(e.get("created_at"))
            repo = (e.get("repo") or {}).get("name", "")
            if date and repo:
                out.append(Fact(date, time, "GitHub: %s %s" % (verb, repo), "github"))
    return list(dict.fromkeys(out))


def _bdecode(data, i=0):
    if data[i:i + 1] == b"i":
        j = data.index(b"e", i)
        return int(data[i + 1:j]), j + 1
    if data[i:i + 1] == b"l":
        out, i = [], i + 1
        while data[i:i + 1] != b"e":
            v, i = _bdecode(data, i)
            out.append(v)
        return out, i + 1
    if data[i:i + 1] == b"d":
        out, i = {}, i + 1
        while data[i:i + 1] != b"e":
            k, i = _bdecode(data, i)
            v, i = _bdecode(data, i)
            out[k] = v
        return out, i + 1
    j = data.index(b":", i)
    n = int(data[i:j])
    return data[j + 1:j + 1 + n], j + 1 + n


def a_torrents():
    """When a download finished, out of qBittorrent's own resume files."""
    d = os.path.join(HOME, "docker", "qbittorrent", "config", "qBittorrent", "BT_backup")
    byday = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(d, "*.fastresume"))):
        try:
            blob, _ = _bdecode(open(p, "rb").read())
        except Exception:
            continue
        done = blob.get(b"completed_time") or blob.get(b"completed_on") or 0
        name = blob.get(b"name") or b""
        if not name:
            tor = p[:-len(".fastresume")] + ".torrent"
            try:
                meta, _ = _bdecode(open(tor, "rb").read())
                name = (meta.get(b"info") or {}).get(b"name") or b""
            except Exception:
                pass
        if not done or not name:
            continue
        date, time = epoch_local(done)
        if date:
            byday[date].append((time, name.decode("utf-8", "replace")[:90]))
    out = []
    for date, rows in byday.items():
        rows.sort()
        f = nest(date, "Downloads finished:",
                 ["%s · %s" % (t, n) for t, n in rows[:12]], "torrents")
        if f:
            out.append(f)
    return out


def a_games():
    """Plays kept in the durable OS log. Each launcher keeps only the latest play
    per game, so the log is what turns that into a history. Minecraft sessions
    (from its own game logs) fold into one line per instance a day; a launch
    within five minutes of a logged session is the same play."""
    label = {"steam": "Steam", "heroic": "Heroic", "epic": "Epic", "gog": "GOG",
             "lutris": "Lutris", "bottles": "Bottles", "minecraft": "Minecraft"}
    byday = defaultdict(lambda: defaultdict(list))
    seen = set()
    rows_all = oslog.load(OS_LOG_DIR, "games")
    sess = defaultdict(list)
    for r in rows_all:
        if r.get("sess_s") is not None:
            sess[r["name"]].append(r)
    for r in sorted(rows_all, key=lambda r: r["ts"]):
        if oslog.STEAM_TOOLS.match(r["name"]):
            continue
        date, time = epoch_local(r["ts"])
        key = (r["name"], r["ts"] // 300)
        if not date:
            continue
        if r.get("store") == "minecraft":           # only the launcher's own launch repeats a session
            if any((r["name"], r["ts"] // 300 + d) in seen for d in (-1, 0, 1)):
                continue
            seen.add(key)
        if r.get("sess_s") is None and any(x["name"] == r["name"] and x.get("sess_s") is not None
                                           and abs(x["ts"] - r["ts"]) <= 300 for x in sess.get(r["name"], ())):
            continue                                # the launch a logged session already covers
        byday[date][(r.get("store"), r["name"])].append((time, r["sess_s"] if "sess_s" in r else r.get("played_s"), "sess_s" in r))
    out = []
    for date, games in byday.items():
        for (store, name), rows in games.items():
            n = len(rows)
            if store == "steam" and any(x[2] for x in rows):
                rows = [x for x in rows if x[2]]        # sessions win over the lifetime total
            n = len(rows)
            if store in ("minecraft", "bottles") or (store == "steam" and rows[0][2]):       # rows are sessions, so they add up
                secs = sum(x[1] for x in rows if x[1])
                extra = [("%d sessions" % n) if n > 1 else "", _hours(secs) if secs >= 60 else ""]
                tail = " (%s)" % ", ".join(e for e in extra if e) if any(extra) else ""
                out.append(Fact(date, min(x[0] for x in rows), "%s: %s %s%s" % (
                    label[store], "ran" if store == "bottles" else "played", name, tail), "games"))
                continue
            total = rows[-1][1]
            tail = (" (%s in total)" % _hours(total)) if total else ""
            verb = "opened" if name == "Epic Games Launcher" else "played"
            out.append(Fact(date, min(x[0] for x in rows), "%s: %s %s%s%s" % (
                label.get(store, "Game"), verb, name, " x%d" % n if n > 1 else "", tail), "games"))
    return out


ADAPTERS = [a_erste, a_brac, a_git, a_jellyfin, a_simkl, a_saves, a_worklog,
            a_docs, a_neptun, a_canvas, a_immich, a_claude, a_lastfm,
            a_takeout, a_instagram, a_facebook, a_discord, a_snapchat, a_xiaomi_dashboard, a_xiaomi_fitness, a_commute,
            a_wakatime, a_boots, a_mail, a_files,
            a_arr, a_navidrome, a_mal, a_github, a_torrents, a_games,
            a_grades, a_logins, a_dnf, a_crashes, a_shell]

# --------------------------------------------------------------------------
# month file rendering
# --------------------------------------------------------------------------
DAYH = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
BEGIN = "<!-- auto:begin %s -->"
END = "<!-- auto:end -->"


def split_file(text):
    lines = text.split("\n")
    starts = [i for i, l in enumerate(lines) if DAYH.match(l)]
    if not starts:
        # No days yet. Everything from the first month-level section onward is
        # the tail, or new days would be appended below the references.
        tail = len(lines)
        for i, l in enumerate(lines):
            if i and l.startswith("## ") and not DAYH.match(l):
                tail = i
                break
        while tail and not lines[tail - 1].strip():
            tail -= 1
        if tail and lines[tail - 1].strip() == "---":
            tail -= 1
        return lines[:tail], [], lines[tail:]
    first = starts[0]
    end = len(lines)
    for i in range(starts[-1] + 1, len(lines)):
        if lines[i].strip() == "---" or (lines[i].startswith("## ") and not DAYH.match(lines[i])):
            end = i
            break
    days, bounds = [], starts + [end]
    for k, s in enumerate(starts):
        days.append((DAYH.match(lines[s]).group(1), lines[s:bounds[k + 1]]))
    return lines[:first], days, lines[end:]


def render_block(date, facts, numbers):
    body = [BEGIN % date, ""]
    if facts:
        body.extend(render_day(facts, numbers))
    else:
        body.append("_Nothing recorded in any source for this day._")
    body += ["", END]
    return ["#### Auto generated", ""] + body + [""]


def rebuild_day(date, existing, facts, numbers):
    block = render_block(date, facts, numbers)
    if existing is None:
        return ["## %s" % date, "", "#### Manual", "", "#### LLM", ""] + block
    out, i, done = [], 0, False
    while i < len(existing):
        if existing[i].startswith("#### Auto generated"):
            j = i
            while j < len(existing) and END not in existing[j]:
                j += 1
            out += block
            i = j + 1
            done = True
            while i < len(existing) and not existing[i].strip():
                i += 1
            continue
        out.append(existing[i]); i += 1
    if not done:
        while out and not out[-1].strip():
            out.pop()
        out += [""] + block
    return out


def has_manual(body):
    """True when a day section carries dictated text of its own."""
    if not body:
        return False
    try:
        i = next(k for k, l in enumerate(body) if l.startswith("#### Manual"))
    except StopIteration:
        return False
    for l in body[i + 1:]:
        if l.startswith("#### Auto generated"):
            break
        if l.strip():
            return True
    return False


def new_month_header(ym):
    y, m = ym.split("-")
    label = "%s %s" % (MONTHS[int(m) - 1], y)
    return [
        "---",
        "title: Journal — %s" % label,
        "datetime: %s-01T00:00:00" % ym,
        "description: Auto-generated only. Nothing was dictated for this month; every line is derived from the sources listed at the bottom.",
        "tags:",
        "  - Journal",
        "purpose: Journaling",
        "month: %s" % ym,
        "---",
        "",
        "# Journal — %s" % label,
        "",
        "**Nothing was dictated for this month.** Every day below carries only a `#### Auto generated` block; there is no `#### Manual` section, because nothing was written. What each source can and cannot honestly say is set out in [[Auto Journal - Spec and Method]].",
        "",
    ]


GC_HDR = [
    "---",
    "",
    "## Group chats",
    "",
    "Every group chat the days above name, with who is in it. A chat of %d people or more is left out: a roster that size is a mailing list, not a group of people. Instagram members are handles, because that is what identifies somebody there; Messenger has no handles, so those are the names the export carries. Rewritten wholesale on every run." % GC_ROSTER_MAX,
    "",
]

AUTOREF_HDR = [
    "---",
    "",
    "## Auto references",
    "",
    "Sources behind the `#### Auto generated` blocks. Numbered `[^a1]`, `[^a2]` and so on, in a namespace of their own so a regenerate never disturbs the manual footnotes above. Rewritten wholesale on every run.",
    "",
]


def write_month(ym, byday, apply):
    path = os.path.join(BASE, "%s.md" % ym)
    exists = os.path.exists(path)
    if exists:
        pre, days, post = split_file(open(path, encoding="utf-8").read())
    else:
        pre, days, post = new_month_header(ym), [], list(AUTOREF_HDR) + [
            "<!-- autoref:begin -->", "_Not generated yet._", "<!-- autoref:end -->"]

    order, numbers = [], {}
    for date in sorted(set(list(byday) + [d for d, _ in days])):
        for f in byday.get(date, []):
            if f.src not in numbers:
                numbers[f.src] = len(order) + 1
                order.append(f.src)

    have = {d: body for d, body in days}
    merged = []
    for date in sorted(set(list(have) + list(byday))):
        body = have.get(date)
        # A day with nothing dictated and nothing in any source should not exist.
        # This also cleans up sections a previous, buggier run invented.
        if not byday.get(date) and not has_manual(body):
            continue
        merged.append((date, rebuild_day(date, body, byday.get(date, []), numbers)))

    # The roster section, rebuilt from whatever group chats this month names.
    gc = []
    for key in sorted(set(k for date, _ in merged for k in GC_DAYS.get(date, ()))):
        svc, title = key.split("\t", 1)
        members = GC_ROSTERS.get(key)
        if not members:
            continue          # over the size cap, so no roster was kept
        gc.append("- **%s** (%s, %s): %s" % (
            title, svc, plural(len(members), "member"), ", ".join(members)))

    refs = ["<!-- autoref:begin -->"]
    if order:
        for src in order:
            refs.append("[^a%d]: %s" % (numbers[src], SOURCES[src]))
    else:
        refs.append("_No sources carried data for this month._")
    refs.append("<!-- autoref:end -->")

    post_text = "\n".join(post)
    post_text = re.sub(r"\n*---\n+## Group chats\n.*?<!-- autogc:end -->", "",
                       post_text, flags=re.S)
    post = post_text.split("\n")
    if "autoref:begin" in post_text:
        post_text = re.sub(r"<!-- autoref:begin -->.*?<!-- autoref:end -->",
                           "\n".join(refs), post_text, flags=re.S)
        post = post_text.split("\n")
    else:
        while post and not post[-1].strip():
            post.pop()
        post += [""] + AUTOREF_HDR + refs

    if gc:
        block = GC_HDR + ["<!-- autogc:begin -->"] + gc + ["<!-- autogc:end -->"]
        try:
            at = post.index("## Auto references")
        except ValueError:
            at = len(post)
        while at and not post[at - 1].strip():
            at -= 1
        if at and post[at - 1].strip() == "---":
            at -= 1
        post = post[:at] + block + [""] + post[at:]

    body = []
    for _, blk in merged:
        while blk and not blk[-1].strip():
            blk.pop()
        body += blk + [""]

    # Manual and LLM prose is user-owned. Do not normalize blank lines across
    # the whole month: doing so would quietly alter a prewritten section that
    # has nothing to do with the generated auto blocks.
    out = "\n".join(pre + body + post).rstrip() + "\n"
    n = sum(len(v) for v in byday.values())
    if not merged:
        print("  %s  %s" % (ym, "delete (no days left)" if exists else "skip (nothing to write)"))
        if apply and exists:
            os.remove(path)
        return
    print("  %s  %s  %2d days, %3d lines, %d sources" % (
        ym, "update" if exists else "CREATE", len(merged), n, len(order)))
    if apply:
        open(path, "w", encoding="utf-8").write(out)


# A day has four visual bands: daily summaries, the clock-ordered event stream,
# activity lists, then archive artefacts. A coding total and step total describe
# the whole day, so they lead rather than interrupt a moment-by-moment record.
# Messages, searches and media are likewise lists of interactions, not one event
# at a parent bullet's arbitrary time. They are consolidated across services.
DAY_SUMMARIES = ("wakatime", "xiaomi_dashboard", "xiaomi_fitness")
ARTEFACT_GROUPS = ("docs", "files", "torrents", "immich", "navidrome", "lastfm")
MUSIC_SOURCES = ("lastfm", "navidrome")
CLOCK_IN_TEXT = ("commute", "worklog")
CLOCK = re.compile(r"\b([0-2]\d:[0-5]\d)\b")
ACTIVITY_SOURCES = ("facebook", "instagram", "discord", "snapchat", "takeout", "lastfm",
                    "navidrome")
PLATFORM_NAMES = {"facebook": "Messenger", "instagram": "Instagram",
                  "discord": "Discord", "snapchat": "Snapchat"}


def refs(sources, numbers):
    """Footnotes for one rendered line, preserving a stable source order."""
    unique = set(sources)
    ordered = sorted(unique, key=lambda src: (ACTIVITY_SOURCES.index(src)
                                               if src in ACTIVITY_SOURCES else 99,
                                               numbers[src]))
    return "".join("[^a%d]" % numbers[src] for src in ordered)


def render_fact(f, numbers):
    stamp = "%s \u00b7 " % f.time if f.time else ""
    head, *rest = f.text.split("\n")
    return ["- %s%s%s" % (stamp, head, refs([f.src], numbers))] + rest


def activity_parts(f):
    """Return (kind, source-labelled child lines), or None for a normal fact."""
    head, *kids = f.text.split("\n")
    for prefix, kind in (("Texted on ", "texted"), ("Called on ", "called"),
                         ("Searched:", "searched"),
                         ("Watched on YouTube:", "youtube"),
                         ("Tracks scrobbled:", "listened")):
        if not head.startswith(prefix):
            continue
        if kids:
            lines = [line.removeprefix("    - ") for line in kids]
        else:
            tail = head[len(prefix):].lstrip(": ")
            lines = ["%s \u00b7 %s" % (f.time, tail)] if f.time else [tail]
        return kind, lines
    return None


def music_line(line):
    """Conservatively recognise YouTube music from its publisher-style label."""
    lower = line.lower()
    if re.search(r"\bby .+ - topic$", line, re.I):
        return re.sub(r" - Topic$", " (YT Music)", line, flags=re.I)
    if "vevo" in lower or re.search(r"^\d\d:\d\d \u00b7 .+ - .+\b(?:ft\.|feat\.)", line, re.I):
        return line + " (YouTube)"
    return None


def search_line(line):
    """Put the product after the query, where it reads as useful context."""
    m = re.match(r"(\d\d:\d\d \u00b7 )([^:]+): (.+)$", line)
    return "%s%s (%s)" % (m.group(1), m.group(3), m.group(2)) if m else line


def render_activity(groups, numbers):
    heads = {"texted": "Texted:", "called": "Called:", "searched": "Searched:",
             "watched": "Watched:", "listened": "Listened to:"}
    lines = []
    for kind in ("texted", "called", "searched", "watched", "listened"):
        rows = groups.get(kind, [])
        if not rows:
            continue
        sources = [src for _line, src in rows]
        children = []
        for line, src in rows:
            if kind in ("texted", "called"):
                line += " (%s)" % PLATFORM_NAMES[src]
            elif kind == "searched":
                line = search_line(line)
            elif kind == "watched":
                line += " (YouTube)"
            elif kind == "listened":
                line += {"lastfm": " (Last.fm)", "navidrome": " (Navidrome)"}.get(src, "")
            children.append((line, src))
        children.sort(key=lambda row: (row[0][:5], row[0]))
        lines.append("- %s%s" % (heads[kind], refs(sources, numbers)))
        lines.extend("    - %s" % line for line, _src in children)
    return lines


COLLAPSE_AT = 4


def collapse(facts):
    """Identical timed one-liners from one source become a single line with a
    count and the span, so fifty Instagram posts do not own the day."""
    groups = defaultdict(list)
    for f in facts:
        if f.time and "\n" not in f.text:
            groups[(f.src, f.text)].append(f)
    done, out = set(), []
    for f in facts:
        g = groups.get((f.src, f.text)) if f.time and "\n" not in f.text else None
        if not g or len(g) < COLLAPSE_AT:
            out.append(f)
        elif (f.src, f.text) not in done:
            done.add((f.src, f.text))
            times = sorted(x.time for x in g)
            out.append(Fact(f.date, times[0], "%s x%d (to %s)" % (f.text, len(g), times[-1]), f.src))
    return out


def render_day(facts, numbers):
    """Render a day without letting untimed lists split the timeline."""
    summaries, timed, untimed, artefacts = [], [], [], []
    activity = defaultdict(list)
    for f in collapse(facts):
        if f.src in DAY_SUMMARIES:
            summaries.append(f)
            continue
        if f.src in ARTEFACT_GROUPS:
            # Last.fm belongs with YouTube music below; the other archive lists
            # keep their established order at the end of a day.
            part = activity_parts(f) if f.src in MUSIC_SOURCES else None
            if part:
                kind, rows = part
                activity[kind].extend((line, f.src) for line in rows)
            elif f.src in MUSIC_SOURCES:
                # A one-track day is deliberately a flat Fact in the adapter.
                # It still belongs in the combined listening list, not beneath
                # the archive artefacts just because it lacks a child bullet.
                activity["listened"].append(
                    ("%s - %s" % (f.time, f.text) if f.time else f.text, f.src))
            else:
                artefacts.append(f)
            continue
        part = activity_parts(f)
        if part:
            kind, rows = part
            if kind == "youtube":
                for line in rows:
                    music = music_line(line)
                    activity["listened" if music else "watched"].append(
                        (music or line, f.src))
            else:
                activity[kind].extend((line, f.src) for line in rows)
            continue
        (timed if day_order(f)[0] == 0 else untimed).append(f)

    out = []
    for source in DAY_SUMMARIES:
        for f in summaries:
            if f.src == source:
                out.extend(render_fact(f, numbers))
    for f in timed:
        out.extend(render_fact(f, numbers))
    for f in untimed:
        out.extend(render_fact(f, numbers))
    out.extend(render_activity(activity, numbers))
    for source in ARTEFACT_GROUPS:
        for f in artefacts:
            if f.src == source:
                out.extend(render_fact(f, numbers))
    return out


def day_order(f):
    if f.src in DAY_SUMMARIES:
        return (-1, DAY_SUMMARIES.index(f.src), "", f.src, f.text)
    if f.src in ARTEFACT_GROUPS:
        return (2, ARTEFACT_GROUPS.index(f.src), "", f.src, f.text)
    stamp = f.time
    if not stamp and f.src in CLOCK_IN_TEXT:
        m = CLOCK.search(f.text.split("\n")[0])
        stamp = m.group(1) if m else None
    if stamp:
        return (0, 0, stamp, f.src, f.text)
    return (1, 0, "", f.src, f.text)          # nothing dates it; after the clock


def track_journal(label):
    """Commit the journal directory to its own git repository (created on first
    use). Local only: nothing is ever pushed."""
    ignore = os.path.join(BASE, ".gitignore")
    if not os.path.exists(ignore):
        open(ignore, "w", encoding="utf-8").write("*.log\n__pycache__/\n")
    print("journal git: %s" % ("committed " + label if oslog.git_commit(BASE, "journal: " + label)
                               else "no changes (%s)" % label))


def run(config, *, apply: bool, only: list[str] | None = None, force: bool = False) -> None:
    """Compile one configured journal. Writing requires an explicit flag."""
    configure(config)
    only = only or []
    if only and apply and not force:
        print("Refusing to write from a subset of adapters.\n"
              "  Fences are rebuilt wholesale, so writing with only %s would DELETE\n"
              "  every line the other adapters contribute. Run with no adapter names to\n"
              "  write everything, or add --force if losing the rest is what you want."
              % ", ".join(only))
        sys.exit(2)
    if apply and OS_LOG_DIR:
        print("oslog harvest: %s" % oslog.harvest(OS_LOG_DIR, HOME, CRASH_IGNORE))
    facts = []
    for fn in ADAPTERS:
        key = fn.__name__[2:]
        if only and key not in only:
            continue
        got = fn()
        print("source %-9s %5d facts" % (key, len(got)))
        facts += got
    facts = list(dict.fromkeys(facts))
    bymonth = defaultdict(lambda: defaultdict(list))
    for f in facts:
        bymonth[f.date[:7]][f.date].append(f)
    for ym in sorted(bymonth):
        for date in bymonth[ym]:
            bymonth[ym][date].sort(key=day_order)
    # months that already have a file but no facts still get their refs refreshed
    for p in glob.glob(os.path.join(BASE, "20??-??.md")):
        bymonth.setdefault(os.path.basename(p)[:7], defaultdict(list))
    print("\n%d months, %d facts total%s\n" % (
        len(bymonth), len(facts), "" if apply else "  (dry run, nothing written)"))
    if apply:
        # Snapshot first, so anything typed into a Manual section since the last
        # run is in history before the fences are rebuilt around it.
        track_journal("snapshot before regenerate")
    for ym in sorted(bymonth):
        write_month(ym, bymonth[ym], apply)
    if apply:
        track_journal("regenerate auto blocks")
