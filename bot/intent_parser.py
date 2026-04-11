import logging
import os
import requests
import json
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import time

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("OLLAMA_MODEL", "mistral-small:22b")


def detect_category(text: str) -> str | None:
    """Returns 'shopping', 'calendar', or 'weather' if text starts with that keyword, else None."""
    t = text.strip().lower()
    first_word = t.split()[0] if t.split() else ''
    if re.match(r'(shopping|grocery\s+list|groceries)\b', t) or SequenceMatcher(None, first_word, 'shopping').ratio() >= 0.82:
        return 'shopping'
    if re.match(r'calendar\b', t) or SequenceMatcher(None, first_word, 'calendar').ratio() >= 0.82:
        return 'calendar'
    if re.match(r'weather\b', t) or SequenceMatcher(None, first_word, 'weather').ratio() >= 0.82:
        return 'weather'
    return None


def get_system_prompt() -> str:
    return """You are a domestic assistant named "house-bot".
You will receive messages generally in English, but you might also receive them in other languages.
In any case you must interpret messages and respond ONLY in English with a valid JSON object.

Messages about shopping, weather, or calendar always start with the corresponding keyword "shopping", "weather", or "calendar" (or similar variants),
and are handled separately. Here you only handle generic messages that do not contain these keywords.

Available actions:
- help: the user asks what you can do or how to use you.
- unknown: any other message — respond relevantly in the "reply" field.

If the action is "unknown", add a "reply" field where you respond directly and relevantly, short and like a professional assistant would.
Try to understand if the request is related to shopping, weather, or calendar features, and if so suggest the user use the correct keyword.
If you really can't understand, respond relevantly and DO NOT respond with generic phrases.

Examples:
Message: "help"
Response: {"action": "help"}

Message: "what can you do?"
Response: {"action": "help"}

Message: "how are you?"
Response: {"action": "unknown", "reply": "I'm doing great, thanks! 😊"}

Message: "what's the capital of France?"
Response: {"action": "unknown", "reply": "The capital of France is Paris! 🗼"}

Respond ONLY with JSON, no additional text, no markdown, no explanations.

"""


def get_shopping_prompt() -> str:
    return """You are a shopping list assistant named "house-bot". Interpret the message and respond ONLY with a valid JSON object.

Available actions:
- add: adds items. {"action": "add", "items": [{"name": "...", "category": "..."}]}
- remove: removes items from the list. {"action": "remove"}
- bought: marks items as bought. {"action": "bought", "items": [{"name": "...", "category": "..."}]}
- show: shows the list. {"action": "show", "category": null|"food"|"other"|"clothing"|"health"}
- clear: clears the entire list. {"action": "clear"}

Valid categories: food, other, clothing, health.
Medicine, drugs, vitamins → health. Clothes, shoes, accessories → clothing.

Examples:
Message: "shopping add milk and eggs"
Response: {"action": "add", "items": [{"name": "milk", "category": "food"}, {"name": "eggs", "category": "food"}]}

Message: "shopping add aspirin and vitamin C"
Response: {"action": "add", "items": [{"name": "aspirin", "category": "health"}, {"name": "vitamin C", "category": "health"}]}

Message: "shopping add new shoes"
Response: {"action": "add", "items": [{"name": "new shoes", "category": "clothing"}]}

Message: "shopping show"
Response: {"action": "show", "category": null}

Message: "shopping list"
Response: {"action": "show", "category": null}

Message: "shopping what's on the list?"
Response: {"action": "show", "category": null}

Message: "shopping what's missing for food?"
Response: {"action": "show", "category": "food"}

Message: "shopping remove the bread"
Response: {"action": "remove"}

Message: "shopping I bought milk and bread"
Response: {"action": "bought", "items": [{"name": "milk", "category": "food"}, {"name": "bread", "category": "food"}]}

Message: "shopping bought milk and bread"
Response: {"action": "bought", "items": [{"name": "milk", "category": "food"}, {"name": "bread", "category": "food"}]}

Message: "shopping clear"
Response: {"action": "clear"}

Respond ONLY with JSON, no additional text, no markdown, no explanations."""


def get_calendar_prompt() -> str:
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%A").lower()
    current_year = now.year
    next_year = current_year + 1

    # This week: current Monday → current Sunday
    this_monday = now - timedelta(days=now.weekday())
    this_sunday = this_monday + timedelta(days=6)
    this_mon_str = this_monday.strftime("%Y-%m-%d")
    this_sun_str = this_sunday.strftime("%Y-%m-%d")

    # Next week: next Monday → next Sunday
    days_to_next_monday = (7 - now.weekday()) % 7 or 7
    next_monday = now + timedelta(days=days_to_next_monday)
    next_sunday = next_monday + timedelta(days=6)
    next_mon_str = next_monday.strftime("%Y-%m-%d")
    next_sun_str = next_sunday.strftime("%Y-%m-%d")
    two_weeks_sun_str = (next_monday + timedelta(days=13)).strftime("%Y-%m-%d")
    three_weeks_sun_str = (next_monday + timedelta(days=20)).strftime("%Y-%m-%d")

    return f"""You are a calendar assistant. Interpret the message and respond ONLY with a valid JSON object.

Today's date: {today} ({weekday}). Current year: {current_year}.
For dates without a year use {current_year}. If the date has already passed this year, use {next_year}.

Available actions:
- calendar_show: for relative queries — today, tomorrow, day after tomorrow, next N days. ALWAYS use this for relative queries without fixed dates.
  {{"action": "calendar_show", "days": N, "offset_days": 0|1|2}}
- calendar_period: for week, month, fixed date range, or specific date (use start_date = end_date).
  {{"action": "calendar_period", "start_date": "YYYY-MM-DD", "end_date": "YYYY-MM-DD"}}
- calendar_add: {{"action": "calendar_add", "title": "...", "date": "YYYY-MM-DD", "start_time": "HH:MM", "end_time": null, "location": null}}
- calendar_delete: {{"action": "calendar_delete", "title": "..."}}
- calendar_edit: {{"action": "calendar_edit", "title": "...", "new_title": null, "new_date": null, "new_time": null, "new_location": null}}
- calendar_details: {{"action": "calendar_details", "title": "..."}}

IMPORTANT: Words like "appointment", "event", "reminder", "meeting" are generic and are NOT part of the title. The title is the specific event name (e.g. "concert of Pixies", "dinner with Mark", "doctor visit").

Examples:
Message: "calendar"
Response: {{"action": "calendar_show", "days": 1, "offset_days": 0}}

Message: "calendar events"
Response: {{"action": "calendar_show", "days": 1, "offset_days": 0}}

Message: "calendar today"
Response: {{"action": "calendar_show", "days": 1, "offset_days": 0}}

Message: "calendar tomorrow"
Response: {{"action": "calendar_show", "days": 1, "offset_days": 1}}

Message: "calendar day after tomorrow"
Response: {{"action": "calendar_show", "days": 1, "offset_days": 2}}

Message: "calendar next 3 days"
Response: {{"action": "calendar_show", "days": 3, "offset_days": 0}}

Message: "calendar next 10 days"
Response: {{"action": "calendar_show", "days": 10, "offset_days": 0}}

Message: "calendar this week"
Response: {{"action": "calendar_period", "start_date": "{this_mon_str}", "end_date": "{this_sun_str}"}}

Message: "calendar show appointments this week"
Response: {{"action": "calendar_period", "start_date": "{this_mon_str}", "end_date": "{this_sun_str}"}}

Message: "calendar next week"
Response: {{"action": "calendar_period", "start_date": "{next_mon_str}", "end_date": "{next_sun_str}"}}

Message: "calendar next two weeks"
Response: {{"action": "calendar_period", "start_date": "{next_mon_str}", "end_date": "{two_weeks_sun_str}"}}

Message: "calendar next three weeks"
Response: {{"action": "calendar_period", "start_date": "{next_mon_str}", "end_date": "{three_weeks_sun_str}"}}

Message: "calendar april"
Response: {{"action": "calendar_period", "start_date": "{current_year}-04-01", "end_date": "{current_year}-04-30"}}

Message: "calendar events in april"
Response: {{"action": "calendar_period", "start_date": "{current_year}-04-01", "end_date": "{current_year}-04-30"}}

Message: "calendar may"
Response: {{"action": "calendar_period", "start_date": "{current_year}-05-01", "end_date": "{current_year}-05-31"}}

Message: "calendar from the 5th to the 20th of april"
Response: {{"action": "calendar_period", "start_date": "{current_year}-04-05", "end_date": "{current_year}-04-20"}}

Message: "calendar april 9th"
Response: {{"action": "calendar_period", "start_date": "{current_year}-04-09", "end_date": "{current_year}-04-09"}}

Message: "calendar what do I have on march 15th"
Response: {{"action": "calendar_period", "start_date": "{current_year}-03-15", "end_date": "{current_year}-03-15"}}

Message: "calendar add dinner with Mark friday april 3rd at 9pm"
Response: {{"action": "calendar_add", "title": "dinner with Mark", "date": "{current_year}-04-03", "start_time": "21:00", "end_time": null, "location": null}}

Message: "calendar delete dinner with Mark"
Response: {{"action": "calendar_delete", "title": "dinner with Mark"}}

Message: "calendar move doctor visit to april 6th at 11am"
Response: {{"action": "calendar_edit", "title": "doctor visit", "new_title": null, "new_date": "{current_year}-04-06", "new_time": "11:00", "new_location": null}}

Message: "calendar move appointment Rossella from april 2nd to april 9th"
Response: {{"action": "calendar_edit", "title": "Rossella", "new_title": null, "new_date": "{current_year}-04-09", "new_time": null, "new_location": null}}

Message: "calendar details dinner with Mark"
Response: {{"action": "calendar_details", "title": "dinner with Mark"}}

Respond ONLY with JSON, no additional text, no markdown, no explanations."""


def get_weather_prompt() -> str:
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    today_weekday = now.strftime("%A").lower()

    # Build next-occurrence table
    weekday_seen: dict[str, datetime] = {}
    for i in range(7):
        d = now + timedelta(days=i)
        name = d.strftime("%A")
        if name not in weekday_seen:
            weekday_seen[name] = d

    ordered_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    table_lines = []
    for day in ordered_days:
        if day in weekday_seen:
            d = weekday_seen[day]
            note = " (today)" if d.date() == now.date() else ""
            table_lines.append(f'  "{day.lower()}" → "{d.strftime("%Y-%m-%d")}" ({day} {d.day}{note})')
    table_str = "\n".join(table_lines)

    ex_a = now + timedelta(days=2)
    ex_a_str = ex_a.strftime("%Y-%m-%d")
    ex_a_label = ex_a.strftime("%B %d").lstrip("0")

    ex_b = weekday_seen.get("Sunday", now + timedelta(days=6))
    ex_b_str = ex_b.strftime("%Y-%m-%d")
    ex_b_day = ex_b.strftime("%A")

    return f"""You are a weather assistant. Interpret the message and respond ONLY with a valid JSON object.

Today's date: {today_str} ({today_weekday}).

Available actions:
- weather_now: current weather conditions. {{"action": "weather_now", "city": null|"name"}}
- weather_forecast: forecast for multiple days or for today/tomorrow generically.
  {{"action": "weather_forecast", "city": null|"name", "days": N, "offset_days": 0|1}}
  offset_days=0: from today. offset_days=1: from tomorrow.
- weather_hours: next N hours from now. {{"action": "weather_hours", "city": null|"name", "hours": N}}
- weather_date: DAILY forecast for a specific day (date or weekday name).
  {{"action": "weather_date", "city": null|"name", "date": "YYYY-MM-DD"}}
  ALWAYS use this action when the message specifies a weekday or a precise date and does NOT ask for hourly forecasts.
- weather_hours_date: HOURLY forecast for a specific day.
  {{"action": "weather_hours_date", "city": null|"name", "date": "YYYY-MM-DD"}}
  ALWAYS use this action when hourly weather is requested for a specific day other than "now"/"next hours".
  Available only for the next 3 days. Use the table below for weekday names.

Upcoming days table (use this to translate weekday → date):
{table_str}

If city is not specified use null. Default days=3, default hours=12 (max 24).

Examples:
Message: "weather"
Response: {{"action": "weather_forecast", "city": null, "days": 3, "offset_days": 0}}

Message: "weather forecast"
Response: {{"action": "weather_forecast", "city": null, "days": 3, "offset_days": 0}}

Message: "weather today"
Response: {{"action": "weather_forecast", "city": null, "days": 1, "offset_days": 0}}

Message: "weather tomorrow"
Response: {{"action": "weather_forecast", "city": null, "days": 1, "offset_days": 1}}

Message: "weather right now"
Response: {{"action": "weather_now", "city": null}}

Message: "weather now"
Response: {{"action": "weather_now", "city": null}}

Message: "weather now in Milan"
Response: {{"action": "weather_now", "city": "Milan"}}

Message: "weather Barcelona"
Response: {{"action": "weather_forecast", "city": "Barcelona", "days": 3, "offset_days": 0}}

Message: "weather next 4 days"
Response: {{"action": "weather_forecast", "city": null, "days": 4, "offset_days": 0}}

Message: "weather next 3 days in Madrid"
Response: {{"action": "weather_forecast", "city": "Madrid", "days": 3, "offset_days": 0}}

Message: "weather next hours"
Response: {{"action": "weather_hours", "city": null, "hours": 12}}

Message: "weather next 6 hours in Ripoll"
Response: {{"action": "weather_hours", "city": "Ripoll", "hours": 6}}

Message: "weather hourly forecast tomorrow"
Response: {{"action": "weather_hours_date", "city": null, "date": "{(now + timedelta(days=1)).strftime('%Y-%m-%d')}"}}

Message: "weather hourly day after tomorrow"
Response: {{"action": "weather_hours_date", "city": null, "date": "{(now + timedelta(days=2)).strftime('%Y-%m-%d')}"}}

Message: "weather hourly {ex_b_day.lower()}"
Response: {{"action": "weather_hours_date", "city": null, "date": "{ex_b_str}"}}

Message: "weather {ex_b_day.lower()} in Ripoll"
Response: {{"action": "weather_date", "city": "Ripoll", "date": "{ex_b_str}"}}

Message: "weather forecast {ex_b_day.lower()}"
Response: {{"action": "weather_date", "city": null, "date": "{ex_b_str}"}}

Message: "weather {ex_a_label}"
Response: {{"action": "weather_date", "city": null, "date": "{ex_a_str}"}}

Respond ONLY with JSON, no additional text, no markdown, no explanations."""


def _parse_raw(raw: str) -> dict:
    raw_normalized = raw.replace('{{', '{').replace('}}', '}')
    match = re.search(r'\{.*\}', raw_normalized, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {raw}")
    return json.loads(match.group())


def validate_transcription(text: str) -> bool:
    """Ask the LLM if a Whisper transcription is coherent speech.
    Returns True (valid) on any doubt or error, so we never silently drop real messages."""
    prompt = (
        f"The following text was automatically transcribed from a voice message.\n"
        f"Respond ONLY with \"yes\" if the text is understandable and makes sense as spoken language, "
        f"or \"no\" if it is incomprehensible, pure garbage, transcribed noise, or makes no sense.\n\n"
        f"Text: \"{text}\"\nResponse:"
    )
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 5},
        }, timeout=15)
        answer = response.json().get("response", "").strip().lower()
        logger.debug("🎤 validate_transcription → '%s' for: %s", answer, text)
        return not answer.startswith("no")
    except Exception as e:
        logger.warning("⚠️ validate_transcription fallback (fail-open): %s", e)
        return True


def parse_intent(text: str) -> dict:
    category = detect_category(text)
    if category == 'shopping':
        prompt_text = f"{get_shopping_prompt()}\n\nMessage: \"{text}\"\nResponse:"
    elif category == 'calendar':
        prompt_text = f"{get_calendar_prompt()}\n\nMessage: \"{text}\"\nResponse:"
    elif category == 'weather':
        prompt_text = f"{get_weather_prompt()}\n\nMessage: \"{text}\"\nResponse:"
    else:
        prompt_text = f"{get_system_prompt()}\n\nMessage: \"{text}\"\nResponse:"

    payload = {
        "model": MODEL,
        "prompt": prompt_text,
        "stream": False,
        "options": {"temperature": 0.1}
    }

    try:
        t1 = time.time()
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        t2 = time.time()
        logger.debug("⏱️ Ollama HTTP call: %.2fs", t2 - t1)
        response.raise_for_status()
        raw = response.json()["response"].strip()
        logger.debug("🧠 Ollama raw response: %s", raw)
        return _parse_raw(raw)
    except Exception as e:
        logger.error("Error in parse_intent: %s", e)
        return {"action": "error"}
