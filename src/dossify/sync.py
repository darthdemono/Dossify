"""Exact, auditable reconciliation for a private People registry.

This module deliberately has a small ownership boundary.  ``People.json`` is
the registry: named records from Nextcloud and Immich are added to it, never
removed.  The synchronizer then propagates the fields that have an equivalent
on a service: CardDAV Facebook/Instagram profile links and full birthdays, and
Immich full birthdays.  It never uses a similarity score, a transliteration,
or a database write.
"""

from __future__ import annotations

import base64
import copy
import datetime as dt
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dossify.config import DossifyConfig
from dossify.people import normalize_identifier

FULL_BIRTHDAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class NextcloudCard:
    uid: str
    name: str
    birthday: str | None
    birthday_present: bool
    instagram_usernames: tuple[str, ...]
    facebook_usernames: tuple[str, ...]
    body: str


@dataclass(frozen=True)
class ImmichPerson:
    person_id: str
    name: str
    birthday: str | None


def _http(url: str, *, headers: dict[str, str], body: bytes | None = None, method: str = "GET") -> bytes:
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"cannot reach {url}: {exc.reason}") from exc


def _basic_auth(user: str, password: str) -> str:
    encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {encoded}"


def _unfold_vcard(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n ", "").replace("\n\t", "")


def _unescape_vcard(value: str) -> str:
    out: list[str] = []
    escaped = False
    for char in value:
        if escaped:
            out.append({"n": "\n", "N": "\n"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    if escaped:
        out.append("\\")
    return "".join(out)


def _vcard_value(lines: list[str], property_name: str) -> str | None:
    for line in lines:
        head, separator, value = line.partition(":")
        if separator and head.upper().split(";", 1)[0] == property_name:
            return _unescape_vcard(value)
    return None


def _username_from_profile(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.strip())
    host = parsed.netloc.casefold().removeprefix("www.")
    pieces = [piece for piece in parsed.path.split("/") if piece]
    if len(pieces) != 1:
        return None
    if host == "instagram.com":
        return ("instagram_usernames", pieces[0])
    if host in {"facebook.com", "m.facebook.com"}:
        return ("facebook_usernames", pieces[0])
    return None


def _card_profiles(lines: list[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    values: dict[str, list[str]] = {"instagram_usernames": [], "facebook_usernames": []}
    for line in lines:
        head, separator, value = line.partition(":")
        if not separator or head.upper().split(";", 1)[0] != "X-SOCIALPROFILE":
            continue
        identity = _username_from_profile(_unescape_vcard(value))
        if identity and identity[1] not in values[identity[0]]:
            values[identity[0]].append(identity[1])
    return tuple(values["instagram_usernames"]), tuple(values["facebook_usernames"])


def parse_nextcloud_cards(export: str) -> list[NextcloudCard]:
    """Parse a CardDAV export without applying name normalization to its data."""
    cards: list[NextcloudCard] = []
    for match in re.finditer(r"BEGIN:VCARD.*?END:VCARD", _unfold_vcard(export), re.DOTALL | re.IGNORECASE):
        body = match.group(0)
        lines = body.split("\n")
        uid = _vcard_value(lines, "UID")
        name = _vcard_value(lines, "FN")
        if not uid or not name:
            continue
        birthday = _vcard_value(lines, "BDAY")
        instagram, facebook = _card_profiles(lines)
        cards.append(
            NextcloudCard(
                uid=uid,
                name=name,
                birthday=birthday if birthday and FULL_BIRTHDAY.fullmatch(birthday) else None,
                birthday_present=birthday is not None,
                instagram_usernames=instagram,
                facebook_usernames=facebook,
                body=body,
            )
        )
    return cards


def parse_immich_people(payload: object) -> list[ImmichPerson]:
    """Accept current Immich list responses while keeping their IDs opaque."""
    rows = payload
    if isinstance(payload, dict):
        rows = payload.get("people", payload.get("data", payload))
    if not isinstance(rows, list):
        raise TypeError("Immich /api/people response must contain a people or data list")
    people: list[ImmichPerson] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        person_id = row.get("id") or row.get("personGroupId")
        name = row.get("name")
        birthday = row.get("birthDate")
        if isinstance(person_id, str) and isinstance(name, str) and name:
            people.append(
                ImmichPerson(
                    person_id=person_id,
                    name=name,
                    birthday=birthday if isinstance(birthday, str) and FULL_BIRTHDAY.fullmatch(birthday) else None,
                )
            )
    return people


def _add_unique(values: list[str], additions: list[str]) -> list[str]:
    output = list(values)
    known = {normalize_identifier(value) for value in output if value}
    for value in additions:
        if value and normalize_identifier(value) not in known:
            output.append(value)
            known.add(normalize_identifier(value))
    return output


def _empty_person() -> dict[str, object]:
    return {
        "facebook_names": [], "facebook_usernames": [], "nextcloud_uids": [],
        "immich_person_ids": [], "instagram_names": [], "instagram_usernames": [],
        "nextcloud_names": [], "discord_usernames": [], "snapchat_usernames": [],
    }


def _by_normalized_name(names: list[str]) -> tuple[dict[str, str], dict[str, list[str]]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for name in names:
        grouped[normalize_identifier(name)].append(name)
    one = {key: values[0] for key, values in grouped.items() if len(values) == 1}
    return one, {key: values for key, values in grouped.items() if len(values) > 1}


def _append_change(changes: dict[str, dict[str, list[str]]], name: str, field: str, values: list[str]) -> None:
    if values:
        changes.setdefault(name, {}).setdefault(field, []).extend(values)


def reconcile(people: dict[str, object], cards: list[NextcloudCard], immich_people: list[ImmichPerson]) -> tuple[dict[str, object], dict[str, object]]:
    """Return a proposed registry and a complete no-write reconciliation plan."""
    proposed = copy.deepcopy(people)
    if not all(isinstance(name, str) and isinstance(person, dict) for name, person in proposed.items()):
        raise ValueError("People.json must be an object of canonical-name objects")
    canonical, collisions = _by_normalized_name(list(proposed))
    plan: dict[str, object] = {
        "format_version": "1.0", "created_people": [], "people_updates": {},
        "nextcloud_updates": [], "immich_updates": [], "conflicts": [],
        "source_counts": {"nextcloud_cards": len(cards), "immich_named_people": len(immich_people)},
    }
    if collisions:
        plan["conflicts"].extend(
            {"kind": "canonical_name_collision", "names": values} for values in collisions.values()
        )

    card_groups: dict[str, list[NextcloudCard]] = defaultdict(list)
    immich_groups: dict[str, list[ImmichPerson]] = defaultdict(list)
    for card in cards:
        card_groups[normalize_identifier(card.name)].append(card)
    for person in immich_people:
        immich_groups[normalize_identifier(person.name)].append(person)

    # The registry must include every named source record.  A pre-existing
    # canonical spelling wins; otherwise first exact source spelling is used.
    for key in sorted(set(card_groups) | set(immich_groups)):
        if key in collisions:
            plan["conflicts"].append({"kind": "ambiguous_canonical_name", "normalized_name": key})
            continue
        if key not in canonical:
            source_name = (card_groups.get(key) or immich_groups[key])[0].name
            proposed[source_name] = _empty_person()
            canonical[key] = source_name
            plan["created_people"].append(source_name)

    changes: dict[str, dict[str, list[str]]] = {}
    for key, name in canonical.items():
        person = proposed[name]
        assert isinstance(person, dict)
        group_cards = card_groups.get(key, [])
        group_immich = immich_groups.get(key, [])
        additions = {
            "nextcloud_uids": [card.uid for card in group_cards],
            "nextcloud_names": [card.name for card in group_cards],
            "immich_person_ids": [record.person_id for record in group_immich],
            "instagram_usernames": [username for card in group_cards for username in card.instagram_usernames],
            "facebook_usernames": [username for card in group_cards for username in card.facebook_usernames],
        }
        for field, values in additions.items():
            existing = person.get(field, [])
            if not isinstance(existing, list) or not all(isinstance(value, str) for value in existing):
                raise ValueError(f"People.json {name!r}.{field} must be a list of strings")
            updated = _add_unique(existing, values)
            inserted = updated[len(existing):]
            if inserted:
                person[field] = updated
                _append_change(changes, name, field, inserted)

        birthdays = {value for value in [person.get("birthday")] if isinstance(value, str) and FULL_BIRTHDAY.fullmatch(value)}
        birthdays.update(card.birthday for card in group_cards if card.birthday)
        birthdays.update(record.birthday for record in group_immich if record.birthday)
        if len(birthdays) > 1:
            plan["conflicts"].append({"kind": "birthday_conflict", "person": name, "birthdays": sorted(birthdays)})
            continue
        birthday = next(iter(birthdays), None)
        if birthday and person.get("birthday") != birthday:
            person["birthday"] = birthday
            _append_change(changes, name, "birthday", [birthday])

        if not birthday:
            continue
        instagram = person.get("instagram_usernames", [])
        facebook = person.get("facebook_usernames", [])
        assert isinstance(instagram, list) and isinstance(facebook, list)
        for card in group_cards:
            # A partial CardDAV date (for example ``--05-17``) is meaningful
            # data.  Do not append a second BDAY line just because it cannot
            # be safely reconciled with a full date.
            needs_birthday = card.birthday is None and not card.birthday_present
            profile_additions = {
                "instagram_usernames": _add_unique(list(card.instagram_usernames), instagram)[len(card.instagram_usernames):],
                "facebook_usernames": _add_unique(list(card.facebook_usernames), facebook)[len(card.facebook_usernames):],
            }
            if needs_birthday or any(profile_additions.values()):
                plan["nextcloud_updates"].append({
                    "person": name, "uid": card.uid,
                    "birthday": birthday if needs_birthday else None,
                    **profile_additions,
                })
        for record in group_immich:
            if record.birthday is None:
                plan["immich_updates"].append({"person": name, "person_id": record.person_id, "birthday": birthday})
    plan["people_updates"] = changes
    return proposed, plan


def _card_with_updates(card: NextcloudCard, update: dict[str, object]) -> str:
    lines = card.body.replace("\r\n", "\n").split("\n")
    insertion = next((index for index, line in enumerate(lines) if line.upper() == "END:VCARD"), len(lines))
    additions: list[str] = []
    birthday = update.get("birthday")
    if isinstance(birthday, str):
        additions.append(f"BDAY:{birthday}")
    for field, provider in (("instagram_usernames", "INSTAGRAM"), ("facebook_usernames", "FACEBOOK")):
        usernames = update.get(field, [])
        assert isinstance(usernames, list)
        for username in usernames:
            if isinstance(username, str):
                base = "instagram.com" if provider == "INSTAGRAM" else "facebook.com"
                additions.append(f"X-SOCIALPROFILE;TYPE={provider}:https://www.{base}/{username}")
    lines = [line for line in lines if not line.startswith("REV:")]
    insertion = next((index for index, line in enumerate(lines) if line.upper() == "END:VCARD"), len(lines))
    lines[insertion:insertion] = additions + [f"REV:{dt.datetime.now(dt.UTC).strftime('%Y%m%dT%H%M%SZ')}"]
    return "\r\n".join(lines).rstrip("\r\n") + "\r\n"


def _snapshot(
    directory: Path, people_path: Path, people_bytes: bytes, nextcloud: bytes, immich: bytes
) -> tuple[Path, dict[str, str]]:
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H%M%S")
    target = directory / f"people-sync-{stamp}"
    target.mkdir(parents=True, exist_ok=False)
    (target / "People.json.before.json").write_bytes(people_bytes)
    (target / "Nextcloud.before.vcf").write_bytes(nextcloud)
    (target / "Immich.before.json").write_bytes(immich)
    (target / "README.txt").write_text(
        f"Private Dossify People sync snapshot before writes. Source map: {people_path.name}\n",
        encoding="utf-8",
    )
    return target, {
        "People.json.before.json": hashlib.sha256(people_bytes).hexdigest(),
        "Nextcloud.before.vcf": hashlib.sha256(nextcloud).hexdigest(),
        "Immich.before.json": hashlib.sha256(immich).hexdigest(),
    }


def _atomic_json_write(path: Path, payload: dict[str, object]) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)


def run(config: DossifyConfig, *, apply: bool, snapshot_dir: Path | None, report: Path | None) -> dict[str, object]:
    """Fetch, plan, optionally snapshot/apply, and return a private sync report."""
    if not config.people_file:
        raise ValueError("sync needs people_file in dossify.toml")
    settings = config.sync
    required = {
        "sync.nextcloud_url": settings.nextcloud_url,
        "sync.nextcloud_user": settings.nextcloud_user,
        "sync.nextcloud_password_env": settings.nextcloud_password_env,
        "sync.immich_url": settings.immich_url,
        "sync.immich_api_key_env": settings.immich_api_key_env,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError(f"sync needs {', '.join(missing)}")
    nextcloud_password = os.environ.get(settings.nextcloud_password_env or "")
    immich_key = os.environ.get(settings.immich_api_key_env or "")
    if not nextcloud_password or not immich_key:
        raise ValueError("sync credential environment variables are missing")

    people_bytes = config.people_file.read_bytes()
    raw_people = json.loads(people_bytes)
    if not isinstance(raw_people, dict):
        raise TypeError("People.json must be an object keyed by canonical name")
    nextcloud_url = (settings.nextcloud_url or "").rstrip("/")
    nextcloud_dump = _http(
        f"{nextcloud_url}?export",
        headers={"Authorization": _basic_auth(settings.nextcloud_user or "", nextcloud_password)},
    )
    immich_url = (settings.immich_url or "").rstrip("/")
    immich_dump = _http(f"{immich_url}/api/people", headers={"x-api-key": immich_key})
    cards = parse_nextcloud_cards(nextcloud_dump.decode("utf-8"))
    immich_people = parse_immich_people(json.loads(immich_dump))
    proposed, plan = reconcile(raw_people, cards, immich_people)
    target_snapshot = snapshot_dir or settings.snapshot_dir
    snapshot_path: Path | None = None
    if target_snapshot:
        snapshot_path, hashes = _snapshot(
            target_snapshot, config.people_file, people_bytes, nextcloud_dump, immich_dump
        )
        plan["snapshot"] = {"path": str(snapshot_path), "sha256": hashes}
    if apply and not target_snapshot:
        raise ValueError("--apply needs [sync].snapshot_dir or --snapshot-dir")
    if apply:
        _atomic_json_write(config.people_file, proposed)
        card_by_uid = {card.uid: card for card in cards}
        nextcloud_updates = plan["nextcloud_updates"]
        assert isinstance(nextcloud_updates, list)
        for update in nextcloud_updates:
            assert isinstance(update, dict)
            uid = update["uid"]
            assert isinstance(uid, str)
            _http(
                f"{nextcloud_url}/{uid}.vcf",
                method="PUT",
                body=_card_with_updates(card_by_uid[uid], update).encode(),
                headers={
                    "Authorization": _basic_auth(settings.nextcloud_user or "", nextcloud_password),
                    "Content-Type": "text/vcard; charset=utf-8",
                },
            )
        immich_updates = plan["immich_updates"]
        assert isinstance(immich_updates, list)
        for update in immich_updates:
            assert isinstance(update, dict)
            person_id = update["person_id"]
            birthday = update["birthday"]
            assert isinstance(person_id, str) and isinstance(birthday, str)
            _http(
                f"{immich_url}/api/people/{person_id}", method="PUT",
                body=json.dumps({"birthDate": birthday}).encode(),
                headers={"x-api-key": immich_key, "Content-Type": "application/json"},
            )
        plan["applied"] = True
    else:
        plan["applied"] = False
    rendered = json.dumps(plan, indent=2, ensure_ascii=False) + "\n"
    if report:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return plan
