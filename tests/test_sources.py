import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dossify import journal, ledger, unified, workflow
from dossify.config import load_config
from dossify.providers import provider_manifest
from dossify.sources import registry, takeout, chat_exports, meta


def config_for(tmp_path: Path, blocks: str):
    (tmp_path / "Journal").mkdir(exist_ok=True)
    (tmp_path / "dossify.toml").write_text(
        'output_dir = "Journal"\ntimezone = "UTC"\n[journal]\ncache_dir = "cache"\n' + blocks)
    return load_config(tmp_path / "dossify.toml")


def make_repo(path: Path) -> None:
    path.mkdir(parents=True)
    env = {**os.environ, "GIT_AUTHOR_NAME": "Test Person", "GIT_AUTHOR_EMAIL": "t@example.test",
           "GIT_COMMITTER_NAME": "Test Person", "GIT_COMMITTER_EMAIL": "t@example.test"}
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=env)
    (path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "first change"], check=True, env=env)


def test_a_source_runs_only_when_it_has_a_provider_block(tmp_path: Path) -> None:
    make_repo(tmp_path / "code" / "proj")
    off = config_for(tmp_path, "")
    journal.configure(off)
    facts, outcomes, _ = unified.collect(off, journal, [])
    assert facts == [] and outcomes == []
    on = config_for(tmp_path, f'[providers.git]\nroots = ["{tmp_path / "code"}"]\n')
    journal.configure(on)
    facts, outcomes, _ = unified.collect(on, journal, [])
    assert [o.name for o in outcomes] == ["git"] and "proj" in facts[0].text and "first change" in facts[0].text
    disabled = config_for(tmp_path, f'[providers.git]\nenabled = false\nroots = ["{tmp_path / "code"}"]\n')
    assert unified.collect(disabled, journal, [])[0] == []


def test_author_terms_filter_commits(tmp_path: Path) -> None:
    make_repo(tmp_path / "code" / "proj")
    config = config_for(tmp_path, f'[providers.git]\nroots = ["{tmp_path / "code"}"]\nauthor_terms = ["somebody else"]\n')
    journal.configure(config)
    assert unified.collect(config, journal, [])[0] == []


def test_end_to_end_bank_statement_through_a_provider_block(tmp_path: Path, monkeypatch) -> None:
    statements = tmp_path / "statements"
    statements.mkdir()
    (statements / "a.csv").write_text("Date,Amount,Currency,Description\n2026-02-03,-1500,EUR,SHOP ONE\n")
    config = config_for(tmp_path, f'[providers.bank_statements]\nsources = ["{statements}"]\n'
                                  '[providers.bank_statements.names]\n"SHOP ONE" = "Shop One"\n')
    workflow.run(config, apply=True)
    month = (tmp_path / "Journal" / "2026-02.md").read_text()
    assert "Paid 1,500 EUR to Shop One" in month
    assert ledger.latest(workflow.ledger_root(config)).manifest["adapters"][0]["name"] == "bank_statements"


def test_cache_key_changes_with_the_provider_options(tmp_path: Path) -> None:
    config = config_for(tmp_path, "")
    journal.configure(config)
    data = tmp_path / "x.json"
    data.write_text("[]")
    journal.CACHE_SALT = "one"
    assert journal.cached("t", [str(data)], lambda paths: [journal.Fact("2026-01-01", None, "first", "t")])[0].text == "first"
    assert journal.cached("t", [str(data)], lambda paths: [journal.Fact("2026-01-01", None, "second", "t")])[0].text == "first"
    journal.CACHE_SALT = "two"
    assert journal.cached("t", [str(data)], lambda paths: [journal.Fact("2026-01-01", None, "second", "t")])[0].text == "second"


def test_instagram_and_facebook_exports_are_found_by_marker_inside_the_named_folder(tmp_path: Path) -> None:
    root = tmp_path / "exports"
    (root / "ig-download" / "your_instagram_activity").mkdir(parents=True)
    (root / "fb-download" / "your_facebook_activity").mkdir(parents=True)
    meta._O = {"export": [str(root)]}
    assert meta.meta_root("instagram") == str(root / "ig-download")
    assert meta.meta_root("facebook") == str(root / "fb-download")
    meta._O = {"export": [str(root / "ig-download")]}
    assert meta.meta_root("instagram") == str(root / "ig-download")
    meta._O = {"export": [str(tmp_path / "missing")]}
    assert meta.meta_root("instagram") is None
    meta._O = {}
    assert meta.meta_root("instagram") is None


def test_takeout_accepts_one_account_or_a_folder_of_accounts(tmp_path: Path) -> None:
    one = tmp_path / "one"
    (one / "Takeout").mkdir(parents=True)
    many = tmp_path / "many"
    for name in ("alice", "bob"):
        (many / name / "Takeout").mkdir(parents=True)
    takeout._O = {"export": [str(one)]}
    assert [label for label, _ in takeout.takeout_accounts()] == ["one"]
    takeout._O = {"export": [str(many)]}
    assert [label for label, _ in takeout.takeout_accounts()] == ["alice", "bob"]
    takeout._O = {"export": [str(many), str(tmp_path / "absent")]}
    assert len(takeout.takeout_accounts()) == 2


def test_chat_exports_use_the_named_folder_directly(tmp_path: Path) -> None:
    (tmp_path / "discord").mkdir()
    chat_exports._O = {"export": str(tmp_path / "discord")}
    assert chat_exports.export_dirs("discord") == [str(tmp_path / "discord")]
    chat_exports._O = {"export": str(tmp_path / "nope")}
    assert chat_exports.export_dirs("discord") == []


def test_timezone_history_picks_the_zone_that_applied(tmp_path: Path) -> None:
    (tmp_path / "Journal").mkdir(exist_ok=True)
    (tmp_path / "dossify.toml").write_text(
        'output_dir = "Journal"\ntimezone = "Europe/Budapest"\n[[timezone_history]]\n'
        'until = "2025-08-31T00:00:00+00:00"\nzone = "Asia/Dhaka"\n')
    journal.configure(load_config(tmp_path / "dossify.toml"))
    assert journal.local_of(datetime(2025, 8, 30, 20, 0, tzinfo=UTC)) == ("2025-08-31", "02:00")   # Dhaka, UTC+6
    assert journal.local_of(datetime(2025, 9, 1, 20, 0, tzinfo=UTC)) == ("2025-09-01", "22:00")    # Budapest, UTC+2


def test_secret_comes_from_the_environment_or_a_command_never_the_file(monkeypatch) -> None:
    monkeypatch.setenv("DOSSIFY_TEST_KEY", " from-env ")
    assert journal.secret({"api_key_env": "DOSSIFY_TEST_KEY"}) == "from-env"
    assert journal.secret({"api_key_env": "UNSET_VAR_XYZ"}) is None
    assert journal.secret({"api_key_command": ["printf", "from-command"]}) == "from-command"
    assert journal.secret({"url_command": ["printf", "u"]}, "url") == "u"
    assert journal.secret({"api_key": "plain text in the file"}) is None
    assert journal.secret({"api_key_command": ["definitely-not-a-command-xyz"]}) is None


def test_the_retired_rules_file_names_where_to_look(tmp_path: Path) -> None:
    (tmp_path / "dossify.toml").write_text('output_dir = "J"\n[journal]\nrules_file = "Journal Rules.json"\n')
    with pytest.raises(ValueError, match="docs/MIGRATING.md"):
        load_config(tmp_path / "dossify.toml")


def test_every_bundled_reader_is_listed_documented_and_tiered() -> None:
    listed = {p["name"] for p in provider_manifest()}
    readers = set(registry.readers())
    assert readers <= listed, f"readers missing from the provider list: {sorted(readers - listed)}"
    assert set(registry.tiers().values()) == {"core", "optional"}
    for name, (module, _fn) in registry.readers().items():
        assert module.__doc__
        assert name in module.READERS and module.LABELS


def test_providers_doc_matches_the_source_modules() -> None:
    doc = (Path(__file__).parent.parent / "docs" / "PROVIDERS.md").read_text(encoding="utf-8")
    from dossify.providers import typed_options_markdown

    assert registry.options_markdown() in doc and typed_options_markdown() in doc


def test_example_config_loads_and_every_active_block_is_a_known_provider() -> None:
    example = Path(__file__).parent.parent / "dossify.example.toml"
    config = load_config(example)
    known = {p["name"] for p in provider_manifest()} | set()
    assert set(config.providers) <= known
    assert config.output.profile == "journal" and config.privacy.preset == "balanced"
