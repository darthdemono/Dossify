"""Private Dossify journal configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class JournalSettings(BaseModel):
    """Private journal locations and data files.

    Provider rules are deliberately data, not Python constants: a photo policy,
    account aliases, source descriptions, or local path can change without
    forking Dossify or placing a user's data in its source tree.
    """

    model_config = ConfigDict(extra="forbid")

    workspace_root: Path | None = None
    rules_file: Path | None = None
    cache_dir: Path | None = None
    elteportal_path: Path | None = None


class SyncSettings(BaseModel):
    """Private service settings for the explicit People registry synchronizer.

    Secret *values* never go in TOML.  The two credential settings name
    environment variables supplied by the caller.  The command is read-only
    unless its ``--apply`` switch is used.
    """

    model_config = ConfigDict(extra="forbid")

    nextcloud_url: str | None = None
    nextcloud_user: str | None = None
    nextcloud_password_env: str | None = None
    immich_url: str | None = None
    immich_api_key_env: str | None = None
    snapshot_dir: Path | None = None


class DossifyConfig(BaseModel):
    """Configuration that remains in the private workspace, not Dossify itself."""

    model_config = ConfigDict(extra="forbid")

    people_file: Path | None = None
    output_dir: Path | None = None
    journal: JournalSettings = Field(default_factory=JournalSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    providers: dict[str, dict[str, object]] = Field(default_factory=dict)


def load_config(path: Path) -> DossifyConfig:
    """Load a TOML configuration, resolving relative data paths beside it."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    config = DossifyConfig.model_validate(raw)
    base = path.parent.resolve()
    if config.people_file and not config.people_file.is_absolute():
        config.people_file = base / config.people_file
    if config.output_dir and not config.output_dir.is_absolute():
        config.output_dir = base / config.output_dir
    for field in ("workspace_root", "rules_file", "cache_dir", "elteportal_path"):
        value = getattr(config.journal, field)
        if value and not value.is_absolute():
            setattr(config.journal, field, (base / value).resolve())
    if config.sync.snapshot_dir and not config.sync.snapshot_dir.is_absolute():
        config.sync.snapshot_dir = (base / config.sync.snapshot_dir).resolve()
    # P0 adapters accept one explicitly configured export source.  Resolving it
    # here gives plans an unambiguous, reviewable path and keeps private TOML
    # portable when the workspace moves.
    for values in config.providers.values():
        source = values.get("source")
        if isinstance(source, str):
            candidate = Path(source)
            if not candidate.is_absolute():
                values["source"] = str((base / candidate).resolve())
    return config
