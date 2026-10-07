"""Workspace commands: init, doctor, status, index, search, compile."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from dossify import ledger, profiles, workflow
from dossify.claims import load_user_claims
from dossify.dossier import build
from dossify.providers import MATURITY, provider_manifest

STARTER = '''# Private Dossify configuration. Keep this and everything beside it out of git.
people_file = "People.json"
output_dir = "Journal"

[output]
# digest | journal | chronicle shape month files; dossier | casefile | monograph compile reports.
profile = "journal"

[privacy]
# minimal | balanced | forensic. Delete this block for no restriction.
preset = "balanced"

[journal]
workspace_root = "."
rules_file = "Journal Rules.json"
'''


def init(target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    made = []
    for name, body in (("dossify.toml", STARTER), ("People.json", "{}\n"), ("Journal Rules.json", "{}\n")):
        path = target / name
        if path.exists():
            print(f"kept   {path}")
            continue
        path.write_text(body, encoding="utf-8")
        made.append(name)
    (target / "Journal").mkdir(exist_ok=True)
    (target / ".gitignore").write_text(
        (target / ".gitignore").read_text() if (target / ".gitignore").exists()
        else "dossify.toml\nPeople.json\nJournal Rules.json\nJournal/\n", encoding="utf-8")
    print(f"created {', '.join(made) or 'nothing new'} in {target}; next: dossify doctor {target / 'dossify.toml'}")


def doctor(config, config_path: Path) -> int:
    problems = 0

    def check(ok: bool, label: str, hint: str = "") -> None:
        nonlocal problems
        print(("ok    " if ok else "FAIL  ") + label + ("" if ok else f"  -> {hint}"))
        problems += not ok

    check(sys.version_info >= (3, 13), f"python {sys.version_info.major}.{sys.version_info.minor}", "needs 3.13+")
    check(bool(config.output_dir and config.output_dir.is_dir()), "output_dir exists", "create it or fix output_dir")
    check(bool(config.people_file and config.people_file.is_file()), "people_file exists", "create People.json")
    check(bool(config.journal.rules_file and config.journal.rules_file.is_file()), "rules_file exists", "create Journal Rules.json")
    check(bool(config.journal.workspace_root and config.journal.workspace_root.is_dir()), "workspace_root exists")
    root = workflow.ledger_root(config)
    check(os.access(root if root.exists() else root.parent if root.parent.exists() else Path.home(), os.W_OK),
          f"ledger directory writable ({root})", "set ledger_dir")
    if config.claims_file:
        check(config.claims_file.is_file(), "claims_file exists")
    try:
        profiles.get(config.output.profile)
        check(True, f"profile {config.output.profile}")
    except ValueError as exc:
        check(False, "profile", str(exc))
    try:
        from dossify import privacy

        privacy.resolve(config.privacy.preset, config.privacy.classes)
        check(True, f"privacy {config.privacy.preset or 'unrestricted'}")
    except ValueError as exc:
        check(False, "privacy", str(exc))
    for env in (config.sync.nextcloud_password_env, config.sync.immich_api_key_env):
        if env:
            check(env in os.environ, f"credential variable {env} is set", "export it before dossify sync")
    from dossify.unified import selected_p0

    for name, _adapter, typed in selected_p0(config, []):
        check(Path(typed.source).exists(), f"typed adapter {name}: source exists", "fix source path")
    counts: dict[str, int] = {}
    for p in provider_manifest():
        counts[p["maturity"]] = counts.get(p["maturity"], 0) + 1
    print("providers by support: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    print("DONE" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


def status(config) -> int:
    run = ledger.latest(workflow.ledger_root(config))
    if not run:
        print("no recorded run yet; use: dossify journal <config> --review")
        return 1
    print("\n".join(ledger.status_lines(run.manifest)))
    print("\nsupport levels: " + "; ".join(f"{k} = {v}" for k, v in MATURITY.items()))
    return 0


def compile_document(config, *, profile: str, period: str, output: Path | None, write: bool) -> None:
    from dossify import journal

    journal.configure(config)
    prof = profiles.get(profile, "document")
    evidence = workflow.prepare(config, journal, [], "journal")
    facts, outcomes, policy = evidence
    previous = ledger.latest(workflow.ledger_root(config))
    text = build(facts, outcomes, profile=prof.name, period=period,
                 claims=load_user_claims(config.claims_file), policy=policy, sources=journal.SOURCES,
                 digest=ledger.evidence_digest(facts), run_id=previous.manifest["run_id"] if previous else None,
                 timezone=str(__import__("datetime").datetime.now().astimezone().tzinfo),
                 tasks=evidence.tasks)
    target = output or (Path(journal.BASE) / "Dossiers" / f"{prof.title} - {period}.md" if write else None)
    if target:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"wrote {target}")
    else:
        print(text, end="")


def index_path(config) -> Path:
    return (config.journal.cache_dir or Path.home() / ".cache" / "dossify") / "index.sqlite"


def build_index(config) -> None:
    """A disposable full-text index of the day timeline. Markdown stays canonical."""
    from dossify import journal

    journal.configure(config)
    facts, _outcomes, _policy = workflow.prepare(config, journal, [], "journal")
    path = index_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    db = sqlite3.connect(path)
    db.execute("create virtual table facts using fts5(date unindexed, time unindexed, src, text)")
    db.executemany("insert into facts values (?,?,?,?)", [(f.date, f.time or "", f.src, f.text) for f in facts])
    db.commit()
    db.close()
    print(f"indexed {len(facts)} records into {path} (delete it any time; it is rebuilt from the sources)")


def search(config, query: str, limit: int) -> None:
    path = index_path(config)
    if not path.exists():
        raise SystemExit("no index yet; run: dossify index <config>")
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    for d, t, s, text in db.execute(
            "select date, time, src, text from facts where facts match ? order by date, time limit ?",
            (query, limit)):
        print(f"{d} {t or '     '} [{s}] {text.splitlines()[0]}")
