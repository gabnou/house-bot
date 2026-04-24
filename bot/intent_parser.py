import logging
import math
import os
import threading
import requests
import json
import re
from difflib import SequenceMatcher
import time

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
MODEL = os.getenv("OLLAMA_MODEL", "mistral-small:22b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text:latest")
_OLLAMA_BASE = OLLAMA_URL.rsplit("/api/", 1)[0]
EMBED_URL = f"{_OLLAMA_BASE}/api/embeddings"

# Anchor phrases per category — used to build mean embedding vectors for cosine-similarity classification
_CATEGORY_ANCHORS: dict[str, list[str]] = {
    "shopping": [
        "add to the shopping list",
        "remove item from grocery list",
        "we need to buy milk",
        "out of bread, eggs, butter",
        "add bananas to the list",
        "what do we need to buy",
        "supermarket provisions and supplies",
    ],
    "weather": [
        "what is the weather forecast",
        "will it rain today",
        "temperature tomorrow",
        "how is the weather outside",
        "forecast for the next days",
        "is it going to be sunny",
        "wind and humidity conditions",
    ],
    "calendar": [
        "add event to calendar",
        "what do I have scheduled today",
        "create an appointment",
        "what is on my agenda this week",
        "set a reminder for tomorrow",
        "schedule a meeting",
        "upcoming events and appointments",
    ],
}

_anchor_cache: dict[str, list[float]] | None = None
_anchor_lock = threading.Lock()


def _get_embedding(text: str) -> list[float] | None:
    """Return the embedding vector for *text* using the embed model."""
    keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "5m")
    try:
        resp = requests.post(EMBED_URL, json={
            "model": EMBED_MODEL,
            "prompt": text,
            "keep_alive": keep_alive,
        }, timeout=15)
        return resp.json().get("embedding")
    except Exception as e:
        logger.warning("⚠️ _get_embedding error: %s", e)
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _mean_vec(vecs: list[list[float]]) -> list[float]:
    n, dim = len(vecs), len(vecs[0])
    return [sum(v[i] for v in vecs) / n for i in range(dim)]


def preload_embed_anchors() -> None:
    """Pre-compute mean anchor embeddings for each category and warm up the embed model.
    Safe to call from a background thread; idempotent (skips if already cached)."""
    global _anchor_cache
    with _anchor_lock:
        if _anchor_cache is not None:
            return
        cache: dict[str, list[float]] = {}
        for category, phrases in _CATEGORY_ANCHORS.items():
            vecs = [v for p in phrases if (v := _get_embedding(p)) is not None]
            if vecs:
                cache[category] = _mean_vec(vecs)
                logger.debug("🧬 Anchor cached for '%s' (%d/%d phrases)", category, len(vecs), len(phrases))
            else:
                logger.warning("⚠️ No anchor embeddings computed for '%s'", category)
        _anchor_cache = cache
    logger.info("🧬 Embedding anchors ready (%d categories).", len(cache))


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


def _classify_by_embedding(text: str) -> str | None:
    """Classify category via cosine similarity against anchor embeddings.
    Returns the best-match category if similarity >= 0.50, else None."""
    global _anchor_cache
    if _anchor_cache is None:
        preload_embed_anchors()
    if not _anchor_cache:
        return None
    vec = _get_embedding(text)
    if vec is None:
        return None
    scores = {cat: _cosine_similarity(vec, anchor) for cat, anchor in _anchor_cache.items()}
    best = max(scores, key=scores.__getitem__)
    best_score = scores[best]
    logger.debug("🧬 embed scores: %s → best=%s (%.3f)", scores, best, best_score)
    return best if best_score >= 0.50 else None


def classify_intent_category(text: str) -> str | None:
    """Classify translated text into shopping, calendar, weather or none.
    First attempts fast embedding-based cosine similarity; falls back to LLM
    only when the embedding model is unavailable or confidence is below threshold.
    This is the fallback for when detect_category() finds no keyword match."""
    # Fast path: embedding cosine similarity
    embed_result = _classify_by_embedding(text)
    if embed_result:
        logger.debug("🧬 classify_intent_category (embed) → '%s' for: %s", embed_result, text)
        return embed_result

    # Fallback: LLM classification
    logger.debug("🏷️ classify_intent_category falling back to LLM for: %s", text)
    prompt = (
        "Classify the following message into one of these categories: shopping, weather, calendar.\n"
        "The message may be a translation from another language and may not start with the exact keyword, "
        "but its intent should clearly relate to one of these domains:\n"
        "- shopping: buying groceries, adding/removing items from a shopping list, "
        "what to buy, provisions, supplies, supermarket, store.\n"
        "- weather: forecast, temperature, rain, sun, wind, climate, meteorology, conditions.\n"
        "- calendar: events, appointments, schedule, agenda, meetings, dates, reminders.\n\n"
        "Respond with exactly one word — no punctuation, no markdown, no explanation: "
        "shopping, weather, calendar, or none.\n\n"
        f"Message: \"{text}\"\nCategory:"
    )
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 10},
        }, timeout=15)
        raw = response.json().get("response", "").strip().lower()
        # Strip markdown formatting (e.g. **shopping** → shopping) and stray punctuation
        answer = re.sub(r'[*_`#]', '', raw).strip().strip('"').strip("'").strip()
        logger.debug("🏷️ classify_intent_category → '%s' for: %s", answer, text)
        if answer in ("shopping", "weather", "calendar"):
            return answer
        return None
    except Exception as e:
        logger.warning("⚠️ classify_intent_category error: %s", e)
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
    from skills.shopping import prompt as _p
    return _p()


def get_calendar_prompt() -> str:
    from skills.calendar import prompt as _p
    return _p()


def get_weather_prompt() -> str:
    from skills.weather import prompt as _p
    return _p()


def _parse_raw(raw: str) -> dict:
    raw_normalized = raw.replace('{{', '{').replace('}}', '}')
    match = re.search(r'\{.*\}', raw_normalized, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {raw}")
    return json.loads(match.group())


def detect_language(text: str) -> dict:
    """Ask the LLM to detect the language of a message.
    Returns {"language": "...", "confidence": "high"|"medium"|"low"} or None on error."""
    prompt = (
        "Detect the language of the following text. "
        "Respond ONLY with a valid JSON object with two fields:\n"
        '- "language": the full English name of the language (e.g. "Spanish", "Italian", "French", "German").\n'
        '- "confidence": "high", "medium", or "low".\n'
        "If the text is in English, respond with {\"language\": \"English\", \"confidence\": \"high\"}.\n\n"
        f"Text: \"{text}\"\nResponse:"
    )
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0, "num_predict": 50},
        }, timeout=30)
        raw = response.json().get("response", "").strip()
        logger.debug("🌐 detect_language raw → %s", raw)
        return _parse_raw(raw)
    except Exception as e:
        logger.warning("⚠️ detect_language error: %s", e)
        return None


def translate_to_english(text: str, source_language: str) -> str | None:
    """Translate text from a detected language to English using the LLM."""
    prompt = (
        f"Translate the following {source_language} text to English. "
        "Respond ONLY with the English translation, nothing else. "
        "Translate only the action/command words; do NOT translate proper nouns, personal names, or specific event/item titles — keep those exactly as they appear in the original text.\n\n"
        f"Text: \"{text}\"\nTranslation:"
    )
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }, timeout=60)
        result = response.json().get("response", "").strip().strip('"')
        logger.debug("🌐 translate_to_english → %s", result)
        return result if result else None
    except Exception as e:
        logger.warning("⚠️ translate_to_english error: %s", e)
        return None


def translate_from_english(text: str, target_language: str) -> str | None:
    """Translate an English response to the target language using the LLM."""
    prompt = (
        f"Translate the following English text to {target_language}. "
        "Output ONLY the translated text — no explanations, no notes, no comments, no parenthetical remarks, no quotation marks around the output. "
        "Translate ALL words including: grocery items, food items, household products, common words, and command keywords. "
        "The ONLY exceptions (keep exactly as in the original): personal names (people's names), geographical place names, and calendar event titles.\n\n"
        f"Text:\n{text}\n\nTranslation:"
    )
    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }, timeout=60)
        result = response.json().get("response", "").strip().strip('"').strip()
        logger.debug("🌐 translate_from_english → %s", result)
        return result if result else None
    except Exception as e:
        logger.warning("⚠️ translate_from_english error: %s", e)
        return None


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
    from skills.registry import get_prompt
    category = detect_category(text)
    prompt_fn = get_prompt(category) if category else None
    if prompt_fn:
        prompt_text = f"{prompt_fn()}\n\nMessage: \"{text}\"\nResponse:"
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
        logger.debug("⏱️ Ollama HTTP call (%s): %.2fs", MODEL, t2 - t1)
        response.raise_for_status()
        raw = response.json()["response"].strip()
        logger.debug("🧠 Ollama raw response (%s): %s", MODEL, raw)
        return _parse_raw(raw)
    except Exception as e:
        logger.error("Error in parse_intent: %s", e)
        return {"action": "error"}
