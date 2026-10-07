# Support policy

## Support levels

| Level | Meaning |
|---|---|
| `stable_typed` | Built-in typed adapter with plan, facts, coverage, provenance, fixtures and a passing conformance check. |
| `typed_wrapped` | A legacy reader running inside the typed pipeline: typed facts and provenance, reads not itemised in advance. |
| `experimental` | Usable, but format or version support is limited and may change in a minor release. |
| `planned` | A target only. |
| `external_producer` | Dossify reads another tool's export; it does not collect it. |

`dossify providers` prints the level of every provider, and the README table is generated from the same registry.

## Supported export formats (typed adapters)

| Provider | Recognised formats |
|---|---|
| `activitywatch` | ActivityWatch JSON export with `buckets` and `events` |
| `health_archive` | Apple Health `export.xml` (step records), step CSV with `Date` and `Steps` columns |
| `hyperos_dashboard` | `dashboard-history.csv` with columns `date,steps,duration,distance,calories`, from the HyperOS Dashboard history exporter |
| `immich` | Immich metadata JSON export |
| `nextcloud` | Nextcloud Activity JSON export, or an ICS calendar |
| `google_takeout` | A Takeout directory, or an activity JSON file |

An export that does not match is named in the result's warnings and never silently read as empty. Detection reads a few kilobytes and does not validate the whole file.

The HyperOS exporter validates only one phone, system and Dashboard package; Dossify records what the owner supplies about the device and reports whether the days are continuous, and makes no further claim.

## Versioning

- The adapter contract (`dossify-adapter-api`) follows semantic versioning: a major version breaks the contract, and a manifest declares the API range it supports.
- `dossify` follows semantic versioning for commands, configuration and the ledger manifest. A new command or optional setting is a minor release.
- A support level can move up in a minor release and down only with a changelog entry.

## Deprecation

A deprecated command keeps working for at least one minor release and prints its replacement. `sync` is kept as an alias of `people reconcile`.

## What is not supported

Remote services beyond a single configured read-only JSON endpoint and the generic OAuth client. No provider-specific OAuth integrations ship; they are written as external adapters and must pass conformance.
