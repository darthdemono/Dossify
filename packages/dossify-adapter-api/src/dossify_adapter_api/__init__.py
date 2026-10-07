"""Public, versioned evidence contract for Dossify adapters.

Adapters turn owner-supplied records into facts.  They do not write journals,
touch arbitrary files, or infer permissions.  The core owns those decisions.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ADAPTER_API_VERSION = "1.0"
PLAN_FORMAT_VERSION = "1.0"
CACHE_CONTRACT_VERSION = "1.0"

ProviderId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]*$")]


class Sensitivity(StrEnum):
    """How cautiously a renderer should treat a fact's values and display text."""

    PUBLIC = "public"
    PRIVATE = "private"
    SENSITIVE = "sensitive"


class TimePrecision(StrEnum):
    INSTANT = "instant"
    DAY = "day"


class InputFingerprint(BaseModel):
    """An immutable description of one input observed during execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    locator: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    modified_at: datetime


class Coverage(BaseModel):
    """The time range an adapter actually observed, never an assertion of absence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    complete: bool = False
    note: str | None = None

    @model_validator(mode="after")
    def ordered_range(self) -> Coverage:
        if self.starts_at and self.ends_at and self.ends_at < self.starts_at:
            raise ValueError("coverage ends_at must not precede starts_at")
        return self


class Fact(BaseModel):
    """A source-linked, renderer-neutral item of personal evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    adapter_id: ProviderId
    source_locator: str
    source_record_id: str | None = None
    observed_at: datetime
    time_precision: TimePrecision = TimePrecision.INSTANT
    event_type: str = Field(pattern=r"^[a-z][a-z0-9_.-]*$")
    values: dict[str, Any] = Field(default_factory=dict)
    display: str | None = None
    sensitivity: Sensitivity = Sensitivity.PRIVATE
    retention: Literal["ephemeral", "cache", "archive"] = "cache"

    @field_validator("observed_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must include a timezone")
        return value


class AdapterManifest(BaseModel):
    """Static capabilities and compatibility declared before an adapter runs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    adapter_id: ProviderId
    display_name: str = Field(min_length=1)
    adapter_version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
    adapter_api_min: str = Field(pattern=r"^\d+\.\d+$")
    adapter_api_max: str = Field(pattern=r"^\d+\.\d+$")
    config_schema_version: str = Field(pattern=r"^\d+\.\d+$")
    config_schema_id: str
    capabilities: tuple[str, ...]
    requested_permissions: tuple[str, ...]
    deterministic_output: bool
    cache_contract_version: str = CACHE_CONTRACT_VERSION


class RequestedPermissions(BaseModel):
    """The adapter's requested access after intersection with command policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    read_paths: tuple[str, ...] = ()
    network_hosts: tuple[str, ...] = ()
    may_write: bool = False


class PlannedRead(BaseModel):
    """A file the adapter intends to inspect, without reading its contents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    locator: str
    reason: str
    size_bytes: int | None = Field(default=None, ge=0)
    modified_at: datetime | None = None


class ExecutionPlan(BaseModel):
    """Canonical, reviewable preflight artifact.  The core verifies its hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: str = PLAN_FORMAT_VERSION
    provider_id: ProviderId
    adapter_id: ProviderId
    manifest_version: str
    config_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reads: tuple[PlannedRead, ...] = ()
    permissions: RequestedPermissions
    cache_action: Literal["bypass", "read_or_write"] = "read_or_write"
    warnings: tuple[str, ...] = ()
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")


class CacheDirective(BaseModel):
    """Core-owned cache decision recorded with every result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reusable: bool
    cache_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["hit", "miss", "bypass"]
    reason: str


class Provenance(BaseModel):
    """Evidence needed to explain and reproduce an adapter result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_id: ProviderId
    adapter_id: ProviderId
    adapter_version: str
    adapter_api_version: str
    plan_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_fingerprints: tuple[InputFingerprint, ...]
    effective_permissions: RequestedPermissions
    coverage: Coverage
    cache: CacheDirective


class AdapterResult(BaseModel):
    """Validated execution result.  Facts are sorted by the core before output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    facts: tuple[Fact, ...]
    provenance: Provenance
    warnings: tuple[str, ...] = ()
