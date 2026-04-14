#!/usr/bin/env bash
set -euo pipefail

# Simple smoke test for House-Bot skills + orchestrator
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

# Choose python executable from venv if present
if [ -x "./.venv/bin/python" ]; then
  PY="./.venv/bin/python"
else
  PY=python
fi

echo "[smoke] Using Python: $($PY -V 2>&1)"

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

echo "[smoke] 2) Orchestrator basic call: show (non-destructive)"
$PY - <<'PY'
import sys, os, asyncio
sys.path.insert(0, os.path.join(os.getcwd(), 'bot'))
from bot.orchestrator import handle_intent
res = asyncio.run(handle_intent({'action':'show'}, 'show list', 'smoke_test'))
print('Orchestrator response:')
print(res)
PY

echo "[smoke] 3) Optional: check Ollama connectivity (check_ollama.py)"
if [ -f "./check_ollama.py" ]; then
  echo "Running check_ollama.py (this may take a moment)..."
  if $PY check_ollama.py; then
    echo "Ollama check: OK"
  else
    echo "Ollama check: FAILED (Ollama may be offline)"
  fi
else
  echo "No check_ollama.py found; skipping Ollama check"
fi

echo "[smoke] Completed."
