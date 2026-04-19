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
             ├── Transcription → faster-whisper (local)
             └── Admin API     → bot/admin/router.py (/admin/api/*)

Scheduler (Python, standalone) → broadcasts via FastAPI /broadcast

Control Panel (SvelteKit + Skeleton UI) :5252
             └── /admin/api/* ──► FastAPI Admin Router
```

All services are managed by `housebot.sh` (start/stop/restart/watchdog). Logs and PIDs live in `logs/`. After starting, day-to-day management is done via the Control Panel at `http://localhost:5252`.

## Request Flow

Every inbound message follows this exact sequence. **There is no LLM reasoning loop by design** — HouseBot handles simple, direct requests and the single-shot approach keeps latency low and output predictable.

```
Incoming message
      │
      ▼
 pre_route()  ── identity/help regex only (no LLM) ──►  action dict
      │ (miss)
      ▼
 language detection + translation (LLM, only if non-English)
      │
      ▼
 detect_category() / classify_intent_category()  ──► prepend keyword
      │
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
bot/          → FastAPI server + LLM/NLP layer (intent parsing, orchestration, scheduler)
bot/admin/    → Admin API router (service control, model switching, prompt editor, log viewer)
bot/skills/   → dispatch layer (registry, Pydantic schemas, per-domain tool wrappers)
bot/services/ → business logic layer (Shopping DB, weather API, Google Calendar API)
bot/prompts/  → optional hot-reload prompt overrides ({skill}.txt replaces built-in LLM prompt)
bridge/       → WhatsApp bridge (Node.js, Baileys)
ui/           → SvelteKit control panel (Skeleton UI cerberus theme, Tailwind v4)
ui/src/routes/ → pages: / (home), /status, /admin, /prompts, /config, /install
ui/build/     → production bundle served statically by FastAPI at /
```

## File Map

### `bot/main.py` — FastAPI Server (entry point)
- **Endpoints**: `POST /message` (main handler), `POST /transcribe` (audio→text), `POST /broadcast` (send to all partners)
- **Message flow**: `pre_route()` (identity/help only, no LLM) → language detection + translation → `detect_category()` / `classify_intent_category()` → `parse_intent()` (LLM) → `orchestrator.handle_intent()` → reply
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
- `get_prompt(category)` — checks `bot/prompts/{category}.txt` first; falls back to the registered Python prompt function (enables hot-reload without restart)
- `get_prompt_text(category)` / `list_prompt_categories()` — used by the Admin API prompt editor

#### `bot/skills/shopping.py`, `bot/skills/weather.py`, `bot/skills/calendar.py`
- Each registers its domain tools and its LLM prompt builder
- LLM prompts live here (not in `intent_parser.py`) so domains are fully isolated

#### `bot/skills/schemas.py`
- `ToolInput` — base Pydantic class for skill input schemas (extend per tool)
- `ToolOutput` — base Pydantic class: `{ok: bool, message: str|None, data: dict|None}`

#### `bot/skills/utils.py`
- `format_tool_reply(result)` — normalises any tool return value (str / dict / None) to a plain string for the reply

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

### `bot/admin/router.py` — Admin API
All endpoints are under `/admin/api/` and registered on the FastAPI app in `bot/main.py`.
- `GET  /admin/api/ping` — health check
- `GET  /admin/api/status` — FastAPI/Ollama/Bridge health + config array
- `GET  /admin/api/logs` — last N lines per service log file
- `GET  /admin/api/ollama/models` — list locally available Ollama models
- `GET  /admin/api/ollama/active` — currently loaded model (in-memory)
- `POST /admin/api/ollama/switch` — switch active model; optional `persist: bool` (default `true`) — when `false`, updates only the in-memory `intent_parser.MODEL` without writing `.env` (used for test loads)
- `POST /admin/api/ollama/tested` — mark a model as tested/compatible; saved to `bot/tested_models.json`; also removes from incompatible store
- `POST /admin/api/ollama/incompatible` — mark a model as incompatible; saved to `bot/incompatible_models.json`
- `POST /admin/api/services/{service}/restart|stop|start` — control fastapi/bridge/scheduler
- `POST /admin/api/services/restart-all` / `stop-all` — bulk service control
- `GET  /admin/api/prompts/{skill}` — get prompt text (override file or built-in)
- `PUT  /admin/api/prompts/{skill}` — write override file to `bot/prompts/{skill}.txt`
- `DELETE /admin/api/prompts/{skill}` — delete override file (revert to built-in)
- `GET  /admin/api/google-auth/status` — token status (auto-refreshes if expired + has refresh_token)
- `POST /admin/api/google-auth` — start OAuth flow: spins a wsgiref server on :8787, returns `auth_url`
- `POST /admin/api/google-auth/refresh` — force-refresh token via stored refresh_token
- `DELETE /admin/api/google-auth` — revoke token (delete token.json)
- All four Google OAuth routes are also available under `/admin/api/install/google-auth/*` (install wizard alias)
- `POST /admin/api/install/ollama/pull` — SSE stream of Ollama model pull progress
- `POST /admin/api/install/ollama/chat` — SSE stream of a single Ollama chat turn (model test)
- `GET  /admin/api/install/system-info` — system RAM in GB (macOS `sysctl`)
- `GET  /admin/api/install/ollama/keep-alive` — read `OLLAMA_KEEP_ALIVE` from env
- `POST /admin/api/install/ollama/keep-alive` — write `OLLAMA_KEEP_ALIVE` to `.env`

### `ui/` — Control Panel (SvelteKit)
- **Framework**: SvelteKit v2 + Svelte 5 runes mode (`$state`, `$effect`, `$derived`, `$props`, `{@render}`). Never use `$:` reactive statements — runes mode only.
- **UI library**: Skeleton UI v4 (cerberus theme). CSS imported via **relative paths** in `app.css` (Tailwind v4 cannot resolve `exports` globs in package imports)
- **Tailwind v4**: `@variant dark (&:where(.dark, .dark *));` in `app.css` is required for class-based dark mode (v4 defaults to media query)
- **Dark mode**: `.dark` class on `<html>` toggled via `localStorage` key `'colorMode'`. Both layout and home page keep a `toggleMode()` that syncs `classList` + storage
- **Adapter**: `adapter-static`, `fallback: 'index.html'`, builds to `ui/build/`. SSR disabled via `ui/src/routes/+layout.ts` (`ssr = false`, `prerender = false`)
- **Vite**: port 5252, `host: 'localhost'`. Proxy `/admin/api` and `/message` → `:8000`; 503 JSON error handler on `/admin/api`
- **Git info**: baked at build time in `vite.config.ts` via Vite `define` — `__GIT_HASH__`, `__GIT_DATE__`, `__GIT_BRANCH__`, `__GIT_COMMIT_URL__`. Displayed as a badge in the page footer (all pages)
- **Pages**:
  - `/` — home: logo, quick-link grid, dark/light toggle, CTA to install wizard
  - `/status` — live health cards (FastAPI/Ollama/Bridge), config table, log viewer with per-service tabs and 4s auto-refresh
  - `/admin` — service control (per-service Restart/Stop/Start + bulk actions) + model manager (real model list, switch button) + Google Account (Create Token, Re-authorize, Refresh Token, Token Status, Revoke Token)
  - `/prompts` — live prompt editor per skill (load/save/reset, `customised` badge when override file exists)
  - `/config` — Ollama model management: installed models list (with tested/incompatible/untested badges), "Load and Test the Model with HouseBot" section (routes through real `POST /message` pipeline; verdict buttons mark model as tested or incompatible), keep-alive setting, model catalog with pull
  - `/install` — installation wizard; Step 1 (Ollama) and Step 2 (Google OAuth) are interactive accordions; Steps 3–6 are static placeholders
- **Layout** (`ui/src/routes/+layout.svelte`): sidebar (60-wide, nav items, dark toggle in footer), topbar hidden on `/`, main content area with git badge footer
- All API calls use `fetch('/admin/api/...')` — never absolute URLs

### `housebot.sh` — Lifecycle Management
- Commands: `start`, `stop`, `restart`, `status`, `logs`, `logs-live`, `logs-rotate`, `qr`, `watchdog-start`, `watchdog-stop`, `ui-build`, `ui-dev`, `ui-stop`
- Spawns: FastAPI (uvicorn :8000), Bridge (node :3001), Scheduler
- Reads `LOG_LEVEL` from `.env` and passes `--log-level` to uvicorn
- Watchdog checks every 5 min and auto-restarts crashed services
- `ui-build` runs `npm run build` in `ui/`; `ui-dev` starts Vite dev server on :5252

## Key Patterns

### Intent Detection Pipeline
1. `pre_route(text)` — regex for **identity** and **help** only. Returns `None` for all other input. Domain-specific patterns (shopping, calendar, weather) were removed — they caused cross-domain false positives, especially on translated text.
2. `detect_language()` → if non-English, `translate_to_english()` → re-run `pre_route()` on the translated text
3. `detect_category(text)` — keyword/fuzzy match on first word (`shopping`, `calendar`, `weather`)
4. If no category: `classify_intent_category(text)` — LLM semantic fallback; prepends the detected category keyword
5. `parse_intent(text)` — LLM call with the category-specific prompt
6. `translate_from_english(reply, lang)` — translate reply back if the original was non-English

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
- `PARTNER_LID` — comma-separated `jid:name` entries (e.g. `93119@lid:Alice,12345@lid:Bob`); **the only JID list read by both `main.py` and `bridge/index.js`**. Name is optional; both consumer strip everything after `:` to obtain the bare JID.
- `GOOGLE_CALENDAR_NAME` — calendar to use
- `DEFAULT_CITY`, `DEFAULT_LATITUDE`, `DEFAULT_LONGITUDE` — weather defaults
- `WHISPER_MODEL` — faster-whisper model size (small/medium/large)
- `BRIEFING_TIME` — HH:MM format (default 07:30)
- `BRIEFING_LANGUAGE` — translate briefing (default English)
- `TIMEZONE_DEFAULT` — timezone for weather/calendar

## Conventions
- Python code uses `logging.getLogger(__name__)` — log level is re-applied in the FastAPI lifespan event (not just at import time) because uvicorn calls `logging.config.dictConfig()` after importing `main.py`, which resets the root logger
- LLM prompts live in `skills/<domain>.py` as the `prompt()` function registered via `register_prompt()`; override files in `bot/prompts/{skill}.txt` take priority at runtime
- JSON is the only LLM response format — never markdown, never plain text
- Fuzzy matching uses `difflib.SequenceMatcher` with threshold 0.82
- The bridge and FastAPI communicate only via HTTP (ports 3001 and 8000)
- The Control Panel communicates with FastAPI only via `/admin/api/*` endpoints — no direct DB or file access from the UI
- Svelte 5 runes mode: use `$state()`, `$effect()`, `$derived()`, `$props()` — never `$:` reactive statements
- Skeleton UI CSS must be imported with relative `../node_modules/...` paths in `app.css`
- No external cloud services except: Open-Meteo (free), Google Calendar API, WhatsApp (Meta)
- **StaticFiles mount order is critical**: `app.mount("/", StaticFiles(...))` must be the very last line in `bot/main.py`. Starlette resolves routes in registration order — mounting at `/` before route decorators causes `StaticFiles` to intercept all requests (POST included) and return 405.
- **Model compatibility tracking**: `bot/tested_models.json` and `bot/incompatible_models.json` store user-confirmed verdicts. The Config page "Load and Test" section calls `POST /message` with `sender: '__admin_test__'` so the full pipeline is exercised. The user then explicitly marks the model as tested (persists to `.env`, sets active) or incompatible (records it, restores previous model in-memory). Marking as tested also removes from the incompatible store.
- **`ollama/switch` with `persist: false`**: loads the model and updates `intent_parser.MODEL` in-memory without writing `.env`. Safe for test loads — the configured model is not silently changed until the user confirms.
- **Google OAuth local callback**: the flow runs a `wsgiref.simple_server` on port 8787 in a daemon thread. `OAUTHLIB_INSECURE_TRANSPORT=1` must be set because the redirect URI is `http://` (localhost only — safe). Token is saved to `creds/token.json`. The status endpoint auto-refreshes an expired token if a `refresh_token` is present, matching `calendar_handler.get_service()` behaviour.

## Copilot Agent Behaviours
- Write code directly in the correct file and location — never create a temporary file and ask the user to move it.
- When editing a file, use the editor tools to make precise changes — do not reproduce the entire file unless asked.
- If a file cannot be edited via tools, ask the user to do it — do not create external scripts as a workaround.
- Always find simple solutions that do not require new dependencies or complex refactors. If a change is needed across multiple files explain it clearly and seek for approvals before proceeding.
- The first step of processing any prompt is ALWAYS a proofread.
- After executing and testing code changes, provide the option to commit the changes in git with a clear commit message. Do not commit without asking.


