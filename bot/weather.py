import certifi
import logging
import os
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# SSL verification
_certifi_path = certifi.where()
_SSL_VERIFY = _certifi_path if os.path.isfile(_certifi_path) else True

# Default city settings (loaded from .env)
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Barcelona")
DEFAULT_LATITUDE = float(os.getenv("DEFAULT_LATITUDE", "41.3874"))
DEFAULT_LONGITUDE = float(os.getenv("DEFAULT_LONGITUDE", "2.1686"))
TIMEZONE_DEFAULT = os.getenv("TIMEZONE_DEFAULT", "Europe/Madrid")
MAX_HOURS = 24

# OpenWeatherMap API
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
OPENWEATHER_BASE_URL = "https://api.openweathermap.org"

# International city name aliases (input → canonical name for geocoding)
_CITY_ALIASES = {
    "barcellona": "Barcelona",    # Italian
    "londra": "London",           # Italian
    "nueva york": "New York",     # Spanish
    "parigi": "Paris",            # Italian
    "mosca": "Moscow",            # Italian
    "pechino": "Beijing",         # Italian
    "tokio": "Tokyo",             # Spanish
    "sidney": "Sydney",           # Common misspelling
    "roma": "Rome",               # Italian
    "berlino": "Berlin",          # Italian
}

# OpenWeatherMap condition codes → emoji + description
OW_CODES = {
    200: "⛈️ Thunderstorm with light rain",
    201: "⛈️ Thunderstorm with rain",
    202: "⛈️ Thunderstorm with heavy rain",
    210: "⛈️ Light thunderstorm",
    211: "⛈️ Thunderstorm",
    212: "⛈️ Heavy thunderstorm",
    230: "⛈️ Thunderstorm with drizzle",
    300: "🌦️ Light drizzle",
    301: "🌦️ Drizzle",
    302: "🌧️ Heavy drizzle",
    500: "🌧️ Light rain",
    501: "🌧️ Moderate rain",
    502: "🌧️ Heavy rain",
    511: "🌧️ Freezing rain",
    520: "🌦️ Light shower rain",
    521: "🌧️ Shower rain",
    600: "🌨️ Light snow",
    601: "🌨️ Snow",
    602: "❄️ Heavy snow",
    611: "🌧️ Sleet",
    615: "🌨️ Rain and snow",
    620: "🌨️ Shower snow",
    701: "🌫️ Mist",
    721: "🌫️ Haze",
    741: "🌫️ Fog",
    781: "🌪️ Tornado",
    800: "☀️ Clear sky",
    801: "🌤️ Few clouds",
    802: "⛅ Scattered clouds",
    803: "🌥️ Broken clouds",
    804: "☁️ Overcast",
}

# WMO codes for Open-Meteo fallback
WMO_CODES = {
    0: "☀️ Clear sky",
    1: "🌤️ Mostly clear",
    2: "⛅ Partly cloudy",
    3: "☁️ Overcast",
    45: "🌫️ Fog",
    48: "🌫️ Fog with rime",
    51: "🌦️ Light drizzle",
    53: "🌦️ Moderate drizzle",
    55: "🌧️ Heavy drizzle",
    61: "🌧️ Light rain",
    63: "🌧️ Moderate rain",
    65: "🌧️ Heavy rain",
    71: "🌨️ Light snow",
    73: "🌨️ Moderate snow",
    75: "❄️ Heavy snow",
    80: "🌦️ Light showers",
    81: "🌧️ Moderate showers",
    82: "⛈️ Heavy showers",
    95: "⛈️ Thunderstorm",
    96: "⛈️ Thunderstorm with hail",
    99: "⛈️ Thunderstorm with heavy hail",
}

WIND_DIRECTIONS = [
    "N", "NNE", "NE", "ENE",
    "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW",
    "W", "WNW", "NW", "NNW",
]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def degrees_to_direction(degrees: float) -> str:
    index = round(degrees / 22.5) % 16
    return WIND_DIRECTIONS[index]


def get_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=2, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _ow_desc(code: int) -> str:
    return OW_CODES.get(code, "🌡️ Variable conditions")


def _resolve_city_name(city: str) -> str:
    return _CITY_ALIASES.get(city.lower().strip(), city)


def geocode(city: str):
    city = _resolve_city_name(city)
    try:
        resp = get_session().get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "en", "format": "json"},
            timeout=10,
            verify=_SSL_VERIFY
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        r = results[0]
        return r["latitude"], r["longitude"], r["name"], r.get("timezone", TIMEZONE_DEFAULT)
    except Exception as e:
        logger.error("Geocoding error: %s", e)
        return None


def _resolve_city(city: str = None):
    if not city:
        return DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_CITY, TIMEZONE_DEFAULT
    result = geocode(city)
    if not result:
        return None
    return result


# ─── OpenWeatherMap helpers ───────────────────────────────────────────────────

def _fetch_openweather_onecall(lat: float, lon: float) -> dict | None:
    if not OPENWEATHER_API_KEY:
        return None
    try:
        resp = get_session().get(
            f"{OPENWEATHER_BASE_URL}/data/3.0/onecall",
            params={
                "lat": lat,
                "lon": lon,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric",
                "exclude": "minutely,alerts",
            },
            timeout=15,
            verify=_SSL_VERIFY,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error("OpenWeather One Call error: %s", e)
        return None


def _fetch_open_meteo(params: dict) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    resp = get_session().get(url, params=params, timeout=15, verify=_SSL_VERIFY)
    resp.raise_for_status()
    return resp.json()


# ─── Public interface ─────────────────────────────────────────────────────────

def get_weather_now(city: str = None) -> str:
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."
    lat, lon, name, tz_name = geo

    # Primary: OpenWeatherMap
    if OPENWEATHER_API_KEY:
        data = _fetch_openweather_onecall(lat, lon)
        if data:
            cur = data["current"]
            desc = _ow_desc(cur["weather"][0]["id"])
            temp = cur.get("temp", "N/A")
            humidity = cur.get("humidity", "N/A")
            rain = cur.get("rain", {}).get("1h", 0)
            wind = cur.get("wind_speed", "N/A")
            dir_str = degrees_to_direction(cur.get("wind_deg", 0))
            uv = cur.get("uvi", "N/A")
            rain_str = f"{rain} mm" if rain and rain > 0 else "None"
            logger.debug("[weather] get_weather_now: OpenWeather (city=%s)", name)
            return (
                f"🌍 *{name} — Now*\n\n"
                f"{desc}\n"
                f"🌡️ Temperature: {temp}°C\n"
                f"🌧️ Rain: {rain_str}\n"
                f"💧 Humidity: {humidity}%\n"
                f"💨 Wind: {wind} km/h from {dir_str}\n"
                f"☀️ UV index: {uv}"
            )
        logger.warning("[weather] get_weather_now: OpenWeather failed, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": lat, "longitude": lon,
            "current": ["temperature_2m", "precipitation", "precipitation_probability",
                        "wind_speed_10m", "wind_direction_10m", "uv_index", "weather_code"],
            "timezone": tz_name,
        })
        cur = data["current"]
        desc = WMO_CODES.get(cur.get("weather_code", 0), "🌡️ Variable conditions")
        temp = cur.get("temperature_2m", "N/A")
        rain = cur.get("precipitation", 0)
        rain_prob = cur.get("precipitation_probability", 0)
        wind = cur.get("wind_speed_10m", "N/A")
        dir_str = degrees_to_direction(cur.get("wind_direction_10m", 0))
        uv = cur.get("uv_index", "N/A")
        rain_str = f"{rain} mm" if rain and rain > 0 else "None"
        return (
            f"🌍 *{name} — Now*\n\n"
            f"{desc}\n"
            f"🌡️ Temperature: {temp}°C\n"
            f"🌧️ Rain: {rain_str} (prob. {rain_prob}%)\n"
            f"💨 Wind: {wind} km/h from {dir_str}\n"
            f"☀️ UV index: {uv}"
        )
    except Exception as e:
        return f"⚠️ Error fetching current weather: {e}"


def get_weather_hours(hours: int = 12, city: str = None) -> str:
    warning = ""
    if hours > MAX_HOURS:
        warning = f"⚠️ Showing only the next {MAX_HOURS} hours (maximum supported).\n\n"
        hours = MAX_HOURS

    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."
    lat, lon, name, tz_name = geo

    # Primary: OpenWeatherMap
    if OPENWEATHER_API_KEY:
        data = _fetch_openweather_onecall(lat, lon)
        if data:
            tz = ZoneInfo(tz_name)
            now = datetime.now(tz)
            lines = [f"{warning}🌍 *{name} — Next {hours} hours*\n"]
            count = 0
            for h in data.get("hourly", []):
                if count >= hours:
                    break
                dt = datetime.fromtimestamp(h["dt"], tz=tz)
                if dt < now:
                    continue
                desc = _ow_desc(h["weather"][0]["id"])
                temp = h.get("temp", "N/A")
                pop = round(h.get("pop", 0) * 100)
                rain = h.get("rain", {}).get("1h", 0)
                wind = h.get("wind_speed", "N/A")
                dir_str = degrees_to_direction(h.get("wind_deg", 0))
                rain_str = f"{rain}mm" if rain and rain > 0 else "—"
                lines.append(
                    f"*{dt.strftime('%H:%M')}* {desc}\n"
                    f"  🌡️ {temp}°C · 🌧️ {pop}% ({rain_str}) · 💨 {wind}km/h {dir_str}"
                )
                count += 1
            logger.debug("[weather] get_weather_hours: OpenWeather (city=%s, hours=%s)", name, hours)
            return "\n".join(lines)
        logger.warning("[weather] get_weather_hours: OpenWeather failed, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": lat, "longitude": lon,
            "hourly": ["temperature_2m", "precipitation_probability", "precipitation",
                       "wind_speed_10m", "wind_direction_10m", "weather_code"],
            "timezone": tz_name, "forecast_days": 2,
        })
        hourly = data["hourly"]
        current_time = datetime.now(timezone.utc)
        lines = [f"{warning}🌍 *{name} — Next {hours} hours*\n"]
        count = 0
        for i, time_str in enumerate(hourly["time"]):
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < current_time:
                continue
            if count >= hours:
                break
            desc = WMO_CODES.get(hourly["weather_code"][i], "🌡️")
            temp = hourly["temperature_2m"][i]
            prob = hourly["precipitation_probability"][i]
            rain = hourly["precipitation"][i]
            wind = hourly["wind_speed_10m"][i]
            dir_str = degrees_to_direction(hourly["wind_direction_10m"][i])
            rain_str = f"{rain}mm" if rain and rain > 0 else "—"
            lines.append(
                f"*{dt.strftime('%H:%M')}* {desc}\n"
                f"  🌡️ {temp}°C · 🌧️ {prob}% ({rain_str}) · 💨 {wind}km/h {dir_str}"
            )
            count += 1
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching hourly weather: {e}"


def get_weather_hours_day(target_date: str, city: str = None) -> str:
    try:
        target_d = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        return "⚠️ Invalid date."

    today = datetime.now().date()
    offset = (target_d - today).days
    if offset < 0:
        return "⚠️ The requested date has already passed."
    if offset > 3:
        return "⚠️ Hourly forecasts are available only for the next 3 days."

    if offset == 0:
        title = "Today"
    elif offset == 1:
        title = "Tomorrow"
    elif offset == 2:
        title = "Day after tomorrow"
    else:
        title = WEEKDAYS[target_d.weekday()]

    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."
    lat, lon, name, tz_name = geo

    # Primary: OpenWeatherMap
    if OPENWEATHER_API_KEY:
        data = _fetch_openweather_onecall(lat, lon)
        if data:
            tz = ZoneInfo(tz_name)
            lines = [f"🌍 *{name} — Hourly {title}*\n"]
            count = 0
            for h in data.get("hourly", []):
                dt = datetime.fromtimestamp(h["dt"], tz=tz)
                if dt.date() != target_d:
                    continue
                desc = _ow_desc(h["weather"][0]["id"])
                temp = h.get("temp", "N/A")
                pop = round(h.get("pop", 0) * 100)
                rain = h.get("rain", {}).get("1h", 0)
                wind = h.get("wind_speed", "N/A")
                dir_str = degrees_to_direction(h.get("wind_deg", 0))
                rain_str = f"{rain}mm" if rain and rain > 0 else "—"
                lines.append(
                    f"*{dt.strftime('%H:%M')}* {desc}\n"
                    f"  🌡️ {temp}°C · 🌧️ {pop}% ({rain_str}) · 💨 {wind}km/h {dir_str}"
                )
                count += 1
            if count == 0:
                return f"⚠️ No hourly data available for {title}."
            logger.debug("[weather] get_weather_hours_day: OpenWeather (city=%s, date=%s)", name, target_date)
            return "\n".join(lines)
        logger.warning("[weather] get_weather_hours_day: OpenWeather failed, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": lat, "longitude": lon,
            "hourly": ["temperature_2m", "precipitation_probability", "precipitation",
                       "wind_speed_10m", "wind_direction_10m", "weather_code"],
            "timezone": tz_name, "forecast_days": offset + 2,
        })
        hourly = data["hourly"]
        lines = [f"🌍 *{name} — Hourly {title}*\n"]
        count = 0
        for i, time_str in enumerate(hourly["time"]):
            dt = datetime.fromisoformat(time_str)
            if dt.date() != target_d:
                continue
            desc = WMO_CODES.get(hourly["weather_code"][i], "🌡️")
            temp = hourly["temperature_2m"][i]
            prob = hourly["precipitation_probability"][i]
            rain = hourly["precipitation"][i]
            wind = hourly["wind_speed_10m"][i]
            dir_str = degrees_to_direction(hourly["wind_direction_10m"][i])
            rain_str = f"{rain}mm" if rain and rain > 0 else "—"
            lines.append(
                f"*{dt.strftime('%H:%M')}* {desc}\n"
                f"  🌡️ {temp}°C · 🌧️ {prob}% ({rain_str}) · 💨 {wind}km/h {dir_str}"
            )
            count += 1
        if count == 0:
            return f"⚠️ No hourly data available for {title}."
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching hourly weather: {e}"


def get_weather_forecast(city: str = None, days: int = 3, offset_days: int = 0) -> str:
    days = min(days, 7)
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."
    lat, lon, name, tz_name = geo

    today_d = datetime.now().date()
    tomorrow_d = today_d + timedelta(days=1)

    if days == 1 and offset_days == 0:
        title = "Today"
    elif days == 1 and offset_days == 1:
        title = "Tomorrow"
    elif days == 1 and offset_days >= 2:
        title = WEEKDAYS[(today_d + timedelta(days=offset_days)).weekday()]
    else:
        title = f"Next {days} days"

    # Primary: OpenWeatherMap
    if OPENWEATHER_API_KEY:
        data = _fetch_openweather_onecall(lat, lon)
        if data:
            tz = ZoneInfo(tz_name)
            daily = data.get("daily", [])[offset_days:offset_days + days]
            lines = [f"🌍 *{name} — {title}*\n"]
            for d in daily:
                dt = datetime.fromtimestamp(d["dt"], tz=tz)
                date_val = dt.date()
                date_str = dt.strftime("%Y-%m-%d")
                if date_val == today_d:
                    day_label = "Today"
                elif date_val == tomorrow_d:
                    day_label = "Tomorrow"
                else:
                    day_label = WEEKDAYS[date_val.weekday()]
                desc = _ow_desc(d["weather"][0]["id"])
                t_min = d["temp"]["min"]
                t_max = d["temp"]["max"]
                pop = round(d.get("pop", 0) * 100)
                rain = d.get("rain", 0)
                wind = d.get("wind_speed", "N/A")
                dir_str = degrees_to_direction(d.get("wind_deg", 0))
                uv = d.get("uvi", "N/A")
                rain_str = f"{rain}mm" if rain and rain > 0 else "None"
                lines.append(
                    f"*{day_label}* ({date_str})\n"
                    f"{desc}\n"
                    f"🌡️ {t_min}°C — {t_max}°C\n"
                    f"🌧️ {rain_str} (prob. {pop}%) · 💨 {wind}km/h {dir_str} · ☀️ UV {uv}\n"
                )
            logger.debug("[weather] get_weather_forecast: OpenWeather (city=%s, days=%s)", name, days)
            return "\n".join(lines)
        logger.warning("[weather] get_weather_forecast: OpenWeather failed, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": lat, "longitude": lon,
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                      "precipitation_probability_max", "wind_speed_10m_max",
                      "wind_direction_10m_dominant", "uv_index_max", "weather_code"],
            "timezone": tz_name, "forecast_days": offset_days + days,
        })
        daily = data["daily"]
        lines = [f"🌍 *{name} — {title}*\n"]
        for i in range(offset_days, offset_days + days):
            date_str = daily["time"][i]
            data_obj = datetime.strptime(date_str, "%Y-%m-%d")
            date_val = data_obj.date()
            if date_val == today_d:
                day_label = "Today"
            elif date_val == tomorrow_d:
                day_label = "Tomorrow"
            else:
                day_label = WEEKDAYS[data_obj.weekday()]
            desc = WMO_CODES.get(daily["weather_code"][i], "🌡️ Variable")
            t_max = daily["temperature_2m_max"][i]
            t_min = daily["temperature_2m_min"][i]
            rain = daily["precipitation_sum"][i]
            prob = daily["precipitation_probability_max"][i]
            wind = daily["wind_speed_10m_max"][i]
            dir_str = degrees_to_direction(daily["wind_direction_10m_dominant"][i])
            uv = daily["uv_index_max"][i]
            rain_str = f"{rain}mm" if rain and rain > 0 else "None"
            lines.append(
                f"*{day_label}* ({date_str})\n"
                f"{desc}\n"
                f"🌡️ {t_min}°C — {t_max}°C\n"
                f"🌧️ {rain_str} (prob. {prob}%) · 💨 {wind}km/h {dir_str} · ☀️ UV {uv}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching forecast: {e}"


def get_morning_briefing() -> str:
    lat, lon, name, tz_name = _resolve_city(None)

    # Primary: OpenWeatherMap
    if OPENWEATHER_API_KEY:
        data = _fetch_openweather_onecall(lat, lon)
        if data:
            cur = data["current"]
            day = data["daily"][0]
            desc = _ow_desc(cur["weather"][0]["id"])
            current_temp = cur.get("temp", "N/A")
            t_min = day["temp"]["min"]
            t_max = day["temp"]["max"]
            pop = round(day.get("pop", 0) * 100)
            rain = day.get("rain", 0)
            wind = day.get("wind_speed", "N/A")
            dir_str = degrees_to_direction(day.get("wind_deg", 0))
            uv = day.get("uvi", "N/A")
            rain_str = (
                f"{rain}mm (prob. {pop}%) — bring an umbrella! ☂️" if rain and rain > 0
                else f"None (prob. {pop}%) 👍"
            )
            uv_warn = " — use sunscreen! 🧴" if uv != "N/A" and float(uv) >= 6 else ""
            logger.debug("[weather] get_morning_briefing: OpenWeather")
            return (
                f"☀️ *Good morning from House-Bot!*\n\n"
                f"🌍 *{name} — Today*\n"
                f"{desc}\n\n"
                f"🌡️ Now: {current_temp}°C\n"
                f"📊 Min/Max: {t_min}°C — {t_max}°C\n"
                f"🌧️ Rain: {rain_str}\n"
                f"💨 Max wind: {wind}km/h from {dir_str}\n"
                f"☀️ UV index: {uv}{uv_warn}"
            )
        logger.warning("[weather] get_morning_briefing: OpenWeather failed, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": DEFAULT_LATITUDE, "longitude": DEFAULT_LONGITUDE,
            "daily": ["temperature_2m_max", "temperature_2m_min", "precipitation_sum",
                      "precipitation_probability_max", "wind_speed_10m_max",
                      "wind_direction_10m_dominant", "uv_index_max", "weather_code"],
            "current": ["temperature_2m", "weather_code"],
            "timezone": TIMEZONE_DEFAULT, "forecast_days": 1,
        })
        cur = data["current"]
        daily = data["daily"]
        desc = WMO_CODES.get(daily["weather_code"][0], "🌡️ Variable")
        current_temp = cur.get("temperature_2m", "N/A")
        t_max = daily["temperature_2m_max"][0]
        t_min = daily["temperature_2m_min"][0]
        rain = daily["precipitation_sum"][0]
        prob = daily["precipitation_probability_max"][0]
        wind = daily["wind_speed_10m_max"][0]
        dir_str = degrees_to_direction(daily["wind_direction_10m_dominant"][0])
        uv = daily["uv_index_max"][0]
        rain_str = (
            f"{rain}mm (prob. {prob}%) — bring an umbrella! ☂️" if rain and rain > 0
            else f"None (prob. {prob}%) 👍"
        )
        uv_warn = " — use sunscreen! 🧴" if uv and uv >= 6 else ""
        return (
            f"☀️ *Good morning from House-Bot!*\n\n"
            f"🌍 *{DEFAULT_CITY} — Today* (Open-Meteo)\n"
            f"{desc}\n\n"
            f"🌡️ Now: {current_temp}°C\n"
            f"📊 Min/Max: {t_min}°C — {t_max}°C\n"
            f"🌧️ Rain: {rain_str}\n"
            f"💨 Max wind: {wind}km/h from {dir_str}\n"
            f"☀️ UV index: {uv}{uv_warn}"
        )
    except Exception as e:
        return f"⚠️ Error fetching morning briefing: {e}"
