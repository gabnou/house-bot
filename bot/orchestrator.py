import os
import sys
import json
import asyncio
import inspect
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Actions that map to shopping tools for now
SHOPPING_ACTIONS = {"add", "remove", "bought", "show", "clear"}

_SKILLS_CONFIG_FILE = Path(__file__).parent / "skills_config.json"

_SKILL_DISPLAY_NAMES = {
    "calendar": "Google Calendar",
    "shopping": "Shopping List",
    "weather": "Weather Forecast",
}


def _is_skill_enabled(skill: str) -> bool:
    """Read skills_config.json and return whether the given skill is enabled.

    Defaults to True (enabled) if the file is missing or the key is absent.
    """
    try:
        cfg = json.loads(_SKILLS_CONFIG_FILE.read_text(encoding="utf-8"))
        return bool(cfg.get(skill, True))
    except Exception:
        return True


def action_to_tool(action: str) -> Optional[str]:
    if not action:
        return None
    # Allow passing fully-qualified tool names
    if "." in action:
        return action

    a = action.lower().strip().replace("-", "_").replace(" ", "_")

    # Shopping
    if a in SHOPPING_ACTIONS:
        return f"shopping.{a}"

    # Weather mappings
    weather_map = {
        "weather_now": "weather.now",
        "weather_hours": "weather.hours",
        "weather_hours_date": "weather.hours_day",
        "weather_forecast": "weather.forecast",
        "weather_date": "weather.date",
        "weather_morning": "weather.morning",
    }
    if a in weather_map:
        return weather_map[a]

    # Calendar mappings
    calendar_map = {
        "calendar_show": "calendar.show",
        "calendar_period": "calendar.period",
        "calendar_add": "calendar.add",
        "calendar_delete": "calendar.delete",
        "calendar_edit": "calendar.edit",
        "calendar_details": "calendar.details",
    }
    if a in calendar_map:
        return calendar_map[a]

    return None


async def handle_intent(intent: Dict[str, Any], text: str, sender: str) -> Optional[Dict[str, Any]]:
    """Orchestrator entrypoint.

    Returns a dict with `reply` and optional `notification`, or None if it didn't handle the intent.
    """
    try:
        from skills.registry import get as registry_get
        from skills import format_tool_reply
    except Exception as e:
        logger.exception("Failed importing skills registry: %s", e)
        return None

    action = intent.get("action", "")
    tool_name = action_to_tool(action)
    if not tool_name:
        logger.debug("Orchestrator: no mapping for action '%s'", action)
        return None

    # Gate on skill enabled state
    skill_prefix = tool_name.split(".")[0]
    if not _is_skill_enabled(skill_prefix):
        display = _SKILL_DISPLAY_NAMES.get(skill_prefix, skill_prefix.title())
        logger.info("Orchestrator: skill '%s' is disabled — rejecting action '%s'", skill_prefix, action)
        return {
            "reply": f"The {display} skill is currently disabled. You can enable it in the Skills page of the Control Panel.",
            "notification": None,
        }

    tool = registry_get(tool_name)
    if not tool:
        logger.debug("Orchestrator: no registered tool '%s'", tool_name)
        return None

    input_schema = tool.get("in")
    fn = tool.get("fn")

    # Prefer `params` if provided by intent, else send whole intent
    payload = intent.get("params") if isinstance(intent.get("params"), dict) else intent

    # Validate input schema if present
    if input_schema:
        try:
            validated = input_schema(**(payload or {}))
            payload_dict = validated.dict()
        except Exception as e:
            logger.warning("Orchestrator: input validation failed for %s: %s", tool_name, e)
            return {"reply": f"⚠️ Invalid parameters for {tool_name}: {e}", "notification": None}
    else:
        payload_dict = payload or {}

    # Call tool (sync tools run in thread pool)
    try:
        if inspect.iscoroutinefunction(fn):
            result = await fn(payload_dict)
        else:
            result = await asyncio.to_thread(fn, payload_dict)
    except Exception as e:
        logger.exception("Orchestrator: tool %s raised: %s", tool_name, e)
        return {"reply": f"⚠️ Error while executing {tool_name}: {e}", "notification": None}

    # Format reply
    if isinstance(result, dict):
        reply = result.get("message") or result.get("reply") or format_tool_reply(result)
    else:
        reply = format_tool_reply(result)

    notification = None
    # Build notification for modifying shopping actions if needed
    if action in {"add", "remove", "bought", "clear"}:
        try:
            from services.shopping_db import show_list
            updated_list = await asyncio.to_thread(show_list)
            notification = f"📋 List updated by a partner:\n\n{updated_list}"
        except Exception:
            notification = None

    return {"reply": reply, "notification": notification}
