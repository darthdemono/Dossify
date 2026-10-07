"""Conformance checks an adapter must pass before Dossify trusts it."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel

from dossify.adapter_api import ADAPTER_API_VERSION, AdapterResult
from dossify.pipeline import build_plan, canonical_json, execute_plan


def check(adapter, config: BaseModel, cache_dir: Path | None = None) -> list[str]:
    """Return failures; an empty list means the adapter conforms."""
    failures: list[str] = []
    m = getattr(adapter, "manifest", None)
    if m is None or not isinstance(getattr(adapter, "config_model", None), type):
        return ["adapter needs a `manifest` and a pydantic `config_model` class"]
    if not issubclass(adapter.config_model, BaseModel):
        failures.append("config_model must be a pydantic model")
    if not (m.adapter_api_min <= ADAPTER_API_VERSION <= m.adapter_api_max):
        failures.append(f"manifest does not support adapter API {ADAPTER_API_VERSION}")
    if not m.config_schema_id.startswith("https://"):
        failures.append("config_schema_id must be an https URL")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", m.adapter_id):
        failures.append("adapter_id must be lowercase letters, digits, _ or -")
    try:
        plan = build_plan(adapter, config)
        again = build_plan(adapter, config)
    except Exception as exc:
        return failures + [f"plan failed: {type(exc).__name__}: {exc}"]
    if plan != again:
        failures.append("plan is not deterministic: two calls disagreed")
    if plan.provider_id != m.provider_id or plan.adapter_id != m.adapter_id:
        failures.append("plan names a different provider or adapter than the manifest")
    if plan.permissions.may_write:
        failures.append("plan requests write access; adapters never write")
    try:
        result = execute_plan(adapter, config, plan, cache_dir)
    except Exception as exc:
        return failures + [f"execute failed: {type(exc).__name__}: {exc}"]
    if not isinstance(result, AdapterResult):
        return failures + ["execute must return an AdapterResult"]
    prov = result.provenance
    if (prov.provider_id, prov.adapter_id) != (m.provider_id, m.adapter_id):
        failures.append("provenance names a different provider or adapter than the manifest")
    for fact in result.facts:
        if (fact.provider_id, fact.adapter_id) != (m.provider_id, m.adapter_id):
            failures.append(f"fact {fact.event_type} names a different provider or adapter")
            break
    declared = set(plan.permissions.read_paths)
    if not set(prov.effective_permissions.read_paths) <= declared:
        failures.append("effective read paths exceed the plan's declared reads")
    if not set(prov.effective_permissions.network_hosts) <= set(plan.permissions.network_hosts):
        failures.append("effective network hosts exceed the plan's declared hosts")
    if m.deterministic_output:
        second = execute_plan(adapter, config, plan, None)
        if canonical_json(result.facts) != canonical_json(second.facts):
            failures.append("declares deterministic_output but two executions differ")
    return failures
