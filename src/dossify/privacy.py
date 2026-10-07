"""Privacy policy by data class.

A policy names what *kind* of data a provider carries (message content, health
measurements, financial values, ...) and how much of it may be rendered:
``raw`` keeps every line, ``count`` replaces a day's lines with one tally, and
``hidden`` drops them.  No ``[privacy]`` block means unrestricted, which is the
behaviour before policies existed.
"""

from __future__ import annotations

from collections import Counter, defaultdict

GRANULARITIES = ("raw", "count", "hidden")

# Which data class each legacy journal source carries.  A source missing here
# carries no class a policy can restrict and always renders raw.
SOURCE_CLASS = {
    "instagram": "message_content", "facebook": "message_content",
    "discord": "message_content", "snapchat": "message_content", "mail": "message_content",
    "takeout": "search_terms",
    "commute": "location",
    "bank_statements": "financial",
    "immich": "faces",
    "docs": "file_paths", "files": "file_paths",
    "jellyfin": "media_titles", "navidrome": "media_titles", "lastfm": "media_titles",
    "mal": "media_titles", "simkl": "media_titles", "torrents": "media_titles",
    "arr": "media_titles", "games": "media_titles", "saves": "media_titles",
}
CLASSES = tuple(sorted(set(SOURCE_CLASS.values())))

PRESETS: dict[str, dict[str, str]] = {
    "forensic": {name: "raw" for name in CLASSES},
    "balanced": {
        **{name: "raw" for name in CLASSES},
        "message_content": "count", "search_terms": "count", "file_paths": "count",
    },
    "minimal": {
        "message_content": "hidden", "search_terms": "hidden", "file_paths": "hidden",
        "faces": "hidden", "location": "count", "health": "count",
        "financial": "count", "media_titles": "count",
    },
}


def check_source_classes(source_classes: dict[str, str]) -> None:
    """Reject a class a policy could never restrict, so a typo cannot fail open."""
    for source, name in source_classes.items():
        if name not in CLASSES:
            raise ValueError(f"source {source!r} maps to unknown data class {name!r}; use one of {', '.join(CLASSES)}")


def resolve(preset: str | None, overrides: dict[str, str]) -> dict[str, str]:
    """Merge a preset with per-class overrides, rejecting unknown names."""
    if preset is None and not overrides:
        return {}
    if preset is not None and preset not in PRESETS:
        raise ValueError(f"unknown privacy preset {preset!r}; use one of {', '.join(PRESETS)}")
    policy = dict(PRESETS.get(preset or "", {}))
    for name, level in overrides.items():
        if name not in CLASSES:
            raise ValueError(f"unknown data class {name!r}; use one of {', '.join(CLASSES)}")
        if level not in GRANULARITIES:
            raise ValueError(f"data class {name} must be one of {', '.join(GRANULARITIES)}, not {level!r}")
        policy[name] = level
    return policy


def apply(facts, policy: dict[str, str], labels: dict[str, str] | None = None,
          source_classes: dict[str, str] | None = None):
    """Return ``(facts, excluded)`` with the policy applied.

    ``excluded`` maps a source to ``hidden`` or ``count`` when the policy changed
    what it renders, so the run ledger can say so rather than look like silence.
    """
    if not policy:
        return list(facts), {}
    kept, tally, excluded = [], defaultdict(Counter), {}
    classes = {**SOURCE_CLASS, **(source_classes or {})}
    for fact in facts:
        level = policy.get(classes.get(fact.src, ""), "raw")
        if level == "raw":
            kept.append(fact)
        elif level == "count":
            tally[fact.src][fact.date] += 1
            excluded[fact.src] = "count"
        else:
            excluded[fact.src] = "hidden"
    fact_type = type(facts[0]) if facts else None
    for src, days in tally.items():
        for date, n in days.items():
            kept.append(fact_type(date, None,
                                  "%d %s record%s (details withheld by privacy policy)"
                                  % (n, (labels or {}).get(src, src), "" if n == 1 else "s"), src))
    return kept, excluded
