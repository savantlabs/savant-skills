"""Public facade for Savant workflow node builders.

Use this module as the stable import surface:

    from workflow import builders as nb

The implementation lives in ``workflow._builders_impl`` so builder agents and
humans do not need to read a large implementation file to discover the public
API. Prefer ``references/standards/node-builders-api.md`` and the
builder cookbook before opening the implementation.
"""

from __future__ import annotations

from typing import Any

try:  # Package import, e.g. ``from workflow import builders``.
    from . import _builders_impl as _impl
except ImportError:  # Direct module import when this folder is on sys.path.
    import _builders_impl as _impl  # type: ignore

__all__ = list(_impl.__all__)

globals().update({name: getattr(_impl, name) for name in __all__})


def __getattr__(name: str) -> Any:
    """Forward uncommon/private implementation lookups for compatibility."""

    return getattr(_impl, name)


def __dir__() -> list[str]:
    return sorted(set(__all__) | set(dir(_impl)))
