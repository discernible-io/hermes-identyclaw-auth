"""IdentyClaw auth — Hermes plugin shell around the Node idcp + RODiT sidecar."""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["register"]


def register(ctx) -> None:
    """Register tools, CLI, skill, and optional session-start sidecar ensure."""
    try:
        from . import schemas, tools
        from .cli import _handle, _setup_argparse
    except ImportError:
        # Flat import fallback when the plugin dir is on sys.path without package context.
        import schemas  # type: ignore
        import tools  # type: ignore
        from cli import _handle, _setup_argparse  # type: ignore

    toolset = "identyclaw-auth"
    registrations = (
        ("identyclaw_enroll", schemas.ENROLL, tools.identyclaw_enroll),
        ("identyclaw_ensure_session", schemas.ENSURE_SESSION, tools.identyclaw_ensure_session),
        ("identyclaw_me", schemas.ME, tools.identyclaw_me),
        ("identyclaw_list_sessions", schemas.LIST_SESSIONS, tools.identyclaw_list_sessions),
        ("identyclaw_request", schemas.REQUEST, tools.identyclaw_request),
        ("identyclaw_create_hola", schemas.CREATE_HOLA, tools.identyclaw_create_hola),
        ("identyclaw_verify_hola", schemas.VERIFY_HOLA, tools.identyclaw_verify_hola),
        ("identyclaw_sidecar_status", schemas.SIDECAR_STATUS, tools.identyclaw_sidecar_status),
    )
    for name, schema, handler in registrations:
        try:
            ctx.register_tool(name=name, toolset=toolset, schema=schema, handler=handler)
        except Exception:
            logger.warning("identyclaw-auth: failed to register tool %s", name, exc_info=True)

    try:
        ctx.register_cli_command(
            name="identyclaw",
            help="IdentyClaw Passport auth (enroll, session, HOLA, sidecar)",
            setup_fn=_setup_argparse,
            handler_fn=_handle,
            description=(
                "Host-login helpers and localhost RODiT sidecar for IdentyClaw Passport. "
                "Node binary lives inside this plugin; run `hermes identyclaw install-deps` after install."
            ),
        )
    except Exception:
        logger.warning("identyclaw-auth: failed to register CLI", exc_info=True)

    skill_md = Path(__file__).resolve().parent / "skills" / "identyclaw" / "SKILL.md"
    if skill_md.is_file():
        try:
            ctx.register_skill("identyclaw", skill_md)
        except Exception:
            logger.warning("identyclaw-auth: failed to register skill", exc_info=True)
    else:
        logger.warning("identyclaw-auth: skill missing at %s", skill_md)

    def _on_session_start(**kwargs):
        """Best-effort sidecar ensure for gateway/chat sessions (peer stack)."""
        try:
            from . import node_bridge
        except ImportError:
            import node_bridge  # type: ignore
        if not node_bridge.sidecar_autostart_enabled():
            return
        if node_bridge.sidecar_health():
            return
        # Only auto-start when NEAR credentials are present — otherwise peer stack isn't ready.
        if not node_bridge.ensure_near_credentials_env():
            return
        result = node_bridge.ensure_sidecar_running()
        if not result.get("ok"):
            logger.info(
                "identyclaw-auth: sidecar not started on session start: %s",
                result.get("error") or result,
            )

    try:
        ctx.register_hook("on_session_start", _on_session_start)
    except Exception:
        logger.debug("identyclaw-auth: on_session_start hook not available", exc_info=True)
