"""Boots, desktop logins, package changes and crashes, from the durable OS log.

Options: crashes.ignore (executable substrings to skip)."""

import os
from collections import Counter, defaultdict
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact, UTC, _hm, _hours, epoch_local
from dossify import oslog

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def _span(on, off):
    """`HH:MM-HH:MM`, with the day offset when a session runs past midnight."""
    if off is None:
        return "%s-" % _hm(on)
    gap = (datetime.fromtimestamp(off, UTC).astimezone(J.TZ_DEFAULT).date()
           - datetime.fromtimestamp(on, UTC).astimezone(J.TZ_DEFAULT).date()).days
    return "%s-%s%s" % (_hm(on), _hm(off), " +%dd" % gap if gap else "")


def a_boots():
    """When the machine was on, one line a day. Sessions come from the durable
    OS log (wtmp reaches back further than the journal) and short bursts of
    power cycling collapse to a count and a total instead of a line each."""
    rows = sorted(oslog.load(J.OS_LOG_DIR, "boots"), key=lambda r: r["on"])
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
    for r in oslog.load(J.OS_LOG_DIR, "logins"):
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
    for r in oslog.load(J.OS_LOG_DIR, "dnf"):
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
    for r in oslog.load(J.OS_LOG_DIR, "crashes"):
        date, time = epoch_local(r["ts"])
        if date and not any(i in r["exe"] for i in _O.get("ignore", [])):
            byday[date].append((time, os.path.basename(r["exe"]) or "unknown"))
    return [Fact(date, min(t for t, _n in rows), "Crashed: " + ", ".join(
        "%s x%d" % (n, c) if c > 1 else n
        for n, c in Counter(n for _t, n in rows).items()), "crashes")
        for date, rows in byday.items()]


READERS = {"boots": a_boots, "logins": a_logins, "dnf": a_dnf, "crashes": a_crashes}
LABELS = {'boots': 'Machine power sessions from the OS log.', 'logins': 'Desktop logins from the OS log.', 'dnf': 'Package changes from the OS log.', 'crashes': 'Program crashes from the OS log.'}
