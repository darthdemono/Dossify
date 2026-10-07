#!/usr/bin/env python3
"""Build the #### Auto generated blocks in Journal/YYYY-MM.md from every source
that records what I did. Dry run by default; --apply writes.

Contract: everything between <!-- auto:begin DATE --> and <!-- auto:end --> is
owned by this script and rebuilt wholesale. Everything outside is the user's and
is never touched. Same for <!-- autoref:begin/end -->.

Design and the blind spots of each source: Journal/Auto Journal - Spec and Method.md
"""
import collections, glob, json, os, re, subprocess
from collections import defaultdict, namedtuple
from datetime import datetime, timezone as _tz
from pathlib import Path

from dossify import oslog, profiles
from dossify.people import journal_identity, load_people

from zoneinfo import ZoneInfo

UTC = _tz.utc
HOME = os.path.expanduser("~")
BASE = ""
ARCHIVE = ""
CACHE = os.path.join(HOME, ".cache", "dossify")
_IDENTITY: dict[str, object] | None = None
PROVIDERS: dict[str, dict] = {}          # the [providers.<name>] blocks of dossify.toml
SOURCES: dict[str, str] = {}             # footnote text per source, filled from the source modules
TZ_DEFAULT = UTC                         # the owner's timezone
TZ_HISTORY: list[tuple[datetime, object]] = []   # (until, zone) spans before the default applies
GC_ROSTER_MAX = 200
GC_INLINE_MAX = 6
OS_LOG_DIR = ""

Fact = namedtuple("Fact", "date time text src")


def system_zone():
    """The machine's IANA timezone, or UTC when it cannot be told."""
    try:
        target = os.path.realpath("/etc/localtime")
        if "zoneinfo/" in target:
            return ZoneInfo(target.split("zoneinfo/", 1)[1])
    except Exception:
        pass
    return UTC


def configure(config) -> None:
    """Bind this engine to one private Dossify configuration."""
    global ARCHIVE, BASE, CACHE, SOURCES, _IDENTITY, PROVIDERS, TZ_DEFAULT, TZ_HISTORY
    global GC_ROSTER_MAX, GC_INLINE_MAX, OS_LOG_DIR
    from dossify.sources import registry

    if not config.output_dir:
        raise ValueError("dossify.toml needs output_dir")
    BASE = str(config.output_dir.resolve())
    ARCHIVE = str((config.journal.workspace_root or config.output_dir.parent).resolve())
    CACHE = str((config.journal.cache_dir or Path(HOME, ".cache", "dossify")).resolve())
    PROVIDERS = {name: dict(values) for name, values in config.providers.items()}
    people = load_people(config.people_file) if config.people_file and config.people_file.is_file() else {}
    _IDENTITY = journal_identity(people)
    TZ_DEFAULT = ZoneInfo(config.timezone) if config.timezone else system_zone()
    TZ_HISTORY = sorted(((span.until, ZoneInfo(span.zone)) for span in config.timezone_history),
                        key=lambda pair: pair[0])
    GC_ROSTER_MAX = config.journal.group_chat_roster_max
    GC_INLINE_MAX = config.journal.group_chat_inline_max
    OS_LOG_DIR = str(config.journal.os_log_dir or "")
    oslog.LOCAL = TZ_DEFAULT
    SOURCES = registry.labels()


def listify(value):
    """A config value that may be one string or a list, as a list of expanded paths or strings."""
    if value in (None, ""):
        return []
    items = [value] if isinstance(value, (str, os.PathLike, dict)) else list(value)
    return [os.path.expanduser(i) if isinstance(i, str) else i for i in items]


def secret(options, name="api_key"):
    """A credential from an environment variable or from a command that prints it.

    Configured as ``<name>_env = "VAR"`` and/or ``<name>_command = ["tool", "arg"]``.  The value is
    never logged and never written to the configuration.
    """
    var = options.get(name + "_env")
    if var and os.environ.get(var, "").strip():
        return os.environ[var].strip()
    command = options.get(name + "_command")
    if command:
        try:
            out = subprocess.run(list(command), capture_output=True, text=True, timeout=60).stdout.strip()
        except Exception:
            return None
        return out or None
    return None


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

# --------------------------------------------------------------------------
# footnote definitions, keyed by source
# --------------------------------------------------------------------------


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

def money(n, cur="HUF"):
    if abs(n - round(n)) < 0.005:
        return "{:,} {}".format(int(round(n)), cur)
    return "{:,.2f} {}".format(n, cur)























def play_span(a, b):
    def secs(s):
        p = [int(x) for x in s.split(":")] if re.match(r"^\d+:\d\d:\d\d$", s) else None
        return p[0] * 3600 + p[1] * 60 + p[2] if p else None
    x, y = secs(a), secs(b)
    if x is None or y is None or y <= x:
        return None
    d = y - x
    return "%d h %02d min played" % (d // 3600, (d % 3600) // 60)























# My own handsets, keyed by the EXIF model string. The value is the name I would
# actually say out loud, which is what goes in the journal line.
MY_CAMERAS: dict[str, str] = {}
ME_NAMES: set[str] = set()
NOT_MINE: set[str] = set()
ANIK_ALBUM = ""
DERIVED_NAME = r"$^"
CAMERA_NAME = r"$^"











# --------------------------------------------------------------------------
# bulk exports: Google Takeout, Instagram, Facebook
#
# These read extracted archives sitting outside this repository, because a
# Takeout runs to tens of gigabytes and carries whole mailboxes. Nothing is
# copied into the archive. When no export is present every adapter returns
# nothing and says so. Layout, request options and blind spots:
# Journal/Export Ingest - Google Takeout and Meta.md
# --------------------------------------------------------------------------

def local_of(dt):
    """A UTC datetime as (date, HH:MM) in the zone the owner was in at that moment."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    zone = next((z for until, z in TZ_HISTORY if dt < until), TZ_DEFAULT)
    loc = dt.astimezone(zone)
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


# The cache is keyed on the export files, so a change to the parsers would not
# invalidate it on its own. Bump this whenever an export adapter's output changes.
CACHE_VERSION = 25
# Set to the running provider's options before each read, so changing an option (say, turning
# message text on) can never serve a result cached under different options.
CACHE_SALT = ""


def lastfm_cache_path():
    """Where the Last.fm scrobble cache lives (shared with the reader that de-duplicates against it)."""
    return os.path.expanduser(str(PROVIDERS.get("lastfm", {}).get("cache") or os.path.join(CACHE, "lastfm.json")))


def cached(tag, paths, build):
    """Memoise an adapter's facts against the size and mtime of its inputs.

    A single MyActivity.json runs to hundreds of megabytes, so a full run must
    not re-parse an export that has not changed since the last one.
    """
    paths = sorted(paths)
    if not paths:
        return []
    try:
        key = json.dumps([CACHE_VERSION, CACHE_SALT] +
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





















            # No line at all when only the count survives; see above.
















# ------------------------------------------------------------------- Meta ---

def meta_text(s):
    """Meta writes UTF-8 bytes through latin-1, so every accent arrives broken."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s




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




















# Broadcast groups he was added to rather than conversations he had. The web
# design course group alone put 94 lines across ten months, and its title
# carries a tick and a pair of pipes that break the Markdown around them.
META_NOISE_CHATS: list[str] = []





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


















def _hm(seconds):
    m = int(round(seconds / 60.0))
    return "%d h %02d min" % (m // 60, m % 60) if m >= 60 else "%d min" % m




def _hm(ts):
    return epoch_local(ts)[1]




def _hours(sec):
    sec = int(sec)
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm" % (sec // 60)












































ADAPTERS: list = []            # extra always-on readers; tests and embedders may append

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


PROFILE = "journal"


def render_block(date, facts, numbers):
    body = [BEGIN % date, ""]
    if facts:
        body.extend(profiles.shape_day(render_day(facts, numbers), facts, PROFILE))
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


def write_month(ym, byday, apply, emit=None):
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
            refs.append("[^a%d]: %s" % (numbers[src], SOURCES.get(src, src)))
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
        if emit:
            emit(path, None)
        elif apply and exists:
            os.remove(path)
        return
    print("  %s  %s  %2d days, %3d lines, %d sources" % (
        ym, "update" if exists else "CREATE", len(merged), n, len(order)))
    if emit:
        emit(path, out)
    elif apply:
        open(path, "w", encoding="utf-8").write(out)


# A day has four visual bands: daily summaries, the clock-ordered event stream,
# activity lists, then archive artefacts. A coding total and step total describe
# the whole day, so they lead rather than interrupt a moment-by-moment record.
# Messages, searches and media are likewise lists of interactions, not one event
# at a parent bullet's arbitrary time. They are consolidated across services.
DAY_SUMMARY_BASE = ("wakatime", "daily_csv")
DAY_SUMMARIES = list(DAY_SUMMARY_BASE)    # typed adapters may add their own via values["summary"]
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


def run(config, *, apply: bool, only: list[str] | None = None, force: bool = False,
        profile: str | None = None, review: bool = False) -> None:
    """Compile one configured journal. Writing requires an explicit flag."""
    from dossify import workflow

    workflow.run(config, apply=apply, only=only, force=force, profile=profile, review=review)
