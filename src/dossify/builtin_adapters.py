"""Export-first P0 adapters shipped with Dossify.

They deliberately accept only owner-supplied files.  Remote APIs, OAuth, and
local-service credentials are outside the v1.0 contract.
"""

from __future__ import annotations

import csv
import json
import xml.etree.ElementTree as element_tree
from collections import Counter
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from dossify.adapter_api import (
    ADAPTER_API_VERSION,
    AdapterManifest,
    AdapterResult,
    CacheDirective,
    Coverage,
    Fact,
    InputFingerprint,
    Provenance,
    Sensitivity,
)
from dossify.pipeline import ExecutionPlan, PlannedRead, planned_read


class ExportConfig(BaseModel):
    """Common, intentionally small configuration for a local P0 source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: Path
    enabled: bool = True


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            return datetime.fromtimestamp(float(value), UTC)
        except (OverflowError, OSError, ValueError):
            return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _day(value: str) -> datetime | None:
    try:
        return datetime.combine(datetime.fromisoformat(value[:10]).date(), time(), UTC)
    except ValueError:
        return None


def _coverage(facts: list[Fact]) -> Coverage:
    if not facts:
        return Coverage(
            complete=False, note="The selected export contained no supported records."
        )
    ordered = sorted(fact.observed_at for fact in facts)
    return Coverage(starts_at=ordered[0], ends_at=ordered[-1], complete=True)


class LocalExportAdapter:
    """Shared plan and provenance behaviour for static, local-file adapters."""

    config_model = ExportConfig
    file_reason = "owner-supplied export"
    manifest: AdapterManifest

    def source_files(self, config: ExportConfig) -> tuple[Path, ...]:
        source = config.source.expanduser()
        return (source,) if source.is_file() else ()

    def plan(
        self, config: BaseModel
    ) -> tuple[tuple[PlannedRead, ...], tuple[str, ...]]:
        typed = self.config_model.model_validate(config)
        files = self.source_files(typed)
        if not files:
            return (), (f"No supported export found at {typed.source}.",)
        return tuple(planned_read(path, self.file_reason) for path in files), ()

    def result(
        self,
        facts: list[Fact],
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
        warnings: tuple[str, ...] = (),
    ) -> AdapterResult:
        return AdapterResult(
            facts=tuple(facts),
            warnings=warnings,
            provenance=Provenance(
                provider_id=self.manifest.provider_id,
                adapter_id=self.manifest.adapter_id,
                adapter_version=self.manifest.adapter_version,
                adapter_api_version=ADAPTER_API_VERSION,
                plan_id=plan.plan_id,
                input_fingerprints=fingerprints,
                effective_permissions=plan.permissions,
                coverage=_coverage(facts),
                cache=CacheDirective(
                    reusable=False,
                    cache_key="0" * 64,
                    decision="bypass",
                    reason="set by core",
                ),
            ),
        )


class ActivityWatchAdapter(LocalExportAdapter):
    manifest = AdapterManifest(
        provider_id="activitywatch",
        adapter_id="activitywatch_export",
        display_name="ActivityWatch export",
        adapter_version="1.0.0",
        adapter_api_min="1.0",
        adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/activitywatch-export/1.0.json",
        capabilities=("facts.read", "export.read"),
        requested_permissions=("filesystem.read",),
        deterministic_output=True,
    )

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult:
        facts: list[Fact] = []
        for item in plan.reads:
            try:
                data = json.loads(Path(item.locator).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            buckets = data.get("buckets", data) if isinstance(data, dict) else {}
            totals: Counter[tuple[str, str]] = Counter()
            for bucket_id, bucket in sorted(
                buckets.items() if isinstance(buckets, dict) else []
            ):
                events = bucket.get("events", []) if isinstance(bucket, dict) else []
                for index, event in enumerate(events):
                    if not isinstance(event, dict):
                        continue
                    stamp = _parse_timestamp(event.get("timestamp"))
                    if not stamp:
                        continue
                    app = (
                        str((event.get("data") or {}).get("app") or bucket_id).strip()
                        or "unclassified activity"
                    )
                    try:
                        seconds = max(0, round(float(event.get("duration", 0))))
                    except (TypeError, ValueError):
                        seconds = 0
                    totals[(stamp.date().isoformat(), app)] += seconds
            for (date, app), seconds in sorted(totals.items()):
                observed = _day(date)
                assert observed
                minutes = round(seconds / 60)
                facts.append(
                    Fact(
                        provider_id="activitywatch",
                        adapter_id="activitywatch_export",
                        source_locator=item.locator,
                        source_record_id=f"{date}:{app}",
                        observed_at=observed,
                        time_precision="day",
                        event_type="activity.app_summary",
                        values={"application": app, "duration_seconds": seconds},
                        display=f"Used {app} for {minutes} min",
                        sensitivity=Sensitivity.PRIVATE,
                    )
                )
        return self.result(facts, plan, fingerprints)


class NextcloudAdapter(LocalExportAdapter):
    manifest = AdapterManifest(
        provider_id="nextcloud",
        adapter_id="nextcloud_export",
        display_name="Nextcloud Activity or ICS export",
        adapter_version="1.0.0",
        adapter_api_min="1.0",
        adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/nextcloud-export/1.0.json",
        capabilities=("facts.read", "export.read"),
        requested_permissions=("filesystem.read",),
        deterministic_output=True,
    )

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult:
        facts: list[Fact] = []
        for item in plan.reads:
            path = Path(item.locator)
            if path.suffix.lower() == ".ics":
                for index, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").splitlines()
                ):
                    if not line.startswith("DTSTART"):
                        continue
                    raw = line.split(":", 1)[-1].strip()
                    stamp = _parse_timestamp(raw.replace("Z", "+00:00")) or _day(raw)
                    if stamp:
                        facts.append(
                            Fact(
                                provider_id="nextcloud",
                                adapter_id="nextcloud_export",
                                source_locator=item.locator,
                                source_record_id=f"ics:{index}",
                                observed_at=stamp,
                                time_precision="day" if len(raw) == 8 else "instant",
                                event_type="calendar.event",
                                values={"source": "ics"},
                                sensitivity=Sensitivity.PRIVATE,
                            )
                        )
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = (
                payload.get("ocs", {}).get("data", [])
                if isinstance(payload, dict)
                else payload
            )
            daily: Counter[str] = Counter()
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                stamp = _parse_timestamp(
                    row.get("datetime") or row.get("timestamp") or row.get("date")
                )
                if stamp:
                    daily[stamp.date().isoformat()] += 1
            for date, count in sorted(daily.items()):
                observed = _day(date)
                assert observed
                facts.append(
                    Fact(
                        provider_id="nextcloud",
                        adapter_id="nextcloud_export",
                        source_locator=item.locator,
                        source_record_id=f"activity:{date}",
                        observed_at=observed,
                        time_precision="day",
                        event_type="cloud.activity_summary",
                        values={"activity_count": count},
                        display=f"{count} Nextcloud activities",
                        sensitivity=Sensitivity.PRIVATE,
                    )
                )
        return self.result(facts, plan, fingerprints)


class ImmichAdapter(LocalExportAdapter):
    manifest = AdapterManifest(
        provider_id="immich",
        adapter_id="immich_export",
        display_name="Immich metadata export",
        adapter_version="1.0.0",
        adapter_api_min="1.0",
        adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/immich-export/1.0.json",
        capabilities=("facts.read", "export.read"),
        requested_permissions=("filesystem.read",),
        deterministic_output=True,
    )

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult:
        facts: list[Fact] = []
        for item in plan.reads:
            try:
                payload = json.loads(Path(item.locator).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rows = (
                payload.get("assets", payload) if isinstance(payload, dict) else payload
            )
            daily: Counter[str] = Counter()
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                stamp = _parse_timestamp(
                    row.get("fileCreatedAt")
                    or row.get("localDateTime")
                    or row.get("createdAt")
                )
                if stamp:
                    daily[stamp.date().isoformat()] += 1
            for date, count in sorted(daily.items()):
                observed = _day(date)
                assert observed
                facts.append(
                    Fact(
                        provider_id="immich",
                        adapter_id="immich_export",
                        source_locator=item.locator,
                        source_record_id=f"assets:{date}",
                        observed_at=observed,
                        time_precision="day",
                        event_type="photos.asset_summary",
                        values={"asset_count": count},
                        display=f"Added {count} photo assets",
                        sensitivity=Sensitivity.PRIVATE,
                    )
                )
        return self.result(facts, plan, fingerprints)


class GoogleTakeoutAdapter(LocalExportAdapter):
    manifest = AdapterManifest(
        provider_id="google_takeout",
        adapter_id="google_takeout_export",
        display_name="Google Takeout activity export",
        adapter_version="1.0.0",
        adapter_api_min="1.0",
        adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/google-takeout-export/1.0.json",
        capabilities=("facts.read", "export.read"),
        requested_permissions=("filesystem.read",),
        deterministic_output=True,
    )

    def source_files(self, config: ExportConfig) -> tuple[Path, ...]:
        if config.source.is_file():
            return (config.source,)
        if not config.source.is_dir():
            return ()
        names = {
            "myactivity.json",
            "watch-history.json",
            "history.json",
            "browserhistory.json",
        }
        return tuple(
            sorted(
                (
                    path
                    for path in config.source.rglob("*.json")
                    if path.name.lower() in names
                ),
                key=lambda path: str(path),
            )
        )

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult:
        facts: list[Fact] = []
        for item in plan.reads:
            try:
                rows = json.loads(Path(item.locator).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            daily: Counter[tuple[str, str]] = Counter()
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                stamp = _parse_timestamp(
                    row.get("time") or row.get("timestamp") or row.get("time_usec")
                )
                if not stamp:
                    continue
                title = str(row.get("title") or "")
                product = "YouTube" if "youtube" in title.lower() else "Google activity"
                daily[(stamp.date().isoformat(), product)] += 1
            for (date, product), count in sorted(daily.items()):
                observed = _day(date)
                assert observed
                facts.append(
                    Fact(
                        provider_id="google_takeout",
                        adapter_id="google_takeout_export",
                        source_locator=item.locator,
                        source_record_id=f"{Path(item.locator).name}:{date}:{product}",
                        observed_at=observed,
                        time_precision="day",
                        event_type="activity.summary",
                        values={"product": product, "event_count": count},
                        display=f"{count} {product} records",
                        sensitivity=Sensitivity.SENSITIVE,
                    )
                )
        return self.result(facts, plan, fingerprints)


class HealthArchiveAdapter(LocalExportAdapter):
    manifest = AdapterManifest(
        provider_id="health_archive",
        adapter_id="health_archive_export",
        display_name="Apple Health, Fitbit, or Google Fit export",
        adapter_version="1.0.0",
        adapter_api_min="1.0",
        adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/health-archive-export/1.0.json",
        capabilities=("facts.read", "export.read"),
        requested_permissions=("filesystem.read",),
        deterministic_output=True,
    )

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult:
        facts: list[Fact] = []
        for item in plan.reads:
            path = Path(item.locator)
            steps: Counter[str] = Counter()
            if path.suffix.lower() == ".xml":
                try:
                    for record in element_tree.iterparse(path, events=("end",)):
                        element = record[1]
                        if (
                            element.tag != "Record"
                            or element.attrib.get("type")
                            != "HKQuantityTypeIdentifierStepCount"
                        ):
                            continue
                        stamp = _parse_timestamp(element.attrib.get("startDate"))
                        try:
                            value = round(float(element.attrib.get("value", "0")))
                        except ValueError:
                            continue
                        if stamp and value >= 0:
                            steps[stamp.date().isoformat()] += value
                        element.clear()
                except (OSError, element_tree.ParseError):
                    continue
            elif path.suffix.lower() == ".csv":
                try:
                    with path.open(encoding="utf-8-sig", newline="") as handle:
                        for row in csv.DictReader(handle):
                            stamp = _day(str(row.get("Date") or row.get("date") or ""))
                            raw = (
                                row.get("Steps")
                                or row.get("steps")
                                or row.get("step_count")
                            )
                            try:
                                value = round(float(str(raw).replace(",", "")))
                            except (TypeError, ValueError):
                                continue
                            if stamp and value >= 0:
                                steps[stamp.date().isoformat()] += value
                except OSError:
                    continue
            for date, count in sorted(steps.items()):
                observed = _day(date)
                assert observed
                facts.append(
                    Fact(
                        provider_id="health_archive",
                        adapter_id="health_archive_export",
                        source_locator=item.locator,
                        source_record_id=f"steps:{date}",
                        observed_at=observed,
                        time_precision="day",
                        event_type="health.steps",
                        values={"steps": count},
                        display=f"{count:,} steps",
                        sensitivity=Sensitivity.SENSITIVE,
                        retention="archive",
                    )
                )
        return self.result(facts, plan, fingerprints)


P0_ADAPTERS: dict[str, LocalExportAdapter] = {
    "activitywatch": ActivityWatchAdapter(),
    "nextcloud": NextcloudAdapter(),
    "immich": ImmichAdapter(),
    "google_takeout": GoogleTakeoutAdapter(),
    "health_archive": HealthArchiveAdapter(),
}


def builtin_manifests() -> tuple[AdapterManifest, ...]:
    return tuple(adapter.manifest for _name, adapter in sorted(P0_ADAPTERS.items()))
