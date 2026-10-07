# Provider options

Every source is switched on by a `[providers.<name>]` block in `dossify.toml` and configured by the keys of that block. This table is generated from each source module by `dossify providers --options`, and a test fails if it drifts.

Common conventions: `export` is the folder of an unzipped data download (one path or a list); `user` is an account name; credentials are never written in the file, only fetched at run time with `api_key_env = "VAR"` (an environment variable) or `api_key_command = ["tool", "arg"]` (a command that prints the secret); `psql` is a command prefix that opens a `psql` prompt on the right database; paths may start with `~`.

| Provider | Tier | What it reads | Options |
|---|---|---|---|
| `arr` | optional | Grabbed and imported items from Sonarr and Radarr history databases. | sonarr_db, radarr_db. |
| `bank_statements` | core | Bank statements (CSV and PDF): the counterparty cleaner and the reader. | sources, names, strip_prefixes, strip_suffixes, accent_digraphs, contacts_csv. |
| `discord` | core | Chat exports from Discord and Snapchat (data-request archives). | export (the extracted archive folder, or several). |
| `snapchat` | core | Chat exports from Discord and Snapchat (data-request archives). | export (the extracted archive folder, or several). |
| `claude` | optional | AI coding-assistant session transcripts on this machine. | projects_dir (default ~/.claude/projects). |
| `commute` | optional | Travel either side of a shift, from calendar events named 'Travel ...'. | work_pattern, home_pattern, psql (command prefix), nextcloud_user, nextcloud_calendars, ics (list of {url_env | url_command}). |
| `daily_csv` | core | Daily totals from any CSV with one row per day (steps, distance, calories, minutes, anything numeric). | files (a file, a folder, a glob, or a list of them), title, date_column (default date), date_format (default %Y-%m-%d), columns (a list of tables: column or columns, label, scale, format, kind = "distance" to space a unit like 3km). |
| `docs` | optional | Documents created, from DD-MM-YYYY dates in file names under chosen folders. | root (default workspace_root), folders. |
| `games` | optional | Game plays kept in the durable OS log. | none |
| `git` | core | Commits from local git repositories. | roots (folders of repos), repos (single repos), author_terms. |
| `github` | optional | Account activity from the GitHub API (pushes are skipped; git reads those). | user, api_key_env or api_key_command. |
| `immich_db` | optional | Photos taken, from an Immich database. | psql (command prefix opening psql), self_names, not_mine_names, cameras (model to label), special_album, derived_name_pattern, camera_name_pattern. |
| `jellyfin` | optional | Plays from a Jellyfin library database. | user, db (path to jellyfin.db). |
| `lastfm` | optional | Scrobbles fetched from the Last.fm API and cached. | user, api_key_env or api_key_command, cache. |
| `mail` | core | Mail sent, from a local Thunderbird profile. | profiles (default ~/.thunderbird). |
| `mal` | optional | Anime list activity from the MyAnimeList API. | user, api_key_env or api_key_command (a client id). |
| `facebook` | core | Instagram and Facebook data-download exports. | export, messages ('none' counts only; 'threads' also names who), title_renames, communities, noise_chats. |
| `instagram` | core | Instagram and Facebook data-download exports. | export, messages ('none' counts only; 'threads' also names who), title_renames, communities, noise_chats. |
| `navidrome` | optional | Plays from a Navidrome database that a scrobbler did not receive. | db. |
| `ncloud` | optional | Activity counts from a Nextcloud database. | psql (a command prefix that opens psql on the database). |
| `files` | optional | Files opened, from the desktop's recently-used list. | file (default ~/.local/share/recently-used.xbel). |
| `saves` | optional | Play sessions from save-analyser markdown reports. | dir, files, default_game (the game name used before a report names one). |
| `simkl` | optional | Watch history from the Simkl API, or a CSV backup when the API is not set up. | api_key_env or api_key_command, token_file, backup_csv. |
| `boots` | optional | Boots, desktop logins, package changes and crashes, from the durable OS log. | crashes.ignore (executable substrings to skip). |
| `crashes` | optional | Boots, desktop logins, package changes and crashes, from the durable OS log. | crashes.ignore (executable substrings to skip). |
| `dnf` | optional | Boots, desktop logins, package changes and crashes, from the durable OS log. | crashes.ignore (executable substrings to skip). |
| `logins` | optional | Boots, desktop logins, package changes and crashes, from the durable OS log. | crashes.ignore (executable substrings to skip). |
| `takeout` | core | Google Takeout activity (search, YouTube, Chrome, location, Play, Fit). | export, search_text, browser_urls, known_places ([lat, lng, radius_km, name] rows). |
| `torrents` | optional | Download completions from qBittorrent resume files. | dir (the BT_backup folder). |
| `wakatime` | optional | Hours coded per day from the WakaTime API. | api_key_env or api_key_command. |
| `worklog` | optional | Shifts from a markdown work-log table. | path, label (a short employer name shown before the role). |

### Typed adapters

These read a file or an address you give them and validate their block strictly.

| Provider | Tier | What it reads | Options |
|---|---|---|---|
| `activitywatch` | core | ActivityWatch export | source |
| `google_takeout` | core | Google Takeout activity export | source |
| `health_archive` | core | Apple Health, Fitbit, or Google Fit export | source |
| `immich` | core | Immich metadata export | source |
| `nextcloud` | core | Nextcloud Activity or ICS export | source |
| `http_json` | core | Read-only self-hosted JSON API | url, allow_network, token_env, items_path, time_field, title_field, id_field, event_type |
| `elteportal` | optional | ELTE portal (Canvas submissions and grades, Neptun timetable) | neptun_ics, canvas, grades, profile, settings |
