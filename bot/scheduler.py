import sys
import logging
import os
from pathlib import Path

import fcntl
import time
import requests
from datetime import datetime, date
from services.weather import get_morning_briefing
from intent_parser import MODEL, OLLAMA_URL, translate_from_english
from services.calendar_handler import show_events

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / '.env')

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

FASTAPI_URL = "http://localhost:8000"
_briefing_time = os.getenv("BRIEFING_TIME", "07:30").strip()
try:
    _bt_parts = _briefing_time.split(":")
    BRIEFING_HOUR = int(_bt_parts[0])
    BRIEFING_MINUTE = int(_bt_parts[1])
except (ValueError, IndexError):
    BRIEFING_HOUR = 7
    BRIEFING_MINUTE = 30
WINDOW_WAKEUP = 30  # send if within 30min of target time
BRIEFING_LANGUAGE = os.getenv("BRIEFING_LANGUAGE", "").strip() or None

BRIEFING_LOCK_FILE = Path(__file__).parent.parent / "logs" / "briefing_sent.lock"


def _briefing_already_sent_today() -> bool:
    """Returns True if a briefing lock file exists for today's date."""
    if BRIEFING_LOCK_FILE.exists():
        try:
            saved = date.fromisoformat(BRIEFING_LOCK_FILE.read_text().strip())
            return saved == date.today()
        except ValueError:
            pass
    return False


def _mark_briefing_sent():
    """Writes today's date to the lock file."""
    BRIEFING_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    BRIEFING_LOCK_FILE.write_text(date.today().isoformat())


def _try_claim_briefing() -> bool:
    """Atomically claim the right to send today's briefing.
    Returns True only if THIS process successfully claims it.
    Uses flock to prevent race conditions between multiple scheduler instances."""
    BRIEFING_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    lock_path = str(BRIEFING_LOCK_FILE) + ".lock"
    try:
        fd = open(lock_path, 'w')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if _briefing_already_sent_today():
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()
            return False
        _mark_briefing_sent()
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
        return True
    except BlockingIOError:
        return False
    except Exception as e:
        logger.error("⚠️ Briefing lock error: %s", e)
        return False


def generate_morning_quote() -> str:
    payload = {
        "model": MODEL,
        "prompt": (
            "You are a cultured and direct assistant. Generate ONE single short quote or phrase to start the day. "
            "Choose from poets, Buddhist or Zen thinkers, and great sports figures, but avoid existentialists. "
            "The phrase must be authentic, direct, not cheesy or preachy. "
            "Avoid obvious or overused quotes. Prefer something that motivates and energizes a person to face the day. "
            "The quote should help the person overcome daily difficulties. "
            "Format: just the quote with the author after a dash, nothing else.\n"
            "Example: «The miracle isn't that I finished. The miracle is that I had the courage to start.» — John Bingham"
        ),
        "stream": False,
        "options": {"temperature": 0.9}
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=60)
        response.raise_for_status()
        return response.json()["response"].strip()
    except Exception as e:
        logger.error("⚠️ Quote generation error: %s", e)
        return "«Dum differtur vita transcurrit.» — Seneca"


def send_briefing():
    logger.info("🌤️ Fetching weather...")
    weather = get_morning_briefing()
    logger.info("🌤️ Weather: %s", weather[:50] if weather else 'EMPTY')

    logger.info("📅 Fetching calendar...")
    calendar = show_events(days=1)
    logger.info("📅 Calendar: %s", calendar[:50] if calendar else 'EMPTY')

    logger.info("💭 Generating quote...")
    quote = generate_morning_quote()
    logger.info("💭 Quote: %s", quote[:50] if quote else 'EMPTY')

    text = f"{weather}\n\n{calendar}\n\n💭 {quote}"

    if BRIEFING_LANGUAGE:
        logger.info("🌐 Translating briefing to %s...", BRIEFING_LANGUAGE)
        translated = translate_from_english(text, BRIEFING_LANGUAGE)
        if translated:
            text = translated
        else:
            logger.warning("⚠️ Briefing translation to %s failed, sending in English", BRIEFING_LANGUAGE)

    logger.info("📤 Total text: %d characters", len(text))

    try:
        requests.post(f"{FASTAPI_URL}/broadcast", json={"text": text}, timeout=10)
        logger.info("✅ Briefing sent at %s", datetime.now().strftime('%H:%M'))
    except Exception as e:
        logger.error("❌ Briefing send error: %s", e)


def run():
    """
    Main scheduler loop. Checks every 30 seconds whether it's time to send
    the morning briefing (BRIEFING_HOUR:BRIEFING_MINUTE).

    Uses a tolerance window (WINDOW_WAKEUP) so that a late restart or a
    missed tick still triggers the briefing, as long as the scheduler comes
    back within the window. A date guard prevents re-sending more than once
    per day regardless of how many ticks fall inside the window.
    """
    logger.info(
        "⏰ Scheduler started — morning briefing at %02d:%02d (window %d min)",
        BRIEFING_HOUR, BRIEFING_MINUTE, WINDOW_WAKEUP,
    )

    while True:
        now = datetime.now()
        target = now.replace(hour=BRIEFING_HOUR, minute=BRIEFING_MINUTE, second=0, microsecond=0)
        minutes_from_target = (now - target).total_seconds() / 60

        if 0 <= minutes_from_target < WINDOW_WAKEUP and _try_claim_briefing():
            logger.info("📤 Sending morning briefing...")
            send_briefing()

        time.sleep(30)


if __name__ == "__main__":
    run()
