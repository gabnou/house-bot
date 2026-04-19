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
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from faster_whisper import WhisperModel
from services.shopping_db import init_db
from intent_parser import parse_intent, detect_category, validate_transcription, detect_language, translate_to_english, translate_from_english, classify_intent_category
from admin.router import router as admin_router

WHATSAPP_APPNAME = os.getenv("WHATSAPP_APPNAME", "HouseBot").strip()

# List of partner JIDs from env (format: jid:name,jid:name or plain jid,jid)
PARTNER = [
    entry.split(":")[0].strip()
    for entry in os.getenv("PARTNER_LID", "").split(",")
    if entry.strip()
]

# Regex patterns for identity and help — the only domain-independent intents
# safe to short-circuit without LLM. All domain-specific patterns (shopping,
# calendar, weather) are handled by parse_intent() to avoid cross-domain mismatches.
_PATTERN_IDENTITY = _re.compile(
    r'\b(who\s+are\s+you|what\s+are\s+you|what(?:\'s|\s+is)\s+your\s+name|introduce\s+yourself)\b',
    _re.IGNORECASE
)
_PATTERN_HELP = _re.compile(
    r'^(help|what\s+can\s+you\s+do|commands?|how\s+to\s+use(\s+you)?)$',
    _re.IGNORECASE
)

# Fast intent detection — only for domain-independent intents (identity, help).
# Returns None for everything else, delegating to parse_intent() via the LLM.
def pre_route(text: str) -> dict | None:
    t = text.strip().lower()
    if _PATTERN_IDENTITY.search(t):
        return {"action": "identity"}
    if _PATTERN_HELP.match(t):
        return {"action": "help"}
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
                # Re-run fast routing on the translated text — saves classify + parse_intent LLM calls
                # for simple messages like "aiuto" → "help", "chi sei?" → "who are you?"
                intent = pre_route(effective_text)
                if intent:
                    logger.debug("⚡ pre_route match (post-translation): %s", intent)

        if not intent:
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
            case "identity":
                reply = (
                    f"🤖 I'm *{WHATSAPP_APPNAME}*, your home assistant bot!\n\n"
                    "I can help you with:\n"
                    "🛒 Shopping list\n"
                    "🌤️ Weather forecasts\n"
                    "📅 Google Calendar\n\n"
                    "Send *help* to see all available commands."
                )
            case "help":
                reply = (
                    f"🤖 *{WHATSAPP_APPNAME} — What I can do*\n\n"
                    "🛒 *Shopping list*\n"
                    "  add milk and eggs\n"
                    "  add aspirin\n"
                    "  I bought milk\n"
                    "  remove bread\n"
                    "  what's missing?\n"
                    "  clear the list\n\n"
                    "🌤️ *Weather*\n"
                    "  weather in Barcelona\n"
                    "  weather now\n"
                    "  weather now in Milan\n"
                    "  forecast next 4 days\n"
                    "  forecast next hours\n"
                    "  forecast next 6 hours in New York\n"
                    "  forecast\n"
                    "  forecast London\n\n"
                    "📅 *Calendar*\n"
                    "  what do I have today?\n"
                    "  this week\n"
                    "  events in April\n"
                    "  events from the 5th to the 20th of April\n"
                    "  details dinner with John\n"
                    "  add dinner with John friday 28th at 9pm\n"
                    "  delete dinner with John\n"
                    "  move doctor visit from April 5th to April 6th at 11am\n\n"
                )
            case _:
                llm_reply = intent.get("reply", "I couldn't understand, please try again!")
                reply = (
                    "🤖 I didn't understand what you mean and I answer:\n"
                    f"{llm_reply}\n"
                    "🤖 I can help you with:\n"
                    "🛒 Shopping list\n"
                    "🌤️ Weather forecasts\n"
                    "📅 Google Calendar\n\n"    
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
    class _SPAStaticFiles(StaticFiles):
        """
        StaticFiles subclass that serves index.html for any path that does not
        match a real file — enabling SvelteKit client-side routing on direct
        navigation (e.g. /install, /admin).

        Static assets (/_app/*, *.js, *.css …) are served normally because
        they exist as real files in ui/build/.  Only unknown paths fall through
        to index.html, so API GET endpoints are never affected.
        """
        async def get_response(self, path: str, scope):
            try:
                return await super().get_response(path, scope)
            except StarletteHTTPException as exc:
                if exc.status_code == 404:
                    return await super().get_response("index.html", scope)
                raise

    app.mount("/", _SPAStaticFiles(directory=str(_UI_BUILD), html=True), name="ui")
    logger.info("🖥️  Admin UI served from %s", _UI_BUILD)
