# Dossify

**Dossify turns the records already on your machine into a journal you can read: what happened, when it happened, and where each line came from. It compiles private exports into Markdown.**

Your activity is already scattered across messages, photos, commits, music history, banking exports, calendars, health backups, course portals, and a dozen other places. Those records are useful separately but difficult to hold together. Dossify reads the sources you choose, applies rules you own, and writes one chronological auto-generated section into each daily journal. The manual part of the journal remains yours.

The repository is deliberately empty of personal data. There are no journal entries, names, account handles, exports, secrets, device identifiers, local paths, or hard-coded assumptions about one person's life. A private workspace supplies all of that through configuration files kept outside this repository.

---

## What it does

- Compiles configured activity into dated Markdown journal entries.
- Keeps day-wide summaries such as coding time and step counts at the top, before chronological events.
- Groups high-volume activity such as messages, searches, calls, listening, and documents into readable sections instead of interrupting the timeline.
- Keeps provider identities explicit. `People.json` matches exact normalized identifiers only, so a typo, transliteration, reordered name, or near match cannot silently become a person.
- Handles exports and local records across social activity, finance, development, media, photos, files, education, health, devices, travel, work, games, and homelab services.
- Runs locally. The engine has no cloud dependency, telemetry, or built-in remote filesystem access.
- Has a versioned evidence contract: facts retain timestamps, source locators, sensitivity, and execution provenance.

The provider registry currently covers finance, development, AI sessions, mail, social exports, search and video history, media services, photos, files, education, health, device activity, homelab services, games, work, and commutes. A provider being listed means Dossify knows the shape of that adapter; your private configuration decides whether it is enabled and where its records live.

## The private boundary

Dossify is the engine. Your private workspace is the memory. Keep the following files beside the journal, outside this repository.

| File | Owns | Important rule |
| --- | --- | --- |
| `dossify.toml` | Paths, output location, enabled providers, and the names of private data files. | It is the entry point for every run. |
| `People.json` | Canonical people and provider-specific identifiers. | The journal only reads it. `dossify sync` can explicitly reconcile it with exact-name Nextcloud and Immich records. |
| `Journal Rules.json` | Source labels, export roots, device aliases, photo ownership rules, account-specific settings, and formatting policy. | It is typed data, not Python constants. |

[`People.example.json`](People.example.json), [`Journal Rules.example.json`](<Journal Rules.example.json>), and [`dossify.example.toml`](dossify.example.toml) show the public-safe shapes. [`schemas/People.schema.json`](schemas/People.schema.json) and [`schemas/Journal Rules.schema.json`](<schemas/Journal Rules.schema.json>) provide editor and validator contracts for those JSON files. Copy the examples into a private workspace and replace every example value there. Do not add your real files to this repository.

`People.json` is intentionally more precise than a loose name replacement list. New maps use independent `instagram_names`, `instagram_usernames`, `facebook_names`, and `facebook_usernames` arrays, plus exact Nextcloud, Immich, Discord, and Snapchat identifiers. The canonical object key is the shared person name, so Immich needs only its stable person ID. Legacy paired Instagram entries remain supported read-only. Dossify normalizes Unicode presentation forms and case only, then requires an exact one-person match. It does not strip accents, trim names, reorder words, transliterate, or use fuzzy matching. An identifier that maps to more than one person remains unresolved.

Dossify does not run an MCP server and does not grant a chat access to local files. It only compiles the local records that its private configuration permits.

## Quick start

You need Python 3.13 or newer and [uv](https://docs.astral.sh/uv/). The first command checks the private configuration without reading every provider; the second runs a dry compilation; the third writes the auto-generated journal blocks.

```pwsh
uv run --directory "$HOME/Code/Dossify" dossify config-validate "$HOME/Documents/PrivateJournal/dossify.toml"
uv run --directory "$HOME/Code/Dossify" dossify journal "$HOME/Documents/PrivateJournal/dossify.toml"
uv run --directory "$HOME/Code/Dossify" dossify journal "$HOME/Documents/PrivateJournal/dossify.toml" --apply
```

`journal` is dry-run by default. `--apply` is the deliberate write switch. If you name only a subset of adapters, Dossify refuses to write unless you also pass `--force`; a partial run must not silently erase facts from a complete generated block.

### `dossify sync <config> [--snapshot-dir path] [--report path] [--apply]`

Builds an exact-name plan across `People.json`, the configured Nextcloud CardDAV
address book, and Immich people. It expands the registry to include every named
source record and records their stable IDs. It also reconciles full birthdays
and Facebook/Instagram usernames, but never deletes data, creates a remote
record, or guesses a match. Unicode presentation variants and case are accepted;
accents, spaces, word order, transliterations, and near matches are not.

The command prints a plan by default. `--snapshot-dir` saves the three
before-state inputs so the plan can be checked against a 1:1 reproduction.
`--apply` is the only write mode, requires a snapshot directory, writes the map
atomically, and uses CardDAV and the Immich API rather than either database.
Conflicting full birthdays are reported and left unchanged.

The private workspace can also keep a small PowerShell wrapper so everyday use stays one command:

```pwsh
& "$HOME/Documents/PrivateJournal/Run-Dossify.ps1" journal
```

## Commands

### `dossify config-validate <config>`

Loads the TOML and validates its structure. Run this first after moving a private workspace, adding a rules file, or changing a provider.

### `dossify journal <config> [adapters...] [--apply] [--force]`

Collects facts from the configured adapters, sorts and formats them, then reports the generated daily blocks. Without `--apply`, nothing is changed. With `--apply`, Dossify replaces only the content between `<!-- auto:begin YYYY-MM-DD -->` and `<!-- auto:end -->`; everything outside those markers is untouched.

### `dossify ingest <config> ...`

Inspects and safely ingests provider export archives. It exists for imports that need preparation before the journal compiler can read them. It replaces a private workspace helper script, not the journal itself.

### `dossify migrate <config> <months...> [--apply] [--demote-h3]`

Performs the one-time structural migration that adds Manual, LLM, and Auto sections to selected monthly files. It is not part of normal journal generation.

### `dossify providers`

Prints the built-in provider capability manifest. It is a public inventory, not a list of what you use.

### `dossify adapters [--json]`

Lists the public, export-first P0 adapter manifests. Version 1.0 ships ActivityWatch, Nextcloud Activity/ICS, Immich metadata, Google Takeout activity, and Apple Health, Fitbit, or Google Fit step archives. They are local file parsers only: no OAuth, remote API, or service credentials are accepted.

### `dossify plan <config> [adapters...] [--output plan.json]`

Creates a canonical preflight plan without parsing export contents, writing facts, or updating the cache. The plan lists the exact files it would read, effective read permission, input size and modification time, warnings, and a hash-bound plan ID.

### `dossify facts <config> <plan.json> [--output facts.json]`

Executes only a plan that still matches the selected adapter configuration and input metadata. It emits deterministic normalized facts and provenance, including SHA-256 input fingerprints, coverage, permission scope, and cache decision. A changed input requires a new plan.

## Journal shape

Dossify writes a small, stable region inside a daily note.

```markdown
#### Auto generated

<!-- auto:begin 2026-01-01 -->

- 9,042 steps (5 km; 364 kcal; 1 h 53 min)
- Coded 1 h 53 min: project A (56 min), project B (30 min)
- 13:05 · Story on Instagram: Example[^instagram]
- Texted:[^instagram]
    - 13:12 · Example conversation

<!-- auto:end -->
```

Day-wide summaries come first because they describe the whole day. Individual events then follow in time order. Repeated, detail-heavy kinds of data are grouped into named sections so a list of searches or messages does not make the main timeline unreadable. The exact categories, labels, source citations, privacy choices, aliases, and photo inclusion policy belong in `Journal Rules.json`.

## Photos and people

Photo ownership is a rule, not a guess. A private photo policy can include an item when it was shot by one of your configured cameras **or** when the configured self identity is recognised in it. It can separately suppress copied images, exclude people, recognise special albums, and normalize historical device names. This is why camera aliases and self aliases live in `Journal Rules.json` instead of in code.

People work the same way. `People.json` is a data migration from an older identity map, not a cosmetic rename file. It preserves the evidence necessary to render a person correctly for each source. When the data says an association is uncertain, the correct output is uncertainty, not an invented name.

## Development

Run the test suite from the project directory:

```pwsh
Set-Location "$HOME/Code/Dossify"
uv run pytest
```

The tests cover private-path resolution, identity pairing, plan-only dry runs, stale-plan rejection, deterministic cache results, Takeout redaction, and checked-in schema snapshots. A complete private journal compilation can take longer because it reads real exports; test it as a dry run before using `--apply`.

The public project uses the standard `src/` layout. `dossify.config` validates private TOML, `dossify.people` validates private identities, `dossify.providers` declares generic adapter capabilities, and the journal, ingest, and migration modules perform the work.

## Status

Dossify 1.0 stabilizes the local evidence boundary: generic engine here, private records elsewhere. The legacy journal renderer remains supported while its existing providers are migrated behind the typed contract. P1 service integrations, external adapter discovery, and read-only OAuth remain intentionally deferred until their capability, fixture, and secret-storage contracts are settled.
