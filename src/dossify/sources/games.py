"""Game plays kept in the durable OS log.

No options."""

from collections import defaultdict

from dossify import journal as J
from dossify.journal import Fact, _hours, epoch_local
from dossify import oslog

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_games():
    """Plays kept in the durable OS log. Each launcher keeps only the latest play
    per game, so the log is what turns that into a history. Minecraft sessions
    (from its own game logs) fold into one line per instance a day; a launch
    within five minutes of a logged session is the same play."""
    label = {"steam": "Steam", "heroic": "Heroic", "epic": "Epic", "gog": "GOG",
             "lutris": "Lutris", "bottles": "Bottles", "minecraft": "Minecraft"}
    byday = defaultdict(lambda: defaultdict(list))
    seen = set()
    rows_all = oslog.load(J.OS_LOG_DIR, "games")
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


READERS = {"games": a_games}
LABELS = {'games': 'Game plays from launcher logs.'}
