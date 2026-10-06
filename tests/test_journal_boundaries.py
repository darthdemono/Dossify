from dossify.journal import Fact, rebuild_day


def test_rebuild_day_preserves_manual_and_llm_sections_verbatim() -> None:
    manual = "Woke up late, ate dinner, then moved house."
    llm = "A private reflection stays here too."
    existing = [
        "## 2026-01-01",
        "",
        "#### Manual",
        "",
        manual,
        "",
        "",
        "",
        "",
        "",
        "#### LLM",
        "",
        llm,
        "",
        "#### Auto generated",
        "",
        "<!-- auto:begin 2026-01-01 -->",
        "- old generated line",
        "<!-- auto:end -->",
    ]

    rebuilt = rebuild_day("2026-01-01", existing, [Fact("2026-01-01", "12:00", "New event", "test")], {"test": 1})
    text = "\n".join(rebuilt)

    assert f"{manual}\n\n\n\n\n" in text
    assert llm in text
    assert "- old generated line" not in text
    assert "- 12:00 · New event[^a1]" in text


def test_navidrome_and_lastfm_share_one_listened_list() -> None:
    from dossify.journal import render_day

    facts = [
        Fact("2026-01-01", None, "Tracks scrobbled:\n    - 02:55 - 2 tracks by Radiohead", "lastfm"),
        Fact("2026-01-01", "03:30", "Let Down by Alessandro Veloz", "navidrome"),
    ]
    out = "\n".join(render_day(facts, {"lastfm": 1, "navidrome": 2}))
    assert out.count("Listened to:") == 1
    assert "Played in Navidrome" not in out
    assert "(Navidrome)" in out and "[^a1][^a2]" in out


def test_identical_timed_lines_collapse_but_distinct_ones_stay() -> None:
    from dossify.journal import collapse

    posts = [Fact("2026-01-01", "%02d:00" % h, "Posted on Instagram", "instagram") for h in range(5)]
    other = Fact("2026-01-01", "09:30", "Installed Penny", "takeout")
    out = collapse(posts + [other])
    assert [f.text for f in out] == ["Posted on Instagram x5 (to 04:00)", "Installed Penny"]
    assert collapse(posts[:3]) == posts[:3]


def test_shell_history_keeps_command_names_only() -> None:
    from dossify.oslog import shell_command

    assert shell_command("sudo TOKEN=abc git push origin main") == "git"
    assert shell_command("/usr/bin/curl -H 'Authorization: Bearer sk-live-123' x") == "curl"
    assert shell_command("sk" + "_live_" + "x" * 24) == ""   # built at runtime so scanners do not flag the test


def test_oslog_merge_never_duplicates_or_forgets(tmp_path) -> None:
    from dossify.oslog import load, merge

    d = str(tmp_path)
    assert merge(d, "dnf", [{"id": 1, "ts": 5}, {"id": 2, "ts": 9}], lambda r: r["id"], "ts") == 2
    assert merge(d, "dnf", [{"id": 2, "ts": 9}, {"id": 3, "ts": 12}], lambda r: r["id"], "ts") == 1
    assert [r["id"] for r in load(d, "dnf")] == [1, 2, 3]


def test_heroic_and_steam_rows_merge_into_the_games_log(tmp_path) -> None:
    import json as _json
    from dossify.oslog import heroic, steam

    root = tmp_path / ".config" / "heroic"
    (root / "store").mkdir(parents=True)
    (root / "sideload_apps").mkdir()
    (root / "store" / "timestamp.json").write_text(_json.dumps(
        {"abc": {"lastPlayed": "2026-06-20T03:37:44.011Z", "totalPlayed": 20}}))
    (root / "sideload_apps" / "library.json").write_text(_json.dumps(
        {"games": [{"app_name": "abc", "title": "Factorio"}]}))
    row = heroic(str(tmp_path), {})[0]
    assert row["name"] == "Factorio" and row["played_s"] == 1200 and row["instance"] == "heroic:abc"

    cfg = tmp_path / ".local" / "share" / "Steam" / "userdata" / "1" / "config"
    cfg.mkdir(parents=True)
    (cfg / "localconfig.vdf").write_text('\n\t\t"480"\n\t\t{\n\t\t\t"LastPlayed"\t\t"1750021527"\n\t\t\t"Playtime"\t\t"10"\n\t\t}\n')
    row = steam(str(tmp_path), {"steam:480": "Spacewar"})[0]
    assert row["name"] == "Spacewar" and row["played_s"] == 600


def test_minecraft_sessions_read_rotated_logs(tmp_path) -> None:
    import gzip
    from dossify.oslog import minecraft_sessions

    logs = tmp_path / "minecraft" / "logs"
    logs.mkdir(parents=True)
    with gzip.open(logs / "2026-05-20-1.log.gz", "wt") as fh:
        fh.write("[22:45:01] [main/INFO]: start\n[23:25:24] [Client thread/WARN]: end\n")
    with gzip.open(logs / "2026-05-21-1.log.gz", "wt") as fh:
        fh.write("[23:50:00] [main/INFO]: start\n[00:10:00] [main/INFO]: end\n")
    rows = minecraft_sessions(str(tmp_path), "RLCraft", "mc:RLCraft")
    assert [r["played_s"] for r in rows] == [2423, 1200]


def test_bottles_sessions_come_from_process_metrics(tmp_path) -> None:
    import sqlite3 as _sq
    from dossify.oslog import bottles

    db = tmp_path / ".var/app/com.usebottles.bottles/data/bottles"
    db.mkdir(parents=True)
    con = _sq.connect(db / "process_metrics.sqlite")
    con.execute("create table sessions (bottle_name, program_id, program_name, started_at, duration_seconds)")
    con.execute("insert into sessions values ('b1', 'p1', 'Setup.exe', 1777814352, 71)")
    con.commit()
    row = bottles(str(tmp_path))[0]
    assert row["name"] == "Setup.exe (b1)" and row["played_s"] == 71 and row["ts"] == 1777814352


def test_prism_and_modrinth_minecraft_rows(tmp_path) -> None:
    import sqlite3 as _sq
    from dossify.oslog import games, modrinth

    inst = tmp_path / ".local/share/PrismLauncher/instances/Pack"
    inst.mkdir(parents=True)
    (inst / "instance.cfg").write_text("lastLaunchTime=1777653438494\nlastTimePlayed=1682\nname=Pack\n")
    row = games(str(tmp_path))[0]
    assert row["instance"] == "mc:prism:Pack" and row["ts"] == 1777653438 and row["played_s"] == 1682

    db = tmp_path / ".var/app/com.modrinth.ModrinthApp/data/ModrinthApp"
    db.mkdir(parents=True)
    con = _sq.connect(db / "app.db")
    con.execute("create table instances (name, last_played, submitted_time_played)")
    con.execute("insert into instances values ('Cool Pack', 1790000000, 600)")
    con.commit()
    assert modrinth(str(tmp_path))[0]["instance"] == "mc:modrinth:Cool Pack"


def test_steam_sessions(tmp_path):
    from dossify import oslog
    logs = tmp_path / ".local/share/Steam/logs"
    logs.mkdir(parents=True)
    (logs / "content_log.txt").write_text(
        "[2026-07-05 00:09:01] AppID 730 state changed : Fully Installed,App Running,\n"
        "[2026-07-05 00:09:01] AppID 730 state changed : Fully Installed,App Running,\n"
        "[2026-07-05 00:35:52] AppID 730 state changed : Fully Installed,\n")
    (logs.parent / "steamapps").mkdir()
    rows = oslog.steam_sessions(str(tmp_path), {"steam:730": "Counter-Strike 2"})
    assert len(rows) == 1 and rows[0]["sess_s"] == 26 * 60 + 51 and rows[0]["name"] == "Counter-Strike 2"
