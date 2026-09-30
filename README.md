# @identyclaw/hermes-identyclaw-auth

**Host package** (not a Hermes plugin): IdentyClaw Passport helpers for stock Hermes —
the **`idcp` CLI** (host login / HOLA) plus a **localhost auth sidecar** wrapping
`@rodit/rodit-auth-be`, and the **`identyclaw` skill**.

There is no `plugin.yaml`. Do **not** run `hermes plugins install` on this repo.
Install with npm + symlink (or the stock playbook below), then install the skill.

Peer A2A / RODiT webhooks are separate Hermes plugins:

- [`hermes-identyclaw-a2a`](https://github.com/discernible-io/hermes-identyclaw-a2a) → plugin id `identyclaw-a2a`
- [`hermes-identyclaw-webhook`](https://github.com/discernible-io/hermes-identyclaw-webhook) → plugin id `identyclaw-webhooks`

## Prerequisites

- Stock Hermes Agent already installed (`hermes` on `PATH`)
- Node **≥ 22.19** and `libatomic.so.1`
- OpenClaw left **stopped** (do not run both peer stacks)

## One-shot stock install

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
git clone https://github.com/discernible-io/hermes-identyclaw-auth.git \
  "$HERMES_HOME/hermes-identyclaw-auth"
cd "$HERMES_HOME/hermes-identyclaw-auth"
npm install --omit=dev
bash scripts/install-stock-hermes.sh --a2a-public-url "https://YOUR.PUBLIC.HOST"
```

That script: installs `idcp` → skill → enroll/session → systemd user sidecar →
`hermes plugins install` for A2A + webhooks → optional docs MCP.

## Manual auth-only install

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
git clone https://github.com/discernible-io/hermes-identyclaw-auth.git \
  "$HERMES_HOME/hermes-identyclaw-auth"
cd "$HERMES_HOME/hermes-identyclaw-auth"
npm install --omit=dev
mkdir -p "$HERMES_HOME/bin"
ln -sfn "$(pwd)/bin/idcp.mjs" "$HERMES_HOME/bin/idcp"
export PATH="$HERMES_HOME/bin:$PATH"

hermes skills install discernible-io/hermes-identyclaw-auth/identyclaw

idcp enroll
# buy Passport at https://purchase.identyclaw.com with printed account_id
idcp ensure_session
idcp me
```

Secrets land under `$HERMES_HOME/secrets/` (`near-credentials/`, `identyclaw/`).
Always export `HERMES_HOME` (or rely on the `~/.hermes` default when that directory exists).

## Auth sidecar lifecycle

Peer plugins expect `http://127.0.0.1:9910`. Prefer the systemd user unit:

```bash
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export NEAR_CREDENTIALS_FILE_PATH="$HERMES_HOME/secrets/near-credentials/<account>.json"
bash scripts/install-sidecar-unit.sh
# systemctl --user status identyclaw-auth-sidecar.service
curl -fsS http://127.0.0.1:9910/health
curl -fsS http://127.0.0.1:9910/v1/own_passport
```

Manual (foreground):

```bash
NEAR_CREDENTIALS_FILE_PATH=/path/to/near.json \
  node bin/sidecar.mjs --port 9910
```

Health-check `/health` before enabling A2A or webhooks.

Inbound JWT `aud` comes from `RoditClient.getConfigOwnRodit().own_rodit.owner_id`.
`IDENTYCLAW_JWT_AUDIENCE` is an optional fallback only when the passport cannot load.

## Sidecar routes

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | liveness |
| GET | `/v1/own_passport` | `owner_id` / `token_id` / issuer from RoditClient |
| POST | `/v1/validate_jwt` | Passport JWT → `token_id` |
| POST | `/v1/login_server` | outbound peer login |
| POST | `/v1/authenticate_webhook` | Ed25519 webhook verify |
| GET/POST | `/api/login/timestamp`, `/api/login` | peer inbound login |

Binds **127.0.0.1** only. The CLI never prints full JWTs.

## Minimal `.env` surface

```bash
# $HERMES_HOME/.env
HERMES_HOME=/home/you/.hermes
NEAR_CREDENTIALS_FILE_PATH=/home/you/.hermes/secrets/near-credentials/<account>.json
IDENTYCLAW_AUTH_PORT=9910
IDENTYCLAW_HOOKS_PORT=9911
A2A_PUBLIC_URL=https://your.public.host
A2A_PORT=9900
```

Catalog submission for the peer plugins is optional; `owner/repo` installs work without it.
