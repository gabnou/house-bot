# Standard library imports
import sys
import os
import logging
import tempfile
import re as _re
from pathlib import Path

# Load environment variables
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

# Configure logging
_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    force=True,
)
logger = logging.getLogger(__name__)

# Third-party and local imports
from fastapi import FastAPI, UploadFile, File
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from contextlib import asynccontextmanager
from faster_whisper import WhisperModel
from services.shopping_db import init_db
from intent_parser import parse_intent, detect_category, validate_transcription, detect_language, translate_to_english, translate_from_english, classify_intent_category
from admin.router import router as admin_router

# List of partner JIDs from env (format: jid:name,jid:name or plain jid,jid)
PARTNER = [
    entry.split(":")[0].strip()
    for entry in os.getenv("PARTNER_LID", "").split(",")
    if entry.strip()
]

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
    # uvicorn calls logging.config.dictConfig() after importing main.py, which
    # resets the root logger level and overrides our basicConfig. Re-apply here,
    # after uvicorn's logging setup is complete.
    logging.getLogger().setLevel(_log_level)
    for _lgr_name, _lgr in logging.root.manager.loggerDict.items():
        if isinstance(_lgr, logging.Logger) and not _lgr_name.startswith(("uvicorn", "websockets", "watchfiles")):
            _lgr.setLevel(_log_level)
    logger.debug("🪵 Log level applied: %s", logging.getLevelName(_log_level))
    init_db()
    model_name = os.getenv("WHISPER_MODEL", "small")
    logger.info("🎤 Loading Whisper model '%s'...", model_name)
    _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
    logger.info("🎤 Whisper ready.")
    yield

# FastAPI app instance
app = FastAPI(lifespan=lifespan)

# Admin API router
app.include_router(admin_router)

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
            vad_filter=True,
            temperature=0,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        logger.info("🎤 Transcribed [%s, prob=%.2f]: %s", info.language, info.language_probability, text)
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
    # Try fast intent detection first — no language overhead for keyword messages
    intent = pre_route(text)
    effective_text = text
    detected_lang = None

    if intent:
        logger.debug("⚡ pre_route match: %s", intent)
    else:
        # Detect language before sending to LLM
        lang_info = detect_language(text)
        lang = lang_info.get("language", "").strip() if lang_info else ""
        confidence = lang_info.get("confidence", "low").strip().lower() if lang_info else "low"

        if lang and lang.lower() != "english" and confidence in ("high", "medium"):
            logger.info("🌐 Detected language: %s (%s confidence) — translating...", lang, confidence)
            translated = translate_to_english(text, lang)
            if translated:
                logger.info("🌐 Translated to English: %s", translated)
                detected_lang = lang
                effective_text = translated

        # Classify category if not directly detectable (handles non-keyword messages)
        if detect_category(effective_text) is None:
            classified = classify_intent_category(effective_text)
            if classified:
                logger.info("🏷️ Classified as '%s' — prepending keyword", classified)
                effective_text = f"{classified} {effective_text}"

        logger.debug("🤖 Sending to Ollama: '%s'", effective_text)
        intent = parse_intent(effective_text)

    action = intent.get("action", "unknown")
    t1 = time.time()
    logger.debug("⏱️ parse_intent: %.2fs", t1 - t0)
    reply = None
    notification = None

    from orchestrator import handle_intent as _orchestrator
    try:
        orchestrator_result = await _orchestrator(intent, effective_text, msg.sender)
    except Exception as e:
        logger.exception("Orchestrator error: %s", e)
        orchestrator_result = None

    if orchestrator_result:
        reply = orchestrator_result.get("reply")
        notification = orchestrator_result.get("notification")
    else:
        # Fallback for actions not handled by any skill (help, unknown, error)
        match action:
            case "help":
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
            case _:
                llm_reply = intent.get("reply", "I couldn't understand, please try again!")
                suggestion = ""
                if detect_category(effective_text) is None:
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

    t2 = time.time()
    logger.debug("⏱️ action '%s': %.2fs", action, t2 - t1)
    logger.debug("⏱️ total: %.2fs", t2 - t0)

    # Translate reply back if the original message was in a foreign language
    if detected_lang and reply:
        translated_reply = translate_from_english(reply, detected_lang)
        if translated_reply:
            reply = translated_reply

    return {"reply": reply, "notification": notification}

# Serve the SvelteKit production build (ui/build/) if it exists.
# MUST be mounted LAST — StaticFiles at "/" would intercept all routes
# registered after it, returning 405 for POST endpoints.
_UI_BUILD = Path(__file__).parent.parent / "ui" / "build"
if _UI_BUILD.exists():
    app.mount("/", StaticFiles(directory=str(_UI_BUILD), html=True), name="ui")
    logger.info("🖥️  Admin UI served from %s", _UI_BUILD)
