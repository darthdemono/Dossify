"""Private Dossify journal configuration."""

from __future__ import annotations

import tomllib
from datetime import datetime
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
    cache_dir: Path | None = None
    os_log_dir: Path | None = None       # durable system-log store used by the boot/login/package/crash/game readers
    group_chat_roster_max: int = 200     # larger group chats list no roster in the month file
    group_chat_inline_max: int = 6       # most speakers named inline before "+N"
    rules_file: Path | None = None       # retired: kept only so the error can say what to do


class TimezoneSpan(BaseModel):
    """Records before ``until`` are shown in ``zone`` (for someone who moved between timezones)."""

    model_config = ConfigDict(extra="forbid")

    until: datetime
    zone: str


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
    # Which data class an external adapter's records belong to, e.g. { my_adapter = "health" }.
    source_classes: dict[str, str] = Field(default_factory=dict)


class AdapterSettings(BaseModel):
    """Where the owner's own plugins live.  Installed plugins need no setting: a provider block turns one on."""

    model_config = ConfigDict(extra="forbid")

    # Folder of the owner's own plugins, auto-wired. Default: ./custom, then the checkout's custom/.
    custom_dir: Path | None = None


class IngestSettings(BaseModel):
    """Where ``dossify ingest`` unpacks data-request archives.  Point each provider's ``export`` at the result."""

    model_config = ConfigDict(extra="forbid")

    roots: list[Path] = Field(default_factory=list)   # first existing root wins
    default_meta_handle: str = ""


class DossifyConfig(BaseModel):
    """Configuration that remains in the private workspace, not Dossify itself."""

    model_config = ConfigDict(extra="forbid")

    people_file: Path | None = None
    output_dir: Path | None = None
    timezone: str | None = None          # IANA name; default is the machine's own
    timezone_history: list[TimezoneSpan] = Field(default_factory=list)
    ledger_dir: Path | None = None
    claims_file: Path | None = None
    output: OutputSettings = Field(default_factory=OutputSettings)
    privacy: PrivacySettings = Field(default_factory=PrivacySettings)
    adapters: AdapterSettings = Field(default_factory=AdapterSettings)
    ingest: IngestSettings = Field(default_factory=IngestSettings)
    oauth: dict[str, OAuthSettings] = Field(default_factory=dict)
    journal: JournalSettings = Field(default_factory=JournalSettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    providers: dict[str, dict[str, object]] = Field(default_factory=dict)


def load_config(path: Path) -> DossifyConfig:
    """Load a TOML configuration, resolving relative data paths beside it."""
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    config = DossifyConfig.model_validate(raw)
    if config.journal.rules_file:
        raise ValueError(
            "[journal] rules_file is retired: its settings now live in dossify.toml, as options on "
            "[providers.<name>] blocks. See docs/MIGRATING.md for where each old key went.")
    base = path.parent.resolve()
    if config.people_file and not config.people_file.is_absolute():
        config.people_file = base / config.people_file
    if config.output_dir and not config.output_dir.is_absolute():
        config.output_dir = base / config.output_dir
    for name in ("ledger_dir", "claims_file"):
        value = getattr(config, name)
        if value and not value.is_absolute():
            setattr(config, name, (base / value).resolve())
    for field in ("workspace_root", "cache_dir", "os_log_dir"):
        value = getattr(config.journal, field)
        if value and not value.is_absolute():
            setattr(config.journal, field, (base / value).resolve())
    if config.adapters.custom_dir and not config.adapters.custom_dir.is_absolute():
        config.adapters.custom_dir = (base / config.adapters.custom_dir).resolve()
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
