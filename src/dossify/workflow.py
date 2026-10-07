"""Journal runs: collect, apply policy, render, then review, apply or undo.

``journal`` alone is a dry run and changes nothing.  ``--review`` records a run
in the private ledger (manifest, proposed and previous text, unified diff) and
still changes nothing.  ``apply <run-id>`` writes exactly what was reviewed, and
only if every file is still as it was; ``undo <run-id>`` restores it.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from dossify import identity_claims, ledger, privacy, profiles, review, unified
from dossify.people import load_people
from dossify.pipeline import digest


def ledger_root(config) -> Path:
    return (config.ledger_dir or (config.journal.cache_dir or Path.home() / ".cache" / "dossify") / "runs")


def _version() -> str:
    try:
        return metadata.version("dossify")
    except metadata.PackageNotFoundError:
        return "unknown"


@dataclass
class Evidence:
    """What a run knows: iterating yields ``(facts, outcomes, policy)``."""

    facts: list
    outcomes: list
    policy: dict
    tasks: list

    def __iter__(self):
        return iter((self.facts, self.outcomes, self.policy))


def prepare(config, journal, only, profile_name) -> Evidence:
    """Collect, apply the privacy policy, and gather review tasks."""
    journal.PROFILE = profile_name
    facts, outcomes, typed = unified.collect(config, journal, only)
    policy = privacy.resolve(config.privacy.preset, config.privacy.classes)
    facts, excluded = privacy.apply(facts, policy)
    for outcome in outcomes:
        if outcome.name in excluded:
            outcome.policy = excluded[outcome.name]
            if excluded[outcome.name] == "hidden" and outcome.status == "ok":
                outcome.status = "excluded_by_policy"
    findings = []
    if config.people_file and config.people_file.is_file():
        findings = identity_claims.contradictions(identity_claims.collect(load_people(config.people_file)))
    return Evidence(facts, outcomes, policy, review.tasks(facts, typed, findings))


def run(config, *, apply: bool, only: list[str] | None = None, force: bool = False,
        profile: str | None = None, review: bool = False) -> None:
    from dossify import journal

    journal.configure(config)
    only = only or []
    name = profiles.get(profile or config.output.profile, "journal").name
    if only and apply and not force:
        print("Refusing to write from a subset of adapters.\n"
              "  Fences are rebuilt wholesale, so writing with only %s would DELETE\n"
              "  every line the other adapters contribute. Run with no adapter names to\n"
              "  write everything, or add --force if losing the rest is what you want."
              % ", ".join(only))
        sys.exit(2)
    if apply and journal.OS_LOG_DIR:
        print("oslog harvest: %s" % journal.oslog.harvest(
            journal.OS_LOG_DIR, journal.HOME, journal.CRASH_IGNORE))
    evidence = prepare(config, journal, only, name)
    facts, outcomes, policy = evidence

    bymonth = defaultdict(lambda: defaultdict(list))
    for f in facts:
        bymonth[f.date[:7]][f.date].append(f)
    for ym in sorted(bymonth):
        for date in bymonth[ym]:
            bymonth[ym][date].sort(key=journal.day_order)
    import glob
    for p in glob.glob(os.path.join(journal.BASE, "20??-??.md")):
        bymonth.setdefault(os.path.basename(p)[:7], defaultdict(list))
    print("\n%d months, %d facts total, profile %s%s\n" % (
        len(bymonth), len(facts), name, "" if apply else "  (nothing written)"))

    changes: dict[str, tuple[Path, str | None]] = {}

    def emit(path, text):
        changes[os.path.basename(path)[:7]] = (Path(path), text)

    for ym in sorted(bymonth):
        journal.write_month(ym, bymonth[ym], apply, emit=emit)

    if not (apply or review):
        return

    root = ledger_root(config)
    previous = ledger.latest(root)
    record = ledger.Run(root, ledger.new_run_id())
    months = []
    for ym, (path, text) in sorted(changes.items()):
        before = ledger.read_text(path)
        if text == before:
            continue
        record.stash("before", ym, before)
        record.stash("proposed", ym, text)
        months.append({"ym": ym, "path": str(path), "sha_before": ledger.sha(before),
                       "sha_after": ledger.sha(text),
                       "action": "delete" if text is None else "create" if before is None else "update"})
    exports = (journal.RULES.get("exports") or {})
    record.manifest.update({
        "created_at": datetime.now(UTC).isoformat(), "dossify_version": _version(),
        "mode": "reviewed", "profile": name, "privacy_preset": config.privacy.preset,
        "privacy_policy": policy, "partial": bool(only), "only": only,
        "config_fingerprint": digest(config), "evidence_digest": ledger.evidence_digest(facts),
        "timezone_assumption": {
            "legacy_dates": "machine-local calendar dates",
            "machine_timezone": str(datetime.now().astimezone().tzinfo),
            "before_move_timezone": exports.get("before_move_timezone"),
            "move_utc": exports.get("move_utc")},
        "adapters": [asdict(o) for o in outcomes], "months": months,
        "review_tasks": [asdict(task) for task in evidence.tasks],
        "previous_run": previous.manifest["run_id"] if previous else None,
    })
    diff = "".join(ledger.unified_diff(m["path"], record.fetch("before", m["ym"]),
                                       record.fetch("proposed", m["ym"])) for m in months)
    record.dir.mkdir(parents=True, exist_ok=True)
    (record.dir / "changes.diff").write_text(diff, encoding="utf-8")
    record.save()
    print("run %s: %d month file%s would change, diff at %s" % (
        record.manifest["run_id"], len(months), "" if len(months) == 1 else "s", record.dir / "changes.diff"))
    if review:
        print("review it, then: dossify apply <config> %s" % record.manifest["run_id"])
        return
    _write(journal, record)


def _write(journal, record: ledger.Run) -> None:
    journal.track_journal("snapshot before regenerate")
    for m in record.manifest["months"]:
        path = Path(m["path"])
        proposed = record.fetch("proposed", m["ym"])
        if m["action"] == "delete":
            path.unlink(missing_ok=True)
        else:
            path.write_text(proposed, encoding="utf-8")
    record.manifest["mode"] = "applied"
    record.manifest["applied_at"] = datetime.now(UTC).isoformat()
    record.save()
    journal.track_journal("regenerate auto blocks")


def _current_mismatch(record: ledger.Run, key: str) -> list[str]:
    return [m["path"] for m in record.manifest["months"]
            if ledger.sha(ledger.read_text(Path(m["path"]))) != m[key]]


def apply_run(config, run_id: str, force: bool = False) -> None:
    from dossify import journal

    journal.configure(config)
    record = ledger.Run.load(ledger_root(config), run_id)
    mode = record.manifest.get("mode")
    if mode != "reviewed":
        raise SystemExit(f"run {run_id} is {mode}; only a reviewed run can be applied")
    if record.manifest.get("partial") and not force:
        raise SystemExit("this run covered only some adapters; applying it would delete the rest. "
                         "Re-review without adapter names, or pass --force")
    stale = _current_mismatch(record, "sha_before")
    if stale:
        raise SystemExit("refusing: changed since review (create a new review):\n  " + "\n  ".join(stale))
    _write(journal, record)
    print(f"applied run {run_id}: {len(record.manifest['months'])} files")


def undo_run(config, run_id: str) -> None:
    from dossify import journal

    journal.configure(config)
    record = ledger.Run.load(ledger_root(config), run_id)
    if record.manifest.get("mode") != "applied":
        raise SystemExit(f"run {run_id} is {record.manifest.get('mode')}; only an applied run can be undone")
    stale = _current_mismatch(record, "sha_after")
    if stale:
        raise SystemExit("refusing: edited since this run applied it (undo would lose that work):\n  "
                         + "\n  ".join(stale))
    journal.track_journal("snapshot before undo")
    for m in record.manifest["months"]:
        path = Path(m["path"])
        before = record.fetch("before", m["ym"])
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before, encoding="utf-8")
    record.manifest["mode"] = "undone"
    record.manifest["undone_at"] = datetime.now(UTC).isoformat()
    record.save()
    journal.track_journal("undo run " + run_id)
    print(f"undid run {run_id}: {len(record.manifest['months'])} files restored")
