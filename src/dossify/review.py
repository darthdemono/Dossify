"""Contradictions and gaps surfaced as review tasks, never resolved silently."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ReviewTask:
    kind: str
    subject: str
    detail: str


def steps_by_day(typed) -> dict[str, dict[str, int]]:
    days: dict[str, dict[str, int]] = {}
    for fact in typed:
        if fact.event_type.startswith("health.steps") and "steps" in fact.values:
            day = fact.observed_at.date().isoformat()
            days.setdefault(day, {})[fact.provider_id] = int(fact.values["steps"])
    return days


def tasks(facts, typed, identity_findings: list[str], today: date | None = None) -> list[ReviewTask]:
    today = today or date.today()
    out = [ReviewTask("identity", "People.json", finding) for finding in identity_findings]
    future = sorted({(f.src, f.date) for f in facts if f.date > today.isoformat()})
    out += [ReviewTask("future_dated", src, f"records dated {day}, which has not happened") for src, day in future[:20]]
    for day, per in sorted(steps_by_day(typed).items()):
        if len(set(per.values())) > 1:
            pair = " vs ".join(f"{k}={v:,}" for k, v in sorted(per.items()))
            out.append(ReviewTask("steps_disagree", day,
                                  f"{pair}; these may share sensors, so they are never added together"))
    return out
