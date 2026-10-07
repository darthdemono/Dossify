import re
from pathlib import Path

from dossify import profiles, workflow, workspace
from dossify.config import load_config
from dossify.providers import provider_manifest, provider_table
from tests.test_workflow import workspace as make_workspace


def test_readme_provider_table_matches_registry() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    block = re.search(r"<!-- providers:begin -->\n(.*?)\n<!-- providers:end -->", readme, re.S)
    assert block and block.group(1).strip() == provider_table().strip()


def test_readme_names_every_profile() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in readme for name in profiles.PROFILES)


def test_every_provider_has_a_known_support_level() -> None:
    from dossify.providers import MATURITY

    assert {p["maturity"] for p in provider_manifest()} <= set(MATURITY)
    stable = {p["name"] for p in provider_manifest() if p["maturity"] == "stable_typed"}
    assert {"activitywatch", "nextcloud", "immich", "google_takeout", "health_archive",
            "hyperos_dashboard"} == stable


def test_init_creates_skeleton_and_keeps_existing(tmp_path: Path, capsys) -> None:
    workspace.init(tmp_path / "w")
    assert (tmp_path / "w" / "dossify.toml").exists() and (tmp_path / "w" / "Journal").is_dir()
    (tmp_path / "w" / "People.json").write_text('{"keep": {}}')
    workspace.init(tmp_path / "w")
    assert "keep" in (tmp_path / "w" / "People.json").read_text()
    config = load_config(tmp_path / "w" / "dossify.toml")
    assert config.privacy.preset == "balanced" and config.output.profile == "journal"


def test_doctor_passes_on_init_workspace_and_fails_on_missing(tmp_path: Path, capsys) -> None:
    workspace.init(tmp_path / "w")
    config = load_config(tmp_path / "w" / "dossify.toml")
    assert workspace.doctor(config, tmp_path / "w" / "dossify.toml") == 0
    (tmp_path / "w" / "People.json").unlink()
    assert workspace.doctor(config, tmp_path / "w" / "dossify.toml") == 1
    assert "FAIL  people_file exists" in capsys.readouterr().out


def test_status_reads_latest_run(tmp_path: Path, monkeypatch, capsys) -> None:
    config = make_workspace(tmp_path, monkeypatch)
    assert workspace.status(config) == 1
    workflow.run(config, apply=False, review=True)
    assert workspace.status(config) == 0
    assert "fake: ok, 2 records on 1 days" in capsys.readouterr().out


def test_compile_writes_into_dossiers_folder(tmp_path: Path, monkeypatch) -> None:
    config = make_workspace(tmp_path, monkeypatch)
    workspace.compile_document(config, profile="casefile", period="2026-02", output=None, write=True)
    text = (tmp_path / "Journal" / "Dossiers" / "Casefile - 2026-02.md").read_text()
    assert "# Casefile: 2026-02" in text and "2026-02-03: 2 records" in text


def test_index_and_search_round_trip(tmp_path: Path, monkeypatch, capsys) -> None:
    config = make_workspace(tmp_path, monkeypatch)
    workspace.build_index(config)
    workspace.search(config, "another", 10)
    assert "[other] Did another" in capsys.readouterr().out
