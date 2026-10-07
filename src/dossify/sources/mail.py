"""Mail sent, from a local Thunderbird profile.

Options: profiles (default ~/.thunderbird)."""

import glob, os, re

from dossify import journal as J
from dossify.journal import Fact, UTC

TIER = "core"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_mail():
    """Mail sent. What arrived is somebody else's action, and it is noise.

    Thunderbird stores these as maildir on this machine, one `.eml` per
    message under `cur/`, but the same folder is an mbox file in older
    profiles, so both shapes are handled.
    """
    out, boxes = [], []
    roots = []
    for profile in J.listify(_O.get("profiles") or "~/.thunderbird"):    # Thunderbird profile folders
        roots += glob.glob(os.path.join(profile, "*", "ImapMail", "*", "*.sbd")) + \
                 glob.glob(os.path.join(profile, "*", "Mail", "*")) + \
                 glob.glob(os.path.join(profile, "*", "ImapMail", "*"))
    for root in roots:
        for name in ("Sent Mail", "Sent Items", "Sent", "Sent Messages"):
            p = os.path.join(root, name)
            if os.path.isdir(os.path.join(p, "cur")):
                boxes += sorted(glob.glob(os.path.join(p, "cur", "*")))
            elif os.path.isfile(p):
                boxes.append(p)
    for box in sorted(set(boxes)):
        try:
            raw = open(box, "rb").read()
        except OSError:
            continue
        chunks = re.split(rb"\r?\n(?=From )", raw) if raw.startswith(b"From ") else [raw]
        for chunk in chunks:
            head = re.split(rb"\r?\n\r?\n", chunk, maxsplit=1)[0].decode("utf-8", "replace")
            head = re.sub(r"\r?\n[ \t]+", " ", head)
            d = re.search(r"^Date:\s*(.+)$", head, re.M)
            if not d:
                continue
            sm = re.search(r"^Subject:\s*(.+)$", head, re.M)
            t = re.search(r"^To:\s*(.+)$", head, re.M)
            try:
                from email.utils import parsedate_to_datetime
                dt = parsedate_to_datetime(d.group(1).strip())
            except Exception:
                continue
            if dt is None:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            loc = dt.astimezone(J.TZ_DEFAULT)
            subj = _mime_header(sm.group(1).strip()) if sm else "(no subject)"
            to = _mime_header(t.group(1).strip()) if t else ""
            to = re.sub(r"\s*<[^>]*>", "", to).strip(' "')
            to = to.split(",")[0].strip() or "someone"
            out.append(Fact(loc.strftime("%Y-%m-%d"), loc.strftime("%H:%M"),
                            "Emailed %s: %s" % (to, subj[:80]), "mail"))
    return list(dict.fromkeys(out))


def _mime_header(v):
    try:
        from email.header import decode_header, make_header
        return str(make_header(decode_header(v)))
    except Exception:
        return v


READERS = {"mail": a_mail}
LABELS = {'mail': 'Mail sent, read from a local mail client.'}
