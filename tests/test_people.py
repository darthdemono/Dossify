import json

from dossify.people import journal_identity, load_people, resolve_person


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
