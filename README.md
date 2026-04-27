# housebot

![housebot-logo](img/housebot_logo_v2_small.png)

Your home assistant on WhatsApp — manage a shared shopping list, keep your Google Calendar in sync and check the weather, all by sending messages. No cloud subscriptions, no monthly fees. Everything runs on your own Computer.

> **For developers and contributors:** see [DEVELOPMENT.md](DEVELOPMENT.md) for architecture details, project structure, tech stack, and how to extend the bot.

---

## What it does

- 🛒 **Shopping list** — add, remove, and view items by category (food, health, clothing, other). Changes are instantly notified to all household members.
- 🌤️ **Weather** — current conditions and multi-day forecasts, powered by Open-Meteo (free, no API key needed).
- 📅 **Google Calendar** — check, add, edit, and delete events by natural language. *(optional — requires a Google account)*
- 🎙️ **Voice messages** — send a voice note and the bot transcribes and processes it automatically.
- 🌍 **Any language** — write in Italian, Spanish, French, or any language. The bot detects it, processes your request, and replies in the same language.
- 🌅 **Morning briefing** — a daily message at 07:30 with weather, today's agenda, and a motivational quote.

---

## Requirements

- **A MacBook or Mac Mini** running macOS (everything else is installed automatically)
- **A WhatsApp number for the bot:**
  - *Shared household use* — a second SIM card (dedicated to the bot) so everyone can message it
  - *Personal use* — your own number works fine; just chat with yourself
- **RAM:** at least 8 GB (16 GB recommended for better AI models)
- **A Google account** — only if you want calendar management (this feature is optional)

---

## Installation

### 1 — Download the latest release

Go to the [Releases page](https://github.com/gabnou/house-bot/releases/latest), download the **`housebot-<version>.zip`** file (not "Source code"), and save it somewhere easy to find — for example your Desktop or Downloads folder.

Then open the **Terminal** app (press `⌘ Space`, type *Terminal*, press Enter) and run these commands — replacing the path with wherever you saved the zip:

```bash
cd ~/Downloads          # or wherever you saved the zip, e.g. cd ~/Desktop
unzip housebot-*.zip
cd housebot-*
```

### 2 — Run the installer

```bash
chmod 755 install.sh
./install.sh
```

The installer takes care of everything you need to run the bot: Homebrew, Python, Node.js, Ollama (Private AI models), dependencies, and starting the bot for the first time.

### 3 — Open the Control Panel and finish setup

When the installer finishes, open **[http://localhost:8000](http://localhost:8000)** in your browser and go to the **Configuration** page. Follow the sections in order:

| Section | What you do |
|---|---|
| **0. Bot display name** | Choose the name the bot will show on WhatsApp |
| **1. Private AI Configuration (Ollama models)** | Pick and download a local AI model. Lighter models (8B) work on 8 GB RAM; bigger ones (22B) need 16 GB+. |
| **2. WhatsApp Pairing** | Scan a QR code to link the bot's WhatsApp number |
| **3. Sender Restrictions** | Send a message from each household member's phone, then approve them here |
| **4. Location & Briefing** | Set your city for weather and choose the morning briefing language |
| **5. Speech recognition model** | Choose the voice transcription quality (small = fast, large = more accurate) |

That's it — the bot is ready. No config files to edit manually.

> **All sections are optional except WhatsApp Pairing.** Shopping list and Weather work out of the box without Google Calendar. You can skip any section and come back later.

---

## Updating

The easiest way is through the Control Panel at **[http://localhost:8000](http://localhost:8000)** → Admin → HouseBot Software Update. Click **⬆️ Update Now** — it downloads, applies, and restarts everything automatically.

---

## Commands

Send messages directly to the bot in a private WhatsApp chat. You don't need any special syntax — just write naturally.

> **Tip:** You can also personalise how the bot understands your household's language at **[http://localhost:8000](http://localhost:8000)** → Prompting.

### Shopping List

```
add milk and eggs
add ibuprofen
what's missing?
I bought apples
remove pasta
clear the list
```

### Weather

```
weather now
weather tomorrow
weather next 4 days
weather next 3 days in Madrid
weather next 6 hours in Lecce
```

### Calendar

```
what do I have today?
this week
events in April
add dinner with Mario Friday at 9pm
delete dinner with Mario
move doctor visit to April 6th at 11am
```

### Special commands

| Message | What happens |
|---|---|
| `help` | Shows all available commands |
| `who are you` | Bot introduces itself |

All commands work in any language.

---

## Managing the bot

Once running, use the **Control Panel** at **[http://localhost:8000](http://localhost:8000)** for everything:
- Start, stop, or restart services
- Switch or test AI models
- Monitor live status and logs
- Edit the morning briefing settings
- Manage household members

For command-line control:

```bash
./housebot.sh start      # start everything
./housebot.sh stop       # stop everything
./housebot.sh restart    # restart everything
./housebot.sh status     # check what's running
./housebot.sh logs       # view recent logs
./housebot.sh logs-live  # follow logs in real time
```

---

*Made for learning purposes, and fixing family headaches.*
