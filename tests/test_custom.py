from pathlib import Path

from dossify import external, journal, workflow
from dossify.config import load_config
from tests.test_workflow import workspace

PLUGIN = '''
from datetime import UTC, datetime
from pathlib import Path
from dossify_adapter_api import (ADAPTER_API_VERSION, AdapterManifest, AdapterResult, CacheDirective,
                                 Coverage, Fact, Provenance, TimePrecision)
from pydantic import BaseModel, ConfigDict


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = True


class Mine:
    config_model = Config
    manifest = AdapterManifest(
        provider_id="%(name)s", adapter_id="%(name)s_plugin", display_name="My plugin", adapter_version="1.0.0",
        adapter_api_min="1.0", adapter_api_max="1.0", config_schema_version="1.0",
        config_schema_id="https://example.test/schema.json", capabilities=("facts.read",),
        requested_permissions=(), deterministic_output=False)

    def plan(self, config):
        return (), ()

    def execute(self, config, plan, fingerprints):
        fact = Fact(provider_id="%(name)s", adapter_id="%(name)s_plugin", source_locator="x",
                    observed_at=datetime(2026, 2, 3, tzinfo=UTC), time_precision=TimePrecision.DAY,
                    event_type="thing.daily", values={"summary": %(summary)s}, display="A custom line")
        return AdapterResult(facts=(fact,), provenance=Provenance(
            provider_id="%(name)s", adapter_id="%(name)s_plugin", adapter_version="1.0.0",
            adapter_api_version=ADAPTER_API_VERSION, plan_id=plan.plan_id, input_fingerprints=fingerprints,
            effective_permissions=plan.permissions, coverage=Coverage(complete=False),
            cache=CacheDirective(reusable=False, cache_key="0" * 64, decision="bypass", reason="x")))


ADAPTER = Mine()
'''


def write(folder: Path, file: str, name: str, summary: str = "False") -> None:
    folder.mkdir(exist_ok=True)
    (folder / file).write_text(PLUGIN % {"name": name, "summary": summary})


def test_plugins_in_the_custom_folder_are_found_without_any_registration(tmp_path: Path) -> None:
    write(tmp_path, "mine.py", "mine")
    pkg = tmp_path / "pkgplugin"
    pkg.mkdir()
    (pkg / "__init__.py").write_text((PLUGIN % {"name": "pkgone", "summary": "False"}))
    write(tmp_path, "_ignored.py", "hidden")
    found, errors = external.discover_custom(tmp_path)
    assert sorted(found) == ["mine", "pkgone"] and errors == {}


def test_a_broken_plugin_is_reported_and_never_stops_the_others(tmp_path: Path) -> None:
    write(tmp_path, "good.py", "good")
    (tmp_path / "broken.py").write_text("raise RuntimeError('boom')\n")
    (tmp_path / "empty.py").write_text("x = 1\n")
    write(tmp_path, "clash.py", "git")
    write(tmp_path, "twin.py", "good")
    found, errors = external.discover_custom(tmp_path)
    assert list(found) == ["good"]
    assert "boom" in errors["broken"] and "none of ADAPTER" in errors["empty"]
    assert "collides" in errors["clash"] and "twice" in errors["twin"]


def test_discovery_alone_does_not_switch_a_plugin_on(tmp_path: Path, monkeypatch) -> None:
    config = workspace(tmp_path, monkeypatch)
    write(tmp_path / "custom", "mine.py", "mine", summary="True")
    monkeypatch.setenv("DOSSIFY_CUSTOM_DIR", str(tmp_path / "custom"))
    workflow.run(config, apply=False, review=True)
    names = {a["name"] for a in __import__("dossify.ledger", fromlist=["x"]).latest(tmp_path / "runs").manifest["adapters"]}
    assert "mine" not in names                               # found, but no [providers.mine] block
    (tmp_path / "dossify.toml").write_text((tmp_path / "dossify.toml").read_text() + "\n[providers.mine]\nenabled = true\n")
    config = load_config(tmp_path / "dossify.toml")
    workflow.run(config, apply=True)
    month = (tmp_path / "Journal" / "2026-02.md").read_text()
    assert "A custom line" in month
    assert "mine" in journal.DAY_SUMMARIES                   # summary facts lead their day


def test_config_can_point_at_another_folder_and_missing_folder_is_fine(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DOSSIFY_CUSTOM_DIR", raising=False)
    assert external.discover_custom(None) == ({}, {})
    other = tmp_path / "elsewhere"
    write(other, "mine.py", "mine")
    (tmp_path / "dossify.toml").write_text(
        'output_dir = "J"\n[adapters]\ncustom_dir = "elsewhere"\n'
        '[journal]\nworkspace_root = "."\n')
    config = load_config(tmp_path / "dossify.toml")
    assert external.custom_dir(config) == other.resolve()
