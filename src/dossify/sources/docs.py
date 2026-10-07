"""Documents created, from DD-MM-YYYY dates in file names under chosen folders.

Options: root (default workspace_root), folders."""

import glob, os, re
from collections import defaultdict
from datetime import datetime

from dossify import journal as J
from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_docs():
    folders = list(_O.get("folders", []))
    base = os.path.expanduser(str(_O.get("root") or J.ARCHIVE))
    seen, byday = set(), defaultdict(set)
    today = datetime.now().strftime("%Y-%m-%d")
    for rel in folders:
        for path in glob.glob(os.path.join(base, rel, "**", "*"), recursive=True):
            if not os.path.isfile(path):
                continue
            name = os.path.basename(path)
            if name.startswith(".") or "/backup/" in path:
                continue
            cands = []
            for mm in re.finditer(r"\b([0-3]\d)-([01]\d)-(20\d\d)\b", name):
                d = "%s-%s-%s" % (mm.group(3), mm.group(2), mm.group(1))
                try:
                    datetime.strptime(d, "%Y-%m-%d")
                except ValueError:
                    continue
                if d <= today:                      # a filed document is never future-dated
                    cands.append(d)
            if not cands:
                continue
            date = cands[-1]
            stem, ext = os.path.splitext(name)
            # Obsidian resolves a Markdown note without its extension; everything
            # else needs the real one to point at the actual file.
            link = stem if ext.lower() == ".md" else name
            if (date, link) in seen:
                continue
            seen.add((date, link))
            byday[date].add(link)
    out = []
    for date, links in byday.items():
        kids = "\n".join("    - [[%s]]" % l for l in sorted(links))
        out.append(Fact(date, None, "Today's documents:\n" + kids, "docs"))
    return out


READERS = {"docs": a_docs}
LABELS = {'docs': 'Documents filed, dated from their file names.'}
