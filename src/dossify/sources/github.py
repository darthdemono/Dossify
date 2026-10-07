"""Account activity from the GitHub API (pushes are skipped; git reads those).

Options: user, api_key_env or api_key_command."""

import json

from dossify import journal as J
from dossify.journal import Fact, iso_local

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


GH_EVENTS = {
    "WatchEvent": "starred", "ForkEvent": "forked", "CreateEvent": "created",
    "IssuesEvent": "opened an issue on", "PullRequestEvent": "opened a pull request on",
    "ReleaseEvent": "released", "PublicEvent": "made public",
    "IssueCommentEvent": "commented on",
}


def a_github():
    """What local git cannot see. Pushes are deliberately skipped, because the
    git adapter already reads the commits out of the working copies."""
    key = J.secret(_O)
    username = str(_O.get("user") or "")
    if not key or not username:
        return []
    import urllib.request
    out = []
    for page in range(1, 4):
        req = urllib.request.Request(
            f"https://api.github.com/users/{username}/events?per_page=100&page={page}",
            headers={"Authorization": "Bearer " + key,
                     "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = json.load(r)
        except Exception as ex:
            print("  github: %s" % ex)
            break
        if not rows:
            break
        for e in rows:
            verb = GH_EVENTS.get(e.get("type"))
            if not verb:
                continue
            date, time = iso_local(e.get("created_at"))
            repo = (e.get("repo") or {}).get("name", "")
            if date and repo:
                out.append(Fact(date, time, "GitHub: %s %s" % (verb, repo), "github"))
    return list(dict.fromkeys(out))


READERS = {"github": a_github}
LABELS = {'github': 'Account activity fetched from GitHub.'}
