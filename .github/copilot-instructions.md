# HouseBot — Copilot Instructions

## Project Overview

HouseBot is a domestic WhatsApp bot for shared management of a shopping list, weather forecasts, and a shared Google Calendar. It runs entirely locally using a local LLM (Ollama) and local speech-to-text (faster-whisper). The bot is English by default but supports multi-language input/output via LLM-based detection and translation.

## Architecture

```
WhatsApp ←→ Bridge (Node.js, Baileys) :3001
                  ↕ HTTP
             FastAPI (Python) :8000
             ├── Intent Parser → Ollama LLM (local)
             ├── Shopping List → SQLite
             ├── Weather → OpenWeatherMap / Open-Meteo (fallback)
             ├── Calendar → Google Calendar API
             └── Transcription → faster-whisper (local)

Scheduler (Python, standalone) → broadcasts via FastAPI /broadcast
```

All services are managed by `housebot.sh` (start/stop/restart/watchdog). Logs and PIDs live in `logs/`.

## File Map

### `bot/main.py` — FastAPI Server (entry point)
- **Endpoints**: `POST /message` (main handler), `POST /transcribe` (audio→text), `POST /broadcast` (send to all partners)
- **Message flow**: `pre_route()` (fast regex) → `parse_intent()` (LLM fallback) → action handler → reply
- **Language fallback** (in `unknown` handler): `detect_language()` → `translate_to_english()` → re-parse → `classify_intent_category()` (keyword affinity) → process → `translate_from_english()` response
- **Imports from**: `intent_parser`, `db_handler`, `weather`, `calendar_handler`
- **Whisper model** loaded at startup via lifespan event; auto-detects language (no hardcoded `language=` param)

### `bot/intent_parser.py` — LLM-Based Intent Recognition
- `detect_category(text)` — keyword/fuzzy match for `shopping`, `weather`, `calendar` (returns `None` if no match)
- `classify_intent_category(text)` — LLM fallback to classify translated text into one of the three categories by semantic affinity
- `parse_intent(text)` — routes to category-specific LLM prompt, returns JSON dict with `action` + params
- **LLM prompts**: `get_system_prompt()`, `get_shopping_prompt()`, `get_weather_prompt()`, `get_calendar_prompt()` — each returns a string with examples for few-shot prompting
- `detect_language(text)` — returns `{"language": "...", "confidence": "high|medium|low"}`
- `translate_to_english(text, source_language)` / `translate_from_english(text, target_language)` — LLM translation
- `validate_transcription(text)` — checks if Whisper output is coherent (fail-open)
- All LLM calls go to `OLLAMA_URL` with model `MODEL` (from env)

### `bot/db_handler.py` — SQLite Shopping List
- Functions: `init_db()`, `add_item()`, `remove_item()`, `mark_bought()`, `add_and_mark_bought()`, `show_list()`, `clear_list()`, `recent_bought()`, `get_pending_items()`
- Categories: `food`, `other`, `clothing`, `health`
- Item statuses: `pending`, `bought`
- Schema defined in `bot/schema.sql`

### `bot/weather.py` — Weather Data
- Functions: `get_weather_now()`, `get_weather_forecast()`, `get_weather_hours()`, `get_weather_hours_day()`, `get_morning_briefing()`
- Primary source: OpenWeatherMap (One Call API 3.0); fallback: Open-Meteo (free, no key)
- `geocode(city)` resolves city names via Open-Meteo geocoding API
- Default city/coords from env (`DEFAULT_CITY`, `DEFAULT_LATITUDE`, `DEFAULT_LONGITUDE`)

### `bot/calendar_handler.py` — Google Calendar
- Functions: `show_events()`, `show_events_period()`, `add_event()`, `delete_event()`, `edit_event()`, `event_details()`
- OAuth2 credentials in `creds/client_google_api_calendar.json`, token in `creds/token.json`
- Calendar name configured via `GOOGLE_CALENDAR_NAME` env var

### `bot/scheduler.py` — Morning Briefing
- Standalone process (not part of FastAPI); runs in a loop checking every 30s
- `send_briefing()` assembles weather + calendar + motivational quote, optionally translates to `BRIEFING_LANGUAGE`, then POSTs to `/broadcast`
- `generate_morning_quote()` uses Ollama with high temperature (0.9)
- Atomic lock file (`logs/briefing_sent.lock`) prevents duplicate sends
- Time configurable via `BRIEFING_TIME` env var (default `07:30`)

### `bridge/index.js` — WhatsApp Bridge (Node.js)
- Uses Baileys (`@whiskeysockets/baileys`) for WhatsApp Web session
- Message queue with serial processing (`drainQueue()`)
- Voice notes: downloads audio → POSTs to FastAPI `/transcribe` → uses text result
- Text messages: POSTs to FastAPI `/message` → sends reply to sender + notification to other partners
- Express server on port 3001 with `/send` endpoint (used by scheduler broadcasts)
- Auth state persisted in `bridge/baileys_auth/`

### `housebot.sh` — Lifecycle Management
- Commands: `start`, `stop`, `restart`, `status`, `logs`, `logs-live`, `logs-rotate`, `qr`, `watchdog-start`, `watchdog-stop`
- Spawns: FastAPI (uvicorn :8000), Bridge (node :3001), Scheduler
- Reads `LOG_LEVEL` from `.env` and passes `--log-level` to uvicorn
- Watchdog checks every 5 min and auto-restarts crashed services

## Key Patterns

### Intent Detection Pipeline
1. `detect_category(text)` — fast keyword/fuzzy match on first word
2. `pre_route(text)` — regex patterns for common intents (bought, remove, show, add, calendar today)
3. `parse_intent(text)` — full LLM call with category-specific prompt
4. For multi-language: `detect_language()` → translate → re-run pipeline → `classify_intent_category()` as keyword affinity fallback → translate reply back

### LLM Interaction
- All LLM calls go through `requests.post(OLLAMA_URL, json={...})` — no SDK
- Prompts are few-shot with explicit JSON-only response format
- `_parse_raw(raw)` extracts JSON from LLM response (handles double braces, finds first `{...}`)
- Temperature: 0 for classification/validation, 0.1 for intent parsing, 0.9 for quote generation

### Shopping List Actions
- `add` → `add_item()` per item
- `remove` → fuzzy match against pending items → `remove_item()`
- `bought` → fuzzy match or LLM extraction → `mark_bought()` or `add_and_mark_bought()`
- `show` → `show_list(category)`
- `clear` → `clear_list()`
- Modifying actions (`add`, `remove`, `bought`, `clear`) trigger a notification to the other partner

## Configuration

All config is in `.env` (see `.env.example`). Key variables:
- `OLLAMA_URL`, `OLLAMA_MODEL` — LLM endpoint and model
- `LOG_LEVEL` — DEBUG/INFO/WARNING/ERROR (propagated to uvicorn and all app loggers)
- `PARTNER_LID`, `PARTNER_NET` — WhatsApp partner JIDs
- `GOOGLE_CALENDAR_NAME` — calendar to use
- `DEFAULT_CITY`, `DEFAULT_LATITUDE`, `DEFAULT_LONGITUDE` — weather defaults
- `OPENWEATHER_API_KEY` — primary weather (optional; falls back to Open-Meteo)
- `WHISPER_MODEL` — faster-whisper model size (small/medium/large)
- `BRIEFING_TIME` — HH:MM format (default 07:30)
- `BRIEFING_LANGUAGE` — translate briefing (default English)
- `TIMEZONE_DEFAULT` — timezone for weather/calendar

## Conventions
- Python code uses `logging.getLogger(__name__)` — levels set explicitly per module in `main.py`
- All LLM prompts live in `bot/intent_parser.py` as `get_*_prompt()` functions
- JSON is the only LLM response format — never markdown, never plain text
- Fuzzy matching uses `difflib.SequenceMatcher` with threshold 0.82
- The bridge and FastAPI communicate only via HTTP (ports 3001 and 8000)
- No external cloud services except: OpenWeatherMap, Google Calendar API, WhatsApp (Meta)
