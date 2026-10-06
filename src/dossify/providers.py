"""Provider registry for Dossify adapters.

Adapters are intentionally configured in a private TOML file. This public module
contains names and capabilities only, never an account, export path, or journal data.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    category: str
    capabilities: tuple[str, ...]


CURRENT_PROVIDER_SPECS = (
    ProviderSpec("erste", "finance", ("transactions",)),
    ProviderSpec("brac", "finance", ("transactions",)),
    ProviderSpec("git", "development", ("commits",)),
    ProviderSpec("wakatime", "development", ("coding_time",)),
    ProviderSpec("claude", "ai", ("sessions",)),
    ProviderSpec("mail", "communications", ("messages",)),
    ProviderSpec("instagram", "social", ("posts", "stories", "messages", "calls")),
    ProviderSpec("facebook", "social", ("messages", "calls")),
    ProviderSpec("discord", "social", ("messages",)),
    ProviderSpec("snapchat", "social", ("messages",)),
    ProviderSpec("google_takeout", "activity", ("searches", "youtube")),
    ProviderSpec("lastfm", "media", ("scrobbles",)),
    ProviderSpec("navidrome", "media", ("plays",)),
    ProviderSpec("jellyfin", "media", ("plays",)),
    ProviderSpec("mal", "media", ("activity",)),
    ProviderSpec("simkl", "media", ("activity",)),
    ProviderSpec("immich", "photos", ("assets",)),
    ProviderSpec("nextcloud", "files", ("activity",)),
    ProviderSpec("documents", "files", ("created_documents",)),
    ProviderSpec("files", "files", ("filesystem_activity",)),
    ProviderSpec("neptun", "education", ("events",)),
    ProviderSpec("canvas", "education", ("events",)),
    ProviderSpec("grades", "education", ("grades",)),
    ProviderSpec("xiaomi_dashboard", "health", ("steps",)),
    ProviderSpec("xiaomi_fitness", "health", ("workouts",)),
    ProviderSpec("boots", "device", ("power_sessions",)),
    ProviderSpec("logins", "device", ("sessions",)),
    ProviderSpec("dnf", "device", ("package_changes",)),
    ProviderSpec("crashes", "device", ("crashes",)),
    ProviderSpec("shell", "device", ("commands",)),
    ProviderSpec("arr", "homelab", ("activity",)),
    ProviderSpec("github", "development", ("activity",)),
    ProviderSpec("torrents", "homelab", ("activity",)),
    ProviderSpec("games", "games", ("activity",)),
    ProviderSpec("saves", "games", ("save_activity",)),
    ProviderSpec("worklog", "work", ("shifts",)),
    ProviderSpec("commute", "travel", ("trips",)),
)


def provider_manifest() -> list[dict[str, object]]:
    return [
        {"name": spec.name, "category": spec.category, "capabilities": list(spec.capabilities)}
        for spec in CURRENT_PROVIDER_SPECS
    ]
