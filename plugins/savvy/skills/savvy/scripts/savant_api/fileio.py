from __future__ import annotations

import json
import os
import re
import sys
import argparse
import stat
import tempfile
from pathlib import Path
from typing import Any


def save_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")


SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validate_session_id(value: str, source: str) -> str:
    session_id = value.strip()
    if not session_id:
        raise RuntimeError(f"{source} is set but empty.")
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise RuntimeError(
            f"{source} must be a safe single path segment: letters, numbers, dot, underscore, or hyphen."
        )
    return session_id


def _claude_session_from_path(value: str | None) -> str | None:
    if not value:
        return None
    parts = Path(value).parts
    for index, part in enumerate(parts[:-1]):
        if part == "sessions" and index + 1 < len(parts):
            return parts[index + 1]
    return None


def ai_session_id(environ: dict[str, str] | None = None) -> str:
    """Return the current AI conversation/session id, or fail fast.

    ``SAVANT_AI_SESSION_ID`` is the generic runtime contract. Runtime-derived ids
    are accepted only when exposed by the host: Codex provides ``CODEX_THREAD_ID``;
    Claude Code provides ``CLAUDE_CODE_SESSION_ID``; Claude Cowork exposes a
    per-session ``/sessions/<id>`` home/tmp path. Resolving the id natively per
    runtime is what lets the chat client and the savant.py shell agree on the
    creds-file path without the model setting anything by hand.
    """
    env = os.environ if environ is None else environ
    explicit = env.get("SAVANT_AI_SESSION_ID")
    if explicit is not None:
        return _validate_session_id(explicit, "SAVANT_AI_SESSION_ID")
    codex = env.get("CODEX_THREAD_ID")
    if codex is not None:
        return _validate_session_id(codex, "CODEX_THREAD_ID")
    claude = env.get("CLAUDE_CODE_SESSION_ID")
    if claude is not None:
        return _validate_session_id(claude, "CLAUDE_CODE_SESSION_ID")
    for key in ("CLAUDE_TMPDIR", "CLAUDE_CODE_TMPDIR", "HOME"):
        session_id = _claude_session_from_path(env.get(key))
        if session_id is not None:
            return _validate_session_id(session_id, key)
    raise RuntimeError(
        "AI session id unavailable. Set SAVANT_AI_SESSION_ID for this AI session "
        "or run in a supported runtime that exposes CLAUDE_CODE_SESSION_ID, "
        "CODEX_THREAD_ID, or /sessions/<id>."
    )


CAPABILITIES_REL = Path("references") / "capabilities.json"


def workspace_root(start: Path | None = None) -> Path:
    """Return the skill root — the directory that holds ``scripts/`` and ``references/``.

    Used to LOCATE the shipped ``references/capabilities.json`` (the API capability gate
    flag), relative to this script's own location — works whether running from a source
    tree or an installed plugin dir. It is NOT a place to write output; see ``workspace_tmp``.
    """
    here = Path(__file__).resolve() if start is None else Path(start).resolve()
    # Anchor on the dir whose references/capabilities.json exists; fallback savant_api -> scripts -> <root>.
    return next((p for p in here.parents if (p / CAPABILITIES_REL).exists()), here.parents[2])


def session_tmp_root() -> Path:
    """Per-session scratch root in system temp: ``<temp>/savant/<ai-session-id>``.

    NOT anchored to the script or the cwd. A shipped plugin lives in a read-only install
    dir, and the user's working directory is an unrelated project — neither is a valid
    place to write runtime scratch or a bearer-token creds file. System temp is writable
    everywhere and OS-reaped.

    Prefer ``$XDG_RUNTIME_DIR`` when present (a user-private ``0700`` tmpfs on Linux, the
    right home for short-lived secrets); otherwise fall back to ``tempfile.gettempdir()``.
    Keyed by ``ai_session_id()`` so the chat client (which writes the creds file) and the
    savant.py shell (which reads it) derive the SAME path with no coordination.
    """
    base = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
    return Path(base).joinpath("savant", ai_session_id())


def workspace_tmp(*parts: str) -> Path:
    """Absolute ``<session-tmp-root>/<parts...>`` — the single resolver every helper uses to
    place its output. Deterministic and identical across runtimes (Cowork, Codex, Claude
    Code) because it is keyed by the AI session id, not by cwd or the install location."""
    return session_tmp_root().joinpath(*parts)


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _load_capabilities(root: Path) -> dict[str, Any]:
    return json.loads((root / CAPABILITIES_REL).read_text(encoding="utf-8"))


def _remove_write_bits(path: Path) -> bool:
    if path.is_symlink():
        return False
    current = path.stat().st_mode
    desired = current & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    if desired == current:
        return False
    path.chmod(desired)
    return True


def lock_package_for_session(
    *,
    root: Path | None = None,
    dry_run: bool = False,
    allow_internal: bool = False,
) -> dict[str, Any]:
    """Prepare a shipped package for a session: tmp writable, shipped source read-only.

    This is a startup guardrail. It is strongest when the package is mounted read-only or
    owned by a different OS user; when the agent owns the files, it can still deliberately
    chmod them back.
    """
    package_root = workspace_root() if root is None else Path(root).resolve()
    capabilities = _load_capabilities(package_root)
    api_supported = bool(capabilities.get("api_supported"))
    if api_supported and not allow_internal:
        raise RuntimeError(
            "Refusing to lock an API-enabled package. Use --allow-internal only when "
            "intentionally testing this guard outside an API-less package."
        )

    session_id = ai_session_id()
    tmp_root = package_root / "tmp"
    session_tmp = tmp_root / session_id

    locked = 0
    checked = 0
    skipped = 0
    if not dry_run:
        session_tmp.mkdir(parents=True, exist_ok=True)
        tmp_root.chmod(tmp_root.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRUSR)
        session_tmp.chmod(session_tmp.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR | stat.S_IRUSR)
        probe = session_tmp / ".write-probe"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()

    tmp_resolved = tmp_root.resolve() if tmp_root.exists() else tmp_root
    for path in sorted(package_root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        checked += 1
        try:
            resolved = path.resolve()
        except OSError:
            skipped += 1
            continue
        if path == tmp_root or _path_is_relative_to(resolved, tmp_resolved):
            skipped += 1
            continue
        if path.is_symlink():
            skipped += 1
            continue
        if dry_run:
            if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                locked += 1
        elif _remove_write_bits(path):
            locked += 1

    if not dry_run:
        _remove_write_bits(package_root)

    return {
        "ok": True,
        "root": str(package_root),
        "session_id": session_id,
        "tmp": str(session_tmp),
        "dry_run": dry_run,
        "api_supported": api_supported,
        "checked_paths": checked,
        "locked_paths": locked,
        "skipped_paths": skipped,
        "note": (
            "Source files were made read-only and session tmp was verified writable. "
            "For hard enforcement, combine this with read-only mounts or non-agent ownership."
        ),
    }


def _exports_dir() -> Path:
    """Absolute ``<workspace-root>/tmp/<ai-session-id>/savant-api-exports`` (see :func:`workspace_tmp`)."""
    return workspace_tmp("savant-api-exports")


def _default_output_path(flow_id: str) -> Path:
    return _exports_dir() / f"{flow_id}.json"


def _default_executions_output_path(flow_id: str) -> Path:
    return _exports_dir() / f"{flow_id}.executions.json"


def _default_import_output_path(json_path: Path) -> Path:
    return _exports_dir() / f"{json_path.stem}.import.json"


def _default_save_report_path(flow_id: str) -> Path:
    return _exports_dir() / f"{flow_id}.save-report.json"


def _default_execution_detail_output_path(execution_id: str) -> Path:
    return _exports_dir() / f"{execution_id}.execution.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve AI-session-scoped Savant helper paths.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("id", help="Print the resolved AI session id.")
    p_tmp = sub.add_parser("tmp-path", help="Print an absolute path under tmp/<ai-session-id>/.")
    p_tmp.add_argument("parts", nargs="*", help="Path segments under the session tmp directory.")
    p_lock = sub.add_parser(
        "lock-package",
        help="Customer-session startup guard: make package source read-only and verify session tmp is writable.",
    )
    p_lock.add_argument("--dry-run", action="store_true", help="Report what would be locked without changing modes.")
    p_lock.add_argument(
        "--allow-internal",
        action="store_true",
        help="Allow locking an API-enabled/internal package. Intended only for explicit testing.",
    )
    p_lock.add_argument("--json", action="store_true", help="Print the guard report as JSON.")

    args = parser.parse_args(argv)
    try:
        if args.command == "id":
            print(ai_session_id())
            return 0
        if args.command == "tmp-path":
            print(workspace_tmp(*args.parts))
            return 0
        if args.command == "lock-package":
            report = lock_package_for_session(dry_run=args.dry_run, allow_internal=args.allow_internal)
            if args.json:
                print(json.dumps(report, indent=2))
            else:
                action = "Would lock" if args.dry_run else "Locked"
                print(
                    f"{action} {report['locked_paths']} package paths read-only; "
                    f"session tmp writable at {report['tmp']}"
                )
            return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
