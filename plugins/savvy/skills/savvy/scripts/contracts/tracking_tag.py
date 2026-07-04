"""Single source of truth for the Savvy workflow tracking tag.

Every flow Savvy creates or edits carries one tracking tag recording the Savvy version
that last touched it, e.g. ``Savvy v0.0.1``. The version is read from the skill's
``references/capabilities.json`` (``savvy_version``) so a release bump updates the tag in
one place. Builders default the flow tag to ``tracking_tag()`` and validation enforces it,
so the version is never left to agent judgment.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TAG_PREFIX = "Savvy"


def _read_version() -> str | None:
    """Read ``savvy_version`` from ``references/capabilities.json`` (same upward walk
    capabilities.py uses, so it resolves in both the source tree and a shipped package)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "references" / "capabilities.json"
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            version = data.get("savvy_version") if isinstance(data, dict) else None
            return version if isinstance(version, str) and version.strip() else None
    return None


def savvy_version() -> str | None:
    """The canonical Savvy version string (e.g. ``v0.0.1``), or None if unresolvable."""
    return _read_version()


def tracking_tag() -> str:
    """The canonical tracking tag, e.g. ``Savvy v0.0.1``.

    Falls back to bare ``Savvy`` only when the version file is missing/unreadable, so a
    flow always carries at least the family tag even in a degraded environment.
    """
    version = _read_version()
    return f"{TAG_PREFIX} {version}" if version else TAG_PREFIX


def is_savvy_tracking_tag(tag: Any) -> bool:
    """A Savvy-family tracking tag: bare ``Savvy`` or ``Savvy {version}``."""
    return isinstance(tag, str) and (tag == TAG_PREFIX or tag.startswith(TAG_PREFIX + " "))


def is_versioned_tracking_tag(tag: Any) -> bool:
    """A Savvy tracking tag carrying a non-empty version suffix (``Savvy {version}``)."""
    return (
        isinstance(tag, str)
        and tag.startswith(TAG_PREFIX + " ")
        and bool(tag[len(TAG_PREFIX) + 1:].strip())
    )
