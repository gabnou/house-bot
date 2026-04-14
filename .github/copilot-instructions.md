# HouseBot — Copilot Instructions

## Project Overview

HouseBot is a domestic WhatsApp bot for shared management of a shopping list, weather forecasts, and a shared Google Calendar. It runs entirely locally using a local LLM (Ollama) and local speech-to-text (faster-whisper). The bot is English by default but supports multi-language input/output via LLM-based detection and translation.

## Architecture

```
WhatsApp ←→ Bridge (Node.js, Baileys) :3001
                  ↕ HTTP
             FastAPI (Python) :8000
             ├── Intent Parser → Ollama LLM (local)
             ├── Orchestrator  → Skills registry
             │       └── Skills (shopping, weather, calendar)
             │               └── Services (Shopping DB, weather API, Calendar API)
             └── Transcription → faster-whisper (local)

Scheduler (Python, standalone) → broadcasts via FastAPI /broadcast
```

All services are managed by `housebot.sh` (start/stop/restart/watchdog). Logs and PIDs live in `logs/`.

## Request Flow

Every inbound message follows this exact sequence. **There is no LLM reasoning loop by design** — HouseBot handles simple, direct requests and the single-shot approach keeps latency low and output predictable.

```
Incoming message
      │
      ▼
 language detection + translation (LLM, only if non-English)
      │
      ▼
 pre_route()  ──── fast regex match (no LLM) ──►  action dict
      │ (miss)
      ▼
 parse_intent()  ── LLM call → JSON {"action": "...", ...} ──►  action dict
      │
      ▼
 orchestrator.py
      │  action_to_tool("weather_forecast") → "weather.forecast"
      ▼
 skills/registry  →  get("weather.forecast")  →  forecast_tool(payload)
      │
      ▼
 services/weather.py  →  get_weather_forecast(...)  →  string reply
      │
      ▼
 translate reply back (LLM, only if non-English)
      │
      ▼
  {"reply": "...", "notification": "..."}
```

## Folder Map

```
bot/        → server + LLM/NLP layer (FastAPI, intent parsing, orchestration, scheduler)
bot/skills/ → dispatch layer (registry, Pydantic schemas, per-domain tool wrappers)
bot/services/ → business logic layer (Shopping DB, weather API, Google Calendar API)
bridge/     → WhatsApp bridge (Node.js, Baileys)
```

## File Map

### `bot/main.py` — FastAPI Server (entry point)
- **Endpoints**: `POST /message` (main handler), `POST /transcribe` (audio→text), `POST /broadcast` (send to all partners)
- **Message flow**: `pre_route()` (fast regex) → `parse_intent()` (LLM fallback) → `orchestrator.handle_intent()` → reply
- **Language fallback**: `detect_language()` → `translate_to_english()` → re-parse → `classify_intent_category()` → process → `translate_from_english()` response
- **Whisper model** loaded at startup via lifespan event; auto-detects language (no hardcoded `language=` param)

### `bot/intent_parser.py` — LLM-Based Intent Recognition
- `detect_category(text)` — keyword/fuzzy match for `shopping`, `weather`, `calendar` (returns `None` if no match)
- `classify_intent_category(text)` — LLM fallback to classify translated text into one of the three categories by semantic affinity
- `parse_intent(text)` — routes to category-specific LLM prompt, returns JSON dict with `action` + params
- **LLM prompts**: each skill registers its own prompt via `register_prompt()` in `skills/`
- `detect_language(text)` — returns `{"language": "...", "confidence": "high|medium|low"}`
- `translate_to_english(text, source_language)` / `translate_from_english(text, target_language)` — LLM translation
- `validate_transcription(text)` — checks if Whisper output is coherent (fail-open)
- All LLM calls go to `OLLAMA_URL` with model `MODEL` (from env)

### `bot/orchestrator.py` — Skill Dispatcher
- `action_to_tool(action)` — maps LLM action strings (e.g. `"weather_forecast"`) to registered skill names (e.g. `"weather.forecast"`)
- `handle_intent(intent, text, sender)` — looks up the tool in the registry, validates input with Pydantic, calls the tool, formats the reply
- Builds shopping notifications (partner alerts) for modifying actions

### `bot/scheduler.py` — Morning Briefing
- Standalone process (not part of FastAPI); runs in a loop checking every 30s
- `send_briefing()` assembles weather + calendar + motivational quote, optionally translates to `BRIEFING_LANGUAGE`, then POSTs to `/broadcast`
- `generate_morning_quote()` uses Ollama with high temperature (0.9)
- Atomic lock file (`logs/briefing_sent.lock`) prevents duplicate sends
- Time configurable via `BRIEFING_TIME` env var (default `07:30`)

### `skills/` — Dispatch Layer

The skills layer is the **extension point** of the bot. Adding a new capability means creating a new `bot/skills/X.py` with `register()` calls — no changes to `main.py` or `orchestrator.py` are required.

Each skill file does three things:
1. Defines **Pydantic input schemas** for parameter validation
2. Wraps the underlying `services/` function in a thin callable
3. Calls `register()` to publish the tool into the central registry

#### `bot/skills/registry.py`
- `register(name, fn, input_schema, output_schema, desc)` — registers a tool
- `register_prompt(category, fn)` — registers the LLM prompt builder for a category
- `get(name)` → tool dict; `list_tools()` → all registered names

#### `bot/skills/shopping.py`, `bot/skills/weather.py`, `bot/skills/calendar.py`
- Each registers its domain tools and its LLM prompt builder
- LLM prompts live here (not in `intent_parser.py`) so domains are fully isolated

### `services/` — Business Logic Layer

Pure Python modules with no awareness of HTTP, skills, or the registry.

#### `bot/services/shopping_db.py` — SQLite Shopping List
- Functions: `init_db()`, `add_item()`, `remove_item()`, `mark_bought()`, `add_and_mark_bought()`, `show_list()`, `clear_list()`, `recent_bought()`, `get_pending_items()`
- Categories: `food`, `other`, `clothing`, `health`
- Item statuses: `pending`, `bought`
- DB: `bot/services/db/shoppinglist.db` — Schema: `bot/services/db/shoppinglist_schema.sql`

#### `bot/services/weather.py` — Weather Data
- Functions: `get_weather_now()`, `get_weather_forecast()`, `get_weather_hours()`, `get_weather_hours_day()`, `get_morning_briefing()`
- Source: Open-Meteo (free, no API key required)
- `geocode(city)` resolves city names via Open-Meteo geocoding API
- Default city/coords from env (`DEFAULT_CITY`, `DEFAULT_LATITUDE`, `DEFAULT_LONGITUDE`)

#### `bot/services/calendar_handler.py` — Google Calendar
- Functions: `show_events()`, `show_events_period()`, `add_event()`, `delete_event()`, `edit_event()`, `event_details()`
- OAuth2 credentials in `creds/client_google_api_calendar.json`, token in `creds/token.json`
- Calendar name configured via `GOOGLE_CALENDAR_NAME` env var

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
3. `parse_intent(text)` — full LLM call with category-specific prompt from the skill's registered prompt builder
4. For multi-language: `detect_language()` → translate → re-run pipeline → `classify_intent_category()` as keyword affinity fallback → translate reply back

### Why No LLM Loop
HouseBot intentionally avoids a reasoning loop (ReAct / tool-chaining). One message → one LLM call → one tool → one reply. This is the right trade-off for a household bot with simple, direct requests: it keeps latency low, output deterministic, and the system easy to debug. Multi-step agentic chains would add hallucination risk and complexity without benefit for this use case.

### Adding a New Skill
1. Create `bot/skills/mynewskill.py`
2. Define Pydantic input schemas
3. Write a callable that maps payload → `bot/services/` call → `{"ok": bool, "message": str}`
4. Call `register("mynewskill.action", fn, input_schema=..., desc="...")`
5. Optionally call `register_prompt("mynewskill", prompt_fn)` to provide the LLM prompt
6. Import the module in `bot/skills/__init__.py`
7. Add the action mapping in `bot/orchestrator.py → action_to_tool()`

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
- `WHISPER_MODEL` — faster-whisper model size (small/medium/large)
- `BRIEFING_TIME` — HH:MM format (default 07:30)
- `BRIEFING_LANGUAGE` — translate briefing (default English)
- `TIMEZONE_DEFAULT` — timezone for weather/calendar

## Conventions
- Python code uses `logging.getLogger(__name__)` — levels set explicitly per module in `main.py`
- LLM prompts live in `skills/<domain>.py` as the `prompt()` function registered via `register_prompt()`
- JSON is the only LLM response format — never markdown, never plain text
- Fuzzy matching uses `difflib.SequenceMatcher` with threshold 0.82
- The bridge and FastAPI communicate only via HTTP (ports 3001 and 8000)
- No external cloud services except: Open-Meteo (free), Google Calendar API, WhatsApp (Meta)

