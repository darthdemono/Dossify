"""Identity as reviewable claims, never fuzzy merges.

Every identifier in ``People.json`` becomes a claim: this person holds this
identifier on this provider, optionally within a validity period, with a stated
provenance.  Two people holding the same identifier at overlapping times is a
contradiction to review, not something to resolve silently.

An optional ``identity_claims`` list on a person adds periods and provenance:
``{"provider": "instagram_handle", "identifier": "x", "valid_from": "2024-01-01",
"valid_to": null, "source": "told me", "status": "active"}``.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from dossify.people import Person, normalize_identifier

FIELD_PROVIDER = {
    "instagram_usernames": "instagram_handle", "instagram_names": "instagram_display_name",
    "facebook_names": "facebook_name", "facebook_usernames": "facebook_username",
    "nextcloud_uids": "nextcloud_uid", "nextcloud_names": "nextcloud_name",
    "immich_person_ids": "immich_person_id", "discord_usernames": "discord_username",
    "snapchat_usernames": "snapchat_username",
}


class IdentityClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    person: str
    provider: str
    identifier: str
    valid_from: date | None = None
    valid_to: date | None = None
    source: str = "People.json"
    status: Literal["active", "retired", "disputed"] = "active"


def collect(people: dict[str, Person]) -> list[IdentityClaim]:
    claims = []
    for name, person in people.items():
        for field, provider in FIELD_PROVIDER.items():
            claims += [IdentityClaim(person=name, provider=provider, identifier=v,
                                     source=f"People.json:{field}") for v in getattr(person, field) if v]
        for pair in person.instagram:
            if pair.handle:
                claims.append(IdentityClaim(person=name, provider="instagram_handle",
                                            identifier=pair.handle, source="People.json:instagram"))
            if pair.display:
                claims.append(IdentityClaim(person=name, provider="instagram_display_name",
                                            identifier=pair.display, source="People.json:instagram"))
        for raw in (person.model_extra or {}).get("identity_claims", []):
            claims.append(IdentityClaim.model_validate({**raw, "person": name}))
    return claims


def _overlap(a: IdentityClaim, b: IdentityClaim) -> bool:
    start = max(filter(None, (a.valid_from, b.valid_from)), default=date.min)
    end = min(filter(None, (a.valid_to, b.valid_to)), default=date.max)
    return start <= end


def contradictions(claims: list[IdentityClaim]) -> list[str]:
    """Plain-English findings; empty means nothing to review."""
    found = []
    live = [c for c in claims if c.status != "retired"]
    for c in claims:
        if c.valid_from and c.valid_to and c.valid_to < c.valid_from:
            found.append(f"{c.person}: {c.provider} {c.identifier!r} ends before it begins")
    by_key: dict[tuple[str, str], list[IdentityClaim]] = {}
    for c in live:
        by_key.setdefault((c.provider, normalize_identifier(c.identifier)), []).append(c)
    for (provider, ident), group in sorted(by_key.items()):
        people = sorted({c.person for c in group})
        if len(people) > 1 and any(_overlap(a, b) for i, a in enumerate(group) for b in group[i + 1:]
                                   if a.person != b.person):
            found.append(f"{provider} {ident!r} is claimed by {', '.join(people)} at overlapping times")
    return found


def resolve_at(claims: list[IdentityClaim], provider: str, identifier: str, on: date) -> str | None:
    """The one person holding an identifier on a date, or None when absent or ambiguous."""
    key = normalize_identifier(identifier)
    holders = {c.person for c in claims if c.status == "active" and c.provider == provider
               and normalize_identifier(c.identifier) == key
               and (c.valid_from is None or c.valid_from <= on)
               and (c.valid_to is None or on <= c.valid_to)}
    return next(iter(holders)) if len(holders) == 1 else None
