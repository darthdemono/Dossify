"""Cheap export-format sniffing, so an unsupported export is named, not silently empty.

Detection reads at most a few kilobytes and is used by ``doctor`` and by adapter
results; a plan never parses contents.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED = {
    "activitywatch": ("activitywatch-json",),
    "health_archive": ("apple-health-xml", "steps-csv"),
    "hyperos_dashboard": ("hyperos-dashboard-csv",),
    "immich": ("immich-metadata-json",),
    "nextcloud": ("nextcloud-activity-json", "ics"),
    "google_takeout": ("takeout-directory", "takeout-activity-json"),
}


def _head(path: Path, size: int = 4096) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(size).decode("utf-8", errors="replace").lstrip("﻿")
    except OSError:
        return ""


def detect(provider_id: str, path: Path) -> str | None:
    """The recognised format label for a source, or None when unrecognised."""
    if provider_id not in SUPPORTED:
        return None
    if path.is_dir():
        if provider_id == "google_takeout":
            return "takeout-directory" if any(path.rglob("*.json")) or any(path.rglob("*.html")) else None
        if provider_id == "hyperos_dashboard":
            return "hyperos-dashboard-csv" if any(path.glob("*dashboard-history*.csv")) else None
        return None
    head = _head(path)
    suffix = path.suffix.lower()
    if provider_id == "health_archive":
        if suffix == ".xml" and "<HealthData" in head:
            return "apple-health-xml"
        first_line = (head.splitlines() or [""])[0].lower()
        if suffix == ".csv" and "date" in first_line and "step" in first_line:
            return "steps-csv"
    elif provider_id == "hyperos_dashboard":
        if head.splitlines()[:1] == ["date,steps,duration,distance,calories"]:
            return "hyperos-dashboard-csv"
    elif provider_id == "activitywatch":
        if suffix == ".json" and ('"buckets"' in head or '"events"' in head):
            return "activitywatch-json"
    elif provider_id == "immich":
        if suffix == ".json" and head.lstrip()[:1] in "[{":
            return "immich-metadata-json"
    elif provider_id == "nextcloud":
        if suffix == ".ics" and "BEGIN:VCALENDAR" in head:
            return "ics"
        if suffix == ".json" and head.lstrip()[:1] in "[{":
            return "nextcloud-activity-json"
    elif provider_id == "google_takeout" and suffix == ".json" and head.lstrip()[:1] in "[{":
        return "takeout-activity-json"
    return None
