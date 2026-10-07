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

Sources come in three tiers, and the table below says which is which. **Core** sources are general: things many people have, such as git history, bank statements, and the data download you can request from a social platform. **Optional** sources are bundled but niche, such as a particular self-hosted media server, one log format, or a calendar convention. They are plug and play: nothing runs until you write the matching `[providers.<name>]` block. **Custom** plugins are your own, live in a gitignored `custom/` folder, and are described further down. Listing a provider means Dossify knows the shape of its adapter; your private configuration decides whether it is on and where its records live.

<!-- providers:begin -->
| Provider | Category | Facts | Tier | Support |
|---|---|---|---|---|
| `git` | development | commits | core | typed_wrapped |
| `wakatime` | development | coding_time | optional | typed_wrapped |
| `claude` | ai | sessions | optional | typed_wrapped |
| `bank_statements` | finance | transactions | core | typed_wrapped |
| `mail` | communications | messages | core | typed_wrapped |
| `instagram` | social | posts, stories, messages, calls | core | typed_wrapped |
| `facebook` | social | messages, calls | core | typed_wrapped |
| `discord` | social | messages | core | typed_wrapped |
| `snapchat` | social | messages | core | experimental |
| `takeout` | activity | searches, youtube, location, play | core | typed_wrapped |
| `google_takeout` | activity | searches, youtube | core | stable_typed |
| `daily_csv` | health | daily_totals | core | typed_wrapped |
| `lastfm` | media | scrobbles | optional | typed_wrapped |
| `navidrome` | media | plays | optional | typed_wrapped |
| `jellyfin` | media | plays | optional | typed_wrapped |
| `mal` | media | activity | optional | experimental |
| `simkl` | media | activity | optional | experimental |
| `immich_db` | photos | assets | optional | typed_wrapped |
| `immich` | photos | assets | core | stable_typed |
| `ncloud` | files | activity | optional | typed_wrapped |
| `nextcloud` | files | activity | core | stable_typed |
| `docs` | files | created_documents | optional | typed_wrapped |
| `files` | files | filesystem_activity | optional | typed_wrapped |
| `boots` | device | power_sessions | optional | typed_wrapped |
| `logins` | device | sessions | optional | typed_wrapped |
| `dnf` | device | package_changes | optional | typed_wrapped |
| `crashes` | device | crashes | optional | experimental |
| `arr` | homelab | activity | optional | typed_wrapped |
| `github` | development | activity | optional | typed_wrapped |
| `torrents` | homelab | activity | optional | experimental |
| `games` | games | activity | optional | typed_wrapped |
| `saves` | games | save_activity | optional | typed_wrapped |
| `worklog` | work | shifts | optional | typed_wrapped |
| `commute` | travel | trips | optional | typed_wrapped |
| `activitywatch` | device | window_activity | core | stable_typed |
| `health_archive` | health | steps | core | stable_typed |
| `http_json` | homelab | records | core | experimental |
| `elteportal` | education | timetable, submissions, grades | optional | stable_typed |
<!-- providers:end -->

Generated by `dossify providers --markdown`, and a test fails if it drifts from the registry. Support levels: `stable_typed` runs through the typed plan, facts and provenance pipeline; `typed_wrapped` is a legacy reader running inside the typed pipeline (typed facts and provenance, reads not itemised in advance); `experimental` has limited format support; `external_producer` reads another tool's export; `planned` is a target only. Enabling a typed adapter replaces its legacy twin (`immich`, `nextcloud` for `ncloud`, `google_takeout` for `takeout`) instead of doubling it.

## The private boundary

Dossify is the engine. Your private workspace is the memory. Keep these beside the journal, outside this repository.

| File | Owns | Important rule |
| --- | --- | --- |
| `dossify.toml` | Everything configurable: output location, timezone, privacy policy, and one `[providers.<name>]` block per source. | It is the single entry point. Nothing runs without a block. No secret ever goes in it. |
| `People.json` | Canonical people and provider-specific identifiers. | The journal only reads it. `dossify sync` can explicitly reconcile it with exact-name Nextcloud and Immich records. |
| `custom/` | Your own plugins, as Python files. | Gitignored, auto-discovered, switched on by a provider block. |

[`dossify.example.toml`](dossify.example.toml) and [`People.example.json`](People.example.json) show the public-safe shapes, and [`docs/PROVIDERS.md`](docs/PROVIDERS.md) lists every option of every source. [`schemas/People.schema.json`](schemas/People.schema.json) validates the identity map for editors.

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

## Wiring a source

The whole configuration is one file. A source is **off** until it has a block, and the block's keys are its options:

```toml
timezone = "Europe/London"

[providers.git]
roots = ["~/Code"]

[providers.bank_statements]
sources = ["~/Documents/statements"]

[providers.lastfm]
user = "your-name"
api_key_env = "LASTFM_API_KEY"
```

Four conventions cover almost everything. A path option may start with `~`. `export` is the folder of an unzipped data download, one path or a list. A credential is never written in the file: you give the name of an environment variable (`api_key_env`) or a command that prints it (`api_key_command = ["tool", "arg"]`), so any secret manager works. `psql` is a command prefix that opens `psql` on the right database, for the few sources that read one, and `docker exec` or a plain `psql -h` both fit.

There is no separate rules file. Everything that used to be a personal rule is an option on the provider it affects: merchant names and prefixes on `bank_statements`, camera ownership on the photo source, chat renames on the social ones. If you do not use a source you never see its options.

`timezone` is an IANA name (the default is the machine's own). If you moved country, add `[[timezone_history]]` with an `until` instant and the `zone` that applied before it, and older records are shown in the zone you were in.

## Social media: exports, not APIs

Dossify never logs in to a social platform and never asks for a password or a token. It reads the **data download** each platform lets you request about yourself. That is the only supported route, and it keeps working when an API gets locked down.

For each platform: request your data from its account settings, choose a machine-readable format (JSON for the Meta platforms, Discord and Snapchat, JSON or HTML activity for Google), wait for the archive, unzip it somewhere, and point the provider's `export` at that folder. Where exactly the request lives changes from time to time, so look in the platform's own account or privacy settings. `dossify ingest` can unpack downloaded zips into a tidy folder for you, but it is optional.

| Provider | `export` points at | What Dossify reads | Text it can show |
| --- | --- | --- | --- |
| `instagram` | the unzipped Instagram download (or a folder holding it) | posts, stories, reels, likes, places, message counts | thread names only with `messages = "threads"` |
| `facebook` | the unzipped Facebook download | posts, comments, check-ins, message counts | thread names only with `messages = "threads"` |
| `discord` | the unzipped Discord data package | message counts per day | counts only |
| `snapchat` | the unzipped Snapchat download | what the export carries per day | counts only |
| `takeout` | a folder holding one Takeout per Google account, or a single account's Takeout | searches, YouTube watching, Chrome hosts, Timeline movement, Play installs, Fit | search text only with `search_text = true`, hosts only with `browser_urls = true` |

Message bodies are never written to the journal. By default a chat is a count; with `messages = "threads"` it also names who the chat is with. Rename or group chats with `title_renames`, `communities` and `noise_chats` on the provider. The privacy policy still applies on top, so `minimal` can hide a whole source.

A missing or unmounted `export` folder is not an error: that source goes quiet and the status report says so, so an unplugged disk never looks like a quiet month.

## Commands

### `dossify config-validate <config>`

Loads the TOML and validates its structure. Run this first after moving a private workspace or changing a provider block.

### `dossify journal <config> [adapters...] [--profile digest|journal|chronicle] [--review] [--apply] [--force]`

Collects facts from the configured adapters (typed and legacy, through one collection path), applies the privacy policy, sorts and formats them, then reports the generated daily blocks. Without a flag, nothing is changed and nothing is recorded. `--review` records the run in the private ledger and still changes nothing. With `--apply`, Dossify replaces only the content between `<!-- auto:begin YYYY-MM-DD -->` and `<!-- auto:end -->`; everything outside those markers is untouched. A source that fails is recorded as failed and the others still run.

### `dossify apply <config> <run-id>` and `dossify undo <config> <run-id>`

`apply` writes exactly what a reviewed run proposed, and refuses if any file changed since the review. `undo` restores the files an applied run changed, and refuses if any of them was edited afterwards. A run that covered only some adapters cannot be applied without `--force`.

### `dossify compile <config> [--profile dossier|casefile|monograph] [--period all|YYYY|YYYY-MM] [--output file | --write]`

Compiles a standalone report from the same facts. Prints to the terminal unless `--output` or `--write` (into `<output_dir>/Dossiers/`) is given. See Output profiles.

### `dossify status <config>`, `dossify doctor <config>`, `dossify init <directory>`

`status` shows per-source coverage from the latest recorded run: ok, no events, failed, excluded by privacy policy, replaced by a typed adapter, plus silent gaps of two weeks or more inside a source's own range. A source that returned nothing is never shown as if nothing happened. `doctor` checks paths, the ledger directory, profile and privacy settings, the presence (never the value) of credential variables, and typed adapter sources. `init` creates a private workspace skeleton and never overwrites a file.

### `dossify index <config>` and `dossify search <config> "<query>"`

`index` builds a disposable SQLite full-text index of the timeline in the cache directory, after the privacy policy. `search` queries it read-only. Delete the index whenever you like; Markdown stays canonical.

### `dossify conformance <config> <adapter>`, `dossify adapters --external`

`conformance` runs the adapter conformance suite (manifest, deterministic read-only plan, provenance identity, permissions, deterministic results) against a configured typed adapter. `adapters --external` lists installed third-party adapters; none loads unless its name is under `[adapters] external` in your private configuration. The adapter contract is its own package, `dossify-adapter-api`, so an adapter never needs the engine.

### `dossify facts <config> <plan> --since-checkpoint [--overlap-days N]`

Resumable typed imports: emits only facts within the overlap window before the last checkpoint and reports whether the input is `unchanged` or `changed_input`.

### `dossify login <config> <provider>`, `dossify logout <config> <provider>`

Single-user, read-only OAuth (authorization code with PKCE, loopback redirect) for a `[oauth.<provider>]` block. Network access needs `allow_network = true` and an `allowed_hosts` list; the token is stored mode 0600 in the file you name; `logout` revokes at the provider when a revocation URL is set, then deletes the token. No provider-specific integration ships; write one as an external adapter.

### `dossify profiles`, `dossify people reconcile <config>`, `dossify people claims <config>`

`profiles` lists the output profiles. `people reconcile` is the clearer name for `dossify sync`, which still works. `people claims` lists every identity as a claim with provider, validity period and provenance, and reports identifiers held by two people at overlapping times; it never merges anything by fuzzy match.

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

## Output profiles

Six profiles, from a quick note to a research-paper document. All of them read the same facts: a deeper profile never knows more than a shallower one, it only says more about how it knows.

| Profile | Kind | What you get |
|---|---|---|
| `digest` | journal | Basic journal: at most 12 headline lines a day, no nested detail. |
| `journal` | journal | Standard journal: every generated line. The default, and exactly the output Dossify has always written. |
| `chronicle` | journal | Advanced journal: the full journal plus a per-day coverage line naming each source. |
| `dossier` | document | Scope, source coverage, monthly activity, measured facts and stated claims. |
| `casefile` | document | The dossier plus a day-by-day index, claim evidence and a gap register. |
| `monograph` | document | Research-paper layout: abstract, scope, method, results, evidence footnotes, stated claims, limitations, reproducibility appendix. |

Journal profiles reshape the generated block in your month files (`--profile`, or `[output] profile`). Document profiles never touch month files; they compile a separate report with `dossify compile`.

## Privacy by data class

A policy says what *kind* of data may be rendered and at what granularity: `raw`, `count` (one tally per day) or `hidden`. Classes: `message_content`, `search_terms`, `location`, `health`, `financial`, `faces`, `file_paths`, `media_titles`.

```toml
[privacy]
preset = "balanced"          # minimal | balanced | forensic; omit the block for no restriction

[privacy.classes]
financial = "count"          # per-class override
```

`forensic` renders everything, `balanced` tallies messages, search terms and file paths, `minimal` hides or tallies every sensitive class. The policy applies to the journal, the compiled documents and the search index, and the ledger records which sources it changed. Source options such as `messages` and `search_text` still apply on top.

## General tools in core, niche ones as plugins

The public tool ships only **general** sources: things many people have and that can be described without naming anyone's accounts. Git history, a bank statement in CSV or PDF, a photo library's metadata, a calendar export, a messaging export, a health archive, a generic read-only JSON endpoint. If a source is useful to nearly anyone, it belongs in core, with fixtures and tests.

Everything **niche** is plug and play. Some of it ships in the repository as optional sources you switch on with a block. The rest is yours, and stays out of the repository. Your university's portal, the app your particular phone uses, a bank's private API, the scripts that only make sense on your machine: those are plugins, and they live in a folder called `custom/` at the root of your checkout. That folder is gitignored and never published. You write a Python file (or a small package) in it, Dossify finds it on every run, and nobody reading the public code can tell what you use. That matters more than it sounds: a list of your banks, your university and your devices is exactly what someone writing a phishing message wants.

Here is the whole contract. A file in `custom/` exposes `ADAPTER` (one adapter), `ADAPTERS` (several) or a `register()` function that returns them. An adapter is a small object with a manifest, a pydantic config model, a `plan` that says what it will read, and an `execute` that returns facts. It depends only on the `dossify-adapter-api` package, so it never needs the engine. Discovery is automatic, with no registration step, because this is your own code on your own machine. Discovery does not switch a plugin on, though. A `[providers.<name>]` block in your private `dossify.toml` does, so a plugin you are still writing cannot run by accident.

The same rule covers plugins you install as packages. A package registers an entry point in the `dossify.adapters` group, and Dossify loads it only when a block of the same name exists. There is no separate allowlist: writing the block is the opt-in, and installing a package never runs it by itself. That is the route for sharing a niche reader with other people as a plain package that anyone can plug in.

A plugin that fails to import is reported and skipped, never fatal, and `dossify custom <config>` lists what was found, what is on, and what is broken. `dossify conformance <config> <name>` runs the contract checks against a plugin, and `[privacy.source_classes]` tells the privacy policy what kind of data it carries so `minimal` and `balanced` cover it too. A plugin can mark a fact with `values = {"summary": true}` and it will lead its day, like a daily total. If the thing you wrote turns out to be useful to everyone, promote it: move it into core, strip anything personal, add tests.

### Bundled niche adapters: ELTE portal

The one niche adapter that talks to a service rather than reading a file is the ELTE portal one. It reads Canvas submissions and grades, and the Neptun timetable, for students whose university the [EltePortal](https://github.com/darthdemono/EltePortal) library supports. It lives in the same repository but needs nothing from the core, and the core needs nothing from it: the library is imported only when you switch the adapter on.

Setting it up alongside Dossify is three steps. First download the library into Dossify's environment, which is what the `elte` extra does:

```pwsh
uv sync --extra elte
```

Then switch the adapter on with a block in your `dossify.toml`:

```toml
[providers.elteportal]
neptun_ics = "~/Calendars/neptun.ics"    # a calendar export from Neptun; the timetable is read from this file
canvas = true                            # submissions
grades = true                            # the grade timeline
# profile = "~/university.toml"          # another university's EltePortal profile; the bundled one when omitted
```

Then run `dossify doctor <config>`. It says whether the library is installed, whether the profile loads, whether a Canvas token resolves (it never prints the token), and whether the calendar file is there. Canvas reads use EltePortal's own secret handling, so set up the token the way its documentation describes; Dossify never stores or logs it. If you skip the first step, the run records `failed` with the exact command to run, and the other sources carry on.

The Neptun side deliberately reads an exported calendar file and never logs in, so this adapter can never trigger the captcha lockout a bad Neptun login can cause. Live Neptun reads belong to the `elte` command itself.

## Daily totals from any CSV

`daily_csv` is a basic reader for a CSV with one row per day: steps, distance, calories, minutes, anything. You name the files and say which columns to show. The first column leads the line, the rest follow in brackets, and the line leads its day like coding time does. A phone dashboard exporter such as [hyperos-dashboard-history-exporter](https://github.com/darthdemono/hyperos-dashboard-history-exporter) is one way to get such a file, a wearable's export or a hand-kept spreadsheet is another; none of them is special.

```toml
[providers.daily_csv]
files = ["~/Exports/dashboard"]          # a folder, a glob, a file, or a list; the newest file wins per day
title = "Dashboard"

[[providers.daily_csv.columns]]
column = "steps"
label = "steps"

[[providers.daily_csv.columns]]
columns = ["distance_m", "distance"]     # alternatives: the first one with a value wins
scale = 0.001
format = "{:.2f} km"
kind = "distance"                        # also tidies a text value like 3km into 3 km

[[providers.daily_csv.columns]]
column = "calories"
format = "{} kcal"
```

That produces lines such as `Dashboard: 5,013 steps (3.00 km; 205 kcal)`. Numbers are scaled and formatted by the column; text cells such as `51m10s` are tidied and shown as written.

One more rule, because it is the point: core never names a specific bank, university, device vendor or service of yours. If you catch it doing that, it is a bug.

## Bank statements

`bank_statements` reads CSV and PDF statements from the folders or files listed under `sources`. Columns, encodings, dates and amounts are recognised by shape, and PDFs need poppler's `pdftotext`. Per source you can set `currency`, `whole_units` and `card_prefixes`; on the provider, `names`, `strip_prefixes`, `strip_suffixes` and `accent_digraphs` turn terminal-style counterparties into names a person would say, and `contacts_csv` can resolve people. See `docs/SUPPORT_POLICY.md` for what it recognises and where it has to guess.

## Claims and what Dossify refuses to infer

Every statement in a document says how it is known. Dossify generates only `observed` claims (a source reported it) and `derived` claims (a deterministic count). `user_asserted` and `disputed` claims come from your private `claims_file` (JSON list of `{predicate, value, claim_type, ...}`); an `inferred` claim in that file is rejected. Dossify refuses outright to produce medical or mental-health diagnoses, beliefs, relationship status or closeness, sleep from inactivity, exercise type from steps, productivity, emotional state, or criminal behaviour. It can report the underlying evidence; it will not draw the conclusion.

## The run ledger

`--review` and `--apply` write a private run record under `ledger_dir` (default: `<cache_dir>/runs`): a manifest with the run id, profile, privacy policy, per-source outcome and coverage, an evidence digest, the timezone assumptions, per-file hashes before and after, and the previous run, plus the proposed and previous text of each changed month and a unified diff. It is an audit trail, not a database: delete it and nothing but undo is lost.

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

Photo ownership is a rule, not a guess. The photo options of the photo source can include an item when it was shot by one of your configured cameras **or** when the configured self identity is recognised in it. It can separately suppress copied images, exclude people, recognise special albums, and normalize historical device names. This is why camera aliases and self aliases live in `Journal Rules.json` instead of in code.

People work the same way. `People.json` is a data migration from an older identity map, not a cosmetic rename file. It preserves the evidence necessary to render a person correctly for each source. When the data says an association is uncertain, the correct output is uncertainty, not an invented name.

## Development

Run the test suite from the project directory:

```pwsh
Set-Location "$HOME/Code/Dossify"
uv run pytest
```

The tests cover private-path resolution, identity pairing, plan-only dry runs, stale-plan rejection, deterministic cache results, Takeout redaction, and checked-in schema snapshots. A complete private journal compilation can take longer because it reads real exports; test it as a dry run before using `--apply`.

The public project uses the standard `src/` layout. `dossify.config` validates private TOML, `dossify.people` validates private identities, `dossify.providers` declares generic adapter capabilities, and the journal, ingest, and migration modules perform the work.

## Documents

`docs/ARCHITECTURE.md` is the normative description of the pipeline, invariants, claims and identity model. `docs/SUPPORT_POLICY.md` lists support levels, recognised export formats, versioning and deprecation. `THREAT_MODEL.md` states what is protected and what is not.

## Licence

Dossify is licensed under the Apache License 2.0 (see `LICENSE`). The `NOTICE` file names the author, Jubair Hasan (DarthDemono). Apache-2.0 requires anyone who redistributes Dossify or a derivative work to keep that `NOTICE` and to state their changes, so the work stays attributed to its author.

## Status

Dossify 1.1 runs every source, typed or legacy, through one typed pipeline with a run ledger, a privacy policy by data class and six output profiles. Legacy readers are wrapped in the typed contract rather than rewritten, so their behaviour is unchanged; the support table says which provider is which. Remote access is limited to a generic read-only JSON adapter and a generic OAuth client, both opt-in. Provider-specific remote integrations are written as external adapters.
