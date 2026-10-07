"""External adapter discovery through Python entry points.

Loading an entry point runs third-party code, so nothing loads unless the owner
named it under ``[adapters] external`` in their private configuration.  An
external adapter may not take the name of a built-in provider.
"""

from __future__ import annotations

from importlib import metadata

from dossify.builtin_adapters import P0_ADAPTERS
from dossify.privacy import SOURCE_CLASS

GROUP = "dossify.adapters"
RESERVED = set(P0_ADAPTERS) | set(SOURCE_CLASS) | {"git", "wakatime", "claude", "neptun", "canvas",
                                                    "grades", "worklog", "boots", "logins", "dnf",
                                                    "crashes", "shell", "github", "ncloud"}


def available() -> dict[str, metadata.EntryPoint]:
    return {ep.name: ep for ep in metadata.entry_points(group=GROUP)}


def load(allowed: list[str]) -> dict[str, object]:
    """Load only allowlisted adapters; an unknown or reserved name is an error."""
    found = available()
    loaded: dict[str, object] = {}
    for name in allowed:
        if name in RESERVED:
            raise ValueError(f"external adapter {name!r} collides with a built-in provider")
        if name not in found:
            raise ValueError(f"external adapter {name!r} is allowed in config but not installed")
        target = found[name].load()
        adapter = target() if isinstance(target, type) else target
        if adapter.manifest.provider_id != name:
            raise ValueError(f"entry point {name!r} declares provider_id {adapter.manifest.provider_id!r}")
        loaded[name] = adapter
    return loaded
