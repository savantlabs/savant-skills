#!/usr/bin/env python3
"""Consolidated command router for Savant helper scripts.

Implementation lives in packages such as `savant_api`, `workflow`, `validators`,
and `handoff`. This command is the stable CLI surface.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import threading
import time
from contextlib import redirect_stderr, redirect_stdout
from importlib import import_module
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


ROUTES: dict[tuple[str, ...], tuple[str, str]] = {
    ("capabilities",): ("savant_api.capabilities", "Report package capabilities + probe API availability"),
    ("api",): ("savant_api.cli", "Authenticated app API passthrough"),
    ("app",): ("savant_api.cli", "Authenticated app API passthrough"),
    ("dataset", "create"): ("savant_api.datasets", "Create a dataset from a local file"),
    ("dataset", "discover"): ("workflow.discovery", "Match workflow sources to visible datasets"),
    ("dataset", "download"): ("savant_api.dataset_download", "Download uploaded files behind datasets"),
    ("source", "profile"): ("workflow.source_profile", "Profile local CSV/Excel/PDF sources and likely joins"),
    ("preview", "nodes"): ("workflow.previews", "Read or analyze node preview output"),
    ("workflow", "create"): ("workflow.create", "Import a workflow JSON and verify it"),
    ("workflow", "edit"): ("workflow.edit", "Save an edited recipe in place and verify it"),
    ("workflow", "inspect"): ("workflow.inspection", "Inspect a live workflow after import"),
    ("workflow", "health"): ("workflow.health", "Run read-only workflow health checks"),
    ("workflow", "map"): ("workflow.map", "Build a compact workflow map"),
    ("workflow", "polish"): ("workflow.polish", "Apply shared workflow JSON layout/color polish"),
    ("workflow", "targets"): ("workflow.targets", "Suggest validation checkpoints"),
    ("usage", "admin"): ("savant_api.admin_usage", "Read admin usage data"),
    ("session",): ("savant_api.fileio", "Resolve AI session id and session-scoped tmp paths"),
    ("registry", "summary"): ("registry.print_summary", "Print registry summary"),
    ("docs", "builder-pack"): ("docs.builder_pack", "Compact Builder packet for one or more component types"),
    ("docs", "handoff-pack"): ("docs.handoff_pack", "Compact Planner-to-Builder handoff contract"),
    ("handoff",): ("handoff", "Create or validate stage handoff envelopes"),
    ("validate", "workflow"): ("validators.workflow", "Validate workflow JSON"),
    ("validate", "stage"): ("validators.stage_gate", "Validate role/stage precheck or done evidence"),
}

API_REQUIRED_ROUTES = {
    ("api",),
    ("app",),
    ("dataset", "create"),
    ("dataset", "download"),
    ("preview", "nodes"),
    ("workflow", "create"),
    ("workflow", "edit"),
    ("workflow", "inspect"),
    ("workflow", "health"),
    ("workflow", "map"),
    ("workflow", "targets"),
    ("usage", "admin"),
}


def _usage() -> str:
    lines = [
        "usage: savant.py <command> [args...]",
        "",
        "Commands:",
    ]
    width = max(len(" ".join(route)) for route in ROUTES)
    for route, (_module, description) in sorted(ROUTES.items()):
        label = " ".join(route)
        lines.append(f"  {label:<{width}}  {description}")
    lines.append(f"  {'serve':<{width}}  Persistent warm process: JSON-lines requests on stdin, dispatched through the router")
    lines.extend(
        [
            "",
            "Examples:",
            "  savant.py app --import-json workflow.json --folder-id <folderId>",
            "  savant.py dataset create --file data.csv --name Data",
            "  savant.py dataset discover --workflow-json workflow.json --sources-json sources.json",
            "  savant.py dataset download <flow-url> --output-dir tmp/source-download",
            "  savant.py preview nodes <flow-url> --node-id source_a",
            "  savant.py validate workflow workflow.json",
        ]
    )
    return "\n".join(lines)


def _resolve(argv: list[str]) -> tuple[tuple[str, ...], str, list[str]]:
    for width in (2, 1):
        route = tuple(argv[:width])
        if route in ROUTES:
            return route, ROUTES[route][0], argv[width:]
    raise SystemExit(_usage())


def _call_module_main(module_name: str, args: list[str]) -> int:
    try:
        module = import_module(module_name)
    except (ModuleNotFoundError, ImportError) as exc:
        print(
            f"`{module_name}` is not available in this Savant package. "
            "This command requires a package that ships the live Savant API.",
            file=sys.stderr,
        )
        if str(exc):
            print(f"Import error: {exc}", file=sys.stderr)
        return 2
    main = getattr(module, "main", None)
    if main is None:
        raise SystemExit(f"`{module_name}` does not expose main().")
    original_argv = sys.argv
    sys.argv = [" ".join(original_argv[:1] + args[:0])] + args
    try:
        result = main()
    finally:
        sys.argv = original_argv
    return int(result or 0)


def _api_enabled() -> tuple[bool, dict]:
    try:
        capabilities = import_module("savant_api.capabilities")
        result = capabilities.detect()
    except Exception as exc:  # noqa: BLE001
        return False, {"api_enabled": False, "reason": f"{type(exc).__name__}: {exc}"}
    return bool(result.get("api_enabled")), result


def _dispatch_once(args: list[str]) -> int:
    """Resolve one command line through the router and run it. Shared by the
    normal one-shot path and the persistent `serve` loop."""
    route, module_name, remaining = _resolve(args)
    if route in API_REQUIRED_ROUTES:
        enabled, capability = _api_enabled()
        if not enabled:
            reason = capability.get("reason") or capability.get("detail") or "API is not available in this package/session."
            print(
                "Savant API is not enabled for this package/session. "
                f"mode={capability.get('mode', 'manual')}; reason={reason}",
                file=sys.stderr,
            )
            return 2
    return _call_module_main(module_name, remaining)


def _default_idle_timeout() -> float:
    try:
        return float(os.environ.get("SAVANT_SERVE_IDLE_TIMEOUT", "600"))
    except (TypeError, ValueError):
        return 600.0


def _serve(serve_args: list[str] | None = None) -> int:
    """Persistent warm-process mode. Reads one JSON request per line on stdin and
    writes one JSON response per line on stdout, dispatching each through the same
    router as the one-shot CLI.

    This is runtime-agnostic: any caller that can spawn a process and write to its
    stdin can drive it (Cowork via Desktop Commander's interact_with_process; Codex
    or a native shell by piping directly). It touches no host-execution bridge.

    The win: the interpreter, imports, and — via the in-process session cache — the
    browser-session discovery are paid once on the first command instead of on every
    call. Send the capability probe first to warm the session.

    Request:  {"id": <any, optional>, "argv": ["app", "--list-ai-providers"]}
              (a bare JSON array is also accepted as argv)
    Response: {"id": <echoed>, "ok": <bool>, "exit_code": <int>,
               "stdout": <str>, "stderr": <str>}
    Send {"argv": ["__quit__"]} (or "quit"/"exit") to stop the loop.

    Idle self-shutdown: with no command for `--idle-timeout` seconds (default 600;
    env `SAVANT_SERVE_IDLE_TIMEOUT`; 0 or negative disables) the process exits on its
    own so abandoned warm processes don't accumulate across sessions. The timer only
    counts idle time *between* commands — a long-running command is never interrupted.
    """
    parser = argparse.ArgumentParser(prog="savant.py serve", add_help=True)
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=_default_idle_timeout(),
        metavar="SECONDS",
        help="Exit after this many idle seconds with no command (default 600; 0 disables).",
    )
    opts = parser.parse_args(serve_args or [])
    idle_timeout = opts.idle_timeout

    out = sys.stdout
    emit_lock = threading.Lock()

    def emit(obj: dict) -> None:
        with emit_lock:
            out.write(json.dumps(obj) + "\n")
            out.flush()

    # Idle watchdog. A blocking stdin read can't time out portably (select() does
    # not work on pipes on Windows), so a daemon thread watches a last-activity clock
    # and ends the whole process via os._exit when idle exceeds the limit. `busy`
    # guards an in-flight command so a slow API call is never killed mid-request.
    state = {"last": time.monotonic(), "busy": False}
    state_lock = threading.Lock()

    def touch(busy: bool) -> None:
        with state_lock:
            state["busy"] = busy
            state["last"] = time.monotonic()

    if idle_timeout and idle_timeout > 0:
        poll = max(0.05, min(idle_timeout / 2.0, 5.0))

        def _watchdog() -> None:
            while True:
                time.sleep(poll)
                with state_lock:
                    idle = (not state["busy"]) and (time.monotonic() - state["last"]) >= idle_timeout
                if idle:
                    emit({"event": "idle_shutdown", "idle_timeout_s": idle_timeout})
                    sys.stderr.flush()
                    os._exit(0)

        threading.Thread(target=_watchdog, name="savant-serve-idle", daemon=True).start()

    emit({"event": "ready", "pid": os.getpid(), "idle_timeout_s": idle_timeout if idle_timeout > 0 else None})
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        touch(True)  # mark active the moment input arrives, before any work
        try:
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                emit({"id": None, "ok": False, "exit_code": 2, "stdout": "", "stderr": f"invalid JSON request: {exc}"})
                continue
            if isinstance(req, list):
                req = {"argv": req}
            if not isinstance(req, dict):
                emit({"id": None, "ok": False, "exit_code": 2, "stdout": "", "stderr": "request must be a JSON object or array"})
                continue
            req_id = req.get("id")
            argv = req.get("argv")
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                emit({"id": req_id, "ok": False, "exit_code": 2, "stdout": "", "stderr": "request must include 'argv' as a list of strings"})
                continue
            if argv and argv[0] in {"__quit__", "quit", "exit"}:
                emit({"id": req_id, "ok": True, "exit_code": 0, "stdout": "", "stderr": "", "bye": True})
                return 0
            if argv and argv[0] == "serve":
                emit({"id": req_id, "ok": False, "exit_code": 2, "stdout": "", "stderr": "serve cannot be nested"})
                continue
            cap_out, cap_err = io.StringIO(), io.StringIO()
            exit_code = 0
            try:
                with redirect_stdout(cap_out), redirect_stderr(cap_err):
                    exit_code = _dispatch_once(argv)
            except SystemExit as exc:  # argparse / _resolve raise this on bad input
                code = exc.code
                if isinstance(code, int):
                    exit_code = code
                elif code is None:
                    exit_code = 0
                else:
                    cap_err.write(str(code))
                    exit_code = 2
            except Exception as exc:  # one bad command must not kill the warm process
                exit_code = 1
                cap_err.write(f"{type(exc).__name__}: {exc}")
            emit({
                "id": req_id,
                "ok": exit_code == 0,
                "exit_code": exit_code,
                "stdout": cap_out.getvalue(),
                "stderr": cap_err.getvalue(),
            })
        finally:
            touch(False)  # back to idle; restart the clock
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help", "help"}:
        print(_usage())
        return 0
    if args[0] == "help":
        args = args[1:]
        if not args:
            print(_usage())
            return 0
    if args[0] == "serve":
        return _serve(args[1:])
    return _dispatch_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
