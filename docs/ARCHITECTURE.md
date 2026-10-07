# Architecture

Normative description of how Dossify turns private records into Markdown. "Must" and "never" are requirements; tests enforce the ones marked (tested).

## Pipeline

```
sources -> adapters -> typed facts -> privacy policy -> projections (journal, documents, index)
                              |                                  |
                         run ledger  <----------------------------+
```

1. **Adapters** turn owner-supplied records into facts. Every source, typed or legacy, runs through the same contract: a manifest, a `plan` that declares intended reads without parsing them, and an `execute` that returns validated facts with provenance. Legacy readers are wrapped (`typed_wrapped`); their plans say reads are not itemised in advance.
2. **Facts** are source-linked and timezone-aware (`observed_at`), with a time precision, a sensitivity and a retention class. A legacy fact keeps its exact calendar date and clock so wrapping never moves a record across midnight (tested).
3. **Privacy policy** is applied once, before any projection (journal, document, index). Data classes map to `raw`, `count` or `hidden`. No `[privacy]` block means unrestricted (tested).
4. **Projections** are views of the same facts. Journal profiles reshape the generated block of a month file. Document profiles compile a separate report. The index is a disposable SQLite full-text table. Markdown stays canonical.
5. **The run ledger** records each reviewed or applied run: per-source outcome, coverage, evidence digest, review tasks, timezone assumptions, per-file hashes, and the proposed and previous text.

## Invariants

- A subset of adapters never writes without `--force`; fences are rebuilt wholesale (tested).
- `apply` writes exactly the reviewed text and refuses if any file changed since (tested). `undo` refuses if any file was edited after the run (tested).
- A failing source is recorded as failed and never stops the others (tested). An empty source is `no_events`, never silence.
- Manual and LLM sections of a month file are never touched; only text between `auto:begin` and `auto:end` is generated.
- Typed adapters never write. A plan that requests write access fails conformance (tested).
- Sources that may share sensors (a phone's activity export and a health archive, say) are reported side by side and never summed (tested).

## Claims

Every document statement carries a type: `observed` (a source reported it), `derived` (a deterministic count), `user_asserted` or `disputed` (from the owner's claims file), `inferred` or `unknown` (vocabulary only). Dossify generates `observed` and `derived` claims. The claims file refuses `inferred`. A fixed list of predicates (diagnoses, beliefs, relationship status or closeness, sleep from inactivity, exercise type, productivity, emotional state, criminal behaviour) is refused outright (tested).

## Identity

`People.json` supplies exact identifiers. Each becomes an `IdentityClaim` with provider, identifier, optional validity period and provenance. There is no fuzzy matching. Two people holding one identifier at overlapping times is a review task, not a silent choice, and an ambiguous identifier resolves to nobody (tested).

## Review tasks

Checked on every run and stored in the ledger: identifier ownership conflicts, future-dated records, and disagreeing step totals from typed sources. Nothing else is compared, and documents say so.

## Adapters and the evidence contract

The contract lives in the separate `dossify-adapter-api` package, which depends only on pydantic. The owner's own plugins live in a gitignored `custom/` folder and are discovered automatically (a `[providers.<name>]` block still switches one on). A published adapter package registers an entry point in the `dossify.adapters` group instead. Dossify loads an installed adapter only if the owner lists its name under `[adapters] external`, rejects a name that collides with a built-in provider, and expects `dossify conformance` to pass before the owner relies on it. The conformance suite checks the manifest, plan determinism, read-only plans, provenance identity, declared versus effective permissions and determinism of results.

## Resumable imports

After a run, `facts --since-checkpoint` stores each adapter's coverage end and input hashes. The next run emits only facts within the overlap window (default 3 days) before that end, reports whether the input is `unchanged` or `changed_input`, and never suppresses a changed input.

## Remote access

Network use is opt-in per provider. `oauth` implements a single-user, read-only authorization-code flow with PKCE and a loopback redirect; `http_json` reads one configured JSON endpoint of a self-hosted service. Both require `allow_network = true`, an `allowed_hosts` list, https (loopback http only), and never follow a redirect to another host. Tokens live in an owner-named file created mode 0600 and a world-readable token file is refused. See `THREAT_MODEL.md`.

## Decisions

- Markdown is the canonical record; the ledger, caches and indexes are rebuildable (read-only derived data).
- One privacy policy by data class, not per-provider switches. Provider-specific rules-file settings still apply on top.
- Core stays general; anything niche is a plugin in `custom/`, so the public code never reveals what one person uses.
- Legacy readers are wrapped, not rewritten, so a refactor cannot change a private journal's output.
- Claims are counted or quoted; Dossify has no inference engine and says so.
