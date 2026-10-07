"""Generate stable Draft 2020-12 schemas from the public adapter contract."""

from __future__ import annotations

import json
from pathlib import Path

from dossify.adapter_api import AdapterManifest, AdapterResult, ExecutionPlan
from dossify.builtin_adapters import P0_ADAPTERS
from dossify.http_adapter import P1_ADAPTERS
from dossify.integrations import OPTIONAL_ADAPTERS

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def adapter_config_schema(provider_id: str) -> dict[str, object]:
    adapter = {**P0_ADAPTERS, **P1_ADAPTERS, **OPTIONAL_ADAPTERS}[provider_id]
    schema = adapter.config_model.model_json_schema()
    schema["$schema"] = SCHEMA_DIALECT
    schema["$id"] = adapter.manifest.config_schema_id
    return schema


def public_schemas() -> dict[str, dict[str, object]]:
    schemas: dict[str, dict[str, object]] = {
        "adapter-api.json": AdapterManifest.model_json_schema(),
        "adapter-result.json": AdapterResult.model_json_schema(),
        "execution-plan.json": ExecutionPlan.model_json_schema(),
    }
    for name, schema in schemas.items():
        schema["$schema"] = SCHEMA_DIALECT
        schema["$id"] = f"https://dossify.dev/schemas/{name}"
    schemas.update(
        {
            f"adapters/{provider_id}.json": adapter_config_schema(provider_id)
            for provider_id in (*P0_ADAPTERS, *P1_ADAPTERS, *OPTIONAL_ADAPTERS)
        }
    )
    return schemas


def write_public_schemas(root: Path) -> None:
    for relative, schema in public_schemas().items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
