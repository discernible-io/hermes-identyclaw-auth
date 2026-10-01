#!/usr/bin/env bash
# Stock Hermes + IdentyClaw install playbook (OpenClaw stays stopped).
#
# Ordered: prereqs → auth host package → skill → enroll/session → sidecar →
# A2A plugin → webhook plugin → optional MCP docs.
#
# Usage:
#   export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
#   bash scripts/install-stock-hermes.sh
#
# Flags:
#   --skip-enroll     Do not run idcp enroll / ensure_session
#   --skip-plugins    Stop after auth + sidecar
#   --skip-sidecar    Do not start the auth sidecar
#   --a2a-public-url URL   Write A2A_PUBLIC_URL into $HERMES_HOME/.env
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
AUTH_ROOT="${IDENTYCLAW_AUTH_ROOT:-$HERMES_HOME/hermes-identyclaw-auth}"
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

# --- 1) Auth host package (NOT a Hermes plugin) ------------------------------
log "Install hermes-identyclaw-auth (host CLI + sidecar + skill source)"
if [[ ! -d "$AUTH_ROOT/.git" ]]; then
  git clone https://github.com/discernible-io/hermes-identyclaw-auth.git "$AUTH_ROOT"
else
  git -C "$AUTH_ROOT" pull --ff-only || true
fi
(
  cd "$AUTH_ROOT"
  npm install --omit=dev
)
ln -sfn "$AUTH_ROOT/bin/idcp.mjs" "$HERMES_HOME/bin/idcp"
chmod +x "$AUTH_ROOT/bin/"*.mjs "$AUTH_ROOT/scripts/"*.sh 2>/dev/null || true
hash -r
command -v idcp >/dev/null || die "idcp not on PATH (expected $HERMES_HOME/bin/idcp)"

# --- 2) Skill ----------------------------------------------------------------
log "Install identyclaw skill into Hermes"
if hermes skills list 2>/dev/null | grep -qi 'identyclaw'; then
  echo "Skill already present (hermes skills list)."
else
  hermes skills install discernible-io/hermes-identyclaw-auth/identyclaw --yes \
    || hermes skills install discernible-io/hermes-identyclaw-auth/identyclaw
fi

# --- 3) Enroll / session -----------------------------------------------------
if [[ "$SKIP_ENROLL" -eq 0 ]]; then
  log "Passport enrollment / session"
  idcp enroll || true
  echo "If this is a new account, buy a Passport at https://purchase.identyclaw.com"
  echo "with the account_id printed by enroll, then re-run: idcp ensure_session && idcp me"
  idcp ensure_session || echo "ensure_session failed — mint Passport then retry"
  idcp me || echo "idcp me failed — Passport not ready yet"
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

# --- 4) Sidecar --------------------------------------------------------------
if [[ "$SKIP_SIDECAR" -eq 0 ]]; then
  log "Start auth sidecar (systemd --user)"
  bash "$AUTH_ROOT/scripts/install-sidecar-unit.sh"
  curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/health"
  echo
  curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/v1/own_passport" || true
  echo
fi

if [[ "$SKIP_PLUGINS" -eq 1 ]]; then
  log "Done (plugins skipped)."
  exit 0
fi

# Health gate before peer plugins
if ! curl -fsS "http://127.0.0.1:${IDENTYCLAW_AUTH_PORT:-9910}/health" >/dev/null 2>&1; then
  die "Auth sidecar not healthy on :${IDENTYCLAW_AUTH_PORT:-9910} — start it before enabling A2A/webhooks"
fi

# --- 5) A2A platform plugin --------------------------------------------------
# Stock Hermes flow (docs): install owner/repo → enable (opt-in) → capabilities.
# Scripted form uses --no-enable / --enable as documented; we install disabled,
# disable bundled platforms/a2a, then enable with tools.override grant.
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

# --- 6) Webhooks platform plugin --------------------------------------------
# Repo: hermes-identyclaw-webhook  |  plugin id: identyclaw-webhooks
# Prefer --enable (documented one-shot); fall back to enable if needed.
log "Install IdentyClaw webhooks (hermes plugins install owner/repo)"
if [[ -d "$HERMES_HOME/plugins/identyclaw-webhooks" ]]; then
  hermes plugins install discernible-io/hermes-identyclaw-webhook --enable --force
else
  hermes plugins install discernible-io/hermes-identyclaw-webhook --enable
fi
hermes plugins enable identyclaw-webhooks 2>/dev/null || true

# --- 7) Optional MCP docs ----------------------------------------------------
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
