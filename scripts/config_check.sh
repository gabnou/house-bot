#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# config_check.sh — HouseBot environment & configuration check
#
# Purpose:
#   Verifies that all required tools, runtimes, and AI models are correctly
#   installed and configured. Run this after installation or before deploying
#   to catch missing dependencies early. Does NOT send any messages or modify
#   any data.
#
# Usage:
#   ./scripts/config_check.sh
#
# What it checks:
#   1. Python          — version, virtual environment, pip dependencies
#   2. Node.js         — version, bridge npm packages
#   3. Ollama          — running, LLM model installed (from .env)
#   4. Embedding model — installed in Ollama (from .env), auto-pulls if missing
#   5. FastAPI         — server reachable on :8000
#   6. .env file       — all required keys are present
#   7. Google Calendar — creds file present (optional, soft warning)
#
# Exit codes:
#   0  all mandatory checks passed
#   1  one or more mandatory checks failed
# =============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

PASS=0
FAIL=0
WARN=0

_pass() { echo "  PASS  $*"; ((PASS++)) || true; }
_fail() { echo "  FAIL  $*"; ((FAIL++)) || true; }
_warn() { echo "  WARN  $*"; ((WARN++)) || true; }
_section() { echo ""; echo "── $* ──────────────────────────────────────"; }

# ---------------------------------------------------------------------------
# Helper: read a value from .env
# ---------------------------------------------------------------------------
_env() {
  grep -E "^${1}=" "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2- | tr -d '[:space:]' || true
}

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║      HouseBot — Configuration Check          ║"
echo "╚══════════════════════════════════════════════╝"

# ---------------------------------------------------------------------------
# 1. Python
# ---------------------------------------------------------------------------
_section "1. Python"

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  PY="$PROJECT_DIR/.venv/bin/python"
  _pass "Virtual environment found: .venv"
else
  PY=$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)
  if [ -n "$PY" ]; then
    _warn "No .venv found — using system Python: $PY"
    _warn "Run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  else
    _fail "Python not found. Install Python 3.10+ from https://python.org"
    PY="python3"
  fi
fi

PY_VERSION=$("$PY" -c "import sys; print('.'.join(map(str,sys.version_info[:3])))" 2>/dev/null || echo "unknown")
REQUIRED_MINOR=10
PY_MINOR=$("$PY" -c "import sys; print(sys.version_info.minor)" 2>/dev/null || echo "0")
if [ "$PY_MINOR" -ge "$REQUIRED_MINOR" ] 2>/dev/null; then
  _pass "Python version: $PY_VERSION"
else
  _fail "Python $PY_VERSION is too old — need 3.${REQUIRED_MINOR}+"
fi

# Check key pip packages — list of "pip-name:import-name" pairs
MISSING_PKGS=""
for pair in "fastapi:fastapi" "uvicorn:uvicorn" "requests:requests" "python-dotenv:dotenv" "faster_whisper:faster_whisper"; do
  pkg="${pair%%:*}"
  mod="${pair##*:}"
  if ! "$PY" -c "import $mod" 2>/dev/null; then
    MISSING_PKGS="$MISSING_PKGS $pkg"
  fi
done
if [ -z "$MISSING_PKGS" ]; then
  _pass "Core Python packages installed"
else
  _fail "Missing Python packages:$MISSING_PKGS"
  echo "   FIX  Run: pip install -r requirements.txt"
fi

# ---------------------------------------------------------------------------
# 2. Node.js
# ---------------------------------------------------------------------------
_section "2. Node.js"

if command -v node &>/dev/null; then
  NODE_VERSION=$(node --version)
  NODE_MAJOR=$(node --version | sed 's/v\([0-9]*\).*/\1/')
  if [ "$NODE_MAJOR" -ge 18 ] 2>/dev/null; then
    _pass "Node.js version: $NODE_VERSION"
  else
    _fail "Node.js $NODE_VERSION is too old — need v18+"
  fi
else
  _fail "Node.js not found. Install via Homebrew: brew install node"
fi

if [ -d "$PROJECT_DIR/bridge/node_modules" ]; then
  _pass "Bridge npm packages installed (node_modules present)"
else
  _fail "Bridge npm packages missing"
  _fail "Run: cd bridge && npm install"
fi

# ---------------------------------------------------------------------------
# 3. Ollama — running + LLM model
# ---------------------------------------------------------------------------
_section "3. Ollama"

if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
  _fail "Ollama is not running — start it with: ollama serve"
  # Cannot check models without Ollama; mark remaining Ollama checks as failed
  _fail "LLM model check skipped (Ollama offline)"
  _fail "Embedding model check skipped (Ollama offline)"
else
  _pass "Ollama is running"

  OLLAMA_TAGS=$(curl -sf http://localhost:11434/api/tags)
  OLLAMA_MODEL=$(_env OLLAMA_MODEL)
  OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.2:3b}"

  echo "       LLM model configured: $OLLAMA_MODEL"
  if echo "$OLLAMA_TAGS" | grep -q "\"name\":\"${OLLAMA_MODEL}\""; then
    _pass "LLM model installed: $OLLAMA_MODEL"
  else
    echo "       Model not found — pulling '$OLLAMA_MODEL'..."
    if ollama pull "$OLLAMA_MODEL"; then
      _pass "LLM model pulled: $OLLAMA_MODEL"
    else
      _fail "Failed to pull LLM model: $OLLAMA_MODEL"
    fi
  fi

  # ---------------------------------------------------------------------------
  # 4. Embedding model
  # ---------------------------------------------------------------------------
  _section "4. Embedding model"

  EMBED_MODEL=$(_env OLLAMA_EMBED_MODEL)
  EMBED_MODEL="${EMBED_MODEL:-nomic-embed-text:latest}"

  echo "       Embedding model configured: $EMBED_MODEL"
  if echo "$OLLAMA_TAGS" | grep -q "\"name\":\"${EMBED_MODEL}\""; then
    _pass "Embedding model installed: $EMBED_MODEL"
  else
    echo "       Model not found — pulling '$EMBED_MODEL'..."
    if ollama pull "$EMBED_MODEL"; then
      _pass "Embedding model pulled: $EMBED_MODEL"
    else
      _fail "Failed to pull embedding model: $EMBED_MODEL"
    fi
  fi
fi

# ---------------------------------------------------------------------------
# 5. FastAPI server
# ---------------------------------------------------------------------------
_section "5. FastAPI server"

if curl -sf http://localhost:8000/admin/api/ping > /dev/null 2>&1; then
  _pass "FastAPI is running on :8000"
else
  _warn "FastAPI is not running (start with: ./housebot.sh start)"
fi

# ---------------------------------------------------------------------------
# 6. .env file — required keys
# ---------------------------------------------------------------------------
_section "6. .env configuration"

if [ ! -f "$PROJECT_DIR/.env" ]; then
  _fail ".env file not found — copy .env.example to .env and fill in the values"
else
  _pass ".env file present"
  REQUIRED_KEYS="OLLAMA_URL OLLAMA_MODEL DEFAULT_CITY DEFAULT_LATITUDE DEFAULT_LONGITUDE TIMEZONE_DEFAULT"
  for key in $REQUIRED_KEYS; do
    val=$(_env "$key")
    if [ -n "$val" ]; then
      _pass "$key = $val"
    else
      _fail "$key is not set in .env"
    fi
  done

  # Optional but recommended keys
  for key in PARTNER_LID WHATSAPP_APPNAME WHISPER_MODEL; do
    val=$(_env "$key")
    if [ -n "$val" ]; then
      _pass "$key = $val"
    else
      _warn "$key is not set (optional — bot will use defaults)"
    fi
  done
fi

# ---------------------------------------------------------------------------
# 7. Google Calendar credentials (optional)
# ---------------------------------------------------------------------------
_section "7. Google Calendar (optional)"

if [ -f "$PROJECT_DIR/creds/client_google_api_calendar.json" ]; then
  _pass "Google API credentials file present"
else
  _warn "creds/client_google_api_calendar.json not found — Calendar features will be unavailable"
fi

if [ -f "$PROJECT_DIR/creds/token.json" ]; then
  _pass "Google OAuth token present"
else
  _warn "creds/token.json not found — authorise via Control Panel → Admin → Google Account"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "══════════════════════════════════════════════"
echo "  Results — passed: $PASS   failed: $FAIL   warnings: $WARN"
echo "══════════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
  echo "  ✗ Some checks failed. Fix the issues above and re-run."
  echo ""
  exit 1
else
  echo "  ✓ All mandatory checks passed."
  echo ""
fi
