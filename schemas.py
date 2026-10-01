"""Tool schemas — what the LLM sees for IdentyClaw auth ops."""

from __future__ import annotations

ENROLL = {
    "name": "identyclaw_enroll",
    "description": (
        "Create IdentyClaw secrets layout under $HERMES_HOME/secrets and ensure a "
        "NEAR implicit account exists for Passport minting. Returns account_id and "
        "next human step (purchase portal). Never invent credentials."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

ENSURE_SESSION = {
    "name": "identyclaw_ensure_session",
    "description": (
        "Obtain or refresh an IdentyClaw host-login JWT session for an API base URL. "
        "Returns metadata only (ok, tokenId, jwt_length) — never the full JWT."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force": {
                "type": "boolean",
                "description": "Force remint even if a cached session exists",
            },
            "base": {
                "type": "string",
                "description": "API base URL (default https://api.identyclaw.com)",
            },
        },
        "required": [],
    },
}

ME = {
    "name": "identyclaw_me",
    "description": (
        "Return the current Passport identity for the active IdentyClaw session "
        "(token_id / account metadata). Requires a prior ensure_session."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "base": {
                "type": "string",
                "description": "API base URL (default https://api.identyclaw.com)",
            },
        },
        "required": [],
    },
}

LIST_SESSIONS = {
    "name": "identyclaw_list_sessions",
    "description": (
        "List cached IdentyClaw API sessions (hosts + metadata). Never returns JWTs."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

REQUEST = {
    "name": "identyclaw_request",
    "description": (
        "Call an IdentyClaw API path with the host-injected Bearer session. "
        "Prefer this over inventing Authorization headers or pasting JWTs."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "description": "HTTP method (GET, POST, PUT, DELETE, …)",
            },
            "path": {
                "type": "string",
                "description": "API path beginning with / (e.g. /api/agents)",
            },
            "body": {
                "type": "string",
                "description": "Optional JSON body string for POST/PUT",
            },
            "base": {
                "type": "string",
                "description": "API base URL override",
            },
        },
        "required": ["method", "path"],
    },
}

CREATE_HOLA = {
    "name": "identyclaw_create_hola",
    "description": (
        "Create a HOLA peer-handshake line for MUNDO or a peer token_id. "
        "Use after a verified inbound HOLA on the same channel."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "recipient": {
                "type": "string",
                "description": "MUNDO or peer token_id (default MUNDO)",
            },
            "base": {
                "type": "string",
                "description": "API base URL override",
            },
        },
        "required": [],
    },
}

VERIFY_HOLA = {
    "name": "identyclaw_verify_hola",
    "description": (
        "Verify an inbound HOLA line. On verified:true, immediately create_hola "
        "and reply on the same channel."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "hola": {
                "type": "string",
                "description": "Full HOLA/… line to verify",
            },
            "expected": {
                "type": "string",
                "description": "Expected recipient (default MUNDO)",
            },
            "base": {
                "type": "string",
                "description": "API base URL override",
            },
        },
        "required": ["hola"],
    },
}

SIDECAR_STATUS = {
    "name": "identyclaw_sidecar_status",
    "description": (
        "Check whether the localhost IdentyClaw auth sidecar (default :9910) is "
        "healthy. Peer A2A/webhooks require this process."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "ensure": {
                "type": "boolean",
                "description": "If true and autostart is enabled, start the sidecar when down",
            },
        },
        "required": [],
    },
}
