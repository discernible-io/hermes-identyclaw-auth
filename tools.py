"""Tool handlers — shell out to the plugin-owned Node idcp / sidecar."""

from __future__ import annotations

import json
from typing import Any

try:
    from . import node_bridge
except ImportError:  # flat plugin-dir import
    import node_bridge  # type: ignore


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def identyclaw_enroll(args: dict, **kwargs) -> str:
    # quiet=True: agent tool returns JSON; human banner is for install-deps / CLI enroll.
    return _dumps(node_bridge.ensure_enrolled(quiet=True))


def identyclaw_ensure_session(args: dict, **kwargs) -> str:
    argv = ["ensure_session"]
    if args.get("force"):
        argv.append("--force")
    if args.get("base"):
        argv.extend(["--base", str(args["base"])])
    return _dumps(node_bridge.run_idcp(argv))


def identyclaw_me(args: dict, **kwargs) -> str:
    argv = ["me"]
    if args.get("base"):
        argv.extend(["--base", str(args["base"])])
    return _dumps(node_bridge.run_idcp(argv))


def identyclaw_list_sessions(args: dict, **kwargs) -> str:
    return _dumps(node_bridge.run_idcp(["list_sessions"]))


def identyclaw_request(args: dict, **kwargs) -> str:
    method = str(args.get("method") or "").strip()
    path = str(args.get("path") or "").strip()
    if not method or not path:
        return _dumps({"ok": False, "error": "method and path are required"})
    argv = ["request", method, path]
    if args.get("body"):
        argv.extend(["--body", str(args["body"])])
    if args.get("base"):
        argv.extend(["--base", str(args["base"])])
    return _dumps(node_bridge.run_idcp(argv))


def identyclaw_create_hola(args: dict, **kwargs) -> str:
    argv = ["create_hola"]
    if args.get("recipient"):
        argv.extend(["--recipient", str(args["recipient"])])
    if args.get("base"):
        argv.extend(["--base", str(args["base"])])
    return _dumps(node_bridge.run_idcp(argv))


def identyclaw_verify_hola(args: dict, **kwargs) -> str:
    hola = str(args.get("hola") or "").strip()
    if not hola:
        return _dumps({"ok": False, "error": "hola is required"})
    argv = ["verify_hola", "--hola", hola]
    if args.get("expected"):
        argv.extend(["--expected", str(args["expected"])])
    if args.get("base"):
        argv.extend(["--base", str(args["base"])])
    return _dumps(node_bridge.run_idcp(argv))


def identyclaw_sidecar_status(args: dict, **kwargs) -> str:
    if args.get("ensure"):
        return _dumps(node_bridge.ensure_sidecar_running())
    return _dumps(node_bridge.sidecar_status())
