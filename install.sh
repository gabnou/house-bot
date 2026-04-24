#!/usr/bin/env bash
# =============================================================================
# install.sh — HouseBot interactive installer (macOS only)
#
# Sets up the minimal environment required to run HouseBot and open the
# Control Panel. From there, use the Installation Wizard to complete the
# full configuration (LLM model, WhatsApp pairing, Google Calendar, etc.).
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# Safe to re-run — all steps are idempotent.
# =============================================================================

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Terminal helpers ──────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

_ok()   { echo -e "  ${GREEN}✓${NC}  $*"; }
_warn() { echo -e "  ${YELLOW}⚠${NC}  $*"; }
_fail() { echo -e "  ${RED}✗${NC}  $*"; }
_info() { echo -e "  ${DIM}→${NC}  $*"; }
_step() {
  echo
  echo -e "${BOLD}${BLUE}  ── $* ──${NC}"
  echo
}
_pause() {
  echo
  read -rp "  Press Enter to continue… "
}
_header() {
  clear
  echo
  echo -e "${BOLD}"
  echo "  ╔══════════════════════════════════════════════════╗"
  echo "  ║         HouseBot — Installation Wizard           ║"
  echo "  ╚══════════════════════════════════════════════════╝"
  echo -e "${NC}"
}
_abort() {
  echo
  _fail "$*"
  echo
  exit 1
}

# ── Step 0: macOS + RAM ───────────────────────────────────────────────────────
_header
_step "Step 0 — System requirements"

if [[ "$(uname)" != "Darwin" ]]; then
  _abort "HouseBot is only supported on macOS. Exiting."
fi
_ok "macOS $(sw_vers -productVersion) detected"

RAM_BYTES=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
RAM_GB=$(( RAM_BYTES / 1024 / 1024 / 1024 ))
if (( RAM_GB < 8 )); then
  _warn "${RAM_GB}GB RAM detected — 8GB or more is recommended to run an LLM locally."
  _warn "You may run out of memory. Consider a lightweight model (e.g. llama3.1:8b)."
  echo
  read -rp "  Continue anyway? [y/N] " _ANS
  [[ "${_ANS,,}" == "y" ]] || exit 0
else
  _ok "${RAM_GB}GB RAM — OK"
fi

_pause

# ── Step 1: Homebrew ─────────────────────────────────────────────────────────
_header
_step "Step 1 — Homebrew"

if command -v brew &>/dev/null; then
  _ok "Homebrew already installed ($(brew --version | head -1))"
else
  _info "Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

  # Add brew to PATH — required for Apple Silicon (/opt/homebrew) and Intel (/usr/local)
  if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -f /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi

  _ok "Homebrew installed"
fi

# Ensure brew is in PATH for subsequent steps (especially on Apple Silicon)
if [[ -f /opt/homebrew/bin/brew ]]; then
  eval "$(/opt/homebrew/bin/brew shellenv)"
fi

_pause

# ── Step 2: Python 3.11+ ─────────────────────────────────────────────────────
_header
_step "Step 2 — Python 3.11+"

PYTHON=""
for _candidate in python3.13 python3.12 python3.11; do
  if command -v "$_candidate" &>/dev/null; then
    PYTHON="$_candidate"
    _ok "Found $PYTHON ($($PYTHON --version))"
    break
  fi
done

if [[ -z "$PYTHON" ]]; then
  _info "Python 3.11+ not found — installing Python 3.13 via Homebrew..."
  brew install python@3.13
  # Brew installs as python3.13 in its prefix
  BREW_PYTHON="$(brew --prefix)/bin/python3.13"
  if [[ -x "$BREW_PYTHON" ]]; then
    PYTHON="$BREW_PYTHON"
  else
    PYTHON="python3.13"
  fi
  _ok "Python 3.13 installed ($($PYTHON --version))"
fi

_pause

# ── Step 3: Python virtual environment + dependencies ────────────────────────
_header
_step "Step 3 — Python virtual environment"

VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

if [[ -f "$VENV_PYTHON" ]]; then
  _ok ".venv already exists ($($VENV_PYTHON --version))"
else
  _info "Creating virtual environment at .venv..."
  "$PYTHON" -m venv "$VENV_DIR"
  _ok ".venv created"
fi

_info "Installing Python dependencies from requirements.txt..."
"$VENV_PIP" install --upgrade pip --quiet
"$VENV_PIP" install -r "$PROJECT_DIR/requirements.txt" --quiet
_ok "Python dependencies installed"

_pause

# ── Step 4: Ollama ───────────────────────────────────────────────────────────
_header
_step "Step 4 — Ollama"

if command -v ollama &>/dev/null; then
  _ok "Ollama already installed ($(ollama --version 2>/dev/null | head -1))"
else
  _info "Installing Ollama via Homebrew..."
  brew install ollama
  _ok "Ollama installed"
fi

_warn "No LLM model will be pulled at this stage."
_warn "After the installer finishes, use the Control Panel to pull a model"
_warn "(e.g. 'ollama pull mistral-small:22b' or 'ollama pull llama3.1:8b')."

# Pull the embedding model if not already present.
# nomic-embed-text is small (~270 MB) and required for fast multilingual intent classification.
_EMBED_MODEL="${OLLAMA_EMBED_MODEL:-nomic-embed-text:latest}"
echo
_info "Checking embedding model '${_EMBED_MODEL}'..."

# Ensure Ollama is running so we can query the model list
if ! curl -s http://localhost:11434/ &>/dev/null; then
  _info "Starting Ollama temporarily to check for the embedding model..."
  nohup ollama serve > "$PROJECT_DIR/logs/ollama.log" 2>&1 &
  for _i in $(seq 1 20); do
    sleep 1
    if curl -s http://localhost:11434/ &>/dev/null; then
      break
    fi
  done
fi

if ollama list 2>/dev/null | grep -q "^${_EMBED_MODEL%%:*}"; then
  _ok "Embedding model '${_EMBED_MODEL}' already present"
else
  _info "Pulling embedding model '${_EMBED_MODEL}' (≈270 MB, one-time download)..."
  if ollama pull "${_EMBED_MODEL}"; then
    _ok "Embedding model '${_EMBED_MODEL}' pulled successfully"
  else
    _warn "Failed to pull '${_EMBED_MODEL}' — the bot will fall back to LLM-based classification."
    _warn "You can pull it later with: ollama pull ${_EMBED_MODEL}"
  fi
fi

_pause

# ── Step 5: Node.js, bridge dependencies & Control Panel UI build ────────────
_header
_step "Step 5 — Node.js, bridge & Control Panel UI"

if command -v node &>/dev/null; then
  _ok "Node.js already installed ($(node --version))"
else
  _info "Installing Node.js via Homebrew..."
  brew install node
  _ok "Node.js installed ($(node --version))"
fi

_info "Installing bridge (Node.js) dependencies..."
(cd "$PROJECT_DIR/bridge" && npm install --silent)
_ok "Bridge dependencies installed"

_info "Building the Control Panel UI (this may take a minute)..."
chmod +x "$PROJECT_DIR/housebot.sh"
"$PROJECT_DIR/housebot.sh" ui-build
_ok "Control Panel UI built"

_pause

# ── Step 6: Start HouseBot ───────────────────────────────────────────────────
_header
_step "Step 6 — Starting HouseBot"

mkdir -p "$PROJECT_DIR/logs"
mkdir -p "$PROJECT_DIR/creds"

# Create .env from .env.example if missing
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  if [[ -f "$PROJECT_DIR/.env.example" ]]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    _info ".env created from .env.example — complete the configuration in the Control Panel"
  else
    _warn ".env.example not found — a minimal .env will be created"
    cat > "$PROJECT_DIR/.env" <<'EOF'
OLLAMA_URL=http://localhost:11434/api/generate
OLLAMA_MODEL=mistral-small:22b
WHISPER_MODEL=small
LOG_LEVEL=INFO
GOOGLE_CALENDAR_NAME=
PARTNER_LID=
EOF
  fi
else
  _ok ".env already exists"
fi

# Start Ollama (housebot.sh start requires it to be reachable)
if curl -s http://localhost:11434/ &>/dev/null; then
  _ok "Ollama already running"
else
  _info "Starting Ollama in the background..."
  nohup ollama serve > "$PROJECT_DIR/logs/ollama.log" 2>&1 &

  # Wait up to 20 seconds for Ollama to become reachable
  _READY=false
  for _i in $(seq 1 20); do
    sleep 1
    if curl -s http://localhost:11434/ &>/dev/null; then
      _READY=true
      break
    fi
  done

  if [[ "$_READY" == "true" ]]; then
    _ok "Ollama started"
  else
    _warn "Ollama did not respond within 20s — it may still be starting up."
    _warn "Check logs/ollama.log if the bot fails to start."
  fi
fi

# Start HouseBot (FastAPI + Bridge + Scheduler)
_info "Starting HouseBot services..."
"$PROJECT_DIR/housebot.sh" start
sleep 2

_ok "HouseBot started"

# ── Done ─────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}${GREEN}  ✅  Installation complete!${NC}"
echo
echo -e "  Open the Control Panel to finish configuring the bot:"
echo
echo -e "    ${BOLD}${BLUE}➜  http://localhost:8000${NC}"
echo
echo -e "  From the ${BOLD}Installation Wizard${NC} in the Control Panel you can:"
echo -e "    • Pull the LLM model (e.g. ollama pull mistral-small:22b)"
echo -e "    • Configure .env (location, timezone, partners, calendar)"
echo -e "    • Set up Google Calendar OAuth"
echo -e "    • Pair WhatsApp via QR code"
echo -e "    • Discover and save partner JIDs"
echo -e "    • Run a smoke test"
echo
_info "To reopen the Control Panel later:  open http://localhost:8000"
_info "To stop HouseBot:                   ./housebot.sh stop"
_info "To check status:                    ./housebot.sh status"
echo
