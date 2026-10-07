"""Standalone document profiles: dossier, casefile, monograph.

Everything stated here is counted from the facts or taken from the owner's
claims file.  Nothing is inferred: where a conclusion would need guessing, the
document says what is missing instead.
"""

from __future__ import annotations

import calendar
from collections import Counter, defaultdict
from datetime import date, datetime

from dossify import profiles
from dossify.claims import FORBIDDEN_PREDICATES, Claim
from dossify.providers import maturity_of


def _table(head: list[str], rows: list[list[object]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out + [""]


def _days_in(period: str, first: str, last: str) -> int:
    if len(period) == 7:
        return calendar.monthrange(int(period[:4]), int(period[5:]))[1]
    if len(period) == 4:
        return 366 if calendar.isleap(int(period)) else 365
    return (date.fromisoformat(last) - date.fromisoformat(first)).days + 1


def derive_claims(facts, period: str, digest: str) -> list[Claim]:
    """Observed per-source counts and derived totals, each citing the evidence digest."""
    if not facts:
        return []
    ev = [f"evidence digest {digest[:12]}"]
    dates = sorted({f.date for f in facts})
    per_day = Counter(f.date for f in facts)
    busiest, n = max(sorted(per_day.items()), key=lambda kv: kv[1])
    span = _days_in(period, dates[0], dates[-1])
    claims = [Claim(predicate="source.records", value=f"{src}: {count}", claim_type="observed",
                    valid_from=date.fromisoformat(dates[0]), valid_to=date.fromisoformat(dates[-1]),
                    evidence=ev, algorithm="count/1")
              for src, count in sorted(Counter(f.src for f in facts).items())]
    claims += [
        Claim(predicate="records.total", value=str(len(facts)), claim_type="derived",
              evidence=ev, algorithm="count/1"),
        Claim(predicate="days.with_records", value=f"{len(dates)} of {span}", claim_type="derived",
              evidence=ev, algorithm="distinct-days/1",
              coverage="%.0f%% of days" % (100 * len(dates) / span)),
        Claim(predicate="days.busiest", value=f"{busiest} ({n} records)", claim_type="derived",
              evidence=ev, algorithm="max-per-day/1"),
    ]
    return claims


def build(facts, outcomes, *, profile: str, period: str, claims: list[Claim], policy: dict,
          sources: dict[str, str], digest: str, run_id: str | None, timezone: str,
          tasks: list | None = None) -> str:
    prof = profiles.get(profile, "document")
    facts = [f for f in facts if period == "all" or f.date.startswith(period)]
    derived = derive_claims(facts, period, digest)
    dates = sorted({f.date for f in facts})
    per_src = Counter(f.src for f in facts)
    by_month: dict[str, list] = defaultdict(list)
    for f in facts:
        by_month[f.date[:7]].append(f)
    month_rows = [[ym, len(v), len({f.date for f in v}), ", ".join(sorted({f.src for f in v}))]
                  for ym, v in sorted(by_month.items())]
    gaps_empty = []
    if dates:
        y, m = int(dates[0][:4]), int(dates[0][5:7])
        while (y, m) <= (int(dates[-1][:4]), int(dates[-1][5:7])):
            if f"{y:04d}-{m:02d}" not in by_month:
                gaps_empty.append(f"{y:04d}-{m:02d}")
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    cover = f"{dates[0]} to {dates[-1]}" if dates else "no records"
    out = ["---", f"title: {prof.title} - {period}", f"datetime: {datetime.now().replace(microsecond=0).isoformat()}",
           f"description: {prof.title} compiled by Dossify from {len(facts)} records, {cover}",
           f"profile: {profile}", f"period: {period}", "---", "",
           f"# {prof.title}: {period}", "",
           "**PRIVATE.** Compiled from personal records. Every statement below is counted or quoted, never guessed.", ""]

    status_rows = []
    for o in outcomes:
        if o.status == "not_selected":
            continue
        status_rows.append([o.name, o.status.replace("_", " "), per_src.get(o.name, 0),
                            o.first_date or "", o.last_date or "", maturity_of(o.name), o.policy or "raw"])
    src_head = ["Source", "Status", "Records in period", "First seen", "Last seen", "Support", "Privacy"]

    def claim_rows(items):
        return [[c.predicate, c.value, c.claim_type, c.coverage or "", c.algorithm or ""] for c in items]

    stated = [c for c in claims if c.status == "active"]
    tasks = tasks or []
    task_lines = [f"- [{x.kind}] {x.subject}: {x.detail}" for x in tasks]
    unknown = [o for o in outcomes if o.status in ("failed", "no_events", "excluded_by_policy", "replaced_by_typed")]

    if profile == "monograph":
        total = len(facts)
        out += ["## Abstract", "",
                f"This document summarises {total} records from {len(per_src)} sources covering {cover}. "
                f"Records fall on {len(dates)} distinct days. Figures are counts of what the sources reported; "
                "no behaviour, state of mind or relationship is inferred. Gaps, failed sources and privacy "
                "withholdings are listed under Limitations.", "",
                "## 1. Scope", "", f"Period: {period}. Evidence digest: `{digest[:16]}`"
                + (f". Ledger run: `{run_id}`." if run_id else "."), "",
                "## 2. Method", "",
                "Each source is read by a Dossify adapter. A fact is a dated line with a source; facts are "
                "merged, de-duplicated, passed through the privacy policy, then counted. No statistical model is applied.", ""]
        out += _table(src_head, status_rows)
        out += [f"Privacy policy: {policy or 'unrestricted'}. Dates are {timezone}-local calendar dates unless a "
                "source states otherwise.", "",
                "## 3. Results", "", "### 3.1 Activity by month", ""]
        out += _table(["Month", "Records", "Active days", "Sources"], month_rows)
        out += ["### 3.2 Measured facts", ""]
        out += _table(["Measure", "Value", "Type", "Coverage", "Algorithm"], claim_rows(derived))
        out += ["## 4. Evidence", ""]
        notes = []
        for src in sorted(per_src):
            notes.append(f"[^{len(notes) + 1}]: {src}: {sources.get(src, 'no description recorded')}")
        out += ["Source records are cited by footnote: " + ", ".join(f"{s}[^{i + 1}]" for i, s in enumerate(sorted(per_src))), ""]
        out += ["## 5. Stated claims", ""]
        out += _table(["Predicate", "Value", "Type", "Coverage", "Algorithm"], claim_rows(stated))
        out += ["## 6. Limitations", "",
                "- Absence of a record is not absence of an event: a source reports only what it holds.",
                "- Counts measure how much a source recorded, not how much happened.",
                "- Dossify generates no inferred claims. Refused by design: " + ", ".join(FORBIDDEN_PREDICATES) + ".",
                "- Contradiction checks cover identifier ownership, future-dated records and disagreeing "
                "step totals from typed sources; anything else is not compared."]
        out += [f"- Source `{o.name}`: {o.status.replace('_', ' ')}" + (f" ({o.error})" if o.error else "")
                for o in unknown]
        out += [f"- No records in {m}" for m in gaps_empty]
        out += ["", "## 7. Review tasks", ""] + (task_lines or ["None. No contradiction was detected."])
        out += ["", "## Appendix A. Reproducibility", "",
                f"Re-run `dossify compile <config> --profile monograph --period {period}`; identical sources give the same digest.", ""]
        out += notes
        return "\n".join(out).rstrip() + "\n"

    out += ["## Scope", "", f"- Period: {period} ({cover})", f"- Records: {len(facts)} from {len(per_src)} sources on {len(dates)} days",
            f"- Evidence digest: `{digest[:16]}`" + (f", ledger run `{run_id}`" if run_id else ""), "",
            "## Sources and coverage", ""]
    out += _table(src_head, status_rows)
    out += ["## Activity by month", ""] + _table(["Month", "Records", "Active days", "Sources"], month_rows)
    out += ["## Measured facts", ""] + _table(["Measure", "Value", "Type", "Coverage", "Algorithm"], claim_rows(derived))
    out += ["## Stated claims", ""] + _table(["Predicate", "Value", "Type", "Coverage", "Algorithm"], claim_rows(stated))
    out += ["## Unknown", ""]
    out += [f"- `{o.name}`: {o.status.replace('_', ' ')}" + (f" ({o.error})" if o.error else "") for o in unknown] or ["- No source failed or was withheld."]
    out += [f"- No records in {m}" for m in gaps_empty]
    out += ["", "## Review tasks", ""] + (task_lines or ["None. No contradiction was detected."]) + [""]
    if profile == "casefile":
        out += ["## Claim evidence", ""]
        for c in derived + stated:
            out.append(f"- **{c.predicate}** = {c.value} ({c.claim_type}); algorithm {c.algorithm or 'n/a'}; "
                       f"evidence: {', '.join(c.evidence) or 'owner statement'}")
        out += ["", "## Gap register", ""]
        gap_rows = [[o.name, a, b, n] for o in outcomes for a, b, n in o.gaps]
        out += _table(["Source", "From", "To", "Silent days"], gap_rows)
        out += ["## Day index", ""]
        by_day = defaultdict(list)
        for f in facts:
            by_day[f.date].append(f.src)
        out += [f"- {d}: {len(v)} records ({', '.join(sorted(set(v)))})" for d, v in sorted(by_day.items())]
        out += [""]
    return "\n".join(out).rstrip() + "\n"
