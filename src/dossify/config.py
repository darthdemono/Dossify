"""Private Dossify journal configuration."""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from dossify.oauth import OAuthSettings


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


class OutputSettings(BaseModel):
    """Which rendering profile ``dossify journal`` and ``dossify compile`` default to."""

    model_config = ConfigDict(extra="forbid")

    profile: str = "journal"


class PrivacySettings(BaseModel):
    """Data-class privacy policy. Absent means unrestricted (legacy behaviour)."""

    model_config = ConfigDict(extra="forbid")

    preset: str | None = None
    classes: dict[str, str] = Field(default_factory=dict)


class AdapterSettings(BaseModel):
    """Third-party adapters the owner has chosen to trust, by entry-point name."""

    model_config = ConfigDict(extra="forbid")

    external: list[str] = Field(default_factory=list)


class DossifyConfig(BaseModel):
    """Configuration that remains in the private workspace, not Dossify itself."""

    model_config = ConfigDict(extra="forbid")

    people_file: Path | None = None
    output_dir: Path | None = None
    ledger_dir: Path | None = None
    claims_file: Path | None = None
    output: OutputSettings = Field(default_factory=OutputSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    adapters: AdapterSettings = Field(default_factory=AdapterSettings)
    oauth: dict[str, OAuthSettings] = Field(default_factory=dict)
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
    for name in ("ledger_dir", "claims_file"):
        value = getattr(config, name)
        if value and not value.is_absolute():
            setattr(config, name, (base / value).resolve())
    for field in ("workspace_root", "rules_file", "cache_dir", "elteportal_path"):
        value = getattr(config.journal, field)
        if value and not value.is_absolute():
            setattr(config.journal, field, (base / value).resolve())
    for settings in config.oauth.values():
        if not settings.token_file.is_absolute():
            settings.token_file = (base / settings.token_file).resolve()
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
