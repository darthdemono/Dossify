# Changelog

## 1.1.0 - 2026-10-07

- Added six output profiles: `digest`, `journal`, `chronicle` (month files) and `dossier`, `casefile`, `monograph` (compiled documents).
- Added a private run ledger with `journal --review`, `apply <run-id>` and `undo <run-id>`.
- Added per-source outcomes (ok, no events, failed, excluded by policy, replaced by a typed adapter) and `dossify status`; a failing source no longer stops a run.
- Added privacy policy by data class with `minimal`, `balanced` and `forensic` presets.
- Wrapped every legacy journal reader in the typed adapter contract so one pipeline runs all sources.
- Added the HyperOS Dashboard history adapter (steps, walking duration, walking distance, estimated calories).
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
