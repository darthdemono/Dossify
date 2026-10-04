"""Private identity data used by Dossify journal adapters.

The public package has no names or account identifiers. A private
``People.json`` owns those mappings and keeps provider identities distinct:
an Instagram display name is paired only with the account that exported it.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class InstagramIdentity(BaseModel):
    """One account and, when known, the display name paired with it."""

    model_config = ConfigDict(extra="forbid")

    handle: str | None = None
    display: str | None = None


class Person(BaseModel):
    """Identifiers for one canonical person, all supplied privately."""

    model_config = ConfigDict(extra="allow")

    instagram: list[InstagramIdentity] = Field(default_factory=list)
    facebook_names: list[str] = Field(default_factory=list)
    facebook_usernames: list[str] = Field(default_factory=list)
    nextcloud_uids: list[str] = Field(default_factory=list)
    immich_person_ids: list[str] = Field(default_factory=list)


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
    normalized = identifier.casefold()
    for name, person in people.items():
        values: list[str]
        if provider == "instagram_handle":
            values = [identity.handle or "" for identity in person.instagram]
        elif provider == "instagram_display_name":
            values = [identity.display or "" for identity in person.instagram]
        elif provider == "facebook_name":
            values = person.facebook_names
        elif provider == "facebook_username":
            values = person.facebook_usernames
        elif provider == "nextcloud_uid":
            values = person.nextcloud_uids
        elif provider == "immich_person_id":
            values = person.immich_person_ids
        else:
            return None
        if normalized in {value.casefold() for value in values if value}:
            matches.append(name)
    return matches[0] if len(matches) == 1 else None


def journal_identity(people: dict[str, Person]) -> dict[str, object]:
    """Build the legacy renderer's indexes from People.json.

    It retains account/display pairing. A person with several accounts cannot
    leak an unrelated handle into another account's thread.
    """
    by_handle: dict[str, str] = {}
    by_display: dict[str, str] = {}
    by_facebook: dict[str, str] = {}
    records: list[dict[str, object]] = []
    for name, person in people.items():
        instagram = [identity.model_dump() for identity in person.instagram]
        records.append({"name": name, "instagram": instagram})
        for identity in person.instagram:
            if identity.handle:
                by_handle.setdefault(identity.handle, name)
            if identity.display:
                by_display.setdefault(identity.display, name)
        for facebook_name in person.facebook_names:
            by_facebook.setdefault(facebook_name, name)
    return {
        "by_ig_handle": by_handle,
        "by_ig_display": by_display,
        "by_fb_name": by_facebook,
        "people": records,
    }
