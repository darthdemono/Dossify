# 1.0.0 release preparation

The package version and public adapter API are 1.0.0. The release scope is local, export-first evidence compilation: typed facts, source provenance, plan-first execution, cache ownership, deterministic P0 fixtures, and checked-in schemas.

Validated on 04-10-2026:

- `uv run pytest -q` passes 11 tests.
- Targeted Ruff and ty checks pass for the v1 public contract, pipeline, adapters, schema generator, configuration, CLI, and adapter tests.
- `uv build` produces a source distribution and universal wheel.
- A synthetic ActivityWatch export completes `dossify plan` then `dossify facts` without exposing the window title.

Do not publish a public release until the owner selects an explicit licence and adds it to the repository. P1 connectors, entry-point discovery, OAuth, and remote service access are deliberately out of scope. The legacy journal implementation remains supported but is not yet a whole-tree strict-lint/type gate; finish that migration or document the precise supported verification gate before publishing.
