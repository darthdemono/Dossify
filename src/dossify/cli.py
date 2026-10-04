"""Dossify command-line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dossify.adapter_api import ExecutionPlan
from dossify.builtin_adapters import P0_ADAPTERS, builtin_manifests
from dossify.config import load_config
from dossify.pipeline import build_plan, canonical_json, execute_plan
from dossify.providers import provider_manifest


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
    subcommands.add_parser(
        "providers", help="print the built-in provider capability manifest"
    )
    adapters = subcommands.add_parser(
        "adapters", help="list public export-first adapter manifests"
    )
    adapters.add_argument("--json", action="store_true", help="print canonical JSON")
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
        "--output",
        type=Path,
        help="write canonical results to this file; defaults to stdout",
    )
    schemas = subcommands.add_parser(
        "schemas", help="write checked-in public adapter JSON Schemas"
    )
    schemas.add_argument("--output-dir", type=Path, default=Path("schemas"))
    return command


def _selected_p0(config, requested: list[str]):
    names = requested or [name for name in P0_ADAPTERS if name in config.providers]
    unknown = sorted(set(names) - set(P0_ADAPTERS))
    if unknown:
        raise ValueError(f"not an export-first P0 adapter: {', '.join(unknown)}")
    selected = []
    for name in names:
        values = config.providers.get(name)
        if values is None:
            raise ValueError(
                f'{name} needs a [providers.{name}] block with source = "..."'
            )
        typed = P0_ADAPTERS[name].config_model.model_validate(values)
        if typed.enabled:
            selected.append((name, P0_ADAPTERS[name], typed))
    return selected


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
        for provider in provider_manifest():
            print(
                f"{provider['name']}: {provider['category']} ({', '.join(provider['capabilities'])})"
            )
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
    if args.command == "journal":
        from dossify.journal import run

        run(config, apply=args.apply, only=args.adapters, force=args.force)
        return
    if args.command == "ingest":
        from dossify.ingest import run

        run(config, args.arguments)
        return
    if args.command == "migrate":
        from dossify.migrate import run

        run(config, args.months, apply=args.apply, demote_h3=args.demote_h3)
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
            results.append(execute_plan(adapter, typed, plan, cache_dir))
        _write_or_print({"format_version": "1.0", "results": results}, args.output)
