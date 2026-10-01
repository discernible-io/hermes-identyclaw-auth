"""CLI for ``hermes identyclaw …`` — wraps the Node idcp + sidecar lifecycle."""

from __future__ import annotations

import json
import sys
from typing import Any

try:
    from . import node_bridge
except ImportError:  # flat plugin-dir import
    import node_bridge  # type: ignore


def _print(payload: Any) -> int:
    if isinstance(payload, dict):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if payload.get("ok", True) else 1
    print(payload)
    return 0


def _setup_argparse(subparser) -> None:
    subs = subparser.add_subparsers(dest="identyclaw_cmd")

    subs.add_parser(
        "enroll",
        help="Create secrets layout + NEAR implicit account (also run automatically by install-deps)",
    )

    p_ensure = subs.add_parser("ensure_session", help="Mint/refresh host login JWT (metadata only)")
    p_ensure.add_argument("--force", action="store_true")
    p_ensure.add_argument("--base", default=None, help="API base URL")
    p_ensure.add_argument("--credentials", default=None, help="NEAR credentials JSON path")

    p_me = subs.add_parser("me", help="Show Passport identity for the active session")
    p_me.add_argument("--base", default=None)

    subs.add_parser("list_sessions", help="List cached sessions (no JWTs)")

    p_req = subs.add_parser("request", help="Authenticated API request via idcp")
    p_req.add_argument("method")
    p_req.add_argument("path")
    p_req.add_argument("--body", default=None)
    p_req.add_argument("--base", default=None)

    p_ch = subs.add_parser("create_hola", help="Create a HOLA handshake line")
    p_ch.add_argument("--recipient", default=None)
    p_ch.add_argument("--base", default=None)
    p_ch.add_argument("--credentials", default=None)

    p_vh = subs.add_parser("verify_hola", help="Verify an inbound HOLA line")
    p_vh.add_argument("--hola", required=True)
    p_vh.add_argument("--expected", default=None)
    p_vh.add_argument("--base", default=None)

    subs.add_parser(
        "install-deps",
        help=(
            "npm ci into this plugin's node_modules, then create a NEAR implicit "
            "account if none is present"
        ),
    )

    p_sc = subs.add_parser("sidecar", help="Manage the localhost RODiT auth sidecar")
    sc_subs = p_sc.add_subparsers(dest="sidecar_cmd")
    sc_subs.add_parser("start", help="Start sidecar on IDENTYCLAW_AUTH_PORT (default 9910)")
    sc_subs.add_parser("stop", help="Stop sidecar via pidfile")
    sc_subs.add_parser("status", help="Health + pidfile status")
    sc_subs.add_parser("ensure", help="Start only if /health is down (respects AUTOSTART)")

    subs.add_parser("status", help="Alias for sidecar status + deps state")


def _handle(args) -> None:
    cmd = getattr(args, "identyclaw_cmd", None)
    if not cmd:
        print(
            "Usage: hermes identyclaw <enroll|ensure_session|me|list_sessions|request|"
            "create_hola|verify_hola|install-deps|sidecar|status> …",
            file=sys.stderr,
        )
        sys.exit(2)

    if cmd == "install-deps":
        code = node_bridge.install_node_deps()
        if code != 0:
            _print({"ok": False, "error": "npm install failed", "root": str(node_bridge.PLUGIN_ROOT)})
            sys.exit(code)
        enroll = node_bridge.ensure_enrolled()
        account_id = enroll.get("account_id") if isinstance(enroll, dict) else None
        _print(
            {
                "ok": True,
                "deps_installed": node_bridge.deps_installed(),
                "root": str(node_bridge.PLUGIN_ROOT),
                "enroll": enroll,
                "account_id": account_id,
                "purchase": "https://purchase.identyclaw.com",
                "next_human": (
                    "Paste account_id at https://purchase.identyclaw.com, then: "
                    "hermes identyclaw ensure_session && hermes identyclaw me"
                ),
            }
        )
        # npm deps are the hard requirement; enroll is best-effort (idempotent).
        sys.exit(0)

    if cmd == "status":
        payload = node_bridge.sidecar_status()
        payload["plugin_root"] = str(node_bridge.PLUGIN_ROOT)
        payload["idcp"] = str(node_bridge.IDCP_SCRIPT)
        sys.exit(_print(payload))

    if cmd == "sidecar":
        sc = getattr(args, "sidecar_cmd", None)
        if sc == "start":
            sys.exit(_print(node_bridge.start_sidecar()))
        if sc == "stop":
            sys.exit(_print(node_bridge.stop_sidecar()))
        if sc == "ensure":
            sys.exit(_print(node_bridge.ensure_sidecar_running()))
        if sc == "status" or sc is None:
            sys.exit(_print(node_bridge.sidecar_status()))
        print("Usage: hermes identyclaw sidecar <start|stop|status|ensure>", file=sys.stderr)
        sys.exit(2)

    argv: list[str] = [cmd]
    if cmd == "ensure_session":
        if getattr(args, "force", False):
            argv.append("--force")
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
        if getattr(args, "credentials", None):
            argv.extend(["--credentials", args.credentials])
    elif cmd == "me":
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
    elif cmd == "request":
        argv.extend([args.method, args.path])
        if getattr(args, "body", None):
            argv.extend(["--body", args.body])
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
    elif cmd == "create_hola":
        if getattr(args, "recipient", None):
            argv.extend(["--recipient", args.recipient])
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
        if getattr(args, "credentials", None):
            argv.extend(["--credentials", args.credentials])
    elif cmd == "verify_hola":
        argv.extend(["--hola", args.hola])
        if getattr(args, "expected", None):
            argv.extend(["--expected", args.expected])
        if getattr(args, "base", None):
            argv.extend(["--base", args.base])
    elif cmd in {"enroll", "list_sessions"}:
        pass
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)

    sys.exit(_print(node_bridge.run_idcp(argv)))
