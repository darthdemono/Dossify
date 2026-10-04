# Changelog

## 1.0.0 - 2026-10-04

- Added the public, versioned typed fact, adapter manifest, provenance, execution-plan, coverage, and cache contracts.
- Added export-first P0 adapters for ActivityWatch, Nextcloud Activity/ICS, Immich metadata, Google Takeout activity, and Apple Health, Fitbit, and Google Fit step archives.
- Added canonical plan and fact commands. A plan reads no source contents, and execution rejects stale plans.
- Added core-owned SHA-256 provenance and deterministic cache handling for P0 results.
- Added checked-in Draft 2020-12 schemas and fixture-based tests for redaction, determinism, plan safety, and schema snapshots.
- Deliberately deferred external adapter discovery, P1 services, remote OAuth, and source mutation.
