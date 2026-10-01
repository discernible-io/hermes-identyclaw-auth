import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

/**
 * Secrets / app-dir root.
 * Prefer IDENTYCLAW_HOME → HERMES_APP_DIR → HERMES_HOME → ~/.hermes (stock)
 * → sibling hermes-agents-app (legacy Podman monorepo layout).
 */
export function appDir() {
  const raw =
    process.env.IDENTYCLAW_HOME ||
    process.env.HERMES_APP_DIR ||
    process.env.HERMES_HOME ||
    "";
  if (raw) return path.resolve(raw);
  const home = process.env.HOME || "";
  if (home) {
    const stock = path.join(home, ".hermes");
    if (fs.existsSync(stock)) return stock;
  }
  // Legacy: packages/hermes-identyclaw-auth → repo → sibling hermes-agents-app
  const pkgRoot = path.resolve(__dirname, "../..");
  const repoRoot = path.resolve(pkgRoot, "../..");
  return path.join(path.dirname(repoRoot), "hermes-agents-app");
}

export function secretsDir() {
  return path.join(appDir(), "secrets");
}

export function nearCredentialsDir() {
  return (
    process.env.IDENTYCLAW_NEAR_CREDENTIALS_DIR ||
    path.join(secretsDir(), "near-credentials")
  );
}

export function identyclawSecretsDir() {
  return path.join(secretsDir(), "identyclaw");
}

export function sessionsMetaPath() {
  return path.join(identyclawSecretsDir(), "sessions.json");
}

export function defaultBaseUrl() {
  return (process.env.IDENTYCLAW_BASE_URL || "https://api.identyclaw.com").replace(
    /\/$/,
    ""
  );
}

export function hostKey(baseUrl) {
  return Buffer.from(baseUrl).toString("base64url");
}

export function jwtPathFor(baseUrl = defaultBaseUrl()) {
  return path.join(identyclawSecretsDir(), `jwt-${hostKey(baseUrl)}.txt`);
}

export function ensureSecretsLayout() {
  for (const dir of [secretsDir(), nearCredentialsDir(), identyclawSecretsDir()]) {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    try {
      fs.chmodSync(dir, 0o700);
    } catch {
      /* ignore */
    }
  }
}

/** Resolve NEAR credentials file path for RoditClient (NEAR_CREDENTIALS_FILE_PATH). */
export function resolveNearCredentialsFilePath(credentialsPath = null) {
  if (credentialsPath) return path.resolve(credentialsPath);
  const active = resolveActiveNearCredentialsPath(null);
  if (active) return active;
  try {
    const creds = loadNearCredentials(null);
    return creds.path && creds.path !== "(env)" ? creds.path : null;
  } catch {
    return null;
  }
}

/** Ensure env vars RoditClient expects before loading @rodit/rodit-auth-be.
 * Soft: does not throw when credentials are missing (health / timestamp still work). */
export function ensureRoditCredentialEnv(credentialsPath = null) {
  const filePath = resolveNearCredentialsFilePath(credentialsPath);
  if (filePath && filePath !== "(env)") {
    process.env.NEAR_CREDENTIALS_FILE_PATH = filePath;
    process.env.CREDENTIALS_FILE_PATH = filePath;
  }
  // Same default as origin/main packages/hermes-identyclaw-a2a/sidecar/server.mjs
  process.env.NEAR_CONTRACT_ID =
    process.env.NEAR_CONTRACT_ID ||
    process.env.IDENTYCLAW_NEAR_CONTRACT_ID ||
    "genaaaa-identyclaw-com.near";
  if (!process.env.RODIT_NEAR_CREDENTIALS_SOURCE?.trim()) {
    if (process.env.NEAR_CREDENTIALS_FILE_PATH?.trim()) {
      process.env.RODIT_NEAR_CREDENTIALS_SOURCE = "file";
    }
  }
  if (!process.env.LOG_LEVEL) process.env.LOG_LEVEL = "error";
  if (process.env.SUPPRESS_NO_CONFIG_WARNING === undefined) {
    process.env.SUPPRESS_NO_CONFIG_WARNING = "true";
  }
  if (process.env.SUPPRESS_STRICTNESS_CHECK === undefined) {
    process.env.SUPPRESS_STRICTNESS_CHECK = "true";
  }
  return filePath;
}

/** List sorted *.json basenames under near-credentials. */
export function listNearCredentialFiles(dir = nearCredentialsDir()) {
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort();
}

/**
 * Pin the active credentials file via near-credentials/.active (basename).
 * Consumers and enroll reprints prefer this over leftover files from prior installs.
 */
export function pinActiveNearCredentials(credentialsFilePath) {
  if (!credentialsFilePath || credentialsFilePath === "(env)") return null;
  const full = path.resolve(credentialsFilePath);
  const dir = path.dirname(full);
  const base = path.basename(full);
  if (!base.endsWith(".json") || !fs.existsSync(full)) return null;
  try {
    fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
    fs.writeFileSync(path.join(dir, ".active"), `${base}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
  } catch {
    return null;
  }
  return full;
}

/**
 * Resolve which credentials JSON is canonical.
 * Order: explicit path → NEAR_CREDENTIALS_FILE_PATH → .active → sole file → sorted first.
 */
export function resolveActiveNearCredentialsPath(credentialsPath = null) {
  if (credentialsPath) {
    const resolved = path.resolve(credentialsPath);
    return fs.existsSync(resolved) ? resolved : null;
  }
  if (process.env.NEAR_CREDENTIALS_FILE_PATH?.trim()) {
    const resolved = path.resolve(process.env.NEAR_CREDENTIALS_FILE_PATH.trim());
    if (fs.existsSync(resolved)) return resolved;
  }
  const dir = nearCredentialsDir();
  const files = listNearCredentialFiles(dir);
  if (files.length === 0) return null;
  const active = path.join(dir, ".active");
  if (fs.existsSync(active)) {
    const name = fs.readFileSync(active, "utf8").trim();
    if (files.includes(name) || files.includes(`${name}.json`)) {
      const chosen = files.includes(name) ? name : `${name}.json`;
      return path.join(dir, chosen);
    }
  }
  return path.join(dir, files[0]);
}

/** Load credentials from env / explicit path / active near-credentials JSON. */
export function loadNearCredentials(credentialsPath) {
  if (credentialsPath) {
    const raw = JSON.parse(fs.readFileSync(credentialsPath, "utf8"));
    return normalizeCreds(raw, credentialsPath);
  }
  if (process.env.IDENTYCLAW_ACCOUNT_ID && process.env.IDENTYCLAW_NEAR_PRIVATE_KEY) {
    return {
      accountid: process.env.IDENTYCLAW_ACCOUNT_ID,
      nearPrivateKey: process.env.IDENTYCLAW_NEAR_PRIVATE_KEY,
      path: "(env)",
    };
  }
  const dir = nearCredentialsDir();
  if (!fs.existsSync(dir)) {
    throw new Error(`No credentials dir: ${dir}`);
  }
  const files = listNearCredentialFiles(dir);
  if (files.length === 0) {
    throw new Error(`No *.json in ${dir} — run: idcp enroll`);
  }
  const full = resolveActiveNearCredentialsPath(null);
  if (!full || !fs.existsSync(full)) {
    throw new Error(`No *.json in ${dir} — run: idcp enroll`);
  }
  return normalizeCreds(JSON.parse(fs.readFileSync(full, "utf8")), full);
}

function normalizeCreds(raw, filePath) {
  const accountid = raw.account_id || raw.implicit_account_id;
  const nearPrivateKey = raw.private_key;
  if (!accountid || !nearPrivateKey) {
    throw new Error(`Invalid credentials JSON: ${filePath}`);
  }
  return { accountid, nearPrivateKey, path: filePath };
}

export function loadJwt(baseUrl = defaultBaseUrl()) {
  const p = jwtPathFor(baseUrl);
  if (!fs.existsSync(p)) return null;
  const jwt = fs.readFileSync(p, "utf8").trim();
  return jwt || null;
}

export function saveJwt(jwt, baseUrl = defaultBaseUrl(), meta = {}) {
  ensureSecretsLayout();
  const p = jwtPathFor(baseUrl);
  fs.writeFileSync(p, jwt, { mode: 0o600 });
  const sessions = loadSessionsMeta();
  sessions[baseUrl] = {
    jwt_path: p,
    jwt_length: jwt.length,
    updated_at: new Date().toISOString(),
    ...meta,
  };
  fs.writeFileSync(sessionsMetaPath(), JSON.stringify(sessions, null, 2) + "\n", {
    mode: 0o600,
  });
  return p;
}

export function loadSessionsMeta() {
  const p = sessionsMetaPath();
  if (!fs.existsSync(p)) return {};
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return {};
  }
}

export function loadHolaClient() {
  const vendor = path.join(__dirname, "../../vendor/hola-client/index.js");
  return require(vendor);
}

export function packageRoot() {
  return path.resolve(__dirname, "../..");
}
