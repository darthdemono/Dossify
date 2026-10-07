# Migrating from `Journal Rules.json`

Earlier versions kept personal settings in a second file, `Journal Rules.json`, named by `[journal] rules_file`. That file is retired. Dossify refuses to load a config that still names it, and tells you to come here. Every old key became an option on the provider it belongs to, and every provider is now switched on by its own block.

Two behaviour changes come with that. A source now runs **only if it has a `[providers.<name>]` block**, instead of every reader running against built-in guesses about where your files live. And there are no hard-coded locations any more: if a source needs a database or a folder, you name it.

| Old key | Now |
| --- | --- |
| `paths.bank_statements`, `bank_names`, `bank_cleanup.*`, `paths.contacts_export_glob` | `[providers.bank_statements]`: `sources`, `names` (pattern to name), `strip_prefixes`, `strip_suffixes`, `accent_digraphs`, `contacts_csv` |
| `exports.roots` | each social provider's own `export` (see the social media section of the README) |
| `exports.parts.message_threads` / `message_text` | `messages = "threads"` on `instagram` and `facebook` (otherwise `"none"`) |
| `exports.parts.search_text`, `browser_urls` | `search_text`, `browser_urls` on `takeout` |
| `exports.known_places` | `known_places` on `takeout` |
| `exports.move_utc`, `exports.before_move_timezone` | top-level `timezone` plus `[[timezone_history]]` with `until` and `zone` |
| `social.instagram_title_renames`, `communities`, `noise_chats` | `title_renames`, `communities`, `noise_chats` on `instagram` (and `communities`, `noise_chats` on `facebook`) |
| `social.roster_max`, `inline_max` | `[journal] group_chat_roster_max`, `group_chat_inline_max` |
| `photo_policy.*` | `self_names`, `not_mine_names`, `cameras`, `special_album`, `derived_name_pattern`, `camera_name_pattern` on the photo source (`immich_db`) |
| `accounts.*_user`, `jellyfin_username` | `user` on the matching provider |
| `accounts.git_author_terms` | `author_terms` on `git` |
| `accounts.calendar_ics_env_vars` | `ics = [{ url_env = "VAR" }]` on `commute` |
| `paths.work_log`, `paths.simkl_backup_csv`, `save_files` | `path` on `worklog`, `backup_csv` on `simkl`, `files` on `saves` |
| `paths.os_log_dir` | `[journal] os_log_dir` |
| `os_log.crash_ignore` | `ignore` on `crashes` |
| `source_descriptions` | gone: each source describes itself |
| credentials fetched from a secret manager by name | `api_key_env` or `api_key_command` on the provider that needs one |

Two names changed so they could not collide with the typed export adapters: the database photo reader is `immich_db` (the file-export adapter keeps `immich`), and the document filer is `docs`.

A reader that used to have an implicit default path (a git folder, a media database, a download client's resume folder) now needs that path in its block. `docs/PROVIDERS.md` lists every option.
