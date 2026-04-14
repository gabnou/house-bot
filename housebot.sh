#!/bin/bash

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# Maximum size of a single log file before rotation (default: 10 MB)
LOG_MAX_BYTES=${LOG_MAX_BYTES:-10485760}

# Read LOG_LEVEL from .env (default: info) and convert to lowercase for uvicorn
LOG_LEVEL=$(grep -E '^LOG_LEVEL=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2 | tr '[:upper:]' '[:lower:]')
LOG_LEVEL=${LOG_LEVEL:-info}

check_model() {
    echo "🔍 Checking Ollama model..."

    # Read the configured model from .env (strip quotes, carriage returns, and surrounding whitespace)
    MODEL_CONFIGURED=$(grep '^OLLAMA_MODEL' "$PROJECT_DIR/.env" | head -1 | sed 's/.*=\s*//' | tr -d '"'"'" | tr -d '\r' | xargs)
    echo "📦 Configured model: $MODEL_CONFIGURED"

    # Read the model currently loaded in memory
    MODEL_IN_MEMORY=$(curl -s http://localhost:11434/api/ps 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    models = data.get('models', [])
    if models:
        print(models[0]['name'])
except:
    pass
" 2>/dev/null)

    if [ -z "$MODEL_IN_MEMORY" ]; then
        echo "ℹ️ No model loaded in memory — will be loaded on first message."
        return
    fi

    echo "📦 Model in memory: $MODEL_IN_MEMORY"

    if [ "$MODEL_IN_MEMORY" != "$MODEL_CONFIGURED" ]; then
        echo "⚠️ Different model — unloading $MODEL_IN_MEMORY and loading $MODEL_CONFIGURED..."
        ollama stop "$MODEL_IN_MEMORY" 2>/dev/null
        sleep 2
        ollama run "$MODEL_CONFIGURED" "" > /dev/null 2>&1 &
        sleep 10
        pkill -f "ollama run" 2>/dev/null
        echo "✅ Model updated to $MODEL_CONFIGURED"
    else
        echo "✅ Correct model already in memory."
    fi
}

rotate_logs() {
    local rotated=0

    # Delete .log.old files older than 3 days
    find "$LOG_DIR" -maxdepth 1 -name "*.log.old" -mtime +3 -delete

    for log in "$LOG_DIR"/fastapi.log "$LOG_DIR"/bridge.log "$LOG_DIR"/scheduler.log "$LOG_DIR"/watchdog.log; do
        [ -f "$log" ] || continue
        local size
        size=$(wc -c < "$log")
        if [ "$size" -gt "$LOG_MAX_BYTES" ]; then
            mv "$log" "${log%.log}.log.old"
            touch "$log"
            echo "🔄 Rotated $(basename $log) (${size} bytes → archived as $(basename ${log%.log}.log.old))"
            rotated=$((rotated + 1))
        fi
    done
    [ "$rotated" -eq 0 ] && echo "✅ Logs within size limit — no rotation needed."
}

start() {
    echo "🚀 Starting HouseBot..."

    rotate_logs

    # Check that Ollama is reachable
    if ! curl -s http://localhost:11434 > /dev/null 2>&1; then
        echo "❌ Ollama is not running. Start it manually with: ollama serve"
        exit 1
    fi

    # Verify and sync the model
    check_model

    # FastAPI
    if [ -f "$LOG_DIR/fastapi.pid" ] && kill -0 $(cat "$LOG_DIR/fastapi.pid") 2>/dev/null; then
        echo "✅ FastAPI was already running"
    else
        nohup bash -c "cd '$PROJECT_DIR/bot' && '$PROJECT_DIR/.venv/bin/python' -m uvicorn main:app --port 8000 --log-level $LOG_LEVEL" \
            > "$LOG_DIR/fastapi.log" 2>&1 &
        echo $! > "$LOG_DIR/fastapi.pid"
        echo "✅ FastAPI started (PID $(cat $LOG_DIR/fastapi.pid))"
    fi

    # WhatsApp Bridge
    if [ -f "$LOG_DIR/bridge.pid" ] && kill -0 $(cat "$LOG_DIR/bridge.pid") 2>/dev/null; then
        echo "✅ WhatsApp Bridge was already running"
    else
        nohup node "$PROJECT_DIR/bridge/index.js" \
            > "$LOG_DIR/bridge.log" 2>&1 &
        echo $! > "$LOG_DIR/bridge.pid"
        echo "✅ WhatsApp Bridge started (PID $(cat $LOG_DIR/bridge.pid))"
    fi

    # Scheduler — kill ALL running scheduler instances
    pkill -f "scheduler.py" 2>/dev/null
    sleep 1
    nohup bash -c "cd '$PROJECT_DIR/bot' && '$PROJECT_DIR/.venv/bin/python' scheduler.py" \
        > "$LOG_DIR/scheduler.log" 2>&1 &
    echo $! > "$LOG_DIR/scheduler.pid"
    echo "✅ Scheduler started (PID $(cat $LOG_DIR/scheduler.pid))"

    echo ""
    echo "🤖 HouseBot is operational!"

    # Start watchdog last, after all services are up
    start_watchdog
}

watchdog_loop() {
    echo "🐕 Watchdog started (PID $$)" >> "$LOG_DIR/watchdog.log"
    while true; do
        sleep 300

        # Bridge
        if [ -f "$LOG_DIR/bridge.pid" ]; then
            BRIDGE_PID=$(cat "$LOG_DIR/bridge.pid")
            if ! kill -0 "$BRIDGE_PID" 2>/dev/null; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️  Bridge died (PID $BRIDGE_PID) — restarting..." >> "$LOG_DIR/watchdog.log"
                nohup node "$PROJECT_DIR/bridge/index.js" \
                    >> "$LOG_DIR/bridge.log" 2>&1 &
                echo $! > "$LOG_DIR/bridge.pid"
                echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Bridge restarted (PID $!)" >> "$LOG_DIR/watchdog.log"
            fi
        fi

        # FastAPI
        if [ -f "$LOG_DIR/fastapi.pid" ]; then
            FASTAPI_PID=$(cat "$LOG_DIR/fastapi.pid")
            if ! kill -0 "$FASTAPI_PID" 2>/dev/null; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️  FastAPI died (PID $FASTAPI_PID) — restarting..." >> "$LOG_DIR/watchdog.log"
                nohup bash -c "cd '$PROJECT_DIR/bot' && '$PROJECT_DIR/.venv/bin/python' -m uvicorn main:app --port 8000 --log-level $LOG_LEVEL" \
                    >> "$LOG_DIR/fastapi.log" 2>&1 &
                echo $! > "$LOG_DIR/fastapi.pid"
                echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ FastAPI restarted (PID $!)" >> "$LOG_DIR/watchdog.log"
            fi
        fi

        # Scheduler
        if [ -f "$LOG_DIR/scheduler.pid" ]; then
            SCHED_PID=$(cat "$LOG_DIR/scheduler.pid")
            if ! kill -0 "$SCHED_PID" 2>/dev/null; then
                echo "$(date '+%Y-%m-%d %H:%M:%S') ⚠️  Scheduler died (PID $SCHED_PID) — restarting..." >> "$LOG_DIR/watchdog.log"
                nohup bash -c "cd '$PROJECT_DIR/bot' && '$PROJECT_DIR/.venv/bin/python' scheduler.py" \
                    >> "$LOG_DIR/scheduler.log" 2>&1 &
                echo $! > "$LOG_DIR/scheduler.pid"
                echo "$(date '+%Y-%m-%d %H:%M:%S') ✅ Scheduler restarted (PID $!)" >> "$LOG_DIR/watchdog.log"
            fi
        fi
    done
}

start_watchdog() {
    if [ -f "$LOG_DIR/watchdog.pid" ] && kill -0 $(cat "$LOG_DIR/watchdog.pid") 2>/dev/null; then
        echo "✅ Watchdog was already running (PID $(cat $LOG_DIR/watchdog.pid))"
        return
    fi
    watchdog_loop &
    echo $! > "$LOG_DIR/watchdog.pid"
    echo "✅ Watchdog started (PID $(cat $LOG_DIR/watchdog.pid))"
}

stop_watchdog() {
    if [ -f "$LOG_DIR/watchdog.pid" ]; then
        kill $(cat "$LOG_DIR/watchdog.pid") 2>/dev/null
        rm "$LOG_DIR/watchdog.pid"
        echo "✅ Watchdog stopped"
    fi
}

stop() {
    echo "🛑 Stopping FastAPI, Bridge and Scheduler..."

    if [ -f "$LOG_DIR/fastapi.pid" ]; then
        kill $(cat "$LOG_DIR/fastapi.pid") 2>/dev/null
        rm "$LOG_DIR/fastapi.pid"
        echo "✅ FastAPI stopped"
    fi

    kill -9 $(lsof -ti :8000) 2>/dev/null

    if [ -f "$LOG_DIR/bridge.pid" ]; then
        kill $(cat "$LOG_DIR/bridge.pid") 2>/dev/null
        rm "$LOG_DIR/bridge.pid"
        echo "✅ WhatsApp Bridge stopped"
    fi

    pkill -f "scheduler.py" 2>/dev/null
    if [ -f "$LOG_DIR/scheduler.pid" ]; then
        rm "$LOG_DIR/scheduler.pid"
    fi
    echo "✅ Scheduler stopped"

    stop_watchdog

    echo ""
    echo "💤 HouseBot stopped (Ollama unchanged)."
}

status() {
    echo "📊 HouseBot Status:"
    echo ""

    if curl -s http://localhost:11434 > /dev/null 2>&1; then
        MODEL_IN_MEMORY=$(curl -s http://localhost:11434/api/ps 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    models = data.get('models', [])
    if models:
        print(models[0]['name'])
    else:
        print('none loaded')
except:
    print('read error')
" 2>/dev/null)
        echo "Ollama       ✅ running (model: $MODEL_IN_MEMORY)"
    else
        echo "Ollama       ❌ not running"
    fi

    if [ -f "$LOG_DIR/fastapi.pid" ] && kill -0 $(cat "$LOG_DIR/fastapi.pid") 2>/dev/null; then
        echo "FastAPI      ✅ running (PID $(cat $LOG_DIR/fastapi.pid))"
    else
        echo "FastAPI      ❌ not running"
    fi

    if [ -f "$LOG_DIR/bridge.pid" ] && kill -0 $(cat "$LOG_DIR/bridge.pid") 2>/dev/null; then
        echo "Bridge WA    ✅ running (PID $(cat $LOG_DIR/bridge.pid))"
    else
        echo "Bridge WA    ❌ not running"
    fi

    if [ -f "$LOG_DIR/scheduler.pid" ] && kill -0 $(cat "$LOG_DIR/scheduler.pid") 2>/dev/null; then
        echo "Scheduler    ✅ running (PID $(cat $LOG_DIR/scheduler.pid))"
    else
        echo "Scheduler    ❌ not running"
    fi

    if [ -f "$LOG_DIR/watchdog.pid" ] && kill -0 $(cat "$LOG_DIR/watchdog.pid") 2>/dev/null; then
        echo "Watchdog     ✅ running (PID $(cat $LOG_DIR/watchdog.pid))"
    else
        echo "Watchdog     ❌ not running"
    fi
}

logs_live() {
    LOGS="$LOG_DIR/bridge.log $LOG_DIR/fastapi.log $LOG_DIR/scheduler.log"
    [ -f "$LOG_DIR/ollama.log" ] && LOGS="$LOGS $LOG_DIR/ollama.log"
    [ -f "$HOME/.ollama/logs/server.log" ] && LOGS="$LOGS $HOME/.ollama/logs/server.log"
    tail -f $LOGS
}

logs() {
    echo "=== FastAPI ===" && tail -n 30 "$LOG_DIR/fastapi.log" 2>/dev/null || echo "(no logs)"
    echo ""
    echo "=== Bridge ===" && tail -n 30 "$LOG_DIR/bridge.log" 2>/dev/null || echo "(no logs)"
    echo ""
    echo "=== Scheduler ===" && tail -n 10 "$LOG_DIR/scheduler.log" 2>/dev/null || echo "(no logs)"
}

qr() {
    echo "📱 Waiting for QR code... (CTRL+C to exit)"
    tail -f "$LOG_DIR/bridge.log"
}

case "$1" in
    start)          start ;;
    stop)           stop ;;
    restart)        stop && sleep 2 && start ;;
    status)         status ;;
    logs-live)      logs_live ;;
    logs)           logs ;;
    logs-rotate)    rotate_logs ;;
    qr)             qr ;;
    watchdog-start) start_watchdog ;;
    watchdog-stop)  stop_watchdog ;;
    *)
        echo "Usage: ./housebot.sh [start|stop|restart|status|logs|logs-live|logs-rotate|qr|watchdog-start|watchdog-stop]"
        ;;
esac
