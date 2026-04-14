import os
import calendar as _calendar_mod
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/calendar']

# Paths relative to project root (three levels above: bot/services/ → bot/ → root)
PROJECT_ROOT = Path(__file__).parent.parent.parent
CREDENTIALS_PATH = os.getenv(
    'GOOGLE_CREDENTIALS_PATH',
    str(PROJECT_ROOT / 'creds' / 'client_google_api_calendar.json')
)
TOKEN_PATH = os.getenv(
    'GOOGLE_TOKEN_PATH',
    str(PROJECT_ROOT / 'creds' / 'token.json')
)
CALENDAR_NAME = os.getenv('GOOGLE_CALENDAR_NAME', 'Familia')
TIMEZONE = os.getenv('CALENDAR_TIMEZONE', 'Europe/Madrid')

MONTHS = ['', 'January', 'February', 'March', 'April', 'May', 'June',
          'July', 'August', 'September', 'October', 'November', 'December']
WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def _format_period_title(start_date: str, end_date: str) -> str:
    """Returns a human-readable English title for a date range."""
    dt_s = datetime.fromisoformat(start_date)
    dt_e = datetime.fromisoformat(end_date)

    if start_date == end_date:
        day = WEEKDAYS[dt_s.weekday()]
        return f"{day} {MONTHS[dt_s.month]} {dt_s.day}, {dt_s.year}"

    last_day = _calendar_mod.monthrange(dt_s.year, dt_s.month)[1]
    if (dt_s.day == 1 and dt_e.day == last_day
            and dt_s.month == dt_e.month and dt_s.year == dt_e.year):
        return f"{MONTHS[dt_s.month]} {dt_s.year}"

    if dt_s.year == dt_e.year:
        if dt_s.month == dt_e.month:
            return f"{MONTHS[dt_s.month]} {dt_s.day}–{dt_e.day}, {dt_s.year}"
        return (f"{MONTHS[dt_s.month]} {dt_s.day} – "
                f"{MONTHS[dt_e.month]} {dt_e.day}, {dt_s.year}")
    return (f"{MONTHS[dt_s.month]} {dt_s.day}, {dt_s.year} – "
            f"{MONTHS[dt_e.month]} {dt_e.day}, {dt_e.year}")


def get_service():
    creds = None

    if Path(TOKEN_PATH).exists():
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token:
            token.write(creds.to_json())

    return build('calendar', 'v3', credentials=creds)


def get_calendar_id() -> str:
    """Find the ID of the configured calendar."""
    service = get_service()
    calendars = service.calendarList().list().execute()
    for cal in calendars.get('items', []):
        if cal['summary'].lower() == CALENDAR_NAME.lower():
            return cal['id']
    return 'primary'


def show_events(days: int = 1, offset_days: int = 0) -> str:
    """Show events. offset_days=0 starts from today, offset_days=1 from tomorrow."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        tz = ZoneInfo(TIMEZONE)
        today_start = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today_start + timedelta(days=offset_days)
        end = today_start + timedelta(days=offset_days + days)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute().get('items', [])

        if not events:
            if offset_days == 1:
                return f"📅 No events tomorrow in calendar {CALENDAR_NAME}."
            elif offset_days == 2:
                return f"📅 No events the day after tomorrow in calendar {CALENDAR_NAME}."
            else:
                period = "today" if days == 1 else f"in the next {days} days"
                return f"📅 No events {period} in calendar {CALENDAR_NAME}."

        if offset_days == 1:
            period = "Tomorrow"
        elif offset_days == 2:
            period = "Day after tomorrow"
        elif days == 1:
            period = "Today"
        else:
            period = f"Next {days} days"

        lines = [f"📅 *{CALENDAR_NAME} — {period}*\n"]
        for e in events:
            start_str = e['start'].get('dateTime', e['start'].get('date', ''))
            try:
                dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                time_str = dt.strftime('%m/%d %H:%M')
            except Exception:
                time_str = start_str

            title = e.get('summary', '(no title)')
            location = f" 📍 {e['location']}" if e.get('location') else ""
            lines.append(f"• *{time_str}* — {title}{location}")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching events: {e}"


def show_events_period(start_date: str, end_date: str) -> str:
    """Show events in a specified period. Dates in YYYY-MM-DD format."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        tz = ZoneInfo(TIMEZONE)
        dt_start = datetime.fromisoformat(start_date).replace(
            hour=0, minute=0, second=0, microsecond=0, tzinfo=tz)
        dt_end = datetime.fromisoformat(end_date).replace(
            hour=23, minute=59, second=59, microsecond=0, tzinfo=tz)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=dt_start.isoformat(),
            timeMax=dt_end.isoformat(),
            singleEvents=True,
            orderBy='startTime'
        ).execute().get('items', [])

        period_title = _format_period_title(start_date, end_date)

        if not events:
            return f"📅 No events — {period_title} in calendar {CALENDAR_NAME}."

        lines = [f"📅 *{CALENDAR_NAME} — {period_title}*\n"]
        for e in events:
            start_str = e['start'].get('dateTime', e['start'].get('date', ''))
            try:
                dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                time_str = dt.strftime('%m/%d %H:%M')
            except Exception:
                time_str = start_str

            title = e.get('summary', '(no title)')
            location = f" 📍 {e['location']}" if e.get('location') else ""
            lines.append(f"• *{time_str}* — {title}{location}")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching events: {e}"


def add_event(title: str, date: str, start_time: str = None,
              end_time: str = None, location: str = None) -> str:
    """Add an event to the calendar."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        if start_time:
            start = {'dateTime': f"{date}T{start_time}:00", 'timeZone': TIMEZONE}
            end_time = end_time or f"{int(start_time[:2])+1:02d}{start_time[2:]}"
            end = {'dateTime': f"{date}T{end_time}:00", 'timeZone': TIMEZONE}
        else:
            start = {'date': date}
            end = {'date': date}

        event = {
            'summary': title,
            'start': start,
            'end': end,
        }
        if location:
            event['location'] = location

        service.events().insert(calendarId=calendar_id, body=event).execute()
        time_str = f" at {start_time}" if start_time else ""
        return f"✅ Event *{title}* added for {date}{time_str}."
    except Exception as e:
        return f"⚠️ Error adding event: {e}"


def delete_event(title: str, date: str = None) -> str:
    """Delete an event by title (and optionally date)."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        now = datetime.utcnow()
        end = now + timedelta(days=30)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat() + 'Z',
            timeMax=end.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime',
            q=title
        ).execute().get('items', [])

        if not events:
            return f"⚠️ No event found with title *{title}*."

        event = events[0]
        service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
        return f"🗑️ Event *{event.get('summary', title)}* deleted."
    except Exception as e:
        return f"⚠️ Error deleting event: {e}"


def edit_event(title: str, new_title: str = None, new_date: str = None,
               new_time: str = None, new_location: str = None) -> str:
    """Edit an existing event."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        now = datetime.utcnow()
        end = now + timedelta(days=30)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat() + 'Z',
            timeMax=end.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime',
            q=title
        ).execute().get('items', [])

        if not events:
            return f"⚠️ No event found with title *{title}*."

        event = events[0]

        if new_title:
            event['summary'] = new_title
        if new_date and new_time:
            event['start'] = {'dateTime': f"{new_date}T{new_time}:00",
                              'timeZone': TIMEZONE}
            end_time = f"{int(new_time[:2])+1:02d}{new_time[2:]}"
            event['end'] = {'dateTime': f"{new_date}T{end_time}:00",
                            'timeZone': TIMEZONE}
        elif new_date:
            event['start'] = {'date': new_date}
            event['end'] = {'date': new_date}
        if new_location:
            event['location'] = new_location

        service.events().update(
            calendarId=calendar_id,
            eventId=event['id'],
            body=event
        ).execute()

        return f"✅ Event *{title}* updated."
    except Exception as e:
        return f"⚠️ Error updating event: {e}"


def event_details(title: str) -> str:
    """Show full details of an event by title."""
    try:
        service = get_service()
        calendar_id = get_calendar_id()

        now = datetime.utcnow()
        end = now + timedelta(days=30)

        events = service.events().list(
            calendarId=calendar_id,
            timeMin=now.isoformat() + 'Z',
            timeMax=end.isoformat() + 'Z',
            singleEvents=True,
            orderBy='startTime',
            q=title
        ).execute().get('items', [])

        if not events:
            return f"⚠️ No event found with title *{title}*."

        e = events[0]

        # Time
        start_str = e['start'].get('dateTime', e['start'].get('date', ''))
        end_str = e['end'].get('dateTime', e['end'].get('date', ''))
        try:
            dt_start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
            dt_end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
            time_range = f"{dt_start.strftime('%m/%d/%Y %H:%M')} → {dt_end.strftime('%H:%M')}"
        except Exception:
            time_range = start_str

        lines = [
            f"📅 *{e.get('summary', '(no title)')}*\n",
            f"🕐 {time_range}",
        ]

        if e.get('location'):
            lines.append(f"📍 {e['location']}")

        if e.get('description'):
            lines.append(f"📝 {e['description']}")

        # Reminders
        reminders = e.get('reminders', {})
        if reminders.get('useDefault'):
            lines.append("🔔 Reminder: default (10 min)")
        elif reminders.get('overrides'):
            reminder_parts = []
            for r in reminders['overrides']:
                minutes = r.get('minutes', 0)
                if minutes >= 60:
                    reminder_parts.append(f"{minutes // 60}h before")
                else:
                    reminder_parts.append(f"{minutes} min before")
            lines.append(f"🔔 Reminders: {', '.join(reminder_parts)}")

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching event details: {e}"
