"""Plan-first execution and cache ownership for public Dossify adapters."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel

from dossify.adapter_api import (
    ADAPTER_API_VERSION,
    AdapterManifest,
    AdapterResult,
    CacheDirective,
    ExecutionPlan,
    InputFingerprint,
    PlannedRead,
    RequestedPermissions,
)


def canonical_json(value: Any) -> str:
    """Return the one JSON representation used for hashes and fixtures."""

    def json_value(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return json_value(item.model_dump(mode="json", exclude_none=True))
        if isinstance(item, dict):
            return {str(key): json_value(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [json_value(child) for child in item]
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        return item

    return json.dumps(
        json_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def config_fingerprint(config: BaseModel) -> str:
    return digest(config)


def issue_plan_id(plan: dict[str, Any]) -> str:
    return digest({key: value for key, value in plan.items() if key != "plan_id"})


def file_fingerprint(path: Path) -> InputFingerprint:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    stat = path.stat()
    return InputFingerprint(
        locator=str(path.resolve()),
        sha256=hasher.hexdigest(),
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


def planned_read(path: Path, reason: str) -> PlannedRead:
    stat = path.stat()
    return PlannedRead(
        locator=str(path.resolve()),
        reason=reason,
        size_bytes=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, UTC),
    )


class Adapter(Protocol):
    manifest: AdapterManifest
    config_model: type[BaseModel]

    def plan(
        self, config: BaseModel
    ) -> tuple[tuple[PlannedRead, ...], tuple[str, ...]]: ...

    def execute(
        self,
        config: BaseModel,
        plan: ExecutionPlan,
        fingerprints: tuple[InputFingerprint, ...],
    ) -> AdapterResult: ...


def build_plan(adapter: Adapter, config: BaseModel) -> ExecutionPlan:
    """Preflight an adapter without parsing input contents or mutating storage."""
    if not (
        adapter.manifest.adapter_api_min
        <= ADAPTER_API_VERSION
        <= adapter.manifest.adapter_api_max
    ):
        raise ValueError(
            f"{adapter.manifest.adapter_id} does not support adapter API {ADAPTER_API_VERSION}"
        )
    reads, warnings = adapter.plan(config)
    draft: dict[str, Any] = {
        "provider_id": adapter.manifest.provider_id,
        "adapter_id": adapter.manifest.adapter_id,
        "manifest_version": adapter.manifest.adapter_version,
        "config_fingerprint": config_fingerprint(config),
        "reads": reads,
        "permissions": RequestedPermissions(
            read_paths=tuple(item.locator for item in reads),
            network_hosts=tuple(getattr(adapter, "network_hosts", lambda _config: ())(config)),
        ),
        "cache_action": "read_or_write"
        if adapter.manifest.deterministic_output
        else "bypass",
        "warnings": warnings,
    }
    draft["plan_id"] = issue_plan_id(draft)
    return ExecutionPlan.model_validate(draft)


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / "facts" / f"{key}.json"


def _cache_key(plan: ExecutionPlan, fingerprints: tuple[InputFingerprint, ...]) -> str:
    return digest({"plan": plan, "inputs": fingerprints, "compiler": "dossify-1"})


def execute_plan(
    adapter: Adapter,
    config: BaseModel,
    plan: ExecutionPlan,
    cache_dir: Path | None = None,
) -> AdapterResult:
    """Execute only a freshly verifiable core-issued plan.

    Cache files are written only after a complete validated result exists.  A
    dry run is therefore exactly ``build_plan`` and cannot mutate this cache.
    """
    expected = build_plan(adapter, config)
    if plan != expected:
        raise ValueError(
            "plan no longer matches this adapter configuration or its inputs; create a new plan"
        )
    fingerprints = tuple(file_fingerprint(Path(item.locator)) for item in plan.reads)
    key = _cache_key(plan, fingerprints)
    cache_file = _cache_path(cache_dir, key) if cache_dir else None
    if cache_file and adapter.manifest.deterministic_output:
        try:
            cached = AdapterResult.model_validate_json(
                cache_file.read_text(encoding="utf-8")
            )
            return cached.model_copy(
                update={
                    "provenance": cached.provenance.model_copy(
                        update={
                            "cache": CacheDirective(
                                reusable=True,
                                cache_key=key,
                                decision="hit",
                                reason="matching plan and inputs",
                            )
                        }
                    )
                }
            )
        except (OSError, ValueError):
            pass
    result = adapter.execute(config, plan, fingerprints)
    result = result.model_copy(
        update={
            "facts": tuple(
                sorted(
                    result.facts,
                    key=lambda fact: (
                        fact.observed_at,
                        fact.event_type,
                        fact.source_locator,
                        fact.source_record_id or "",
                    ),
                )
            ),
            "provenance": result.provenance.model_copy(
                update={
                    "cache": CacheDirective(
                        reusable=adapter.manifest.deterministic_output,
                        cache_key=key,
                        decision="miss"
                        if adapter.manifest.deterministic_output
                        else "bypass",
                        reason="validated execution"
                        if adapter.manifest.deterministic_output
                        else "adapter declares nondeterministic output",
                    )
                }
            ),
        }
    )
    if cache_file and adapter.manifest.deterministic_output:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache_file.with_suffix(".tmp")
        temporary.write_text(canonical_json(result) + "\n", encoding="utf-8")
        temporary.replace(cache_file)
    return result
