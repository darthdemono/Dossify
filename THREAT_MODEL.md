# Threat model

Dossify compiles private records into Markdown on one machine. This file states what it protects, what it does not, and the rules it keeps.

## Assets

Journal text, exports (messages, searches, health, finance, location), the identity file, the run ledger and the search index. All of them are private and none belongs in this repository.

## Trust boundaries

- **Owner-supplied exports are untrusted input.** They are parsed, never executed, and read only from paths the configuration names. Typed adapters publish every intended read in a plan before parsing, and a stale plan is rejected.
- **The engine has no cloud dependency and no telemetry.** The only network use is the explicit `sync` command and sources the owner configures, each read-only unless `--apply` is given.
- **Secrets are never stored in configuration.** `[sync]` holds the names of environment variables, never values. `doctor` checks that a variable is set and never prints it.
- **Writes are bounded.** Generated content lives between `auto:begin` and `auto:end` markers. A subset of adapters cannot write without `--force`. `apply` refuses if a file changed since review and `undo` refuses if a file was edited after the run.

## What the ledger and index contain

The ledger holds file paths, hashes, counts, coverage and the proposed and previous month text. The index holds the rendered timeline lines after the privacy policy. Both live in the cache area, inherit the privacy policy, and are safe to delete. Protect them like the journal itself.

## Network, OAuth and third-party adapters

- **Network is off by default.** `http_json` and `oauth` refuse to contact a host unless `allow_network = true` and the host is in `allowed_hosts`. Both require https (loopback http only). A redirect to a different host is refused.
- **OAuth tokens** are stored only in a file the owner names, created mode 0600. A token file readable by group or others is refused. Client secrets are never in TOML: only the name of an environment variable. Scopes are explicit and listed; `logout` revokes at the provider when a revocation URL is configured and deletes the file. The loopback listener binds 127.0.0.1 only and checks the `state` value.
- **Third-party adapters run arbitrary code.** They load only when named under `[adapters] external`, may not use a built-in provider's name, and should pass `dossify conformance` first. Conformance proves contract behaviour, not harmlessness: read an adapter's source before trusting it.

## Out of scope

- A compromised machine or account. Dossify does not encrypt at rest; use disk encryption.
- Anything the privacy policy does not classify: sources outside the data-class table always render raw.
- Anything a trusted external adapter does with the access you gave it.

## Reporting

Report a vulnerability privately to the repository owner rather than in a public issue, and do not attach real data.
