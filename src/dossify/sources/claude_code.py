"""AI coding-assistant session transcripts on this machine.

Options: projects_dir (default ~/.claude/projects)."""

import glob, json, os
from datetime import datetime

from dossify.journal import Fact

TIER = "optional"

_O: dict = {}   # this provider's options, set by the registry before each read


def a_claude():
    out = []
    for d in sorted(glob.glob(os.path.join(os.path.expanduser(str(_O.get("projects_dir") or "~/.claude/projects")), "*"))):
        for f in glob.glob(os.path.join(d, "*.jsonl")):
            first, last, n, proj = None, None, 0, None
            try:
                for line in open(f, encoding="utf-8", errors="replace"):
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    proj = proj or rec.get("cwd")
                    ts = rec.get("timestamp")
                    if not ts:
                        continue
                    n += 1
                    first = first or ts
                    last = ts
            except Exception:
                continue
            if not first:
                continue
            label = os.path.basename(proj.rstrip("/")) if proj else os.path.basename(d)
            try:
                dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
            except Exception:
                continue
            out.append(Fact(dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"),
                            "Claude session: %s (%d messages)" % (label, n), "claude"))
    return out


READERS = {"claude": a_claude}
LABELS = {'claude': 'AI coding sessions read from local transcripts.'}
