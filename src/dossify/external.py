"""Adapter discovery: installed entry points, and the owner's own ``custom/`` folder.

Loading an *installed* entry point runs third-party code, so nothing loads unless
the owner switched it on with a ``[providers.<name>]`` block in their private configuration.

The ``custom/`` folder is different: it is the owner's own code, gitignored and
never published, so everything in it is wired in automatically.  A ``custom/``
entry is either ``name.py`` or a package directory ``name/__init__.py`` and
exposes ``ADAPTER`` (one adapter), ``ADAPTERS`` (several) or ``register()``
returning adapters.  A broken plugin is reported and skipped; it never stops a
run.  Being discovered does not switch a plugin on: a ``[providers.<name>]`` block
in the configuration does, exactly as for any typed adapter.

No adapter, installed or custom, may take the name of a built-in provider.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from importlib import metadata
from pathlib import Path

from dossify.builtin_adapters import P0_ADAPTERS
from dossify.privacy import SOURCE_CLASS

GROUP = "dossify.adapters"
RESERVED = set(P0_ADAPTERS) | set(SOURCE_CLASS) | {"git", "wakatime", "claude", "worklog", "boots", "logins", "dnf",
                                                    "crashes", "github", "ncloud"}


def available() -> dict[str, metadata.EntryPoint]:
    return {ep.name: ep for ep in metadata.entry_points(group=GROUP)}


def load_configured(config) -> dict[str, object]:
    """Installed plugins switched on by a ``[providers.<name>]`` block of the same name.

    Writing the block is the owner's explicit opt-in, so installing a package never runs it by
    itself and no separate allowlist is needed.  A name that matches a built-in provider is
    never loaded from an entry point.
    """
    wanted = [name for name in available() if name in config.providers and name not in RESERVED
              and config.providers[name].get("enabled", True)]
    return load(wanted)


def load(allowed: list[str]) -> dict[str, object]:
    """Load only allowlisted adapters; an unknown or reserved name is an error."""
    found = available()
    loaded: dict[str, object] = {}
    for name in allowed:
        if name in RESERVED:
            raise ValueError(f"external adapter {name!r} collides with a built-in provider")
        if name not in found:
            raise ValueError(f"external adapter {name!r} is allowed in config but not installed")
        target = found[name].load()
        adapter = target() if isinstance(target, type) else target
        if adapter.manifest.provider_id != name:
            raise ValueError(f"entry point {name!r} declares provider_id {adapter.manifest.provider_id!r}")
        loaded[name] = adapter
    return loaded


_CACHE: dict[tuple[str, float], tuple[dict[str, object], dict[str, str]]] = {}


def custom_dir(config=None) -> Path | None:
    """The folder of custom plugins: config, then $DOSSIFY_CUSTOM_DIR, then ./custom, then the checkout's."""
    candidates = []
    if config is not None and config.adapters.custom_dir:
        candidates.append(config.adapters.custom_dir)
    if os.environ.get("DOSSIFY_CUSTOM_DIR"):
        candidates.append(Path(os.environ["DOSSIFY_CUSTOM_DIR"]))
    candidates += [Path.cwd() / "custom", Path(__file__).resolve().parents[2] / "custom"]
    return next((c for c in candidates if c.is_dir()), None)


def _import(path: Path):
    name = f"dossify_custom_{path.stem}"
    if path.is_dir():
        spec = importlib.util.spec_from_file_location(name, path / "__init__.py",
                                                      submodule_search_locations=[str(path)])
    else:
        spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _adapters_of(module) -> list[object]:
    if hasattr(module, "ADAPTERS"):
        return list(module.ADAPTERS)
    if hasattr(module, "register"):
        return list(module.register())
    if hasattr(module, "ADAPTER"):
        return [module.ADAPTER]
    raise ValueError("defines none of ADAPTER, ADAPTERS or register()")


def discover_custom(folder: Path | None) -> tuple[dict[str, object], dict[str, str]]:
    """``(adapters by provider id, errors by plugin name)`` for one custom folder."""
    if folder is None:
        return {}, {}
    stamp = max([folder.stat().st_mtime] + [p.stat().st_mtime for p in folder.rglob("*.py")])
    key = (str(folder.resolve()), stamp)
    if key in _CACHE:
        return _CACHE[key]
    found: dict[str, object] = {}
    errors: dict[str, str] = {}
    entries = sorted(p for p in folder.iterdir() if not p.name.startswith(("_", "."))
                     and (p.suffix == ".py" or (p.is_dir() and (p / "__init__.py").exists())))
    for entry in entries:
        name = entry.stem if entry.is_file() else entry.name
        try:
            for adapter in _adapters_of(_import(entry)):
                provider = adapter.manifest.provider_id
                if provider in RESERVED:
                    raise ValueError(f"provider {provider!r} collides with a built-in provider")
                if provider in found:
                    raise ValueError(f"provider {provider!r} is defined twice in custom/")
                if not isinstance(getattr(adapter, "config_model", None), type):
                    raise ValueError(f"adapter {provider!r} has no config_model class")
                found[provider] = adapter
        except Exception as exc:  # a broken plugin must not stop the others, or the run
            errors[name] = f"{type(exc).__name__}: {exc}"[:200]
    _CACHE[key] = (found, errors)
    return found, errors
