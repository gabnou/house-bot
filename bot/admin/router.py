import os
import re
import signal
import logging
import subprocess
from collections import deque
from pathlib import Path
from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
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
        models = [
            {
                "name": m["name"],
                "size_gb": round(m.get("size", 0) / 1e9, 1),
                "modified": m.get("modified_at", ""),
                "family": m.get("details", {}).get("family", ""),
                "params": m.get("details", {}).get("parameter_size", ""),
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


class SwitchModelRequest(BaseModel):
    model: str


@router.post("/ollama/switch")
async def ollama_switch(req: SwitchModelRequest):
    """
    Switch the active Ollama model:
    1. Write OLLAMA_MODEL=<model> to .env
    2. Unload the current model (ollama stop)
    3. Warm up the new model in the background (ollama run <model> "")
    """
    import requests as _req

    model = req.model.strip()
    if not model:
        raise HTTPException(status_code=400, detail="model name is required")

    base = _ollama_base()

    # 1. Persist to .env
    _env_set("OLLAMA_MODEL", model)
    os.environ["OLLAMA_MODEL"] = model

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

    logger.info("🧠 Model switched to %s", model)
    return JSONResponse(content={"ok": True, "model": model})


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


@router.post("/services/restart-all")
async def restart_all():
    """Restart FastAPI, Bridge, and Scheduler."""
    for svc in ("fastapi", "bridge", "scheduler"):
        _stop_service(svc)
    import asyncio
    await asyncio.sleep(2)
    _start_bridge()
    _start_scheduler()
    # FastAPI restart is self-defeating since it kills itself — signal the process group instead
    logger.info("🔄 All services restarting")
    return JSONResponse(content={"ok": True, "action": "restart-all"})


@router.post("/services/stop-all")
async def stop_all():
    """Stop FastAPI, Bridge, and Scheduler."""
    for svc in ("bridge", "scheduler"):
        _stop_service(svc)
    logger.info("⏹️  Bridge + Scheduler stopped")
    return JSONResponse(content={"ok": True, "action": "stop-all"})


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
