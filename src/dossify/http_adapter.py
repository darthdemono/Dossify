"""Read-only adapter for a self-hosted service that exposes records as JSON.

One configured GET request; nothing else.  The host is declared in the plan,
network use needs ``allow_network = true``, redirects to another host are
refused and the response is capped.  Fields are mapped by name, so no service is
hard-coded.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

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
from dossify.builtin_adapters import _parse_timestamp
from dossify.oauth import LOOPBACK
from dossify.pipeline import ExecutionPlan

MAX_BYTES = 5_000_000


class HttpJsonConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    enabled: bool = True
    allow_network: bool = False
    token_env: str | None = None
    items_path: str = ""
    time_field: str = "timestamp"
    title_field: str = "title"
    id_field: str | None = None
    event_type: str = "record.item"


def _dig(value, path: str):
    for key in filter(None, path.split(".")):
        value = value.get(key) if isinstance(value, dict) else None
    return value


class _SameHost(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            raise urllib.error.URLError("redirect to another host refused")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HttpJsonAdapter:
    config_model = HttpJsonConfig
    manifest = AdapterManifest(
        provider_id="http_json", adapter_id="http_json_readonly",
        display_name="Read-only self-hosted JSON API", adapter_version="1.0.0",
        adapter_api_min="1.0", adapter_api_max="1.0", config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/http-json/1.0.json",
        capabilities=("facts.read", "network.read"), requested_permissions=("network.read",),
        deterministic_output=False)

    def network_hosts(self, config) -> tuple[str, ...]:
        return (urllib.parse.urlsplit(self.config_model.model_validate(config).url).hostname or "",)

    def plan(self, config):
        typed = self.config_model.model_validate(config)
        parts = urllib.parse.urlsplit(typed.url)
        if not typed.allow_network:
            raise PermissionError("http_json needs allow_network = true; it never contacts a host unasked")
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOOPBACK):
            raise PermissionError("http_json requires https (http only for loopback)")
        return (), (f"One GET request to {parts.hostname}; no other network or file access.",)

    def execute(self, config, plan: ExecutionPlan, fingerprints: tuple[InputFingerprint, ...]) -> AdapterResult:
        typed = self.config_model.model_validate(config)
        headers = {"Accept": "application/json"}
        if typed.token_env:
            token = os.environ.get(typed.token_env)
            if not token:
                raise PermissionError(f"environment variable {typed.token_env} is not set")
            headers["Authorization"] = f"Bearer {token}"
        opener = urllib.request.build_opener(_SameHost)
        with opener.open(urllib.request.Request(typed.url, headers=headers, method="GET"), timeout=30) as response:
            body = json.loads(response.read(MAX_BYTES + 1)[:MAX_BYTES] or b"[]")
        items = _dig(body, typed.items_path) if typed.items_path else body
        facts: list[Fact] = []
        for index, item in enumerate(items if isinstance(items, list) else []):
            if not isinstance(item, dict):
                continue
            stamp = _parse_timestamp(item.get(typed.time_field))
            if not stamp:
                continue
            ident = str(item.get(typed.id_field)) if typed.id_field else f"{index}"
            facts.append(Fact(
                provider_id="http_json", adapter_id="http_json_readonly", source_locator=typed.url,
                source_record_id=ident, observed_at=stamp, event_type=typed.event_type,
                values={"id": ident}, display=str(item.get(typed.title_field) or typed.event_type),
                sensitivity=Sensitivity.PRIVATE))
        stamps = sorted(f.observed_at for f in facts)
        coverage = Coverage(starts_at=stamps[0], ends_at=stamps[-1], complete=False,
                            note="one response page; pagination is not followed") if stamps else Coverage(
            complete=False, note="the response held no usable records")
        return AdapterResult(facts=tuple(facts), provenance=Provenance(
            provider_id="http_json", adapter_id="http_json_readonly",
            adapter_version=self.manifest.adapter_version, adapter_api_version=ADAPTER_API_VERSION,
            plan_id=plan.plan_id, input_fingerprints=fingerprints,
            effective_permissions=plan.permissions, coverage=coverage,
            cache=CacheDirective(reusable=False, cache_key="0" * 64, decision="bypass", reason="set by core")))


P1_ADAPTERS = {"http_json": HttpJsonAdapter()}
