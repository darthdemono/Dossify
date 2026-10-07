"""Play sessions from save-analyser markdown reports.

Options: dir, files, default_game (the game name used before a report names one)."""

import os, re
from collections import defaultdict

from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


NODE = re.compile(r'\["\^(\d+) · ([^"<]*)((?:<br/>[^"]*?)*)"\]')


REF = re.compile(r'^\^(\d+): \[\[([^\]]+)\]\] — _(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})_')


def a_saves():
    root = os.path.expanduser(str(_O.get("dir") or ""))
    out = []
    for fn in _O.get("files", []) if root else []:
        p = os.path.join(root, fn)
        if not os.path.exists(p):
            continue
        text = open(p, encoding="utf-8").read()
        default_game = str(_O.get("default_game") or "")
        refs, game_of, cur_game = {}, {}, default_game
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
            seen[idx] = (refs[idx][0], refs[idx][1], game_of.get(idx, default_game),
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


READERS = {"saves": a_saves}
LABELS = {'saves': 'Play sessions read from save-file analysis reports.'}
