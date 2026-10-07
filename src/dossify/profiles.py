"""Output profiles: how deep a Dossify rendering goes.

Three *journal* profiles reshape the generated block inside each month file.
Three *document* profiles compile a standalone report with ``dossify compile``.
All six read the same facts, so a deeper profile never knows more than a
shallower one, it only says more about how it knows.
"""

from __future__ import annotations

from dataclasses import dataclass

DIGEST_LINES = 12


@dataclass(frozen=True)
class Profile:
    name: str
    kind: str          # "journal" shapes month files, "document" compiles a report
    title: str
    summary: str


PROFILES = {p.name: p for p in (
    Profile("digest", "journal", "Digest",
            f"Basic journal: at most {DIGEST_LINES} headline lines a day, no nested detail."),
    Profile("journal", "journal", "Journal",
            "Standard journal: every generated line, exactly as Dossify has always written it."),
    Profile("chronicle", "journal", "Chronicle",
            "Advanced journal: the full journal plus a per-day coverage line naming each source."),
    Profile("dossier", "document", "Dossier",
            "Report: scope, source coverage, monthly activity, measured facts and stated claims."),
    Profile("casefile", "document", "Casefile",
            "Super dossier: the dossier plus a day-by-day index, claim evidence and a gap register."),
    Profile("monograph", "document", "Monograph",
            "Research-paper dossier: abstract, methods, results, evidence, limitations, appendix."),
)}
DEFAULT = "journal"


def get(name: str, kind: str | None = None) -> Profile:
    try:
        profile = PROFILES[name]
    except KeyError:
        raise ValueError(f"unknown profile {name!r}; use one of {', '.join(PROFILES)}") from None
    if kind and profile.kind != kind:
        names = ", ".join(p.name for p in PROFILES.values() if p.kind == kind)
        raise ValueError(f"profile {name!r} is a {profile.kind} profile here; use one of {names}")
    return profile


def shape_day(lines: list[str], facts, profile: str) -> list[str]:
    """Reshape one day's rendered bullets for a journal profile."""
    if profile == "digest":
        top = [line for line in lines if line.startswith("- ")]
        out = top[:DIGEST_LINES]
        if len(top) > DIGEST_LINES:
            out.append("- %d more lines omitted by the digest profile" % (len(top) - DIGEST_LINES))
        return out
    if profile == "chronicle" and facts:
        sources = sorted({f.src for f in facts})
        return lines + ["", "_Coverage: %d records from %d source%s (%s)._" % (
            len(facts), len(sources), "" if len(sources) == 1 else "s", ", ".join(sources))]
    return lines
