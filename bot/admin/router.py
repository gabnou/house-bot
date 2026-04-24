import os
import re
import json
import signal
import logging
import subprocess
import threading
import wsgiref.simple_server
from collections import deque
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/api", tags=["admin"])

# Absolute path to the project root (two levels up from bot/admin/)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_LOG_DIR = _PROJECT_ROOT / "logs"
_ENV_FILE = _PROJECT_ROOT / ".env"

_KNOWN_LOGS = {
    "fastapi": _LOG_DIR / "fastapi.log",
    "bridge": _LOG_DIR / "bridge.log",
    "scheduler": _LOG_DIR / "scheduler.log",
    "watchdog": _LOG_DIR / "watchdog.log",
}


def _ollama_base() -> str:
    url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    return url.rsplit("/api/", 1)[0]


def _read_pid(name: str) -> int | None:
    pid_file = _LOG_DIR / f"{name}.pid"
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # check it's alive
        return pid
    except Exception:
        return None


def _env_set(key: str, value: str) -> None:
    """Write or update a key=value line in .env atomically."""
    content = _ENV_FILE.read_text(encoding="utf-8") if _ENV_FILE.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
    new_line = f"{key}={value}"
    if pattern.search(content):
        content = pattern.sub(new_line, content)
    else:
        content = content.rstrip("\n") + f"\n{new_line}\n"
    _ENV_FILE.write_text(content, encoding="utf-8")


# ── Google OAuth ─────────────────────────────────────────────────────────────

_CREDS_PATH = _PROJECT_ROOT / "creds" / "client_google_api_calendar.json"
_TOKEN_PATH = _PROJECT_ROOT / "creds" / "token.json"
_GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]
_GOOGLE_CALLBACK_PORT = 8787

# Mutable state for the in-flight OAuth flow (single-process, single-flow)
_google_oauth: dict = {"running": False, "error": None}


def _google_token_status() -> dict:
    """Return a dict describing the current token.json state.

    If the access token is expired but a refresh_token is present, auto-refresh
    and persist the new token — matching the behaviour of the calendar service
    itself (which refreshes transparently on first API call).
    """
    if not _TOKEN_PATH.exists():
        return {"status": "missing"}
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _GOOGLE_SCOPES)
        expiry = creds.expiry.isoformat() if creds.expiry else None
        configured = os.getenv("GOOGLE_CALENDAR_NAME", "")
        if creds.valid:
            return {"status": "valid", "expiry": expiry, "configured_calendar": configured}
        if creds.expired and creds.refresh_token:
            # Silently refresh — same path as calendar_handler.get_service()
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
            expiry = creds.expiry.isoformat() if creds.expiry else None
            logger.debug("🔄 Google token auto-refreshed on status check")
            return {"status": "valid", "expiry": expiry, "configured_calendar": configured}
        if creds.expired:
            return {"status": "expired", "expiry": expiry, "has_refresh": False, "configured_calendar": configured}
        return {"status": "invalid", "expiry": expiry, "configured_calendar": configured}
    except Exception as exc:
        return {"status": "invalid", "error": str(exc)}


@router.get("/ping")
async def ping():
    """Health check for the admin API."""
    return {"ok": True, "service": "housebot-admin"}


@router.get("/git-info")
async def git_info():
    """Return last commit hash, date, branch, and GitHub link."""
    try:
        fmt = subprocess.check_output(
            ["git", "log", "-1", "--format=%H|%h|%cd|%D", "--date=short"],
            cwd=str(_PROJECT_ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip()
        full_hash, short_hash, date, refs = fmt.split("|", 3)

        # Extract branch name from refs like "HEAD -> feat/foo, origin/feat/foo"
        branch = ""
        for part in refs.split(","):
            part = part.strip()
            if part.startswith("HEAD -> "):
                branch = part[len("HEAD -> "):]
                break
        if not branch:
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(_PROJECT_ROOT), text=True, stderr=subprocess.DEVNULL
            ).strip()

        remote = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=str(_PROJECT_ROOT), text=True, stderr=subprocess.DEVNULL
        ).strip().removesuffix(".git")

        return JSONResponse(content={
            "hash": short_hash,
            "date": date,
            "branch": branch,
            "commit_url": f"{remote}/commit/{full_hash}",
            "branch_url": f"{remote}/tree/{branch}",
        })
    except Exception as e:
        logger.warning("git-info failed: %s", e)
        return JSONResponse(content={"hash": "unknown", "date": "", "branch": "", "commit_url": "", "branch_url": ""})


@router.get("/status")
async def status():
    """Return service health and a safe config snapshot."""
    import requests as _req

    results: dict = {}
    base = _ollama_base()

    # FastAPI itself is up
    results["fastapi"] = {"up": True}

    # Ollama reachability
    try:
        r = _req.get(f"{base}/api/tags", timeout=3)
        results["ollama"] = {"up": r.status_code == 200}
    except Exception:
        results["ollama"] = {"up": False}

    # Active Ollama model in memory
    try:
        r = _req.get(f"{base}/api/ps", timeout=3)
        models = r.json().get("models", [])
        results["ollama"]["active_model"] = models[0]["name"] if models else None
    except Exception:
        results["ollama"].setdefault("active_model", None)

    # WhatsApp Bridge (Node.js :3001) — /health or fall back to TCP probe
    try:
        r = _req.get("http://localhost:3001/health", timeout=3)
        results["bridge"] = {"up": r.status_code < 500}
    except Exception:
        import socket
        try:
            with socket.create_connection(("localhost", 3001), timeout=2):
                results["bridge"] = {"up": True}
        except Exception:
            results["bridge"] = {"up": False}

    # Safe config snapshot — no secrets, no JIDs
    results["config"] = [
        {"key": "OLLAMA_MODEL",       "value": os.getenv("OLLAMA_MODEL", ""),         "label": "LLM Model"},
        {"key": "OLLAMA_URL",         "value": os.getenv("OLLAMA_URL", ""),            "label": "Ollama URL"},
        {"key": "WHISPER_MODEL",      "value": os.getenv("WHISPER_MODEL", ""),         "label": "Whisper Model"},
        {"key": "DEFAULT_CITY",       "value": os.getenv("DEFAULT_CITY", ""),          "label": "Default City"},
        {"key": "TIMEZONE_DEFAULT",   "value": os.getenv("TIMEZONE_DEFAULT", ""),      "label": "Timezone"},
        {"key": "BRIEFING_TIME",      "value": os.getenv("BRIEFING_TIME", "07:30"),    "label": "Briefing Time"},
        {"key": "BRIEFING_LANGUAGE",  "value": os.getenv("BRIEFING_LANGUAGE", ""),     "label": "Briefing Language"},
        {"key": "LOG_LEVEL",          "value": os.getenv("LOG_LEVEL", "INFO"),         "label": "Log Level"},
        {"key": "GOOGLE_CALENDAR_NAME","value": os.getenv("GOOGLE_CALENDAR_NAME", ""), "label": "Calendar"},
    ]

    return JSONResponse(content=results)


@router.get("/logs")
async def logs(
    service: str = Query("fastapi", description="One of: fastapi, bridge, scheduler, watchdog"),
    lines: int = Query(100, ge=1, le=2000, description="Number of tail lines to return"),
):
    """Tail the last N lines of a service log file."""
    if service not in _KNOWN_LOGS:
        raise HTTPException(status_code=400, detail=f"Unknown service '{service}'. Choose from: {list(_KNOWN_LOGS)}")

    log_path = _KNOWN_LOGS[service]
    if not log_path.exists():
        return JSONResponse(content={"service": service, "lines": [], "exists": False})

    # Efficient tail using a deque
    try:
        tail: deque[str] = deque(maxlen=lines)
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                tail.append(line.rstrip("\n"))
        return JSONResponse(content={"service": service, "lines": list(tail), "exists": True})
    except Exception as e:
        logger.error("Failed to read log %s: %s", log_path, e)
        raise HTTPException(status_code=500, detail="Could not read log file")


# ── Ollama Model Manager ────────────────────────────────────────────────────

@router.get("/ollama/models")
async def ollama_models():
    """List all locally pulled Ollama models."""
    import requests as _req
    base = _ollama_base()
    try:
        r = _req.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        raw = r.json().get("models", [])
        tested = _load_tested_models()
        incompatible = _load_incompatible_models()
        models = [
            {
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "modified": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
                "params": m.get("details", {}).get("parameter_size", ""),
                "tested": m["name"] in tested,
                "incompatible": m["name"] in incompatible,
            }
            for m in raw
        ]
        configured = os.getenv("OLLAMA_MODEL", "")
        return JSONResponse(content={"models": models, "configured": configured})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}")


@router.get("/ollama/active")
async def ollama_active():
    """Return the model currently loaded in Ollama memory."""
    import requests as _req
    base = _ollama_base()
    try:
        r = _req.get(f"{base}/api/ps", timeout=5)
        r.raise_for_status()
        models = r.json().get("models", [])
        active = models[0]["name"] if models else None
        return JSONResponse(content={"active": active, "configured": os.getenv("OLLAMA_MODEL", "")})
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}")


@router.get("/ollama/status")
async def ollama_status():
    """Lightweight Ollama health check: reachability + active/configured model."""
    import requests as _req
    base = _ollama_base()
    up = False
    try:
        r = _req.get(f"{base}/api/tags", timeout=3)
        up = r.status_code == 200
    except Exception:
        pass

    active_model = None
    if up:
        try:
            r2 = _req.get(f"{base}/api/ps", timeout=3)
            models = r2.json().get("models", [])
            active_model = models[0]["name"] if models else None
        except Exception:
            pass

    return JSONResponse(content={
        "up": up,
        "active_model": active_model,
        "configured_model": os.getenv("OLLAMA_MODEL", ""),
    })


@router.post("/ollama/restart")
async def ollama_restart():
    """Restart the Ollama service (macOS: brew services or pkill + open)."""
    import time as _time

    def _do_restart():
        # Try brew services restart first (works for brew-installed Ollama)
        result = subprocess.run(
            ["brew", "services", "restart", "ollama"],
            capture_output=True, timeout=15
        )
        if result.returncode != 0:
            # Fallback: kill process and relaunch as macOS app
            subprocess.run(["pkill", "-ix", "ollama"], capture_output=True)
            _time.sleep(1.5)
            subprocess.Popen(
                ["open", "-ga", "Ollama"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )

    threading.Thread(target=_do_restart, daemon=True).start()
    logger.info("🔄 Ollama restart initiated")
    return JSONResponse(content={"ok": True, "message": "Ollama restart initiated"})


@router.get("/ollama/version")
async def ollama_version():
    """Return the installed Ollama version and the latest available from GitHub."""
    import requests as _req

    base = _ollama_base()

    # Installed version — prefer CLI binary (reflects actual installed package),
    # fall back to running server API (which may be a stale daemon).
    installed: str | None = None
    try:
        result = subprocess.run(
            ["ollama", "--version"], capture_output=True, text=True, timeout=5
        )
        # Output may be multi-line, e.g.:
        #   ollama version is 0.21.0
        #   Warning: client version is 0.21.1
        # We want the *client* (binary) version, which is the last version-like token.
        import re as _re
        versions = _re.findall(r'\d+\.\d+\.\d+', result.stdout)
        if versions:
            installed = versions[-1]  # last match = client/binary version
    except Exception:
        pass
    if not installed:
        try:
            r = _req.get(f"{base}/api/version", timeout=3)
            if r.status_code == 200:
                installed = r.json().get("version")
        except Exception:
            pass

    # Latest version from GitHub releases
    latest: str | None = None
    try:
        r = _req.get(
            "https://api.github.com/repos/ollama/ollama/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=8,
        )
        if r.status_code == 200:
            tag = r.json().get("tag_name", "")
            latest = tag.lstrip("v")
    except Exception:
        pass

    # Compare versions (e.g. "0.7.1" vs "0.6.9")
    update_available = False
    if installed and latest:
        try:
            def _ver(v: str):
                return tuple(int(x) for x in v.split(".") if x.isdigit())
            update_available = _ver(latest) > _ver(installed)
        except Exception:
            update_available = installed != latest

    return JSONResponse(content={
        "installed": installed,
        "latest": latest,
        "update_available": update_available,
    })


_upgrade_state: dict = {"status": "idle", "log": [], "exit_code": None}
_upgrade_lock = threading.Lock()


@router.get("/ollama/upgrade/status")
async def ollama_upgrade_status():
    """Return the current state of an ongoing (or last completed) brew upgrade."""
    with _upgrade_lock:
        return JSONResponse(content=dict(_upgrade_state))


@router.post("/ollama/upgrade")
async def ollama_upgrade():
    """Upgrade Ollama via brew (macOS). Streams stdout/stderr into a shared state for polling."""
    with _upgrade_lock:
        if _upgrade_state["status"] == "running":
            return JSONResponse(content={"ok": False, "message": "Upgrade already in progress."})
        _upgrade_state.update({"status": "running", "log": [], "exit_code": None})

    def _do_upgrade():
        try:
            proc = subprocess.Popen(
                ["brew", "upgrade", "ollama"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True,
            )
            assert proc.stdout is not None
            for raw_line in proc.stdout:
                line = raw_line.rstrip()
                if line:
                    with _upgrade_lock:
                        _upgrade_state["log"].append(line)
                        if len(_upgrade_state["log"]) > 50:
                            _upgrade_state["log"] = _upgrade_state["log"][-50:]
            proc.wait(timeout=300)
            with _upgrade_lock:
                _upgrade_state["exit_code"] = proc.returncode
                _upgrade_state["status"] = "done" if proc.returncode == 0 else "failed"
        except Exception as exc:
            with _upgrade_lock:
                _upgrade_state["status"] = "failed"
                _upgrade_state["log"].append(str(exc))

    threading.Thread(target=_do_upgrade, daemon=True).start()
    logger.info("⬆️ Ollama upgrade initiated via brew")
    return JSONResponse(content={"ok": True, "message": "Upgrade started."})


# ── HouseBot Software Update ─────────────────────────────────────────────────

_GITHUB_REPO = "gabnou/house-bot"
_RELEASE_FILE = _PROJECT_ROOT / "release.json"


def _git(*args: str) -> str:
    """Run a git command in PROJECT_ROOT and return stdout (stripped)."""
    result = subprocess.run(
        ["git", *args], cwd=str(_PROJECT_ROOT),
        capture_output=True, text=True, timeout=15,
    )
    return result.stdout.strip()


@router.get("/housebot/version")
async def housebot_version():
    """Return the installed version.

    Two states only:
    - source = "release"  → release.json present (installed from a release zip or upgraded)
    - source = "git"      → release.json absent  (running from a git clone)
    """
    import json as _json

    installed: str | None = None
    installed_source: str | None = None

    # ── Release install ───────────────────────────────────────────────────────
    try:
        with open(_RELEASE_FILE) as rf:
            data = _json.load(rf)
            installed = data.get("version") or None
            if installed:
                installed_source = "release"
    except Exception:
        pass

    # ── Git clone fallback ────────────────────────────────────────────────────
    if not installed:
        installed_source = "git"
        try:
            commit = _git("log", "-1", "--format=%h") or None
            branch = _git("rev-parse", "--abbrev-ref", "HEAD") or None
            if commit:
                installed = f"{branch}@{commit}" if branch and branch != "HEAD" else commit
            else:
                installed = "unknown"
        except Exception:
            installed = "unknown"

    return JSONResponse(content={
        "installed": installed,
        "installed_source": installed_source,
        "repo_url": f"https://github.com/{_GITHUB_REPO}",
    })


_hb_upgrade_state: dict = {"status": "idle", "log": [], "exit_code": None}
_hb_upgrade_lock = threading.Lock()


@router.get("/housebot/upgrade/status")
async def housebot_upgrade_status():
    """Return the current state of a HouseBot upgrade."""
    with _hb_upgrade_lock:
        return JSONResponse(content=dict(_hb_upgrade_state))


# Paths (relative to PROJECT_ROOT) that must never be overwritten by an upgrade.
# These hold user data, secrets, runtime state, and local config.
_HB_PRESERVE = {
    ".env",
    "creds",
    "logs",
    "bridge/baileys_auth",
    "bot/services/db",
    "bot/ollama_models.json",
}


def _hb_preserve(rel_path: str) -> bool:
    """Return True if rel_path (forward-slash, relative to project root) should be preserved."""
    from pathlib import PurePosixPath
    p = PurePosixPath(rel_path)
    for preserved in _HB_PRESERVE:
        pres = PurePosixPath(preserved)
        if p == pres or p.parts[:len(pres.parts)] == pres.parts:
            return True
    return False


@router.post("/housebot/upgrade")
async def housebot_upgrade():
    """Upgrade HouseBot: download release zip, apply files, rebuild UI, restart."""
    import requests as _req

    with _hb_upgrade_lock:
        if _hb_upgrade_state["status"] == "running":
            return JSONResponse(content={"ok": False, "message": "Upgrade already in progress."})
        _hb_upgrade_state.update({"status": "running", "log": [], "exit_code": None})

    # Resolve the latest release from GitHub (releases only)
    latest_tag: str | None = None
    zipball_url: str | None = None
    try:
        r = _req.get(
            f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest",
            headers={"Accept": "application/vnd.github.v3+json"},
            timeout=8,
        )
        if r.status_code == 200:
            release = r.json()
            latest_tag = release.get("tag_name") or None
            zipball_url = release.get("zipball_url") or None
    except Exception:
        pass

    if not latest_tag or not zipball_url:
        with _hb_upgrade_lock:
            _hb_upgrade_state.update({"status": "failed", "log": ["No GitHub release found."], "exit_code": 1})
        return JSONResponse(content={"ok": False, "message": "No GitHub release found."})

    def _log(msg: str):
        with _hb_upgrade_lock:
            _hb_upgrade_state["log"].append(msg)
            if len(_hb_upgrade_state["log"]) > 200:
                _hb_upgrade_state["log"] = _hb_upgrade_state["log"][-200:]

    def _run_step(cmd: list[str], cwd: str | None = None) -> int:
        proc = subprocess.Popen(
            cmd, cwd=cwd or str(_PROJECT_ROOT),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            _log(line.rstrip())
        proc.wait(timeout=300)
        return proc.returncode

    def _do_hb_upgrade():
        import tempfile
        import zipfile
        import shutil
        import requests as _req2

        try:
            # 1. Download the release zip
            _log(f"→ Downloading {latest_tag} from GitHub…")
            resp = _req2.get(zipball_url, stream=True, timeout=120, allow_redirects=True)
            resp.raise_for_status()

            with tempfile.TemporaryDirectory() as tmpdir:
                zip_path = f"{tmpdir}/release.zip"
                total = 0
                with open(zip_path, "wb") as fz:
                    for chunk in resp.iter_content(chunk_size=65536):
                        fz.write(chunk)
                        total += len(chunk)
                _log(f"  Downloaded {total // 1024} KB")

                # 2. Extract
                _log("→ Extracting…")
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extractall(tmpdir)

                # GitHub zips contain a single root dir: owner-repo-shortsha/
                candidates = [
                    d for d in os.listdir(tmpdir)
                    if os.path.isdir(os.path.join(tmpdir, d)) and d != "__MACOSX"
                ]
                if not candidates:
                    raise RuntimeError("Could not find extracted directory in zip")
                src_root = os.path.join(tmpdir, candidates[0])

                # 3. Copy files to PROJECT_ROOT, skipping preserved paths
                _log("→ Applying update (preserving .env, creds, logs, DB, auth)…")
                copied = skipped = 0
                for dirpath, dirnames, filenames in os.walk(src_root):
                    # Normalise rel_dir to forward-slash
                    rel_dir = os.path.relpath(dirpath, src_root).replace(os.sep, "/")
                    if rel_dir == ".":
                        rel_dir = ""
                    for filename in filenames:
                        rel_path = f"{rel_dir}/{filename}" if rel_dir else filename
                        if _hb_preserve(rel_path):
                            skipped += 1
                            continue
                        src_file = os.path.join(dirpath, filename)
                        dst_file = str(_PROJECT_ROOT / rel_path.replace("/", os.sep))
                        os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                        shutil.copy2(src_file, dst_file)
                        copied += 1
                _log(f"  {copied} files updated, {skipped} preserved")

                # 3b. Write release.json to record the installed version
                import json as _json2
                from datetime import datetime, timezone
                with open(str(_PROJECT_ROOT / "release.json"), "w") as rf:
                    _json2.dump(
                        {"version": latest_tag, "installed_at": datetime.now(timezone.utc).isoformat()},
                        rf,
                    )
                _log(f"  Release recorded as {latest_tag}")

            # 4. Install/update Python dependencies
            _log("→ Installing Python dependencies…")
            rc = _run_step([_VENV_PYTHON, "-m", "pip", "install", "-r",
                            str(_PROJECT_ROOT / "requirements.txt"), "-q"])
            if rc != 0:
                raise RuntimeError(f"pip install failed (exit {rc})")

            # 5. Build UI
            _log("→ Building UI…")
            rc = _run_step(["bash", _HOUSEBOT_SH, "ui-build"])
            if rc != 0:
                raise RuntimeError(f"ui-build failed (exit {rc})")

            _log("✅ Update complete. Restarting HouseBot in 3s…")
            with _hb_upgrade_lock:
                _hb_upgrade_state.update({"status": "done", "exit_code": 0})

            # Detached restart
            subprocess.Popen(
                ["bash", "-c", f"sleep 3 && bash '{_HOUSEBOT_SH}' restart"],
                close_fds=True, start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            _log(f"❌ {exc}")
            with _hb_upgrade_lock:
                _hb_upgrade_state.update({"status": "failed", "exit_code": 1})

    threading.Thread(target=_do_hb_upgrade, daemon=True).start()
    logger.info("⬆️ HouseBot upgrade initiated → %s", latest_tag)
    return JSONResponse(content={"ok": True, "message": f"Upgrade to {latest_tag} started."})


class SwitchModelRequest(BaseModel):
    model: str
    persist: bool = True


@router.post("/ollama/switch")
async def ollama_switch(req: SwitchModelRequest):
    """
    Switch the active Ollama model.
    When persist=True (default): write OLLAMA_MODEL to .env, unload old model.
    When persist=False: only update in-memory MODEL for a temporary test run.
    """
    import requests as _req

    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model name is required")

    base = _ollama_base()

    # Always update in-memory so /message uses the new model immediately
    os.environ["OLLAMA_MODEL"] = model
    import sys
    if "intent_parser" in sys.modules:
        sys.modules["intent_parser"].MODEL = model

    if req.persist:
        # 1. Persist to .env
        _env_set("OLLAMA_MODEL", model)

        # 2. Unload current model
        try:
            r = _req.get(f"{base}/api/ps", timeout=3)
            current_models = r.json().get("models", [])
            for m in current_models:
                current_name = m["name"]
                if current_name != model:
                    subprocess.Popen(
                        ["ollama", "stop", current_name],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                    )
        except Exception:
            pass  # non-fatal

        # 3. Warm up new model asynchronously
        subprocess.Popen(
            ["ollama", "pull", model],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        logger.info("🧠 Model switched to %s (persisted)", model)
    else:
        logger.info("🧪 Model temporarily loaded for testing: %s", model)

    return JSONResponse(content={"ok": True, "model": model, "persisted": req.persist})


# ── Ollama Model Catalog ─────────────────────────────────────────────────────

_OLLAMA_STATIC_CATALOG = [
    {"id": "llama3.2:1b",          "family": "Meta",        "description": "Llama 3.2 1B — ultra-fast, great for low-RAM machines",     "ram": "~1 GB"},
    {"id": "llama3.2:3b",          "family": "Meta",        "description": "Llama 3.2 3B — small, fast and capable",                    "ram": "~2 GB"},
    {"id": "llama3.1:8b",          "family": "Meta",        "description": "Llama 3.1 8B — great general-purpose model",                "ram": "~5 GB"},
    {"id": "llama3.1:70b",         "family": "Meta",        "description": "Llama 3.1 70B — high quality, large",                       "ram": "~40 GB"},
    {"id": "llama3:8b",            "family": "Meta",        "description": "Llama 3 8B",                                                "ram": "~5 GB"},
    {"id": "llama3:70b",           "family": "Meta",        "description": "Llama 3 70B",                                               "ram": "~40 GB"},
    {"id": "llama2:7b",            "family": "Meta",        "description": "Llama 2 7B",                                                "ram": "~4 GB"},
    {"id": "llama2:13b",           "family": "Meta",        "description": "Llama 2 13B",                                               "ram": "~8 GB"},
    {"id": "gemma4:e2b",           "family": "Google",      "description": "Gemma 4 E2B — multimodal (text+image), 128K context, edge device",  "ram": "~7 GB"},
    {"id": "gemma4:e4b",           "family": "Google",      "description": "Gemma 4 E4B — multimodal (text+image), 128K context, edge device",  "ram": "~10 GB"},
    {"id": "gemma4:26b",           "family": "Google",      "description": "Gemma 4 26B — MoE (4B active), multimodal, 256K context",           "ram": "~18 GB"},
    {"id": "gemma4:31b",           "family": "Google",      "description": "Gemma 4 31B — dense, multimodal, 256K context",                     "ram": "~20 GB"},
    {"id": "gemma3:1b",            "family": "Google",      "description": "Gemma 3 1B — Google's efficient small model",               "ram": "~2 GB"},
    {"id": "gemma3:4b",            "family": "Google",      "description": "Gemma 3 4B",                                                "ram": "~4 GB"},
    {"id": "gemma3:12b",           "family": "Google",      "description": "Gemma 3 12B",                                               "ram": "~12 GB"},
    {"id": "gemma3:27b",           "family": "Google",      "description": "Gemma 3 27B",                                               "ram": "~24 GB"},
    {"id": "gemma2:2b",            "family": "Google",      "description": "Gemma 2 2B",                                                "ram": "~2 GB"},
    {"id": "gemma2:9b",            "family": "Google",      "description": "Gemma 2 9B",                                                "ram": "~6 GB"},
    {"id": "gemma2:27b",           "family": "Google",      "description": "Gemma 2 27B",                                               "ram": "~20 GB"},
    {"id": "mistral:7b",           "family": "Mistral",     "description": "Mistral 7B — fast and highly capable",                     "ram": "~4 GB"},
    {"id": "mistral-small:22b",    "family": "Mistral",     "description": "Mistral Small 22B",                                        "ram": "~16 GB"},
    {"id": "mixtral:8x7b",         "family": "Mistral",     "description": "Mixtral 8x7B Mixture-of-Experts",                          "ram": "~26 GB"},
    {"id": "phi4:14b",             "family": "Microsoft",   "description": "Phi-4 14B — Microsoft's latest small language model",      "ram": "~10 GB"},
    {"id": "phi4-mini:3.8b",       "family": "Microsoft",   "description": "Phi-4 Mini 3.8B",                                         "ram": "~3 GB"},
    {"id": "phi3.5:3.8b",          "family": "Microsoft",   "description": "Phi-3.5 Mini 3.8B",                                       "ram": "~3 GB"},
    {"id": "phi3:3.8b",            "family": "Microsoft",   "description": "Phi-3 Mini 3.8B",                                         "ram": "~2.5 GB"},
    {"id": "phi3:14b",             "family": "Microsoft",   "description": "Phi-3 Medium 14B",                                        "ram": "~9 GB"},
    {"id": "qwen2.5:0.5b",         "family": "Alibaba",     "description": "Qwen 2.5 0.5B — ultra-lightweight",                        "ram": "~0.5 GB"},
    {"id": "qwen2.5:1.5b",         "family": "Alibaba",     "description": "Qwen 2.5 1.5B",                                            "ram": "~1 GB"},
    {"id": "qwen2.5:3b",           "family": "Alibaba",     "description": "Qwen 2.5 3B",                                              "ram": "~2 GB"},
    {"id": "qwen2.5:7b",           "family": "Alibaba",     "description": "Qwen 2.5 7B",                                              "ram": "~5 GB"},
    {"id": "qwen2.5:14b",          "family": "Alibaba",     "description": "Qwen 2.5 14B",                                             "ram": "~10 GB"},
    {"id": "qwen2.5:32b",          "family": "Alibaba",     "description": "Qwen 2.5 32B",                                             "ram": "~20 GB"},
    {"id": "qwen2.5:72b",          "family": "Alibaba",     "description": "Qwen 2.5 72B",                                             "ram": "~45 GB"},
    {"id": "qwen2:7b",             "family": "Alibaba",     "description": "Qwen 2 7B",                                                "ram": "~5 GB"},
    {"id": "qwen2:72b",            "family": "Alibaba",     "description": "Qwen 2 72B",                                               "ram": "~43 GB"},
    {"id": "deepseek-r1:1.5b",     "family": "DeepSeek",    "description": "DeepSeek-R1 1.5B — reasoning model",                      "ram": "~1 GB"},
    {"id": "deepseek-r1:7b",       "family": "DeepSeek",    "description": "DeepSeek-R1 7B",                                           "ram": "~5 GB"},
    {"id": "deepseek-r1:8b",       "family": "DeepSeek",    "description": "DeepSeek-R1 8B",                                           "ram": "~5 GB"},
    {"id": "deepseek-r1:14b",      "family": "DeepSeek",    "description": "DeepSeek-R1 14B",                                          "ram": "~9 GB"},
    {"id": "deepseek-r1:32b",      "family": "DeepSeek",    "description": "DeepSeek-R1 32B",                                          "ram": "~20 GB"},
    {"id": "deepseek-r1:70b",      "family": "DeepSeek",    "description": "DeepSeek-R1 70B",                                          "ram": "~43 GB"},
    {"id": "codellama:7b",         "family": "Meta",        "description": "Code Llama 7B — coding specialist",                        "ram": "~4 GB"},
    {"id": "codellama:13b",        "family": "Meta",        "description": "Code Llama 13B",                                           "ram": "~8 GB"},
    {"id": "codellama:34b",        "family": "Meta",        "description": "Code Llama 34B",                                           "ram": "~20 GB"},
    {"id": "starcoder2:3b",        "family": "BigCode",     "description": "StarCoder2 3B — code generation",                          "ram": "~2 GB"},
    {"id": "starcoder2:7b",        "family": "BigCode",     "description": "StarCoder2 7B",                                            "ram": "~4 GB"},
    {"id": "starcoder2:15b",       "family": "BigCode",     "description": "StarCoder2 15B",                                           "ram": "~9 GB"},
    {"id": "nomic-embed-text",     "family": "Nomic",       "description": "Nomic Embed Text — text embeddings",                       "ram": "~0.3 GB"},
    {"id": "mxbai-embed-large",    "family": "MixedBread",  "description": "MixBread Embed Large — high-quality embeddings",           "ram": "~0.7 GB"},
    {"id": "command-r:35b",        "family": "Cohere",      "description": "Command-R 35B — RAG-optimised model",                     "ram": "~21 GB"},
    {"id": "vicuna:7b",            "family": "LMSYS",       "description": "Vicuna 7B — instruction-tuned",                            "ram": "~4 GB"},
    {"id": "vicuna:13b",           "family": "LMSYS",       "description": "Vicuna 13B",                                               "ram": "~8 GB"},
    {"id": "zephyr:7b",            "family": "HuggingFace", "description": "Zephyr 7B — aligned RLHF assistant",                       "ram": "~4 GB"},
    {"id": "solar:10.7b",          "family": "Upstage",     "description": "Solar 10.7B",                                              "ram": "~7 GB"},
    {"id": "tinyllama:1.1b",       "family": "TinyLlama",   "description": "TinyLlama 1.1B — very lightweight",                        "ram": "~0.7 GB"},
    {"id": "stablelm2:1.6b",       "family": "Stability",   "description": "StableLM 2 1.6B",                                         "ram": "~1 GB"},
    {"id": "neural-chat:7b",       "family": "Intel",       "description": "Neural Chat 7B by Intel",                                  "ram": "~4 GB"},
    {"id": "openhermes:7b",        "family": "NousResearch","description": "OpenHermes 2.5 7B",                                        "ram": "~4 GB"},
    {"id": "orca-mini:3b",         "family": "Orca",        "description": "Orca Mini 3B",                                             "ram": "~2 GB"},
    {"id": "orca-mini:7b",         "family": "Orca",        "description": "Orca Mini 7B",                                             "ram": "~4 GB"},
]

# ── Ollama model verdicts store ───────────────────────────────────────────────
# Single file: bot/ollama_models.json  {"tested": [...], "incompatible": [...]}
# Migrates automatically from the old split-file format on first read.

_OLLAMA_MODELS_FILE = _PROJECT_ROOT / "bot" / "ollama_models.json"
_OLD_TESTED_FILE = _PROJECT_ROOT / "bot" / "tested_models.json"
_OLD_INCOMPATIBLE_FILE = _PROJECT_ROOT / "bot" / "incompatible_models.json"


def _load_ollama_models() -> dict[str, set[str]]:
    """Load verdict store, migrating from old split files if needed."""
    # Auto-migrate from old split files (runs once)
    if not _OLLAMA_MODELS_FILE.exists() and (_OLD_TESTED_FILE.exists() or _OLD_INCOMPATIBLE_FILE.exists()):
        tested: set[str] = set()
        incompatible: set[str] = set()
        try:
            tested = set(json.loads(_OLD_TESTED_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
        try:
            incompatible = set(json.loads(_OLD_INCOMPATIBLE_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
        _save_ollama_models({"tested": tested, "incompatible": incompatible})
        # Remove old files
        for f in (_OLD_TESTED_FILE, _OLD_INCOMPATIBLE_FILE):
            try:
                f.unlink()
            except Exception:
                pass

    try:
        raw = json.loads(_OLLAMA_MODELS_FILE.read_text(encoding="utf-8"))
        return {
            "tested": set(raw.get("tested", [])),
            "incompatible": set(raw.get("incompatible", [])),
        }
    except Exception:
        return {"tested": set(), "incompatible": set()}


def _save_ollama_models(store: dict[str, set[str]]) -> None:
    _OLLAMA_MODELS_FILE.write_text(
        json.dumps(
            {"tested": sorted(store["tested"]), "incompatible": sorted(store["incompatible"])},
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_tested_models() -> set[str]:
    return _load_ollama_models()["tested"]


def _load_incompatible_models() -> set[str]:
    return _load_ollama_models()["incompatible"]


def _save_tested_model(model: str) -> None:
    store = _load_ollama_models()
    store["tested"].add(model)
    _save_ollama_models(store)


def _remove_tested_model(model: str) -> None:
    store = _load_ollama_models()
    store["tested"].discard(model)
    _save_ollama_models(store)


def _save_incompatible_model(model: str) -> None:
    store = _load_ollama_models()
    store["incompatible"].add(model)
    _save_ollama_models(store)


def _remove_incompatible_model(model: str) -> None:
    store = _load_ollama_models()
    store["incompatible"].discard(model)
    _save_ollama_models(store)


def _is_compatible(model_name: str) -> bool:
    return True  # kept for API compatibility; removed hardcoded rules



@router.get("/ollama/catalog")
async def ollama_catalog(q: str = ""):
    """Return the Ollama model catalog (static list), pre-filtered to exclude installed models."""
    import requests as _req

    base = _ollama_base()
    try:
        r = _req.get(f"{base}/api/tags", timeout=5)
        r.raise_for_status()
        installed_names = {m["name"] for m in r.json().get("models", [])}
        # Also match base name (e.g. "llama3.2" matches "llama3.2:3b" installed as "llama3.2:3b")
        installed_base = {n.split(":")[0] for n in installed_names}
    except Exception:
        installed_names = set()
        installed_base = set()

    q_lower = q.strip().lower()
    catalog = []
    for m in _OLLAMA_STATIC_CATALOG:
        if m["id"] in installed_names:
            continue
        if q_lower and q_lower not in m["id"].lower() and q_lower not in m["family"].lower() and q_lower not in m["description"].lower():
            continue
        catalog.append(m)

    return JSONResponse(content={"catalog": catalog, "installed": list(installed_names)})


class MarkTestedRequest(BaseModel):
    model: str

@router.post("/ollama/tested")
async def ollama_mark_tested(req: MarkTestedRequest):
    """Mark a model as successfully tested with HouseBot."""
    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model name is required")
    _save_tested_model(model)
    _remove_incompatible_model(model)  # un-flag if previously marked incompatible
    logger.info("✅ Model marked as tested: %s", model)
    return JSONResponse(content={"ok": True, "model": model, "tested": sorted(_load_tested_models())})


class MarkIncompatibleRequest(BaseModel):
    model: str

@router.post("/ollama/incompatible")
async def ollama_mark_incompatible(req: MarkIncompatibleRequest):
    """Mark a model as incompatible with HouseBot."""
    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model name is required")
    _save_incompatible_model(model)
    _remove_tested_model(model)  # un-flag if previously marked tested
    logger.info("⚠️ Model marked as incompatible: %s", model)
    return JSONResponse(content={"ok": True, "model": model, "incompatible": sorted(_load_incompatible_models())})


class DeleteModelRequest(BaseModel):
    model: str


@router.delete("/ollama/models")
async def ollama_delete_model(req: DeleteModelRequest):
    """Delete a locally pulled Ollama model via the Ollama API."""
    import requests as _req

    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model name is required")

    base = _ollama_base()
    try:
        r = _req.delete(f"{base}/api/delete", json={"name": model}, timeout=15)
        if r.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Model '{model}' not found locally")
        r.raise_for_status()
        logger.info("🗑️  Model deleted: %s", model)
        return JSONResponse(content={"ok": True, "model": model})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama unreachable: {e}")


# ── Service Control ─────────────────────────────────────────────────────────

_VENV_PYTHON = str(_PROJECT_ROOT / ".venv" / "bin" / "python")
_BOT_DIR = str(_PROJECT_ROOT / "bot")
_BRIDGE_JS = str(_PROJECT_ROOT / "bridge" / "index.js")
_LOG_LEVEL = os.getenv("LOG_LEVEL", "info").lower()


def _start_fastapi():
    log = (_LOG_DIR / "fastapi.log").open("a")
    p = subprocess.Popen(
        [_VENV_PYTHON, "-m", "uvicorn", "main:app", "--port", "8000", "--log-level", _LOG_LEVEL],
        cwd=_BOT_DIR, stdout=log, stderr=log,
    )
    (_LOG_DIR / "fastapi.pid").write_text(str(p.pid))


def _start_bridge():
    log = (_LOG_DIR / "bridge.log").open("a")
    p = subprocess.Popen(
        ["node", _BRIDGE_JS],
        stdout=log, stderr=log,
    )
    (_LOG_DIR / "bridge.pid").write_text(str(p.pid))


def _start_scheduler():
    # Kill any existing scheduler first
    subprocess.run(["pkill", "-f", "scheduler.py"], capture_output=True)
    log = (_LOG_DIR / "scheduler.log").open("a")
    p = subprocess.Popen(
        [_VENV_PYTHON, "scheduler.py"],
        cwd=_BOT_DIR, stdout=log, stderr=log,
    )
    (_LOG_DIR / "scheduler.pid").write_text(str(p.pid))


def _stop_service(name: str):
    """Stop a service by PID file, then force-kill by port for fastapi."""
    pid = _read_pid(name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        pid_file = _LOG_DIR / f"{name}.pid"
        pid_file.unlink(missing_ok=True)
    if name == "fastapi":
        subprocess.run(["bash", "-c", "lsof -ti :8000 | xargs kill -9 2>/dev/null"], check=False)
    if name == "scheduler":
        subprocess.run(["pkill", "-f", "scheduler.py"], capture_output=True)


@router.post("/services/{service}/restart")
async def service_restart(service: str):
    """Restart fastapi, bridge, or scheduler."""
    if service not in ("fastapi", "bridge", "scheduler"):
        raise HTTPException(status_code=400, detail=f"Unknown service '{service}'")

    _stop_service(service)

    import asyncio
    await asyncio.sleep(1.5)

    if service == "fastapi":
        _start_fastapi()
    elif service == "bridge":
        _start_bridge()
    elif service == "scheduler":
        _start_scheduler()

    logger.info("🔄 Service restarted: %s", service)
    return JSONResponse(content={"ok": True, "service": service, "action": "restart"})


@router.post("/services/{service}/stop")
async def service_stop(service: str):
    """Stop fastapi, bridge, or scheduler."""
    if service not in ("fastapi", "bridge", "scheduler"):
        raise HTTPException(status_code=400, detail=f"Unknown service '{service}'")
    _stop_service(service)
    logger.info("⏹️  Service stopped: %s", service)
    return JSONResponse(content={"ok": True, "service": service, "action": "stop"})


@router.post("/services/{service}/start")
async def service_start(service: str):
    """Start fastapi, bridge, or scheduler if not already running."""
    if service not in ("fastapi", "bridge", "scheduler"):
        raise HTTPException(status_code=400, detail=f"Unknown service '{service}'")
    pid = _read_pid(service)
    if pid:
        return JSONResponse(content={"ok": True, "service": service, "action": "already_running", "pid": pid})
    if service == "fastapi":
        _start_fastapi()
    elif service == "bridge":
        _start_bridge()
    elif service == "scheduler":
        _start_scheduler()
    logger.info("▶️  Service started: %s", service)
    return JSONResponse(content={"ok": True, "service": service, "action": "start"})


_HOUSEBOT_SH = str(_PROJECT_ROOT / "housebot.sh")


def _run_housebot_detached(command: str) -> None:
    """Run housebot.sh <command> in a fully detached process.

    Uses 'sleep 3 &&' so FastAPI has time to send the HTTP response before
    housebot.sh stop/restart kills this process.
    """
    subprocess.Popen(
        ["bash", "-c", f"sleep 3 && bash '{_HOUSEBOT_SH}' {command}"],
        close_fds=True,
        start_new_session=True,  # detach from this process group
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


@router.post("/services/restart-all")
async def restart_all():
    """Restart all HouseBot services via housebot.sh restart."""
    _run_housebot_detached("restart")
    logger.info("🔄 Restart-all delegated to housebot.sh (detached)")
    return JSONResponse(content={"ok": True, "action": "restart-all"})


@router.post("/services/stop-all")
async def stop_all():
    """Stop all HouseBot services via housebot.sh stop."""
    _run_housebot_detached("stop")
    logger.info("⏹️  Stop-all delegated to housebot.sh (detached)")
    return JSONResponse(content={"ok": True, "action": "stop-all"})


@router.post("/services/start-all")
async def start_all():
    """Start all HouseBot services via housebot.sh start."""
    _run_housebot_detached("start")
    logger.info("▶️  Start-all delegated to housebot.sh (detached)")
    return JSONResponse(content={"ok": True, "action": "start-all"})


# ── Prompt Editor ────────────────────────────────────────────────────────────

_PROMPTS_DIR = _PROJECT_ROOT / "bot" / "prompts"


class SavePromptRequest(BaseModel):
    text: str


@router.get("/prompts/{skill}")
async def get_prompt(skill: str):
    """Return the current prompt text for a skill (override or default)."""
    from skills import shopping as _s, weather as _w, calendar as _c  # ensure registered  # noqa: F401
    from skills.registry import get_prompt_text, list_prompt_categories

    allowed = list_prompt_categories()
    if skill not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown skill '{skill}'. Known: {allowed}")

    text = get_prompt_text(skill)
    if text is None:
        raise HTTPException(status_code=404, detail=f"No prompt registered for '{skill}'")

    override_file = _PROMPTS_DIR / f"{skill}.txt"
    return JSONResponse(content={
        "skill": skill,
        "text": text,
        "is_override": override_file.exists(),
    })


@router.put("/prompts/{skill}")
async def save_prompt(skill: str, req: SavePromptRequest):
    """Save an edited prompt to bot/prompts/{skill}.txt (hot-reload, no restart needed)."""
    from skills import shopping as _s, weather as _w, calendar as _c  # noqa: F401
    from skills.registry import list_prompt_categories

    allowed = list_prompt_categories()
    if skill not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown skill '{skill}'. Known: {allowed}")

    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Prompt text cannot be empty")

    _PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    override_file = _PROMPTS_DIR / f"{skill}.txt"
    override_file.write_text(text, encoding="utf-8")
    logger.info("✏️  Prompt override saved: %s", override_file)
    return JSONResponse(content={"ok": True, "skill": skill, "is_override": True})


@router.delete("/prompts/{skill}")
async def reset_prompt(skill: str):
    """Delete the override file, reverting to the Python default prompt."""
    from skills import shopping as _s, weather as _w, calendar as _c  # noqa: F401
    from skills.registry import list_prompt_categories

    allowed = list_prompt_categories()
    if skill not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown skill '{skill}'")

    override_file = _PROMPTS_DIR / f"{skill}.txt"
    if override_file.exists():
        override_file.unlink()
        logger.info("↩️  Prompt reset to default: %s", skill)
        return JSONResponse(content={"ok": True, "skill": skill, "is_override": False})
    return JSONResponse(content={"ok": True, "skill": skill, "is_override": False, "note": "already default"})


# ── Installation Wizard ──────────────────────────────────────────────────────

class PullModelRequest(BaseModel):
    model: str


class ChatTestRequest(BaseModel):
    model: str
    message: str


@router.post("/install/ollama/pull")
async def install_ollama_pull(req: PullModelRequest):
    """
    Stream ollama model pull progress as Server-Sent Events.
    Each event is a raw JSON line from Ollama's /api/pull response.
    A final {"done": true} event signals completion.
    """
    import json as _json
    import requests as _req

    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")

    base = _ollama_base()

    def _stream():
        try:
            with _req.post(
                f"{base}/api/pull",
                json={"model": model},
                stream=True,
                timeout=3600,
            ) as r:
                for raw in r.iter_lines():
                    if raw:
                        yield f"data: {raw.decode('utf-8')}\n\n"
        except Exception as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
        yield 'data: {"done":true}\n\n'

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/install/ollama/pull/cancel")
async def install_ollama_pull_cancel(req: PullModelRequest):
    """
    Cancel an in-flight model pull and delete any partial blobs from Ollama's cache.
    The client is responsible for aborting the SSE fetch; this endpoint cleans up.
    """
    import requests as _req

    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model is required")

    base = _ollama_base()
    try:
        r = _req.delete(f"{base}/api/delete", json={"name": model}, timeout=15)
        # 404 means nothing was cached yet — treat as success
        if r.status_code not in (200, 404):
            r.raise_for_status()
    except Exception as e:
        logger.warning("⚠️  Could not clean up partial pull for %s: %s", model, e)

    logger.info("🚫 Pull cancelled and cleaned up: %s", model)
    return JSONResponse(content={"ok": True, "model": model})


@router.post("/install/ollama/chat")
async def install_ollama_chat(req: ChatTestRequest):
    """
    Stream a chat prompt to Ollama as Server-Sent Events.
    Each event carries a JSON token: {"token": "..."}.
    A final {"done": true} event signals the end of the response.
    """
    import json as _json
    import requests as _req

    model = req.model.strip()
    message = req.message.strip()
    if not model or not message:
        raise HTTPException(status_code=400, detail="model and message are required")

    base = _ollama_base()

    def _stream():
        # Yield an SSE comment immediately so the proxy/browser knows the
        # connection is alive even while Ollama is loading the model (~10s).
        yield ': connected\n\n'
        try:
            with _req.post(
                f"{base}/api/generate",
                json={"model": model, "prompt": message, "stream": True},
                stream=True,
                timeout=120,
            ) as r:
                for raw in r.iter_lines():
                    if not raw:
                        continue
                    try:
                        chunk = _json.loads(raw.decode("utf-8"))
                        token = chunk.get("response", "")
                        if token:
                            yield f"data: {_json.dumps({'token': token})}\n\n"
                        if chunk.get("done"):
                            break
                    except Exception:
                        pass
        except Exception as exc:
            yield f"data: {_json.dumps({'error': str(exc)})}\n\n"
        yield 'data: {"done":true}\n\n'

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Keep-alive setting ───────────────────────────────────────────────────────

@router.get("/install/system-info")
async def install_system_info():
    """Return system RAM in GB (macOS only via sysctl)."""
    try:
        raw = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
        ram_gb = int(raw) // (1024 ** 3)
    except Exception:
        ram_gb = None
    return JSONResponse(content={"ram_gb": ram_gb})


@router.get("/install/ollama/keep-alive")
async def get_keep_alive():
    """Return the current OLLAMA_KEEP_ALIVE value from .env (or OS env)."""
    value = os.getenv("OLLAMA_KEEP_ALIVE", "")
    return JSONResponse(content={"value": value})


class KeepAliveRequest(BaseModel):
    value: str


@router.post("/install/ollama/keep-alive")
async def set_keep_alive(req: KeepAliveRequest):
    """Write OLLAMA_KEEP_ALIVE to .env."""
    value = req.value.strip()
    _env_set("OLLAMA_KEEP_ALIVE", value)
    os.environ["OLLAMA_KEEP_ALIVE"] = value
    logger.info("⏱️  OLLAMA_KEEP_ALIVE set to %s", value)
    return JSONResponse(content={"ok": True, "value": value})


# ── Whisper model ─────────────────────────────────────────────────────────────

WHISPER_MODELS = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]


@router.get("/install/whisper/model")
async def get_whisper_model():
    """Return the current WHISPER_MODEL value from .env (or OS env)."""
    value = os.getenv("WHISPER_MODEL", "small") or "small"
    return JSONResponse(content={"value": value})


class WhisperModelRequest(BaseModel):
    value: str


@router.post("/install/whisper/model")
async def set_whisper_model(req: WhisperModelRequest):
    """Write WHISPER_MODEL to .env."""
    value = req.value.strip()
    if value not in WHISPER_MODELS:
        raise HTTPException(status_code=400, detail=f"Invalid model. Choose one of: {', '.join(WHISPER_MODELS)}")
    _env_set("WHISPER_MODEL", value)
    os.environ["WHISPER_MODEL"] = value
    logger.info("🎙️  WHISPER_MODEL set to %s", value)
    return JSONResponse(content={"ok": True, "value": value})


# ── WhatsApp App Name ────────────────────────────────────────────────────────

class WaAppNameRequest(BaseModel):
    value: str


@router.get("/install/wa-app-name")
async def get_wa_app_name():
    """Return the current WHATSAPP_APPNAME from env."""
    return JSONResponse(content={"value": os.getenv("WHATSAPP_APPNAME", "HouseBot")})


@router.post("/install/wa-app-name")
async def set_wa_app_name(req: WaAppNameRequest):
    """Write WHATSAPP_APPNAME to .env (max 20 chars)."""
    name = req.value.strip()[:20] or "HouseBot"
    _env_set("WHATSAPP_APPNAME", name)
    os.environ["WHATSAPP_APPNAME"] = name
    logger.info("📱 WHATSAPP_APPNAME set to %s", name)
    return JSONResponse(content={"ok": True, "value": name})


# ── WhatsApp QR Proxy ───────────────────────────────────────────────────────

@router.get("/install/whatsapp/qr")
async def install_whatsapp_qr():
    """
    Proxy the /qr endpoint on the WhatsApp bridge (port 3001).
    Returns:
      {"connected": true}                          – already paired
      {"connected": false, "qr": "data:image/png;base64,..."}  – QR available
      503 – bridge unreachable or QR not yet generated
    """
    import requests as _req
    try:
        r = _req.get("http://localhost:3001/qr", timeout=5)
        return JSONResponse(content=r.json(), status_code=r.status_code)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Bridge unreachable: {exc}")


# ── WhatsApp Disconnect ───────────────────────────────────────────────────────

@router.post("/install/whatsapp/disconnect")
async def whatsapp_disconnect():
    """
    Disconnect the WhatsApp session:
    1. Stop the bridge
    2. Wipe all Baileys auth files
    3. Restart the bridge (will regenerate a fresh QR)
    """
    import asyncio
    import shutil

    _stop_service("bridge")
    await asyncio.sleep(1.0)

    auth_dir = _PROJECT_ROOT / "bridge" / "baileys_auth"
    if auth_dir.exists():
        shutil.rmtree(auth_dir)
    auth_dir.mkdir(exist_ok=True)

    _start_bridge()
    logger.info("📱 WhatsApp session disconnected — bridge restarted for fresh QR")
    return JSONResponse(content={"ok": True})


# ── Google OAuth endpoints ────────────────────────────────────────────────────

@router.get("/install/google-auth/status")
@router.get("/google-auth/status")
async def google_auth_status():
    """Return the current Google OAuth token status."""
    info = _google_token_status()
    info["credentials_exist"] = _CREDS_PATH.exists()
    info["flow_running"] = _google_oauth["running"]
    if _google_oauth["error"]:
        info["flow_error"] = _google_oauth["error"]
    return JSONResponse(content=info)


@router.post("/install/google-auth")
@router.post("/google-auth")
async def google_auth_start():
    """
    Start the Google OAuth flow.
    Spins up a temporary HTTP server on port 8787 in a background thread,
    returns the authorization URL for the user to open in a browser.
    Google redirects back to http://localhost:8787/ after authorization.
    """
    if not _CREDS_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="creds/client_google_api_calendar.json not found — upload your Google OAuth credentials first.",
        )

    if _google_oauth["running"]:
        return JSONResponse(
            content={"ok": False, "detail": "An OAuth flow is already in progress."},
            status_code=409,
        )

    # Allow HTTP for the local loopback redirect URI.
    # This is safe — traffic never leaves localhost.
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    from google_auth_oauthlib.flow import Flow

    redirect_uri = f"http://localhost:{_GOOGLE_CALLBACK_PORT}/"
    flow = Flow.from_client_secrets_file(
        str(_CREDS_PATH),
        scopes=_GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
    )
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent")

    _google_oauth["running"] = True
    _google_oauth["error"] = None

    def _serve_callback() -> None:
        class _SilentHandler(wsgiref.simple_server.WSGIRequestHandler):
            def log_message(self, *args):  # suppress request logs
                pass

        def _wsgi_app(environ, start_response):
            qs = environ.get("QUERY_STRING", "")
            path = environ.get("PATH_INFO", "/")
            auth_response = f"http://localhost:{_GOOGLE_CALLBACK_PORT}{path}{'?' + qs if qs else ''}"
            start_response("200 OK", [("Content-Type", "text/html; charset=utf-8")])
            try:
                os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
                flow.fetch_token(authorization_response=auth_response)
                _TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
                _TOKEN_PATH.write_text(flow.credentials.to_json(), encoding="utf-8")
                logger.info("✅ Google OAuth token saved to %s", _TOKEN_PATH)
                body = (
                    b"<html><head><title>HouseBot</title></head><body>"
                    b"<script>window.close();</script>"
                    b"<p style='font-family:sans-serif;padding:2rem'>Authorization successful! "
                    b"You can close this tab.</p></body></html>"
                )
            except Exception as exc:
                logger.error("Google OAuth callback error: %s", exc)
                _google_oauth["error"] = str(exc)
                body = (
                    f"<html><body><p>Error: {exc}</p></body></html>"
                ).encode("utf-8")
            return [body]

        try:
            server = wsgiref.simple_server.make_server(
                "127.0.0.1", _GOOGLE_CALLBACK_PORT, _wsgi_app, handler_class=_SilentHandler
            )
            server.timeout = 300  # 5-minute window for the user to complete auth
            server.handle_request()
        except Exception as exc:
            logger.error("Google OAuth local server error: %s", exc)
            _google_oauth["error"] = str(exc)
        finally:
            _google_oauth["running"] = False

    threading.Thread(target=_serve_callback, daemon=True).start()

    return JSONResponse(content={"ok": True, "auth_url": auth_url})


@router.post("/install/google-auth/refresh")
@router.post("/google-auth/refresh")
async def google_auth_refresh():
    """Refresh an expired Google OAuth token using the stored refresh_token."""
    if not _TOKEN_PATH.exists():
        raise HTTPException(status_code=404, detail="No token.json found — authorize first.")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _GOOGLE_SCOPES)
        if not creds.refresh_token:
            raise HTTPException(
                status_code=400,
                detail="No refresh token stored — run full re-authorization.",
            )
        creds.refresh(Request())
        _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        logger.info("🔄 Google OAuth token refreshed")
        return JSONResponse(content={"ok": True, "status": "valid"})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/install/google-auth")
@router.delete("/google-auth")
async def google_auth_revoke():
    """Delete the stored Google OAuth token (requires re-authorization afterwards)."""
    if _TOKEN_PATH.exists():
        _TOKEN_PATH.unlink()
        logger.info("🗑️  Google token revoked (token.json deleted)")
    return JSONResponse(content={"ok": True, "status": "missing"})


class SaveCredentialsRequest(BaseModel):
    content: str  # raw JSON text of the Google OAuth client credentials


@router.put("/install/google-auth/credentials")
@router.put("/google-auth/credentials")
async def google_save_credentials(req: SaveCredentialsRequest):
    """
    Validate and save the Google OAuth client credentials JSON to
    creds/client_google_api_calendar.json.
    """
    raw = req.content.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Credentials content is empty.")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    # Must have the expected Google OAuth structure
    if not isinstance(parsed, dict) or not (parsed.get("web") or parsed.get("installed")):
        raise HTTPException(
            status_code=400,
            detail="Not a valid Google OAuth credentials file — expected a 'web' or 'installed' key.",
        )
    client_section = parsed.get("web") or parsed.get("installed")
    if not (client_section.get("client_id") and client_section.get("client_secret")):
        raise HTTPException(
            status_code=400,
            detail="Credentials file is missing 'client_id' or 'client_secret'.",
        )

    _CREDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CREDS_PATH.write_text(raw, encoding="utf-8")
    logger.info("✅ Google OAuth credentials saved to %s", _CREDS_PATH)
    return JSONResponse(content={"ok": True})


@router.get("/install/google-auth/calendars")
@router.get("/google-auth/calendars")
async def google_list_calendars():
    """List all Google Calendars available to the authorized account."""
    if not _TOKEN_PATH.exists():
        raise HTTPException(status_code=400, detail="No token found — authorize first.")
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), _GOOGLE_SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        service = build("calendar", "v3", credentials=creds)
        items: list = []
        page_token = None
        while True:
            kwargs = {"pageToken": page_token} if page_token else {}
            result = service.calendarList().list(**kwargs).execute()
            items.extend(result.get("items", []))
            page_token = result.get("nextPageToken")
            if not page_token:
                break
        calendars = [
            {
                "id": c["id"],
                "name": c["summary"],
                "primary": c.get("primary", False),
            }
            for c in items
        ]
        configured = os.getenv("GOOGLE_CALENDAR_NAME", "")
        return JSONResponse(content={"calendars": calendars, "configured": configured})
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class SetCalendarRequest(BaseModel):
    name: str


@router.post("/install/google-auth/calendar")
@router.post("/google-auth/calendar")
async def google_set_calendar(req: SetCalendarRequest):
    """Save the chosen Google Calendar name to .env."""
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Calendar name is required.")
    _env_set("GOOGLE_CALENDAR_NAME", name)
    os.environ["GOOGLE_CALENDAR_NAME"] = name
    logger.info("📅 GOOGLE_CALENDAR_NAME set to '%s'", name)
    return JSONResponse(content={"ok": True, "name": name})


# ── Sender Restrictions (Install Wizard) ─────────────────────────────────────

class AuthorizeSenderRequest(BaseModel):
    jid: str
    name: str = ""


def _parse_partner_entries(raw: str) -> list[dict]:
    """Parse 'jid:name,...' or plain 'jid,...' into [{jid, name}, ...]."""
    result = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            jid, _, name = entry.partition(":")
            result.append({"jid": jid.strip(), "name": name.strip()})
        else:
            result.append({"jid": entry, "name": ""})
    return result


def _partners_list() -> list[dict]:
    """Return [{jid, name}, ...] parsed from PARTNER_LID (jid:name format)."""
    return _parse_partner_entries(os.getenv("PARTNER_LID", ""))


@router.get("/install/sender-restrictions")
async def get_sender_restrictions():
    """Return the current list of authorized senders (PARTNER_LID + PARTNER_NAMES)."""
    return JSONResponse(content={"partners": _partners_list()})


@router.post("/install/sender-restrictions/scan")
async def scan_sender_restrictions():
    """
    Parse bridge.log for recent sender JIDs.
    Looks for two log patterns emitted by the bridge:
      1. '🚫 Message ignored from: <JID>' — sender not in PARTNER_LID
      2. '🔍 Message — remoteJid: <JID> | fromMe: false' — visible before partner check
    The second pattern also catches the case where fromMe:true silently drops the
    message (personal account), exposing the JID for the user to add.
    Returns a de-duplicated list of detected senders.
    """
    log_path = _KNOWN_LOGS["bridge"]
    if not log_path.exists():
        return JSONResponse(content={"senders": [], "note": "bridge.log not found"})

    authorized = {e["jid"] for e in _parse_partner_entries(os.getenv("PARTNER_LID", ""))}

    tail: deque[str] = deque(maxlen=500)
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                tail.append(line.rstrip("\n"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not read bridge.log: {e}")

    # Pattern 1: explicit "ignored" line — carries name
    ignored_pattern    = re.compile(r"Message ignored from: (\S+@\S+)(?: \(name: (.+?)\))?")
    # Pattern 2: diagnostic line logged before all filters (lenient middle match)
    diagnostic_pattern = re.compile(r"Message .+ remoteJid: (\S+@\S+) \| fromMe: \S+ \| pushName: (.+)")
    # Pattern 3: fromMe skip line — logged when personal-number mode, JID not yet configured
    fromme_pattern     = re.compile(r"Skipped .+ fromMe and (\S+@\S+) is not a configured partner")

    seen: dict[str, dict] = {}

    def _add(jid: str, name: str) -> None:
        if jid.endswith("@g.us"):
            return  # group JIDs are never used for sender filtering
        if jid not in seen:
            seen[jid] = {
                "jid": jid,
                "type": jid.split("@")[1] if "@" in jid else "",
                "name": name if name not in ("unknown", "") else "",
                "already_authorized": jid in authorized,
            }

    for line in tail:
        m = ignored_pattern.search(line)
        if m:
            _add(m.group(1), (m.group(2) or "").strip())
            continue

        m2 = diagnostic_pattern.search(line)
        if m2:
            _add(m2.group(1), m2.group(2).strip())
            continue

        m3 = fromme_pattern.search(line)
        if m3:
            _add(m3.group(1), "")

    return JSONResponse(content={"senders": list(seen.values())})


@router.post("/install/sender-restrictions/authorize")
async def authorize_sender(req: AuthorizeSenderRequest):
    """Append a jid:name entry to PARTNER_LID in .env."""
    jid  = req.jid.strip()
    # Sanitize name: colons and commas would break the format
    name = req.name.strip().replace(":", "-").replace(",", " ")
    if not jid or "@" not in jid:
        raise HTTPException(status_code=400, detail="Invalid JID — expected <number>@<domain>")

    current_entries = _parse_partner_entries(os.getenv("PARTNER_LID", ""))
    if any(e["jid"] == jid for e in current_entries):
        return JSONResponse(content={"ok": True, "partners": _partners_list(), "note": "already authorized"})

    current_entries.append({"jid": jid, "name": name})
    new_value = ",".join(
        f"{e['jid']}:{e['name']}" if e["name"] else e["jid"]
        for e in current_entries
    )
    _env_set("PARTNER_LID", new_value)
    os.environ["PARTNER_LID"] = new_value

    # Hot-reload the bridge's in-memory partner list so the new JID takes
    # effect immediately without restarting the bridge process.
    try:
        import requests as _req
        _req.post("http://localhost:3001/reload-partners", timeout=3)
    except Exception:
        pass  # bridge may not be running; non-fatal

    logger.info("✅ Sender authorized: %s (%s)", jid, name or "no name")
    return JSONResponse(content={"ok": True, "partners": _partners_list()})


class RemoveSenderRequest(BaseModel):
    jid: str


@router.delete("/install/sender-restrictions")
async def remove_sender(req: RemoveSenderRequest):
    """Remove a JID from PARTNER_LID in .env and hot-reload the bridge."""
    jid = req.jid.strip()
    if not jid or "@" not in jid:
        raise HTTPException(status_code=400, detail="Invalid JID")

    entries = _parse_partner_entries(os.getenv("PARTNER_LID", ""))
    filtered = [e for e in entries if e["jid"] != jid]
    if len(filtered) == len(entries):
        raise HTTPException(status_code=404, detail="JID not found in PARTNER_LID")

    new_value = ",".join(
        f"{e['jid']}:{e['name']}" if e["name"] else e["jid"]
        for e in filtered
    )
    _env_set("PARTNER_LID", new_value)
    os.environ["PARTNER_LID"] = new_value

    try:
        import requests as _req
        _req.post("http://localhost:3001/reload-partners", timeout=3)
    except Exception:
        pass

    logger.info("🗑️  Sender removed: %s", jid)
    return JSONResponse(content={"ok": True, "partners": _partners_list()})


# ── Location & Briefing Settings (Install Wizard) ────────────────────────────

_TIMEZONES = [
    "Africa/Abidjan", "Africa/Cairo", "Africa/Johannesburg", "Africa/Lagos",
    "America/Argentina/Buenos_Aires", "America/Bogota", "America/Chicago",
    "America/Denver", "America/Los_Angeles", "America/Mexico_City",
    "America/New_York", "America/Sao_Paulo", "America/Toronto",
    "Asia/Bangkok", "Asia/Dubai", "Asia/Hong_Kong", "Asia/Kolkata",
    "Asia/Jakarta", "Asia/Seoul", "Asia/Shanghai", "Asia/Singapore",
    "Asia/Tokyo", "Australia/Melbourne", "Australia/Sydney",
    "Europe/Amsterdam", "Europe/Athens", "Europe/Berlin", "Europe/Brussels",
    "Europe/Bucharest", "Europe/Copenhagen", "Europe/Dublin",
    "Europe/Helsinki", "Europe/Istanbul", "Europe/Lisbon", "Europe/London",
    "Europe/Madrid", "Europe/Moscow", "Europe/Oslo", "Europe/Paris",
    "Europe/Prague", "Europe/Rome", "Europe/Stockholm", "Europe/Vienna",
    "Europe/Warsaw", "Europe/Zurich", "Pacific/Auckland", "Pacific/Honolulu",
    "UTC",
]


class LocationSettingsRequest(BaseModel):
    city: str
    latitude: float
    longitude: float
    timezone: str
    briefing_language: str


@router.get("/install/location")
async def get_location_settings():
    """Return current location and briefing settings from env."""
    return JSONResponse(content={
        "city":              os.getenv("DEFAULT_CITY", ""),
        "latitude":          os.getenv("DEFAULT_LATITUDE", ""),
        "longitude":         os.getenv("DEFAULT_LONGITUDE", ""),
        "timezone":          os.getenv("TIMEZONE_DEFAULT", ""),
        "briefing_language": os.getenv("BRIEFING_LANGUAGE", "English"),
        "timezones":         _TIMEZONES,
    })


@router.post("/install/location")
async def save_location_settings(req: LocationSettingsRequest):
    """Persist location and briefing settings to .env."""
    city = req.city.strip()
    timezone = req.timezone.strip()
    lang = req.briefing_language.strip()

    if not city:
        raise HTTPException(status_code=400, detail="City name is required")
    if not (-90 <= req.latitude <= 90):
        raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if not (-180 <= req.longitude <= 180):
        raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")

    _env_set("DEFAULT_CITY",      city)
    _env_set("DEFAULT_LATITUDE",  str(round(req.latitude,  6)))
    _env_set("DEFAULT_LONGITUDE", str(round(req.longitude, 6)))
    _env_set("TIMEZONE_DEFAULT",  timezone)
    _env_set("BRIEFING_LANGUAGE", lang)

    os.environ["DEFAULT_CITY"]      = city
    os.environ["DEFAULT_LATITUDE"]  = str(round(req.latitude,  6))
    os.environ["DEFAULT_LONGITUDE"] = str(round(req.longitude, 6))
    os.environ["TIMEZONE_DEFAULT"]  = timezone
    os.environ["BRIEFING_LANGUAGE"] = lang

    logger.info("✅ Location settings saved: %s (%.4f, %.4f) tz=%s lang=%s",
                city, req.latitude, req.longitude, timezone, lang)
    return JSONResponse(content={"ok": True})
