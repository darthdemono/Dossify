"""The built-in sources, found by looking at the modules in this package.

A source module defines ``READERS`` (provider name to reader function), ``LABELS``
(footnote text per source) and ``TIER``:

* ``core``     - general: something many people have and that needs no private setup.
* ``optional`` - a bundled niche reader (a particular self-hosted service, one person's
  log format).  It is plug and play: nothing runs until ``[providers.<name>]`` exists in
  the configuration, exactly like a plugin you wrote yourself.

Every reader runs only when its ``[providers.<name>]`` block is present and not disabled.
The block's keys are handed to the module as ``_O`` just before its reader runs.
"""

from __future__ import annotations

import importlib
import pkgutil
import re

import dossify.sources as package


def modules():
    names = sorted(m.name for m in pkgutil.iter_modules(package.__path__) if not m.name.startswith("_") and m.name != "registry")
    return [importlib.import_module(f"dossify.sources.{name}") for name in names]


def readers() -> dict[str, tuple[object, object]]:
    """Provider name to (module, reader function)."""
    found: dict[str, tuple[object, object]] = {}
    for module in modules():
        for name, fn in getattr(module, "READERS", {}).items():
            found[name] = (module, fn)
    return found


def tiers() -> dict[str, str]:
    return {name: getattr(module, "TIER", "optional") for name, (module, _fn) in readers().items()}


def labels() -> dict[str, str]:
    out: dict[str, str] = {}
    for module in modules():
        out.update(getattr(module, "LABELS", {}))
    return out


def options_markdown() -> str:
    """docs/PROVIDERS.md, built from each module's own docstring so it cannot drift."""
    rows = ["| Provider | Tier | What it reads | Options |", "|---|---|---|---|"]
    for module in modules():
        doc = (module.__doc__ or "").strip()
        summary = doc.split("\n\n")[0].replace("\n", " ")
        options = re.search(r"Options?:\s*(.*)", doc, re.S)
        opts = " ".join(options.group(1).split()) if options else "none"
        for name in sorted(getattr(module, "READERS", {})):
            rows.append(f"| `{name}` | {getattr(module, 'TIER', 'optional')} | {summary} | {opts} |")
    return "\n".join(rows)
