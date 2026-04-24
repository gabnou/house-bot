# housebot

![housebot-logo](img/housebot_logo_v2_small.png)

Domestic WhatsApp bot for shared management of a shopping list between multiple partners, weather, and a shared Google Calendar. It also supports speech-to-text capabilities, automatically transcribing voice messages using a local model. Runs entirely locally on your own computer — no data is sent to external clouds except for explicitly configured third-party APIs.

**macOS only.** HouseBot's installer relies on [Homebrew](https://brew.sh) and is designed and tested exclusively on macOS. It will not run on Windows or Linux as-is.

**Memory requirements depend on the LLM model you choose:** LLM models are very memory intensive. For example:

- `mistral-small:22b` requires at least 16GB of RAM.
- Lighter models like `llama3.1:8b` can run on systems with 8GB of RAM or more.
- See the [Ollama models page](https://ollama.com/library) for a full list of available models and their memory requirements.

**First request warm-up:** The LLM model is loaded into memory on demand — the very first message after starting the bot (or after a period of inactivity) will take noticeably longer to respond while Ollama loads the model. Subsequent messages are fast. By default, Ollama keeps the model in memory for **5 minutes** after the last request, then unloads it to free RAM. This timeout can be adjusted with the `OLLAMA_KEEP_ALIVE` environment variable (e.g. `OLLAMA_KEEP_ALIVE=30m` to extend it to 30 minutes).

**Prompt tuning:** Since LLMs are non-deterministic, the bot's accuracy may vary depending on the model you run. If you notice the bot misinterpreting commands or producing unexpected results, you can fine-tune the prompts located in `bot/intent_parser.py`. Adding more detailed or specific prompts will help the bot better understand user intent and improve overall accuracy.

**Multi-language support:** The bot expects English as the default language, but it can communicate in any language — including voice messages. When a text or audio message is not understood, the bot uses the LLM to detect the source language. If a non-English language is identified, the message is automatically translated to English, processed through the normal command pipeline, and the response is translated back into the detected language. This makes the bot accessible to users in any language without additional configuration. Note that language detection and translation require multiple LLM calls, which will noticeably slow down response times on machines with limited RAM where the model cannot stay fully loaded in memory.

**WhatsApp number:** HouseBot needs a WhatsApp number to act as the bot.
- **Multi-partner use** — a dedicated phone number (separate SIM card) is required so all partners can message the bot. Each partner is individually authorized via the Installation Wizard.
- **Personal use** — no extra SIM needed. You can link your own WhatsApp number and interact with the bot through self-chat (messaging yourself), giving you full access to all features from a single device.

---

## Features

- **Shopping list** — add, remove, view and manage by category (food, other, clothing, health)
- **Weather** — current conditions and forecasts via Open-Meteo (free, no key required)
- **Google Calendar** — read, add, edit and delete events (calendar configurable via `.env`)
- **Voice messages** — voice notes (PTT) automatically transcribed with faster-whisper (local), validated by the LLM and processed as normal commands
- **Multi-language support** — the bot is English by default to keep it international, but if a message in a different language is not understood, the bot automatically detects the language, translates the message to English, re-runs the command pipeline, and replies in the detected language
- **Morning briefing** — automatic message at 07:30 (local time) with weather, today's events and a motivational quote. The schedule and language are configured in the Installation Wizard (Step 5). You can also set `BRIEFING_TIME` and `BRIEFING_LANGUAGE` directly in `.env`
- **Free conversation** — LLM-generated replies for messages not recognized as commands

---

## Prerequisites

- A Mac running macOS (Homebrew, Python, Node.js and Ollama are installed automatically)
- A WhatsApp number for the bot — a **dedicated SIM** for multi-partner setups, or your **own number** for personal single-user use
- A Google account (only if you want the bot to manage a Google Calendar — this skill is optional)

---

## Installation

### 1 — Download and extract the latest release

Go to the [Releases page](https://github.com/gabnou/house-bot/releases/latest) and download the **`housebot-<version>.zip`** asset (not "Source code"). Then extract it and enter the folder:

```bash
unzip housebot-*.zip
cd housebot-*
```

### 2 — Run the installer

```bash
chmod 755 install.sh
./install.sh
```

The installer handles everything automatically (macOS only):
- Installs Homebrew, Python 3.11+, Node.js, and Ollama if missing
- Creates the Python virtual environment and installs all dependencies
- Installs bridge Node.js dependencies and builds the Control Panel UI
- Creates a default `.env` from `.env.example`
- Starts Ollama and all HouseBot services

### 3 — Open the Control Panel and complete configuration

When the installer finishes, the **Control Panel** is available at **[http://localhost:5252](http://localhost:5252)**. This is the browser UI for managing the bot — you will use it for all configuration, monitoring, and day-to-day operations.

Head to **[http://localhost:5252/install](http://localhost:5252/install)** and follow the step-by-step wizard to finish setup. There is no need to edit `.env` manually — the wizard covers everything:

| Step | What it does |
|---|---|
| **1. Ollama — AI Models** | Choose and pull a local LLM model; set the keep-alive timeout; test the model through the real HouseBot pipeline and mark it as tested (sets it active) or incompatible |
| **2. Google OAuth** | Authorize Google Calendar access and store the OAuth token — **only required if you want to use the Calendar skill** (requires `creds/client_google_api_calendar.json` from Google Cloud Console) |
| **3. WhatsApp Pairing** | Scan the QR code to link the dedicated WhatsApp number; set the linked-device display name (`WHATSAPP_APPNAME`) |
| **4. Sender Restrictions** | Send a message from each partner's phone, scan for it here, and authorize the JID — saved automatically to `.env` |
| **5. Location & Briefing** | Search for your city on a map to auto-fill coordinates and timezone; pick the morning briefing language |

All settings are saved directly to `.env` and take effect immediately (a bridge restart is prompted when needed).

> **Skills are optional.** The three built-in skills — Shopping list, Weather, and Google Calendar — work independently of each other. You can use just the ones you need:
> - **Shopping list** works out of the box with no extra configuration.
> - **Weather** works out of the box (Open-Meteo is free and requires no API key). Set your default city in Step 5.
> - **Google Calendar** requires a Google account and OAuth setup (Step 2 of the wizard). Skip it entirely if you don't need calendar management.

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
   ├── Intent Parser             ← bot/intent_parser.py
   │       ├── Embeddings        ← Ollama nomic-embed-text (local) — category classification
   │       ├── LLM               ← Ollama (local) — intent parsing, translation, fallback
   │       └── User Context      ← bot/user_context.json — injected into every LLM call
   ├── Orchestrator              ← bot/orchestrator.py  → Skills registry
   │       └── Skills            ← bot/skills/  (shopping, weather, calendar)
   │               └── Services  ← bot/services/ (DB, weather API, Google Calendar)
   ├── Admin API                 ← bot/admin/router.py (services, models, prompts, logs, user context)
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
 pre_route()  ── identity/help regex only (no LLM) ──► action dict
      │ (miss)
      ▼
 detect_language()  ──► LLM call + user context (language hint)
      │  if non-English:
      ▼
 translate_to_english()  ──► LLM call + user context (vocabulary hints)
      │
      ▼
 detect_category()  ── keyword/fuzzy match ──► category or None
      │  (None)
      ▼
 classify_intent_category()
      │   ├─ fast path: embedding cosine similarity
      │   │       └── nomic-embed-text anchors (pre-computed at startup)
      │   └─ fallback: LLM classification call
      │
      ▼
 parse_intent()  ── LLM call + user context → JSON {"action": "...", ...} ──► action dict
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
 translate_from_english()  ──► LLM call + user context (only if non-English)
      │
      ▼
  {"reply": "...", "notification": "..."}
```

**User context** is a household-specific behavioural profile (preferred language + custom instructions) stored in `bot/user_context.json` and managed via the Prompting page in the Control Panel. When active, it is injected into every LLM call — language detection, translation, and intent parsing — so the model respects household vocabulary, preferred output style, and any domain-specific quirks without changing the prompts in the code.

**Embedding-based classification** uses a local `nomic-embed-text` model (via Ollama) to compute cosine similarity between the incoming message and pre-computed anchor vectors for each skill category. The anchor mean vectors are computed at startup in a background thread and cached in memory. This fast path avoids a full LLM call for category detection in most cases; the LLM classifier only runs as a fallback when embedding confidence is below the threshold (0.50 cosine similarity).

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

The Control Panel production build (`ui/build/`) is served as static files by FastAPI. No separate server is needed — everything runs on port **8000**.

> **`ui/build/` is not committed to git.** It is created by `install.sh` on first installation and must be rebuilt manually after pulling UI source changes (see [Pulling updates](#pulling-updates) below).

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
./housebot.sh ui-build     # compile ui/src/ → ui/build/ (required after UI source changes)
./housebot.sh ui-dev       # start Vite dev server on :5252 (UI development only, on demand)
```

### Typical startup

```bash
# Start Ollama (must be running before housebot.sh start)
ollama serve &

# Start the bot (auto-builds ui/build/ only if absent, i.e. fresh clone)
./housebot.sh start
./housebot.sh status

# Open the control panel
open http://localhost:8000
```

---

### Updating HouseBot

The easiest way to update is through the **Control Panel** at **http://localhost:8000** → Admin → HouseBot Software Update. The page automatically checks for a newer release on GitHub. When one is available, click **Update Now** — the update runs in the background and shows live progress. It:

1. Downloads the release zip from GitHub
2. Applies updated files (your `.env`, credentials, logs, database and WhatsApp session are never overwritten)
3. Installs any new Python dependencies
4. Rebuilds the UI bundle
5. Restarts all services automatically

**Manual update via CLI** — if the bot is not running, download the `housebot-<version>.zip` asset from the [Releases page](https://github.com/gabnou/house-bot/releases/latest) (not "Source code"), extract it over the existing folder (preserve your `.env` and `creds/`), then:

```bash
./housebot.sh ui-build   # only needed if ui/src/ changed
./housebot.sh restart
```

---

### UI development

The Control Panel has two independent serving modes:

| Mode | Command | URL | Reflects source changes |
|---|---|---|---|
| **Dev server** | `cd ui && npm run dev` | :5252 | Instantly (HMR) |
| **Production build** | `./housebot.sh ui-build` then `restart` | :8000 | After each build |

When working on `ui/src/`, use the dev server for instant feedback, then rebuild for production when done:

```bash
# Terminal 1 — bot must be running
ollama serve &
./housebot.sh start

# Terminal 2 — UI dev server (foreground, Ctrl+C to stop)
cd ui && npm run dev
# → edit files in ui/src/, changes appear at http://localhost:5252 immediately

# When finished, publish to production:
./housebot.sh ui-build && ./housebot.sh restart
# → changes now visible at http://localhost:8000
```

---

## Commands

Send messages directly to the bot's number in a private chat.

**Language** — the bot is built in English but understands and replies in any language. Every incoming message is first checked against the language detection pipeline. If a non-English message is detected with sufficient confidence, it is automatically translated to English, processed through the normal command pipeline, and the reply is translated back into the original language. This works for both text and voice messages — including the `help` and identity commands below.

**Voice messages** — voice notes (PTT) are automatically transcribed in any language using a local speech-to-text model. If the transcription is not understandable, the bot asks you to repeat.

**User context** — you can fine-tune how the bot interprets your household's messages (vocabulary quirks, preferred tone, domain-specific terms) in the Control Panel at **http://localhost:5252** → Prompting. Changes take effect on the next message without a restart.

**How intent is recognised** — the bot uses a two-step process to identify what you mean:

1. **Category hint (fast)** — if your message starts with `shopping`, `weather`, or `calendar` the bot uses that as a direct hint and skips classification entirely, going straight to intent parsing.
2. **Automatic classification (no prefix needed)** — if there is no keyword, the bot computes an embedding of your message and compares it to pre-trained anchor vectors for each skill (cosine similarity). In the rare case that confidence is too low, it falls back to a single LLM classification call. Either way, the bot figures out which skill you mean — you do not need to prefix your messages.

The only two commands that bypass this pipeline entirely (no LLM, no embedding) are:

| Message | Action |
|---|---|
| `help`, `what can you do`, `commands` | show the list of available commands |
| `who are you`, `what's your name` | bot introduces itself |

These work in any language — the message is translated to English first if needed, then matched.

### Shopping List

```text
add milk and eggs
add ibuprofen
what's missing?
what's missing for food?
I bought apples
bought milk
remove pasta
clear the list
--
shopping add milk and eggs        ← explicit keyword: skips classification
shopping what's missing for food?
shopping bought apples
shopping remove pasta
shopping clear
```

### Weather

```text
weather now
weather now in Milan
weather tomorrow
weather next weekend
weather next 4 days
weather next 3 days in Madrid
weather next 6 hours in Lecce
--
weather                           ← explicit keyword: skips classification
forecast next 4 days              ← no prefix: classified automatically
forecast London
```

### Calendar

```text
what do I have today?
tomorrow
this week
next week
next two weeks
events in April
events from the 5th to the 20th of April
details dinner with Mario
add dinner with Mario Friday March 28th at 9pm
add doctor visit on April 5th at 10am in Barcelona
delete dinner with Mario
move doctor visit to April 6th at 11am
move Rossella appointment from April 2nd to April 9th
--
calendar today                    ← explicit keyword: skips classification
calendar add dinner with Mario Friday March 28th at 9pm
calendar delete dinner with Mario
calendar move doctor visit to April 6th at 11am
```
