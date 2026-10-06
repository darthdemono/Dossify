from dossify.sync import ImmichPerson, NextcloudCard, parse_nextcloud_cards, reconcile


def card(uid, name, *, birthday=None, instagram=(), facebook=()):
    return NextcloudCard(
        uid=uid,
        name=name,
        birthday=birthday,
        birthday_present=birthday is not None,
        instagram_usernames=instagram,
        facebook_usernames=facebook,
        body=f"BEGIN:VCARD\nUID:{uid}\nFN:{name}\nEND:VCARD",
    )


def test_sync_collects_all_named_sources_and_reconciles_supported_fields():
    proposed, plan = reconcile(
        {
            "Afridi Anindyo": {
                "facebook_names": ["Afridi Anindyo"],
                "facebook_usernames": ["afridi.anindyo"],
                "nextcloud_uids": [], "immich_person_ids": [],
                "instagram_names": [], "instagram_usernames": ["ily.skii"],
                "nextcloud_names": [], "discord_usernames": [], "snapchat_usernames": [],
            }
        },
        [card("card-1", "Ａfridi Anindyo", birthday="2000-01-02")],
        [ImmichPerson("immich-1", "Afridi Anindyo", None), ImmichPerson("immich-2", "New Person", "1999-02-03")],
    )

    assert set(proposed) == {"Afridi Anindyo", "New Person"}
    assert proposed["Afridi Anindyo"]["nextcloud_uids"] == ["card-1"]
    assert proposed["Afridi Anindyo"]["immich_person_ids"] == ["immich-1"]
    assert proposed["Afridi Anindyo"]["birthday"] == "2000-01-02"
    assert proposed["New Person"]["immich_person_ids"] == ["immich-2"]
    assert proposed["New Person"]["birthday"] == "1999-02-03"
    assert plan["created_people"] == ["New Person"]
    assert plan["immich_updates"] == [{"person": "Afridi Anindyo", "person_id": "immich-1", "birthday": "2000-01-02"}]


def test_sync_reports_conflicting_birthdays_without_remote_writes():
    proposed, plan = reconcile(
        {"Person": {"facebook_names": [], "facebook_usernames": [], "nextcloud_uids": [], "immich_person_ids": [], "instagram_names": [], "instagram_usernames": [], "nextcloud_names": [], "discord_usernames": [], "snapchat_usernames": []}},
        [card("card-1", "Person", birthday="2000-01-02")],
        [ImmichPerson("immich-1", "Person", "2001-01-02")],
    )

    assert "birthday" not in proposed["Person"]
    assert plan["nextcloud_updates"] == []
    assert plan["immich_updates"] == []
    assert plan["conflicts"] == [{"kind": "birthday_conflict", "person": "Person", "birthdays": ["2000-01-02", "2001-01-02"]}]


def test_nextcloud_parser_keeps_exact_name_and_uses_only_social_profile_urls():
    cards = parse_nextcloud_cards(
        "BEGIN:VCARD\r\nUID:one\r\nFN: Mária Ádám\r\n"
        "X-SOCIALPROFILE;TYPE=INSTAGRAM:https://www.instagram.com/maria.adam/\r\n"
        "URL:https://facebook.com/not-a-social-profile\r\nEND:VCARD\r\n"
    )

    assert cards[0].name == " Mária Ádám"
    assert cards[0].instagram_usernames == ("maria.adam",)
    assert cards[0].facebook_usernames == ()


def test_immich_current_people_wrapper_is_accepted():
    from dossify.sync import parse_immich_people

    people = parse_immich_people({"people": [{"id": "one", "name": "Person", "birthDate": "2000-01-02"}]})

    assert people == [ImmichPerson("one", "Person", "2000-01-02")]
