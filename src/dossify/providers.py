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
    ProviderSpec("git", "development", ("commits",)),
    ProviderSpec("wakatime", "development", ("coding_time",)),
    ProviderSpec("claude", "ai", ("sessions",)),
    ProviderSpec("bank_statements", "finance", ("transactions",)),
    ProviderSpec("mail", "communications", ("messages",)),
    ProviderSpec("instagram", "social", ("posts", "stories", "messages", "calls")),
    ProviderSpec("facebook", "social", ("messages", "calls")),
    ProviderSpec("discord", "social", ("messages",)),
    ProviderSpec("snapchat", "social", ("messages",)),
    ProviderSpec("takeout", "activity", ("searches", "youtube", "location", "play")),
    ProviderSpec("google_takeout", "activity", ("searches", "youtube")),
    ProviderSpec("daily_csv", "health", ("daily_totals",)),
    ProviderSpec("lastfm", "media", ("scrobbles",)),
    ProviderSpec("navidrome", "media", ("plays",)),
    ProviderSpec("jellyfin", "media", ("plays",)),
    ProviderSpec("mal", "media", ("activity",)),
    ProviderSpec("simkl", "media", ("activity",)),
    ProviderSpec("immich_db", "photos", ("assets",)),
    ProviderSpec("immich", "photos", ("assets",)),
    ProviderSpec("ncloud", "files", ("activity",)),
    ProviderSpec("nextcloud", "files", ("activity",)),
    ProviderSpec("docs", "files", ("created_documents",)),
    ProviderSpec("files", "files", ("filesystem_activity",)),
    ProviderSpec("boots", "device", ("power_sessions",)),
    ProviderSpec("logins", "device", ("sessions",)),
    ProviderSpec("dnf", "device", ("package_changes",)),
    ProviderSpec("crashes", "device", ("crashes",)),
    ProviderSpec("arr", "homelab", ("activity",)),
    ProviderSpec("github", "development", ("activity",)),
    ProviderSpec("torrents", "homelab", ("activity",)),
    ProviderSpec("games", "games", ("activity",)),
    ProviderSpec("saves", "games", ("save_activity",)),
    ProviderSpec("worklog", "work", ("shifts",)),
    ProviderSpec("commute", "travel", ("trips",)),
    ProviderSpec("activitywatch", "device", ("window_activity",)),
    ProviderSpec("health_archive", "health", ("steps",)),
    ProviderSpec("http_json", "homelab", ("records",)),
    ProviderSpec("elteportal", "education", ("timetable", "submissions", "grades")),
)


# Legacy journal source -> the typed P0 adapter that replaces it when configured.
TYPED_REPLACEMENT = {"immich_db": "immich", "takeout": "google_takeout", "ncloud": "nextcloud"}
# A typed adapter whose lines should slot in under an existing journal source name.
PROVIDER_SOURCE: dict[str, str] = {}

MATURITY = {
    "stable_typed": "Typed plan, facts, coverage, provenance and fixtures",
    "typed_wrapped": "A legacy reader running inside the typed pipeline: typed facts and provenance, reads not itemised in advance",
    "experimental": "Usable, but format or version support is limited",
    "planned": "Architectural or research target only",
    "external_producer": "Dossify reads another tool's export; it does not collect it",
}
EXTERNAL: set[str] = set()
EXPERIMENTAL = {"http_json", "snapchat", "mal", "simkl", "torrents", "crashes"}


def maturity_of(name: str) -> str:
    """Support level of one provider, derived from the registry, never typed twice."""
    from dossify.builtin_adapters import P0_ADAPTERS

    from dossify.integrations import OPTIONAL_ADAPTERS

    if name in P0_ADAPTERS or name in OPTIONAL_ADAPTERS:
        return "stable_typed"
    if name in EXTERNAL:
        return "external_producer"
    if name in EXPERIMENTAL:
        return "experimental"
    return "typed_wrapped"


def tier_of(name: str) -> str:
    """core (general) or optional (a bundled niche reader you switch on); typed adapters are core."""
    from dossify.integrations import OPTIONAL_ADAPTERS
    from dossify.sources import registry

    return "optional" if name in OPTIONAL_ADAPTERS else registry.tiers().get(name, "core")


def provider_manifest() -> list[dict[str, object]]:
    return [
        {"name": spec.name, "category": spec.category, "capabilities": list(spec.capabilities),
         "maturity": maturity_of(spec.name), "tier": tier_of(spec.name)}
        for spec in CURRENT_PROVIDER_SPECS
    ]


def provider_table() -> str:
    """Markdown support matrix: the README embeds exactly this text."""
    rows = ["| Provider | Category | Facts | Tier | Support |", "|---|---|---|---|---|"]
    rows += [f"| `{p['name']}` | {p['category']} | {', '.join(p['capabilities'])} | {p['tier']} | {p['maturity']} |"
             for p in provider_manifest()]
    return "\n".join(rows)


def typed_options_markdown() -> str:
    """Options of the typed adapters, from their config models, for docs/PROVIDERS.md."""
    from dossify.builtin_adapters import P0_ADAPTERS
    from dossify.http_adapter import P1_ADAPTERS
    from dossify.integrations import OPTIONAL_ADAPTERS

    rows = ["| Provider | Tier | What it reads | Options |", "|---|---|---|---|"]
    for table, tier in ((P0_ADAPTERS, "core"), (P1_ADAPTERS, "core"), (OPTIONAL_ADAPTERS, "optional")):
        for name, adapter in sorted(table.items()):
            fields = ", ".join(f"{key}" for key in adapter.config_model.model_fields if key != "enabled")
            rows.append(f"| `{name}` | {tier} | {adapter.manifest.display_name} | {fields} |")
    return "\n".join(rows)
