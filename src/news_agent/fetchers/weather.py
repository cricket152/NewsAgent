"""Task T12: open-meteo weather forecast fetcher — free, no API key, 5 s timeout.

Geocodes a city name → latitude/longitude, then fetches a single-day
forecast (max/min temperature, precipitation, weather code).  Returns
a normalised dict on success, ``None`` on any failure (caller displays
"无法获取天气").

API endpoints
-------------
* Geocoding: ``https://geocoding-api.open-meteo.com/v1/search``
* Forecast:  ``https://api.open-meteo.com/v1/forecast``
* Docs:      ``https://open-meteo.com/en/docs``

Privacy note: open-meteo requires no API key, no authentication, and
collects no personal data.  All requests are anonymous.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from news_agent.logging_setup import get_logger

logger = get_logger()

# ---------------------------------------------------------------------------
# WMO weather code → Chinese description (open-meteo reference)
# https://open-meteo.com/en/docs#weathervariables
# ---------------------------------------------------------------------------

_WMO_CODES: dict[int, str] = {
    0:  "晴",
    1:  "主要晴朗",
    2:  "部分多云",
    3:  "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "大毛毛雨",
    56: "小冻毛毛雨",
    57: "大冻毛毛雨",
    61: "小雨",
    63: "雨",
    65: "大雨",
    66: "小冻雨",
    67: "大冻雨",
    71: "小雪",
    73: "雪",
    75: "大雪",
    77: "雪粒",
    80: "小阵雨",
    81: "阵雨",
    82: "大阵雨",
    85: "小阵雪",
    86: "大阵雪",
    95: "雷暴",
    96: "雷暴伴小冰雹",
    99: "雷暴伴大冰雹",
}


def _wmo_description(code: int) -> str:
    """Map a WMO weather code to a short Chinese description."""
    return _WMO_CODES.get(code, "未知")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 with Z suffix."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _geocode(city: str, client: httpx.Client) -> tuple[float, float, str] | None:
    """Resolve *city* to (lat, lon, resolved_name) via open-meteo geocoding API.

    Returns ``None`` on any failure (timeout, HTTP error, empty results).
    """
    url = "https://geocoding-api.open-meteo.com/v1/search"
    try:
        resp = client.get(
            url,
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("weather geocode failed for %s: %s", city, exc)
        return None

    results = data.get("results")
    if not results or not isinstance(results, list):
        logger.warning("weather geocode failed for %s: no results", city)
        return None

    first = results[0]
    try:
        lat = float(first["latitude"])
        lon = float(first["longitude"])
        name = str(first.get("name", city))
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("weather geocode failed for %s: %s", city, exc)
        return None

    return lat, lon, name


def _fetch_forecast(
    lat: float, lon: float, city: str, resolved_name: str, client: httpx.Client,
) -> dict[str, Any] | None:
    """Query open-meteo forecast API and build the result dict.

    Returns ``None`` when the forecast API returns no daily data.
    """
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
        "timezone": "auto",
        "forecast_days": 1,
    }
    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("weather forecast failed for %s: %s", city, exc)
        return None

    daily = data.get("daily")
    if not daily or not isinstance(daily, dict):
        logger.warning("weather forecast failed for %s: missing daily data", city)
        return None

    # Extract first (and only) element from each daily array
    temp_max_arr = daily.get("temperature_2m_max")
    temp_min_arr = daily.get("temperature_2m_min")
    prec_arr = daily.get("precipitation_sum")
    code_arr = daily.get("weathercode")

    if not all(
        isinstance(arr, list) and len(arr) > 0
        for arr in [temp_max_arr, temp_min_arr, prec_arr, code_arr]
    ):
        logger.warning("weather forecast failed for %s: empty daily arrays", city)
        return None

    try:
        temp_max = float(temp_max_arr[0])
        temp_min = float(temp_min_arr[0])
        precip = float(prec_arr[0])
        weather_code = int(code_arr[0])
    except (ValueError, TypeError) as exc:
        logger.warning("weather forecast failed for %s: %s", city, exc)
        return None

    return {
        "city": city,
        "resolved_name": resolved_name,
        "latitude": lat,
        "longitude": lon,
        "today": {
            "temp_max": temp_max,
            "temp_min": temp_min,
            "precipitation_mm": precip,
            "weather_code": weather_code,
            "weather_description": _wmo_description(weather_code),
        },
        "fetched_at": _utcnow_iso(),
        "source": "open-meteo",
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_weather(city: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Fetch today's weather forecast for *city* from open-meteo.

    Args:
        city: City name for geocoding (e.g. ``"Beijing"``).
        timeout: HTTP timeout in seconds (default 5 s, tuned for China ISPs
            where open-meteo (hosted in Germany) may be throttled).

    Returns:
        A dict with keys ``city``, ``resolved_name``, ``latitude``,
        ``longitude``, ``today`` (nested), ``fetched_at``, and ``source``.
        Returns ``None`` on any failure — **never raises**.
    """
    with httpx.Client(timeout=httpx.Timeout(timeout)) as client:
        geo = _geocode(city, client)
        if geo is None:
            return None
        lat, lon, resolved_name = geo
        return _fetch_forecast(lat, lon, city, resolved_name, client)


# ---------------------------------------------------------------------------
# Ad-hoc smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json

    result = fetch_weather("Beijing")
    if result is None:
        print("Failed to fetch weather for Beijing")
    else:
        print("Weather result:")
        print(json.dumps(result, ensure_ascii=False, indent=2))
