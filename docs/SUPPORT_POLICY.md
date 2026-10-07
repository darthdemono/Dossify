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
| `immich` | Immich metadata JSON export |
| `nextcloud` | Nextcloud Activity JSON export, or an ICS calendar |
| `google_takeout` | A Takeout directory, or an activity JSON file |

An export that does not match is named in the result's warnings and never silently read as empty. Detection reads a few kilobytes and does not validate the whole file.


## Versioning

- The adapter contract (`dossify-adapter-api`) follows semantic versioning: a major version breaks the contract, and a manifest declares the API range it supports.
- `dossify` follows semantic versioning for commands, configuration and the ledger manifest. A new command or optional setting is a minor release.
- A support level can move up in a minor release and down only with a changelog entry.

## Deprecation

A deprecated command keeps working for at least one minor release and prints its replacement. `sync` is kept as an alias of `people reconcile`.

## What is not supported

Remote services beyond a single configured read-only JSON endpoint and the generic OAuth client. No provider-specific OAuth integrations ship; they are written as external adapters and must pass conformance.

## Custom plugins and external adapters

Anything tied to one person's accounts or devices belongs outside core. There are two routes, and both use the `dossify-adapter-api` contract and `dossify conformance`:

- **`custom/` (the owner's own plugins).** A gitignored folder at the root of the checkout, or the path in `[adapters] custom_dir`, or `$DOSSIFY_CUSTOM_DIR`. Every `name.py` or `name/__init__.py` in it is wired in automatically; a broken one is reported and skipped; a `[providers.<name>]` block switches one on. It may not take a built-in provider's name.
- **Installed packages (entry points).** A third-party package registers in the `dossify.adapters` group, and Dossify loads it only if its name is listed under `[adapters] external`.

`[privacy.source_classes]` maps a plugin's provider to a data class so the privacy policy covers it. A fact whose `values` carry `"summary": true` leads its day.

## Bank statements

One generic `bank_statements` provider reads CSV and PDF statements from the `sources` listed in `[providers.bank_statements]`. CSV headers are recognised by common words in any order, in UTF-8 or UTF-16, with comma, semicolon or tab delimiters, and debit/credit column pairs are supported. PDFs are read with `pdftotext -layout` (poppler must be installed) and each line is recognised as a date, a description and one or two trailing numbers; direction comes from the running-balance change, starting from an `Opening balance` line when the statement prints one; with neither, the first line is treated as money out because the page does not say. A transaction present in both a CSV and a PDF is reported once. A row that cannot be read is skipped, never guessed. Bank-specific prefixes and accent spellings are configured under `bank_cleanup` in the private rules file.
