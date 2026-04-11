# Standard library imports
import sys
import os
import logging
import tempfile
import re as _re
from pathlib import Path
from difflib import SequenceMatcher
sys.path.append(str(Path(__file__).parent))  # Add bot/ to sys.path

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Configure logging
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

# Third-party and local imports
from fastapi import FastAPI, UploadFile, File
from pydantic import BaseModel
from contextlib import asynccontextmanager
from faster_whisper import WhisperModel
from db_handler import (
    init_db, add_item, remove_item,
    mark_bought, add_and_mark_bought,
    show_list, clear_list,
    recent_bought, get_pending_items
)
from intent_parser import parse_intent, detect_category, validate_transcription
from weather import get_weather_now, get_weather_forecast, get_weather_hours, get_weather_hours_day
from calendar_handler import (
    show_events, add_event,
    delete_event, edit_event,
    event_details, show_events_period
)

# List of partner JIDs from env
PARTNER = [
    jid.strip()
    for jid in os.getenv("PARTNER_LID", "").split(",")
    if jid.strip()
]

# Actions that modify the list
MODIFYING_ACTIONS = {"add", "remove", "bought", "clear"}

# Fuzzy match threshold
FUZZY_THRESHOLD = 0.82

# Find pending items in text using substring or fuzzy match
def match_items_in_text(text: str, pending_items: list) -> list:
    text_lower = text.lower()
    words = text_lower.split()
    matched = []
    for item in pending_items:
        item_lower = item.lower()
        # Exact match
        if item_lower in text_lower:
            matched.append(item)
            continue
        # Fuzzy match
        item_words = item_lower.split()
        n = len(item_words)
        for i in range(len(words) - n + 1):
            window = " ".join(words[i:i + n])
            if SequenceMatcher(None, item_lower, window).ratio() >= FUZZY_THRESHOLD:
                matched.append(item)
                break
    return matched

# Regex patterns for intent detection
_PATTERN_SHOW_LIST = _re.compile(
    r'\b(show(?!\s+(calendar|events|weather))|list|grocery\s+list|shopping\s+list|what\'s\s+missing|groceries)\b',
    _re.IGNORECASE
)
_PATTERN_BOUGHT = _re.compile(
    r'\b(i\s+(bought|got|picked\s+up)|bought|got|purchased)\b',
    _re.IGNORECASE
)
_PATTERN_REMOVE = _re.compile(
    r'\b(remove|delete|drop|take\s+off|cross\s+off)\b',
    _re.IGNORECASE
)
_PATTERN_ADD = _re.compile(
    r'^\s*add\b',
    _re.IGNORECASE
)
_PATTERN_CALENDAR_TODAY = _re.compile(
    r'^(show\s+(calendar|events)|calendar|agenda|appointments|events(\s+today)?|today|what\s+do\s+i\s+have\s+today)$',
    _re.IGNORECASE
)

# Fast intent detection for simple messages
def pre_route(text: str) -> dict | None:
    t = text.strip().lower()
    if _PATTERN_BOUGHT.search(t):
        return {"action": "bought"}
    if _PATTERN_REMOVE.search(t):
        return {"action": "remove"}
    if _PATTERN_CALENDAR_TODAY.match(t):
        return {"action": "calendar_show", "days": 1, "offset_days": 0}
    if detect_category(text) is not None:
        return None
    if _PATTERN_ADD.search(t):
        return {"action": "add"}
    if _PATTERN_SHOW_LIST.search(t):
        return {"action": "show", "category": None}
    return None

# Global Whisper model instance
_whisper_model: WhisperModel | None = None

# FastAPI lifespan event: init DB and load model
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _whisper_model
    init_db()
    model_name = os.getenv("WHISPER_MODEL", "small")
    logger.info("🎤 Loading Whisper model '%s'...", model_name)
    _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
    logger.info("🎤 Whisper ready.")
    yield

# FastAPI app instance
app = FastAPI(lifespan=lifespan)

# Request models
class Message(BaseModel):
    sender: str
    text: str

class Broadcast(BaseModel):
    text: str

# Audio transcription endpoint
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    tmp_path = None
    try:
        suffix = Path(file.filename).suffix if file.filename else ".ogg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = tmp.name
            tmp.write(await file.read())
        segments, info = _whisper_model.transcribe(
            tmp_path,
            beam_size=5,
            language="en",
            vad_filter=True,
            temperature=0,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info("🎤 Transcribed [%s]: %s", info.language, text)
        valid = validate_transcription(text) if text else False
        if not valid:
            logger.info("🎤 Invalid transcription, discarded: '%s'", text)
        return {"text": text, "language": info.language, "valid": valid}
    except Exception as e:
        logger.error("❌ Transcription error: %s", e)
        return {"text": "", "error": str(e)}
    finally:
        if tmp_path and Path(tmp_path).exists():
            Path(tmp_path).unlink()

# Broadcast message to all partners
@app.post("/broadcast")
async def broadcast(msg: Broadcast):
    import requests as req
    for number in PARTNER:
        try:
            req.post("http://localhost:3001/send", json={
                "jid": number,
                "text": msg.text
            }, timeout=5)
        except Exception as e:
            logger.error("Broadcast error to %s: %s", number, e)
    return {"ok": True}

# Main message handler endpoint
@app.post("/message")
async def handle_message(msg: Message):
    import time
    t0 = time.time()
    logger.info("📩 From %s: %s", msg.sender, msg.text)
    text = msg.text.strip()
    if not text:
        return {"reply": None, "notification": None}
    logger.debug("🔍 Received text: '%s'", text)
    # Try fast intent detection, else use LLM
    intent = pre_route(text)
    if intent:
        logger.debug("⚡ pre_route match: %s", intent)
    else:
        logger.debug("🤖 Sending to Ollama: '%s'", text)
        intent = parse_intent(text)
    action = intent.get("action", "unknown")
    t1 = time.time()
    logger.debug("⏱️ parse_intent: %.2fs", t1 - t0)
    reply = None
    notification = None

    if action == "add":
        items = intent.get("items")
        if not items:
            llm_intent = parse_intent("shopping " + text)
            items = llm_intent.get("items") or []
        responses = []
        for item in items:
            responses.append(add_item(item["name"], item.get("category", "other")))
        result = "\n".join(responses)
        updated_list = show_list()
        recent = recent_bought()
        reply = f"{result}\n\n{updated_list}\n\n{recent}" if recent else f"{result}\n\n{updated_list}"

    elif action == "remove":
        pending = get_pending_items()
        matched = match_items_in_text(text, pending)
        if not matched:
            reply = "⚠️ No items from the list found in the message."
        else:
            responses = [remove_item(name) for name in matched]
            result = "\n".join(responses)
            updated_list = show_list()
            recent = recent_bought()
            reply = f"{result}\n\n{updated_list}\n\n{recent}" if recent else f"{result}\n\n{updated_list}"

    elif action == "bought":
        # If pre_route fired there are no items — call LLM just for name extraction
        items_llm = intent.get("items")
        if items_llm is None:
            llm_intent = parse_intent(text)
            llm_intent["action"] = "bought"
            items_llm = llm_intent.get("items") or []
        pending = get_pending_items()
        responses = []
        if items_llm:
            for item in items_llm:
                name_llm = item["name"]
                category = item.get("category", "other")
                matched = match_items_in_text(name_llm, pending)
                if matched:
                    responses.append(mark_bought(matched[0]))
                else:
                    responses.append(add_and_mark_bought(name_llm, category))
        else:
            # Fallback 1: fuzzy match whole message text against pending
            matched = match_items_in_text(text, pending)
            if matched:
                responses = [mark_bought(name) for name in matched]
            else:
                # Fallback 2: strip trigger words and treat remainder as item name
                stripped = _re.sub(
                    r'^\s*(i\s+)?(bought|got|picked\s+up|purchased)\s*',
                    '', text, flags=_re.IGNORECASE
                ).strip()
                if stripped:
                    responses.append(add_and_mark_bought(stripped))
                else:
                    reply = "⚠️ No items found in the message."
        if responses:
            result = "\n".join(responses)
            updated_list = show_list()
            recent = recent_bought()
            reply = f"{result}\n\n{updated_list}\n\n{recent}" if recent else f"{result}\n\n{updated_list}"

    elif action == "show":
        updated_list = show_list(intent.get("category"))
        recent = recent_bought()
        reply = f"{updated_list}\n\n{recent}" if recent else updated_list

    elif action == "clear":
        reply = clear_list()

    elif action == "weather_date":
        from datetime import datetime as _dt
        date_str = intent.get("date", "")
        try:
            target = _dt.strptime(date_str, "%Y-%m-%d").date()
            today = _dt.now().date()
            offset = (target - today).days
            if offset < 0:
                reply = "⚠️ The requested date has already passed."
            elif offset > 6:
                reply = "⚠️ I can only show forecasts for the next 7 days."
            else:
                reply = get_weather_forecast(city=intent.get("city"), days=1, offset_days=offset)
        except Exception:
            reply = "⚠️ Invalid date in the message."

    elif action == "weather_hours_date":
        reply = get_weather_hours_day(
            target_date=intent.get("date", ""),
            city=intent.get("city")
        )

    elif action == "weather_now":
        reply = get_weather_now(intent.get("city"))

    elif action == "weather_hours":
        reply = get_weather_hours(
            hours=intent.get("hours", 12),
            city=intent.get("city")
        )

    elif action == "weather_forecast":
        reply = get_weather_forecast(
            city=intent.get("city"),
            days=intent.get("days", 3),
            offset_days=intent.get("offset_days", 0)
        )

    elif action == "calendar_show":
        reply = show_events(
            days=intent.get("days", 1),
            offset_days=intent.get("offset_days", 0)
        )

    elif action == "calendar_period":
        reply = show_events_period(
            start_date=intent.get("start_date"),
            end_date=intent.get("end_date")
        )

    elif action == "calendar_add":
        reply = add_event(
            title=intent.get("title", "New event"),
            date=intent.get("date"),
            start_time=intent.get("start_time"),
            end_time=intent.get("end_time"),
            location=intent.get("location")
        )

    elif action == "calendar_delete":
        reply = delete_event(
            title=intent.get("title"),
            date=intent.get("date")
        )

    elif action == "calendar_edit":
        reply = edit_event(
            title=intent.get("title"),
            new_title=intent.get("new_title"),
            new_date=intent.get("new_date"),
            new_time=intent.get("new_time"),
            new_location=intent.get("new_location")
        )

    elif action == "calendar_details":
        reply = event_details(intent.get("title"))

    elif action == "help":
        reply = (
            "🤖 *House-Bot — What I can do*\n\n"
            "🛒 *Shopping list*\n"
            "  shopping add milk and eggs\n"
            "  shopping add aspirin\n"
            "  shopping I bought milk\n"
            "  shopping remove bread\n"
            "  shopping what's missing?\n"
            "  shopping clear the list\n\n"
            "🌤️ *Weather*\n"
            "  weather <city> (default: Barcelona)\n"
            "  weather now\n"
            "  weather now in Milan\n"
            "  weather next 4 days\n"
            "  weather next hours\n"
            "  weather next 6 hours in Ripoll\n"
            "  weather forecast\n"
            "  weather forecast London\n\n"
            "📅 *Calendar*\n"
            "  calendar what do I have today?\n"
            "  calendar this week\n"
            "  calendar events in april\n"
            "  calendar from the 5th to the 20th of april\n"
            "  calendar details dinner with Gael\n"
            "  calendar add dinner with Gael friday 28th at 9pm\n"
            "  calendar delete dinner with Gael\n"
            "  calendar move doctor visit to april 6th at 11am\n\n"
        )

    elif action == "unknown":
        llm_reply = intent.get("reply", "I couldn't understand, please try again!")
        suggestion = ""
        if detect_category(text) is None:
            suggestion = (
                "💡 *Tip:* start your message with a keyword:\n"
                "• *shopping* show list\n"
                "• *weather* forecast tomorrow\n"
                "• *calendar* events this week\n"
            )
        reply = (
            "🤖 I'm not sure which of the 3 things I can do you mean. 😊\n"
            f"{suggestion}"
            "\n🤖 Here's my best answer:\n"
            f"{llm_reply}"
        )

    else:
        reply = (
            "⚠️ I couldn't understand the request.\n\n"
            "💡 *Tip:* start your message with a keyword:\n"
            "• *shopping* show list\n"
            "• *weather* forecast tomorrow\n"
            "• *calendar* events this week\n"
        )

    t2 = time.time()
    logger.debug("⏱️ action '%s': %.2fs", action, t2 - t1)
    logger.debug("⏱️ total: %.2fs", t2 - t0)

    if action in MODIFYING_ACTIONS:
        updated_list = show_list()
        notification = f"📋 List updated by a partner:\n\n{updated_list}"

    return {"reply": reply, "notification": notification}
