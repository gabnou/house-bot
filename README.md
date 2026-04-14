# HouseBot


Domestic WhatsApp bot for shared management of a shopping list between multiple partners, weather, and a shared Google Calendar. It also supports speech-to-text capabilities, automatically transcribing voice messages using a local model. Runs entirely locally on your own computer — no data is sent to external clouds except for explicitly configured third-party APIs.

**Tested on macOS (MacBook).** Local setup steps and requirements may differ on Windows or Linux systems, especially regarding Python, Node.js, and hardware compatibility. Adjustments may be needed for your specific architecture.

**Memory requirements depend on the LLM model you choose:**
- For example, `mistral-small:22b` requires at least 16GB of RAM.
- Lighter models like `llama3.1:8b` can run on systems with 8GB of RAM or more.
- See the [Ollama models page](https://ollama.com/library) for a full list of available models and their memory requirements.

**First request warm-up:** The LLM model is loaded into memory on demand — the very first message after starting the bot (or after a period of inactivity) will take noticeably longer to respond while Ollama loads the model. Subsequent messages are fast. By default, Ollama keeps the model in memory for **5 minutes** after the last request, then unloads it to free RAM. This timeout can be adjusted with the `OLLAMA_KEEP_ALIVE` environment variable (e.g. `OLLAMA_KEEP_ALIVE=30m` to extend it to 30 minutes).

**Prompt tuning:** Since LLMs are non-deterministic, the bot's accuracy may vary depending on the model you run. If you notice the bot misinterpreting commands or producing unexpected results, you can fine-tune the prompts located in `bot/intent_parser.py`. Adding more detailed or specific prompts will help the bot better understand user intent and improve overall accuracy.

**Multi-language support:** The bot expects English as the default language, but it can communicate in any language — including voice messages. When a text or audio message is not understood, the bot uses the LLM to detect the source language. If a non-English language is identified, the message is automatically translated to English, processed through the normal command pipeline, and the response is translated back into the detected language. This makes the bot accessible to users in any language without additional configuration. Note that language detection and translation require multiple LLM calls, which will noticeably slow down response times on machines with limited RAM where the model cannot stay fully loaded in memory.

**WhatsApp number and Personal BOT:** For multi-partner use, HouseBot requires a dedicated WhatsApp phone number (SIM card) to act as the bot. All partners interact with the bot via this number. For single-user scenarios, you may register your own WhatsApp number and interact with HouseBot through your personal self-chat, enabling all features without a separate SIM.

---

## Features

- **Shopping list** — add, remove, view and manage by category (food, other, clothing, health)
- **Weather** — current conditions and forecasts via Open-Meteo (free, no key required)
- **Google Calendar** — read, add, edit and delete events (calendar configurable via `.env`)
- **Voice messages** — voice notes (PTT) automatically transcribed with faster-whisper (local), validated by the LLM and processed as normal commands
- **Multi-language support** — the bot is English by default to keep it international, but if a message in a different language is not understood, the bot automatically detects the language, translates the message to English, re-runs the command pipeline, and replies in the detected language
- **Morning briefing** — automatic message at 07:30 (local time) with weather, today's events and motivational quote. Set `BRIEFING_TIME` in `.env` (e.g. `08:00`) to change the schedule. The briefing is in English by default; set `BRIEFING_LANGUAGE` in `.env` (e.g. `Spanish`, `Italian`) to receive it in a different language
- **Free conversation** — LLM-generated replies for messages not recognized as commands

---

## Architecture

```text
WhatsApp (Partner 1 / Partner 2)
        │
        ▼
WhatsApp Servers (Meta)
        │  WebSocket session
        ▼
Baileys Bridge (Node.js)         ← bridge/index.js           :3001
        │  HTTP
        ▼
FastAPI Server (Python)          ← bot/main.py               :8000
   ├── Whisper (transcription)   ← faster-whisper (local)
   ├── Intent Parser             ← bot/intent_parser.py → Ollama (local LLM)
   ├── Orchestrator              ← bot/orchestrator.py  → Skills registry
   │       └── Skills            ← bot/skills/  (shopping, weather, calendar)
   │               └── Services  ← bot/services/ (DB, weather API, Google Calendar)
   ├── Admin API                 ← bot/admin/router.py (services, models, prompts, logs)
   └── Scheduler                 ← bot/scheduler.py     → morning briefing

Control Panel (SvelteKit + Skeleton UI)                       :5252
        └── /admin/api/* ──► FastAPI Admin Router
```

The **Control Panel** is a browser-based UI for configuration, monitoring, and management. It communicates exclusively with the FastAPI Admin Router via `/admin/api/*` endpoints. After the bot is started, all day-to-day operations (service control, model switching, prompt editing, status monitoring) are available there.

### Request flow

Every inbound message follows this exact sequence — **one LLM call, one action, one reply**. There is no reasoning loop by design: HouseBot handles simple, direct requests and the single-shot approach keeps latency low and output predictable.

```text
Incoming message
      │
      ▼
 language detection + translation (LLM, only if non-English)
      │
      ▼
 pre_route()  ──── fast regex match (no LLM) ───► action dict
      │ (miss)
      ▼
 parse_intent()  ── LLM call → JSON {"action": "...", ...} ──► action dict
      │
      ▼
 orchestrator.py
      │  action_to_tool("weather_forecast") → "weather.forecast"
      ▼
 bot/skills/registry  →  get("weather.forecast")  →  forecast_tool(payload)
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

### Why the skills layer matters

The `bot/skills/` package is the extension point of the bot. Each domain (shopping, weather, calendar) registers its tools in a central registry with:
- **Pydantic input schema** — parameters are validated before any business logic runs
- **Own LLM prompt** — the `register_prompt()` call lets each skill own its few-shot examples, keeping domains isolated
- **Callable** — a plain Python function that maps the validated payload to a `services/` call and returns a dict

Adding a new capability (e.g. home automation, reminders) means creating a new `bot/skills/X.py` file with one or more `register()` calls — no changes to `main.py`, `orchestrator.py`, or any other skill.

This is intentionally **not** an agentic loop. HouseBot does not let the LLM chain multiple tool calls or reason across steps. One message → one intent → one tool → one reply. This trade-off is deliberate: for a household WhatsApp bot with simple, direct requests, a reasoning loop would add latency, hallucination risk, and complexity without meaningful benefit.

---

## Project Structure

```shell
house-bot/
├── bridge/                             ← Baileys WhatsApp bridge (Node.js)
│   ├── index.js
│   ├── package.json
│   └── baileys_auth/                   ← WhatsApp session (auto-generated)
├── bot/                                ← FastAPI server + all Python logic
│   ├── main.py                         ← entry point, mounts admin router + static UI
│   ├── intent_parser.py                ← LLM parsing → JSON action
│   ├── orchestrator.py                 ← routes action → skill
│   ├── scheduler.py                    ← morning briefing
│   ├── admin/                          ← Admin API (service control, models, prompts, logs)
│   ├── skills/                         ← tool registry + per-domain skills + LLM prompts
│   │   └── registry.py                 ← checks bot/prompts/{skill}.txt for hot-reload overrides
│   └── services/                       ← business logic (Shopping DB, weather, Google Calendar)
│       └── db/                         ← SQLite schema + database (auto-generated)
├── ui/                                 ← SvelteKit control panel (Skeleton UI, Tailwind v4)
│   ├── src/routes/                     ← pages: home, status, admin, prompts, config, install
│   ├── static/                         ← logo + favicon
│   ├── build/                          ← production build served by FastAPI (generated)
│   └── package.json
├── creds/                              ← Google OAuth credentials + token (auto-generated)
├── logs/                               ← process logs (generated by housebot.sh)
├── .env                                ← environment variables (created at first run)
├── requirements.txt
└── housebot.sh                         ← CLI lifecycle management
```

---

## Prerequisites

- [Homebrew](https://brew.sh)
- Python 3.11+
- Node.js 18+
- Ollama
- A dedicated WhatsApp number (separate SIM, or your own number for single-user)
- A Google account

---

## Installation

### 1 — Clone the repository

```bash
git clone <repo-url> house-bot
cd house-bot
```

### 2 — Install Node.js and Ollama

```bash
brew install node
brew install ollama
```

### 3 — Download the LLM model

```bash
ollama serve &
ollama pull mistral-small:22b
```

For a lighter model (requires less RAM):

```bash
ollama pull llama3.1:8b
```

### 4 — Install dependencies

```bash
# WhatsApp bridge
cd bridge && npm install && cd ..

# Control panel UI (install + production build)
./housebot.sh ui-build

# Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> The production UI build is placed in `ui/build/` and served statically by FastAPI at `http://localhost:8000/`. You only need to rebuild when UI source files change (`./housebot.sh ui-build`).

### 5 — Start and configure via the UI

```bash
ollama serve &
./housebot.sh start
```

Then open **http://localhost:8000** and use the **Installation** wizard to:
- Configure `.env` (Ollama model, location, partners, calendar, timezone …)
- Set up Google Calendar OAuth
- Pair WhatsApp via QR code
- Discover partner JIDs
- Run a smoke test

---

## Usage

`housebot.sh` manages all processes from the CLI. Once the bot is running, the **Control Panel** is available at **http://localhost:8000** — served directly by FastAPI alongside the bot API.

### Tech stack

| Layer | Technology | Port |
|---|---|---|
| WhatsApp bridge | Node.js + Baileys | 3001 (internal) |
| Bot API | Python + FastAPI (uvicorn) | 8000 |
| Local LLM | Ollama | 11434 (default) |
| Speech-to-text | faster-whisper | (in-process) |
| Control Panel | SvelteKit + Skeleton UI + Tailwind v4 | served at :8000/ |

The Control Panel production build (`ui/build/`) is served statically by FastAPI. No separate server is needed in production — everything is on port **8000** and proxied through the bot.

### Make the script executable (first time only)

```bash
chmod +x housebot.sh
```

### Available commands

```bash
./housebot.sh start        # start FastAPI, Bridge and Scheduler (requires Ollama already running)
./housebot.sh stop         # stop everything
./housebot.sh restart      # restart everything
./housebot.sh status       # show process status
./housebot.sh logs         # show recent logs for all processes
./housebot.sh logs-live    # follow all process logs in real time
./housebot.sh logs-rotate  # manually rotate logs (also runs automatically on start)
./housebot.sh qr           # follow bridge log in real time (for QR code on first run)
./housebot.sh ui-build     # rebuild the control panel UI (run after pulling UI changes)
./housebot.sh ui-dev       # start Vite dev server on :5252 (UI development only)
```

> **UI development:** `./housebot.sh ui-dev` starts the Vite dev server at **http://localhost:5252** with HMR — for UI development only. It proxies `/admin/api/*` to the FastAPI server at `:8000`, so the bot must be running alongside. In production, always use **http://localhost:8000**.

### UI development

When working on the Control Panel source files (`ui/src/`), use the Vite dev server for instant feedback via HMR:

```bash
# Terminal 1 — bot must be running
ollama serve &
./housebot.sh start

# Terminal 2 — UI dev server
./housebot.sh ui-dev
```

The dev server is always available at **http://localhost:5252** and proxies all `/admin/api/*` calls to the bot at `:8000`. When you’re done, rebuild the production bundle:

```bash
./housebot.sh ui-build
```

### Typical startup

```bash
# Start Ollama (must be running before housebot.sh start)
ollama serve &

# Normal startup
./housebot.sh start
./housebot.sh status

# Open the control panel
open http://localhost:8000
```

---

## WhatsApp Commands

Send messages directly to the bot's number in a private chat.

**Language** — the bot is built in English but understands and replies in any language. When a message is not recognised as English, it is automatically translated to English, processed, and the reply is translated back to the detected language. This works for both text and voice messages.

**Custom prompts** — the command examples below reflect the default built-in behaviour. You can extend or tune intent recognition per skill (shopping, weather, calendar) directly in the Control Panel at **http://localhost:8000** → Prompting, without restarting the bot.

**Category keywords** — commands start with `shopping`, `weather` or `calendar` to disambiguate the intent.

**Automatic pre-routing** — without a category keyword, the bot assumes you want to mainly interact with the **shopping list** and directly recognizes the most common patterns without going through the LLM:

| Message (examples) | Action |
|---|---|
| `show`, `list`, `shopping list`, `what's missing?` | show the shopping list |
| `add yogurt`, `add bread and milk` | add items to the shopping list |
| `bought milk`, `I bought bread` | mark as bought |
| `remove bread`, `delete eggs` | remove from shopping list |
| `calendar`, `agenda`, `appointments`, `what do I have today?` | show today's events |

**Voice messages** — voice notes (PTT) are automatically transcribed in any language. If the transcription is not understandable, the bot asks you to repeat.

### Shopping List

```text
shopping add milk and eggs
shopping add ibuprofen
shopping what's missing?
shopping what's missing for food?
shopping bought apples
shopping remove pasta
shopping clear
--
add yogurt                    ← no prefix: shopping pre-routing
add bread and milk            ← no prefix: shopping pre-routing
show                          ← no prefix: show list
shopping list                 ← no prefix: show list
bought milk                   ← no prefix: shopping pre-routing
remove bread                  ← no prefix: shopping pre-routing
```

### Weather

```text
weather
weather now
weather now in Milan
weather tomorrow
weather next weekend
weather next 4 days
weather next 3 days in Madrid
weather next 6 hours in Lecce
```

### Family Calendar

```text
calendar today
calendar tomorrow
calendar day after tomorrow
calendar this week
calendar next week
calendar next two weeks
calendar next three weeks
calendar next 3 days
calendar April 9th
calendar show events for April 9th
calendar April
calendar April events
calendar May appointments
calendar from the 5th to the 20th of April
calendar details dinner with Mario
calendar add dinner with Mario Friday March 28th at 9pm
calendar add doctor visit on April 5th at 10am in Barcelona
calendar delete dinner with Mario
calendar move doctor visit to April 6th at 11am
calendar move Rossella appointment from April 2nd to April 9th
--
calendar                      ← no prefix: show today's events
agenda                        ← no prefix: show today's events
what do I have today?         ← no prefix: show today's events

```
