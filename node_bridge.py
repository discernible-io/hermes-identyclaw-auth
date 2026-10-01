"""Shared paths and Node process helpers for the IdentyClaw auth plugin."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional, Sequence

logger = logging.getLogger(__name__)

PLUGIN_ROOT = Path(__file__).resolve().parent
IDCP_SCRIPT = PLUGIN_ROOT / "bin" / "idcp.mjs"
SIDECAR_SCRIPT = PLUGIN_ROOT / "bin" / "sidecar.mjs"
PACKAGE_JSON = PLUGIN_ROOT / "package.json"


def hermes_home() -> Path:
    raw = (
        os.getenv("IDENTYCLAW_HOME")
        or os.getenv("HERMES_APP_DIR")
        or os.getenv("HERMES_HOME")
        or ""
    ).strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".hermes").resolve()


def node_bin() -> str:
    override = (os.getenv("IDENTYCLAW_NODE_BIN") or "").strip()
    if override:
        return override
    return shutil.which("node") or "node"


def npm_bin() -> str:
    return shutil.which("npm") or "npm"


def auth_port() -> int:
    raw = (os.getenv("IDENTYCLAW_AUTH_PORT") or "9910").strip() or "9910"
    try:
        return int(raw)
    except ValueError:
        return 9910


def auth_host() -> str:
    return (os.getenv("IDENTYCLAW_AUTH_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def sidecar_base() -> str:
    return f"http://{auth_host()}:{auth_port()}"


def sidecar_autostart_enabled() -> bool:
    raw = (os.getenv("IDENTYCLAW_SIDECAR_AUTOSTART") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def run_dir() -> Path:
    path = hermes_home() / "run"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = hermes_home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def pidfile_path() -> Path:
    return run_dir() / "identyclaw-auth.pid"


def sidecar_logfile() -> Path:
    return log_dir() / "identyclaw-auth.log"


def deps_installed() -> bool:
    return (PLUGIN_ROOT / "node_modules").is_dir() and PACKAGE_JSON.is_file()


def install_node_deps(*, omit_dev: bool = True) -> int:
    """Run npm ci (fallback: npm install) inside the plugin directory."""
    npm = npm_bin()
    if not shutil.which(npm) and npm == "npm":
        logger.error("npm is not on PATH; install Node.js >= 22.19 and re-run")
        return 1
    if not PACKAGE_JSON.is_file():
        logger.error("package.json missing at %s", PACKAGE_JSON)
        return 1

    print(f"  $ cd {PLUGIN_ROOT} && {npm} ci")
    proc = subprocess.run([npm, "ci"], cwd=str(PLUGIN_ROOT), check=False)
    if proc.returncode != 0:
        args = [npm, "install"]
        if omit_dev:
            args.append("--omit=dev")
        print(f"  npm ci failed — falling back to: {' '.join(args)}")
        proc = subprocess.run(args, cwd=str(PLUGIN_ROOT), check=False)
    return int(proc.returncode)


def near_credentials_dir() -> Path:
    return hermes_home() / "secrets" / "near-credentials"


def list_near_credential_files() -> list[Path]:
    cred_dir = near_credentials_dir()
    if not cred_dir.is_dir():
        return []
    return sorted(cred_dir.glob("*.json"))


def active_near_credentials_marker() -> Path:
    return near_credentials_dir() / ".active"


def pin_active_near_credentials(credentials_path: str) -> Optional[str]:
    """Write near-credentials/.active so leftover files are not mistaken for the live key."""
    path = (credentials_path or "").strip()
    if not path:
        return None
    try:
        full = Path(path).expanduser().resolve()
        if not full.is_file() or full.suffix != ".json":
            return None
        cred_dir = near_credentials_dir()
        cred_dir.mkdir(parents=True, exist_ok=True)
        marker = active_near_credentials_marker()
        marker.write_text(f"{full.name}\n", encoding="utf-8")
        try:
            os.chmod(marker, 0o600)
        except OSError:
            pass
        return str(full)
    except OSError as exc:
        logger.warning("identyclaw-auth: could not pin .active credentials: %s", exc)
        return None


def resolve_active_near_credentials() -> Optional[str]:
    """Pick the canonical credentials file (env → .active → sole/sorted file)."""
    existing = (os.getenv("NEAR_CREDENTIALS_FILE_PATH") or "").strip()
    if existing:
        path = Path(existing).expanduser()
        if path.is_file():
            return str(path.resolve())

    candidates = list_near_credential_files()
    if not candidates:
        return None

    marker = active_near_credentials_marker()
    if marker.is_file():
        try:
            name = marker.read_text(encoding="utf-8").strip()
            if name:
                pinned = near_credentials_dir() / (name if name.endswith(".json") else f"{name}.json")
                if pinned.is_file():
                    return str(pinned.resolve())
        except OSError:
            pass

    return str(candidates[0].resolve())


def ensure_near_credentials_env() -> Optional[str]:
    """Populate NEAR_CREDENTIALS_FILE_PATH from secrets layout when unset."""
    chosen = resolve_active_near_credentials()
    if not chosen:
        return None
    os.environ["NEAR_CREDENTIALS_FILE_PATH"] = chosen
    os.environ.setdefault("RODIT_NEAR_CREDENTIALS_SOURCE", "file")
    pin_active_near_credentials(chosen)
    return chosen


def seed_near_credentials_into_dotenv(credentials_path: str) -> bool:
    """Ensure NEAR_CREDENTIALS_FILE_PATH is recorded in $HERMES_HOME/.env."""
    path = (credentials_path or "").strip()
    if not path:
        return False
    env_file = hermes_home() / ".env"
    try:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        if env_file.is_file():
            text = env_file.read_text(encoding="utf-8")
            if any(line.startswith("NEAR_CREDENTIALS_FILE_PATH=") for line in text.splitlines()):
                return False
        else:
            text = ""
        with env_file.open("a", encoding="utf-8") as fh:
            if text and not text.endswith("\n"):
                fh.write("\n")
            fh.write(f"NEAR_CREDENTIALS_FILE_PATH={path}\n")
        try:
            os.chmod(env_file, 0o600)
        except OSError:
            pass
        return True
    except OSError as exc:
        logger.warning("identyclaw-auth: could not seed .env with NEAR credentials: %s", exc)
        return False


_PURCHASE_URL = "https://purchase.identyclaw.com"
_PASTE_HINT = (
    "Paste ONLY this account_id at the purchase page — "
    "ignore other *.json files under near-credentials/ "
    "(leftovers from prior installs are unsafe to mint to)."
)


def _print_account_id_banner(account_id: str, *, credentials: Optional[str] = None, already: bool = False) -> None:
    """Make the mint recipient unmistakable on first-run / reprint."""
    label = "already present" if already else "paste at purchase"
    print("")
    print("=" * 72)
    print(f"  NEAR account_id ({label})")
    print(f"  {_PASTE_HINT}")
    print("-" * 72)
    print(f"  {account_id}")
    print("=" * 72)
    print(f"  purchase: {_PURCHASE_URL}")
    if credentials:
        print(f"  credentials (NEAR_CREDENTIALS_FILE_PATH): {credentials}")
    extras = list_near_credential_files()
    if len(extras) > 1:
        print(
            f"  note: {len(extras)} credential files in {near_credentials_dir()} — "
            "use only the account_id / path printed above."
        )
    print("  Keep the credentials JSON private (0600). Never paste a private key or JWT.")
    print("")


def ensure_enrolled(*, quiet: bool = False) -> dict[str, Any]:
    """Create a NEAR implicit account when none is present (idempotent).

    Used by ``install-deps`` and best-effort plugin load so operators do not need
    a separate ``hermes identyclaw enroll`` step before purchase.
    Never creates a second account when any ``*.json`` already exists.
    """
    candidates = list_near_credential_files()
    existing = ensure_near_credentials_env()
    if existing or candidates:
        # Prefer the pinned/env path; fall back to first candidate without creating.
        credentials = existing or str(candidates[0].resolve())
        if not existing:
            os.environ["NEAR_CREDENTIALS_FILE_PATH"] = credentials
            os.environ.setdefault("RODIT_NEAR_CREDENTIALS_SOURCE", "file")
            pin_active_near_credentials(credentials)
        account_id = None
        try:
            raw = json.loads(Path(credentials).read_text(encoding="utf-8"))
            account_id = raw.get("account_id") or raw.get("implicit_account_id")
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        payload: dict[str, Any] = {
            "ok": True,
            "already": True,
            "account_id": account_id,
            "credentials": credentials,
            "near_credentials_dir": str(near_credentials_dir()),
            "files": [p.name for p in candidates] if candidates else [Path(credentials).name],
            "purchase": _PURCHASE_URL,
            "next_human": (
                f"{_PASTE_HINT} Then: hermes identyclaw me"
            ),
        }
        if len(payload["files"]) > 1:
            payload["warning"] = (
                f"Multiple credential files present ({len(payload['files'])}). "
                "Use only the printed account_id / credentials path."
            )
        seed_near_credentials_into_dotenv(credentials)
        if not quiet and account_id:
            _print_account_id_banner(account_id, credentials=credentials, already=True)
        return payload

    if not deps_installed():
        return {
            "ok": False,
            "error": "Node dependencies not installed",
            "hint": "Run: hermes identyclaw install-deps",
        }

    if not quiet:
        print("  Creating NEAR implicit account (none found)…")
    payload = run_idcp(["enroll"])
    if not isinstance(payload, dict):
        return {"ok": False, "error": "enroll returned unexpected payload", "raw": payload}

    credentials = ensure_near_credentials_env()
    if not credentials and payload.get("credentials"):
        credentials = str(payload["credentials"])
        os.environ["NEAR_CREDENTIALS_FILE_PATH"] = credentials
        os.environ.setdefault("RODIT_NEAR_CREDENTIALS_SOURCE", "file")
        pin_active_near_credentials(credentials)
    if credentials:
        payload["credentials"] = credentials
        seed_near_credentials_into_dotenv(credentials)
        os.environ["NEAR_CREDENTIALS_FILE_PATH"] = credentials
        os.environ.setdefault("RODIT_NEAR_CREDENTIALS_SOURCE", "file")
        pin_active_near_credentials(credentials)

    account_id = payload.get("account_id")
    payload.setdefault("purchase", _PURCHASE_URL)
    payload.setdefault(
        "next_human",
        f"{_PASTE_HINT} Then: hermes identyclaw me",
    )
    if not quiet:
        if payload.get("ok") and account_id:
            _print_account_id_banner(
                str(account_id),
                credentials=credentials or payload.get("credentials"),
                already=False,
            )
        elif not payload.get("ok"):
            print(f"  Warning: enroll failed: {payload.get('error') or payload}")
    return payload


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    home = str(hermes_home())
    env.setdefault("HERMES_HOME", home)
    env.setdefault("IDENTYCLAW_HOME", home)
    ensure_near_credentials_env()
    if os.getenv("NEAR_CREDENTIALS_FILE_PATH"):
        env["NEAR_CREDENTIALS_FILE_PATH"] = os.environ["NEAR_CREDENTIALS_FILE_PATH"]
        env.setdefault("RODIT_NEAR_CREDENTIALS_SOURCE", "file")
    return env


def run_idcp(argv: Sequence[str], *, timeout: Optional[float] = 120.0) -> dict[str, Any]:
    """Shell out to the plugin-owned Node idcp and parse JSON stdout."""
    if not IDCP_SCRIPT.is_file():
        return {"ok": False, "error": f"idcp missing at {IDCP_SCRIPT}"}
    if not deps_installed():
        return {
            "ok": False,
            "error": "Node dependencies not installed",
            "hint": "Run: hermes identyclaw install-deps",
        }

    cmd = [node_bin(), str(IDCP_SCRIPT), *argv]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(PLUGIN_ROOT),
            env=_child_env(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return {
            "ok": False,
            "error": f"node binary not found ({node_bin()})",
            "hint": "Install Node.js >= 22.19 or set IDENTYCLAW_NODE_BIN",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"idcp timed out after {timeout}s", "argv": list(argv)}

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    if not stdout:
        return {
            "ok": False,
            "error": "idcp produced no stdout",
            "stderr": stderr,
            "exit_code": proc.returncode,
        }
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        # Some commands may print usage text; surface raw output.
        return {
            "ok": proc.returncode == 0,
            "raw": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
        }
    if not isinstance(payload, dict):
        return {"ok": proc.returncode == 0, "result": payload, "exit_code": proc.returncode}
    payload.setdefault("ok", proc.returncode == 0)
    if proc.returncode != 0:
        payload.setdefault("exit_code", proc.returncode)
        if stderr:
            payload.setdefault("stderr", stderr)
    return payload


def sidecar_health(timeout: float = 2.0) -> bool:
    try:
        req = urllib.request.Request(
            sidecar_base().rstrip("/") + "/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — localhost
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("ok"))
    except Exception:
        return False


def read_pid() -> Optional[int]:
    path = pidfile_path()
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sidecar_status() -> dict[str, Any]:
    pid = read_pid()
    healthy = sidecar_health()
    return {
        "ok": True,
        "healthy": healthy,
        "base": sidecar_base(),
        "port": auth_port(),
        "host": auth_host(),
        "pid": pid,
        "pid_alive": bool(pid and pid_alive(pid)),
        "pidfile": str(pidfile_path()),
        "deps_installed": deps_installed(),
        "autostart": sidecar_autostart_enabled(),
    }


def start_sidecar(*, foreground: bool = False) -> dict[str, Any]:
    if sidecar_health():
        return {"ok": True, "already": True, **sidecar_status()}

    if not deps_installed():
        code = install_node_deps()
        if code != 0 or not deps_installed():
            return {
                "ok": False,
                "error": "Failed to install Node dependencies",
                "hint": f"cd {PLUGIN_ROOT} && npm ci",
            }

    if not SIDECAR_SCRIPT.is_file():
        return {"ok": False, "error": f"sidecar missing at {SIDECAR_SCRIPT}"}

    pid = read_pid()
    if pid and pid_alive(pid) and not sidecar_health():
        # Stale listener race — still report so ops can stop/restart.
        return {
            "ok": False,
            "error": f"pidfile points at live pid {pid} but /health failed",
            "hint": "hermes identyclaw sidecar stop && hermes identyclaw sidecar start",
            **sidecar_status(),
        }

    ensure_near_credentials_env()
    port = auth_port()
    env = _child_env()
    env["IDENTYCLAW_AUTH_PORT"] = str(port)
    cmd = [node_bin(), str(SIDECAR_SCRIPT), "--port", str(port)]

    if foreground:
        proc = subprocess.run(cmd, cwd=str(PLUGIN_ROOT), env=env, check=False)
        return {"ok": proc.returncode == 0, "exit_code": proc.returncode}

    logfile = sidecar_logfile()
    log_fh = open(logfile, "a", encoding="utf-8")  # noqa: SIM115 — kept open for daemon
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(PLUGIN_ROOT),
            env=env,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except FileNotFoundError:
        log_fh.close()
        return {
            "ok": False,
            "error": f"node binary not found ({node_bin()})",
            "hint": "Install Node.js >= 22.19 or set IDENTYCLAW_NODE_BIN",
        }
    finally:
        # Child holds the fd; parent can close its copy.
        try:
            log_fh.close()
        except Exception:
            pass

    pidfile_path().write_text(f"{proc.pid}\n", encoding="utf-8")
    # Brief readiness wait
    for _ in range(20):
        if sidecar_health():
            return {
                "ok": True,
                "started": True,
                "pid": proc.pid,
                "log": str(logfile),
                **{k: v for k, v in sidecar_status().items() if k != "ok"},
            }
        if proc.poll() is not None:
            break
        try:
            import time

            time.sleep(0.15)
        except Exception:
            break

    return {
        "ok": False,
        "error": "Sidecar did not become healthy",
        "pid": proc.pid,
        "log": str(logfile),
        "hint": "Check NEAR_CREDENTIALS_FILE_PATH and the log file",
        **{k: v for k, v in sidecar_status().items() if k != "ok"},
    }


def stop_sidecar() -> dict[str, Any]:
    pid = read_pid()
    stopped = False
    if pid and pid_alive(pid):
        try:
            os.kill(pid, 15)
            stopped = True
        except OSError as exc:
            return {"ok": False, "error": f"failed to signal pid {pid}: {exc}"}
    try:
        if pidfile_path().is_file():
            pidfile_path().unlink()
    except OSError:
        pass
    return {
        "ok": True,
        "stopped": stopped,
        "pid": pid,
        "healthy": sidecar_health(),
    }


def ensure_sidecar_running() -> dict[str, Any]:
    """Start the sidecar when autostart is enabled and /health is down."""
    if sidecar_health():
        return {"ok": True, "already": True, **sidecar_status()}
    if not sidecar_autostart_enabled():
        return {
            "ok": False,
            "error": "Auth sidecar is not running",
            "hint": "hermes identyclaw sidecar start  (or enable IDENTYCLAW_SIDECAR_AUTOSTART)",
            **sidecar_status(),
        }
    return start_sidecar()
