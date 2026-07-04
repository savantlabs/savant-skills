"""Folder-target conventions shared across the toolchain.

Kept in `contracts` (no live-API dependency) so both the API client (`savant_api`) and the pure
stage-gate validators can agree on how a folder target is expressed without the validators having
to import the API package.
"""
from __future__ import annotations

# Reserved `--folder-id` / `folder.id` values meaning "the namespace root (Home)" rather than a
# real folder id. The import API represents root as a missing folderId. Real folder ids are
# generated tokens, so these literal aliases never collide with one.
ROOT_FOLDER_ALIASES = {"root", "home"}


def is_root_folder_target(value: str | None) -> bool:
    """True when a folder-target value means the namespace root (Home)."""
    return (value or "").strip().lower() in ROOT_FOLDER_ALIASES
