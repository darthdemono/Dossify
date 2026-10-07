"""Download completions from qBittorrent resume files.

Options: dir (the BT_backup folder)."""

import glob, os
from collections import defaultdict

from dossify.journal import epoch_local, nest

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def _bdecode(data, i=0):
    if data[i:i + 1] == b"i":
        j = data.index(b"e", i)
        return int(data[i + 1:j]), j + 1
    if data[i:i + 1] == b"l":
        out, i = [], i + 1
        while data[i:i + 1] != b"e":
            v, i = _bdecode(data, i)
            out.append(v)
        return out, i + 1
    if data[i:i + 1] == b"d":
        out, i = {}, i + 1
        while data[i:i + 1] != b"e":
            k, i = _bdecode(data, i)
            v, i = _bdecode(data, i)
            out[k] = v
        return out, i + 1
    j = data.index(b":", i)
    n = int(data[i:j])
    return data[j + 1:j + 1 + n], j + 1 + n


def a_torrents():
    """When a download finished, out of qBittorrent's own resume files."""
    d = os.path.expanduser(str(_O.get("dir") or ""))   # qBittorrent BT_backup folder
    byday = defaultdict(list)
    for p in sorted(glob.glob(os.path.join(d, "*.fastresume"))):
        try:
            blob, _ = _bdecode(open(p, "rb").read())
        except Exception:
            continue
        done = blob.get(b"completed_time") or blob.get(b"completed_on") or 0
        name = blob.get(b"name") or b""
        if not name:
            tor = p[:-len(".fastresume")] + ".torrent"
            try:
                meta, _ = _bdecode(open(tor, "rb").read())
                name = (meta.get(b"info") or {}).get(b"name") or b""
            except Exception:
                pass
        if not done or not name:
            continue
        date, time = epoch_local(done)
        if date:
            byday[date].append((time, name.decode("utf-8", "replace")[:90]))
    out = []
    for date, rows in byday.items():
        rows.sort()
        f = nest(date, "Downloads finished:",
                 ["%s · %s" % (t, n) for t, n in rows[:12]], "torrents")
        if f:
            out.append(f)
    return out


READERS = {"torrents": a_torrents}
LABELS = {'torrents': 'Downloads read from torrent client resume files.'}
