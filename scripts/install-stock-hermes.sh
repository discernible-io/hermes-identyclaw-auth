#!/usr/bin/env bash
# Stock Hermes + IdentyClaw install playbook (OpenClaw stays stopped).
#
# Ordered: prereqs → auth plugin → enroll/session → sidecar →
# A2A plugin → webhook plugin → optional MCP docs.
#
# Usage:
#   export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
#   hermes plugins install discernible-io/hermes-identyclaw-auth --enable
#   bash "$HERMES_HOME/plugins/identyclaw-auth/scripts/install-stock-hermes.sh"
#
# Flags:
#   --skip-enroll     Do not run enroll / ensure_session
#   --skip-plugins    Stop after auth + sidecar
#   --skip-sidecar    Do not start the auth sidecar
#   --a2a-public-url URL   Write A2A_PUBLIC_URL into $HERMES_HOME/.env
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
AUTH_ROOT="${IDENTYCLAW_AUTH_ROOT:-}"
SKIP_ENROLL=0
SKIP_PLUGINS=0
SKIP_SIDECAR=0
A2A_PUBLIC_URL_ARG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-enroll) SKIP_ENROLL=1 ;;
    --skip-plugins) SKIP_PLUGINS=1 ;;
    --skip-sidecar) SKIP_SIDECAR=1 ;;
    --a2a-public-url) A2A_PUBLIC_URL_ARG="${2:-}"; shift ;;
    -h|--help)
      sed -n '1,20p' "$0"
      exit 0
      ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

export HERMES_HOME
export PATH="$HERMES_HOME/bin:$HOME/.local/bin:$PATH"

log() { printf '\n==> %s\n' "$*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

resolve_auth_root() {
  if [[ -n "$AUTH_ROOT" && -d "$AUTH_ROOT" ]]; then
    printf '%s' "$AUTH_ROOT"
    return
  fi
  local candidates=(
    "$HERMES_HOME/plugins/identyclaw-auth"
    "$HERMES_HOME/hermes-identyclaw-auth"
    "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  )
  local c
  for c in "${candidates[@]}"; do
    if [[ -f "$c/plugin.yaml" || -f "$c/bin/idcp.mjs" ]]; then
      printf '%s' "$c"
      return
    fi
  done
  return 1
}

# --- 0) Prerequisites -------------------------------------------------------
log "Prerequisites (Hermes already installed; OpenClaw left stopped)"
require_cmd hermes
require_cmd node
require_cmd npm
require_cmd git
require_cmd curl
require_cmd systemctl

NODE_VER="$(node -p 'process.versions.node')"
NODE_OK="$(node -p 'const [a,b]=process.versions.node.split(".").map(Number); a>22||(a===22&&b>=19)')"
[[ "$NODE_OK" == "true" ]] || die "Node >= 22.19 required (found $NODE_VER)"

if ! ldconfig -p 2>/dev/null | grep -q 'libatomic\.so\.1'; then
  die "libatomic.so.1 not found (install libatomic / libatomic1)"
fi

if pgrep -af '[o]penclaw' >/dev/null 2>&1; then
  echo "WARNING: OpenClaw processes are running; stop them before peer plugins:"
  echo "  openclaw gateway stop 2>/dev/null || pkill -f openclaw || true"
fi

mkdir -p "$HERMES_HOME"/{bin,plugins,skills,secrets}

# --- 1) Auth plugin ----------------------------------------------------------
log "Install hermes-identyclaw-auth (Hermes plugin)"
if [[ -d "$HERMES_HOME/plugins/identyclaw-auth" ]]; then
  hermes plugins install discernible-io/hermes-identyclaw-auth --enable --force 2>/dev/null \
    || hermes plugins enable identyclaw-auth 2>/dev/null || true
else
  hermes plugins install discernible-io/hermes-identyclaw-auth --enable
fi

AUTH_ROOT="$(resolve_auth_root)" || die "Could not locate identyclaw-auth plugin tree"
export IDENTYCLAW_AUTH_ROOT="$AUTH_ROOT"
(
  cd "$AUTH_ROOT"
  if command -v hermes >/dev/null 2>&1 && hermes identyclaw install-deps >/dev/null 2>&1; then
    :
  else
    npm ci 2>/dev/null || npm install --omit=dev
  fi
)
chmod +x "$AUTH_ROOT/bin/"*.mjs "$AUTH_ROOT/scripts/"*.sh 2>/dev/null || true

# --- 2) Enroll / session -----------------------------------------------------
if [[ "$SKIP_ENROLL" -eq 0 ]]; then
  log "Passport enrollment / session"
  # install-deps above already auto-enrolls when no account exists; enroll is a safe reprint.
  if hermes identyclaw enroll 2>/dev/null; then
    :
  else
    node "$AUTH_ROOT/bin/idcp.mjs" enroll || true
  fi
  echo "If this is a new account, buy a Passport at https://purchase.identyclaw.com"
  echo "with the account_id printed above, then: hermes identyclaw me"
  hermes identyclaw ensure_session 2>/dev/null \
    || node "$AUTH_ROOT/bin/idcp.mjs" ensure_session \
    || echo "ensure_session failed — mint Passport then retry"
  hermes identyclaw me 2>/dev/null \
    || node "$AUTH_ROOT/bin/idcp.mjs" me \
    || echo "me failed — Passport not ready yet"
fi

# Seed .env
ENV_FILE="$HERMES_HOME/.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"
grep -q '^HERMES_HOME=' "$ENV_FILE" 2>/dev/null || echo "HERMES_HOME=$HERMES_HOME" >>"$ENV_FILE"
grep -q '^IDENTYCLAW_AUTH_PORT=' "$ENV_FILE" 2>/dev/null || echo "IDENTYCLAW_AUTH_PORT=9910" >>"$ENV_FILE"
grep -q '^IDENTYCLAW_HOOKS_PORT=' "$ENV_FILE" 2>/dev/null || echo "IDENTYCLAW_HOOKS_PORT=9911" >>"$ENV_FILE"
if [[ -n "$A2A_PUBLIC_URL_ARG" ]]; then
  if grep -q '^A2A_PUBLIC_URL=' "$ENV_FILE" 2>/dev/null; then
    tmp="$(mktemp)"
    awk -v v="$A2A_PUBLIC_URL_ARG" '
      /^A2A_PUBLIC_URL=/ { print "A2A_PUBLIC_URL=" v; next }
      { print }
    ' "$ENV_FILE" >"$tmp" && mv "$tmp" "$ENV_FILE" && chmod 600 "$ENV_FILE"
  else
    echo "A2A_PUBLIC_URL=$A2A_PUBLIC_URL_ARG" >>"$ENV_FILE"
  fi
fi

mapfile -t creds < <(compgen -G "$HERMES_HOME/secrets/near-credentials/*.json" || true)
if [[ ${#creds[@]} -ge 1 ]] && ! grep -q '^NEAR_CREDENTIALS_FILE_PATH=' "$ENV_FILE" 2>/dev/null; then
  echo "NEAR_CREDENTIALS_FILE_PATH=${creds[0]}" >>"$ENV_FILE"
fi

# --- 3) Sidecar --------------------------------------------------------------
if [[ "$SKIP_SIDECAR" -eq 0 ]]; then
  log "Start auth sidecar (systemd --user preferred)"
  if bash "$AUTH_ROOT/scripts/install-sidecar-unit.sh"; then
    :
  else
    hermes identyclaw sidecar start 2>/dev/null \
      || die "Could not start auth sidecar"
  fi
  curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/health"
  echo
  curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/v1/own_passport" || true
  echo
fi

if [[ "$SKIP_PLUGINS" -eq 1 ]]; then
  log "Done (peer plugins skipped)."
  exit 0
fi

# Health gate before peer plugins
if ! curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/health" >/dev/null 2>&1; then
  die "Auth sidecar not healthy on :${IDENTYCLAW_AUTH_PORT:-9910} — start it before enabling A2A/webhooks"
fi

# --- 4) A2A platform plugin --------------------------------------------------
# Plugin id must be identyclaw-a2a (unique). Bundled key is platforms/a2a
# (yaml name a2a-platform) — enabling "a2a-platform" would hit the bundled copy.
log "Install IdentyClaw A2A overlay (hermes plugins install owner/repo)"
if [[ -d "$HERMES_HOME/plugins/identyclaw-a2a" ]]; then
  hermes plugins install discernible-io/hermes-identyclaw-a2a --no-enable --force
else
  hermes plugins install discernible-io/hermes-identyclaw-a2a --no-enable
fi
hermes plugins disable platforms/a2a 2>/dev/null || true
hermes plugins enable identyclaw-a2a --allow-tool-override

# --- 5) Webhooks platform plugin --------------------------------------------
log "Install IdentyClaw webhooks (hermes plugins install owner/repo)"
if [[ -d "$HERMES_HOME/plugins/identyclaw-webhooks" ]]; then
  hermes plugins install discernible-io/hermes-identyclaw-webhook --enable --force
else
  hermes plugins install discernible-io/hermes-identyclaw-webhook --enable
fi
hermes plugins enable identyclaw-webhooks 2>/dev/null || true

# --- 6) Optional MCP docs ----------------------------------------------------
log "Optional: IdentyClaw docs MCP"
if hermes mcp list 2>/dev/null | grep -qi identyclaw; then
  echo "MCP 'identyclaw' already configured."
else
  hermes mcp add identyclaw --url https://api.identyclaw.com/mcp 2>/dev/null \
    || echo "Skipped MCP (add manually: hermes mcp add identyclaw --url https://api.identyclaw.com/mcp)"
fi

# --- Verify ------------------------------------------------------------------
log "Verification"
hermes plugins list || true
echo
echo "Config tips — minimal $HERMES_HOME/.env / config.yaml surface:"
cat <<EOF
  HERMES_HOME=$HERMES_HOME
  NEAR_CREDENTIALS_FILE_PATH=.../secrets/near-credentials/<account>.json
  IDENTYCLAW_AUTH_PORT=9910
  IDENTYCLAW_HOOKS_PORT=9911
  A2A_PUBLIC_URL=https://your.public.host   # Agent Card / discovery
  A2A_PORT=9900

plugins:
  enabled:
    - identyclaw-auth
    - identyclaw-a2a
    - identyclaw-webhooks
  disabled:
    - platforms/a2a
  entries:
    identyclaw-a2a:
      enabled: true
      allow_tool_override: true
      # or: granted_capabilities: [tools.override]
EOF

echo
echo "Stock Hermes IdentyClaw install complete."
echo "Hermes HMAC /webhooks/{route} is untouched; RODiT hooks are on /hooks/*."
