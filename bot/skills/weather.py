from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta

from services.weather import (
    get_weather_now,
    get_weather_hours,
    get_weather_hours_day,
    get_weather_forecast,
    get_morning_briefing,
)
from .registry import register, register_prompt
from .schemas import ToolOutput


class WeatherNowIn(BaseModel):
    city: Optional[str] = None


class WeatherHoursIn(BaseModel):
    hours: Optional[int] = 12
    city: Optional[str] = None


class WeatherHoursDayIn(BaseModel):
    date: str
    city: Optional[str] = None


class WeatherForecastIn(BaseModel):
    city: Optional[str] = None
    days: Optional[int] = 3
    offset_days: Optional[int] = 0


class WeatherDateIn(BaseModel):
    date: str
    city: Optional[str] = None


def now_tool(payload: dict) -> Dict[str, Any]:
    req = WeatherNowIn(**(payload or {}))
    res = get_weather_now(req.city)
    return {"ok": True, "message": res}


def hours_tool(payload: dict) -> Dict[str, Any]:
    req = WeatherHoursIn(**(payload or {}))
    res = get_weather_hours(hours=req.hours or 12, city=req.city)
    return {"ok": True, "message": res}


def hours_day_tool(payload: dict) -> Dict[str, Any]:
    req = WeatherHoursDayIn(**(payload or {}))
    res = get_weather_hours_day(target_date=req.date, city=req.city)
    return {"ok": True, "message": res}


def forecast_tool(payload: dict) -> Dict[str, Any]:
    req = WeatherForecastIn(**(payload or {}))
    res = get_weather_forecast(city=req.city, days=req.days or 3, offset_days=req.offset_days or 0)
    return {"ok": True, "message": res}


def date_tool(payload: dict) -> Dict[str, Any]:
    """Accepts a `date` in YYYY-MM-DD and shows forecast for that specific date (1 day)."""
    req = WeatherDateIn(**(payload or {}))
    date_str = req.date
    try:
        target = datetime.strptime(date_str, "%Y-%m-%d").date()
        today = datetime.now().date()
        offset = (target - today).days
        if offset < 0:
            return {"ok": False, "message": "⚠️ The requested date has already passed."}
        if offset > 6:
            return {"ok": False, "message": "⚠️ I can only show forecasts for the next 7 days."}
        res = get_weather_forecast(city=req.city, days=1, offset_days=offset)
        return {"ok": True, "message": res}
    except Exception:
        return {"ok": False, "message": "⚠️ Invalid date. Use YYYY-MM-DD."}


def morning_tool(payload: dict) -> Dict[str, Any]:
    res = get_morning_briefing()
    return {"ok": True, "message": res}


# Register weather tools
register(
    "weather.now",
    now_tool,
    input_schema=WeatherNowIn,
    output_schema=ToolOutput,
    desc="Get current weather for a city (optional).",
)

register(
    "weather.hours",
    hours_tool,
    input_schema=WeatherHoursIn,
    output_schema=ToolOutput,
    desc="Get hourly weather for the next N hours.",
)

register(
    "weather.hours_day",
    hours_day_tool,
    input_schema=WeatherHoursDayIn,
    output_schema=ToolOutput,
    desc="Get hourly weather for a specific date (YYYY-MM-DD).",
)

register(
    "weather.forecast",
    forecast_tool,
    input_schema=WeatherForecastIn,
    output_schema=ToolOutput,
    desc="Get daily weather forecast (days, offset_days).",
)

register(
    "weather.date",
    date_tool,
    input_schema=WeatherDateIn,
    output_schema=ToolOutput,
    desc="Get forecast for a specific date (YYYY-MM-DD).",
)

register(
    "weather.morning",
    morning_tool,
    input_schema=None,
    output_schema=ToolOutput,
    desc="Get morning briefing (default location).",
)


def prompt() -> str:
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


register_prompt("weather", prompt)
