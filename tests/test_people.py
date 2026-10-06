import json

from dossify import journal
from dossify.people import (
    journal_identity,
    load_people,
    normalize_identifier,
    resolve_person,
)


def test_people_preserve_instagram_display_handle_pairing(tmp_path):
    path = tmp_path / "People.json"
    path.write_text(
        json.dumps(
            {
                "Person One": {
                    "instagram": [
                        {"display": "Current display", "handle": "current_account"},
                        {"handle": "older_account"},
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    people = load_people(path)
    identity = journal_identity(people)

    assert resolve_person(people, "instagram_display_name", "CURRENT DISPLAY") == "Person One"
    assert identity["by_ig_display"]["Current display"] == "Person One"
    assert identity["people"][0]["instagram"] == [
        {"handle": "current_account", "display": "Current display"},
        {"handle": "older_account", "display": None},
    ]


def test_people_resolve_all_provider_identifiers_exactly_after_presentation_normalization(tmp_path):
    path = tmp_path / "People.json"
    path.write_text(
        json.dumps(
            {
                "Mária Ádám": {
                    "instagram_names": ["Mária Ádám"],
                    "instagram_usernames": ["maria.adam"],
                    "facebook_names": ["Mária Ádám"],
                    "facebook_usernames": ["maria.adam"],
                    "nextcloud_uids": ["carddav-123"],
                    "nextcloud_names": ["Mária Ádám"],
                    "immich_person_ids": ["immich-123"],
                    "discord_usernames": ["maria.adam"],
                    "snapchat_usernames": ["maria_adam"],
                }
            }
        ),
        encoding="utf-8",
    )

    people = load_people(path)
    assert normalize_identifier("𝐌áｒｉａ Áｄáｍ") == normalize_identifier("Mária Ádám")
    for provider, identifier in (
        ("instagram_name", "𝐌áｒｉａ Áｄáｍ"),
        ("instagram_username", "ＭＡＲＩＡ.ＡＤＡＭ"),
        ("facebook_name", "ＭÁＲＩＡ ÁＤÁＭ"),
        ("facebook_username", "ＭＡＲＩＡ.ＡＤＡＭ"),
        ("nextcloud_uid", "CARDdav-123"),
        ("nextcloud_name", "ＭáＲｉＡ Áｄáｍ"),
        ("immich_person_id", "IMMICH-123"),
        ("discord_username", "ＭＡＲＩＡ.ＡＤＡＭ"),
        ("snapchat_username", "ＭＡＲＩＡ＿ＡＤＡＭ"),
    ):
        assert resolve_person(people, provider, identifier) == "Mária Ádám"
    assert resolve_person(people, "facebook_name", "Maria Adam") is None
    assert resolve_person(people, "facebook_name", "Mária   Ádám") is None


def test_people_leave_colliding_identifiers_unresolved(tmp_path):
    path = tmp_path / "People.json"
    path.write_text(
        json.dumps(
            {
                "Person One": {"facebook_names": ["Same Name"]},
                "Person Two": {"facebook_names": ["Ｓａｍｅ Ｎａｍｅ"]},
            }
        ),
        encoding="utf-8",
    )

    people = load_people(path)
    identity = journal_identity(people)
    assert resolve_person(people, "facebook_name", "Same Name") is None
    assert "same name" not in identity["by_fb_name_normalized"]
    previous_identity = journal._IDENTITY
    try:
        journal._IDENTITY = identity
        assert journal.identity_match("by_fb_name", "Same Name") is None
    finally:
        journal._IDENTITY = previous_identity
