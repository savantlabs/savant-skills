"""Folder-target conventions shared across the toolchain.

Kept in `contracts` (no live-API dependency) so both the API client (`savant_api`) and the pure
stage-gate validators can agree on how a folder target is expressed without the validators having
to import the API package.
"""
from __future__ import annotations

# Reserved `--folder-id` / `folder.id` values meaning "the Home folder" (the namespace root,
# as the user sees it in the app) rather than a real folder id. `home` is the canonical
# spelling; `root` is kept as a legacy alias. The import API represents the Home folder as a
# missing folderId. Real folder ids are generated tokens, so these literal aliases never
# collide with one.
ROOT_FOLDER_ALIASES = {"home", "root"}


def is_root_folder_target(value: str | None) -> bool:
    """True when a folder-target value means the Home folder (namespace root)."""
    return (value or "").strip().lower() in ROOT_FOLDER_ALIASES
