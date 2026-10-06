"""Private identity data used by Dossify journal adapters.

The public package has no names or account identifiers. A private
``People.json`` owns those mappings. New Instagram display names and usernames
are independent arrays like Facebook; legacy paired records remain readable.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class InstagramIdentity(BaseModel):
    """One account and, when known, the display name paired with it."""

    model_config = ConfigDict(extra="forbid")

    handle: str | None = None
    display: str | None = None


def normalize_identifier(value: str) -> str:
    """Compare identifiers exactly after Unicode presentation normalization.

    NFKC treats visual letter variants, such as mathematical bold or full-width
    Latin text, as the same letters.  It deliberately does not remove accents,
    reorder words, transliterate, trim, or otherwise perform fuzzy matching.
    """
    return unicodedata.normalize("NFKC", value).casefold()


class Person(BaseModel):
    """Identifiers for one canonical person, all supplied privately."""

    model_config = ConfigDict(extra="allow")

    # ``instagram`` is retained for private maps created before 1.0.1.  New
    # maps should use the two explicit arrays, matching Facebook's shape.
    instagram: list[InstagramIdentity] = Field(default_factory=list)
    instagram_names: list[str] = Field(default_factory=list)
    instagram_usernames: list[str] = Field(default_factory=list)
    facebook_names: list[str] = Field(default_factory=list)
    facebook_usernames: list[str] = Field(default_factory=list)
    nextcloud_uids: list[str] = Field(default_factory=list)
    nextcloud_names: list[str] = Field(default_factory=list)
    immich_person_ids: list[str] = Field(default_factory=list)
    birthday: str | None = None
    discord_usernames: list[str] = Field(default_factory=list)
    snapchat_usernames: list[str] = Field(default_factory=list)


def load_people(path: Path) -> dict[str, Person]:
    """Load a private People.json file without ever writing it back."""
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("People.json must be an object keyed by canonical name")
    return {name: Person.model_validate(data) for name, data in raw.items()}


def resolve_person(people: dict[str, Person], provider: str, identifier: str) -> str | None:
    """Resolve one provider identifier only when it names exactly one person."""
    matches: list[str] = []
    normalized = normalize_identifier(identifier)
    for name, person in people.items():
        values: list[str]
        if provider in {"instagram_handle", "instagram_username"}:
            values = person.instagram_usernames + [identity.handle or "" for identity in person.instagram]
        elif provider in {"instagram_display_name", "instagram_name"}:
            values = person.instagram_names + [identity.display or "" for identity in person.instagram]
        elif provider == "facebook_name":
            values = person.facebook_names
        elif provider == "facebook_username":
            values = person.facebook_usernames
        elif provider == "nextcloud_uid":
            values = person.nextcloud_uids
        elif provider == "nextcloud_name":
            values = person.nextcloud_names
        elif provider == "immich_person_id":
            values = person.immich_person_ids
        elif provider == "discord_username":
            values = person.discord_usernames
        elif provider == "snapchat_username":
            values = person.snapchat_usernames
        else:
            return None
        if normalized in {normalize_identifier(value) for value in values if value}:
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def journal_identity(people: dict[str, Person]) -> dict[str, object]:
    """Build the legacy renderer's indexes from People.json.

    Legacy paired Instagram records retain their account/display relationship;
    the current independent arrays resolve only the exact value supplied by an
    export.
    """
    entries: dict[str, list[tuple[str, str]]] = {
        "by_ig_handle": [],
        "by_ig_display": [],
        "by_fb_name": [],
        "by_fb_username": [],
        "by_nextcloud_uid": [],
        "by_nextcloud_name": [],
        "by_immich_person_id": [],
        "by_discord_username": [],
        "by_snapchat_username": [],
    }
    records: list[dict[str, object]] = []
    for name, person in people.items():
        instagram = [identity.model_dump() for identity in person.instagram]
        records.append(
            {
                "name": name,
                "instagram": instagram,
                "instagram_names": person.instagram_names,
                "instagram_usernames": person.instagram_usernames,
            }
        )
        for identity in person.instagram:
            if identity.handle:
                entries["by_ig_handle"].append((identity.handle, name))
            if identity.display:
                entries["by_ig_display"].append((identity.display, name))
        entries["by_ig_handle"].extend((value, name) for value in person.instagram_usernames)
        entries["by_ig_display"].extend((value, name) for value in person.instagram_names)
        for facebook_name in person.facebook_names:
            entries["by_fb_name"].append((facebook_name, name))
        entries["by_fb_username"].extend((value, name) for value in person.facebook_usernames)
        entries["by_nextcloud_uid"].extend((value, name) for value in person.nextcloud_uids)
        entries["by_nextcloud_name"].extend((value, name) for value in person.nextcloud_names)
        entries["by_immich_person_id"].extend((value, name) for value in person.immich_person_ids)
        entries["by_discord_username"].extend((value, name) for value in person.discord_usernames)
        entries["by_snapchat_username"].extend((value, name) for value in person.snapchat_usernames)

    result: dict[str, object] = {"people": records}
    for key, values in entries.items():
        raw: dict[str, set[str]] = {}
        normalized: dict[str, set[str]] = {}
        for value, name in values:
            if not value:
                continue
            raw.setdefault(value, set()).add(name)
            normalized.setdefault(normalize_identifier(value), set()).add(name)
        # An identifier claimed by several people is intentionally omitted:
        # downstream rendering must leave it unresolved instead of guessing.
        result[key] = {value: next(iter(names)) for value, names in raw.items() if len(names) == 1}
        result[f"{key}_normalized"] = {
            value: next(iter(names)) for value, names in normalized.items() if len(names) == 1
        }
    return result
