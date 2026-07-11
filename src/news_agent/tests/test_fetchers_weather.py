"""Tests for ``news_agent.fetchers.weather`` — open-meteo weather fetcher."""

from __future__ import annotations

from news_agent.fetchers.weather import fetch_weather

GEOCODE_RESPONSE = {"results": [{"latitude": 39.9, "longitude": 116.4, "name": "Beijing"}]}
FORECAST_RESPONSE = {
    "daily": {
        "temperature_2m_max": [32.0],
        "temperature_2m_min": [22.0],
        "precipitation_sum": [0.0],
        "weathercode": [0],
    }
}


def test_fetch_weather_returns_dict_shape(httpx_mock) -> None:
    httpx_mock.add_response(
        url="https://geocoding-api.open-meteo.com/v1/search?name=Beijing&count=1&language=zh&format=json",
        json=GEOCODE_RESPONSE,
        status_code=200,
    )
    httpx_mock.add_response(
        url="https://api.open-meteo.com/v1/forecast?latitude=39.9&longitude=116.4&daily=temperature_2m_max%2Ctemperature_2m_min%2Cprecipitation_sum%2Cweathercode&timezone=auto&forecast_days=1",
        json=FORECAST_RESPONSE,
        status_code=200,
    )

    result = fetch_weather("Beijing")
    assert result is not None
    assert result["city"] == "Beijing"
    assert result["today"]["temp_max"] == 32.0
    assert result["today"]["temp_min"] == 22.0
    assert result["today"]["weather_description"] == "晴"
    assert result["source"] == "open-meteo"
    assert "fetched_at" in result


def test_fetch_weather_unknown_city(httpx_mock) -> None:
    """When geocoding returns no results, returns None."""
    httpx_mock.add_response(
        url="https://geocoding-api.open-meteo.com/v1/search?name=NonExistentCity12345&count=1&language=zh&format=json",
        json={"results": []},
        status_code=200,
    )

    result = fetch_weather("NonExistentCity12345")
    assert result is None


def test_fetch_weather_timeout(httpx_mock) -> None:
    """On httpx timeout, returns None gracefully."""
    import httpx
    httpx_mock.add_exception(
        url="https://geocoding-api.open-meteo.com/v1/search?name=Beijing&count=1&language=zh&format=json",
        exception=httpx.TimeoutException("timeout"),
    )

    result = fetch_weather("Beijing", timeout=0.1)
    assert result is None
