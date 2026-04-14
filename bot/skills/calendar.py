from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta

from services.calendar_handler import (
    show_events,
    show_events_period,
    add_event,
    delete_event,
    edit_event,
    event_details,
)
from .registry import register, register_prompt
from .schemas import ToolOutput


class CalendarShowIn(BaseModel):
    days: Optional[int] = 1
    offset_days: Optional[int] = 0


class CalendarPeriodIn(BaseModel):
    start_date: str
    end_date: str


class CalendarAddIn(BaseModel):
    title: str
    date: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    location: Optional[str] = None


class CalendarDeleteIn(BaseModel):
    title: str
    date: Optional[str] = None


class CalendarEditIn(BaseModel):
    title: str
    new_title: Optional[str] = None
    new_date: Optional[str] = None
    new_time: Optional[str] = None
    new_location: Optional[str] = None


class CalendarDetailsIn(BaseModel):
    title: str


def show_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarShowIn(**(payload or {}))
    res = show_events(days=req.days or 1, offset_days=req.offset_days or 0)
    return {"ok": True, "message": res}


def period_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarPeriodIn(**(payload or {}))
    res = show_events_period(start_date=req.start_date, end_date=req.end_date)
    return {"ok": True, "message": res}


def add_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarAddIn(**(payload or {}))
    res = add_event(title=req.title, date=req.date, start_time=req.start_time, end_time=req.end_time, location=req.location)
    return {"ok": True, "message": res}


def delete_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarDeleteIn(**(payload or {}))
    res = delete_event(title=req.title, date=req.date)
    return {"ok": True, "message": res}


def edit_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarEditIn(**(payload or {}))
    res = edit_event(title=req.title, new_title=req.new_title, new_date=req.new_date, new_time=req.new_time, new_location=req.new_location)
    return {"ok": True, "message": res}


def details_tool(payload: dict) -> Dict[str, Any]:
    req = CalendarDetailsIn(**(payload or {}))
    res = event_details(req.title)
    return {"ok": True, "message": res}


# Register calendar tools
register(
    "calendar.show",
    show_tool,
    input_schema=CalendarShowIn,
    output_schema=ToolOutput,
    desc="Show events for next N days",
)

register(
    "calendar.period",
    period_tool,
    input_schema=CalendarPeriodIn,
    output_schema=ToolOutput,
    desc="Show events in a date range",
)

register(
    "calendar.add",
    add_tool,
    input_schema=CalendarAddIn,
    output_schema=ToolOutput,
    desc="Add calendar event",
)

register(
    "calendar.delete",
    delete_tool,
    input_schema=CalendarDeleteIn,
    output_schema=ToolOutput,
    desc="Delete calendar event by title (optional date)",
)

register(
    "calendar.edit",
    edit_tool,
    input_schema=CalendarEditIn,
    output_schema=ToolOutput,
    desc="Edit calendar event",
)

register(
    "calendar.details",
    details_tool,
    input_schema=CalendarDetailsIn,
    output_schema=ToolOutput,
    desc="Show event details by title",
)


def prompt() -> str:
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


register_prompt("calendar", prompt)
