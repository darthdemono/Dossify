"""Run every legacy journal reader through the typed adapter contract.

The 36 original readers still live in ``journal.py`` and still know how to find
their own records.  Wrapping them gives each one a manifest, a reviewable plan,
typed facts and provenance, so there is one pipeline for every source.  Reads
are not itemised in advance because a legacy reader discovers its files itself;
the plan says so rather than pretending.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    TimePrecision,
)
from dossify.pipeline import ExecutionPlan
from dossify.privacy import SOURCE_CLASS

SENSITIVE_CLASSES = ("message_content", "health", "financial", "faces")


class LegacyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True


def to_typed(fact, adapter_id: str = "legacy-journal") -> Fact:
    """Wrap one legacy ``Fact(date, time, text, src)`` without losing any field."""
    local_tz = datetime.now().astimezone().tzinfo
    clock = (fact.time or "00:00")[:5]
    try:
        at = datetime.fromisoformat(f"{fact.date}T{clock}").replace(tzinfo=local_tz)
    except ValueError:
        at = datetime.fromisoformat(f"{fact.date}T00:00").replace(tzinfo=local_tz)
    return Fact(
        provider_id=fact.src, adapter_id=adapter_id, source_locator=f"legacy:{fact.src}",
        observed_at=at,
        time_precision=TimePrecision.INSTANT if fact.time else TimePrecision.DAY,
        event_type="legacy.activity",
        values={"date": fact.date, "time": fact.time, "text": fact.text, "src": fact.src},
        display=fact.text,
        sensitivity=Sensitivity.SENSITIVE if SOURCE_CLASS.get(fact.src) in SENSITIVE_CLASSES
        else Sensitivity.PRIVATE)


def from_typed(fact: Fact, fact_type):
    """Back to a journal line.  Legacy facts restore their exact date and clock,
    never a timezone conversion of ``observed_at``."""
    values = fact.values
    if "date" in values and "text" in values:
        return fact_type(values["date"], values.get("time"), values["text"],
                         values.get("src", fact.provider_id))
    if fact.time_precision is TimePrecision.DAY:
        # Day facts are anchored at UTC midnight; converting would shift the date.
        return fact_type(fact.observed_at.astimezone(UTC).strftime("%Y-%m-%d"), None,
                         fact.display or fact.event_type, fact.provider_id)
    local = fact.observed_at.astimezone()
    return fact_type(local.strftime("%Y-%m-%d"), local.strftime("%H:%M"),
                     fact.display or fact.event_type, fact.provider_id)


class LegacyJournalAdapter:
    """Typed-contract wrapper around one ``a_<name>()`` journal reader."""

    config_model = LegacyConfig

    def __init__(self, name: str, reader):
        self.reader = reader
        self.manifest = AdapterManifest(
            provider_id=name, adapter_id=f"{name}_legacy_reader",
            display_name=f"{name} (legacy reader)", adapter_version="1.0.0",
            adapter_api_min="1.0", adapter_api_max="1.0", config_schema_version="1.0",
            config_schema_id=f"https://dossify.dev/schemas/adapters/{name}-legacy/1.0.json",
            capabilities=("facts.read", "legacy.reader"),
            requested_permissions=("filesystem.read",), deterministic_output=False)

    def plan(self, config):
        return (), ("Legacy reader: it discovers its own files, so reads are not itemised in advance.",)

    def execute(self, config, plan: ExecutionPlan,
                fingerprints: tuple[InputFingerprint, ...]) -> AdapterResult:
        facts = tuple(to_typed(f, self.manifest.adapter_id) for f in self.reader())
        stamps = sorted(f.observed_at for f in facts)
        coverage = (Coverage(starts_at=stamps[0], ends_at=stamps[-1], complete=False,
                             note="legacy reader does not report completeness")
                    if facts else Coverage(complete=False, note="the reader returned no records"))
        return AdapterResult(facts=facts, provenance=Provenance(
            provider_id=self.manifest.provider_id, adapter_id=self.manifest.adapter_id,
            adapter_version=self.manifest.adapter_version, adapter_api_version=ADAPTER_API_VERSION,
            plan_id=plan.plan_id, input_fingerprints=fingerprints,
            effective_permissions=plan.permissions, coverage=coverage,
            cache=CacheDirective(reusable=False, cache_key="0" * 64, decision="bypass",
                                 reason="set by core")))


def wrap_all(journal_module) -> dict[str, LegacyJournalAdapter]:
    return {fn.__name__[2:]: LegacyJournalAdapter(fn.__name__[2:], fn) for fn in journal_module.ADAPTERS}
