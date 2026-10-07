"""One collection path for every source, typed or legacy.

Typed P0 adapters run through plan and execute and become journal facts; legacy
sources run as before.  Either way each source ends as an ``Outcome`` (so a
failure or an empty source is recorded, never silent) and every legacy fact has
a typed twin for hashing and indexing.
"""

from __future__ import annotations

import time as _time

from dossify import ledger
from dossify import external
from dossify.builtin_adapters import P0_ADAPTERS
from dossify.http_adapter import P1_ADAPTERS
from dossify.legacy_adapters import LegacyConfig, from_typed, to_typed, wrap_all  # noqa: F401

LEGACY_CONFIG = LegacyConfig()
from dossify.pipeline import build_plan, execute_plan
from dossify.providers import PROVIDER_SOURCE, TYPED_REPLACEMENT


def adapter_table(config) -> dict:
    """Built-in typed adapters plus the owner's allowlisted external ones."""
    table = {**P0_ADAPTERS, **P1_ADAPTERS}
    if config.adapters.external:
        table.update(external.load(config.adapters.external))
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


def collect(config, journal, only: list[str] | None = None):
    """Run every selected source; return ``(facts, outcomes, typed_facts)``.

    ``typed_facts`` are the typed adapters' own facts, kept for cross-source checks.

    ``journal`` is the configured journal module, passed in so this file never
    imports it at load time.
    """
    only = only or []
    facts, outcomes, typed_facts = [], [], []
    typed_enabled = {}
    for name, adapter, typed in selected_p0(config, []):
        typed_enabled[name] = (adapter, typed)
    replaced = {legacy for legacy, p0 in TYPED_REPLACEMENT.items() if p0 in typed_enabled}

    wrappers = wrap_all(journal)
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
