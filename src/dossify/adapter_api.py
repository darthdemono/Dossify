"""Compatibility re-export: the contract now lives in ``dossify-adapter-api``."""

from dossify_adapter_api import (  # noqa: F401
    ADAPTER_API_VERSION,
    CACHE_CONTRACT_VERSION,
    PLAN_FORMAT_VERSION,
    AdapterManifest,
    AdapterResult,
    CacheDirective,
    Coverage,
    ExecutionPlan,
    Fact,
    InputFingerprint,
    PlannedRead,
    Provenance,
    ProviderId,
    RequestedPermissions,
    Sensitivity,
    TimePrecision,
)
