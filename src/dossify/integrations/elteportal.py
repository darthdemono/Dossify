"""ELTE portal adapter: Canvas submissions and grades, and the Neptun timetable.

A niche, optional adapter for students of a university that EltePortal supports.  It reads through
the public `EltePortal <https://github.com/darthdemono/EltePortal>`_ library, so a different university
works too if you give it that university's profile.  Install the library with
``uv sync --extra elte`` (or ``pip install "dossify[elte]"``), switch the adapter on with a
``[providers.elteportal]`` block, and run ``dossify doctor`` to check the connection.

It produces three kinds of fact and nothing else:

* ``education.scheduled``  - timetable events, read from a Neptun calendar export file
* ``education.submitted``  - Canvas submissions, by ``submitted_at``
* ``education.graded``     - Canvas grades, by ``graded_at``

The Neptun timetable comes from an exported calendar file, never from a login, so this adapter cannot
trigger the account-lockout risk the Neptun client guards against.  Canvas is read through EltePortal's
GET-only helpers with the token EltePortal resolves; the token never enters a fact.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dossify_adapter_api import (
    ADAPTER_API_VERSION,
    AdapterManifest,
    AdapterResult,
    CacheDirective,
    Coverage,
    Fact,
    InputFingerprint,
    PlannedRead,
    Provenance,
    Sensitivity,
    TimePrecision,
)
from pydantic import BaseModel, ConfigDict

INSTALL_HINT = 'EltePortal is not installed: run `uv sync --extra elte` (or `pip install "dossify[elte]"`)'
ICS_LINE = re.compile(r"^(DTSTART|SUMMARY|LOCATION)[^:]*:(.*)$")
START = re.compile(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?")


class ElteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    neptun_ics: Path | None = None    # a Neptun calendar export (.ics); the timetable is read from this file only
    canvas: bool = True               # submissions
    grades: bool = True               # graded_at timeline
    profile: Path | None = None       # an EltePortal institution profile; the bundled one when omitted
    settings: Path | None = None      # EltePortal's own settings file, when you keep one


def _library():
    try:
        import elteportal
        from elteportal import canvas
        from elteportal import config as elte_config
    except ImportError as exc:
        raise ImportError(INSTALL_HINT) from exc
    return elteportal, canvas, elte_config


def _client(typed: ElteConfig):
    elteportal, canvas, elte_config = _library()
    client = elteportal.Client(profile_path=typed.profile, config_path=typed.settings)
    return client, canvas, elte_config


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _num(value: Any) -> int | float | None:
    """Canvas returns 0.659047619047619; nobody writes that in a diary."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if abs(number - round(number)) < 1e-9 else round(number, 2)


def timetable(text: str, today: str, locator: str, zone) -> list[Fact]:
    """Events up to ``today`` from an iCalendar body; later events are not history yet.

    A time ending in ``Z`` is UTC; a floating time is read in ``zone``.
    """
    out, event = [], {}
    for line in text.replace("\r\n ", "").replace("\n ", "").split("\n"):
        line = line.strip()
        if line == "BEGIN:VEVENT":
            event = {}
        elif line == "END:VEVENT":
            start, summary = event.get("DTSTART", ""), event.get("SUMMARY", "").strip()
            m = START.match(start)
            if not (m and summary):
                continue
            year, month, day = (int(x) for x in m.group(1, 2, 3))
            if m.group(4):
                clock = (int(m.group(4)), int(m.group(5)))
                at = datetime(year, month, day, *clock, tzinfo=UTC if start.rstrip().endswith("Z") else zone)
                precision = TimePrecision.INSTANT
                local_day = at.astimezone(zone).strftime("%Y-%m-%d")
            else:
                at, precision = datetime(year, month, day, tzinfo=UTC), TimePrecision.DAY
                local_day = f"{year:04d}-{month:02d}-{day:02d}"
            if local_day > today:
                continue
            place = event.get("LOCATION", "").strip()
            out.append(Fact(
                provider_id="elteportal", adapter_id="elteportal_journal", source_locator=locator,
                observed_at=at, time_precision=precision, event_type="education.scheduled",
                values={"summary": summary, "location": place},
                display=f"Scheduled: {summary}{f' ({place})' if place else ''}"))
        else:
            m = ICS_LINE.match(line)
            if m:
                event[m.group(1)] = m.group(2)
    return out


def canvas_facts(canvas, token: str, want_submissions: bool, want_grades: bool) -> list[Fact]:
    out = []
    courses = [(c["id"], (c.get("name") or "").strip())
               for c in canvas.courses(token, states=("active", "completed"))]
    for course_id, course in courses:
        base = dict(provider_id="elteportal", adapter_id="elteportal_journal",
                    source_locator=f"canvas:course/{course_id}/assignments")
        for item in canvas.assignments_with_submission(token, course_id):
            sub = item.get("submission") or {}
            name = item.get("name", "?")
            if want_submissions and (at := _iso(sub.get("submitted_at"))):
                out.append(Fact(**base, source_record_id=f"{course_id}:{item.get('id')}:submitted",
                                observed_at=at, event_type="education.submitted",
                                values={"assignment": name, "course": course},
                                display=f"Submitted on Canvas: {name} ({course})"))
            score = _num(sub.get("score"))
            if want_grades and (at := _iso(sub.get("graded_at"))) and score is not None:
                top = _num(item.get("points_possible"))
                mark = f"{score}/{top}" if top else str(score)
                out.append(Fact(**base, source_record_id=f"{course_id}:{item.get('id')}:graded",
                                observed_at=at, event_type="education.graded",
                                sensitivity=Sensitivity.SENSITIVE,
                                values={"assignment": name, "course": course, "score": score},
                                display=f"Canvas grade: {name}, {mark} ({course})"))
    return out


class ElteAdapter:
    config_model = ElteConfig
    manifest = AdapterManifest(
        provider_id="elteportal", adapter_id="elteportal_journal",
        display_name="ELTE portal (Canvas submissions and grades, Neptun timetable)",
        adapter_version="1.0.0", adapter_api_min="1.0", adapter_api_max="1.0",
        config_schema_version="1.0",
        config_schema_id="https://dossify.dev/schemas/adapters/elteportal-journal/1.0.json",
        capabilities=("facts.read", "network.read", "export.read"),
        requested_permissions=("filesystem.read", "network.read"), deterministic_output=False)

    def _host(self, typed: ElteConfig) -> str:
        client, canvas, elte_config = _client(typed)
        with elte_config.use(client.profile, client.settings):
            return urlsplit(canvas.base_url()).hostname or ""

    def network_hosts(self, config) -> tuple[str, ...]:
        typed = self.config_model.model_validate(config)
        return (self._host(typed),) if typed.canvas or typed.grades else ()

    def plan(self, config):
        typed = self.config_model.model_validate(config)
        reads, warnings = [], []
        if typed.canvas or typed.grades:
            _library()                         # fail early, with the install hint, when it is missing
            warnings.append(f"GET requests to {self._host(typed)} with the Canvas token EltePortal resolves; nothing is written.")
        if typed.neptun_ics:
            path = Path(typed.neptun_ics).expanduser()
            if path.is_file():
                stat = path.stat()
                reads.append(PlannedRead(locator=str(path.resolve()), reason="Neptun calendar export",
                                         size_bytes=stat.st_size,
                                         modified_at=datetime.fromtimestamp(stat.st_mtime, UTC)))
            else:
                warnings.append(f"{path} is missing; export your Neptun calendar to that file. Neptun is never logged in to.")
        return tuple(reads), tuple(warnings)

    def execute(self, config, plan, fingerprints: tuple[InputFingerprint, ...]) -> AdapterResult:
        from dossify import journal

        typed = self.config_model.model_validate(config)
        zone = journal.TZ_DEFAULT
        facts: list[Fact] = []
        today = datetime.now(zone).strftime("%Y-%m-%d")
        for read in plan.reads:
            facts += timetable(Path(read.locator).read_text(encoding="utf-8", errors="replace"), today, read.locator, zone)
        if typed.canvas or typed.grades:
            client, canvas, elte_config = _client(typed)
            with elte_config.use(client.profile, client.settings):
                facts += canvas_facts(canvas, canvas.token(), typed.canvas, typed.grades)
        stamps = sorted(f.observed_at for f in facts)
        coverage = (Coverage(starts_at=stamps[0], ends_at=stamps[-1], complete=False,
                             note="Canvas shows only what the account can still see")
                    if stamps else Coverage(complete=False, note="no records"))
        return AdapterResult(facts=tuple(facts), provenance=Provenance(
            provider_id="elteportal", adapter_id="elteportal_journal",
            adapter_version=self.manifest.adapter_version, adapter_api_version=ADAPTER_API_VERSION,
            plan_id=plan.plan_id, input_fingerprints=fingerprints,
            effective_permissions=plan.permissions, coverage=coverage,
            cache=CacheDirective(reusable=False, cache_key="0" * 64, decision="bypass", reason="set by core")))

    def diagnose(self, config) -> list[tuple[bool, str, str]]:
        """Checks ``dossify doctor`` prints.  Never prints a credential, only whether one resolves."""
        typed = self.config_model.model_validate(config)
        try:
            client, canvas, elte_config = _client(typed)
        except ImportError:
            return [(False, "EltePortal library installed", INSTALL_HINT)]
        rows = [(True, "EltePortal library installed", "")]
        with elte_config.use(client.profile, client.settings):
            rows.append((True, f"profile loaded ({client.profile.get('name', 'unnamed')})", ""))
            if typed.canvas or typed.grades:
                try:
                    canvas.token()
                    rows.append((True, "Canvas token resolves", ""))
                except Exception:
                    rows.append((False, "Canvas token resolves",
                                 "set CANVAS_API_KEY or configure an EltePortal secret backend (see its docs/secrets.md)"))
        if typed.neptun_ics:
            path = Path(typed.neptun_ics).expanduser()
            rows.append((path.is_file(), f"Neptun calendar export exists ({path.name})",
                         "export your Neptun calendar to that path"))
        return rows


ADAPTER = ElteAdapter()
