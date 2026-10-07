"""Dossify command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dossify.adapter_api import ExecutionPlan
from dossify.builtin_adapters import P0_ADAPTERS, builtin_manifests  # noqa: F401
from dossify import checkpoints, profiles
from dossify.config import load_config
from dossify.pipeline import build_plan, canonical_json, execute_plan
from dossify.providers import provider_manifest, provider_table
from dossify.unified import selected_p0


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="dossify")
    subcommands = command.add_subparsers(dest="command", required=True)
    validate = subcommands.add_parser(
        "config-validate", help="validate a private Dossify TOML file"
    )
    validate.add_argument("config", type=Path)
    journal = subcommands.add_parser(
        "journal", help="compile a configured private journal"
    )
    journal.add_argument("config", type=Path)
    journal.add_argument(
        "adapters",
        nargs="*",
        help="optional adapter names; dry-run only unless --force",
    )
    journal.add_argument(
        "--apply", action="store_true", help="write generated auto blocks"
    )
    journal.add_argument(
        "--force", action="store_true", help="allow a subset of adapters to write"
    )
    journal.add_argument(
        "--review", action="store_true",
        help="record a reviewable run in the private ledger; writes nothing",
    )
    journal.add_argument(
        "--profile", choices=[p.name for p in profiles.PROFILES.values() if p.kind == "journal"],
        help="journal depth: digest, journal, chronicle",
    )
    for name, text in (("apply", "write exactly what a reviewed run proposed"),
                       ("undo", "restore the files an applied run changed")):
        run_cmd = subcommands.add_parser(name, help=text)
        run_cmd.add_argument("config", type=Path)
        run_cmd.add_argument("run_id")
        if name == "apply":
            run_cmd.add_argument("--force", action="store_true", help="apply a partial-adapter run")
    for name, text in (("doctor", "check paths, credentials and source readiness"),
                       ("status", "show per-source coverage from the latest recorded run"),
                       ("index", "build the disposable full-text timeline index")):
        subcommands.add_parser(name, help=text).add_argument("config", type=Path)
    search_cmd = subcommands.add_parser("search", help="full-text search the timeline index")
    search_cmd.add_argument("config", type=Path)
    search_cmd.add_argument("query")
    search_cmd.add_argument("--limit", type=int, default=50)
    for name, text in (("login", "authorize one configured read-only OAuth provider"),
                       ("logout", "revoke and delete one provider's stored token")):
        auth = subcommands.add_parser(name, help=text)
        auth.add_argument("config", type=Path)
        auth.add_argument("provider")
    init_cmd = subcommands.add_parser("init", help="create a private workspace skeleton")
    init_cmd.add_argument("directory", type=Path)
    compile_cmd = subcommands.add_parser(
        "compile", help="compile a dossier, casefile or monograph document"
    )
    compile_cmd.add_argument("config", type=Path)
    compile_cmd.add_argument(
        "--profile", default="dossier",
        choices=[p.name for p in profiles.PROFILES.values() if p.kind == "document"],
    )
    compile_cmd.add_argument("--period", default="all", help="all, YYYY, or YYYY-MM")
    compile_cmd.add_argument("--output", type=Path, help="write to this file")
    compile_cmd.add_argument("--write", action="store_true", help="write into the output directory")
    subcommands.add_parser("profiles", help="list the output profiles")
    people = subcommands.add_parser("people", help="People registry commands")
    people_commands = people.add_subparsers(dest="people_command", required=True)
    people_commands.add_parser(
        "claims", help="list identity claims and any contradictions"
    ).add_argument("config", type=Path)
    reconcile = people_commands.add_parser(
        "reconcile", help="reconcile exact-name People, Nextcloud, and Immich records"
    )
    reconcile.add_argument("config", type=Path)
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument("--snapshot-dir", type=Path)
    reconcile.add_argument("--report", type=Path)
    oslog_cmd = subcommands.add_parser(
        "oslog", help="harvest OS records into the durable log directory and commit them"
    )
    oslog_cmd.add_argument("config", type=Path)
    ingest = subcommands.add_parser(
        "ingest", help="inspect or safely ingest provider export archives"
    )
    ingest.add_argument("config", type=Path)
    ingest.add_argument(
        "arguments",
        nargs=argparse.REMAINDER,
        help="arguments formerly passed to export_ingest.py",
    )
    migrate = subcommands.add_parser(
        "migrate", help="add Manual/LLM/Auto sections to selected months"
    )
    migrate.add_argument("config", type=Path)
    migrate.add_argument("months", nargs="+", help="month files such as 2026-09.md")
    migrate.add_argument("--apply", action="store_true", help="write the migration")
    migrate.add_argument(
        "--demote-h3", action="store_true", help="demote existing level-three headings"
    )
    sync = subcommands.add_parser(
        "sync", help="reconcile exact-name People, Nextcloud, and Immich records"
    )
    sync.add_argument("config", type=Path)
    sync.add_argument("--apply", action="store_true", help="write the reviewed reconciliation")
    sync.add_argument("--snapshot-dir", type=Path, help="save private before-state snapshots")
    sync.add_argument("--report", type=Path, help="write the private JSON reconciliation report")
    providers = subcommands.add_parser(
        "providers", help="print the built-in provider capability manifest"
    )
    providers.add_argument("--markdown", action="store_true", help="print the README support table")
    adapters = subcommands.add_parser(
        "adapters", help="list public export-first adapter manifests"
    )
    adapters.add_argument("--json", action="store_true", help="print canonical JSON")
    adapters.add_argument("--external", action="store_true",
                          help="list installed third-party adapters (they load only if allowlisted)")
    conformance = subcommands.add_parser(
        "conformance", help="run the adapter conformance checks against a configured adapter"
    )
    conformance.add_argument("config", type=Path)
    conformance.add_argument("adapter")
    plan = subcommands.add_parser(
        "plan", help="create a no-read, no-write P0 adapter execution plan"
    )
    plan.add_argument("config", type=Path)
    plan.add_argument(
        "adapters", nargs="*", help="optional configured P0 adapter names"
    )
    plan.add_argument(
        "--output", type=Path, help="write the canonical plan bundle to this file"
    )
    facts = subcommands.add_parser(
        "facts", help="execute a reviewed P0 plan and emit normalized facts"
    )
    facts.add_argument("config", type=Path)
    facts.add_argument("plan", type=Path, help="plan bundle created by dossify plan")
    facts.add_argument(
        "--since-checkpoint", action="store_true",
        help="emit only facts after the last checkpoint minus the overlap window",
    )
    facts.add_argument("--overlap-days", type=int, default=3, help="days rescanned before the checkpoint")
    facts.add_argument(
        "--output",
        type=Path,
        help="write canonical results to this file; defaults to stdout",
    )
    schemas = subcommands.add_parser(
        "schemas", help="write checked-in public adapter JSON Schemas"
    )
    schemas.add_argument("--output-dir", type=Path, default=Path("schemas"))
    return command


_selected_p0 = selected_p0


def _write_or_print(payload: object, output: Path | None) -> None:
    rendered = canonical_json(payload) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"wrote {output}")
    else:
        print(rendered, end="")


def main() -> None:
    args = parser().parse_args()
    if args.command == "providers":
        if args.markdown:
            print(provider_table())
            return
        for provider in provider_manifest():
            print(
                f"{provider['name']}: {provider['category']} ({', '.join(provider['capabilities'])}) "
                f"[{provider['maturity']}]"
            )
        return
    if args.command == "profiles":
        for p in profiles.PROFILES.values():
            print(f"{p.name:10} {p.kind:9} {p.summary}")
        return
    if args.command == "init":
        from dossify.workspace import init

        init(args.directory)
        return
    if args.command == "adapters" and args.external:
        from dossify import external

        found = external.available()
        for name in sorted(found):
            print(f"{name}: {found[name].value}")
        print(f"{len(found)} external adapter(s) installed; none loads unless named under [adapters] external")
        return
    if args.command == "adapters":
        manifests = builtin_manifests()
        if args.json:
            _write_or_print(manifests, None)
        else:
            for manifest in manifests:
                print(
                    f"{manifest.provider_id}: {manifest.display_name} ({', '.join(manifest.capabilities)})"
                )
        return
    if args.command == "schemas":
        from dossify.schema import write_public_schemas

        write_public_schemas(args.output_dir)
        print(f"wrote public schemas to {args.output_dir}")
        return
    config = load_config(args.config)
    if args.command == "config-validate":
        print(f"valid: {args.config} (private journal configuration)")
        return
    if args.command in ("login", "logout"):
        from dossify import oauth

        try:
            settings = config.oauth[args.provider]
        except KeyError:
            raise SystemExit(f"no [oauth.{args.provider}] block in {args.config}") from None
        if args.command == "login":
            oauth.login(settings)
            print(f"stored a read-only token for {args.provider} at {settings.token_file}")
        else:
            print(oauth.logout(settings))
        return
    if args.command == "conformance":
        from dossify import conformance as conformance_checks

        (_name, adapter, typed), = selected_p0(config, [args.adapter])
        failures = conformance_checks.check(adapter, typed, config.journal.cache_dir)
        print("\n".join(failures) if failures else f"{args.adapter}: conforms")
        raise SystemExit(1 if failures else 0)
    if args.command == "journal":
        from dossify.journal import run

        run(config, apply=args.apply, only=args.adapters, force=args.force,
            profile=args.profile, review=args.review)
        return
    if args.command == "apply":
        from dossify.workflow import apply_run

        apply_run(config, args.run_id, args.force)
        return
    if args.command == "undo":
        from dossify.workflow import undo_run

        undo_run(config, args.run_id)
        return
    if args.command in ("doctor", "status"):
        from dossify import workspace

        raise SystemExit(getattr(workspace, args.command)(
            *((config, args.config) if args.command == "doctor" else (config,))))
    if args.command == "index":
        from dossify.workspace import build_index

        build_index(config)
        return
    if args.command == "search":
        from dossify.workspace import search

        search(config, args.query, args.limit)
        return
    if args.command == "compile":
        from dossify.workspace import compile_document

        compile_document(config, profile=args.profile, period=args.period,
                         output=args.output, write=args.write)
        return
    if args.command == "oslog":
        from dossify import journal

        journal.configure(config)
        if not journal.OS_LOG_DIR:
            raise SystemExit("set paths.os_log_dir in the journal rules file")
        print(journal.oslog.harvest(journal.OS_LOG_DIR, journal.HOME, journal.CRASH_IGNORE))
        return
    if args.command == "ingest":
        from dossify.ingest import run

        run(config, args.arguments)
        return
    if args.command == "migrate":
        from dossify.migrate import run

        run(config, args.months, apply=args.apply, demote_h3=args.demote_h3)
        return
    if args.command == "people" and args.people_command == "claims":
        from dossify import identity_claims
        from dossify.people import load_people

        claims = identity_claims.collect(load_people(config.people_file))
        for claim in claims:
            window = f" {claim.valid_from or ''}..{claim.valid_to or ''}" if claim.valid_from or claim.valid_to else ""
            print(f"{claim.person}: {claim.provider} {claim.identifier!r}{window} [{claim.status}; {claim.source}]")
        findings = identity_claims.contradictions(claims)
        print("\n".join(["", *findings]) if findings else "\nno contradictions")
        raise SystemExit(1 if findings else 0)
    if args.command == "people" or args.command == "sync":
        from dossify.sync import run

        run(config, apply=args.apply, snapshot_dir=args.snapshot_dir, report=args.report)
        return
    if args.command == "plan":
        plans = [
            build_plan(adapter, typed)
            for _name, adapter, typed in _selected_p0(config, args.adapters)
        ]
        _write_or_print({"format_version": "1.0", "plans": plans}, args.output)
        return
    if args.command == "facts":
        try:
            bundle = json.loads(args.plan.read_text(encoding="utf-8"))
            plans = [ExecutionPlan.model_validate(item) for item in bundle["plans"]]
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"cannot read a Dossify plan bundle: {exc}") from exc
        configured = {
            name: (adapter, typed) for name, adapter, typed in _selected_p0(config, [])
        }
        results = []
        for plan in plans:
            try:
                adapter, typed = configured[plan.provider_id]
            except KeyError as exc:
                raise ValueError(
                    f"plan provider {plan.provider_id} is not enabled in this config"
                ) from exc
            cache_dir = config.journal.cache_dir
            result = execute_plan(adapter, typed, plan, cache_dir)
            if args.since_checkpoint:
                previous = checkpoints.load(cache_dir, plan.provider_id)
                print(f"{plan.provider_id}: checkpoint {checkpoints.state(previous, result)}", file=sys.stderr)
                emitted = checkpoints.since(result, previous, args.overlap_days)
                checkpoints.save(cache_dir, result)
                result = emitted
            results.append(result)
        _write_or_print({"format_version": "1.0", "results": results}, args.output)
