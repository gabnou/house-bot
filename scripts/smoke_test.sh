#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# smoke_test.sh — HouseBot sanity check
#
# Purpose:
#   Quickly verifies that the core Python layers are importable and functional
#   without starting the full FastAPI server or the WhatsApp bridge. Safe to run
#   at any time; it makes no writes to the shopping DB and sends no messages.
#
# Usage:
#   ./scripts/smoke_test.sh
#
# What it checks:
#   1. Skills registry — imports bot/skills/ and lists all registered tools.
#   2. Orchestrator — dispatches a read-only "show" intent end-to-end through
#      the registry and the shopping DB, printing the response.
#   3. Ollama connectivity (optional) — runs scripts/check_ollama.py to verify
#      the local LLM is reachable and responding. Skipped gracefully if Ollama
#      is offline; the rest of the test still passes.
#
# Exit codes:
#   0  all mandatory checks passed
#   1  a mandatory check failed (skills import or orchestrator call)
# =============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Prefer the project virtual environment so dependencies are guaranteed to match.
if [ -x "./.venv/bin/python" ]; then
  PY="./.venv/bin/python"
else
  PY=python
fi

echo "[smoke] Using Python: $($PY -V 2>&1)"

# -----------------------------------------------------------------------------
# Step 1: Import the skills package and enumerate registered tools.
# Catches missing __init__.py imports, broken skill modules, or registry errors.
# -----------------------------------------------------------------------------
echo "[smoke] 1) Import skills and list tools"
$PY - <<'PY'
import sys, os
# ensure bot/ modules are importable as top-level names
sys.path.insert(0, os.path.join(os.getcwd(), 'bot'))
try:
    import skills
    print('OK: skills imported')
    try:
        tools = skills.list_tools()
        print('Tools registered (count={}):'.format(len(tools)))
        print(', '.join(tools))
    except Exception as e:
        print('WARN: listing tools failed:', e)
except Exception as e:
    print('ERROR: importing skills failed:', e)
    raise
PY

# -----------------------------------------------------------------------------
# Step 2: Run a non-destructive orchestrator call ("show" reads the shopping DB
# but does not modify it). Verifies the full dispatch path:
#   action dict → orchestrator → registry → service → formatted reply.
# -----------------------------------------------------------------------------
echo "[smoke] 2) Orchestrator basic call: show (non-destructive)"
$PY - <<'PY'
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'bot'))
from bot.orchestrator import handle_intent
res = asyncio.run(handle_intent({'action':'show'}, 'show list', 'smoke_test'))
print('Orchestrator response:')
print(res)
PY

# -----------------------------------------------------------------------------
# Step 3: Optional Ollama connectivity check.
# Pings the local Ollama instance and verifies the configured model responds.
# Failure here does NOT fail the overall smoke test — Ollama may simply be
# offline while the Python code itself is still correct.
# -----------------------------------------------------------------------------
echo "[smoke] 3) Optional: check Ollama connectivity (check_ollama.py)"
if [ -f "$PROJECT_DIR/scripts/check_ollama.py" ]; then
  echo "Running check_ollama.py (this may take a moment)..."
  if $PY "$PROJECT_DIR/scripts/check_ollama.py"; then
    echo "Ollama check: OK"
  else
    echo "Ollama check: FAILED (Ollama may be offline)"
  fi
else
  echo "No check_ollama.py found; skipping Ollama check"
fi

echo "[smoke] Completed."
