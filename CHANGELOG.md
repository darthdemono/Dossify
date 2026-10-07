# Changelog

## 1.1.0 - 2026-10-07

- **One config file.** `Journal Rules.json` is retired. Every personal setting is now an option on the `[providers.<name>]` block it belongs to, and a source runs only when it has a block. See `docs/MIGRATING.md` and `docs/PROVIDERS.md` (generated from the source modules).
- **Sources are modules.** The 3,000-line journal module is split into `dossify.sources.*`, each with its own options, label and tier. **Core** sources are general; **optional** ones are bundled niche readers you switch on; `custom/` plugins are yours. Hard-coded personal locations and secret-manager calls were removed from the code; credentials come from `api_key_env` or `api_key_command`.
- **Daily totals from any CSV.** The dedicated phone-dashboard reader is replaced by `daily_csv`, a basic one-row-per-day reader you point at files and columns; the exporter is just one way to produce such a file.
- **ELTE portal is a bundled optional adapter.** Canvas submissions and grades plus the Neptun timetable, through the public EltePortal library. `uv sync --extra elte` downloads it, a `[providers.elteportal]` block switches it on, `dossify doctor` checks the connection, and a missing library is a recorded failure with the install command. Fact dates now follow the configured timezone.
- **Social media is explicit.** Instagram, Facebook, Discord, Snapchat and Google Takeout read the data download you name with `export`. No login, no API.
- **Timezone is configuration** (`timezone`, `[[timezone_history]]`), not a pair of hard-coded cities.
- Installed plugins load when a provider block of the same name exists; the `[adapters] external` allowlist is gone.
- Cache keys now include the provider's options, so changing one can never serve a stale result.

- Added six output profiles: `digest`, `journal`, `chronicle` (month files) and `dossier`, `casefile`, `monograph` (compiled documents).
- Added a private run ledger with `journal --review`, `apply <run-id>` and `undo <run-id>`.
- Added per-source outcomes (ok, no events, failed, excluded by policy, replaced by a typed adapter) and `dossify status`; a failing source no longer stops a run.
- Added privacy policy by data class with `minimal`, `balanced` and `forensic` presets.
- Wrapped every legacy journal reader in the typed adapter contract so one pipeline runs all sources.
- Added one generic `bank_statements` provider that reads CSV and PDF statements, replacing bank-specific readers. Anything tied to one person's accounts or devices (a university portal, a phone's activity export) is now an external adapter, not core.
- Added the gitignored `custom/` plugin folder: files in it are auto-wired (no entry point or allowlist), isolated if broken, and switched on by a `[providers.<name>]` block. New `dossify custom` command; `doctor` reports plugin load errors; plugin facts marked `summary` lead their day.
- Removed the shell-history reader (it could never produce anything: history files carry no timestamps) and the Mi Fitness reader.
- Removed the university-portal and device-vendor readers from core, along with their path setting; they live in external adapters. `[privacy.source_classes]` lets the privacy policy cover an external adapter.
- Added claims, identity claims with validity periods, and review tasks for contradictions.
- Moved the adapter contract into the `dossify-adapter-api` package; added entry-point adapter discovery, an allowlist, and `dossify conformance`.
- Added checkpoints (`facts --since-checkpoint`), export-format detection, a disposable full-text index with `index` and `search`.
- Added a loopback PKCE OAuth client (`login`, `logout`) and the read-only `http_json` adapter, both opt-in per provider.
- Added `init`, `doctor`, `profiles`, `people reconcile` (alias of `sync`), `people claims`.
- Added the Apache-2.0 licence with a NOTICE file, a threat model, architecture and support policy documents, and CI.

## 1.0.0 - 2026-10-04

- Added the public, versioned typed fact, adapter manifest, provenance, execution-plan, coverage, and cache contracts.
- Added export-first P0 adapters for ActivityWatch, Nextcloud Activity/ICS, Immich metadata, Google Takeout activity, and Apple Health, Fitbit, and Google Fit step archives.
- Added canonical plan and fact commands. A plan reads no source contents, and execution rejects stale plans.
- Added core-owned SHA-256 provenance and deterministic cache handling for P0 results.
- Added checked-in Draft 2020-12 schemas and fixture-based tests for redaction, determinism, plan safety, and schema snapshots.
- Deliberately deferred external adapter discovery, P1 services, remote OAuth, and source mutation.
