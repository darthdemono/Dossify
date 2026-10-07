"""Anime list activity from the MyAnimeList API.

Options: user, api_key_env or api_key_command (a client id)."""

import json

from dossify import journal as J
from dossify.journal import Fact, iso_local, plural

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


MAL_VERB = {"completed": "finished", "watching": "was watching", "on_hold": "put on hold",
            "dropped": "dropped", "plan_to_watch": "added to the plan-to-watch"}


def a_mal():
    """One date per title, the last time the entry was touched, exactly the
    limitation Simkl's export has."""
    cid = J.secret(_O)
    username = str(_O.get("user") or "")
    if not cid or not username:
        return []
    import urllib.request
    out, url = [], (f"https://api.myanimelist.net/v2/users/{username}/animelist"
                    "?fields=list_status&limit=1000&nsfw=true")
    while url:
        req = urllib.request.Request(url, headers={"X-MAL-CLIENT-ID": cid})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = json.load(r)
        except Exception as ex:
            print("  mal: %s" % ex)
            break
        for row in blob.get("data", []):
            st = row.get("list_status") or {}
            title = (row.get("node") or {}).get("title") or ""
            date, time = iso_local(st.get("updated_at"))
            if not date or not title:
                continue
            verb = MAL_VERB.get(st.get("status"), "updated")
            eps = st.get("num_episodes_watched")
            score = st.get("score")
            bits = []
            if eps:
                bits.append(plural(eps, "episode"))
            if score:
                bits.append("scored %s" % score)
            out.append(Fact(date, time, "MyAnimeList: %s %s%s" % (
                verb, title, " (%s)" % ", ".join(bits) if bits else ""), "mal"))
        url = (blob.get("paging") or {}).get("next")
    return out


READERS = {"mal": a_mal}
LABELS = {'mal': 'Anime list activity fetched from MyAnimeList.'}
