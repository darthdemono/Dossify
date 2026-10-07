"""Durable operating-system logs, kept outside the profile.

The journal adapters used to read `journalctl`, `dnf history` and the launcher
configs directly, so a reset of the profile or an expired journal took the
history with it. `harvest` copies those records into append-only JSONL files in
a log directory on another disk, merged by a stable key so a re-run never
duplicates and never forgets, and commits every change to a git repository in
that directory. The adapters read only the log directory.

Every record stores epoch seconds, never a local time string, so the files mean
the same thing on any machine.
"""

from __future__ import annotations

import glob
import gzip
import json
import os
import re
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("UTC")     # set to the configured timezone by journal.configure()
FILES = ("boots", "logins", "dnf", "crashes", "games")
LAST_TIME = r"\w{3} \w{3}\s+\d+ \d\d:\d\d:\d\d \d{4}"
README = """# OS logs

Written by `dossify journal --apply` and `dossify oslog`. One JSONL file per source,
sorted, one record per line, merged by key so re-running never duplicates.
Times are epoch seconds.

boots.jsonl   on, off, end (down|crash|running), kernel   from wtmp (`last -x`)
logins.jsonl  user, tty, start, end                       from wtmp
dnf.jsonl     id, ts, cmd, n                              from `dnf history list`
crashes.jsonl ts, exe, sig, pid                           from `coredumpctl`
games.jsonl   store, instance, name, ts, played_s         from FreesmLauncher and PrismLauncher (+ their game logs), Modrinth App, Steam, Heroic, Lutris, Bottles, Epic launcher logs
"""


def _epoch(text: str) -> int:
    return int(datetime.strptime(" ".join(text.split()), "%a %b %d %H:%M:%S %Y")
               .replace(tzinfo=LOCAL).timestamp())


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return ""


def load(logdir: str, name: str) -> list[dict]:
    path = Path(logdir, name + ".jsonl")
    if not logdir or not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def merge(logdir: str, name: str, new: list[dict], key, order: str, drop=None) -> int:
    """Fold `new` into the file by key (new wins) and return how many keys are new."""
    old = {key(r): r for r in load(logdir, name) if not (drop and drop(r))}
    before = len(old)
    for r in new:
        old[key(r)] = r
    rows = sorted(old.values(), key=lambda r: (r.get(order) or 0, json.dumps(r, sort_keys=True)))
    text = "".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows)
    path = Path(logdir, name + ".jsonl")
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return len(old) - before


def boots() -> list[dict]:
    out = []
    for line in _run("last", "-x", "-F", "-w", "reboot").splitlines():
        m = re.match(r"reboot\s+system boot\s+(\S+)\s+(%s)(?:\s+-\s+(?:(%s)|(crash|down)))?"
                     % (LAST_TIME, LAST_TIME), line)
        if not m:
            continue
        kernel, on, off, flag = m.groups()
        running = "still running" in line
        out.append({"on": _epoch(on), "off": _epoch(off) if off else None,
                    "end": "running" if running else (flag or "down"), "kernel": kernel})
    return out


def logins() -> list[dict]:
    out = []
    for line in _run("last", "-F", "-w").splitlines():
        m = re.match(r"(\S+)\s+(pts/\d+|tty\d+|seat\d+\S*)\s+(\S+)\s+(%s)(?:\s+-\s+(%s|down|crash))?"
                     % (LAST_TIME, LAST_TIME), line)
        if not m or m.group(1) in ("reboot", "shutdown"):
            continue
        user, tty, _host, start, end = m.groups()
        out.append({"user": user, "tty": tty, "start": _epoch(start),
                    "end": _epoch(end) if end and end[0].isalpha() and end not in ("down", "crash") else None})
    return out


def dnf() -> list[dict]:
    out = []
    for line in _run("dnf", "history", "list").splitlines():
        m = re.match(r"(\d+)\s+(.+?)\s+(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\s+(\d+)\s*$", line)
        if m:
            out.append({"id": int(m.group(1)), "cmd": m.group(2).strip(),
                        "ts": int(datetime.strptime(m.group(3), "%Y-%m-%d %H:%M:%S")
                                  .replace(tzinfo=LOCAL).timestamp()), "n": int(m.group(4))})
    return out


def crashes(ignore: list[str]) -> list[dict]:
    try:
        rows = json.loads(_run("coredumpctl", "list", "--json=short") or "[]")
    except ValueError:
        return []
    return [{"ts": int(r["time"] // 1_000_000), "exe": r.get("exe") or "", "sig": r.get("sig"),
             "pid": r.get("pid")} for r in rows
            if not any(i in (r.get("exe") or "") for i in ignore)]


def minecraft_sessions(inst_dir: str, name: str, iid: str) -> list[dict]:
    """One row per rotated game log: the file date plus the first and last clock
    time inside it (the game writes local time). Gives a real history, where the
    launcher keeps only the latest launch."""
    out = []
    for gz in sorted(glob.glob(os.path.join(inst_dir, "minecraft", "logs", "????-??-??-*.log.gz"))):
        day = os.path.basename(gz)[:10]
        try:
            with gzip.open(gz, "rt", encoding="utf-8", errors="replace") as fh:
                times = [m.group(1) for m in (re.match(r"\[(\d\d:\d\d:\d\d)\]", l) for l in fh) if m]
        except (OSError, EOFError):
            continue
        if not times:
            continue
        start = int(datetime.strptime(day + " " + times[0], "%Y-%m-%d %H:%M:%S")
                    .replace(tzinfo=LOCAL).timestamp())
        end = int(datetime.strptime(day + " " + times[-1], "%Y-%m-%d %H:%M:%S")
                  .replace(tzinfo=LOCAL).timestamp())
        if end < start:                       # ran past midnight
            end += 86400
        out.append({"store": "minecraft", "instance": iid, "name": name, "ts": start,
                    "played_s": end - start})
    return out


MC_LAUNCHERS = (("FreesmLauncher", "mc:"), ("PrismLauncher", "mc:prism:"))


def games(home: str) -> list[dict]:
    """Minecraft from the Prism family. FreesmLauncher is a Prism fork with the
    same layout, so one reader covers both; the instance id carries the launcher
    so a copied instance is two ids, and the journal shows the same play once."""
    out = []
    for launcher, prefix in MC_LAUNCHERS:
        for cfg in sorted(glob.glob(os.path.join(
                home, ".local", "share", launcher, "instances", "*", "instance.cfg"))):
            vals = {}
            try:
                for line in open(cfg, encoding="utf-8", errors="replace"):
                    if "=" in line:
                        k, v = line.split("=", 1)
                        vals[k.strip()] = v.strip()
            except OSError:
                continue
            folder = os.path.basename(os.path.dirname(cfg))
            name, iid = vals.get("name") or folder, prefix + folder
            out += minecraft_sessions(os.path.dirname(cfg), name, iid)
            ms = vals.get("lastLaunchTime", "")
            if ms.isdigit():                  # the latest launch, still in latest.log
                last = int(vals["lastTimePlayed"]) if vals.get("lastTimePlayed", "").isdigit() else None
                out.append({"store": "minecraft", "instance": iid, "name": name,
                            "ts": int(ms) // 1000, "played_s": last})
    return out


def modrinth(home: str) -> list[dict]:
    """Modrinth App keeps `last_played` and `submitted_time_played` per instance
    in `app.db` (`profiles` before 0.19). **No row has ever existed on this
    machine, so the units (unix seconds) are the app's documented ones, not seen.**"""
    path = os.path.join(home, ".var", "app", "com.modrinth.ModrinthApp", "data", "ModrinthApp", "app.db")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except sqlite3.Error:
        return []
    out = []
    for table in ("instances", "profiles"):
        try:
            rows = con.execute("select name, last_played, submitted_time_played from %s "
                               "where last_played is not null and last_played > 0" % table).fetchall()
        except sqlite3.Error:
            continue
        out += [{"store": "minecraft", "instance": "mc:modrinth:" + n, "name": n, "ts": int(t),
                 "played_s": int(p) if p else None} for n, t, p in rows]
    return out


def lutris(home: str) -> list[dict]:
    """Lutris' own database: last played and total hours per game, which is also
    where the Epic Games Launcher's wine prefix lives."""
    path = os.path.join(home, ".local", "share", "lutris", "pga.db")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        rows = con.execute("select name, lastplayed, playtime from games "
                           "where lastplayed is not null and lastplayed > 0").fetchall()
    except sqlite3.Error:
        return []
    return [{"store": "lutris", "instance": "lutris:" + n, "name": n, "ts": int(t),
             "played_s": int(h * 3600) if h else None} for n, t, h in rows]


def bottles(home: str) -> list[dict]:
    """Bottles records every program run in its bottles with start, end and
    duration in `process_metrics.sqlite`, so this is a true session history."""
    path = os.path.join(home, ".var", "app", "com.usebottles.bottles", "data", "bottles",
                        "process_metrics.sqlite")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
        rows = con.execute("select bottle_name, program_id, program_name, started_at, "
                           "duration_seconds from sessions where started_at is not null").fetchall()
    except sqlite3.Error:
        return []
    return [{"store": "bottles", "instance": "bottles:%s:%s" % (b, pid), "ts": int(t),
             "name": "%s (%s)" % (n, b), "played_s": int(d) if d is not None else None}
            for b, pid, n, t, d in rows]


def epic_launcher(home: str) -> list[dict]:
    """Epic Games Launcher sessions: every launcher log opens with
    `Log file open, MM/DD/YY HH:MM:SS` in local time."""
    out = []
    for log in glob.glob(os.path.join(home, "Documents", "EpicGamesLauncher", "Saved", "Logs",
                                      "EpicGamesLauncher*.log")):
        try:
            head = open(log, encoding="utf-8", errors="replace").read(4000)
        except OSError:
            continue
        m = re.search(r"Log file open, (\d\d)/(\d\d)/(\d\d) (\d\d:\d\d:\d\d)", head)
        if m:
            mo, d, y, t = m.groups()
            out.append({"store": "epic", "instance": "epic:launcher", "name": "Epic Games Launcher",
                        "ts": int(datetime.strptime("20%s-%s-%s %s" % (y, mo, d, t), "%Y-%m-%d %H:%M:%S")
                                  .replace(tzinfo=LOCAL).timestamp()), "played_s": None})
    return out


def _steam_names(root: str) -> dict[str, str]:
    """appid -> name from every readable library's appmanifests."""
    names, libs = {}, {root}
    try:
        libs |= set(re.findall(r'"path"\s+"([^"]+)"',
                               open(os.path.join(root, "steamapps", "libraryfolders.vdf"),
                                    encoding="utf-8", errors="replace").read()))
    except OSError:
        pass
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                t = open(acf, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            a, n = re.search(r'"appid"\s+"(\d+)"', t), re.search(r'"name"\s+"([^"]*)"', t)
            if a and n:
                names[a.group(1)] = n.group(1)
    return names


NOT_TITLES = {"shared", "title", "default"}      # prefix folder names that name no game
STEAM_TOOLS = re.compile(r"^(Steam Linux Runtime|Proton|Steamworks Common)")


def names_skip(names: dict[str, str]) -> set[str]:
    """App ids that are Steam's own runtimes, which nobody launched."""
    return {a for a, n in names.items() if STEAM_TOOLS.match(n)}


def steam_title(app: str) -> str:
    """Store name for an app no local manifest describes. One short request per
    unknown game, and only until the name is in the log; failure just leaves the id."""
    import urllib.request
    try:
        with urllib.request.urlopen(
                "https://store.steampowered.com/api/appdetails?appids=%s&filters=basic" % app,
                timeout=10) as r:
            return str(json.load(r)[app]["data"]["name"])
    except Exception:
        return ""


def steam(home: str, known: dict[str, str]) -> list[dict]:
    """One row per game Steam has ever recorded a last-played time for. Steam
    keeps only the latest launch per game, so history exists from harvest onward."""
    out = []
    for root in (os.path.join(home, ".local", "share", "Steam"),
                 os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")):
        names = _steam_names(root)
        for cfg in glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf")):
            try:
                t = open(cfg, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            for app, last, play in re.findall(
                    r'\n\t+"(\d+)"\n\t+\{\n\t+"LastPlayed"\s+"(\d+)"(?:\n\t+"Playtime"\s+"(\d+)")?', t):
                if int(last) > 0 and app not in names_skip(names):
                    iid = "steam:" + app
                    out.append({"store": "steam", "instance": iid, "ts": int(last),
                                "name": names.get(app) or (known.get(iid) if not known.get(iid, "Steam app").startswith("Steam app") else "")
                                        or steam_title(app) or "Steam app " + app,
                                "played_s": int(play) * 60 if play else None})
    return out


def steam_sessions(home: str, known: dict[str, str]) -> list[dict]:
    """Sessions from Steam's content_log: an app's state gains `App Running` at
    launch and loses it (or says Terminating) at exit. The log rotates, so the
    durable merge is what keeps older sessions."""
    out = []
    for root in (os.path.join(home, ".local", "share", "Steam"),
                 os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam")):
        names, run = _steam_names(root), {}
        skip = names_skip(names)
        for fn in ("content_log.previous.txt", "content_log.txt"):
            try:
                lines = open(os.path.join(root, "logs", fn), encoding="utf-8", errors="replace")
            except OSError:
                continue
            for ln in lines:
                m = re.match(r"\[([\d-]+ [\d:]+)\] AppID (\d+) state changed : (.*)", ln)
                if not m:
                    continue
                ts, app, st = int(datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=LOCAL).timestamp()), m[2], m[3]
                live = "App Running" in st and "Terminating" not in st
                if live and app not in run:
                    run[app] = ts
                elif not live and app in run:
                    start = run.pop(app)
                    iid = "steam:" + app
                    if app not in skip:
                        out.append({"store": "steam", "instance": iid, "ts": start, "sess_s": max(ts - start, 0),
                                    "name": names.get(app) or known.get(iid) or steam_title(app) or "Steam app " + app})
    return out


def heroic(home: str, known: dict[str, str]) -> list[dict]:
    """Heroic's own timestamp.json (first/last played, total minutes) joined to
    the titles in its library caches."""
    out = []
    for root in (os.path.join(home, ".config", "heroic"),
                 os.path.join(home, ".var", "app", "com.heroicgameslauncher.hgl", "config", "heroic")):
        try:
            stamps = json.load(open(os.path.join(root, "store", "timestamp.json"), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        titles, runner = {}, {}
        for rel in ("store_cache/gog_library.json", "store_cache/legendary_library.json",
                    "store_cache/nile_library.json", "sideload_apps/library.json"):
            try:
                blob = json.load(open(os.path.join(root, rel), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = blob.get("games") or blob.get("library") or []
            for g in rows if isinstance(rows, list) else []:
                if isinstance(g, dict) and g.get("app_name") and g.get("title"):
                    titles[g["app_name"]] = g["title"]
                    runner[g["app_name"]] = {"gog": "gog", "legendary": "epic"}.get(g.get("runner"), "heroic")
        for meta in glob.glob(os.path.join(root, "legendaryConfig", "legendary", "metadata", "*.json")):
            try:
                m = json.load(open(meta, encoding="utf-8"))
                titles.setdefault(m["app_name"], m["app_title"])
                runner.setdefault(m["app_name"], "epic")
            except (OSError, ValueError, KeyError):
                continue
        for app, v in stamps.items():
            last = v.get("lastPlayed")
            if not last:
                continue
            if app not in titles:               # a sideloaded game's prefix is named after it
                try:
                    prefix = json.load(open(os.path.join(root, "GamesConfig", app + ".json"),
                                            encoding="utf-8"))
                    prefix = (prefix.get(app) or prefix).get("winePrefix") or ""
                    if "/Prefixes/" in prefix and os.path.basename(prefix).lower() not in NOT_TITLES:
                        titles[app] = os.path.basename(prefix)
                except (OSError, ValueError, AttributeError):
                    pass
            iid = "heroic:" + app
            out.append({"store": runner.get(app, "heroic"), "instance": iid,
                        "ts": int(datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp()),
                        "name": titles.get(app) or (known.get(iid) if known.get(iid, "").lower() not in NOT_TITLES else "") or "Heroic game " + app,
                        "played_s": int(v.get("totalPlayed") or 0) * 60})
    return out


def git_commit(logdir: str, message: str) -> bool:
    def git(*a):
        return subprocess.run(["git", "-C", logdir, "-c", "user.name=dossify",
                               "-c", "user.email=dossify@localhost", *a],
                              capture_output=True, text=True, timeout=60)
    if not os.path.isdir(os.path.join(logdir, ".git")):
        git("init", "-q")
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return False
    return git("commit", "-q", "-m", message).returncode == 0


def harvest(logdir: str, home: str, crash_ignore: list[str] | None = None) -> dict[str, int]:
    """Merge today's system state into the log directory and commit the change."""
    Path(logdir).mkdir(parents=True, exist_ok=True)
    readme = Path(logdir, "README.md")
    if not readme.exists():
        readme.write_text(README, encoding="utf-8")
    known = {r["instance"]: r["name"] for r in load(logdir, "games")}
    added = {
        "boots": merge(logdir, "boots", boots(), lambda r: r["on"], "on"),
        "logins": merge(logdir, "logins", logins(), lambda r: (r["tty"], r["start"]), "start"),
        "dnf": merge(logdir, "dnf", dnf(), lambda r: r["id"], "ts"),
        "crashes": merge(logdir, "crashes", crashes(crash_ignore or []),
                         lambda r: (r["ts"], r["pid"]), "ts"),
        "games": merge(logdir, "games", games(home) + modrinth(home) + steam(home, known) + steam_sessions(home, known) + heroic(home, known)
                       + lutris(home) + bottles(home) + epic_launcher(home),
                       lambda r: (r["instance"], r["ts"]), "ts",
                       drop=lambda r: "store" not in r),     # pre-store Minecraft rows
    }
    summary = ", ".join("%s +%d" % kv for kv in added.items() if kv[1])
    if summary:
        git_commit(logdir, "harvest: " + summary)
    elif git_commit(logdir, "harvest: refresh"):
        summary = "refresh"
    return added
