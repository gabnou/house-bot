import certifi
import json
import logging
import os
import unicodedata
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Use certifi bundle only if the file actually exists on disk.
_certifi_path = certifi.where()
_SSL_VERIFY = _certifi_path if os.path.isfile(_certifi_path) else True

DEFAULT_CITY = "Barcelona"
DEFAULT_LATITUDE = 41.3874
DEFAULT_LONGITUDE = 2.1686
TIMEZONE_DEFAULT = "Europe/Madrid"
MAX_HOURS = 24

# ─── AEMET (Spain national weather service) ──────────────────────────────────
AEMET_API_KEY = os.getenv("AEMET_API_KEY", "")
AEMET_BASE_URL = "https://opendata.aemet.es/opendata/api"
AEMET_COD_DEFAULT = "08019"  # Barcelona

AEMET_SKY = {
    "11": "☀️ Clear sky",          "11n": "🌙 Clear sky",
    "12": "🌤️ Mostly clear",       "12n": "🌤️ Mostly clear",
    "13": "⛅ Partly cloudy",      "13n": "⛅ Partly cloudy",
    "14": "☁️ Cloudy",              "14n": "☁️ Cloudy",
    "15": "☁️ Very cloudy",         "15n": "☁️ Very cloudy",
    "16": "☁️ Overcast",            "16n": "☁️ Overcast",
    "17": "🌥️ High clouds",         "17n": "🌥️ High clouds",
    "23": "🌦️ Mostly clear with drizzle",
    "24": "🌦️ Cloudy with drizzle",
    "25": "🌧️ Very cloudy with drizzle",
    "26": "🌧️ Overcast with drizzle",
    "33": "🌧️ Partly cloudy with rain",
    "34": "🌧️ Cloudy with rain",
    "35": "🌧️ Very cloudy with rain",
    "36": "🌧️ Overcast with rain",
    "43": "🌨️ Mostly clear with light snow",
    "44": "🌨️ Cloudy with light snow",
    "45": "❄️ Very cloudy with snow",
    "46": "❄️ Overcast with snow",
    "51": "🌨️ Rain and snow",
    "52": "🌨️ Cloudy — rain and snow",
    "53": "🌨️ Very cloudy — rain and snow",
    "54": "🌨️ Overcast — rain and snow",
    "61": "⛈️ Thunderstorm",
    "62": "⛈️ Cloudy with thunderstorm",
    "63": "⛈️ Very cloudy with thunderstorm",
    "64": "⛈️ Overcast with thunderstorm",
    "71": "⛈️ Thunderstorm with snow",
    "72": "⛈️ Cloudy — thunderstorm with snow",
    "73": "⛈️ Very cloudy — thunderstorm with snow",
    "74": "⛈️ Overcast — thunderstorm with snow",
    "81": "🌫️ Fog",
    "82": "🌫️ Dense fog",
    "83": "🌫️ Heavy fog",
    "84": "🌫️ Fog",
}

# City name aliases → Spanish (for AEMET municipality search)
_CITY_ALIAS_ES = {
    "barcellona": "barcelona",
    "valenzia": "valencia",
    "siviglia": "sevilla",
    "saragozza": "zaragoza",
    "cordoba": "cordoba",
    "palma di maiorca": "palma",
}

_municipios_cache: list = []

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


def _fetch_open_meteo(params: dict) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    resp = get_session().get(url, params=params, timeout=15, verify=_SSL_VERIFY)
    resp.raise_for_status()
    return resp.json()


def geocode(city: str):
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


# ─── AEMET helpers ───────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    """Lowercase + strip accents for fuzzy municipality name matching."""
    return "".join(
        c for c in unicodedata.normalize("NFD", s.lower())
        if unicodedata.category(c) != "Mn"
    )


def _get_municipios() -> list:
    global _municipios_cache
    if _municipios_cache:
        return _municipios_cache
    try:
        resp = get_session().get(
            f"{AEMET_BASE_URL}/maestro/municipios",
            params={"api_key": AEMET_API_KEY},
            timeout=15, verify=_SSL_VERIFY,
        )
        resp.raise_for_status()
        datos_url = resp.json().get("datos")
        if not datos_url:
            return []
        raw = get_session().get(datos_url, timeout=15, verify=_SSL_VERIFY).content.decode("latin-1")
        _municipios_cache = json.loads(raw)
        return _municipios_cache
    except Exception as e:
        logger.error("AEMET municipios error: %s", e)
        return []


def _find_municipality(city: str) -> tuple[str, str] | None:
    """Return (codmunicipio, nombre) for a Spanish city, or None."""
    if not AEMET_API_KEY:
        return None
    query = _norm(_CITY_ALIAS_ES.get(_norm(city), city))
    for m in _get_municipios():
        if _norm(m.get("nombre", "")) == query:
            cod = m["id"].replace("id", "")
            return cod, m["nombre"]
    return None


def _fetch_aemet_data(endpoint: str) -> list | None:
    """AEMET two-step fetch: get redirect URL, then fetch data (latin-1 encoded)."""
    try:
        resp = get_session().get(
            f"{AEMET_BASE_URL}{endpoint}",
            params={"api_key": AEMET_API_KEY},
            timeout=15, verify=_SSL_VERIFY,
        )
        resp.raise_for_status()
        datos_url = resp.json().get("datos")
        if not datos_url:
            return None
        raw = get_session().get(datos_url, timeout=15, verify=_SSL_VERIFY).content.decode("latin-1")
        return json.loads(raw)
    except Exception as e:
        logger.error("AEMET error %s: %s", endpoint, e)
        return None


def _aemet_desc(code: str, descripcion: str = "") -> str:
    code = str(code).strip()
    return AEMET_SKY.get(code) or (f"🌡️ {descripcion}" if descripcion else "🌡️")


def _pick_val(items: list, periodo: str, key: str = "value"):
    """Return the value for a specific period key from an AEMET list."""
    for item in items:
        if str(item.get("periodo", "")) == periodo:
            v = item.get(key)
            if v is not None and v != "":
                return v
    return None


def _best_sky(items: list) -> tuple[str, str]:
    """Pick the best sky condition for the day, preferring midday periods."""
    for pref in ("12-18", "06-12", "00-24"):
        for item in items:
            if item.get("periodo") == pref and item.get("value"):
                return item["value"], item.get("descripcion", "")
    for item in items:
        if item.get("value"):
            return item["value"], item.get("descripcion", "")
    return "", ""


def _daily_wind(wind_list: list) -> tuple:
    """Get wind speed + direction for a daily period (prefer daytime)."""
    for pref in ("06-12", "12-24", "00-24"):
        for item in wind_list:
            if item.get("periodo") == pref and item.get("direccion"):
                return item.get("velocidad", "N/A"), item.get("direccion", "—")
    for item in wind_list:
        if item.get("direccion"):
            return item.get("velocidad", "N/A"), item.get("direccion", "—")
    return "N/A", "—"


def _aemet_weather_now(codmunicipio: str, name: str) -> str | None:
    data = _fetch_aemet_data(f"/prediccion/especifica/municipio/horaria/{codmunicipio}/")
    if not data:
        return None

    tz = ZoneInfo("Europe/Madrid")
    now = datetime.now(tz)
    hour_str = f"{now.hour:02d}"
    today = now.strftime("%Y-%m-%d")

    for dia in data[0]["prediccion"]["dia"]:
        if dia["fecha"][:10] != today:
            continue

        sky_list = dia.get("estadoCielo", [])
        temp_list = dia.get("temperatura", [])
        precip_list = dia.get("precipitacion", [])
        humidity_list = dia.get("humedadRelativa", [])
        wind_list = [v for v in dia.get("vientoAndRachaMax", []) if "direccion" in v]

        hours = sorted(item["periodo"] for item in sky_list if item.get("value"))
        target = next((h for h in hours if h >= hour_str), hours[-1] if hours else None)
        if not target:
            break

        sky_item = next((x for x in sky_list if x.get("periodo") == target and x.get("value")), {})
        code = sky_item.get("value", "")
        desc = _aemet_desc(code, sky_item.get("descripcion", ""))
        temp = _pick_val(temp_list, target) or "N/A"
        precip = _pick_val(precip_list, target) or "0"
        humidity = _pick_val(humidity_list, target) or "N/A"

        wind_item = next((v for v in wind_list if v.get("periodo") == target), {})
        vel = str(wind_item.get("velocidad", ["N/A"])[0]) if wind_item.get("velocidad") else "N/A"
        dirz = wind_item.get("direccion", ["—"])[0] if wind_item.get("direccion") else "—"

        precip_str = f"{precip} mm" if precip and float(precip) > 0 else "None"

        return (
            f"🌍 *{name} — Now* (AEMET)\n\n"
            f"{desc}\n"
            f"🌡️ Temperature: {temp}°C\n"
            f"🌧️ Rain: {precip_str}\n"
            f"💧 Humidity: {humidity}%\n"
            f"💨 Wind: {vel} km/h from {dirz}"
        )
    return None


def _aemet_weather_hours(codmunicipio: str, name: str, hours: int) -> str | None:
    data = _fetch_aemet_data(f"/prediccion/especifica/municipio/horaria/{codmunicipio}/")
    if not data:
        return None

    tz = ZoneInfo("Europe/Madrid")
    now = datetime.now(tz)
    hour_str = f"{now.hour:02d}"

    lines = [f"🌍 *{name} — Next {hours} hours* (AEMET)\n"]
    count = 0
    started = False

    for dia in data[0]["prediccion"]["dia"]:
        if count >= hours:
            break
        fecha = dia["fecha"][:10]
        dia_dt = datetime.strptime(fecha, "%Y-%m-%d")
        today = now.strftime("%Y-%m-%d")

        sky_list = dia.get("estadoCielo", [])
        temp_list = dia.get("temperatura", [])
        precip_list = dia.get("precipitacion", [])
        wind_list = [v for v in dia.get("vientoAndRachaMax", []) if "direccion" in v]

        hour_slots = sorted(item["periodo"] for item in sky_list if item.get("value"))

        for h in hour_slots:
            if count >= hours:
                break
            if not started and fecha == today and h < hour_str:
                continue
            started = True

            sky_item = next((x for x in sky_list if x.get("periodo") == h and x.get("value")), {})
            code = sky_item.get("value", "")
            desc = _aemet_desc(code, sky_item.get("descripcion", ""))
            temp = _pick_val(temp_list, h) or "N/A"
            precip = _pick_val(precip_list, h) or "0"

            wind_item = next((v for v in wind_list if v.get("periodo") == h), {})
            vel = str(wind_item.get("velocidad", [""])[0]) if wind_item.get("velocidad") else "—"
            dirz = wind_item.get("direccion", ["—"])[0] if wind_item.get("direccion") else "—"

            precip_str = f"{precip}mm" if precip and float(precip) > 0 else "—"
            dt_str = dia_dt.replace(hour=int(h)).strftime("%H:%M")

            lines.append(
                f"*{dt_str}* {desc}\n"
                f"  🌡️ {temp}°C · 🌧️ {precip_str} · 💨 {vel}km/h {dirz}"
            )
            count += 1

    return "\n".join(lines) if count > 0 else None


def _aemet_weather_hours_day(codmunicipio: str, name: str, target_date: str, title: str) -> str | None:
    """Return hourly forecast for all hours of a specific date from AEMET."""
    data = _fetch_aemet_data(f"/prediccion/especifica/municipio/horaria/{codmunicipio}/")
    if not data:
        return None

    lines = [f"🌍 *{name} — Hourly {title}* (AEMET)\n"]
    count = 0

    for dia in data[0]["prediccion"]["dia"]:
        if dia["fecha"][:10] != target_date:
            continue

        dia_dt = datetime.strptime(target_date, "%Y-%m-%d")
        sky_list = dia.get("estadoCielo", [])
        temp_list = dia.get("temperatura", [])
        precip_list = dia.get("precipitacion", [])
        wind_list = [v for v in dia.get("vientoAndRachaMax", []) if "direccion" in v]

        hour_slots = sorted(item["periodo"] for item in sky_list if item.get("value"))
        for h in hour_slots:
            sky_item = next((x for x in sky_list if x.get("periodo") == h and x.get("value")), {})
            code = sky_item.get("value", "")
            desc = _aemet_desc(code, sky_item.get("descripcion", ""))
            temp = _pick_val(temp_list, h) or "N/A"
            precip = _pick_val(precip_list, h) or "0"

            wind_item = next((v for v in wind_list if v.get("periodo") == h), {})
            vel = str(wind_item.get("velocidad", [""])[0]) if wind_item.get("velocidad") else "—"
            dirz = wind_item.get("direccion", ["—"])[0] if wind_item.get("direccion") else "—"

            precip_str = f"{precip}mm" if precip and float(precip) > 0 else "—"
            dt_str = dia_dt.replace(hour=int(h)).strftime("%H:%M")

            lines.append(
                f"*{dt_str}* {desc}\n"
                f"  🌡️ {temp}°C · 🌧️ {precip_str} · 💨 {vel}km/h {dirz}"
            )
            count += 1
        break

    return "\n".join(lines) if count > 0 else None


def _aemet_weather_forecast(codmunicipio: str, name: str, days: int, offset_days: int = 0) -> str | None:
    days = min(days, 7)
    data = _fetch_aemet_data(f"/prediccion/especifica/municipio/diaria/{codmunicipio}/")
    if not data:
        return None

    forecasts = data[0]["prediccion"]["dia"]
    forecasts = forecasts[offset_days:offset_days + days]

    tz = ZoneInfo("Europe/Madrid")
    today = datetime.now(tz).date()
    tomorrow = today + timedelta(days=1)

    if days == 1 and offset_days == 0:
        title = "Today"
    elif days == 1 and offset_days == 1:
        title = "Tomorrow"
    elif days == 1 and offset_days >= 2:
        target_date = today + timedelta(days=offset_days)
        title = WEEKDAYS[target_date.weekday()]
    else:
        title = f"Next {days} days"

    lines = [f"🌍 *{name} — {title}* (AEMET)\n"]
    for dia in forecasts:
        fecha = dia["fecha"][:10]
        data_obj = datetime.strptime(fecha, "%Y-%m-%d")
        date_val = data_obj.date()
        if date_val == today:
            day_label = "Today"
        elif date_val == tomorrow:
            day_label = "Tomorrow"
        else:
            day_label = WEEKDAYS[data_obj.weekday()]

        code, desc_raw = _best_sky(dia.get("estadoCielo", []))
        desc = _aemet_desc(code, desc_raw)

        t_max = dia.get("temperatura", {}).get("maxima", "N/A")
        t_min = dia.get("temperatura", {}).get("minima", "N/A")
        uv = dia.get("uvMax", "N/A")
        prob = _pick_val(dia.get("probPrecipitacion", []), "00-24") or "0"
        vel, dirz = _daily_wind(dia.get("viento", []))

        lines.append(
            f"*{day_label}* ({fecha})\n"
            f"{desc}\n"
            f"🌡️ {t_min}°C — {t_max}°C\n"
            f"🌧️ Rain prob: {prob}% · 💨 {vel}km/h {dirz} · ☀️ UV {uv}\n"
        )
    return "\n".join(lines)


def _aemet_briefing() -> str | None:
    daily_data = _fetch_aemet_data(f"/prediccion/especifica/municipio/diaria/{AEMET_COD_DEFAULT}/")
    hourly_data = _fetch_aemet_data(f"/prediccion/especifica/municipio/horaria/{AEMET_COD_DEFAULT}/")
    if not daily_data:
        return None

    tz = ZoneInfo("Europe/Madrid")
    now = datetime.now(tz)
    hour_str = f"{now.hour:02d}"
    today = now.strftime("%Y-%m-%d")

    dia = daily_data[0]["prediccion"]["dia"][0]
    code, desc_raw = _best_sky(dia.get("estadoCielo", []))
    desc = _aemet_desc(code, desc_raw)
    t_max = dia.get("temperatura", {}).get("maxima", "N/A")
    t_min = dia.get("temperatura", {}).get("minima", "N/A")
    uv = dia.get("uvMax", "N/A")
    prob = _pick_val(dia.get("probPrecipitacion", []), "00-24") or "0"
    vel, dirz = _daily_wind(dia.get("viento", []))

    # Current temperature from hourly data
    current_temp = "N/A"
    if hourly_data:
        for h_dia in hourly_data[0]["prediccion"]["dia"]:
            if h_dia["fecha"][:10] != today:
                continue
            for t_item in h_dia.get("temperatura", []):
                if t_item.get("periodo", "") >= hour_str:
                    current_temp = t_item["value"]
                    break
            break

    prob_int = int(prob) if str(prob).isdigit() else 0
    rain_str = (
        f"Prob. {prob}% — bring an umbrella! ☂️" if prob_int > 30
        else f"Prob. {prob}% 👍"
    )
    uv_warn = " — use sunscreen! 🧴" if uv != "N/A" and int(uv) >= 6 else ""

    return (
        f"☀️ *Good morning from House-Bot!*\n\n"
        f"🌍 *{DEFAULT_CITY} — Today* (AEMET)\n"
        f"{desc}\n\n"
        f"🌡️ Now: {current_temp}°C\n"
        f"📊 Min/Max: {t_min}°C — {t_max}°C\n"
        f"🌧️ Rain: {rain_str}\n"
        f"💨 Max wind: {vel}km/h from {dirz}\n"
        f"☀️ UV index: {uv}{uv_warn}"
    )


# ─── Public interface ─────────────────────────────────────────────────────────

def get_weather_now(city: str = None) -> str:
    # Try AEMET for Spanish cities (always for default Barcelona)
    if AEMET_API_KEY:
        if not city:
            result = _aemet_weather_now(AEMET_COD_DEFAULT, DEFAULT_CITY)
        else:
            mun = _find_municipality(city)
            result = _aemet_weather_now(mun[0], mun[1]) if mun else None
        if result:
            logger.debug("[weather] get_weather_now: using AEMET (city=%s)", city or DEFAULT_CITY)
            return result
        logger.warning("[weather] get_weather_now: AEMET unavailable, falling back to Open-Meteo (city=%s)", city or DEFAULT_CITY)

    # Fallback: Open-Meteo
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."

    lat, lon, name, tz_name = geo

    try:
        data = _fetch_open_meteo({
            "latitude": lat,
            "longitude": lon,
            "current": [
                "temperature_2m",
                "precipitation",
                "precipitation_probability",
                "wind_speed_10m",
                "wind_direction_10m",
                "uv_index",
                "weather_code",
            ],
            "timezone": tz_name,
        })

        current = data["current"]
        code = current.get("weather_code", 0)
        description = WMO_CODES.get(code, "🌡️ Variable conditions")
        temp = current.get("temperature_2m", "N/A")
        rain = current.get("precipitation", 0)
        rain_prob = current.get("precipitation_probability", 0)
        wind = current.get("wind_speed_10m", "N/A")
        wind_dir = current.get("wind_direction_10m", 0)
        uv = current.get("uv_index", "N/A")

        rain_str = f"{rain} mm" if rain and rain > 0 else "None"
        dir_str = degrees_to_direction(wind_dir)

        return (
            f"🌍 *{name} — Now*\n\n"
            f"{description}\n"
            f"🌡️ Temperature: {temp}°C\n"
            f"🌧️ Rain: {rain_str} (prob. {rain_prob}%)\n"
            f"💨 Wind: {wind} km/h from {dir_str}\n"
            f"☀️ UV index: {uv}"
        )
    except Exception as e:
        return f"⚠️ Error fetching current weather: {e}"


def get_weather_hours(hours: int = 12, city: str = None) -> str:
    """Show hourly weather for the next N hours (max 24)."""
    warning = ""
    if hours > MAX_HOURS:
        warning = f"⚠️ Showing only the next {MAX_HOURS} hours (maximum supported).\n\n"
        hours = MAX_HOURS

    # Try AEMET for Spanish cities
    if AEMET_API_KEY:
        if not city:
            result = _aemet_weather_hours(AEMET_COD_DEFAULT, DEFAULT_CITY, hours)
        else:
            mun = _find_municipality(city)
            result = _aemet_weather_hours(mun[0], mun[1], hours) if mun else None
        if result:
            logger.debug("[weather] get_weather_hours: using AEMET (city=%s, hours=%s)", city or DEFAULT_CITY, hours)
            return warning + result if warning else result
        logger.warning("[weather] get_weather_hours: AEMET unavailable, falling back to Open-Meteo (city=%s)", city or DEFAULT_CITY)

    # Fallback: Open-Meteo
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."

    lat, lon, name, tz = geo

    try:
        data = _fetch_open_meteo({
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "wind_direction_10m",
                "weather_code",
            ],
            "timezone": tz,
            "forecast_days": 2,
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

            code = hourly["weather_code"][i]
            description = WMO_CODES.get(code, "🌡️")
            temp = hourly["temperature_2m"][i]
            prob = hourly["precipitation_probability"][i]
            rain = hourly["precipitation"][i]
            wind = hourly["wind_speed_10m"][i]
            dir_deg = hourly["wind_direction_10m"][i]
            dir_str = degrees_to_direction(dir_deg)
            rain_str = f"{rain}mm" if rain and rain > 0 else "—"

            lines.append(
                f"*{dt.strftime('%H:%M')}* {description}\n"
                f"  🌡️ {temp}°C · 🌧️ {prob}% ({rain_str}) · 💨 {wind}km/h {dir_str}"
            )
            count += 1

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching hourly weather: {e}"


def get_weather_hours_day(target_date: str, city: str = None) -> str:
    """Hourly forecast for all hours of a specific date (YYYY-MM-DD). Max 3 days ahead."""
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

    # Try AEMET for Spanish cities
    if AEMET_API_KEY:
        if not city:
            result = _aemet_weather_hours_day(AEMET_COD_DEFAULT, DEFAULT_CITY, target_date, title)
        else:
            mun = _find_municipality(city)
            result = _aemet_weather_hours_day(mun[0], mun[1], target_date, title) if mun else None
        if result:
            logger.debug("[weather] get_weather_hours_day: using AEMET (city=%s, date=%s)", city or DEFAULT_CITY, target_date)
            return result
        logger.warning("[weather] get_weather_hours_day: AEMET unavailable, falling back to Open-Meteo (city=%s)", city or DEFAULT_CITY)

    # Fallback: Open-Meteo
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."

    lat, lon, name, tz = geo

    try:
        data = _fetch_open_meteo({
            "latitude": lat,
            "longitude": lon,
            "hourly": [
                "temperature_2m",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "wind_direction_10m",
                "weather_code",
            ],
            "timezone": tz,
            "forecast_days": offset + 2,
        })

        hourly = data["hourly"]
        lines = [f"🌍 *{name} — Hourly {title}*\n"]
        count = 0

        for i, time_str in enumerate(hourly["time"]):
            dt = datetime.fromisoformat(time_str)
            if dt.date() != target_d:
                continue

            code = hourly["weather_code"][i]
            description = WMO_CODES.get(code, "🌡️")
            temp = hourly["temperature_2m"][i]
            prob = hourly["precipitation_probability"][i]
            rain = hourly["precipitation"][i]
            wind = hourly["wind_speed_10m"][i]
            dir_deg = hourly["wind_direction_10m"][i]
            dir_str = degrees_to_direction(dir_deg)
            rain_str = f"{rain}mm" if rain and rain > 0 else "—"

            lines.append(
                f"*{dt.strftime('%H:%M')}* {description}\n"
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

    # Try AEMET for Spanish cities
    if AEMET_API_KEY:
        if not city:
            result = _aemet_weather_forecast(AEMET_COD_DEFAULT, DEFAULT_CITY, days, offset_days)
        else:
            mun = _find_municipality(city)
            result = _aemet_weather_forecast(mun[0], mun[1], days, offset_days) if mun else None
        if result:
            logger.debug("[weather] get_weather_forecast: using AEMET (city=%s, days=%s, offset=%s)", city or DEFAULT_CITY, days, offset_days)
            return result
        logger.warning("[weather] get_weather_forecast: AEMET unavailable, falling back to Open-Meteo (city=%s)", city or DEFAULT_CITY)

    # Fallback: Open-Meteo
    geo = _resolve_city(city)
    if not geo:
        return f"⚠️ Could not find city *{city}*. Check the name and try again."

    lat, lon, name, tz = geo

    try:
        data = _fetch_open_meteo({
            "latitude": lat,
            "longitude": lon,
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "wind_direction_10m_dominant",
                "uv_index_max",
                "weather_code",
            ],
            "timezone": tz,
            "forecast_days": offset_days + days,
        })

        daily = data["daily"]
        today_d = datetime.now().date()
        tomorrow_d = today_d + timedelta(days=1)

        if days == 1 and offset_days == 0:
            title = "Today"
        elif days == 1 and offset_days == 1:
            title = "Tomorrow"
        elif days == 1 and offset_days >= 2:
            target_date = today_d + timedelta(days=offset_days)
            title = WEEKDAYS[target_date.weekday()]
        else:
            title = f"Next {days} days"

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
            code = daily["weather_code"][i]
            description = WMO_CODES.get(code, "🌡️ Variable")
            t_max = daily["temperature_2m_max"][i]
            t_min = daily["temperature_2m_min"][i]
            rain = daily["precipitation_sum"][i]
            prob = daily["precipitation_probability_max"][i]
            wind = daily["wind_speed_10m_max"][i]
            dir_deg = daily["wind_direction_10m_dominant"][i]
            dir_str = degrees_to_direction(dir_deg)
            uv = daily["uv_index_max"][i]
            rain_str = f"{rain}mm" if rain and rain > 0 else "None"

            lines.append(
                f"*{day_label}* ({date_str})\n"
                f"{description}\n"
                f"🌡️ {t_min}°C — {t_max}°C\n"
                f"🌧️ {rain_str} (prob. {prob}%) · 💨 {wind}km/h {dir_str} · ☀️ UV {uv}\n"
            )

        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error fetching forecast: {e}"


def get_morning_briefing() -> str:
    # Try AEMET first (Spain-native source for Barcelona)
    if AEMET_API_KEY:
        result = _aemet_briefing()
        if result:
            logger.debug("[weather] get_morning_briefing: using AEMET")
            return result
        logger.warning("[weather] get_morning_briefing: AEMET unavailable, falling back to Open-Meteo")

    # Fallback: Open-Meteo
    try:
        data = _fetch_open_meteo({
            "latitude": DEFAULT_LATITUDE,
            "longitude": DEFAULT_LONGITUDE,
            "daily": [
                "temperature_2m_max",
                "temperature_2m_min",
                "precipitation_sum",
                "precipitation_probability_max",
                "wind_speed_10m_max",
                "wind_direction_10m_dominant",
                "uv_index_max",
                "weather_code",
            ],
            "current": [
                "temperature_2m",
                "weather_code",
            ],
            "timezone": TIMEZONE_DEFAULT,
            "forecast_days": 1,
        })

        current = data["current"]
        daily = data["daily"]

        code_today = daily["weather_code"][0]
        description = WMO_CODES.get(code_today, "🌡️ Variable")
        current_temp = current.get("temperature_2m", "N/A")
        t_max = daily["temperature_2m_max"][0]
        t_min = daily["temperature_2m_min"][0]
        rain = daily["precipitation_sum"][0]
        prob = daily["precipitation_probability_max"][0]
        wind = daily["wind_speed_10m_max"][0]
        dir_deg = daily["wind_direction_10m_dominant"][0]
        dir_str = degrees_to_direction(dir_deg)
        uv = daily["uv_index_max"][0]

        rain_str = f"{rain}mm (prob. {prob}%) — bring an umbrella! ☂️" if rain and rain > 0 else f"None (prob. {prob}%) 👍"
        uv_warn = " — use sunscreen! 🧴" if uv and uv >= 6 else ""

        return (
            f"☀️ *Good morning from House-Bot!*\n\n"
            f"🌍 *{DEFAULT_CITY} — Today* (Open-Meteo)\n"
            f"{description}\n\n"
            f"🌡️ Now: {current_temp}°C\n"
            f"📊 Min/Max: {t_min}°C — {t_max}°C\n"
            f"🌧️ Rain: {rain_str}\n"
            f"💨 Max wind: {wind}km/h from {dir_str}\n"
            f"☀️ UV index: {uv}{uv_warn}"
        )
    except Exception as e:
        return f"⚠️ Error fetching morning briefing: {e}"
