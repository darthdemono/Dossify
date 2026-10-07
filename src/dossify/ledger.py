"""Private run ledger: an audit trail for every reviewed or applied run.

The ledger is not a database of the owner's life.  Each run gets a directory
holding a manifest (what ran, over what coverage, which files changed, with
hashes) plus the proposed and previous text of every month file, so a run can
be reviewed, applied exactly as reviewed, and undone.  Everything here can be
deleted; Markdown stays canonical.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

GAP_DAYS = 14   # a silence this long inside a source's own range is reported


def sha(text: str | None) -> str | None:
    return None if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


@dataclass
class Outcome:
    """What one source did in one run.  Absence of facts is never silent."""

    name: str
    status: str            # ok | no_events | failed | not_selected | excluded_by_policy | replaced_by_typed
    facts: int = 0
    active_days: int = 0
    first_date: str | None = None
    last_date: str | None = None
    gaps: list[list[str | int]] = field(default_factory=list)
    policy: str | None = None
    error: str | None = None
    note: str | None = None


def silent_gaps(dates: list[str]) -> list[list[str | int]]:
    """Runs of at least GAP_DAYS empty days between two days a source did report."""
    days = sorted({date.fromisoformat(d) for d in dates})
    gaps = []
    for a, b in zip(days, days[1:], strict=False):
        if (b - a).days - 1 >= GAP_DAYS:
            gaps.append([(a + timedelta(days=1)).isoformat(), (b - timedelta(days=1)).isoformat(),
                         (b - a).days - 1])
    return sorted(gaps, key=lambda g: -g[2])[:5]


def summarise(name: str, facts) -> Outcome:
    if not facts:
        return Outcome(name, "no_events")
    dates = [f.date for f in facts]
    return Outcome(name, "ok", len(facts), len(set(dates)), min(dates), max(dates), silent_gaps(dates))


def evidence_digest(facts) -> str:
    """Hash of the rendered evidence, so a journal line can be traced to a run."""
    body = "\n".join(sorted("%s|%s|%s|%s" % (f.date, f.time or "", f.src, f.text) for f in facts))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


class Run:
    """One ledger directory and its manifest."""

    def __init__(self, root: Path, run_id: str):
        self.dir = root / run_id
        self.manifest: dict = {"run_id": run_id}

    @classmethod
    def load(cls, root: Path, run_id: str) -> Run:
        run = cls(root, run_id)
        try:
            run.manifest = json.loads((run.dir / "manifest.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise SystemExit(f"no run {run_id} in {root}") from None
        return run

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "manifest.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")

    def stash(self, kind: str, ym: str, text: str | None) -> None:
        if text is None:
            return
        target = self.dir / kind / f"{ym}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def fetch(self, kind: str, ym: str) -> str | None:
        return read_text(self.dir / kind / f"{ym}.md")


def runs(root: Path) -> list[Run]:
    if not root.is_dir():
        return []
    return [Run.load(root, p.name) for p in sorted(root.iterdir()) if (p / "manifest.json").exists()]


def latest(root: Path) -> Run | None:
    found = runs(root)
    return found[-1] if found else None


def unified_diff(path: str, before: str | None, after: str | None) -> str:
    return "".join(difflib.unified_diff(
        (before or "").splitlines(True), (after or "").splitlines(True),
        fromfile=path if before is not None else "/dev/null",
        tofile=path if after is not None else "/dev/null"))


def status_lines(manifest: dict) -> list[str]:
    """Human coverage report for one manifest."""
    out = [f"run {manifest['run_id']}  mode={manifest.get('mode')}  profile={manifest.get('profile')}  "
           f"privacy={manifest.get('privacy_preset') or 'unrestricted'}", ""]
    for o in manifest.get("adapters", []):
        if o["status"] == "ok":
            line = "%s: ok, %d records on %d days, %s to %s" % (
                o["name"], o["facts"], o["active_days"], o["first_date"], o["last_date"])
        else:
            line = "%s: %s" % (o["name"], o["status"].replace("_", " "))
        if o.get("policy"):
            line += f" (policy: {o['policy']})"
        if o.get("error"):
            line += f" [{o['error']}]"
        if o.get("note"):
            line += f" ({o['note']})"
        out.append(line)
        for start, end, n in o.get("gaps", []):
            out.append(f"    silent {start} to {end} ({n} days)")
    tasks = manifest.get("review_tasks", [])
    if tasks:
        out += ["", "review tasks:"] + [f"  [{x['kind']}] {x['subject']}: {x['detail']}" for x in tasks]
    return out
