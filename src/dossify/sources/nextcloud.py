"""Activity counts from a Nextcloud database.

Options: psql (a command prefix that opens psql on the database)."""

import subprocess
from collections import defaultdict

from dossify import journal as J
from dossify.journal import Fact, plural

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


NC_SUBJECTS = {
    "created_self": ("file uploaded", "files uploaded"),
    "deleted_self": ("file deleted", "files deleted"),
    "changed_self": ("file changed", "files changed"),
    "shared_link_self": ("link shared", "links shared"),
    "card_add_self": ("contact added", "contacts added"),
    "card_update_self": ("contact edited", "contacts edited"),
    "card_delete_self": ("contact deleted", "contacts deleted"),
    "calendar_add_self": ("calendar made", "calendars made"),
    "object_add_event_self": ("event added", "events added"),
    "object_update_event_self": ("event edited", "events edited"),
    "object_delete_event_self": ("event deleted", "events deleted"),
}


def a_ncloud():
    """What was done in Nextcloud. Counts, because a bulk import is one act."""
    psql = list(_O.get("psql") or [])
    if not psql:
        return []
    zone = str(J.TZ_DEFAULT).replace("'", "''")
    try:
        r = subprocess.run(
            psql + ["-tAF", "\x1f", "-c",
             "select to_char(to_timestamp(timestamp) at time zone '" + zone + "',"
             "'YYYY-MM-DD'), subject, count(*) from oc_activity "
             "where app <> 'files_sharing' and subject <> 'app_token_created' "
             "group by 1, 2"],
            capture_output=True, text=True, timeout=60)
    except Exception:
        return []
    if r.returncode != 0:
        return []
    byday = defaultdict(list)
    for line in r.stdout.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 3:
            continue
        date, subject, n = parts[0], parts[1], int(parts[2])
        words = NC_SUBJECTS.get(subject)
        if not words:
            continue
        byday[date].append((n, plural(n, words[0], words[1])))
    out = []
    for date, items in byday.items():
        items.sort(key=lambda x: -x[0])
        out.append(Fact(date, None, "Nextcloud: " + ", ".join(t for _n, t in items), "ncloud"))
    return out


READERS = {"ncloud": a_ncloud}
LABELS = {'ncloud': 'Activity read from a Nextcloud database.'}
