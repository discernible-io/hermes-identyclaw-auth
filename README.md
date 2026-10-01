# IdentyClaw Auth (Hermes plugin)

Passport helpers for Hermes: **`hermes identyclaw …`** (Node `idcp`), agent tools,
bundled skill, and a **localhost RODiT auth sidecar** used by the A2A / signed-webhook
peer plugins.

Node stays plugin-owned (`package.json` → `npm ci` into this directory). Python only
orchestrates. Passport mint / NEAR / purchase portal are unchanged.

Peer plugins:

- [`hermes-identyclaw-a2a`](https://github.com/discernible-io/hermes-identyclaw-a2a) → plugin id `identyclaw-a2a`
- [`hermes-identyclaw-webhook`](https://github.com/discernible-io/hermes-identyclaw-webhook) → plugin id `identyclaw-webhooks`

## Prerequisites

- Stock Hermes Agent already installed (`hermes` on `PATH`)
- Node **≥ 22.19** and `npm` (and typically `libatomic.so.1` for RODiT)
- OpenClaw left **stopped** (do not run both peer stacks)

## Install

```bash
hermes plugins install discernible-io/hermes-identyclaw-auth   # Enable? y
hermes identyclaw install-deps                                # npm ci + NEAR account if missing
# Mint Passport at https://purchase.identyclaw.com — paste ONLY the printed account_id
hermes identyclaw me
```

`install-deps` creates **exactly one** NEAR implicit account under
`$HERMES_HOME/secrets/near-credentials/` when none is present and prints
`account_id` in a banner. Re-running is safe (does not overwrite / does not mint a second key).
Manual reprint: `hermes identyclaw enroll`.

**Purchase page:** paste only the `account_id` printed by `install-deps` or
`hermes identyclaw enroll`. Ignore other `*.json` files in that directory
(leftovers from prior installs); minting to the wrong key wastes the Passport.

Optional docs MCP: `hermes mcp add IdentyClawDocs --url https://api.identyclaw.com/mcp`

### Peer stack (A2A + signed `/hooks/*`)

```bash
hermes identyclaw sidecar start                               # 127.0.0.1:9910
# or: bash "$HERMES_HOME/plugins/identyclaw-auth/scripts/install-sidecar-unit.sh"

curl -fsS http://127.0.0.1:9910/health

hermes plugins install discernible-io/hermes-identyclaw-a2a    # Enable? y + tools.override
hermes plugins disable platforms/a2a                          # bundled A2A auto-loads
hermes plugins install discernible-io/hermes-identyclaw-webhook
```

`hermes plugins install` does **not** start a long-lived Node process by itself. Use
`hermes identyclaw sidecar start`, session-start autostart (`IDENTYCLAW_SIDECAR_AUTOSTART`,
default true), or the systemd user unit via `scripts/install-sidecar-unit.sh`.

### One-shot playbook

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
hermes plugins install discernible-io/hermes-identyclaw-auth --enable
bash "$HERMES_HOME/plugins/identyclaw-auth/scripts/install-stock-hermes.sh" \
  --a2a-public-url "https://YOUR.PUBLIC.HOST"
```

## CLI

| Command | Purpose |
|---------|---------|
| `hermes identyclaw enroll` | Secrets dirs + NEAR implicit account (also auto-run by install-deps) |
| `hermes identyclaw ensure_session [--force] [--base URL]` | Host login JWT (metadata only) |
| `hermes identyclaw me` | Passport identity |
| `hermes identyclaw list_sessions` | Cached hosts (no JWTs) |
| `hermes identyclaw request METHOD /api/path` | Bearer-injected API call |
| `hermes identyclaw create_hola` / `verify_hola` | HOLA handshake |
| `hermes identyclaw install-deps` | `npm ci` + auto-create NEAR account if missing |
| `hermes identyclaw sidecar start\|stop\|status\|ensure` | Sidecar lifecycle |

Direct Node entrypoints still work for debugging:

```bash
node bin/idcp.mjs enroll
NEAR_CREDENTIALS_FILE_PATH=/path/to/near.json node bin/sidecar.mjs --port 9910
```

## Sidecar routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness |
| GET | `/v1/own_passport` | `owner_id` / `token_id` / issuer from RoditClient |
| POST | `/v1/validate_jwt` | Passport JWT → `token_id` |
| POST | `/v1/login_server` | outbound peer login |
| POST | `/v1/authenticate_webhook` | Ed25519 webhook verify |
| GET/POST | `/api/login/timestamp`, `/api/login` | peer inbound login |

Binds **127.0.0.1** only. Never prints full JWTs from the CLI.

## Secrets / env

Layout under `$HERMES_HOME` (or `HERMES_APP_DIR` / `IDENTYCLAW_HOME`):

- `secrets/near-credentials/*.json` — NEAR key (from install-deps / enroll; keep one active)
- `secrets/near-credentials/.active` — basename of the live credentials file
- `secrets/identyclaw/jwt-*.txt` — cached host JWTs
- `NEAR_CREDENTIALS_FILE_PATH` — declared as `optional_env` (install may prompt; pins the live key)

Minimal `$HERMES_HOME/.env`:

```bash
HERMES_HOME=/home/you/.hermes
NEAR_CREDENTIALS_FILE_PATH=/home/you/.hermes/secrets/near-credentials/<account>.json
IDENTYCLAW_AUTH_PORT=9910
IDENTYCLAW_HOOKS_PORT=9911
A2A_PUBLIC_URL=https://your.public.host
A2A_PORT=9900
```

Inbound JWT `aud` resolves from `RoditClient.getConfigOwnRodit().own_rodit.owner_id`.
`IDENTYCLAW_JWT_AUDIENCE` is an optional fallback only when the passport cannot load.

## Skill

Shipped via `ctx.register_skill("identyclaw", …)` — load with
`skill_view("identyclaw-auth:identyclaw")`. No separate `hermes skills install`.

## Requirements

- Node.js `>=22.19.0` and `npm` on PATH (or `IDENTYCLAW_NODE_BIN`)
- Hermes Agent with plugins enabled
