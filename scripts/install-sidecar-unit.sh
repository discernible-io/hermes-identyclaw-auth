#!/usr/bin/env bash
# Install/enable a systemd --user unit for the IdentyClaw auth sidecar.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
AUTH_ROOT="${IDENTYCLAW_AUTH_ROOT:-}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_NAME="identyclaw-auth-sidecar.service"
PORT="${IDENTYCLAW_AUTH_PORT:-9910}"

if [[ -z "$AUTH_ROOT" ]]; then
  for c in \
    "$HERMES_HOME/plugins/identyclaw-auth" \
    "$HERMES_HOME/hermes-identyclaw-auth" \
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  do
    if [[ -f "$c/bin/sidecar.mjs" ]]; then
      AUTH_ROOT="$c"
      break
    fi
  done
fi

if [[ -z "${AUTH_ROOT:-}" || ! -d "$AUTH_ROOT" ]]; then
  echo "Auth plugin not found (tried \$HERMES_HOME/plugins/identyclaw-auth)." >&2
  exit 1
fi

# Pick NEAR credentials: env → single file under secrets/near-credentials
CRED="${NEAR_CREDENTIALS_FILE_PATH:-}"
if [[ -z "$CRED" ]]; then
  mapfile -t creds < <(compgen -G "$HERMES_HOME/secrets/near-credentials/*.json" || true)
  if [[ ${#creds[@]} -eq 1 ]]; then
    CRED="${creds[0]}"
  elif [[ ${#creds[@]} -gt 1 ]]; then
    echo "Multiple NEAR credential files; set NEAR_CREDENTIALS_FILE_PATH" >&2
    printf '  %s\n' "${creds[@]}" >&2
    exit 1
  else
    echo "No NEAR credentials under $HERMES_HOME/secrets/near-credentials/ — run: hermes identyclaw install-deps" >&2
    exit 1
  fi
fi

mkdir -p "$UNIT_DIR" "$HERMES_HOME"
ENV_FILE="$HERMES_HOME/.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Ensure credentials path is in .env (idempotent)
if ! grep -q '^NEAR_CREDENTIALS_FILE_PATH=' "$ENV_FILE" 2>/dev/null; then
  echo "NEAR_CREDENTIALS_FILE_PATH=$CRED" >>"$ENV_FILE"
else
  # rewrite existing line
  tmp="$(mktemp)"
  awk -v v="$CRED" '
    BEGIN { done=0 }
    /^NEAR_CREDENTIALS_FILE_PATH=/ { print "NEAR_CREDENTIALS_FILE_PATH=" v; done=1; next }
    { print }
    END { if (!done) print "NEAR_CREDENTIALS_FILE_PATH=" v }
  ' "$ENV_FILE" >"$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
fi
if ! grep -q '^IDENTYCLAW_AUTH_PORT=' "$ENV_FILE" 2>/dev/null; then
  echo "IDENTYCLAW_AUTH_PORT=$PORT" >>"$ENV_FILE"
fi
if ! grep -q '^HERMES_HOME=' "$ENV_FILE" 2>/dev/null; then
  echo "HERMES_HOME=$HERMES_HOME" >>"$ENV_FILE"
fi

NODE_BIN="$(command -v node)"
cat >"$UNIT_DIR/$UNIT_NAME" <<EOF
[Unit]
Description=IdentyClaw Passport auth sidecar (localhost RODiT for Hermes A2A/webhooks)
Documentation=https://github.com/discernible-io/hermes-identyclaw-auth
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$AUTH_ROOT
Environment=HERMES_HOME=$HERMES_HOME
Environment=IDENTYCLAW_AUTH_PORT=$PORT
Environment=NEAR_CREDENTIALS_FILE_PATH=$CRED
EnvironmentFile=-$ENV_FILE
ExecStart=$NODE_BIN $AUTH_ROOT/bin/sidecar.mjs --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT_NAME"

echo "Waiting for sidecar health on 127.0.0.1:$PORT ..."
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "Sidecar healthy."
    curl -fsS "http://127.0.0.1:${PORT}/health" || true
    echo
    exit 0
  fi
  sleep 0.5
done

echo "Sidecar did not become healthy — check: systemctl --user status $UNIT_NAME" >&2
systemctl --user status "$UNIT_NAME" --no-pager || true
exit 1
