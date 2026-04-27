# HouseBot — Developer Reference

This document is for contributors and developers who want to understand the internals, extend the bot, or set up a dev environment.

> **New here?** See [README.md](README.md) for installation and usage instructions.

---

## Architecture

```
WhatsApp ←→ Bridge (Node.js, Baileys) :3001
                  ↕ HTTP
             FastAPI (Python) :8000
             ├── Intent Parser → Ollama LLM (local)
             │       ├── Embeddings (nomic-embed-text) — fast cosine-similarity pre-filter
             │       └── User Context (bot/user_context.json) — injected into every LLM call
             ├── Orchestrator  → Skills registry
             │       └── Skills (shopping, weather, calendar)
             │               └── Services (Shopping DB, weather API, Calendar API)
             ├── Transcription → faster-whisper (local)
             └── Admin API     → bot/admin/router.py (/admin/api/*)

Scheduler (Python, standalone) → broadcasts via FastAPI /broadcast

Control Panel (SvelteKit + Skeleton UI) :5252 (dev) / :8000 (production)
             └── /admin/api/* ──► FastAPI Admin Router
```

All services are managed by `housebot.sh` (start/stop/restart/watchdog). Logs and PIDs live in `logs/`.

---

## Tech stack

| Layer | Technology | Port |
|---|---|---|
| WhatsApp bridge | Node.js + Baileys | 3001 (internal) |
| Bot API | Python + FastAPI (uvicorn) | 8000 |
| Local LLM | Ollama | 11434 (default) |
| Embeddings | Ollama `nomic-embed-text` | (in-process via Ollama) |
| Speech-to-text | faster-whisper | (in-process) |
| Control Panel | SvelteKit + Skeleton UI + Tailwind v4 | :5252 dev / :8000 prod |

---

## Request flow

Every inbound message follows this exact sequence. **There is no LLM reasoning loop by design** — HouseBot handles simple, direct requests and the single-shot approach keeps latency low and output predictable.

```
Incoming message
      │
      ▼
 pre_route()  ── identity/help regex only (no LLM) ──►  action dict
      │ (miss)
      ▼
 language detection + translation (LLM + user context, only if non-English)
      │
      ▼
 detect_category()     ── keyword/fuzzy match (first pass)
 or classify_intent_category()  ── embedding cosine similarity (fast path)
                                    └── LLM semantic fallback (if embedding unclear)
      │ prepends detected category keyword
      ▼
 parse_intent()  ── LLM call → JSON {"action": "...", ...}
      │            user context injected into the prompt
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
 translate reply back (LLM + user context, only if non-English)
      │
      ▼
  {"reply": "...", "notification": "..."}
```

### Why no LLM loop

HouseBot intentionally avoids a reasoning loop (ReAct / tool-chaining). One message → one LLM call → one tool → one reply. This is the right trade-off for a household bot with simple, direct requests: it keeps latency low, output deterministic, and the system easy to debug. Multi-step agentic chains would add hallucination risk and complexity without benefit for this use case.

### User context injection

`bot/user_context.json` stores two fields: `language` (user's preferred language) and `instructions` (free-form behavioural rules, auto-translated to English at save time). They are injected selectively — not into every LLM call:

| LLM call | `language` | `instructions` | When triggered |
|---|---|---|---|
| `detect_language()` | ✅ disambiguation hint | — | Every non-pre_route message |
| `translate_to_english()` | — | ✅ appended as rules | Non-English messages only |
| `translate_from_english()` | — | ✅ appended as rules | Non-English messages only |
| `parse_intent()` | — | ✅ appended after skill prompt | Every non-pre_route message |

For English-speaking users, only `instructions` reaches `parse_intent()` — useful for custom item mappings or naming conventions. For non-English users, both translation passes also apply the rules.

The file is managed through the Control Panel (Prompting page) and is excluded from git.

### Embeddings fast path

At startup, `intent_parser.py` pre-computes anchor vectors for the three domains (shopping, weather, calendar) using `nomic-embed-text` via Ollama. Incoming (translated) messages are embedded and compared via cosine similarity. If a domain exceeds the threshold, it skips the LLM classification call. Only ambiguous messages fall through to the LLM.

---

## Project structure

```
house-bot/
├── bot/                                ← FastAPI server + NLP/LLM layer
│   ├── main.py                         ← entry point, /message, /transcribe, /broadcast
│   ├── intent_parser.py                ← language detection, translation, embeddings, intent parsing
│   ├── orchestrator.py                 ← action-to-tool mapping and skill dispatch
│   ├── scheduler.py                    ← morning briefing (standalone process)
│   ├── user_context.json               ← runtime-only (gitignored), managed via Admin API
│   ├── ollama_models.json              ← user-confirmed model verdicts (tested / incompatible)
│   ├── admin/
│   │   └── router.py                   ← Admin API (/admin/api/*)
│   ├── prompts/                        ← optional hot-reload prompt overrides ({skill}.txt)
│   ├── skills/                         ← tool registry + per-domain skills + LLM prompts
│   │   ├── registry.py                 ← register(), get(), register_prompt(), get_prompt()
│   │   ├── shopping.py / weather.py / calendar.py
│   │   ├── schemas.py                  ← ToolInput / ToolOutput base Pydantic models
│   │   └── utils.py
│   └── services/                       ← business logic (no HTTP/skills awareness)
│       ├── shopping_db.py              ← SQLite shopping list
│       ├── weather.py                  ← Open-Meteo API
│       ├── calendar_handler.py         ← Google Calendar API
│       └── db/                         ← SQLite schema + database
├── bridge/
│   └── index.js                        ← WhatsApp bridge (Node.js, Baileys)
├── ui/                                 ← SvelteKit control panel
│   ├── src/routes/                     ← pages: /, /status, /admin, /prompts, /config, /install
│   ├── build/                          ← production build served by FastAPI (gitignored)
│   └── vite.config.ts                  ← git info baked at build time, proxy /admin/api → :8000
├── creds/                              ← Google OAuth credentials + token (gitignored)
├── logs/                               ← process logs and PIDs (gitignored)
├── scripts/
│   └── smoke_test.sh
├── .env                                ← environment variables (gitignored)
├── requirements.txt
├── housebot.sh                         ← CLI lifecycle management
└── install.sh                          ← one-shot installer (macOS)
```

---

## Key configuration variables (`.env`)

| Variable | Description |
|---|---|
| `OLLAMA_URL` | Ollama API endpoint (default `http://localhost:11434/api/chat`) |
| `OLLAMA_MODEL` | Active LLM model name |
| `OLLAMA_KEEP_ALIVE` | How long Ollama keeps the model in memory (e.g. `5m`, `30m`) |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` — passed to uvicorn |
| `PARTNER_LID` | Comma-separated `jid:name` pairs authorised to use the bot |
| `GOOGLE_CALENDAR_NAME` | Calendar to read/write events on |
| `DEFAULT_CITY`, `DEFAULT_LATITUDE`, `DEFAULT_LONGITUDE` | Default weather location |
| `WHISPER_MODEL` | faster-whisper model size (`small` / `medium` / `large`) |
| `BRIEFING_TIME` | HH:MM for the morning briefing (default `07:30`) |
| `BRIEFING_LANGUAGE` | Language for the morning briefing (default English) |
| `TIMEZONE_DEFAULT` | Timezone for weather and calendar display |

See `.env.example` for the full list.

---

## Adding a new skill

The skills layer is the extension point. Adding a new capability requires no changes to `main.py` or `orchestrator.py`.

1. Create `bot/skills/mynewskill.py`
2. Define Pydantic input schemas (extend `ToolInput`)
3. Write a callable: `payload → services/ call → {"ok": bool, "message": str}`
4. Call `register("mynewskill.action", fn, input_schema=..., desc="...")`
5. Optionally call `register_prompt("mynewskill", prompt_fn)` for the LLM prompt
6. Import the module in `bot/skills/__init__.py`
7. Add the action mapping in `bot/orchestrator.py → action_to_tool()`

### LLM prompt hot-reload

Prompts registered via `register_prompt()` can be overridden at runtime without restarting the bot: create `bot/prompts/{skill}.txt` and the registry will use that file instead. Delete it to revert to the Python-defined prompt. The Control Panel's Prompts page manages this directly.

---

## LLM interaction conventions

- All LLM calls use `requests.post(OLLAMA_URL, json={...})` — no SDK
- JSON is the only response format — never markdown, never plain text
- `_parse_raw(raw)` extracts JSON from LLM response (handles double braces, finds first `{...}`)
- Temperature: `0` for classification/validation, `0.1` for intent parsing, `0.9` for quote generation
- Fuzzy matching uses `difflib.SequenceMatcher` with threshold `0.82`

---

## UI development

The Control Panel is SvelteKit v2 + Svelte 5 (runes mode). **Never use `$:` reactive statements** — use `$state()`, `$effect()`, `$derived()`, `$props()`.

```bash
cd ui
npm run dev     # Vite dev server on :5252 with HMR (proxy /admin/api → :8000)
npm run build   # production build → ui/build/ (served by FastAPI)
```

Or via `housebot.sh`:

```bash
./housebot.sh ui-dev    # start Vite dev server
./housebot.sh ui-build  # production build
```

The production build must be rebuilt after any UI source changes:

```bash
./housebot.sh ui-build
./housebot.sh restart
```

### CSS notes

- Skeleton UI CSS is imported with **relative paths** in `app.css` (Tailwind v4 cannot resolve `exports` globs in package imports)
- `@variant dark (&:where(.dark, .dark *));` in `app.css` is required for class-based dark mode
- Dark mode toggle: `.dark` class on `<html>`, persisted in `localStorage` key `'colorMode'`

### Static file serving

`app.mount("/", StaticFiles(...))` must be the **very last line** in `bot/main.py`. Starlette resolves routes in registration order — mounting at `/` before route decorators causes StaticFiles to intercept all requests and return 405.

The custom `_SPAStaticFiles` class never falls back to `index.html` for `/admin/api` or `/message` paths.

---

## Available `housebot.sh` commands

```bash
./housebot.sh start           # start FastAPI, Bridge and Scheduler
./housebot.sh stop            # stop everything
./housebot.sh restart         # restart everything
./housebot.sh status          # show process status
./housebot.sh logs            # show recent logs for all processes
./housebot.sh logs-live       # follow all logs in real time
./housebot.sh logs-rotate     # rotate logs manually
./housebot.sh qr              # follow bridge log (for QR code on first run / re-auth)
./housebot.sh watchdog-start  # start background watchdog (auto-restarts crashed services)
./housebot.sh watchdog-stop   # stop watchdog
./housebot.sh ui-build        # compile ui/src/ → ui/build/
./housebot.sh ui-dev          # start Vite dev server on :5252
./housebot.sh ui-stop         # stop Vite dev server
```

---

## Updating (manual / CLI)

```bash
# Download housebot-<version>.zip from the Releases page (not "Source code")
unzip housebot-*.zip -d housebot-new
cp housebot-new/* . -r   # preserve .env, creds/, logs/, bridge/baileys_auth/
pip install -r requirements.txt
./housebot.sh ui-build
./housebot.sh restart
```

---

## Logging conventions

- `logging.getLogger(__name__)` throughout
- Log level is re-applied in the FastAPI lifespan event (not just at import time) because uvicorn calls `logging.config.dictConfig()` after importing `main.py`, which resets the root logger

---

## Notes for contributors

- The bridge and FastAPI communicate **only via HTTP** (ports 3001 and 8000)
- The Control Panel communicates with FastAPI only via `/admin/api/*` — no direct DB or file access from the UI
- `bot/ollama_models.json` stores user-confirmed model verdicts (`{"tested": [...], "incompatible": [...]}`)
- `ollama/switch` with `persist: false` loads a model in-memory without writing `.env` — safe for test loads
- Google OAuth local callback runs a `wsgiref.simple_server` on port 8787. `OAUTHLIB_INSECURE_TRANSPORT=1` must be set (localhost-only — safe)
- All API calls from the UI use relative URLs (`/admin/api/...`) — never absolute URLs
