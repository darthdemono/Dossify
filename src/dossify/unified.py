"""One collection path for every source, typed or legacy.

Typed P0 adapters run through plan and execute and become journal facts; legacy
sources run as before.  Either way each source ends as an ``Outcome`` (so a
failure or an empty source is recorded, never silent) and every legacy fact has
a typed twin for hashing and indexing.
"""

from __future__ import annotations

import json
import time as _time

from dossify import ledger
from dossify import external
from dossify.builtin_adapters import P0_ADAPTERS
from dossify.http_adapter import P1_ADAPTERS
from dossify.integrations import OPTIONAL_ADAPTERS
from dossify.legacy_adapters import LegacyConfig, LegacyJournalAdapter, from_typed, to_typed, wrap_all  # noqa: F401
from dossify.sources import registry

LEGACY_CONFIG = LegacyConfig()
from dossify.pipeline import build_plan, execute_plan
from dossify.providers import PROVIDER_SOURCE, TYPED_REPLACEMENT


def adapter_table(config) -> dict:
    """Built-in typed adapters plus the owner's allowlisted external ones."""
    table = {**P0_ADAPTERS, **P1_ADAPTERS, **OPTIONAL_ADAPTERS}
    table.update(external.load_configured(config))        # installed plugins the config asks for
    custom, _errors = external.discover_custom(external.custom_dir(config))
    table.update(custom)                      # the owner's own plugins, auto-wired
    return table


def selected_p0(config, requested: list[str]):
    table = adapter_table(config)
    names = requested or [name for name in table if name in config.providers]
    unknown = sorted(set(names) - set(table))
    if unknown:
        raise ValueError(f"not a typed adapter: {', '.join(unknown)}")
    selected = []
    for name in names:
        values = config.providers.get(name)
        if values is None:
            raise ValueError(f'{name} needs a [providers.{name}] block with source = "..."')
        typed = table[name].config_model.model_validate(values)
        if typed.enabled:
            selected.append((name, table[name], typed))
    return selected


def _bound(module, fn, options):
    """A reader that first hands its module the provider's own options."""
    def run():
        module._O = options
        journal_module = __import__("dossify.journal", fromlist=["x"])
        journal_module.CACHE_SALT = json.dumps(options, sort_keys=True, default=str)
        return fn()
    return run


def collect(config, journal, only: list[str] | None = None):
    """Run every selected source; return ``(facts, outcomes, typed_facts)``.

    ``typed_facts`` are the typed adapters' own facts, kept for cross-source checks.

    ``journal`` is the configured journal module, passed in so this file never
    imports it at load time.
    """
    only = only or []
    journal.DAY_SUMMARIES = list(journal.DAY_SUMMARY_BASE)
    facts, outcomes, typed_facts = [], [], []
    for name, message in external.discover_custom(external.custom_dir(config))[1].items():
        outcomes.append(ledger.Outcome(f"custom/{name}", "failed", error=message))
        print("custom plugin %-12s FAILED %s" % (name, message))
    typed_enabled = {}
    for name, adapter, typed in selected_p0(config, []):
        typed_enabled[name] = (adapter, typed)
    replaced = {legacy for legacy, p0 in TYPED_REPLACEMENT.items() if p0 in typed_enabled}

    wrappers = {}
    for key, (module, fn) in registry.readers().items():
        block = config.providers.get(key)
        if block is None or not block.get("enabled", True):
            continue
        wrappers[key] = LegacyJournalAdapter(key, _bound(module, fn, block))
    wrappers.update(wrap_all(journal))                 # extra always-on readers (tests, embedders)
    for key, wrapper in wrappers.items():
        if only and key not in only:
            outcomes.append(ledger.Outcome(key, "not_selected"))
            continue
        if key in replaced:
            outcomes.append(ledger.Outcome(key, "replaced_by_typed",
                                           note=f"typed adapter {TYPED_REPLACEMENT[key]} is enabled"))
            continue
        start = _time.monotonic()
        try:
            result = execute_plan(wrapper, LEGACY_CONFIG, build_plan(wrapper, LEGACY_CONFIG))
            got = [from_typed(f, journal.Fact) for f in result.facts]
        except Exception as exc:  # a broken source must not erase the others
            outcomes.append(ledger.Outcome(key, "failed", error=f"{type(exc).__name__}: {exc}"[:200]))
            print("source %-9s FAILED %s" % (key, outcomes[-1].error))
            continue
        outcomes.append(ledger.summarise(key, got))
        print("source %-9s %5d facts  %.1fs" % (key, len(got), _time.monotonic() - start))
        facts += got

    for name, (adapter, typed) in typed_enabled.items():
        if only and name not in only:
            outcomes.append(ledger.Outcome(name, "not_selected"))
            continue
        try:
            result = execute_plan(adapter, typed, build_plan(adapter, typed), config.journal.cache_dir)
        except Exception as exc:
            outcomes.append(ledger.Outcome(name, "failed", error=f"{type(exc).__name__}: {exc}"[:200]))
            print("source %-9s FAILED %s" % (name, outcomes[-1].error))
            continue
        typed_facts += list(result.facts)
        for fact in result.facts:                       # a daily total leads its day, like coding time
            if fact.values.get("summary") and name not in journal.DAY_SUMMARIES:
                journal.DAY_SUMMARIES.append(name)
        got = [from_typed(f, journal.Fact) for f in result.facts if f.values.get("render") is not False]
        got = [f._replace(src=PROVIDER_SOURCE.get(f.src, f.src)) for f in got]
        journal.SOURCES.setdefault(name, f"{adapter.manifest.display_name} (typed adapter export)")
        outcome = ledger.summarise(name, got)
        cov = result.provenance.coverage
        outcome.note = "coverage " + ("complete" if cov.complete else "incomplete") + (
            f": {cov.note}" if cov.note else "")
        outcomes.append(outcome)
        print("source %-9s %5d facts  (typed)" % (name, len(got)))
        facts += got
    return list(dict.fromkeys(facts)), outcomes, typed_facts
