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
    ProviderSpec("activitywatch", "device", ("window_activity",)),
    ProviderSpec("health_archive", "health", ("steps",)),
    ProviderSpec("hyperos_dashboard", "health", ("steps", "walking_duration", "walking_distance", "calories_estimated")),
    ProviderSpec("http_json", "homelab", ("records",)),
)


# Legacy journal source -> the typed P0 adapter that replaces it when configured.
TYPED_REPLACEMENT = {"immich": "immich", "takeout": "google_takeout", "ncloud": "nextcloud",
                     "xiaomi_dashboard": "hyperos_dashboard"}
# A typed adapter whose lines should slot in under an existing journal source name.
PROVIDER_SOURCE = {"hyperos_dashboard": "xiaomi_dashboard"}

MATURITY = {
    "stable_typed": "Typed plan, facts, coverage, provenance and fixtures",
    "typed_wrapped": "A legacy reader running inside the typed pipeline: typed facts and provenance, reads not itemised in advance",
    "experimental": "Usable, but format or version support is limited",
    "planned": "Architectural or research target only",
    "external_producer": "Dossify reads another tool's export; it does not collect it",
}
EXTERNAL = {"xiaomi_dashboard", "xiaomi_fitness"}
EXPERIMENTAL = {"http_json", "snapchat", "mal", "simkl", "torrents", "crashes", "shell"}


def maturity_of(name: str) -> str:
    """Support level of one provider, derived from the registry, never typed twice."""
    from dossify.builtin_adapters import P0_ADAPTERS

    if name in P0_ADAPTERS:
        return "stable_typed"
    if name in EXTERNAL:
        return "external_producer"
    if name in EXPERIMENTAL:
        return "experimental"
    return "typed_wrapped"


def provider_manifest() -> list[dict[str, object]]:
    return [
        {"name": spec.name, "category": spec.category, "capabilities": list(spec.capabilities),
         "maturity": maturity_of(spec.name)}
        for spec in CURRENT_PROVIDER_SPECS
    ]


def provider_table() -> str:
    """Markdown support matrix: the README embeds exactly this text."""
    rows = ["| Provider | Category | Facts | Support |", "|---|---|---|---|"]
    rows += [f"| `{p['name']}` | {p['category']} | {', '.join(p['capabilities'])} | {p['maturity']} |"
             for p in provider_manifest()]
    return "\n".join(rows)
