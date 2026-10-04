import json
import shutil
from pathlib import Path

import pytest

from dossify.adapter_api import Fact
from dossify.builtin_adapters import P0_ADAPTERS
from dossify.pipeline import build_plan, canonical_json, execute_plan
from dossify.schema import public_schemas

FIXTURES = Path(__file__).parent / "fixtures"


def test_fact_requires_an_observed_timezone() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Fact(
            provider_id="test",
            adapter_id="test",
            source_locator="fixture",
            observed_at="2026-01-01T12:00:00",
            event_type="test.event",
        )


def test_plan_does_not_parse_activitywatch_export_and_execution_is_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "activitywatch.json"
    shutil.copyfile(FIXTURES / "activitywatch-export.json", source)
    adapter = P0_ADAPTERS["activitywatch"]
    config = adapter.config_model(source=source)
    calls: list[Path] = []
    original = Path.read_text

    def watched_read_text(path: Path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", watched_read_text)
    plan = build_plan(adapter, config)

    assert calls == []
    assert "private-project-secret" not in canonical_json(plan)
    first = execute_plan(adapter, config, plan, tmp_path / "cache")
    second = execute_plan(adapter, config, plan, tmp_path / "cache")
    assert first.facts[0].display == "Used Code for 2 min"
    assert "private-project-secret" not in canonical_json(first)
    assert second.provenance.cache.decision == "hit"
    assert canonical_json(first.facts) == canonical_json(second.facts)


def test_stale_plan_cannot_execute_after_input_changes(tmp_path: Path) -> None:
    source = tmp_path / "fitbit.csv"
    source.write_text("Date,Steps\n2026-01-03,123\n", encoding="utf-8")
    adapter = P0_ADAPTERS["health_archive"]
    config = adapter.config_model(source=source)
    plan = build_plan(adapter, config)
    source.write_text("Date,Steps\n2026-01-03,1234\n", encoding="utf-8")

    with pytest.raises(ValueError, match="plan no longer matches"):
        execute_plan(adapter, config, plan)


def test_google_takeout_uses_activity_categories_not_query_titles(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Takeout"
    root.mkdir()
    shutil.copyfile(FIXTURES / "google-takeout-activity.json", root / "MyActivity.json")
    adapter = P0_ADAPTERS["google_takeout"]
    config = adapter.config_model(source=root)
    plan = build_plan(adapter, config)
    result = execute_plan(adapter, config, plan)

    assert result.facts[0].display == "1 Google activity records"
    assert "private medical question" not in canonical_json(result)


def test_checked_in_schemas_match_models() -> None:
    root = Path(__file__).parents[1] / "schemas"
    for relative, expected in public_schemas().items():
        actual = json.loads((root / relative).read_text(encoding="utf-8"))
        assert actual == expected


@pytest.mark.parametrize(
    ("provider", "fixture", "expected"),
    [
        ("nextcloud", "nextcloud-activity.json", "2 Nextcloud activities"),
        ("immich", "immich-metadata.json", "Added 2 photo assets"),
        ("health_archive", "health-steps.csv", "4,567 steps"),
    ],
)
def test_public_export_fixtures_have_stable_summaries(
    provider: str, fixture: str, expected: str
) -> None:
    adapter = P0_ADAPTERS[provider]
    config = adapter.config_model(source=FIXTURES / fixture)
    plan = build_plan(adapter, config)
    result = execute_plan(adapter, config, plan)

    assert [fact.display for fact in result.facts] == [expected]
