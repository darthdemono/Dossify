import os
from pathlib import Path

from dossify import journal
from dossify.sources import daily_csv

COLUMNS = [
    {"column": "steps", "label": "steps"},
    {"columns": ["distance_m", "distance"], "scale": 0.001, "format": "{:.2f} km", "kind": "distance"},
    {"column": "calories", "format": "{} kcal"},
    {"columns": ["duration_min", "duration"], "format": "{} min"},
]


def read(files, **extra):
    daily_csv._O = {"files": files, "title": "Dashboard", "columns": COLUMNS, **extra}
    return daily_csv.a_daily_csv()


def test_numeric_layout(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_text("date,steps,distance_m,calories,duration_min\n2026-01-02,12256,7234,495,135\n")
    assert [f.text for f in read(str(tmp_path))] == ["Dashboard: 12,256 steps (7.23 km; 495 kcal; 135 min)"]


def test_text_layout_is_tidied_and_unit_spaced(tmp_path: Path) -> None:
    (tmp_path / "b.csv").write_text("date,steps,duration,distance,calories\n2026-01-02,5013,1h23m,3KM,205 KCAL\n")
    assert [f.text for f in read(str(tmp_path / "b.csv"))] == ["Dashboard: 5,013 steps (3 km; 205 kcal; 1h 23m)"]


def test_newest_file_wins_per_day_and_bad_rows_are_skipped(tmp_path: Path) -> None:
    old, new = tmp_path / "old.csv", tmp_path / "new.csv"
    old.write_text("date,steps\n2026-01-02,100\n2026-01-03,300\nnot a date,5\n2026-01-04,\n")
    new.write_text("date,steps\n2026-01-02,200\n")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    got = {f.date: f.text for f in read(str(tmp_path / "*.csv"))}
    assert got == {"2026-01-02": "Dashboard: 200 steps", "2026-01-03": "Dashboard: 300 steps"}


def test_custom_date_column_format_and_no_details(tmp_path: Path) -> None:
    (tmp_path / "c.csv").write_text("Day,Count\n05/01/2026,42\n")
    daily_csv._O = {"files": [str(tmp_path / "c.csv")], "date_column": "Day", "date_format": "%d/%m/%Y",
                    "columns": [{"column": "Count", "label": "things"}]}
    assert [(f.date, f.text) for f in daily_csv.a_daily_csv()] == [("2026-01-05", "Daily metrics: 42 things")]


def test_nothing_configured_means_nothing_read(tmp_path: Path) -> None:
    daily_csv._O = {"files": str(tmp_path)}
    assert daily_csv.a_daily_csv() == []


def test_daily_totals_lead_their_day() -> None:
    assert "daily_csv" in journal.DAY_SUMMARY_BASE
