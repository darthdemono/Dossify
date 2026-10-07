import contextlib
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from dossify import conformance, journal, unified
from dossify.config import load_config
from dossify.integrations import OPTIONAL_ADAPTERS
from dossify.integrations import elteportal as elte
from dossify.pipeline import build_plan

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART:20260310T080000Z
SUMMARY:Algorithms Lecture
LOCATION:Room 1
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Budapest:20260311T101500
SUMMARY:Python Practice
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20260312
SUMMARY:Reading Day
END:VEVENT
BEGIN:VEVENT
DTSTART:20990101T080000Z
SUMMARY:Far Future
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def fake_library(monkeypatch):
    """A stand-in for the EltePortal package, so these tests need nothing installed."""
    package = types.ModuleType("elteportal")
    canvas = types.ModuleType("elteportal.canvas")
    config = types.ModuleType("elteportal.config")

    class Client:
        def __init__(self, profile_path=None, config_path=None):
            self.profile, self.settings = {"name": "Example University"}, {}

    canvas.base_url = lambda: "https://canvas.example.edu/api/v1"
    canvas.token = lambda: "secret-token"
    canvas.courses = lambda tok, states=(): [{"id": 5, "name": " Web Programming "}]
    canvas.assignments_with_submission = lambda tok, cid: [
        {"id": 9, "name": "Homework 1", "points_possible": 10.0,
         "submission": {"submitted_at": "2026-03-01T09:30:00Z", "graded_at": "2026-03-05T12:00:00Z",
                        "score": 6.59047619047619}},
        {"id": 10, "name": "Ungraded", "submission": {"submitted_at": "2026-03-02T09:30:00Z", "score": None}},
        {"id": 11, "name": "Untouched", "submission": {}}]
    config.use = lambda profile, settings=None: contextlib.nullcontext()
    package.Client, package.canvas, package.config = Client, canvas, config
    for name, module in (("elteportal", package), ("elteportal.canvas", canvas), ("elteportal.config", config)):
        monkeypatch.setitem(sys.modules, name, module)
    return canvas


def test_timetable_converts_times_skips_the_future_and_keeps_all_day_events() -> None:
    facts = elte.timetable(ICS, "2026-10-07", "x.ics", ZoneInfo("Europe/Budapest"))
    assert [f.display for f in facts] == [
        "Scheduled: Algorithms Lecture (Room 1)", "Scheduled: Python Practice", "Scheduled: Reading Day"]
    assert facts[0].observed_at.isoformat() == "2026-03-10T08:00:00+00:00"
    assert facts[1].observed_at.utcoffset().total_seconds() == 3600
    assert facts[2].time_precision.value == "day"


def test_floating_times_are_read_in_the_configured_zone() -> None:
    floating = ICS.replace("DTSTART;TZID=Europe/Budapest:20260311T101500", "DTSTART:20260311T101500")
    facts = elte.timetable(floating, "2026-10-07", "x.ics", ZoneInfo("Asia/Tokyo"))
    assert facts[1].observed_at.utcoffset().total_seconds() == 9 * 3600


def test_canvas_facts_round_scores_and_never_carry_the_token(fake_library) -> None:
    facts = elte.canvas_facts(fake_library, "secret-token", True, True)
    texts = [f.display for f in facts]
    assert "Submitted on Canvas: Homework 1 (Web Programming)" in texts
    assert "Canvas grade: Homework 1, 6.59/10 (Web Programming)" in texts
    assert len(facts) == 3 and "secret-token" not in repr(facts)
    assert [f.event_type for f in elte.canvas_facts(fake_library, "t", False, True)] == ["education.graded"]


def test_adapter_conforms_and_declares_the_profile_host(tmp_path: Path, fake_library) -> None:
    ics = tmp_path / "neptun.ics"
    ics.write_text(ICS, encoding="utf-8")
    config = elte.ElteConfig(neptun_ics=ics)
    assert conformance.check(elte.ADAPTER, config) == []
    plan = build_plan(elte.ADAPTER, config)
    assert plan.permissions.network_hosts == ("canvas.example.edu",)
    assert plan.permissions.read_paths == (str(ics.resolve()),)


def test_without_the_library_the_plan_says_how_to_install_it(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "elteportal", None)       # makes `import elteportal` fail
    with pytest.raises(ImportError, match="uv sync --extra elte"):
        build_plan(elte.ADAPTER, elte.ElteConfig())
    assert elte.ADAPTER.diagnose(elte.ElteConfig()) == [(False, "EltePortal library installed", elte.INSTALL_HINT)]


def test_a_missing_library_is_a_recorded_failure_not_a_crash(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "elteportal", None)
    (tmp_path / "Journal").mkdir()
    (tmp_path / "dossify.toml").write_text('output_dir = "Journal"\n[providers.elteportal]\n')
    config = load_config(tmp_path / "dossify.toml")
    journal.configure(config)
    facts, outcomes, _ = unified.collect(config, journal, [])
    assert facts == [] and outcomes[0].status == "failed" and "uv sync --extra elte" in outcomes[0].error


def test_diagnose_reports_each_connection_check_without_a_credential(tmp_path: Path, fake_library) -> None:
    rows = elte.ADAPTER.diagnose(elte.ElteConfig(neptun_ics=tmp_path / "absent.ics"))
    assert rows[0] == (True, "EltePortal library installed", "")
    assert (True, "profile loaded (Example University)", "") in rows and (True, "Canvas token resolves", "") in rows
    assert rows[-1][0] is False and "absent.ics" in rows[-1][1]
    assert "secret-token" not in repr(rows)

    def refuse():
        raise RuntimeError("no token")

    fake_library.token = refuse
    assert any(ok is False and label == "Canvas token resolves" for ok, label, _ in elte.ADAPTER.diagnose(elte.ElteConfig()))


def test_the_adapter_is_bundled_as_optional_and_needs_no_install_to_import() -> None:
    assert "elteportal" in OPTIONAL_ADAPTERS
    from dossify.providers import maturity_of, tier_of

    assert tier_of("elteportal") == "optional" and maturity_of("elteportal") == "stable_typed"


def test_fact_dates_follow_the_configured_timezone(tmp_path: Path) -> None:
    (tmp_path / "Journal").mkdir()
    (tmp_path / "dossify.toml").write_text('output_dir = "Journal"\ntimezone = "Asia/Tokyo"\n')
    journal.configure(load_config(tmp_path / "dossify.toml"))
    fact = elte.timetable("BEGIN:VEVENT\nDTSTART:20260310T230000Z\nSUMMARY:Late\nEND:VEVENT\n", "2026-10-07", "x",
                          journal.TZ_DEFAULT)[0]
    from dossify.legacy_adapters import from_typed

    assert from_typed(fact, journal.Fact).date == "2026-03-11"       # 23:00 UTC is already the 11th in Tokyo
    assert datetime(2026, 3, 10, 23, tzinfo=UTC) == fact.observed_at
