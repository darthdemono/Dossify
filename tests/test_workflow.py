import json
from pathlib import Path

import pytest

from dossify import journal, ledger, workflow
from dossify.config import load_config
from dossify.journal import Fact


def workspace(tmp_path: Path, monkeypatch, extra: str = ""):
    (tmp_path / "Journal").mkdir()
    (tmp_path / "People.json").write_text("{}")
    (tmp_path / "dossify.toml").write_text(
        'people_file = "People.json"\noutput_dir = "Journal"\nledger_dir = "runs"\n' + extra +
        '\n[journal]\nworkspace_root = "."\ncache_dir = "cache"\n')

    def a_fake():
        return [Fact("2026-02-03", "09:00", "Did a thing", "fake"),
                Fact("2026-02-03", "10:00", "Did another", "other")]

    monkeypatch.setattr(journal, "ADAPTERS", [a_fake])
    monkeypatch.setattr(journal, "track_journal", lambda label: None)
    return load_config(tmp_path / "dossify.toml")


def test_dry_run_writes_nothing_and_records_nothing(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    workflow.run(config, apply=False)
    assert not list((tmp_path / "Journal").glob("*.md")) and not (tmp_path / "runs").exists()


def test_review_apply_undo_round_trip(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    workflow.run(config, apply=False, review=True)
    assert not list((tmp_path / "Journal").glob("*.md"))
    run = ledger.latest(tmp_path / "runs")
    assert run.manifest["mode"] == "reviewed" and run.manifest["months"][0]["action"] == "create"
    assert [a["name"] for a in run.manifest["adapters"]] == ["fake"]
    workflow.apply_run(config, run.manifest["run_id"])
    month = tmp_path / "Journal" / "2026-02.md"
    assert "Did a thing" in month.read_text()
    assert ledger.latest(tmp_path / "runs").manifest["mode"] == "applied"
    workflow.undo_run(config, run.manifest["run_id"])
    assert not month.exists()


def test_apply_refuses_when_file_changed_after_review(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    (tmp_path / "Journal" / "2026-02.md").write_text("typed by hand\n")
    workflow.run(config, apply=False, review=True)
    run = ledger.latest(tmp_path / "runs")
    (tmp_path / "Journal" / "2026-02.md").write_text("typed by hand, then more\n")
    with pytest.raises(SystemExit, match="changed since review"):
        workflow.apply_run(config, run.manifest["run_id"])


def test_undo_refuses_after_later_edit(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    workflow.run(config, apply=True)
    run = ledger.latest(tmp_path / "runs")
    month = tmp_path / "Journal" / "2026-02.md"
    month.write_text(month.read_text() + "\nlater edit\n")
    with pytest.raises(SystemExit, match="edited since"):
        workflow.undo_run(config, run.manifest["run_id"])


def test_failed_source_is_recorded_not_fatal(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)

    def a_broken():
        raise RuntimeError("export vanished")

    monkeypatch.setattr(journal, "ADAPTERS", [*journal.ADAPTERS, a_broken])
    workflow.run(config, apply=False, review=True)
    outcomes = {a["name"]: a for a in ledger.latest(tmp_path / "runs").manifest["adapters"]}
    assert outcomes["broken"]["status"] == "failed" and "export vanished" in outcomes["broken"]["error"]
    assert outcomes["fake"]["status"] == "ok"


def test_privacy_policy_reaches_the_journal_and_ledger(tmp_path, monkeypatch) -> None:
    config = workspace(
        tmp_path, monkeypatch,
        '[privacy]\npreset = "minimal"\n[privacy.classes]\nmedia_titles = "hidden"\n')

    def a_navidrome():
        return [Fact("2026-02-03", None, "Played a song", "navidrome")]

    monkeypatch.setattr(journal, "ADAPTERS", [a_navidrome])
    workflow.run(config, apply=True)
    month = tmp_path / "Journal" / "2026-02.md"
    assert not month.exists() or "Played a song" not in month.read_text()
    outcome = ledger.latest(tmp_path / "runs").manifest["adapters"][0]
    assert outcome["status"] == "excluded_by_policy" and outcome["policy"] == "hidden"


def test_subset_review_cannot_be_applied_without_force(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    workflow.run(config, apply=False, only=["fake"], review=True)
    run = ledger.latest(tmp_path / "runs")
    with pytest.raises(SystemExit, match="only some adapters"):
        workflow.apply_run(config, run.manifest["run_id"])


def test_profile_digest_shapes_month_file(tmp_path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    workflow.run(config, apply=True, profile="chronicle")
    assert "_Coverage: 2 records from 2 sources (fake, other)._" in (
        tmp_path / "Journal" / "2026-02.md").read_text()
