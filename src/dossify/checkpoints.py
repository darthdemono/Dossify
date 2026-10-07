"""Checkpoints make typed imports resumable with an overlap rescan.

After a run, the adapter's coverage end and input hashes are stored.  A later
``--since-checkpoint`` run emits only facts from ``overlap_days`` before that
end, so late-arriving records near the boundary are re-read without re-emitting
the whole archive.  A checkpoint never suppresses a changed input: if the export
file changed, the report says so.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

DEFAULT_OVERLAP_DAYS = 3


def _file(cache_dir: Path, provider_id: str) -> Path:
    return cache_dir / "checkpoints" / f"{provider_id}.json"


def load(cache_dir: Path | None, provider_id: str) -> dict | None:
    if not cache_dir:
        return None
    try:
        return json.loads(_file(cache_dir, provider_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state(previous: dict | None, result) -> str:
    """first_run, unchanged or changed_input, comparing input hashes."""
    if previous is None:
        return "first_run"
    now = {f.locator: f.sha256 for f in result.provenance.input_fingerprints}
    return "unchanged" if now == previous.get("inputs") else "changed_input"


def save(cache_dir: Path | None, result) -> None:
    if not cache_dir:
        return
    end = result.provenance.coverage.ends_at
    target = _file(cache_dir, result.provenance.provider_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "provider_id": result.provenance.provider_id,
        "inputs": {f.locator: f.sha256 for f in result.provenance.input_fingerprints},
        "coverage_end": end.isoformat() if end else None,
        "fact_count": len(result.facts),
        "saved_at": datetime.now(UTC).isoformat(),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def since(result, previous: dict | None, overlap_days: int = DEFAULT_OVERLAP_DAYS):
    """The result narrowed to the overlap window after the last checkpoint."""
    if not previous or not previous.get("coverage_end"):
        return result
    cutoff = datetime.fromisoformat(previous["coverage_end"]) - timedelta(days=overlap_days)
    return result.model_copy(update={"facts": tuple(f for f in result.facts if f.observed_at >= cutoff)})
